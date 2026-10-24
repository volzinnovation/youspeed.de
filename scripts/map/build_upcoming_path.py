#!/usr/bin/env python3
"""Build conservative, source-node-proven offline lookahead in an explicit DB.

The caller supplies a disposable/new output database. This never publishes or
downloads data, changes speed-reference policy, or edits the source PBF.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import sys

import osmium

from build_traffic_sign_runtime import way_direction

ROOT = Path(__file__).resolve().parents[2]
GEOMETRY = 'source_vertices_spherical_6371000m_v1'
PROOF = 'source_node_unbranched_unmerged_v1'
TABLES = ('upcoming_path_successor', 'upcoming_path_segment', 'upcoming_path_node',
          'upcoming_path_way', 'upcoming_path_capability')


def distance(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    value = math.sin((lat2-lat1)/2)**2 + math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6371000.0 * 2 * math.asin(min(1.0, math.sqrt(value)))


def sha256(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as source:
        while chunk := source.read(1024*1024):
            value.update(chunk)
    return value.hexdigest()


class Incidence(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.degree = {}
        self.restricted_ways = set()
        self.barrier_nodes = set()
        self.ways = 0
        self.restrictions = 0
        self.nodes_seen = 0

    def node(self, node):
        self.nodes_seen += 1
        if self.nodes_seen % 10000000 == 0:
            print(f'Upcoming path: inspected {self.nodes_seen} source nodes', flush=True)
        if not node.tags:
            return
        if any(key.split(':', 1)[0] in ('barrier', 'access', 'vehicle', 'motor_vehicle', 'motorcar', 'oneway')
               for key, _ in node.tags):
            self.barrier_nodes.add(int(node.id))

    def add_way(self, refs):
        for index, node in enumerate(refs):
            degree = int(index > 0) + int(index+1 < len(refs))
            self.degree[node] = min(3, self.degree.get(node, 0) + degree)
        self.ways += 1

    def way(self, way):
        if way.tags.get('highway'):
            self.add_way([int(n.ref) for n in way.nodes])

    def relation(self, relation):
        if relation.tags.get('type') != 'restriction' and not any(k.startswith('restriction') for k, _ in relation.tags):
            return
        self.restrictions += 1
        for member in relation.members:
            if member.type == 'w':
                self.restricted_ways.add(int(member.ref))
            elif member.type == 'n':
                self.barrier_nodes.add(int(member.ref))


def permissions(tags, highway, stored):
    """Unknown access semantics cannot certify a successor for a motorcar."""
    _, forward, backward = way_direction(tags, highway)
    access_keys = ('access', 'vehicle', 'motor_vehicle', 'motorcar')
    unknown = any('conditional' in k and k.startswith(('oneway', *access_keys)) for k in tags)
    unknown |= any(tags.get(key+suffix, '').lower() not in ('', 'yes', 'no', 'designated', 'permissive')
                   for key in access_keys for suffix in ('', ':forward', ':backward'))
    unknown |= (forward, backward) != tuple(stored)
    if unknown:
        return {1: 'unknown', -1: 'unknown'}
    return {1: 'allowed' if forward else 'blocked', -1: 'allowed' if backward else 'blocked'}


def insert_way(db, incidence, way_id, refs, points, tags, stored, stored_points, stored_length):
    """Insert a source-verified way; exposed separately for small contract tests."""
    valid = len(refs) == len(points) == len(stored_points) and len(refs) >= 2
    valid = valid and all(len(a) == 2 and all(math.isfinite(v) for v in a) and
                         max(abs(a[i]-b[i]) for i in (0, 1)) <= 1e-7
                         for a, b in zip(points, stored_points))
    chainage = [0.0]
    for a, b in zip(points, points[1:]):
        chainage.append(chainage[-1]+distance(a, b))
    valid = valid and math.isfinite(stored_length) and abs(chainage[-1]-stored_length) <= 0.01
    restricted = int(way_id in incidence.restricted_ways)
    db.execute('INSERT INTO upcoming_path_way VALUES(?,?,?)', (way_id, restricted, int(valid)))
    if not valid:
        return False
    repeats = {node for node, count in Counter(refs).items() if count > 1}
    cuts = [0] + [i for i in range(1, len(refs)-1)
                  if incidence.degree.get(refs[i], 0) != 2 or refs[i] in repeats
                  or refs[i] in incidence.barrier_nodes] + [len(refs)-1]
    status = permissions(tags, tags.get('highway'), stored)
    rows, nodes = [], set()
    for index, (first, last) in enumerate(zip(cuts, cuts[1:])):
        if index >= 524288 or way_id <= 0 or way_id > (2**63-1048576)//1048576:
            raise ValueError('Source way cannot be represented by deterministic 64-bit segment IDs')
        length = chainage[last]-chainage[first]
        if length <= 0:
            continue
        for direction in (1, -1):
            start, end = (refs[first], refs[last]) if direction == 1 else (refs[last], refs[first])
            segment_id = way_id*1048576+index*2+(0 if direction == 1 else 1)
            rows.append((segment_id, way_id, direction, chainage[first], chainage[last], start, end, length, status[direction]))
        nodes.update((refs[first], refs[last]))
    db.executemany('INSERT INTO upcoming_path_segment VALUES(?,?,?,?,?,?,?,?,?)', rows)
    db.executemany('INSERT OR IGNORE INTO upcoming_path_node VALUES(?,?,?)',
                   ((node, incidence.degree.get(node, 0), int(node in incidence.barrier_nodes)) for node in nodes))
    return True


class Segments(osmium.SimpleHandler):
    def __init__(self, db, incidence):
        super().__init__()
        self.db, self.incidence = db, incidence
        self.admitted = {row[0] for row in db.execute('SELECT way_id FROM ways')}
        self.seen = set()
        self.invalid = []

    def way(self, way):
        way_id = int(way.id)
        if way_id not in self.admitted:
            return
        self.seen.add(way_id)
        row = self.db.execute('''SELECT g.points_json,d.forward_allowed,d.backward_allowed,d.way_length_m
            FROM way_geom g JOIN traffic_sign_way_direction d USING(way_id) WHERE g.way_id=?''', (way_id,)).fetchone()
        if row is None or not way.tags.get('highway') or any(not n.location.valid() for n in way.nodes):
            self.invalid.append(way_id)
            return
        points = [(n.location.lat, n.location.lon) for n in way.nodes]
        refs = [int(n.ref) for n in way.nodes]
        tags = {k: v for k, v in way.tags}
        if not insert_way(self.db, self.incidence, way_id, refs, points, tags, row[1:3], json.loads(row[0]), row[3]):
            self.invalid.append(way_id)
        if len(self.seen) % 100000 == 0:
            print(f'Upcoming path: source-verified {len(self.seen)} ways', flush=True)


def certify(db):
    # A source degree of two excludes side-road branches, merges and omitted-way
    # incidence, including at nodes in the middle of an admitted source way.
    db.execute('''INSERT INTO upcoming_path_successor
      SELECT a.segment_id,
        CASE WHEN a.permission_status='allowed' AND n.source_degree=2 AND n.restriction_barrier=0
          AND aw.restriction_barrier=0 AND count(b.segment_id)=1 AND min(bw.restriction_barrier)=0
          THEN 'certified' ELSE 'stop' END,
        CASE WHEN a.permission_status='allowed' AND n.source_degree=2 AND n.restriction_barrier=0
          AND aw.restriction_barrier=0 AND count(b.segment_id)=1 AND min(bw.restriction_barrier)=0
          THEN min(b.segment_id) ELSE NULL END,
        a.end_node_id,
        CASE WHEN a.permission_status='allowed' AND n.source_degree=2 AND n.restriction_barrier=0
          AND aw.restriction_barrier=0 AND count(b.segment_id)=1 AND min(bw.restriction_barrier)=0
          THEN 'source_node_unbranched_unmerged_v1' ELSE 'source_incidence_or_permission_stop_v1' END
      FROM upcoming_path_segment a
      JOIN upcoming_path_node n ON n.node_id=a.end_node_id
      JOIN upcoming_path_way aw ON aw.way_id=a.way_id
      LEFT JOIN upcoming_path_segment b ON b.start_node_id=a.end_node_id AND b.permission_status='allowed'
        AND b.segment_id!=a.segment_id
        AND NOT(b.way_id=a.way_id AND b.start_chainage_m=a.start_chainage_m AND b.end_chainage_m=a.end_chainage_m)
      LEFT JOIN upcoming_path_way bw ON bw.way_id=b.way_id
      GROUP BY a.segment_id''')


def build(db, input_pbf):
    expected = dict(db.execute('SELECT key,value FROM traffic_sign_capability')).get('road_snapshot_sha256')
    metadata = dict(db.execute('SELECT key,value FROM metadata'))
    if metadata.get('road_geometry_policy') != 'source_vertices_v1':
        raise ValueError('Upcoming path requires complete source_vertices_v1 geometry')
    source_sha = sha256(input_pbf)
    if not expected or source_sha != expected:
        raise ValueError('Original PBF hash does not match traffic-sign road snapshot')
    incidence = Incidence()
    print('Upcoming path: reading complete source highway incidence and restrictions', flush=True)
    # Untagged nodes cannot restrict access; filter them in C++ before Python
    # callbacks, while every tagged highway/restriction and its node refs stays.
    incidence.apply_file(str(input_pbf), locations=False, filters=[osmium.filter.EmptyTagFilter()])
    print(f'Upcoming path: {incidence.ways} source highways, {len(incidence.degree)} nodes, {incidence.restrictions} restrictions', flush=True)
    db.execute('SAVEPOINT upcoming_path_build')
    try:
        for statement in (ROOT/'mapdata/spec/upcoming_path_v1.sql').read_text().split(';'):
            if statement.strip():
                db.execute(statement)
        for table in TABLES:
            db.execute('DELETE FROM '+table)
        segments = Segments(db, incidence)
        segments.apply_file(str(input_pbf), locations=True, idx='flex_mem')
        missing = segments.admitted-segments.seen
        if segments.invalid or missing:
            raise ValueError(f'Incomplete source geometry: {len(segments.invalid)} invalid, {len(missing)} missing ways; examples {(segments.invalid+sorted(missing))[:10]}')
        certify(db)
        db.execute('''CREATE INDEX IF NOT EXISTS idx_traffic_sign_association_station
            ON traffic_sign_association(way_id,direction,station_chainage_m,sign_id)''')
        report = {'format': 'youspeed.upcoming-path.build.v1', 'source_sha256': source_sha,
                  'source_highways': incidence.ways, 'source_nodes': len(incidence.degree),
                  'source_restrictions': incidence.restrictions, 'admitted_ways': len(segments.seen),
                  'counts': {table: db.execute('SELECT count(*) FROM '+table).fetchone()[0]
                             for table in TABLES if table != 'upcoming_path_capability'},
                  'successors': dict(db.execute('SELECT status,count(*) FROM upcoming_path_successor GROUP BY status'))}
        capability = {'version': '1', 'completeness': 'complete', 'road_snapshot_sha256': source_sha,
                      'geometry_convention': GEOMETRY, 'source_node_incidence': 'complete_pbf_highway_v1',
                      'restrictions': 'all_involved_ways_stop_v1', 'motorcar_profile': 'existing_runtime_direction_v1',
                      'report_json': json.dumps(report, sort_keys=True, separators=(',', ':'))}
        db.executemany('INSERT INTO upcoming_path_capability VALUES(?,?)', capability.items())
        db.execute('RELEASE upcoming_path_build')
        return report
    except BaseException:
        # SQLITE_FULL can automatically roll back the whole transaction and
        # remove its savepoint. Preserve that failure instead of masking it.
        if db.in_transaction:
            try:
                db.execute('ROLLBACK TO upcoming_path_build')
                db.execute('RELEASE upcoming_path_build')
            except sqlite3.Error:
                db.rollback()
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db', type=Path, required=True)
    parser.add_argument('--input-pbf', type=Path, required=True)
    parser.add_argument('--report', type=Path, required=True)
    args = parser.parse_args()
    if not args.db.is_file() or not args.input_pbf.is_file():
        parser.error('Both --db and original --input-pbf must already exist')
    with sqlite3.connect(args.db) as db:
        report = build(db, args.input_pbf)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, indent=2)+'\n')
    print(json.dumps(report, indent=2))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
