#!/usr/bin/env python3
"""Independent format fixtures and native VFS/read/cache/corruption checks."""
import argparse
import concurrent.futures
import ctypes as c
import ctypes.util
import hashlib
import json
from pathlib import Path
import random
import sqlite3
import struct
import subprocess
import tempfile
import unittest
import zlib

BLOCK=262144
LIBRARY=CHECK=NODEBENCH=NODELIBRARY=None
ZSTD=None


def zstd(raw):
    global ZSTD
    if ZSTD is None:
        for name in (ctypes.util.find_library('zstd'),'/opt/homebrew/lib/libzstd.dylib','/opt/local/lib/libzstd.dylib','libzstd.so.1'):
            if not name:continue
            try:ZSTD=c.CDLL(name);break
            except OSError:pass
        if ZSTD is None:raise unittest.SkipTest('zstd compressor unavailable for independent codec-2 fixtures')
        ZSTD.ZSTD_compressBound.argtypes=[c.c_size_t];ZSTD.ZSTD_compressBound.restype=c.c_size_t
        ZSTD.ZSTD_compress.argtypes=[c.c_void_p,c.c_size_t,c.c_void_p,c.c_size_t,c.c_int];ZSTD.ZSTD_compress.restype=c.c_size_t
        ZSTD.ZSTD_isError.argtypes=[c.c_size_t];ZSTD.ZSTD_isError.restype=c.c_uint
    source=c.create_string_buffer(bytes(raw));output=c.create_string_buffer(ZSTD.ZSTD_compressBound(len(raw)));size=ZSTD.ZSTD_compress(output,len(output),source,len(raw),15)
    assert not ZSTD.ZSTD_isError(size)
    return output.raw[:size]


def container(payload,geometry=None,codec=1,transform=None):
    index=b'' if geometry is None else b''.join(struct.pack('<qQII',*row) for row in geometry)
    directory=bytearray();encoded=bytearray()
    for start in range(0,len(payload),BLOCK):
        raw=payload[start:start+BLOCK];data=zlib.compress(raw,6) if codec==1 else zstd(raw)
        if transform:data=transform(data,start//BLOCK)
        directory.extend(struct.pack('<QIIII',len(encoded),len(data),len(raw),zlib.crc32(raw),0));encoded.extend(data)
    header=bytearray(128);directory_offset=128+len(index);data_offset=directory_offset+len(directory)
    struct.pack_into('<8sIIIIQQQQQQQ',header,0,b'YSPCTX1\0' if geometry is None else b'YSPGEO1\0',1,0x01020304,128,BLOCK,len(payload),len(directory)//24,directory_offset,data_offset,data_offset+len(encoded),0 if geometry is None else len(geometry),0 if geometry is None else 128)
    struct.pack_into('<II',header,80,zlib.crc32(directory),zlib.crc32(index));struct.pack_into('<I',header,88,zlib.crc32(header[:88]));struct.pack_into('<I',header,92,codec);header[96:]=hashlib.sha256(b'independent fixture source').digest()
    return header+index+directory+encoded


def refresh(data,index=False,directory=False):
    directory_offset=struct.unpack_from('<Q',data,40)[0];data_offset=struct.unpack_from('<Q',data,48)[0]
    if index:struct.pack_into('<I',data,84,zlib.crc32(data[128:directory_offset]))
    if directory:struct.pack_into('<I',data,80,zlib.crc32(data[directory_offset:data_offset]))
    struct.pack_into('<I',data,88,zlib.crc32(data[:88]))


class PackedRuntime(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp=tempfile.TemporaryDirectory(prefix='ysp-production-format-');cls.root=Path(cls.tmp.name)
        cls.api=c.CDLL(str(LIBRARY))
        for prefix in ('context','geometry'):
            fn=getattr(cls.api,'ysp_'+prefix+'_open');fn.argtypes=[c.c_char_p,c.c_uint64,c.c_void_p,c.c_size_t];fn.restype=c.c_void_p
            getattr(cls.api,'ysp_'+prefix+'_close').argtypes=[c.c_void_p]
            fn=getattr(cls.api,'ysp_'+prefix+'_stats_json');fn.argtypes=[c.c_void_p];fn.restype=c.c_void_p
        cls.api.ysp_context_size.argtypes=[c.c_void_p];cls.api.ysp_context_size.restype=c.c_uint64
        cls.api.ysp_context_read.argtypes=[c.c_void_p,c.c_uint64,c.c_void_p,c.c_size_t,c.c_void_p,c.c_size_t];cls.api.ysp_context_read.restype=c.c_int64
        cls.api.ysp_geometry_json.argtypes=[c.c_void_p,c.c_char_p,c.c_void_p,c.c_size_t];cls.api.ysp_geometry_json.restype=c.c_void_p
        cls.api.ysp_packed_free.argtypes=[c.c_void_p]
        source=cls.root/'source.sqlite';db=sqlite3.connect(source)
        db.executescript('CREATE TABLE ways(way_id INTEGER PRIMARY KEY,speed TEXT);CREATE TABLE way_geom(way_id INTEGER PRIMARY KEY,points_json TEXT,quality TEXT);CREATE TABLE restriction(way_id INTEGER,raw TEXT);')
        cls.geometry={10:'[[48.1000000, 9e0],[48.1,9.2]]',20:'[]',9007199254740993:'['+','.join(['[48.1234567,9.1234567]']*16000)+']'}
        for key,text in cls.geometry.items():db.execute('INSERT INTO ways VALUES(?,?)',(key,'50'));db.execute('INSERT INTO way_geom VALUES(?,?,?)',(key,text,'unchanged'))
        db.execute('INSERT INTO ways VALUES(?,?)',(42,None));db.execute('INSERT INTO restriction VALUES(?,?)',(10,'30 @ (weight > 7.5)'));db.commit();db.close()
        payload=bytearray();rows=[]
        for key,text in sorted(cls.geometry.items()):
            raw=text.encode();rows.append((key,len(payload),len(raw),zlib.crc32(raw)));payload.extend(raw)
        cls.geo=cls.root/'ways.yspg';cls.geo.write_bytes(container(payload,rows))
        cls.raw=cls.root/'context.sqlite';source_db=sqlite3.connect(source);context_db=sqlite3.connect(cls.raw);source_db.backup(context_db);source_db.close()
        context_db.executescript("CREATE TABLE ysp_geometry_keys AS SELECT way_id,quality FROM way_geom;DROP TABLE way_geom;CREATE VIEW way_geom AS SELECT way_id,ysp_way_points_json(CAST(way_id AS TEXT)) AS points_json,quality FROM ysp_geometry_keys;");context_db.commit();context_db.execute('VACUUM');context_db.close()
        cls.context=cls.root/'context.yspc';cls.context.write_bytes(container(cls.raw.read_bytes()))
        cls.large_payload=b'SQLite format 3\0'+bytes(range(256))*((40*BLOCK-16)//256)+bytes(range((40*BLOCK-16)%256))
        cls.large=cls.root/'large.yspc';cls.large.write_bytes(container(cls.large_payload))

    @classmethod
    def tearDownClass(cls):cls.tmp.cleanup()

    def opened(self,path,geometry=False,cache=0):
        error=c.create_string_buffer(512);handle=getattr(self.api,'ysp_'+('geometry' if geometry else 'context')+'_open')(str(path).encode(),cache,error,len(error));self.assertTrue(handle,error.value);return handle

    def stats(self,handle,geometry=False):
        value=getattr(self.api,'ysp_'+('geometry' if geometry else 'context')+'_stats_json')(handle);self.assertTrue(value);raw=c.string_at(value);self.api.ysp_packed_free(value);return json.loads(raw)

    def read(self,handle,offset,count):
        buffer=c.create_string_buffer(count);error=c.create_string_buffer(512);actual=self.api.ysp_context_read(handle,offset,buffer,count,error,len(error));self.assertGreaterEqual(actual,0,error.value);return buffer.raw[:actual]

    def test_cross_block_read_and_eof(self):
        handle=self.opened(self.context)
        try:
            raw=self.raw.read_bytes();self.assertEqual(self.api.ysp_context_size(handle),len(raw))
            for offset,count in [(0,16),(BLOCK-11,4096),(len(raw)-9,20),(len(raw)+1,20)]:self.assertEqual(self.read(handle,offset,count),raw[offset:offset+count])
        finally:self.api.ysp_context_close(handle)

    def test_exact_geometry_and_int64_identity(self):
        handle=self.opened(self.geo,True)
        try:
            for key,expected in self.geometry.items():
                error=c.create_string_buffer(512);value=self.api.ysp_geometry_json(handle,str(key).encode(),error,len(error));self.assertTrue(value,error.value);self.assertEqual(c.string_at(value),expected.encode());self.api.ysp_packed_free(value)
            self.assertEqual(self.stats(handle,True)['file']['mapped_bytes'],0)
        finally:self.api.ysp_geometry_close(handle)

    def test_actual_cache_caps_and_thread_safe_reads(self):
        for capacity in (2*BLOCK,8*1024*1024):
            handle=self.opened(self.large,cache=capacity)
            try:
                for offset in range(0,len(self.large_payload),BLOCK):self.assertEqual(self.read(handle,offset,BLOCK),self.large_payload[offset:offset+BLOCK])
                rng=random.Random(20261027);ranges=[(rng.randrange(len(self.large_payload)-7000),7000) for _ in range(80)]
                with concurrent.futures.ThreadPoolExecutor(max_workers=4) as workers:
                    results=list(workers.map(lambda pair:self.read(handle,*pair),ranges))
                self.assertEqual(results,[self.large_payload[o:o+n] for o,n in ranges]);stats=self.stats(handle)
                self.assertEqual(stats['block_cache_capacity_bytes'],capacity);self.assertLessEqual(stats['block_cache_peak_bytes'],capacity)
                self.assertEqual(stats['block_cache_resident_bytes']%BLOCK,0);self.assertEqual(stats['block_cache_peak_bytes']%BLOCK,0);self.assertLessEqual(stats['encoded_scratch_capacity_bytes'],BLOCK+1024)
                self.assertLessEqual(stats['file']['page_cache_peak_bytes'],stats['file']['page_cache_capacity_bytes']);self.assertEqual(stats['file']['mapped_bytes'],0)
            finally:self.api.ysp_context_close(handle)

    def test_vfs_join_restrictions_missing_geometry_and_read_only(self):
        sql='SELECT w.way_id,g.points_json,g.quality,r.raw FROM ways w LEFT JOIN way_geom g USING(way_id) LEFT JOIN restriction r USING(way_id) ORDER BY CAST(w.way_id AS TEXT) COLLATE BINARY'
        db=sqlite3.connect(self.root/'source.sqlite');expected=[list(row) for row in db.execute(sql)];db.close()
        def run(query):return subprocess.run([str(CHECK),'query',str(self.context),str(self.geo),query],capture_output=True,text=True)
        result=run(sql);self.assertEqual(result.returncode,0,result.stdout);report=json.loads(result.stdout);self.assertEqual(report['rows'],expected)
        self.assertEqual(report['context_io_stats']['block_cache_capacity_bytes'],2*1024*1024);self.assertEqual(report['geometry_io_stats']['block_cache_capacity_bytes'],512*1024);self.assertEqual(report['context_io_stats']['file']['mapped_bytes'],0)
        self.assertEqual(report['context_io_stats']['source_sqlite_sha256'],hashlib.sha256(b'independent fixture source').hexdigest());self.assertEqual(report['context_io_stats']['source_sqlite_sha256'],report['geometry_io_stats']['source_sqlite_sha256'])
        self.assertEqual(json.loads(run('PRAGMA integrity_check').stdout)['rows'],[['ok']]);self.assertEqual(json.loads(run('PRAGMA mmap_size').stdout)['rows'],[[0]])
        self.assertEqual(json.loads(run('PRAGMA cache_size').stdout)['rows'],[[-1536]])
        result=run("UPDATE ways SET speed='999'");self.assertNotEqual(result.returncode,0);self.assertIn('error',json.loads(result.stdout))

    def rejected(self,data,geometry=False):
        path=self.root/'invalid-pack';path.write_bytes(data);error=c.create_string_buffer(512);value=getattr(self.api,'ysp_'+('geometry' if geometry else 'context')+'_open')(str(path).encode(),0,error,len(error));self.assertFalse(value);self.assertTrue(error.value)

    def test_malformed_headers_and_overflowing_block_offsets(self):
        original=self.context.read_bytes();self.rejected(original[:80]);data=bytearray(original);struct.pack_into('<I',data,8,9);refresh(data);self.rejected(data)
        data=bytearray(original);struct.pack_into('<Q',data,40,2**64-1);refresh(data);self.rejected(data)
        data=bytearray(original);directory=struct.unpack_from('<Q',data,40)[0];struct.pack_into('<Q',data,directory,2**64-128);refresh(data,directory=True);self.rejected(data)
        data=bytearray(original);struct.pack_into('<I',data,directory+20,1);refresh(data,directory=True);self.rejected(data)

    def test_corrupt_blocks_and_geometry_index(self):
        data=bytearray(self.context.read_bytes());offset=struct.unpack_from('<Q',data,48)[0];data[offset+3]^=0x55;self.rejected(data)
        data=bytearray(self.geo.read_bytes());struct.pack_into('<q',data,128+24,10);refresh(data,index=True);self.rejected(data,True)
        data=bytearray(self.geo.read_bytes());offset=struct.unpack_from('<Q',data,48)[0];data[offset+3]^=0x55;path=self.root/'bad-geometry-block';path.write_bytes(data);handle=self.opened(path,True)
        try:
            error=c.create_string_buffer(512);self.assertFalse(self.api.ysp_geometry_json(handle,b'10',error,len(error)));self.assertTrue(error.value)
        finally:self.api.ysp_geometry_close(handle)

    def test_valid_empty_geometry(self):
        path=self.root/'empty.yspg';path.write_bytes(container(b'',[]));handle=self.opened(path,True)
        try:
            error=c.create_string_buffer(512);self.assertFalse(self.api.ysp_geometry_json(handle,b'10',error,len(error)));self.assertIn(b'absent',error.value)
        finally:self.api.ysp_geometry_close(handle)

    def test_codec2_exact_cross_block_geometry_and_cache_bound(self):
        payload=self.large_payload[:3*BLOCK];path=self.root/'zstd.yspc';path.write_bytes(container(payload,codec=2));handle=self.opened(path,cache=2*BLOCK)
        try:
            self.assertEqual(self.read(handle,BLOCK-31,BLOCK+100),payload[BLOCK-31:2*BLOCK+69]);stats=self.stats(handle);self.assertEqual(stats['codec'],2);self.assertLessEqual(stats['block_cache_peak_bytes'],2*BLOCK);self.assertGreater(stats['decoder_workspace_bytes'],0);self.assertLessEqual(stats['decoder_workspace_bytes'],BLOCK)
        finally:self.api.ysp_context_close(handle)
        original=self.geo.read_bytes();count=struct.unpack_from('<Q',original,64)[0];rows=[struct.unpack_from('<qQII',original,128+i*24) for i in range(count)];raw=b''.join(self.geometry[key].encode() for key in sorted(self.geometry));path=self.root/'zstd.yspg';path.write_bytes(container(raw,rows,codec=2));handle=self.opened(path,True)
        try:
            for key,expected in self.geometry.items():
                error=c.create_string_buffer(512);value=self.api.ysp_geometry_json(handle,str(key).encode(),error,len(error));self.assertTrue(value,error.value);self.assertEqual(c.string_at(value),expected.encode());self.api.ysp_packed_free(value)
        finally:self.api.ysp_geometry_close(handle)

    def test_codec2_rejects_dictionary_large_window_wrong_size_and_extra_frame(self):
        payload=b'SQLite format 3\0'+b'A'*(BLOCK-16)
        def changed(kind):
            def transform(frame,index):
                self.assertTrue(frame[4]&32,'fixture needs single-segment frame')
                if kind=='dictionary':return frame[:4]+bytes([frame[4]|1,1])+frame[5:]
                if kind=='window':return frame[:4]+bytes([frame[4]&~32,72])+frame[5:]
                if kind=='size':return frame[:5]+bytes([frame[5]^1])+frame[6:]
                if kind=='extra_frame':return frame+zstd(b'')
                raise AssertionError(kind)
            return transform
        for kind in ('dictionary','window','size','extra_frame'):
            with self.subTest(kind=kind):self.rejected(container(payload,codec=2,transform=changed(kind)))
        data=bytearray(container(payload,codec=2));directory=struct.unpack_from('<Q',data,40)[0];struct.pack_into('<I',data,directory+16,1234);refresh(data,directory=True);self.rejected(data)
        data=bytearray(container(payload,codec=2));struct.pack_into('<I',data,92,99);self.rejected(data)

    def test_valid_empty_generic_nodes(self):
        if not NODEBENCH:self.skipTest('nodebench not provided')
        header=bytearray(128);struct.pack_into('<8sIIQQQQQII',header,0,b'YSPNODE1',1,0x01020304,0,128,128,128,128,0,0);struct.pack_into('<I',header,64,zlib.crc32(header[:64]));path=self.root/'empty.yspn';path.write_bytes(header)
        result=subprocess.run([str(NODEBENCH),'query','packed',str(path),'48','9','80'],capture_output=True,text=True);self.assertEqual(result.returncode,0,result.stdout);self.assertEqual(json.loads(result.stdout),[])
        result=subprocess.run([str(NODEBENCH),'roundtrip','packed',str(path)],capture_output=True,text=True);self.assertEqual(result.returncode,0,result.stdout);self.assertEqual(json.loads(result.stdout)['nodes'],0)

    def test_source_complete_country_independent_persistent_nodes_and_empty_sql(self):
        if not NODELIBRARY or not NODEBENCH:self.skipTest('node library/CLI not provided')
        api=c.CDLL(str(NODELIBRARY));api.ysp_nodes_open.argtypes=[c.c_char_p,c.c_uint64,c.c_void_p,c.c_size_t];api.ysp_nodes_open.restype=c.c_void_p
        api.ysp_nodes_json.argtypes=[c.c_void_p,c.c_char_p,c.c_void_p,c.c_size_t];api.ysp_nodes_json.restype=c.c_void_p
        api.ysp_nodes_query_json.argtypes=[c.c_void_p,c.c_double,c.c_double,c.c_double,c.c_void_p,c.c_size_t];api.ysp_nodes_query_json.restype=c.c_void_p
        api.ysp_nodes_stats_json.argtypes=[c.c_void_p];api.ysp_nodes_stats_json.restype=c.c_void_p;api.ysp_nodes_close.argtypes=[c.c_void_p];api.ysp_nodes_free.argtypes=[c.c_void_p]
        repo=Path(__file__).resolve().parents[3]
        def consume(pointer):self.assertTrue(pointer);value=json.loads(c.string_at(pointer));api.ysp_nodes_free(pointer);return value
        for name,nodes in [('empty',[]),('country_nodes',[{'osm_node_id':1,'latitude':48.0,'longitude':9.0,'memberships':[],'tags':{'traffic_sign':'FR:B14','maxspeed:conditional':'30 @ (weight > 7.5)'}},{'osm_node_id':2,'latitude':48.000002,'longitude':9.0,'memberships':[],'tags':{'traffic_sign':'CH:2.30','maxspeed':'signals'}}])]:
            source=self.root/(name+'.json');source.write_text(json.dumps({'node_count':len(nodes),'nodes':nodes}));out=self.root/name
            subprocess.run(['python3',str(repo/'scripts/map/runtime_storage_nodes/build.py'),str(source),str(out)],capture_output=True,text=True,check=True)
            for backend,filename in [('packed','nodes.yspn'),('sqlite','nodes.sqlite')]:
                report=json.loads(subprocess.check_output([str(NODEBENCH),'roundtrip',backend,str(out/filename)],text=True));self.assertEqual(report['nodes'],len(nodes))
            error=c.create_string_buffer(512);handle=api.ysp_nodes_open(str(out/'nodes.yspn').encode(),0,error,len(error));self.assertTrue(handle,error.value)
            try:
                result=consume(api.ysp_nodes_query_json(handle,48,9,80,error,len(error)));self.assertEqual(result,nodes)
                result=consume(api.ysp_nodes_json(handle,b'999',error,len(error)));self.assertIsNone(result)
                stats=consume(api.ysp_nodes_stats_json(handle));self.assertEqual(stats['nodes'],len(nodes));self.assertEqual(stats['file']['mapped_bytes'],0);self.assertLessEqual(stats['file']['page_cache_peak_bytes'],512*1024)
            finally:api.ysp_nodes_close(handle)


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--library',type=Path,required=True);p.add_argument('--check',type=Path,required=True);p.add_argument('--nodebench',type=Path);p.add_argument('--nodes-library',type=Path);a,rest=p.parse_known_args();LIBRARY=a.library.resolve();CHECK=a.check.resolve();NODEBENCH=a.nodebench.resolve() if a.nodebench else None;NODELIBRARY=a.nodes_library.resolve() if a.nodes_library else None;unittest.main(argv=['test_packed_runtime.py',*rest])
