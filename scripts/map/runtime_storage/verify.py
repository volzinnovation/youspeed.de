#!/usr/bin/env python3
"""Exhaustive original-source → both output comparison, not output-to-output only."""
import argparse
import hashlib
import json
import mmap
from pathlib import Path
import sqlite3
import struct
import time
import zlib

from build import BLOCK, BLOCK_SIZE, HEADER_SIZE, ROAD, SourceRows, canonical, decode_geometry, schema


class Pack:
    def __init__(self, path):
        self.file = path.open('rb')
        self.map = mmap.mmap(self.file.fileno(), 0, access=mmap.ACCESS_READ)
        self.header = struct.unpack_from('<8sII14Q', self.map)
        fields = self.header[3:]
        (self.count, _, _, self.block_count, self.road_offset, self.geom_offset,
         self.geom_bytes, _, _, self.block_offset, self.block_data, _, _, _) = fields
        self.cached = {}

    def close(self):
        if self.map is not None:
            self.map.close();self.map=None
        if self.file is not None:
            self.file.close();self.file=None

    def __del__(self):
        self.close()

    def metadata(self, record):
        offset, left = record[6], record[8]
        out = bytearray()
        while left:
            i, pos = divmod(offset, BLOCK_SIZE)
            if i not in self.cached:
                off, size, rawsize, crc = BLOCK.unpack_from(self.map, self.block_offset + i * BLOCK.size)
                raw = zlib.decompress(self.map[self.block_data + off:self.block_data + off + size])
                assert len(raw) == rawsize and zlib.crc32(raw) == crc
                self.cached = {i: raw}
            raw = self.cached[i]
            n = min(left, len(raw) - pos)
            assert n > 0
            out.extend(raw[pos:pos+n])
            left -= n
            offset += n
        return bytes(out)


def verify(source, output, result_path):
    started = time.perf_counter()
    db = sqlite3.connect('file:' + str(source.resolve()) + '?mode=ro&immutable=1', uri=True)
    sql = sqlite3.connect('file:' + str((output/'runtime.sqlite').resolve()) + '?mode=ro&immutable=1', uri=True)
    src = SourceRows(db, schema(db))
    pack = Pack(output/'runtime.pack')
    original = iter(db.execute('SELECT w.*,g.points_json FROM ways w JOIN way_geom g USING(way_id) ORDER BY way_id'))
    target = iter(sql.execute('SELECT way_id,record,geometry FROM road ORDER BY way_id'))
    block_cache = {}
    def sqlmeta(record):
        offset, left = record[6], record[8]
        out = bytearray()
        while left:
            i, pos = divmod(offset, BLOCK_SIZE)
            if i not in block_cache:
                rawsize, crc, encoded = sql.execute('SELECT raw_size,crc,data FROM block WHERE block_id=?',(i,)).fetchone()
                raw = zlib.decompress(encoded)
                assert len(raw) == rawsize and zlib.crc32(raw) == crc
                block_cache.clear()
                block_cache[i] = raw
            raw = block_cache[i]
            n = min(left, len(raw)-pos)
            out.extend(raw[pos:pos+n]);left-=n;offset+=n
        return bytes(out)
    hsource, hsql, hpack = [hashlib.sha256() for _ in range(3)]
    count = points_count = 0
    for count, row in enumerate(original, 1):
        way, points = row[:-1], json.loads(row[-1])
        assert all(round(v*1e7)/1e7==v for v in way[-4:]), ('non-E7 source bounds require outward fallback',way[0])
        way_id, encoded, sqlgeom = next(target)
        packed_record = pack.map[pack.road_offset+(count-1)*ROAD.size:pack.road_offset+count*ROAD.size]
        assert packed_record == encoded, ('record mismatch', way[0])
        record = ROAD.unpack(packed_record)
        assert record[0] == way_id == way[0]
        packgeom = pack.map[pack.geom_offset+record[5]:pack.geom_offset+record[5]+record[7]]
        assert sqlgeom == packgeom
        assert decode_geometry(sqlgeom) == points, ('SQL geometry mismatch',way_id)
        assert decode_geometry(packgeom) == points, ('packed geometry mismatch',way_id)
        payload = src.payload(way)
        sqldata, packdata = sqlmeta(record), pack.metadata(record)
        assert sqldata == payload, ('SQL semantic mismatch',way_id)
        assert packdata == payload, ('packed semantic mismatch',way_id)
        assert zlib.crc32(payload) == record[-2]
        identity = struct.pack('<qI', way_id, len(payload))
        for h, data in zip((hsource,hsql,hpack),(payload,sqldata,packdata)):
            h.update(identity);h.update(data)
            for p in points:
                h.update(struct.pack('<dd',*p))
        points_count += len(points)
        if count % 100000 == 0:
            print('verified ways',count,'seconds',round(time.perf_counter()-started,1),flush=True)
    assert next(target,None) is None and count == pack.count
    archive = json.loads((output/'source-semantics.index.json').read_text())
    # Verify each table independently against fresh original SQL iteration and archived bytes.
    entries = archive['blocks']
    archive_file = (output/'source-semantics.zblocks').open('rb')
    cached = {}
    def archive_bytes(offset,length):
        while length:
            i,pos = divmod(offset,BLOCK_SIZE)
            if i not in cached:
                off,size,rawsize,crc=entries[i]
                archive_file.seek(off);raw=zlib.decompress(archive_file.read(size))
                assert len(raw)==rawsize and zlib.crc32(raw)==crc
                cached.clear();cached[i]=raw
            raw=cached[i];n=min(length,len(raw)-pos)
            assert n>0
            yield raw[pos:pos+n];offset+=n;length-=n
    table_counts = {}
    for table, info in archive['tables'].items():
        order=','.join('"'+v+'"' for v in info['order_by'])
        expected, actual=hashlib.sha256(),hashlib.sha256()
        rows=0
        for row in db.execute(f'SELECT * FROM "{table}" ORDER BY {order}'):
            expected.update(canonical(list(row))+b'\n');rows+=1
        for data in archive_bytes(info['logical_offset'],info['logical_bytes']):
            actual.update(data)
        assert expected.hexdigest()==actual.hexdigest()==info['sha256'],('archive mismatch',table)
        assert rows==info['rows']
        table_counts[table]=rows
        print('verified archive',table,rows,flush=True)
    result={'ways':count,'points':points_count,'all_source_geometries_exact':True,
            'all_source_per_way_rows_exact_in_both_backends':True,
            'canonical_original_sha256':hsource.hexdigest(),'canonical_sqlite_sha256':hsql.hexdigest(),
            'canonical_packed_sha256':hpack.hexdigest(),'complete_original_source_archive_verified':True,
            'archive_table_counts':table_counts,'elapsed_seconds':time.perf_counter()-started}
    result_path.write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2),flush=True)
    archive_file.close();pack.close();db.close();sql.close()


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--source',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True);p.add_argument('--result',type=Path,required=True)
    a=p.parse_args();verify(a.source,a.output_dir,a.result)
