import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'scripts/map'))
import build_traffic_sign_runtime as runtime
from validate_traffic_sign_runtime import validate
import openlr


def reference(lon1=8.0,lon2=8.002,orientation=1,distance=149,offset=.5):
    return openlr.binary_encode(openlr.PointAlongLineLocationReference([
        openlr.LocationReferencePoint(lon1,48,openlr.FRC.FRC5,openlr.FOW.SINGLE_CARRIAGEWAY,90,openlr.FRC.FRC5,distance),
        openlr.LocationReferencePoint(lon2,48,openlr.FRC.FRC5,openlr.FOW.SINGLE_CARRIAGEWAY,270,openlr.FRC.FRC7,0)],offset,
        openlr.Orientation(orientation),openlr.SideOfRoad.ON_ROAD_OR_UNKNOWN))


class DirectionTests(unittest.TestCase):
    def test_oneway_reverse_and_motorcar_access(self):
        self.assertEqual(runtime.way_direction({'oneway':'-1'}),(-1,0,1))
        self.assertEqual(runtime.way_direction({},'motorway'),(1,1,0))
        self.assertEqual(runtime.way_direction({'oneway':'no'},'motorway'),(0,1,1))
        self.assertEqual(runtime.way_direction({'motorcar':'no'}),(0,0,0))
        self.assertEqual(runtime.way_direction({'motorcar':'yes','access':'no'}),(0,1,1))
        self.assertEqual(runtime.way_direction({'oneway':'reversible'}),(0,0,0))
        self.assertEqual(runtime.way_direction({'oneway:conditional':'yes @ (08:00-12:00)'}),(0,0,0))
        self.assertEqual(runtime.way_direction({'motor_vehicle:backward':'no'}),(0,1,0))
        self.assertEqual(runtime.way_direction({},'motorway_link'),(1,1,0))
        self.assertEqual(runtime.way_direction({'oneway':'yes','oneway:motorcar':'no'}),(0,1,1))

    def test_lanes_preserve_explicit_direction_and_conflicting_values(self):
        rows=runtime.lane_rows(1,{'lanes':'3','lanes:forward':'2','maxspeed:lanes:forward':'50|70','lanes:backward':'1','maxspeed:lanes:backward':'30'},0)
        self.assertEqual([(r[1],r[2],r[3]) for r in rows],[(1,1,'50'),(1,2,'70'),(-1,1,'30')])
        self.assertEqual(runtime.lane_rows(1,{'lanes':'2'},0),[])


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.folder=Path(self.tmp.name)
        self.db=sqlite3.connect(':memory:')
        self.db.executescript('''
          CREATE TABLE ways(way_id INTEGER PRIMARY KEY,maxspeed TEXT,highway TEXT,ref TEXT,street_name TEXT);
          CREATE VIRTUAL TABLE ways_rtree USING rtree(way_id,min_lon,max_lon,min_lat,max_lat);
          CREATE TABLE way_geom(way_id INTEGER PRIMARY KEY,points_json TEXT);
          CREATE TABLE way_endpoints(way_id INTEGER PRIMARY KEY,start_node_key TEXT,end_node_key TEXT,way_length_m REAL);
          CREATE TABLE traffic_sign_source(source_id TEXT PRIMARY KEY,snapshot_sha256 TEXT);
          INSERT INTO traffic_sign_source VALUES('test','snapshot');
          CREATE TABLE traffic_sign_inventory(row_id INTEGER PRIMARY KEY,source_id TEXT,record_key TEXT,sign_code TEXT,
             latitude REAL,longitude REAL,orientation_deg REAL,openlr_binary TEXT,openlr_confidence REAL);
          INSERT INTO ways VALUES(1,'70','residential',NULL,'Test');
          INSERT INTO ways_rtree VALUES(1,8,8.002,48,48);
          INSERT INTO way_geom VALUES(1,'[[48,8],[48,8.002]]');
          INSERT INTO way_endpoints VALUES(1,'a','b',148.808);
        ''')
        self.meta=self.folder/'ways.meta'
        self.write_meta({})
        self.sign(1,'DE:310')

    def tearDown(self):
        self.db.close();self.tmp.cleanup()

    def write_meta(self,tags):
        self.meta.write_text(json.dumps({'way_id':1,'highway':'residential','raw_tags':tags})+'\n')

    def sign(self,n,code,lon=8.001,ori=90,raw=None):
        self.db.execute('INSERT INTO traffic_sign_inventory VALUES(?,?,?,?,?,?,?,?,?)',(n,'test',str(n),code,48,lon,ori,raw or reference(),90))

    def build(self):return runtime.build_runtime(self.db,self.meta)

    def test_decoded_direction_and_town_intervals_do_not_change_osm(self):
        self.sign(2,'DE:274-30',lon=8.0012)
        result=self.build()
        self.assertEqual(result['associations'],{'accepted':2})
        self.assertEqual(self.db.execute('SELECT maxspeed FROM ways').fetchone()[0],'70')
        rules=self.db.execute('SELECT speed_kmh,inside_city,association_status,lane_scope FROM traffic_sign_way_rule ORDER BY start_chainage_m').fetchall()
        self.assertEqual(rules,[(None,1,'accepted','all'),(30,1,'accepted','all')])
        self.assertEqual(self.db.execute("SELECT value FROM traffic_sign_capability WHERE key='version'").fetchone()[0],'1')
        self.assertEqual(result['rules'],2)

    def test_opposing_oneway_rejects_reference(self):
        self.write_meta({'oneway':'-1'})
        result=self.build()
        self.assertEqual(result['rules'],0)
        self.assertEqual(result['associations'],{'no_verified_directed_path':1})

    def test_reverse_orientation_uses_backward_interval(self):
        self.db.execute('UPDATE traffic_sign_inventory SET openlr_binary=?,orientation_deg=270',(reference(orientation=2),))
        result=self.build()
        self.assertEqual(result['associations'],{'accepted':1})
        direction,start,end,station=self.db.execute('SELECT direction,start_chainage_m,end_chainage_m,station_chainage_m FROM traffic_sign_way_rule').fetchone()
        self.assertEqual(direction,-1)
        self.assertEqual(start,0)
        self.assertEqual(end,station)

    def connected_ways(self):
        for table in ('ways','ways_rtree','way_geom','way_endpoints'):self.db.execute('DELETE FROM '+table)
        meta=[]
        for i in range(3):
            way=i+1;start=8+i*.001;end=start+.001
            self.db.execute('INSERT INTO ways VALUES(?,?,?,?,?)',(way,'70','residential',None,'Test'))
            self.db.execute('INSERT INTO ways_rtree VALUES(?,?,?,?,?)',(way,start,end,48,48))
            self.db.execute('INSERT INTO way_geom VALUES(?,?)',(way,json.dumps([[48,start],[48,end]])))
            self.db.execute('INSERT INTO way_endpoints VALUES(?,?,?,?)',(way,str(i),str(i+1),74.404))
            meta.append(json.dumps({'way_id':way,'highway':'residential','raw_tags':{}}))
        self.meta.write_text('\n'.join(meta)+'\n')
        self.db.execute('UPDATE traffic_sign_inventory SET longitude=8.0015,openlr_binary=?',(reference(lon2=8.003,distance=223),))

    def test_openlr_path_can_span_connected_osm_ways(self):
        self.connected_ways()
        result=self.build()
        self.assertEqual(result['associations'],{'accepted':1})
        self.assertEqual(self.db.execute('SELECT way_id FROM traffic_sign_way_rule').fetchone()[0],2)
        self.assertEqual(self.db.execute('SELECT way_id FROM traffic_sign_way_rule ORDER BY way_id').fetchall(),[(2,),(3,)])
        self.assertEqual(result['continuation_rules'],1)
        self.assertTrue(validate(self.db,require=True)['ready'])
        # End masks must not resurrect the identical old OSM 70 tag at an
        # ordinary source-way split. Their original physical station stays on 2.
        for code in ('DE:278','DE:282'):
            with self.subTest(cancellation=code):
                self.db.execute('UPDATE traffic_sign_inventory SET sign_code=?',(code,))
                result=self.build()
                self.assertEqual(result['continuation_rules'],1)
                self.assertEqual(self.db.execute('SELECT way_id,speed_kmh FROM traffic_sign_way_rule ORDER BY way_id').fetchall(),[(2,None),(3,None)])
                self.assertEqual(self.db.execute('SELECT way_id FROM traffic_sign_association').fetchone()[0],2)
                self.assertTrue(validate(self.db,require=True)['ready'])

    def test_colocated_town_and_fresh_speed_at_way_exit_continue_only_fresh_offer(self):
        self.connected_ways()
        self.sign(2,'DE:274-30',lon=8.0015,raw=reference(lon2=8.003,distance=223))
        self.build()
        graph=runtime.Graph(self.db)
        self.db.execute('UPDATE traffic_sign_association SET station_chainage_m=?',(graph.way(2)['length']+1e-9,))
        self.db.execute('DELETE FROM traffic_sign_rule_path')
        self.db.execute('DELETE FROM traffic_sign_way_rule')
        runtime.emit_intervals(self.db,graph)
        self.assertEqual(self.db.execute('SELECT speed_kmh,inside_city FROM traffic_sign_way_rule WHERE way_id=3').fetchall(),[(30,1)])
        self.assertEqual(self.db.execute('SELECT count(*) FROM traffic_sign_association WHERE way_id=2').fetchone()[0],2)
        self.assertTrue(validate(self.db,require=True)['ready'])

    def test_continuation_stops_at_explicit_nonnumeric_or_conditional_speed(self):
        self.connected_ways()
        self.db.execute("UPDATE traffic_sign_inventory SET sign_code='DE:274-30'")
        for tags in ({'maxspeed':'none'},{'maxspeed':'walk'},{'maxspeed:conditional':'50 @ (wet)'}):
            with self.subTest(tags=tags):
                rows=[{'way_id':i,'highway':'residential','raw_tags':tags if i==3 else {}} for i in (1,2,3)]
                self.meta.write_text(''.join(json.dumps(r)+'\n' for r in rows))
                result=self.build()
                self.assertEqual(result['continuation_rules'],0)
                self.assertEqual(self.db.execute('SELECT count(*) FROM traffic_sign_way_rule WHERE way_id=3').fetchone()[0],0)

    def test_parallel_equally_plausible_roads_remain_ambiguous(self):
        offset=.00002
        self.db.execute('UPDATE ways_rtree SET min_lat=?,max_lat=?',(48-offset,48-offset))
        self.db.execute('UPDATE way_geom SET points_json=?',(json.dumps([[48-offset,8],[48-offset,8.002]]),))
        self.db.execute("INSERT INTO ways VALUES(2,'70','residential',NULL,'Parallel')")
        self.db.execute('INSERT INTO ways_rtree VALUES(2,8,8.002,?,?)',(48+offset,48+offset))
        self.db.execute('INSERT INTO way_geom VALUES(2,?)',(json.dumps([[48+offset,8],[48+offset,8.002]]),))
        self.db.execute("INSERT INTO way_endpoints VALUES(2,'c','d',148.808)")
        with self.meta.open('a') as f:f.write(json.dumps({'way_id':2,'highway':'residential','raw_tags':{}})+'\n')
        result=self.build()
        self.assertEqual(result['associations'],{'ambiguous_directed_path':1})
        self.assertEqual(result['rules'],0)

    def test_unknown_orientation_and_dynamic_signs_cannot_act(self):
        self.db.execute('UPDATE traffic_sign_inventory SET openlr_binary=?',(reference(orientation=0),))
        self.sign(2,'DE:274-50[WVZ Rombachtunnel]')
        result=self.build()
        self.assertEqual(result['rules'],0)
        self.assertEqual(result['associations'],{'invalid_openlr':1,'unverified_source_annotation':1})

    def test_lane_conflict_is_retained_without_universal_speed_action(self):
        self.write_meta({'oneway':'yes','lanes':'2','maxspeed:lanes':'50|70'})
        self.db.execute("UPDATE traffic_sign_inventory SET sign_code='DE:274-30'")
        result=self.build()
        self.assertEqual(result['known_lanes'],2)
        self.assertEqual(result['unresolved_lane_rules'],1)
        self.assertEqual(self.db.execute('SELECT lane_scope FROM traffic_sign_way_rule').fetchone()[0],'unresolved')

    def test_end_sign_masks_stale_same_way_speed_without_inventing_value(self):
        self.db.execute("UPDATE traffic_sign_inventory SET sign_code='DE:274-30'")
        self.sign(2,'DE:278',lon=8.0012)
        result=self.build()
        self.assertEqual(result['rules'],2)
        self.assertEqual(self.db.execute('SELECT speed_kmh FROM traffic_sign_way_rule ORDER BY start_chainage_m').fetchall(),[(30,), (None,)])

    def test_conflicting_colocated_speed_values_are_not_arbitrarily_selected(self):
        self.db.execute("UPDATE traffic_sign_inventory SET sign_code='DE:274-30'")
        self.sign(2,'DE:274-50')
        result=self.build()
        self.assertEqual(result['rules'],0)
        self.assertEqual(result['associations'],{'conflicting_source_values':2})

    def test_atomic_rebuild_and_stable_contract(self):
        first=self.build()
        expected=self.db.execute('SELECT * FROM traffic_sign_way_rule').fetchall()
        self.assertEqual(self.build(),first)
        self.db.execute("CREATE TRIGGER refuse BEFORE INSERT ON traffic_sign_runtime BEGIN SELECT RAISE(ABORT,'test'); END")
        with self.assertRaises(sqlite3.IntegrityError):self.build()
        self.assertEqual(self.db.execute('SELECT * FROM traffic_sign_way_rule').fetchall(),expected)

    def test_contract_gate_old_region_and_direction_corruption(self):
        self.assertTrue(validate(self.db)['ready'])
        self.assertFalse(validate(self.db,require=True)['ready'])
        self.build()
        self.assertTrue(validate(self.db,require=True)['ready'])
        self.db.execute('UPDATE traffic_sign_way_direction SET forward_allowed=0')
        report=validate(self.db,require=True)
        self.assertFalse(report['ready'])
        self.assertEqual(report['failed_rows']['accepted_associations_permitted'],1)

    def setup_osm_fallback_source(self):
        from traffic_sign_inventory import SCHEMA
        self.db.execute('DROP TABLE traffic_sign_source')
        self.db.execute(SCHEMA.split(';')[0])
        self.db.execute('INSERT INTO traffic_sign_source VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)',
                        ('test','Publisher','https://example.org','https://example.org','test','https://example.org','snapshot',None,1,8,48,8.002,48,'inventory_only','Test'))
        source=self.folder/'source.pbf';source.write_bytes(b'pinned-road-test-source')
        self.db.execute('CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT)')
        self.db.execute('INSERT INTO metadata VALUES(?,?)',('source_input_pbf',str(source)))
        self.db.execute("INSERT INTO metadata VALUES('country_code','DE')")
        self.db.execute('''CREATE TABLE settlement_sign(sign_id TEXT PRIMARY KEY,way_id INTEGER,direction INTEGER,
            lon REAL,lat REAL,sign_code TEXT,inside_city INTEGER,association TEXT)''')

    def test_osm_fallback_boundary_cuts_inventory_and_masks_old_way_speed(self):
        self.setup_osm_fallback_source()
        self.db.execute("INSERT INTO settlement_sign VALUES('n:42',1,1,8.0016,48,'DE:311',0,'node_membership')")
        result=self.build()
        self.assertEqual(result['osm_town_fallbacks'],1)
        self.assertEqual(result['signs'],2)
        self.assertEqual(self.db.execute('SELECT speed_kmh,inside_city FROM traffic_sign_way_rule ORDER BY start_chainage_m').fetchall(),[(None,1),(None,0)])
        self.assertEqual(self.db.execute("SELECT license_id FROM traffic_sign_source WHERE source_id='osm-settlement'").fetchone()[0],'ODbL-1.0')
        self.assertTrue(validate(self.db,require=True)['ready'])
        self.assertEqual(self.build(),result)

    def test_osm_split_boundary_uses_one_downstream_physical_station(self):
        self.setup_osm_fallback_source()
        self.db.execute("INSERT INTO ways VALUES(2,'70','residential',NULL,'Test')")
        self.db.execute('INSERT INTO ways_rtree VALUES(2,8.002,8.003,48,48)')
        self.db.execute("INSERT INTO way_geom VALUES(2,'[[48,8.002],[48,8.003]]')")
        self.db.execute("INSERT INTO way_endpoints VALUES(2,'b','c',74.404)")
        with self.meta.open('a') as f:f.write(json.dumps({'way_id':2,'highway':'residential','raw_tags':{}})+'\n')
        for way in (1,2):
            self.db.execute('INSERT INTO settlement_sign VALUES(?,?,1,8.002,48,\'DE:311\',0,\'collinear_way_split\')',(f'n:42:forward:w:{way}',way))
        result=self.build()
        self.assertEqual(result['osm_town_fallbacks'],1)
        row=self.db.execute("SELECT s.record_key,a.way_id,a.evidence_json FROM traffic_sign_runtime s JOIN traffic_sign_association a USING(sign_id) WHERE s.source_id='osm-settlement'").fetchone()
        self.assertEqual(row[:2],('n:42:forward:w:2',2))
        self.assertEqual(json.loads(row[2])['source_station_ids'],['n:42:forward:w:1','n:42:forward:w:2'])
        self.assertTrue(validate(self.db,require=True)['ready'])
        self.db.execute("INSERT INTO settlement_sign VALUES('n:42:main:end',2,1,8.002,48,'city_limit:end',0,'node_membership')")
        self.assertEqual(self.build()['osm_town_fallbacks'],1)
        evidence=json.loads(self.db.execute("SELECT a.evidence_json FROM traffic_sign_association a JOIN traffic_sign_runtime s USING(sign_id) WHERE s.source_id='osm-settlement'").fetchone()[0])
        self.assertEqual(len(evidence['source_station_ids']),3)
        # The same physical town boundary may be in MobiData just before the
        # split and in OSM on its downstream way. Compare both source-way
        # alternatives so it cannot reset twice across the source-way boundary.
        self.db.execute("UPDATE settlement_sign SET sign_code='DE:310',inside_city=1")
        self.db.execute('UPDATE traffic_sign_inventory SET longitude=8.0018,openlr_binary=?',(reference(offset=.9),))
        result=self.build()
        self.assertEqual(result['osm_town_fallbacks'],0)
        self.assertEqual(result['associations'],{'accepted':1})
        self.assertTrue(validate(self.db,require=True)['ready'])
        # Existing generic OSM city_limit end semantics must also release an
        # inventory town epoch in Germany, with the original source code kept.
        self.db.execute("UPDATE traffic_sign_inventory SET sign_code='DE:274-30'")
        self.db.execute("UPDATE settlement_sign SET sign_code='city_limit:end',inside_city=0")
        result=self.build()
        self.assertEqual(result['osm_town_fallbacks'],1)
        row=self.db.execute("SELECT s.sign_code,a.evidence_json FROM traffic_sign_runtime s JOIN traffic_sign_association a USING(sign_id) WHERE s.source_id='osm-settlement'").fetchone()
        self.assertEqual(row[0],'DE:311')
        self.assertEqual(json.loads(row[1])['original_sign_code'],'city_limit:end')
        self.assertTrue(validate(self.db,require=True)['ready'])
        self.db.execute("UPDATE metadata SET value='FR' WHERE key='country_code'")
        self.assertEqual(self.build()['osm_town_fallbacks'],0)


if __name__=='__main__':unittest.main()
