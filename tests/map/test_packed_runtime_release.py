import hashlib
import json
from pathlib import Path
import sqlite3
import struct
import sys
import tempfile
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts/map'))
import packed_runtime as packed
from extract_packed_sign_nodes import Memberships, relevant
from pack_sign_nodes import pack as pack_nodes


class PackedRuntimeReleaseTests(unittest.TestCase):
    def test_both_codecs_cross_blocks_and_eof(self):
        raw=hashlib.shake_256(b'packed deterministic cross-block source').digest(packed.BLOCK*3+101)
        with tempfile.TemporaryDirectory() as temp:
            for codec in [1,2]:
                path=Path(temp)/str(codec)
                packed.pack_chunks([raw[:17],raw[17:]],path,hashlib.sha256(raw).hexdigest(),codec=codec)
                reader=packed.Reader(path)
                self.assertEqual(reader.read(13,len(raw)),raw[13:])
                self.assertEqual(reader.read(packed.BLOCK-1,3),raw[packed.BLOCK-1:packed.BLOCK+2])
                self.assertEqual(reader.read(len(raw),100),b'')
                reader.close()

    def test_context_preserves_rowids_types_restrictions_and_missing_geometry(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'source.sqlite';db=sqlite3.connect(source)
            db.executescript('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);CREATE TABLE ways(way_id INTEGER PRIMARY KEY);CREATE TABLE way_geom(way_id INTEGER PRIMARY KEY,points_json TEXT NOT NULL);CREATE TABLE evidence(value,rule TEXT);')
            db.executemany('INSERT INTO ways VALUES(?)',[(10,),(20,),(9007199254740993,)])
            text='[[48.1000000, 9.2000000],[48.100001,9.200001]]'
            db.executemany('INSERT INTO way_geom VALUES(?,?)',[(10,text),(9007199254740993,'[[49,8]]')])
            db.executemany('INSERT INTO evidence(rowid,value,rule) VALUES(?,?,?)',[(2,b'\x00\xff','30 @ (weight>7.5)'),(19,None,'signals')])
            db.commit();source_sha=packed.digest(source)
            geometry=root/'roads.yspg';context=root/'context.yspc'
            packed.build_geometry(db,geometry,source_sha)
            packed.build_context(source,geometry,context,source_sha,'test-one')
            image=packed.Reader(context);logical=root/'logical.sqlite';logical.write_bytes(image.read(0,image.logical));image.close()
            native=packed.Reader(geometry);result=sqlite3.connect(logical);result.create_function('ysp_way_points_json',1,native.geometry)
            self.assertEqual(result.execute('SELECT rowid,* FROM evidence').fetchall(),db.execute('SELECT rowid,* FROM evidence').fetchall())
            self.assertEqual(result.execute('SELECT * FROM ways JOIN way_geom USING(way_id) ORDER BY way_id').fetchall(),db.execute('SELECT * FROM ways JOIN way_geom USING(way_id) ORDER BY way_id').fetchall())
            self.assertEqual(native.geometry(10),text)
            self.assertEqual(native.geometry(9007199254740993),'[[49,8]]')
            self.assertIsNone(native.geometry(20))
            self.assertEqual(packed.digest(source),source_sha)
            result.close();native.close();db.close()

    def test_corrupt_block_fails_closed(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'source';packed.pack_chunks([b'raw bytes'*50000],path,'00'*32)
            raw=bytearray(path.read_bytes());offset=struct.unpack_from('<Q',raw,48)[0];raw[offset]^=0x80;path.write_bytes(raw)
            reader=packed.Reader(path)
            with self.assertRaises(ValueError):
                reader.read(0,100)
            reader.close()

    def test_empty_generic_nodes_and_international_tags(self):
        self.assertTrue(relevant({'traffic_sign':'FR:B14:50'}))
        self.assertTrue(relevant({'traffic_sign:backward':'CH:2.30'}))
        self.assertTrue(relevant({'maxspeed:hgv:conditional':'30 @ (weight>7.5)'}))
        self.assertFalse(relevant({'amenity':'bench'}))
        self.assertFalse(relevant({'traffic_signals':'signal'}))
        with tempfile.TemporaryDirectory() as temp:
            source=Path(temp)/'nodes.json';source.write_text(json.dumps({'nodes':[],'node_count':0}))
            output=Path(temp)/'nodes.yspn';pack_nodes(source,output)
            self.assertEqual(output.stat().st_size,128)
            self.assertEqual(struct.unpack_from('<Q',output.read_bytes(),16)[0],0)

    def test_snapshot_mismatch_retains_source_membership_without_binding(self):
        database=sqlite3.connect(':memory:');database.execute('CREATE TABLE way_geom(way_id INTEGER,points_json TEXT)')
        database.execute('INSERT INTO way_geom VALUES(10,?)',('[[48,9],[49,10]]',))
        node={'latitude':47.0,'longitude':8.0,'memberships':[],'source_way_memberships':[],'binding_status':'no_admitted_source_way'}
        handler=Memberships(database,{99:node})
        class Ref:
            def __init__(self,ref):self.ref=ref
        class Way:
            id=10
            nodes=[Ref(99),Ref(100)]
        handler.way(Way())
        self.assertEqual(handler.incompatible_ways,1)
        self.assertEqual(node['memberships'],[])
        self.assertEqual(node['source_way_memberships'][0]['way_id'],10)
        database.close()


if __name__=='__main__':unittest.main()
