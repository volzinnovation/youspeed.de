#!/usr/bin/env python3
"""Export small real-bundle reader fixtures, never an installable road bundle.

The input is read-only. Cases contain a certified cross-way approach whose first
physical primary event has a unique numeric offer. Native tests use this to
exercise the actual source rows without copying a multi-gigabyte DB to a phone.
"""
import argparse
import json
import math
from pathlib import Path
import sqlite3


def distance(a, b):
    p, q = math.radians(a[0]), math.radians(b[0])
    x = math.sin((q-p)/2)**2 + math.cos(p)*math.cos(q)*math.sin(math.radians(b[1]-a[1])/2)**2
    return 12742000 * math.asin(min(1, math.sqrt(x)))


def pose(points, station, direction):
    progress = 0.0
    for a, b in zip(points, points[1:]):
        length = distance(a, b)
        if length > 0 and progress+length >= station:
            t = max(0, min(1, (station-progress)/length))
            lat, lon = a[0]+t*(b[0]-a[0]), a[1]+t*(b[1]-a[1])
            heading = math.degrees(math.atan2((b[1]-a[1])*math.cos(math.radians(lat)), b[0]-a[0]))
            return lat, lon, (heading+(180 if direction < 0 else 0)) % 360
        progress += length
    raise ValueError('Station lies outside source geometry')


def groups(db, way):
    return {row[0] for row in db.execute("""SELECT m.continuity_group_id
        FROM way_continuity_membership m JOIN way_continuity_group g USING(continuity_group_id)
        WHERE m.way_id=? AND g.continuity_kind='route_relation_connected'""", (way,))}


def trace(db, initial, chainage):
    path, events, visited = [], [], set()
    segment = dict(initial)
    common = groups(db, segment['way_id'])
    entry = segment['start_chainage_m'] if segment['direction'] == 1 else segment['end_chainage_m']
    entry_distance = -segment['direction']*(chainage-entry)
    seen_events = set()
    for _ in range(32):
        if segment['segment_id'] in visited or segment['permission_status'] != 'allowed':
            break
        visited.add(segment['segment_id'])
        common &= groups(db, segment['way_id'])
        if not common:
            break
        path.append(segment)
        entry = segment['start_chainage_m'] if segment['direction'] == 1 else segment['end_chainage_m']
        for row in db.execute("""SELECT a.*,s.kind,s.numeric_value,s.unit,s.parameter_status
            FROM traffic_sign_association a JOIN traffic_sign_runtime s USING(sign_id)
            WHERE a.way_id=? AND a.direction=? AND a.station_chainage_m BETWEEN ? AND ?
              AND (s.kind IN('speed_limit','speed_limit_end','settlement_boundary') OR s.sign_code='DE:282')""",
                (segment['way_id'], segment['direction'], segment['start_chainage_m'], segment['end_chainage_m'])):
            remaining = entry_distance+segment['direction']*(row['station_chainage_m']-entry)
            if 0 < remaining <= 300 and row['sign_id'] not in seen_events:
                events.append((remaining, dict(row)))
                seen_events.add(row['sign_id'])
        entry_distance += segment['length_m']
        if entry_distance >= 300:
            break
        successor = db.execute("""SELECT s.* FROM upcoming_path_successor x
            JOIN upcoming_path_segment s ON s.segment_id=x.to_segment_id
            WHERE x.from_segment_id=? AND x.status='certified'
              AND x.proof='source_node_unbranched_unmerged_v1'""", (segment['segment_id'],)).fetchone()
        if successor is None:
            break
        segment = dict(successor)
    return path, sorted(events, key=lambda item: (item[0], item[1]['sign_id']))


def cases(db, count):
    seeds = db.execute("""SELECT f.*,a.sign_id target_sign FROM upcoming_path_successor x
        JOIN upcoming_path_segment f ON f.segment_id=x.from_segment_id
        JOIN upcoming_path_segment t ON t.segment_id=x.to_segment_id
        JOIN traffic_sign_association a ON a.way_id=t.way_id AND a.direction=t.direction
          AND a.station_chainage_m BETWEEN t.start_chainage_m AND t.end_chainage_m
        JOIN traffic_sign_runtime s USING(sign_id)
        WHERE x.status='certified' AND f.way_id!=t.way_id
          AND f.permission_status='allowed' AND t.permission_status='allowed'
          AND a.status='accepted' AND s.kind='speed_limit' AND s.unit='km/h'
          AND s.parameter_status='parsed_source_value' AND s.numeric_value BETWEEN 1 AND 129
          AND t.direction*(a.station_chainage_m-CASE WHEN t.direction=1 THEN t.start_chainage_m ELSE t.end_chainage_m END)<200
        ORDER BY a.sign_id,f.segment_id LIMIT 2000""")
    result, selected_ways, used = [], set(), set()
    for seed in seeds:
        if seed['way_id'] in used:
            continue
        gap = min(80, seed['length_m']/2)
        if gap < 5:
            continue
        chainage = seed['end_chainage_m']-gap if seed['direction'] == 1 else seed['start_chainage_m']+gap
        path, events = trace(db, seed, chainage)
        if len(path) < 2 or not events:
            continue
        remaining, event = events[0]
        if event['sign_id'] != seed['target_sign'] or event['status'] != 'accepted':
            continue
        # No nearby co-station ambiguity, even outside the first exact point.
        if len(events) > 1 and abs(events[1][0]-remaining) <= 1:
            continue
        speed = event['numeric_value']
        if event['kind'] != 'speed_limit' or speed is None or not math.isfinite(speed) or speed != int(speed):
            continue
        station, direction = event['station_chainage_m'], event['direction']
        rules = list(db.execute("""SELECT * FROM traffic_sign_way_rule WHERE way_id=? AND direction=?
            AND ((direction=1 AND start_chainage_m<=? AND end_chainage_m>?)
              OR (direction=-1 AND start_chainage_m<? AND end_chainage_m>=?))""",
                (event['way_id'], direction, station, station, station, station)))
        if len(rules) != 1:
            continue
        rule = rules[0]
        if (rule['sign_id'] != event['sign_id'] or rule['association_status'] != 'accepted'
                or rule['lane_scope'] != 'all' or rule['speed_kmh'] != speed
                or abs(rule['station_chainage_m']-station) > 0.000001):
            continue
        points = json.loads(db.execute('SELECT points_json FROM way_geom WHERE way_id=?', (seed['way_id'],)).fetchone()[0])
        lat, lon, heading = pose(points, chainage, seed['direction'])
        result.append(dict(id=f'bw-cross-way-{len(result)+1}', wayID=str(seed['way_id']), direction=seed['direction'],
            chainageM=chainage, points=points, lat=lat, lon=lon, headingDeg=heading,
            relationGroupIDs=sorted(groups(db, seed['way_id'])), expectedSignID=event['sign_id'],
            expectedSpeedKmh=int(speed), expectedDistanceM=remaining, expectedOriginWayID=str(event['way_id'])))
        selected_ways.update(row['way_id'] for row in path)
        used.add(seed['way_id'])
        if len(result) >= count:
            break
    if len(result) != count:
        raise ValueError(f'Only {len(result)} certified source cases found; requested {count}')
    return result, selected_ways


def copy_rows(source, target, table, where='', parameters=()):
    schema = source.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone()
    if schema is None:
        return
    target.execute(schema[0])
    cursor = source.execute('SELECT * FROM '+table+(' WHERE '+where if where else ''), tuple(parameters))
    insert = 'INSERT INTO '+table+' VALUES('+','.join('?' for _ in cursor.description)+')'
    target.executemany(insert, (tuple(row) for row in cursor))


def export(db_path, output, count=5):
    output.mkdir(parents=True, exist_ok=True)
    fixture = output/'probe.sqlite'
    if fixture.exists():
        raise ValueError('Refusing to replace existing probe.sqlite; use a new output directory')
    with sqlite3.connect(db_path.resolve().as_uri()+'?mode=ro', uri=True) as source:
        source.row_factory = sqlite3.Row
        examples, ways = cases(source, count)
        marks = ','.join('?' for _ in ways)
        way_filter = 'way_id IN('+marks+')'
        with sqlite3.connect(fixture) as target:
            for table in ('metadata','traffic_sign_capability','upcoming_path_capability','traffic_sign_source'):
                copy_rows(source,target,table)
            for table in ('ways','way_geom','traffic_sign_way_direction','traffic_sign_way_rule',
                          'traffic_sign_association','upcoming_path_way','upcoming_path_segment','way_continuity_membership'):
                copy_rows(source,target,table,way_filter,ways)
            sign_filter = 'sign_id IN(SELECT sign_id FROM traffic_sign_association WHERE '+way_filter+') OR sign_id IN(SELECT sign_id FROM traffic_sign_way_rule WHERE '+way_filter+')'
            copy_rows(source,target,'traffic_sign_runtime',sign_filter,(*ways,*ways))
            copy_rows(source,target,'way_continuity_group','continuity_group_id IN(SELECT continuity_group_id FROM way_continuity_membership WHERE '+way_filter+')',ways)
            copy_rows(source,target,'upcoming_path_successor','from_segment_id IN(SELECT segment_id FROM upcoming_path_segment WHERE '+way_filter+')',ways)
            copy_rows(source,target,'upcoming_path_node','node_id IN(SELECT start_node_id FROM upcoming_path_segment WHERE '+way_filter+') OR node_id IN(SELECT end_node_id FROM upcoming_path_segment WHERE '+way_filter+')',(*ways,*ways))
            # Mirror the production nonunique indexes on the copied query tables.
            for row in source.execute("SELECT sql FROM sqlite_master WHERE type='index' AND sql IS NOT NULL"):
                try:
                    target.execute(row[0])
                except sqlite3.OperationalError as error:
                    if 'no such table' not in str(error):
                        raise
        payload = dict(format='youspeed.upcoming.bw-probe.v1', source_db=str(db_path),
            source_road_sha256=dict(source.execute('SELECT key,value FROM upcoming_path_capability'))['road_snapshot_sha256'],
            description='Read-only source-row subset for native reader tests. Not an installable or globally complete road bundle.', cases=examples)
        (output/'cases.json').write_text(json.dumps(payload,indent=2)+'\n')
    return payload


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',type=Path,required=True)
    parser.add_argument('--out-dir',type=Path,required=True)
    parser.add_argument('--count',type=int,default=5)
    args=parser.parse_args()
    if not 1 <= args.count <= 50:
        parser.error('--count must be between 1 and 50')
    report=export(args.db,args.out_dir,args.count)
    print(json.dumps(dict(cases=len(report['cases']),fixture=str(args.out_dir/'probe.sqlite')),indent=2))


if __name__=='__main__':
    main()
