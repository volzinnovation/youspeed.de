#!/usr/bin/env python3
"""Read-only structural/certificate gate for optional upcoming-path topology."""
import argparse
import json
from pathlib import Path
import sqlite3

from build_upcoming_path import GEOMETRY, PROOF


def validate(db, require=False):
    # Large validation sorts are connection-local and must not compete with a
    # local bundle/app build for temporary disk space. The DB stays read-only.
    db.execute('PRAGMA temp_store=MEMORY')
    report = {'format': 'youspeed.upcoming-path.validation.v1', 'supported': False,
              'ready': False, 'errors': [], 'counts': {}, 'failed_rows': {}}
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if 'upcoming_path_capability' not in tables:
        report['ready'] = not require
        if require:
            report['errors'].append('Missing required upcoming-path capability')
        return report
    try:
        capability = dict(db.execute('SELECT key,value FROM upcoming_path_capability'))
        expected = {'version': '1', 'completeness': 'complete', 'geometry_convention': GEOMETRY,
                    'source_node_incidence': 'complete_pbf_highway_v1',
                    'restrictions': 'all_involved_ways_stop_v1', 'motorcar_profile': 'existing_runtime_direction_v1'}
        for key, value in expected.items():
            if capability.get(key) != value:
                report['errors'].append('Unsupported/missing capability '+key)
        sign_capability = dict(db.execute('SELECT key,value FROM traffic_sign_capability'))
        if not capability.get('road_snapshot_sha256') or capability.get('road_snapshot_sha256') != sign_capability.get('road_snapshot_sha256'):
            report['errors'].append('Road source snapshot mismatch')
        required = {'upcoming_path_segment', 'upcoming_path_successor', 'upcoming_path_node', 'upcoming_path_way'}
        report['errors'] += ['Missing table: '+table for table in sorted(required-tables)]
        if report['errors']:
            return report
        report['supported'] = True
        checks = {
            'unverified_admitted_geometry': '''SELECT count(*) FROM ways w LEFT JOIN upcoming_path_way p USING(way_id)
                WHERE p.way_id IS NULL OR p.geometry_verified!=1''',
            'invalid_segment_geometry_or_permission': '''SELECT count(*) FROM upcoming_path_segment s
                LEFT JOIN traffic_sign_way_direction d USING(way_id)
                WHERE d.way_id IS NULL OR s.direction NOT IN(-1,1) OR s.start_chainage_m<0
                OR s.end_chainage_m<=s.start_chainage_m OR s.end_chainage_m>d.way_length_m+0.01
                OR abs(s.start_chainage_m)>1e12 OR abs(s.end_chainage_m)>1e12 OR abs(s.length_m)>1e12
                OR abs(s.length_m-(s.end_chainage_m-s.start_chainage_m))>0.000001
                OR s.permission_status NOT IN('allowed','blocked','unknown')
                OR (s.permission_status='allowed' AND ((s.direction=1 AND d.forward_allowed!=1)
                    OR (s.direction=-1 AND d.backward_allowed!=1)))''',
            'missing_segment_successor_or_node_audit': '''SELECT count(*) FROM upcoming_path_segment s
                LEFT JOIN upcoming_path_successor x ON x.from_segment_id=s.segment_id
                LEFT JOIN upcoming_path_node a ON a.node_id=s.start_node_id
                LEFT JOIN upcoming_path_node b ON b.node_id=s.end_node_id
                WHERE x.from_segment_id IS NULL OR a.node_id IS NULL OR b.node_id IS NULL''',
            'invalid_certified_successor': '''SELECT count(*) FROM upcoming_path_successor x
                LEFT JOIN upcoming_path_segment a ON a.segment_id=x.from_segment_id
                LEFT JOIN upcoming_path_segment b ON b.segment_id=x.to_segment_id
                LEFT JOIN upcoming_path_node n ON n.node_id=x.via_node_id
                LEFT JOIN upcoming_path_way aw ON aw.way_id=a.way_id
                LEFT JOIN upcoming_path_way bw ON bw.way_id=b.way_id
                WHERE x.status='certified' AND (a.segment_id IS NULL OR b.segment_id IS NULL
                    OR x.proof!='source_node_unbranched_unmerged_v1' OR x.via_node_id!=a.end_node_id
                    OR x.via_node_id!=b.start_node_id OR n.source_degree IS NOT 2
                    OR n.restriction_barrier IS NOT 0 OR aw.restriction_barrier IS NOT 0
                    OR bw.restriction_barrier IS NOT 0 OR a.permission_status!='allowed'
                    OR b.permission_status!='allowed' OR a.segment_id=b.segment_id
                    OR (a.way_id=b.way_id AND a.start_chainage_m=b.start_chainage_m
                        AND a.end_chainage_m=b.end_chainage_m)
                    OR (SELECT count(*) FROM upcoming_path_segment c WHERE c.start_node_id=a.end_node_id
                        AND c.permission_status='allowed' AND c.segment_id!=a.segment_id
                        AND NOT(c.way_id=a.way_id AND c.start_chainage_m=a.start_chainage_m
                            AND c.end_chainage_m=a.end_chainage_m))!=1)''',
            'invalid_stop_successor': '''SELECT count(*) FROM upcoming_path_successor x
                LEFT JOIN upcoming_path_segment a ON a.segment_id=x.from_segment_id
                WHERE a.segment_id IS NULL OR x.status NOT IN('certified','stop')
                    OR (x.status='stop' AND x.to_segment_id IS NOT NULL)''',
            'segment_coverage_gaps': '''SELECT count(*) FROM (
                SELECT s.*,lag(end_chainage_m) OVER(PARTITION BY way_id,direction ORDER BY start_chainage_m) previous_end
                FROM upcoming_path_segment s) WHERE previous_end IS NOT NULL
                AND abs(start_chainage_m-previous_end)>0.000001''',
            'segment_coverage_bounds': '''SELECT count(*) FROM (
                SELECT w.way_id,d.way_length_m,expected.direction,count(s.segment_id) segments,
                    min(s.start_chainage_m) lo,max(s.end_chainage_m) hi
                FROM ways w JOIN traffic_sign_way_direction d USING(way_id)
                CROSS JOIN (SELECT 1 direction UNION ALL SELECT -1) expected
                LEFT JOIN upcoming_path_segment s ON s.way_id=w.way_id AND s.direction=expected.direction
                WHERE d.way_length_m>0 GROUP BY w.way_id,expected.direction
                HAVING segments=0 OR lo!=0 OR abs(hi-d.way_length_m)>0.01)''',
        }
        for table in sorted(required):
            report['counts'][table] = db.execute('SELECT count(*) FROM '+table).fetchone()[0]
        for key, sql in checks.items():
            count = db.execute(sql).fetchone()[0]
            report['failed_rows'][key] = count
            if count:
                report['errors'].append(f'{key}: {count} invalid rows')
        report['successors'] = dict(db.execute('SELECT status,count(*) FROM upcoming_path_successor GROUP BY status'))
    except (sqlite3.Error, ValueError, TypeError) as error:
        report['errors'].append(str(error))
    report['ready'] = not report['errors']
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--report', '--out-json', dest='report', type=Path, required=True)
    parser.add_argument('--require', action='store_true')
    args = parser.parse_args()
    with sqlite3.connect(args.db.resolve().as_uri()+'?mode=ro', uri=True) as db:
        report = validate(db, args.require)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))
    return 0 if report['ready'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
