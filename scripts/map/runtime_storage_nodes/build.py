#!/usr/bin/env python3
"""Compile every full-source speed/sign node into equivalent queryable stores."""
import argparse
import hashlib
import json
import math
from pathlib import Path
import random
import sqlite3
import struct
import zlib

REC = struct.Struct('<qiiQIIIQ')
HEADER_SIZE = 128

def fnv(data):
    value = 14695981039346656037
    for byte in data:
        value = ((value ^ byte) * 1099511628211) & ((1 << 64) - 1)
    return value

def build(source, output):
    output.mkdir(parents=True, exist_ok=True)
    document = json.loads(source.read_text())
    rows = document['nodes']
    assert len(rows) == document['node_count']
    assert len({n['osm_node_id'] for n in rows}) == len(rows)
    compiled = []
    for row in rows:
        raw = json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        lat, lon = round(row['latitude'] * 1e7), round(row['longitude'] * 1e7)
        assert lat / 1e7 == row['latitude'] and lon / 1e7 == row['longitude']
        compiled.append((lat, lon, row['osm_node_id'], raw, zlib.compress(raw, 9), zlib.crc32(raw), fnv(raw)))
    compiled.sort(key=lambda row: (row[0], row[1], row[2]))
    records = bytearray()
    blob = bytearray()
    for lat, lon, node_id, raw, encoded, crc, digest in compiled:
        records.extend(REC.pack(node_id, lat, lon, len(blob), len(encoded), len(raw), crc, digest))
        blob.extend(encoded)
    order = b''.join(struct.pack('<I', index) for index in sorted(range(len(compiled)), key=lambda i: compiled[i][2]))
    ro, oo, bo = HEADER_SIZE, HEADER_SIZE + len(records), HEADER_SIZE + len(records) + len(order)
    header = bytearray(HEADER_SIZE)
    struct.pack_into('<8sIIQQQQQII', header, 0, b'YSPNODE1', 1, 0x01020304, len(rows), ro, oo, bo, bo + len(blob), zlib.crc32(records), zlib.crc32(order))
    struct.pack_into('<I', header, 64, zlib.crc32(header[:64]))
    packed = output / 'nodes.yspn'
    packed.write_bytes(header + records + order + blob)

    sqlpath = output / 'nodes.sqlite'
    if sqlpath.exists():
        sqlpath.unlink()
    db = sqlite3.connect(sqlpath)
    db.executescript('''PRAGMA page_size=4096; PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
      CREATE TABLE node(node_id INTEGER PRIMARY KEY,latitude_e7 INTEGER NOT NULL,longitude_e7 INTEGER NOT NULL,
        raw_size INTEGER NOT NULL,crc INTEGER NOT NULL,digest TEXT NOT NULL,data BLOB NOT NULL);
      CREATE VIRTUAL TABLE spatial USING rtree_i32(node_id,min_lon,max_lon,min_lat,max_lat);
      CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL) WITHOUT ROWID;''')
    db.executemany('INSERT INTO node VALUES(?,?,?,?,?,?,?)',
        ((node_id, lat, lon, len(raw), crc, f'{digest:016x}', encoded) for lat, lon, node_id, raw, encoded, crc, digest in compiled))
    db.executemany('INSERT INTO spatial VALUES(?,?,?,?,?)',
        ((node_id, lon, lon, lat, lat) for lat, lon, node_id, *_ in compiled))
    db.executemany('INSERT INTO metadata VALUES(?,?)', [('node_count', str(len(rows))), ('source_sha256', hashlib.sha256(source.read_bytes()).hexdigest()), ('schema', 'ysp-source-nodes-1')])
    db.commit()
    db.execute('VACUUM')
    assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',)
    db.close()
    # All source nodes, exact center and a deterministic radius. Every imported
    # node is exercised on both devices; sparse/no-hit queries are added below.
    corpus = ['lat,lon,radius_m']
    for index, row in enumerate(sorted(rows, key=lambda n: n['osm_node_id'])):
        corpus.append(f"{row['latitude']:.7f},{row['longitude']:.7f},{[1,25,100,250][index % 4]}")
    rng = random.Random(20261026)
    for _ in range(256):
        corpus.append(f'{rng.uniform(47.5,49.8):.7f},{rng.uniform(7.5,10.5):.7f},100')
    (output / 'queries.csv').write_text('\n'.join(corpus) + '\n')
    report = {'schema': 1, 'nodes': len(rows), 'memberships': sum(len(n['memberships']) for n in rows),
        'queries': len(corpus) - 1, 'source_sha256': hashlib.sha256(source.read_bytes()).hexdigest(),
        'packed_bytes': packed.stat().st_size, 'sqlite_bytes': sqlpath.stat().st_size,
        'source_bytes': source.stat().st_size, 'source_semantics': 'Full canonical node JSON, all tags and original double chainage; memberships imply no verified applicability.'}
    (output / 'build.json').write_text(json.dumps(report, indent=2) + '\n')
    print(json.dumps(report))

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    build(args.source, args.output)
