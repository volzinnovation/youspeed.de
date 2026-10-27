#!/usr/bin/env python3
"""Meaningful format regressions: source fidelity, spatial borders and malformed files."""
import argparse
import contextlib
import io
import json
from pathlib import Path
import sqlite3
import struct
import subprocess
import tempfile
import unittest
import zlib

from build import build, geometry, decode_geometry, ROAD, varint
from compact_globals import compact
from verify import verify

BINARY = None


class StorageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory(prefix='ysp-storage-test-')
        cls.out = Path(cls.tmp.name)/'out'
        cls.source = Path(cls.tmp.name)/'source.sqlite'
        d = sqlite3.connect(cls.source)
        d.executescript('''CREATE TABLE ways(way_id INTEGER PRIMARY KEY,highway TEXT,street_name TEXT,ref TEXT,maxspeed TEXT,maxspeed_forward TEXT,maxspeed_backward TEXT,maxspeed_type TEXT,source_maxspeed TEXT,approx_heading_deg REAL,service TEXT,tunnel TEXT,min_lon REAL,min_lat REAL,max_lon REAL,max_lat REAL);
        CREATE TABLE way_geom(way_id INTEGER PRIMARY KEY,points_json TEXT);
        CREATE TABLE road_speed_source_tag(way_id INTEGER,key TEXT,raw_value TEXT,source_snapshot TEXT,PRIMARY KEY(way_id,key));
        CREATE TABLE traffic_sign_way_rule(rule_id TEXT PRIMARY KEY,sign_id TEXT,way_id INTEGER,direction INTEGER,station_chainage_m REAL,speed_kmh REAL);
        CREATE TABLE generic_node(node_id INTEGER PRIMARY KEY,lat REAL,lon REAL,tags_json TEXT);''')
        for i in range(70):
            lat,lon=round(48+i*.001,7),round(9+i*.001,7)
            points=[[lat,lon],[round(lat+.0005,7),round(lon+.0005,7)],[round(lat+.001,7),round(lon+.001,7)]]
            d.execute('INSERT INTO ways VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',(i+1,'residential','Straße "ß"',None,'50',None,'30',None,'sign',45,None,None,lon,lat,points[-1][1],points[-1][0]))
            d.execute('INSERT INTO way_geom VALUES(?,?)',(i+1,json.dumps(points)))
        d.execute('INSERT INTO road_speed_source_tag VALUES(?,?,?,?)',(1,'maxspeed:conditional','30 @ (Mo-Fr 22:00-06:00; wet)','pinned'))
        d.execute('INSERT INTO traffic_sign_way_rule VALUES(?,?,?,?,?,?)',('rule-1','node:123',1,-1,13.123456789,30))
        d.execute('INSERT INTO generic_node VALUES(?,?,?,?)',(123,48,9,'{"traffic_sign":"DE:274","maxspeed":"signals"}'))
        d.commit();d.close()
        with contextlib.redirect_stdout(io.StringIO()):
            build(cls.source,cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def call(self,command,kind,path,*args):
        p=subprocess.run([str(BINARY),command,kind,str(path),*map(str,args)],capture_output=True,text=True)
        return p.returncode,json.loads(p.stdout)

    def test_geometry_fallback_and_signed_deltas(self):
        for points in ([[[48,9],[47.9999999,8.9999999],[-80,-170]]],):
            for p in points:
                self.assertEqual(decode_geometry(geometry(p)),p)
        p=[[48.123456789123,9.123456789123],[48.1,9.0]]
        self.assertEqual(geometry(p)[0],1)
        self.assertEqual(decode_geometry(geometry(p)),p)

    def test_original_semantic_and_geometry_fidelity(self):
        expected=None
        for kind,filename in [('packed','runtime.pack'),('sqlite','runtime.sqlite')]:
            rc,value=self.call('way',kind,self.out/filename,1)
            self.assertEqual(rc,0)
            self.assertEqual(value['geometry'],[[48,9],[48.0005,9.0005],[48.001,9.001]])
            self.assertEqual(value['semantic']['road_speed_source_tag'][0][2],'30 @ (Mo-Fr 22:00-06:00; wet)')
            self.assertEqual(value['semantic']['traffic_sign_way_rule'][0][-2],13.123456789)
            if expected is not None:self.assertEqual(value,expected)
            expected=value

    def test_spatial_boundaries_and_exact_backend_parity(self):
        for lat,lon,radius in [(48,9,1),(48.032,9.032,150),(48.0699,9.0699,20),(48.01,9.009,200),(0,0,100)]:
            _,a=self.call('query','packed',self.out/'runtime.pack',lat,lon,radius)
            _,b=self.call('query','sqlite',self.out/'runtime.sqlite',lat,lon,radius)
            self.assertEqual(a,b)
            if (lat,lon)==(0,0):self.assertEqual(a,[])
        _,a=self.call('query','packed',self.out/'runtime.pack',48,9,1)
        self.assertEqual([r['way_id'] for r in a],[1])

    def bad(self,name,data,command='way',*args):
        p=Path(self.tmp.name)/name;p.write_bytes(data)
        rc,result=self.call(command,'packed',p,*(args or (1,)))
        self.assertEqual(rc,1)
        self.assertIn('error',result)

    def test_truncated_and_unsupported_format(self):
        data=bytearray((self.out/'runtime.pack').read_bytes())
        self.bad('truncated',data[:60])
        self.bad('truncated-block',data[:-1])
        struct.pack_into('<I',data,8,2)
        struct.pack_into('<I',data,128,zlib.crc32(data[:128]))
        self.bad('version',data)

    def test_corrupt_geometry_and_semantic_block_fail_closed(self):
        data=bytearray((self.out/'runtime.pack').read_bytes())
        geom_offset=struct.unpack_from('<Q',data,16+5*8)[0]
        data[geom_offset+4]^=1
        self.bad('geometry-crc',data)
        data=bytearray((self.out/'runtime.pack').read_bytes())
        blocks_offset=struct.unpack_from('<Q',data,16+10*8)[0]
        data[blocks_offset+4]^=0x7f
        self.bad('semantic-crc',data)

    def test_invalid_offsets_and_cyclic_spatial_index(self):
        data=bytearray((self.out/'runtime.pack').read_bytes())
        struct.pack_into('<Q',data,160+24,2**63)
        self.bad('bad-geometry-offset',data)
        data=bytearray((self.out/'runtime.pack').read_bytes())
        nodes_offset=struct.unpack_from('<Q',data,16+7*8)[0]
        struct.pack_into('<I',data,nodes_offset+16,0)
        self.bad('cyclic-spatial',data,'query',48,9,100)

    def test_structured_invalid_delta_rejected_after_valid_checksums(self):
        data=bytearray((self.out/'runtime.pack').read_bytes())
        geom_offset=struct.unpack_from('<Q',data,16+5*8)[0]
        encoded=bytes([0,3,1,0])+bytes(varint(2**64-1))+bytes([0,0,0])
        data[geom_offset:geom_offset+len(encoded)]=encoded
        road=list(ROAD.unpack_from(data,160));road[7]=len(encoded);road[-1]=zlib.crc32(encoded)
        ROAD.pack_into(data,160,*road)
        struct.pack_into('<I',data,132,zlib.crc32(data[160:geom_offset]))
        self.bad('invalid-delta-valid-crc',data)

    def test_block_offset_wrap_rejected_after_valid_index_checksum(self):
        data=bytearray((self.out/'runtime.pack').read_bytes())
        blockdir=struct.unpack_from('<Q',data,16+9*8)[0]
        blockdata=struct.unpack_from('<Q',data,16+10*8)[0]
        struct.pack_into('<Q',data,blockdir,2**64-blockdata+160)
        struct.pack_into('<I',data,144,zlib.crc32(data[blockdir:blockdata]))
        self.bad('wrapped-block-offset-valid-crc',data)

    def test_complete_table_hash_reconstruction_deduplicates_global_archive(self):
        result=Path(self.tmp.name)/'full-verification.json'
        with contextlib.redirect_stdout(io.StringIO()):
            verify(self.source,self.out,result)
            compact(self.source,self.out,result)
        proof=json.loads((self.out/'compact-coverage-verification.json').read_text())
        self.assertTrue(proof['all_original_table_hashes_reconstructed_exactly'])
        self.assertEqual(proof['source_tables'],5)
        self.assertTrue(proof['raw_geometry_json_spelling_preserved'])
        self.assertEqual(proof['table_proofs']['traffic_sign_way_rule']['rows'],1)
        index=json.loads((self.out/'runtime-globals.index.json').read_text())
        self.assertEqual(index['tables']['ways']['storage'],'native_per_way_semantic_records')
        self.assertEqual(index['tables']['way_geom']['storage'],'runtime_globals')
        self.assertEqual(index['tables']['generic_node']['storage'],'runtime_globals')


if __name__=='__main__':
    ap=argparse.ArgumentParser();ap.add_argument('--binary',type=Path,required=True)
    a,rest=ap.parse_known_args();BINARY=a.binary.resolve();unittest.main(argv=['test_storage.py',*rest])
