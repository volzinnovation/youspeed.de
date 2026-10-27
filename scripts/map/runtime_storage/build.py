#!/usr/bin/env python3
"""Lossless, non-production runtime storage experiment. Never edits its source."""
import argparse
import collections
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import struct
import time
import zlib

ROAD = struct.Struct('<qiiiiQQIIIhhhHQI')
NODE = struct.Struct('<iiiiIIII')
BLOCK = struct.Struct('<QIII')
HEADER_SIZE = 160
BLOCK_SIZE = 262144
MAGIC = b'YSPACK1\0'
RELATED = ('way_endpoints', 'traffic_sign_way_direction', 'traffic_sign_lane',
           'traffic_sign_way_rule', 'road_speed_source_tag', 'road_speed_rule_set',
           'road_speed_rule', 'road_speed_interpretation', 'settlement_segment',
           'way_links', 'way_continuity_membership', 'upcoming_path_way',
           'upcoming_path_segment', 'motorway_exit_approach')


def canonical(value):
    return json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode()


def fnv(data):
    h = 14695981039346656037
    for x in data:
        h = ((h ^ x) * 1099511628211) & 0xffffffffffffffff
    return h


def varint(x):
    out = bytearray()
    while x >= 128:
        out.append((x & 127) | 128)
        x >>= 7
    out.append(x)
    return out


def geometry(points):
    exact = all(round(v * 1e7) / 1e7 == v for p in points for v in p)
    out = bytearray([0 if exact else 1]) + varint(len(points))
    if not exact:
        return out + b''.join(struct.pack('<dd', *p) for p in points)
    prev = [0, 0]
    for point in points:
        for axis in (0, 1):
            v = round(point[axis] * 1e7)
            delta = v - prev[axis]
            prev[axis] = v
            out += varint(delta * 2 if delta >= 0 else -delta * 2 - 1)
    return out


def decode_geometry(data):
    def read(pos):
        value = shift = 0
        while True:
            byte = data[pos]
            pos += 1
            value |= (byte & 127) << shift
            if byte < 128:
                return value, pos
            shift += 7
            if shift > 63:
                raise ValueError('bad geometry varint')
    count, pos = read(1)
    if data[0] == 1:
        return [list(struct.unpack_from('<dd', data, pos + i * 16)) for i in range(count)]
    prev = [0, 0]
    out = []
    for _ in range(count):
        p = []
        for axis in (0, 1):
            delta, pos = read(pos)
            prev[axis] += delta // 2 if delta % 2 == 0 else -(delta // 2) - 1
            p.append(prev[axis] / 1e7)
        out.append(p)
    if pos != len(data):
        raise ValueError('trailing geometry bytes')
    return out


def speed(value):
    if value is None:
        return -32768
    if value == 'none':
        return -1
    try:
        f = float(value)
        if f.is_integer() and 0 <= f <= 32767:
            return int(f)
    except (ValueError, TypeError):
        pass
    return -32767  # exact raw value always retained in semantic payload


class Blocks:
    def __init__(self, path):
        self.file = path.open('wb')
        self.buffer = bytearray()
        self.entries = []
        self.logical = 0

    def append(self, data):
        offset = self.logical
        self.logical += len(data)
        self.buffer.extend(data)
        while len(self.buffer) >= BLOCK_SIZE:
            self.flush(BLOCK_SIZE)
        return offset

    def flush(self, size):
        raw = bytes(self.buffer[:size])
        del self.buffer[:size]
        encoded = zlib.compress(raw, 6)
        self.entries.append((self.file.tell(), len(encoded), len(raw), zlib.crc32(raw)))
        self.file.write(encoded)

    def finish(self):
        if self.buffer:
            self.flush(len(self.buffer))
        self.file.close()


def schema(db):
    names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
    # R-tree internal shadow tables are implementation artifacts, not extra source features.
    virtual = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE sql LIKE 'CREATE VIRTUAL TABLE%'")}
    names = [n for n in names if not any(n == v + s for v in virtual for s in ('_node', '_rowid', '_parent'))]
    return {name: [r[1] for r in db.execute(f'PRAGMA table_info("{name}")')] for name in names}


class SourceRows:
    def __init__(self, db, columns):
        self.db, self.columns = db, columns
        self.streams = {}
        for name in RELATED:
            if name in columns:
                it = iter(db.execute(f'SELECT * FROM "{name}" ORDER BY way_id'))
                self.streams[name] = [it, next(it, None), columns[name].index('way_id')]

    def payload(self, way):
        result = {'ways': list(way)}
        way_id = way[0]
        for name, state in self.streams.items():
            it, row, col = state
            while row is not None and row[col] < way_id:
                row = next(it, None)
            rows = []
            while row is not None and row[col] == way_id:
                rows.append(list(row))
                row = next(it, None)
            state[1] = row
            if rows:
                # Stabilize joins even when original SQL has no secondary index ordering.
                rows.sort(key=canonical)
                result[name] = rows
        return canonical(result)


def morton(x, y):
    x = max(0, min(65535, int((x + 1800000000) / 3600000000 * 65535)))
    y = max(0, min(65535, int((y + 900000000) / 1800000000 * 65535)))
    def spread(v):
        v = (v | v << 8) & 0x00ff00ff
        v = (v | v << 4) & 0x0f0f0f0f
        v = (v | v << 2) & 0x33333333
        return (v | v << 1) & 0x55555555
    return spread(x) | spread(y) << 1


def make_index(roads):
    order = sorted(range(len(roads)), key=lambda i: morton((roads[i][1] + roads[i][3]) // 2, (roads[i][2] + roads[i][4]) // 2))
    nodes = []
    def visit(start, end):
        idx = len(nodes)
        nodes.append(None)
        if end - start <= 32:
            rs = [roads[order[k]] for k in range(start, end)]
            bounds = (min(r[1] for r in rs), min(r[2] for r in rs), max(r[3] for r in rs), max(r[4] for r in rs))
            nodes[idx] = bounds + (start, end - start, 1, 0)
        else:
            mid = (start + end) // 2
            left, right = visit(start, mid), visit(mid, end)
            a, b = nodes[left], nodes[right]
            bounds = (min(a[0], b[0]), min(a[1], b[1]), max(a[2], b[2]), max(a[3], b[3]))
            nodes[idx] = bounds + (left, right, 0, 0)
        return idx
    if order:
        visit(0, len(order))
    return nodes, order


def copy_file(src, dst):
    with src.open('rb') as f:
        while data := f.read(1024 * 1024):
            dst.write(data)


def archive_source(db, out, columns):
    """Independent complete source record archive, including non-runtime data."""
    target = out / 'source-semantics.zblocks'
    writer = Blocks(target)
    tables = {}
    for name, cols in columns.items():
        h = hashlib.sha256()
        start = writer.logical
        count = 0
        # Canonical primary-key order; all remaining column ties form identical rows.
        info = list(db.execute(f'PRAGMA table_info("{name}")'))
        primary = [r[1] for r in sorted(info, key=lambda r: r[5]) if r[5]]
        order = ','.join('"' + p + '"' for p in primary) or 'rowid'
        for row in db.execute(f'SELECT * FROM "{name}" ORDER BY {order}'):
            data = canonical(list(row)) + b'\n'
            h.update(data)
            writer.append(data)
            count += 1
        tables[name] = {'columns': cols, 'rows': count, 'logical_offset': start,
                        'logical_bytes': writer.logical - start, 'sha256': h.hexdigest(),
                        'order_by': primary or ['rowid']}
        print('archive', name, count, flush=True)
    writer.finish()
    index = {'block_size': BLOCK_SIZE, 'blocks': writer.entries, 'tables': tables,
             'description': 'Lossless typed original rows; complete semantic coverage, shared and counted for each candidate. Native hot lookup consumes related per-way rows separately.'}
    (out / 'source-semantics.index.json').write_bytes(canonical(index))
    return index


def build(source, out, archive=True):
    started = time.perf_counter()
    out.mkdir(parents=True, exist_ok=True)
    if (out / 'runtime.pack').exists() or (out / 'runtime.sqlite').exists():
        raise FileExistsError('Output runtime files already exist; use a new output directory')
    db = sqlite3.connect('file:' + str(source.resolve()) + '?mode=ro&immutable=1', uri=True)
    db.execute('PRAGMA cache_size=-32768')
    columns = schema(db)
    src = SourceRows(db, columns)
    sql = sqlite3.connect(out / 'runtime.sqlite')
    sql.executescript('''PRAGMA page_size=4096; PRAGMA journal_mode=OFF; PRAGMA synchronous=OFF;
        PRAGMA cache_size=-32768;
        CREATE TABLE road(way_id INTEGER PRIMARY KEY,record BLOB NOT NULL,geometry BLOB NOT NULL) WITHOUT ROWID;
        CREATE TABLE block(block_id INTEGER PRIMARY KEY,raw_size INTEGER NOT NULL,crc INTEGER NOT NULL,data BLOB NOT NULL) WITHOUT ROWID;
        CREATE VIRTUAL TABLE spatial USING rtree_i32(way_id,min_lon,max_lon,min_lat,max_lat);
        CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL) WITHOUT ROWID;''')
    roads = []
    geom_path, block_path = out / 'geometry.stage', out / 'metadata.stage'
    blocks = Blocks(block_path)
    points_count = fallbacks = 0
    source_geo, roundtrip_geo = hashlib.sha256(), hashlib.sha256()
    attrs_sha = hashlib.sha256()
    with geom_path.open('wb') as geom:
        for way in db.execute('SELECT * FROM ways ORDER BY way_id'):
            # Indexed original lookup avoids materializing the million-way source in memory.
            row = db.execute('SELECT points_json FROM way_geom WHERE way_id=?', (way[0],)).fetchone()
            if row is None:
                raise ValueError(f'Missing geometry for way {way[0]}')
            points = json.loads(row[0])
            data = geometry(points)
            restored = decode_geometry(data)
            if restored != points:
                raise ValueError(f'Coordinate roundtrip failure {way[0]}')
            payload = src.payload(way)
            meta_offset = blocks.append(payload)
            bbox = [round(float(way[columns['ways'].index(k)]) * 1e7) for k in ('min_lon', 'min_lat', 'max_lon', 'max_lat')]
            speedvals = [speed(way[columns['ways'].index(k)]) for k in ('maxspeed', 'maxspeed_forward', 'maxspeed_backward')]
            record = (way[0], *bbox, geom.tell(), meta_offset, len(data), len(payload), len(points), *speedvals, 0, zlib.crc32(payload), zlib.crc32(data))
            encoded_record = ROAD.pack(*record)
            roads.append(record)
            geom.write(data)
            sql.execute('INSERT INTO road VALUES(?,?,?)', (way[0], encoded_record, data))
            sql.execute('INSERT INTO spatial VALUES(?,?,?,?,?)', (way[0], bbox[0], bbox[2], bbox[1], bbox[3]))
            identity = struct.pack('<qI', way[0], len(points))
            source_geo.update(identity)
            roundtrip_geo.update(identity)
            for p, q in zip(points, restored):
                source_geo.update(struct.pack('<dd', *p))
                roundtrip_geo.update(struct.pack('<dd', *q))
            attrs_sha.update(struct.pack('<qI', way[0], len(payload)))
            attrs_sha.update(payload)
            points_count += len(points)
            fallbacks += data[0] == 1
            if len(roads) % 50000 == 0:
                sql.commit()
                print('roads', len(roads), 'seconds', round(time.perf_counter() - started, 1), flush=True)
    blocks.finish()
    with block_path.open('rb') as f:
        for idx, (offset, length, rawsize, crc) in enumerate(blocks.entries):
            f.seek(offset)
            sql.execute('INSERT INTO block VALUES(?,?,?,?)', (idx, rawsize, crc, f.read(length)))
    nodes, order = make_index(roads)
    offset = HEADER_SIZE
    roads_offset, offset = offset, offset + len(roads) * ROAD.size
    geom_offset, offset = offset, offset + geom_path.stat().st_size
    nodes_offset, offset = offset, offset + len(nodes) * NODE.size
    order_offset, offset = offset, offset + len(order) * 4
    blockdir_offset, offset = offset, offset + len(blocks.entries) * BLOCK.size
    blockdata_offset, offset = offset, offset + block_path.stat().st_size
    header = struct.pack('<8sII14Q', MAGIC, 1, 0x01020304, len(roads), len(nodes), len(order), len(blocks.entries),
                         roads_offset, geom_offset, geom_path.stat().st_size, nodes_offset, order_offset,
                         blockdir_offset, blockdata_offset, offset, BLOCK_SIZE, blocks.logical)
    header += struct.pack('<I', zlib.crc32(header))
    header += bytes(HEADER_SIZE - len(header))
    with (out / 'runtime.pack').open('wb') as pack:
        pack.write(header)
        roads_crc = nodes_crc = order_crc = blockdir_crc = 0
        for road in roads:
            data = ROAD.pack(*road)
            roads_crc = zlib.crc32(data, roads_crc)
            pack.write(data)
        copy_file(geom_path, pack)
        for node in nodes:
            data = NODE.pack(*node)
            nodes_crc = zlib.crc32(data, nodes_crc)
            pack.write(data)
        for i in order:
            data = struct.pack('<I', i)
            order_crc = zlib.crc32(data, order_crc)
            pack.write(data)
        for entry in blocks.entries:
            data = BLOCK.pack(*entry)
            blockdir_crc = zlib.crc32(data, blockdir_crc)
            pack.write(data)
        copy_file(block_path, pack)
        pack.seek(132)
        pack.write(struct.pack('<IIIII', roads_crc, nodes_crc, order_crc, blockdir_crc, 0x43524331))
    sql.execute('INSERT INTO metadata VALUES(?,?)', ('schema', canonical(columns).decode()))
    sql.execute('INSERT INTO metadata VALUES(?,?)', ('block_size', str(BLOCK_SIZE)))
    sql.execute('INSERT INTO metadata VALUES(?,?)', ('way_count', str(len(roads))))
    sql.commit()
    sql.close()
    archive_index = archive_source(db, out, columns) if archive else None
    db.close()
    geom_path.unlink()
    block_path.unlink()
    result = {'format': 1, 'source': str(source.resolve()), 'source_bytes': source.stat().st_size,
              'ways': len(roads), 'points': points_count, 'fallback_double_ways': fallbacks,
              'geometry_source_sha256': source_geo.hexdigest(), 'geometry_roundtrip_sha256': roundtrip_geo.hexdigest(),
              'per_way_source_semantics_sha256': attrs_sha.hexdigest(), 'source_tables': columns,
              'related_tables': [n for n in RELATED if n in columns], 'build_seconds': time.perf_counter() - started,
              'files': {p.name: {'bytes': p.stat().st_size} for p in out.iterdir() if p.is_file()},
              'archive_tables': len(archive_index['tables']) if archive_index else 0,
              'warning': 'Experimental storage kernel. Original rows fully retained. Does not replace the production matcher or protected speed-reference policy.'}
    (out / 'manifest.json').write_text(json.dumps(result, indent=2) + '\n')
    print(json.dumps(result, indent=2), flush=True)
    return result


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--source', type=Path, required=True)
    ap.add_argument('--output-dir', type=Path, required=True)
    ap.add_argument('--without-source-archive', action='store_true', help='Tests only; invalid for full-data comparison')
    args = ap.parse_args()
    build(args.source, args.output_dir, not args.without_source_archive)
