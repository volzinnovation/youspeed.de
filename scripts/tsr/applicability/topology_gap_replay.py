"""Replay recorded selected ways against independent corrected OSM connectivity.

This measures structural context coverage, not sign applicability. It preserves
recorded timestamps and never injects new map data into an old native decision.
No driver behavior, expected sign labels or learned features are inputs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


def departures(topology: dict, way_id: str, *, endpoints_only: bool = False) -> list[dict]:
    ways = {w['id']: w for w in topology['ways']}
    way = ways.get(way_id)
    if way is None:
        return []
    endpoints = {way['nodeIds'][0], way['nodeIds'][-1]}
    found = []
    for node in topology['connections']:
        if way_id not in node['incomingWayIds']:
            continue
        if endpoints_only and node['osmNodeId'] not in endpoints:
            continue
        for target in node['outgoingWayIds']:
            tags = ways[target]['tags']
            if target != way_id and tags.get('highway') in {'motorway_link', 'trunk_link'}:
                found.append({'fromWayId': way_id, 'toWayId': target,
                              'osmNodeId': node['osmNodeId'],
                              'interiorNode': node['osmNodeId'] not in endpoints})
    return sorted(found, key=lambda row: (row['osmNodeId'], row['toWayId']))


def replay(recorded: dict, topology: dict, scenario_id: str) -> dict:
    scenario = next(s for s in recorded['scenarios'] if s['id'] == scenario_id)
    known_ways = {w['id'] for w in topology['ways']}
    rows = []
    for batch in scenario['batches']:
        road = batch.get('road') or {}
        way_id = road.get('wayId')
        road_time = road.get('capturedAtMs')
        age = None if road_time is None else batch['capturedAtMs'] - road_time
        covered = way_id in known_ways
        rows.append({
            'frameId': batch['frameId'], 'wayId': way_id,
            'capturedAtMs': batch['capturedAtMs'], 'recordedRoadAtMs': road_time,
            'recordedAgeMs': age,
            'recordedContextFresh': age is not None and 0 <= age <= 1500,
            'recordedBranches': road.get('branches', []),
            'correctedExtractCoversSelectedWay': covered,
            'endpointOnlyCounterfactual': departures(topology, way_id, endpoints_only=True),
            'nodeIdentityCounterfactual': departures(topology, way_id),
            'nativeApplicabilityAfterCorrection': 'not_evaluated',
        })
    return {
        'schemaVersion': 1, 'scenarioId': scenario_id,
        'experiment': 'structural_context_coverage_only',
        'behavior': 'off', 'learnedGeometry': 'not_run',
        'isAsDrivenBundle': False, 'rows': rows,
        'summary': {
            'recordedFrames': len(rows),
            'coveredFrames': sum(r['correctedExtractCoversSelectedWay'] for r in rows),
            'staleOrMissingFrames': sum(not r['recordedContextFresh'] for r in rows),
            'recordedFramesWithBranches': sum(bool(r['recordedBranches']) for r in rows),
            'endpointCounterfactualFramesWithDeparture': sum(bool(r['endpointOnlyCounterfactual']) for r in rows),
            'nodeIdentityCounterfactualFramesWithDeparture': sum(bool(r['nodeIdentityCounterfactual']) for r in rows),
        },
        'limitations': [
            'Current topology differs from the recorded bundle; this is a counterfactual.',
            'Connection somewhere on the selected way does not prove proximity, sign road or ego lane.',
            'No capture position, camera calibration or sign support is fabricated.',
            'Corrected topology does not refresh old fixes or resolve physical-sign identity.',
            'No false-activation, authority, passage or latency improvement is measured.',
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--recorded', required=True, type=Path)
    parser.add_argument('--topology', required=True, type=Path)
    parser.add_argument('--scenario', required=True)
    parser.add_argument('--output', required=True, type=Path)
    args = parser.parse_args()
    report = replay(json.loads(args.recorded.read_text()),
                    json.loads(args.topology.read_text()), args.scenario)
    report['inputs'] = {name: {'path': str(path), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest()}
                        for name, path in [('recorded', args.recorded), ('topology', args.topology)]}
    report['runnerSha256'] = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report['summary'], sort_keys=True))


if __name__ == '__main__':
    main()
