#!/usr/bin/env python3
"""Add the MobiData BW inventory to a bundle; never modify speed/settlement tables."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import urllib.request
import uuid

SOURCE_ID = 'mobidata-bw-vzk'
SOURCE_URL = 'https://mobidata-bw.de/daten/portal/VZ-Daten/signs.geojson'
DATASET_URL = 'https://mobidata-bw.de/dataset/verkehrszeichen-baden-wurttemberg'
MAX_BYTES = 200 * 1024 * 1024
SCHEMA = '''
CREATE TABLE IF NOT EXISTS traffic_sign_source (
 source_id TEXT PRIMARY KEY, publisher TEXT NOT NULL, dataset_url TEXT NOT NULL,
 source_url TEXT NOT NULL, license_id TEXT NOT NULL, license_url TEXT NOT NULL,
 snapshot_sha256 TEXT NOT NULL, snapshot_timestamp TEXT, record_count INTEGER NOT NULL,
 min_lon REAL NOT NULL, min_lat REAL NOT NULL, max_lon REAL NOT NULL, max_lat REAL NOT NULL,
 usage_role TEXT NOT NULL CHECK(usage_role='inventory_only'), modification_notice TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS traffic_sign_inventory (
 row_id INTEGER PRIMARY KEY, source_id TEXT NOT NULL REFERENCES traffic_sign_source(source_id),
 record_key TEXT NOT NULL, group_id TEXT NOT NULL, group_order INTEGER,
 location_id TEXT NOT NULL, sign_code TEXT NOT NULL, longitude REAL NOT NULL, latitude REAL NOT NULL,
 orientation_deg REAL, openlr_binary TEXT, openlr_confidence REAL,
 municipality_ars TEXT, municipality_name TEXT, installed_at TEXT, updated_at TEXT,
 raw_properties_json TEXT NOT NULL, UNIQUE(source_id,record_key)
);
CREATE VIRTUAL TABLE IF NOT EXISTS traffic_sign_inventory_rtree USING rtree(row_id,min_lon,max_lon,min_lat,max_lat);
CREATE INDEX IF NOT EXISTS idx_traffic_sign_inventory_code ON traffic_sign_inventory(sign_code);
CREATE INDEX IF NOT EXISTS idx_traffic_sign_inventory_position ON traffic_sign_inventory(latitude,longitude);
CREATE INDEX IF NOT EXISTS idx_traffic_sign_inventory_location ON traffic_sign_inventory(location_id);
'''


def is_bw_region(region):
    return str(region).strip().lower().replace('_', '-').split('/')[-1] in {
        'baden-wuerttemberg', 'germany-baden-wuerttemberg', 'baden-wuerttemberg-settlement-pilot'}


def canonical(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False)


def number(value, name, minimum, maximum, optional=False):
    if value is None and optional:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not minimum <= value <= maximum:
        raise ValueError(f'Invalid {name}: expected finite number in [{minimum},{maximum}]')
    return value


def parse_snapshot(path):
    path = Path(path)
    if path.stat().st_size > MAX_BYTES:
        raise ValueError('Traffic-sign snapshot exceeds 200 MiB')
    raw = path.read_bytes()
    data = json.loads(raw, parse_constant=lambda value: (_ for _ in ()).throw(ValueError('Nonfinite JSON: '+value)))
    if not isinstance(data, dict) or data.get('type') != 'FeatureCollection':
        raise ValueError('Expected a GeoJSON FeatureCollection')
    features = data.get('features')
    if not isinstance(features, list) or not features:
        raise ValueError('Refusing an empty or missing traffic-sign inventory')
    if 'numberReturned' in data and data['numberReturned'] != len(features):
        raise ValueError('numberReturned differs from the feature count')
    rows, seen = [], set()
    for feature in features:
        if feature.get('type') != 'Feature' or feature.get('geometry', {}).get('type') != 'Point':
            raise ValueError('Inventory features must be Points')
        coords = feature['geometry'].get('coordinates')
        if not isinstance(coords, list) or len(coords) < 2:
            raise ValueError('Missing point coordinates')
        lon, lat = number(coords[0], 'longitude', -180, 180), number(coords[1], 'latitude', -90, 90)
        p = feature.get('properties')
        if not isinstance(p, dict):
            raise ValueError('Missing sign properties')
        for key in ['GruppenID', 'StandortID']:
            uuid.UUID(p[key])
        code = p.get('Verkehrszeichennummer')
        if not isinstance(code, str) or not code.startswith('DE:') or len(code) > 512:
            raise ValueError('Missing or invalid German sign code')
        # Group order is an order of groups on a support, not an individual sign ID.
        # Preserve multiple signs within a group; use a canonical feature fingerprint.
        key = hashlib.sha256(canonical(feature).encode()).hexdigest()
        if key in seen:
            raise ValueError('Duplicate identical inventory feature')
        seen.add(key)
        rows.append((key, p['GruppenID'], p.get('GruppenReihung'), p['StandortID'], code, lon, lat,
                     number(p.get('GruppenAusrichtung'), 'orientation', 0, 360, True),
                     p.get('OpenLRBinary'), number(p.get('OpenLRConfidence'), 'OpenLR confidence', 0, 100, True),
                     p.get('ARS'), p.get('Verwaltungsebene'), p.get('AufstellungsDatum'),
                     p.get('LetzteAktualisierung'), canonical(p)))
    rows.sort(key=lambda row: row[0])
    return {'sha256': hashlib.sha256(raw).hexdigest(), 'timestamp': data.get('timeStamp'), 'rows': rows,
            'counts': dict(sorted(Counter(row[4] for row in rows).items())),
            'bbox': [min(r[5] for r in rows), min(r[6] for r in rows), max(r[5] for r in rows), max(r[6] for r in rows)]}


def import_inventory(conn, path):
    snapshot = parse_snapshot(path)  # Validate before beginning a replacement.
    conn.execute('SAVEPOINT traffic_sign_import')
    try:
        # executescript commits open transactions; execute statements separately for atomic rollback.
        for statement in SCHEMA.split(';'):
            if statement.strip():
                conn.execute(statement)
        conn.execute('DELETE FROM traffic_sign_inventory_rtree WHERE row_id IN (SELECT row_id FROM traffic_sign_inventory WHERE source_id=?)', (SOURCE_ID,))
        conn.execute('DELETE FROM traffic_sign_inventory WHERE source_id=?', (SOURCE_ID,))
        bbox = snapshot['bbox']
        conn.execute('INSERT OR REPLACE INTO traffic_sign_source VALUES('+','.join('?' for _ in range(15))+')',
                     (SOURCE_ID, 'Verkehrsministerium Baden-Württemberg / MobiData BW', DATASET_URL, SOURCE_URL,
                      'dl-de/by-2-0', 'https://www.govdata.de/dl-de/by-2-0', snapshot['sha256'], snapshot['timestamp'],
                      len(snapshot['rows']), *bbox, 'inventory_only',
                      'GeoJSON transformed to SQLite inventory tables; codes and raw properties preserved. No speed-rule interpretation.'))
        start = conn.execute('SELECT COALESCE(MAX(row_id),0) FROM traffic_sign_inventory').fetchone()[0]
        rows = [(start+i, SOURCE_ID, *row) for i, row in enumerate(snapshot['rows'], 1)]
        conn.executemany('INSERT INTO traffic_sign_inventory VALUES('+','.join('?' for _ in range(17))+')', rows)
        conn.executemany('INSERT INTO traffic_sign_inventory_rtree VALUES(?,?,?,?,?)',
                         [(r[0], r[7], r[7], r[8], r[8]) for r in rows])
        conn.execute('RELEASE traffic_sign_import')
    except BaseException:
        conn.execute('ROLLBACK TO traffic_sign_import')
        conn.execute('RELEASE traffic_sign_import')
        raise
    return {'source_id': SOURCE_ID, 'record_count': len(rows), 'snapshot_sha256': snapshot['sha256'],
            'snapshot_timestamp': snapshot['timestamp'], 'usage_role': 'inventory_only', 'counts': snapshot['counts']}


def download_snapshot(output):
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix+'.download')
    try:
        request = urllib.request.Request(SOURCE_URL, headers={'User-Agent': 'YouSpeed-BW-sign-inventory/1.0'})
        with urllib.request.urlopen(request, timeout=90) as response, temporary.open('wb') as dst:
            total = 0
            while chunk := response.read(1024*1024):
                total += len(chunk)
                if total > MAX_BYTES:
                    raise ValueError('Traffic-sign download exceeds 200 MiB')
                dst.write(chunk)
        parse_snapshot(temporary)
        temporary.replace(output)
    finally:
        temporary.unlink(missing_ok=True)
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    download = sub.add_parser('download');download.add_argument('--output', type=Path, required=True)
    ingest = sub.add_parser('import');ingest.add_argument('--db', type=Path, required=True);ingest.add_argument('--geojson', type=Path, required=True)
    args = parser.parse_args()
    if args.command == 'download':
        print(download_snapshot(args.output))
    else:
        if not args.db.is_file():
            parser.error('Bundle database does not exist')
        with sqlite3.connect(args.db) as conn:
            print(json.dumps(import_inventory(conn, args.geojson), ensure_ascii=False))


if __name__ == '__main__':
    main()
