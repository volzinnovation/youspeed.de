import hashlib
import json
from pathlib import Path

import pytest

from scripts.tsr.applicability.extract_osm_exit_topology import extract
from scripts.tsr.applicability.topology_gap_replay import departures, replay


def source(ways):
    nodes = ''.join(f'<node id="{i}" lat="49" lon="6.{i}"/>' for i in range(1, 7))
    return (f'<osm>{nodes}{ways}</osm>').encode()


def way(identity, nodes, direction='yes', extra=''):
    tags = f'<tag k="oneway" v="{direction}"/>' if direction else ''
    refs = ''.join(f'<nd ref="{n}"/>' for n in nodes)
    return f'<way id="{identity}">{refs}<tag k="highway" v="motorway_link"/>{tags}{extra}</way>'


def result(data):
    return extract(data, source_url='https://api.openstreetmap.org/api/0.6/map?bbox=synthetic',
                   site_id='synthetic-test', fetched_at='2026-09-28T00:00:00Z')


def test_interior_node_exit_is_connected_without_splitting_way_identity():
    r = result(source(way(10, [1, 2, 3]) + way(20, [2, 4])))
    junction = r['connections'][0]
    assert junction == dict(osmNodeId='2', wayIds=['10', '20'],
                            incomingWayIds=['10'], outgoingWayIds=['10', '20'])
    assert r['ways'][0]['nodeIds'] == ['1', '2', '3']


def test_reversed_and_explicit_two_way_edges_preserve_orientation():
    r = result(source(way(10, [1, 2], '-1') + way(20, [2, 3], 'no')))
    assert {(e['wayId'], e['fromNode'], e['toNode']) for e in r['directedEdges']} == {
        ('10', '2', '1'), ('20', '2', '3'), ('20', '3', '2')}


def test_equal_coordinates_on_distinct_osm_nodes_do_not_invent_junction():
    data = source(way(10, [1, 2]) + way(20, [3, 4])).replace(b'lon="6.3"', b'lon="6.2"')
    assert result(data)['connections'] == []


@pytest.mark.parametrize('direction,extra,reason', [
    (None, '', 'explicit_direction_unavailable'),
    ('yes', '<tag k="oneway:conditional" v="no @ (Mo-Fr)"/>', 'conditional_direction_unresolved'),
])
def test_unknown_direction_never_becomes_legal_route_evidence(direction, extra, reason):
    r = result(source(way(10, [1, 2], direction, extra)))
    assert r['directedEdges'] == []
    assert r['capabilityGaps'] == [dict(wayId='10', reason=reason)]


def test_source_hash_and_counterfactual_role_cannot_claim_as_driven_truth():
    data = source(way(10, [1, 2]))
    r = result(data)
    assert r == result(data)
    assert r['source']['sha256'] == hashlib.sha256(data).hexdigest()
    assert r['isAsDrivenBundle'] is False and r['provesSignGoverningRoad'] is False
    assert r['source']['license'] == 'ODbL-1.0'


def test_missing_node_geometry_fails_before_producing_partial_graph():
    with pytest.raises(ValueError, match='Incomplete'):
        result(source(way(10, [1, 7])))


def test_lane_specific_limits_are_preserved_without_assigning_the_vehicle_lane():
    tags = '<tag k="maxspeed:lanes" v="110|110|90"/><tag k="turn:lanes" v="through|through|slight_right"/>'
    r = result(source(way(10, [1, 2], extra=tags)))
    assert r['ways'][0]['tags']['maxspeed:lanes'] == '110|110|90'
    assert r['ways'][0]['tags']['turn:lanes'] == 'through|through|slight_right'
    assert r['provesSignGoverningRoad'] is False


def test_real_brouck_departure_is_an_interior_node_not_the_nearby_emergency_access():
    path = Path(__file__).resolve().parents[2] / 'shared/tsr/applicability/fixtures/corrected-exit-topology-v1/brouck.json'
    r = json.loads(path.read_text())
    ways = {w['id']: w for w in r['ways']}
    assert '10532395' in ways['216220089']['nodeIds'][1:-1]
    assert ways['4683712']['nodeIds'][0] == '10532395'
    assert ways['4683712']['tags']['destination'] == 'Aire de Brouck'
    connection = next(c for c in r['connections'] if c['osmNodeId'] == '10532395')
    assert '216220089' in connection['incomingWayIds']
    assert '4683712' in connection['outgoingWayIds']
    assert ways['227886706']['tags']['service'] == 'emergency_access'
    assert not any(e['wayId'] == '227886706' for e in r['directedEdges'])


def test_real_issoire_lane_limit_does_not_become_the_limit_for_all_lanes():
    path = Path(__file__).resolve().parents[2] / 'shared/tsr/applicability/fixtures/corrected-exit-topology-v1/issoire.json'
    r = json.loads(path.read_text())
    ways = {w['id']: w for w in r['ways']}
    assert ways['546168660']['tags']['maxspeed'] == '110'
    assert ways['546168660']['tags']['maxspeed:lanes'] == '110|110|90'
    assert ways['546168667']['nodeIds'][0] in ways['546168660']['nodeIds']
    assert r['isAsDrivenBundle'] is False


def test_recorded_brouck_replay_restores_connection_but_never_refreshes_time_or_grants_authority():
    base = Path(__file__).resolve().parents[2] / 'shared/tsr/applicability/fixtures'
    topology = json.loads((base / 'corrected-exit-topology-v1/brouck.json').read_text())
    recorded = json.loads((base / 'fr-exit-failures-20260928-v1.json').read_text())
    before = json.dumps(recorded, sort_keys=True)
    r = replay(recorded, topology, 'clip-143435')
    assert len(r['rows']) == 49
    row = next(row for row in r['rows'] if row['wayId'] == '216220089')
    assert row['recordedBranches'] == []
    assert not any(d['toWayId'] == '4683712' for d in row['endpointOnlyCounterfactual'])
    assert any(d['toWayId'] == '4683712' for d in row['nodeIdentityCounterfactual'])
    assert row['recordedAgeMs'] == row['capturedAtMs'] - row['recordedRoadAtMs']
    assert row['nativeApplicabilityAfterCorrection'] == 'not_evaluated'
    assert json.dumps(recorded, sort_keys=True) == before
    assert r['behavior'] == 'off'


def test_topology_replay_does_not_guess_uncovered_ways_or_unknown_direction():
    topology = result(source(way(10, [1, 2, 3]) + way(20, [2, 4], None)))
    assert departures(topology, '999') == []
    assert departures(topology, '10') == []


def test_endpoint_and_internal_node_ablations_only_differ_on_internal_connection():
    topology = result(source(way(10, [1, 2, 3]) + way(20, [2, 4]) + way(30, [3, 5])))
    assert {d['toWayId'] for d in departures(topology, '10')} == {'20', '30'}
    assert {d['toWayId'] for d in departures(topology, '10', endpoints_only=True)} == {'30'}
