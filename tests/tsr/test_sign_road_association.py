import copy
import importlib.util
import json
from pathlib import Path
import sqlite3
import sys

import pytest

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts/tsr/collection"


def load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    sys.modules[name] = result
    spec.loader.exec_module(result)
    return result


m = load("sign_road_association")
extractor = load("extract_candidate_road_graph")
FRAME = {"frame_id": "synthetic", "axes": "east_north", "units": "metres",
         "provenance": {"reference": "synthetic", "sha256": "a" * 64}}


def road(identity="1", points=None, nodes=None, direction="forward", error=0):
    return {"way_id": identity, "points_en_m": points or [[-10, 0], [10, 0]],
            "node_ids": nodes or ["a", "b"], "direction": direction,
            "geometry_error_bound_m": error, "tags": {"highway": "primary"}}


def graph(*roads):
    return {"local_frame": FRAME, "source": {"sha256": "b" * 64,
            "geometry_bounds_known": True, "topology": "original_osm_node_ids"}, "roads": list(roads)}


def solver(bounded=True, clipped=False):
    return {"local_frame": FRAME, "estimate_en_m": [0, 0],
            "feasible_region": {"vertices_en_m": [[-1, -1], [1, -1], [1, 1], [-1, 1]],
                                "bounds_known": bounded, "range_clipped": clipped}}


def test_projection_uses_consecutive_nodes_not_two_nearest_vertices():
    result = m.closest_segment([0, 1], [[0, 0], [100, 0], [100, 100], [0, 2]])
    assert result["distance_m"] == pytest.approx(1)
    assert result["projection_en_m"] == [0, 0]
    assert result["segment_index"] == 0


def test_projection_side_direction_and_endpoint_clamping():
    east = m.segment_projection([5, 2], [0, 0], [10, 0])
    assert east["fraction"] == .5
    assert east["signed_left_offset_m"] == 2
    assert east["tangent_degrees"] == 90
    reverse = m.segment_projection([5, 2], [10, 0], [0, 0])
    assert reverse["signed_left_offset_m"] == -2
    assert reverse["tangent_degrees"] == 270
    beyond = m.segment_projection([15, 2], [0, 0], [10, 0])
    assert beyond["fraction"] == 1 and beyond["unclamped_fraction"] == 1.5
    assert beyond["distance_m"] == pytest.approx(29**.5)


def test_repeated_nodes_skip_zero_segments_without_changing_original_index():
    result = m.closest_segment([5, 1], [[0, 0], [0, 0], [10, 0]])
    assert result["segment_index"] == 1 and result["along_way_m"] == 5
    with pytest.raises(ValueError, match="nonzero"):
        m.closest_segment([0, 0], [[0, 0], [0, 0]])


def test_bend_tangent_tie_is_explicitly_ambiguous():
    r = road(points=[[-10, 0], [0, 0], [0, 10]], nodes=["a", "b", "c"])
    result = m.associate_roads(solver(), graph(r), search_radius_m=0)
    projection = result["roads"][0]["nominal_projection"]
    assert projection["tangent_ambiguous"] is True
    assert result["roads"][0]["permitted_local_headings_degrees"] == []


def test_polygon_distance_detects_crossing_without_any_node_inside():
    polygon = [[-1, -1], [1, -1], [1, 1], [-1, 1]]
    assert m.region_road_distance(polygon, [[-100, 0], [100, 0]]) == 0
    assert m.region_road_distance(polygon, [[-100, 4], [100, 4]]) == 3


def test_parallel_roads_remain_candidates_even_when_one_nominally_closer():
    result = m.associate_roads(solver(), graph(road(), road("2", [[-10, 2], [10, 2]])), search_radius_m=2)
    assert result["candidate_way_ids"] == ["1", "2"]
    assert result["status"] == "multiple_enumerated_candidates"
    assert result["proves_applicability"] is False


@pytest.mark.parametrize("bounded,clipped,error,source_bound", [(False, False, 0, True), (True, True, 0, True), (True, False, None, True), (True, False, 0, False)])
def test_unknown_bounds_never_discard_enumerated_distant_candidate(bounded, clipped, error, source_bound):
    g = graph(road("far", [[-10, 500], [10, 500]], error=error))
    g["source"]["geometry_bounds_known"] = source_bound
    result = m.associate_roads(solver(bounded, clipped), g, search_radius_m=2)
    assert result["candidate_way_ids"] == ["far"]
    assert result["status"] == "uncertainty_unbounded"


def test_bounded_distance_uses_region_and_geometry_error_not_only_point_estimate():
    result = m.associate_roads(solver(), graph(road("2", [[-10, 5], [10, 5]], error=2)), search_radius_m=2)
    assert result["candidate_way_ids"] == ["2"]  # inclusive 4 m region distance
    result = m.associate_roads(solver(), graph(road("2", [[-10, 5.01], [10, 5.01]], error=2)), search_radius_m=2)
    assert result["candidate_way_ids"] == []


def test_same_way_and_directed_branch_preserve_distinction_from_sign_relevance():
    g = graph(road(), road("2", [[10, 0], [10, 20]], nodes=["b", "c"]))
    path = {"source_sha256": "b" * 64, "way_ids": ["1"], "direction_by_way": {"1": "forward"}}
    rows = m.associate_roads(solver(), g, path)["roads"]
    assert rows[0]["travelled_path"]["relation"] == "same_mapped_way"
    assert rows[1]["travelled_path"]["relation"] == "directed_adjacent_candidate"
    assert rows[1]["travelled_path"]["shared_node_ids"] == ["b"]
    path["direction_by_way"]["1"] = "reverse"
    assert m.associate_roads(solver(), g, path)["roads"][0]["travelled_path"]["direction_compatibility"] == "opposite_explicit_direction"


def test_internal_node_connection_uses_ids_and_overpass_coordinates_do_not_connect():
    a = road(points=[[-10, 0], [0, 0], [10, 0]], nodes=["a", "b", "c"])
    b = road("2", [[0, 0], [0, 20]], nodes=["b", "d"])
    p = {"source_sha256": "b" * 64, "way_ids": ["1"], "direction_by_way": {"1": "forward"}}
    assert m.associate_roads(solver(), graph(a, b), p)["roads"][1]["travelled_path"]["relation"] == "directed_adjacent_candidate"
    b["node_ids"] = ["bridge_node", "d"]
    assert m.associate_roads(solver(), graph(a, b), p)["roads"][1]["travelled_path"]["relation"] == "no_direct_shared_node"


def test_unknown_road_direction_and_map_mismatch_remain_unknown():
    r = road(direction="unknown")
    p = {"source_sha256": "b" * 64, "way_ids": ["1"], "direction_by_way": {"1": "forward"}}
    row = m.associate_roads(solver(), graph(r), p)["roads"][0]
    assert row["travelled_path"]["direction_compatibility"] == "unknown"
    assert row["permitted_local_headings_degrees"] == []
    p["source_sha256"] = "c" * 64
    assert m.associate_roads(solver(), graph(r), p)["roads"][0]["travelled_path"]["relation"] == "unknown"


def test_impossible_or_unknown_path_direction_cannot_assert_legal_branch():
    for direction in ["reverse", "unknown"]:
        g = graph(road(direction=direction), road("2", [[10, 0], [10, 20]], nodes=["b", "c"]))
        path = {"source_sha256": "b" * 64, "way_ids": ["1"], "direction_by_way": {"1": "forward"}}
        row = m.associate_roads(solver(), g, path)["roads"][1]
        assert row["travelled_path"]["direction_compatibility"] == "unknown"


def test_bidirectional_legal_road_does_not_invent_bidirectional_actual_travel():
    g = graph(road(direction="both"), road("2", [[-10, 0], [-10, 20]], nodes=["a", "c"]))
    path = {"source_sha256": "b" * 64, "way_ids": ["1"], "direction_by_way": {"1": "both"}}
    assert m.associate_roads(solver(), g, path)["roads"][1]["travelled_path"]["direction_compatibility"] == "unknown"


def test_no_count_can_imply_unproved_candidate_population_completeness():
    g = graph(road())
    g["extraction"] = {"bounds_wgs84": [[8, 48, 8.0001, 48.0001]]}
    result = m.associate_roads(solver(), g)
    assert result["candidate_population_complete_for_region"] is False
    assert result["extraction_scope"] == g["extraction"]
    assert result["status"] == "one_enumerated_candidate"


def test_degenerate_region_does_not_gain_a_false_finite_bound():
    s = solver()
    s["feasible_region"]["vertices_en_m"] = [[0, 0], [1, 0], [2, 0]]
    result = m.associate_roads(s, graph(road("far", [[-10, 100], [10, 100]])), search_radius_m=0)
    assert result["status"] == "uncertainty_unbounded" and result["candidate_way_ids"] == ["far"]


def test_mismatched_frame_and_nonfinite_input_fail_closed():
    s = copy.deepcopy(solver())
    s["local_frame"]["frame_id"] = "different"
    with pytest.raises(ValueError, match="frame_mismatch"):
        m.associate_roads(s, graph(road()))
    for invalid in [True, float("nan"), float("inf")]:
        s = solver()
        s["estimate_en_m"] = [invalid, 0]
        with pytest.raises(ValueError, match="coordinate"):
            m.associate_roads(s, graph(road()))


def test_projection_units_axes_and_range_guard():
    assert m.local_en([48, 8], [48, 8]) == [0, 0]
    assert m.local_en([48.001, 8], [48, 8])[1] == pytest.approx(111.19508023)
    with pytest.raises(ValueError, match="50km"):
        m.local_en([49, 8], [48, 8])


def sqlite_fixture(path):
    with sqlite3.connect(path) as c:
        c.executescript("CREATE TABLE ways(way_id INTEGER PRIMARY KEY,highway TEXT,ref TEXT,street_name TEXT); CREATE TABLE way_geom(way_id INTEGER PRIMARY KEY,points_json TEXT); CREATE VIRTUAL TABLE ways_rtree USING rtree(way_id,min_lon,max_lon,min_lat,max_lat);")
        c.execute("INSERT INTO ways VALUES(1,'service',null,null)")
        c.execute("INSERT INTO way_geom VALUES(1,?)", (json.dumps([[48, 8], [48, 8.001]]),))
        c.execute("INSERT INTO ways_rtree VALUES(1,8,8.001,48,48)")


def test_sqlite_adapter_hash_binding_no_writes_and_degraded_labels(tmp_path):
    path = tmp_path / "roads.sqlite"
    sqlite_fixture(path)
    before = m.sha256(path)
    result = m.load_candidate_roads_sqlite(path, [7.99, 47.99, 8.01, 48.01], before)
    assert m.sha256(path) == before
    assert result["roads"][0]["direction"] == "unknown"
    assert result["roads"][0]["geometry_error_bound_m"] is None
    assert result["source"]["topology"] == "coordinate_endpoints_only"
    assert not result["source"]["is_as_driven"]
    with pytest.raises(ValueError, match="hash_mismatch"):
        m.load_candidate_roads_sqlite(path, [7.99, 47.99, 8.01, 48.01], "0" * 64)


def xml_fixture(path):
    path.write_text('''<osm version="0.6"><node id="1" lat="48" lon="8"/><node id="2" lat="48" lon="8.001"/><node id="3" lat="48.001" lon="8.001"/>
    <way id="1"><nd ref="1"/><nd ref="2"/><tag k="highway" v="primary"/><tag k="oneway" v="yes"/></way>
    <way id="2"><nd ref="2"/><nd ref="3"/><tag k="highway" v="service"/><tag k="oneway" v="-1"/><tag k="oneway:conditional" v="yes @ (Mo-Fr)"/></way></osm>''')


def test_original_graph_retains_all_nodes_and_explicit_uncertain_direction(tmp_path):
    path = tmp_path / "map.osm"
    xml_fixture(path)
    result = extractor.extract_graph(path, [[7.999, 47.999, 8.002, 48.002]], m.sha256(path))
    assert result["roads"][0]["node_ids"] == ["1", "2"]
    assert result["roads"][0]["direction"] == "forward"
    assert result["roads"][1]["direction"] == "unknown"
    assert result["source"]["geometry_bounds_known"] is True
    assert result["extraction"]["legal_routing_complete"] is False
    projected = m.project_graph(result, [48, 8], FRAME)
    assert projected["local_frame"] == FRAME
    assert projected["roads"][0]["points_en_m"][0] == [0, 0]


def test_whole_crossing_segment_kept_even_when_vertices_outside_query(tmp_path):
    path = tmp_path / "map.osm"
    xml_fixture(path)
    result = extractor.extract_graph(path, [[8.0004, 47.9999, 8.0006, 48.0001]], m.sha256(path))
    assert [r["way_id"] for r in result["roads"]] == ["1"]
    assert len(result["roads"][0]["points_lat_lon"]) == 2


def test_extractor_never_returns_silent_partial_graph(tmp_path):
    path = tmp_path / "map.osm"
    xml_fixture(path)
    with pytest.raises(ValueError, match="cap_exceeded"):
        extractor.extract_graph(path, [[7.999, 47.999, 8.002, 48.002]], m.sha256(path), max_ways=1)
    path.write_text(path.read_text().replace('<node id="3" lat="48.001" lon="8.001"/>', ''))
    with pytest.raises(ValueError, match="missing_referenced_node"):
        extractor.extract_graph(path, [[7.999, 47.999, 8.002, 48.002]], m.sha256(path))


def test_file_backed_pbf_reader_matches_xml_fixture(tmp_path):
    osmium = pytest.importorskip("osmium")
    path = tmp_path / "map.osm"
    xml_fixture(path)
    pbf = tmp_path / "map.osm.pbf"
    with osmium.SimpleWriter(str(pbf)) as writer:
        class Copy(osmium.SimpleHandler):
            def node(self, node):
                writer.add_node(node)

            def way(self, way):
                writer.add_way(way)
        Copy().apply_file(str(path))
    bounds = [[7.999, 47.999, 8.002, 48.002]]
    a = extractor.extract_graph(path, bounds, m.sha256(path))
    b = extractor.extract_graph(pbf, bounds, m.sha256(pbf))
    assert a["roads"] == b["roads"]
