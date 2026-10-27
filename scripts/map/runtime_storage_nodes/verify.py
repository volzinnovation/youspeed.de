#!/usr/bin/env python3
"""Verify all compiled node metadata bytes against the independent PBF extraction."""
import argparse
import json
from pathlib import Path
import sqlite3
import struct
import zlib
from build import REC, fnv

def verify(source, directory):
    document = json.loads(source.read_text())
    rows = {row['osm_node_id']: row for row in document['nodes']}
    packed = (directory / 'nodes.yspn').read_bytes()
    count, ro, oo, bo, total = struct.unpack_from('<QQQQQ', packed, 16)
    assert count == len(rows) and total == len(packed)
    ids = set()
    expected_digest = 14695981039346656037
    db = sqlite3.connect(f'file:{directory / "nodes.sqlite"}?mode=ro', uri=True)
    assert db.execute('PRAGMA integrity_check').fetchone() == ('ok',)
    assert db.execute('SELECT count(*) FROM node').fetchone() == (len(rows),)
    for index in range(count):
        node_id, lat, lon, offset, size, rawsize, crc, digest = REC.unpack_from(packed, ro + index * REC.size)
        raw = zlib.decompress(packed[bo+offset:bo+offset+size])
        expected = json.dumps(rows[node_id], ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        assert raw == expected and len(raw) == rawsize and zlib.crc32(raw) == crc and fnv(raw) == digest
        assert lat / 1e7 == rows[node_id]['latitude'] and lon / 1e7 == rows[node_id]['longitude']
        sql_lat, sql_lon, sql_size, sql_crc, sql_hash, sql_encoded = db.execute('SELECT latitude_e7,longitude_e7,raw_size,crc,digest,data FROM node WHERE node_id=?', (node_id,)).fetchone()
        assert (sql_lat, sql_lon, sql_size, sql_crc, sql_hash) == (lat, lon, rawsize, crc, f'{digest:016x}')
        assert zlib.decompress(sql_encoded) == expected
        assert json.loads(raw)['memberships'] == rows[node_id]['memberships']
        ids.add(node_id)
    assert ids == rows.keys()
    for node_id in sorted(rows):
        raw = json.dumps(rows[node_id], ensure_ascii=False, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()
        for byte in raw:
            expected_digest = ((expected_digest ^ byte) * 1099511628211) & ((1 << 64) - 1)
    result = {'nodes': count, 'full_source_records_byte_identical': True, 'original_chainage_doubles_identical': True,
        'semantic_fnv1a64': f'{expected_digest:016x}'}
    (directory / 'source-verification.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result))

if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('source', type=Path)
    p.add_argument('directory', type=Path)
    a = p.parse_args()
    verify(a.source, a.directory)
