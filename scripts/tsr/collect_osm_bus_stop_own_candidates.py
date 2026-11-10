#!/usr/bin/env python3
"""Read-only own-instance picture inventory for OSM-guided bus-stop mining.

Coordinates locate candidate pictures, not a sign label. Pixels are not read.
"""
import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.tsr.prepare_de_field_evaluation import store_context, collections, dump, sha, distance
from scripts.tsr.de_expanded_classifier import exclude_groups

BBOXES = {'Karlsruhe': [8.30, 48.95, 8.50, 49.05],
          'Pforzheim': [8.65, 48.85, 8.77, 48.93]}
SQL = """SELECT picture_id::text, fingerprint, source_id,
 metadata#>'{picture,geometry,coordinates}' AS coordinates,
 metadata#>>'{picture,ts}' AS captured_at,
 metadata->'collections' AS collections,
 metadata->'annotations' AS annotations
 FROM youspeed.panoramax_items
 WHERE active AND visibility='anyone'
 AND source_id IN ('panoramax.woladen.de','panoramax.youspeed.de')
 AND metadata#>>'{picture,geometry,type}'='Point'
 AND (metadata#>>'{picture,geometry,coordinates,0}')::double precision BETWEEN %s AND %s
 AND (metadata#>>'{picture,geometry,coordinates,1}')::double precision BETWEEN %s AND %s
 ORDER BY picture_id LIMIT %s"""


def snapshot(output, limit):
    if output.exists():
        raise ValueError('Use a fresh snapshot path')
    areas = []
    print('Opening read-only source connection', flush=True)
    with store_context() as (store, _):
        print('SSH tunnel ready', flush=True)
        with store.connection() as db:
            print('Read-only database connection ready', flush=True)
            db.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY')
            db.execute("SET LOCAL statement_timeout='60000ms'")
            identity = db.execute("SELECT transaction_timestamp() AS as_of,current_user AS role,current_setting('transaction_read_only') AS read_only").fetchone()
            assert identity['role'] == 'youspeed_report' and identity['read_only'] == 'on'
            for name, (west, south, east, north) in BBOXES.items():
                rows = db.execute(SQL, (west, east, south, north, limit + 1)).fetchall()
                clipped = len(rows) > limit
                rows = rows[:limit]
                records = []
                for row in rows:
                    routes = ['collection:' + i for i in collections(row['collections'])]
                    records.append({'sample_id': 'own-picture-' + row['picture_id'],
                        'picture_id': row['picture_id'], 'source_id': row['source_id'],
                        'fingerprint': row['fingerprint'], 'coordinates': row['coordinates'][:2],
                        'captured_at': row['captured_at'], 'route_tokens': routes,
                        'group_id': routes[0] if routes else 'picture:' + row['picture_id'],
                        'annotations': row['annotations'] or [],
                        'metadata_url': 'https://panoramax.youspeed.de/api/pictures/' + row['picture_id']})
                areas.append({'area': name, 'bbox': BBOXES[name], 'rows': records, 'truncated': clipped})
                print(json.dumps({'area': name, 'records': len(records), 'truncated': clipped}), flush=True)
    dump(output, {'schema': 'own-panoramax-osm-anchor-inventory-v1', 'identity': identity,
                  'areas': areas, 'script_sha256': sha(__file__), 'pixels_read': False,
                  'label_policy': 'OSM location anchors do not establish image sign labels.'})


def select(snapshot_path, anchors_path, protected_paths, output, max_distance):
    if output.exists():
        raise ValueError('Use a fresh selection path')
    inventory = json.loads(snapshot_path.read_text())
    anchors = [a for a in json.loads(anchors_path.read_text())['anchors'] if not a.get('exclusion_reasons')]
    protected = []
    for path in protected_paths:
        protected.extend(json.loads(path.read_text())['samples'])
    rows = {r['picture_id']: r for area in inventory['areas'] for r in area['rows']}
    # Close multi-collection links before excluding complete held-out routes.
    groups = [{r['picture_id'], *r['route_tokens']} for r in rows.values()]
    parent = {}
    def root(x):
        parent.setdefault(x, x)
        if parent[x] != x: parent[x] = root(parent[x])
        return parent[x]
    for group in groups:
        first = min(group)
        for value in sorted(group):
            left, right = sorted((root(value), root(first)))
            parent[right] = left
    values = list(rows.values())
    for row in values: row['group_id'] = root(row['picture_id'])
    kept, exclusions = exclude_groups(values, protected, radius_m=250)
    candidates = []
    for row in kept:
        near = [(distance(row['coordinates'], anchor['coordinates']), anchor) for anchor in anchors]
        if not near: continue
        metres, anchor = min(near, key=lambda item: item[0])
        if metres <= max_distance:
            candidates.append({**row, 'osm_anchor': anchor, 'anchor_distance_m': round(metres, 2),
                               'truth_label': None, 'human_approved': False, 'training_only': True})
    candidates.sort(key=lambda r: (r['anchor_distance_m'], r['picture_id']))
    dump(output, {'schema': 'own-panoramax-osm-bus-stop-candidates-v1',
        'created_at': datetime.now(timezone.utc).isoformat(), 'samples': candidates,
        'snapshot_sha256': sha(snapshot_path), 'osm_anchors_sha256': sha(anchors_path),
        'protected_manifest_sha256': [sha(p) for p in protected_paths],
        'input_pictures': len(rows), 'heldout_route_excluded_pictures': len(rows) - len(kept),
        'max_anchor_distance_m': max_distance, 'protected_radius_m': 250,
        'pixels_read': False, 'labels_assigned': False, 'script_sha256': sha(__file__)})
    print(json.dumps({'input_pictures': len(rows), 'candidates': len(candidates),
                     'protected_exclusions': len(rows)-len(kept)}))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase', choices=['snapshot', 'select'])
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--limit-per-area', type=int, default=10000)
    p.add_argument('--snapshot', type=Path)
    p.add_argument('--anchors', type=Path)
    p.add_argument('--protected', type=Path, nargs='+')
    p.add_argument('--max-distance', type=float, default=35)
    a = p.parse_args()
    a.output.parent.mkdir(parents=True, exist_ok=True)
    if a.phase == 'snapshot': snapshot(a.output, a.limit_per_area)
    else: select(a.snapshot, a.anchors, a.protected, a.output, a.max_distance)


if __name__ == '__main__': main()
