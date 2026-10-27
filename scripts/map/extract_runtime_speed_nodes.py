#!/usr/bin/env python3
"""Export generic speed-sign nodes without assigning runtime authority.

Preserves every source tag and explicit source-way memberships. A membership
with unknown travel direction is not a verified legal association.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import time

import osmium


def speed_node(tags):
    for key, value in tags.items():
        if key.split(':', 1)[0] == 'maxspeed':
            return True
        if key.startswith('traffic_sign'):
            low = value.lower()
            if 'maxspeed' in low or any(code in value for code in ('DE:274', 'DE:278', 'DE:282')):
                return True
    return False


def distance(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    v = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371000.0 * 2 * math.asin(min(1.0, math.sqrt(v)))


class Nodes(osmium.SimpleHandler):
    def __init__(self):
        super().__init__()
        self.nodes = {}

    def node(self, node):
        tags = {k: v for k, v in node.tags}
        if not speed_node(tags) or not node.location.valid():
            return
        self.nodes[int(node.id)] = {
            'source_id': 'osm-node:' + str(node.id), 'osm_node_id': int(node.id),
            'latitude': node.location.lat, 'longitude': node.location.lon,
            'tags': tags, 'memberships': [], 'binding_status': 'unresolved_direction',
        }


class Memberships(osmium.SimpleHandler):
    def __init__(self, db, nodes):
        super().__init__()
        self.db, self.nodes = db, nodes
        self.ways = {r[0] for r in db.execute('SELECT way_id FROM ways')}
        self.geometry_mismatches = 0

    def way(self, way):
        if way.id not in self.ways:
            return
        hits = [(i, self.nodes[n.ref]) for i, n in enumerate(way.nodes) if n.ref in self.nodes]
        if not hits:
            return
        row = self.db.execute('SELECT points_json FROM way_geom WHERE way_id=?', (way.id,)).fetchone()
        points = json.loads(row[0]) if row else []
        if len(points) != len(way.nodes):
            self.geometry_mismatches += 1
            return
        chainage, stations = 0.0, [0.0]
        for a, b in zip(points, points[1:]):
            chainage += distance(a, b)
            stations.append(chainage)
        for ordinal, record in hits:
            record['memberships'].append({
                'way_id': int(way.id), 'source_vertex_ordinal': ordinal,
                'chainage_m': stations[ordinal], 'direction': 'unknown',
                'proof': 'explicit_source_way_node_membership',
            })


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--pbf', type=Path, required=True)
    ap.add_argument('--db', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    args = ap.parse_args()
    started = time.monotonic()
    nodes = Nodes()
    nodes.apply_file(str(args.pbf), locations=False, filters=[osmium.filter.EmptyTagFilter()])
    db = sqlite3.connect('file:' + str(args.db.resolve()) + '?mode=ro&immutable=1', uri=True)
    memberships = Memberships(db, nodes.nodes)
    memberships.apply_file(str(args.pbf), locations=False, filters=[osmium.filter.EmptyTagFilter()])
    assert memberships.geometry_mismatches == 0, 'Source vertices differ from bundle geometry'
    source_hash = hashlib.sha256()
    with args.pbf.open('rb') as source:
        while data := source.read(4 * 1024 * 1024):
            source_hash.update(data)
    records = [nodes.nodes[k] for k in sorted(nodes.nodes)]
    for record in records:
        record['memberships'].sort(key=lambda m: (m['way_id'], m['source_vertex_ordinal']))
        if not record['memberships']:
            record['binding_status'] = 'no_admitted_source_way'
    result = {
        'schema': 'youspeed.generic-speed-nodes.prototype.v1',
        'source_pbf_sha256': source_hash.hexdigest(),
        'node_count': len(records),
        'membership_count': sum(len(r['memberships']) for r in records),
        'unassociated_node_count': sum(not r['memberships'] for r in records),
        'geometry_mismatches': memberships.geometry_mismatches,
        'authority': 'source observations only; no verified direction or legal authority implied',
        'nodes': records,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, separators=(',', ':'), sort_keys=True) + '\n')
    print(json.dumps({k: v for k, v in result.items() if k != 'nodes'}, indent=2))
    print('elapsed_seconds', time.monotonic() - started)


if __name__ == '__main__':
    main()
