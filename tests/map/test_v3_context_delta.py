import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


MAP_SCRIPTS = Path(__file__).resolve().parents[2] / "scripts" / "map"
sys.path.insert(0, str(MAP_SCRIPTS))
from v3_context_delta import assert_context_equivalence, build_context_delta


class ContextDeltaTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name) / "base.sqlite"
        self.target = Path(self.tmp.name) / "target.sqlite"
        with sqlite3.connect(self.base) as connection:
            connection.executescript("""
                CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT);
                INSERT INTO metadata VALUES('schema_version','1'),('settlement_context_version','1'),
                  ('settlement_source_date','old');
                CREATE TABLE settlement_segment(segment_id INTEGER PRIMARY KEY, way_id INTEGER,
                  segment_index INTEGER, direction INTEGER, inside_city INTEGER CHECK(inside_city IN(0,1)),
                  source TEXT, confidence TEXT, evidence_json TEXT, points_json TEXT);
                INSERT INTO settlement_segment VALUES
                  (1,10,0,0,1,'zone_traffic','high','{}','[[49,8],[49,8.1]]'),
                  (2,20,0,0,0,'source_maxspeed','high','{}','[[49,8],[49,8.1]]'),
                  (3,30,0,0,NULL,'missing','unknown','{}','[[49,8],[49,8.1]]');
                CREATE TABLE settlement_area(area_id TEXT PRIMARY KEY, inside_city INTEGER, tags_json TEXT);
                INSERT INTO settlement_area VALUES('r:1',1,'{"name":"Old"}');
                CREATE TABLE settlement_ring(area_id TEXT,ring_index INTEGER,outer_index INTEGER,
                  is_hole INTEGER,points_json TEXT,PRIMARY KEY(area_id,ring_index));
                INSERT INTO settlement_ring VALUES('r:1',0,0,0,'[[8,49],[9,49],[9,50],[8,49]]');
                CREATE TABLE settlement_sign(sign_id TEXT PRIMARY KEY,inside_city INTEGER,direction INTEGER);
                INSERT INTO settlement_sign VALUES('n:1',1,1);
                CREATE TABLE city_boundary(row_id INTEGER PRIMARY KEY,name TEXT);
                INSERT INTO city_boundary VALUES(1,'Old County');
                CREATE VIRTUAL TABLE city_boundary_rtree USING rtree(row_id,min_lon,max_lon,min_lat,max_lat);
                INSERT INTO city_boundary_rtree VALUES(1,8,9,49,50);
                CREATE TABLE city_ring(boundary_row_id INTEGER,ring_index INTEGER,points_json TEXT);
                INSERT INTO city_ring VALUES(1,0,'[[8,49],[9,49],[9,50],[8,49]]');
                CREATE TABLE city_tile(boundary_row_id INTEGER,tile_x INTEGER,tile_y INTEGER);
                INSERT INTO city_tile VALUES(1,10,20);
                CREATE TABLE city_place(row_id INTEGER PRIMARY KEY,name TEXT);
                INSERT INTO city_place VALUES(1,'Old Place');
                CREATE VIRTUAL TABLE city_place_rtree USING rtree(row_id,min_lon,max_lon,min_lat,max_lat);
                INSERT INTO city_place_rtree VALUES(1,8,8,49,49);
            """)
        shutil.copyfile(self.base, self.target)

    def assert_equivalent(self, patched, target):
        with sqlite3.connect(":memory:") as connection:
            connection.execute("ATTACH DATABASE ? AS p", (str(patched),))
            connection.execute("ATTACH DATABASE ? AS t", (str(target),))
            assert_context_equivalence(connection)

    def test_round_trip_preserves_nullable_boolean_and_all_context_tables(self):
        with sqlite3.connect(self.target) as connection:
            connection.executescript("""
                UPDATE settlement_segment SET inside_city=NULL,source='conflict',confidence='unknown' WHERE segment_id=1;
                UPDATE settlement_segment SET inside_city=1 WHERE segment_id=2;
                UPDATE settlement_segment SET inside_city=0,source='traffic_sign',confidence='high' WHERE segment_id=3;
                INSERT INTO settlement_segment VALUES(4,40,0,-1,NULL,'missing','unknown','{}','[[49,8],[49,8.1]]');
                UPDATE settlement_area SET inside_city=NULL,tags_json='{"name":"O''Brien"}';
                INSERT INTO settlement_ring VALUES('r:1',1,0,1,'[[8.1,49.1],[8.2,49.1],[8.2,49.2],[8.1,49.1]]');
                DELETE FROM settlement_sign;
                INSERT INTO settlement_sign VALUES('n:2',0,-1);
                UPDATE city_boundary SET name='Updated County';
                UPDATE city_boundary_rtree SET max_lon=9.1234567;
                UPDATE city_ring SET points_json='[[8,49],[9.1,49],[9,50],[8,49]]';
                DELETE FROM city_tile;
                INSERT INTO city_tile VALUES(1,11,20);
                UPDATE city_place SET name='Updated Place';
                UPDATE city_place_rtree SET min_lon=8.01,max_lon=8.01;
                UPDATE metadata SET value='new' WHERE key='settlement_source_date';
            """)
        statements, counts = build_context_delta(self.base, self.target)
        self.assertEqual(counts["settlement_segment"], {"deleted": 3, "inserted": 4})
        with sqlite3.connect(self.base) as connection:
            connection.executescript("BEGIN;\n" + "\n".join(statements) + "\nCOMMIT;")
            self.assertEqual(connection.execute("SELECT inside_city FROM settlement_segment ORDER BY segment_id").fetchall(),
                             [(None,), (1,), (0,), (None,)])
        self.assert_equivalent(self.base, self.target)

    def test_cli_round_trip_updates_current_topology_and_corridor_schema(self):
        with sqlite3.connect(self.base) as connection:
            connection.executescript("""
                CREATE TABLE ways(way_id INTEGER PRIMARY KEY,highway TEXT,street_name TEXT,ref TEXT,
                  maxspeed TEXT,maxspeed_type TEXT,source_maxspeed TEXT,approx_heading_deg REAL,
                  service TEXT,tunnel TEXT,min_lon REAL,min_lat REAL,max_lon REAL,max_lat REAL);
                INSERT INTO ways VALUES(10,'primary','Road',NULL,'50',NULL,NULL,90,NULL,NULL,8,49,8.1,49);
                CREATE VIRTUAL TABLE ways_rtree USING rtree(way_id,min_lon,max_lon,min_lat,max_lat);
                INSERT INTO ways_rtree VALUES(10,8,8.1,49,49);
                CREATE TABLE way_geom(way_id INTEGER PRIMARY KEY,points_json TEXT);
                INSERT INTO way_geom VALUES(10,'[[49,8],[49,8.1]]');
                CREATE TABLE way_links(way_id INTEGER NOT NULL,linked_way_id INTEGER NOT NULL,
                  shared_ref INTEGER NOT NULL,shared_node_key TEXT NOT NULL,
                  PRIMARY KEY(way_id,linked_way_id,shared_node_key));
                INSERT INTO way_links VALUES(10,20,0,'node-a'),(10,20,0,'node-b');
                CREATE TABLE corridor_progress(corridor_kind TEXT,corridor_id INTEGER,
                  side_node_key TEXT,way_id INTEGER,start_depth_m REAL,end_depth_m REAL,
                  start_depth_nodes INTEGER,end_depth_nodes INTEGER,corridor_span_m REAL,corridor_span_nodes INTEGER,
                  PRIMARY KEY(corridor_kind,corridor_id,side_node_key,way_id));
                INSERT INTO corridor_progress VALUES('tunnel',1,'node-a',20,0,15,0,1,15,1);
                CREATE TABLE corridor_pairs(corridor_kind TEXT,corridor_id INTEGER,side_node_key TEXT,
                  paired_kind TEXT,paired_corridor_id INTEGER,
                  PRIMARY KEY(corridor_kind,corridor_id,side_node_key,paired_kind,paired_corridor_id));
                INSERT INTO corridor_pairs VALUES('tunnel',1,'node-a','tunnel',2);
                CREATE TABLE way_continuity_group(continuity_group_id INTEGER PRIMARY KEY,continuity_kind TEXT,
                  source_relation_id INTEGER,ref_norm TEXT,street_name_norm TEXT,member_count INTEGER);
                INSERT INTO way_continuity_group VALUES(1,'name',NULL,NULL,'ROAD',1);
                CREATE TABLE way_continuity_membership(way_id INTEGER,continuity_group_id INTEGER,continuity_kind TEXT,
                  PRIMARY KEY(way_id,continuity_group_id));
                INSERT INTO way_continuity_membership VALUES(10,1,'name');
                CREATE TABLE surface_way_network(way_id INTEGER PRIMARY KEY);
                INSERT INTO surface_way_network VALUES(10);
                CREATE VIRTUAL TABLE surface_way_network_rtree USING rtree(way_id,min_lon,max_lon,min_lat,max_lat);
                INSERT INTO surface_way_network_rtree VALUES(10,8,8.1,49,49);
            """)
        shutil.copyfile(self.base, self.target)
        with sqlite3.connect(self.target) as connection:
            connection.executescript("""
                UPDATE ways SET maxspeed='70' WHERE way_id=10;
                UPDATE way_links SET shared_ref=1 WHERE shared_node_key='node-a';
                INSERT INTO way_links VALUES(20,30,0,'node-c');
                UPDATE corridor_progress SET end_depth_m=20,corridor_span_m=20;
                UPDATE corridor_pairs SET paired_corridor_id=3;
                UPDATE way_continuity_group SET member_count=2;
                INSERT INTO way_continuity_membership VALUES(20,1,'name');
                UPDATE surface_way_network_rtree SET max_lon=8.1234567;
                INSERT INTO metadata VALUES('corridor_progress_count','1');
            """)
        diff = Path(self.tmp.name) / 'empty.osc'
        diff.write_text('<osmChange version="0.6"/>')
        out = Path(self.tmp.name) / 'delta'
        subprocess.run([
            sys.executable, str(MAP_SCRIPTS / 'build_v3_delta_pack.py'),
            '--base-db', str(self.base), '--target-db', str(self.target),
            '--diff-file', str(diff), '--from-version', 'old', '--to-version', 'new',
            '--out-dir', str(out), '--patch-compression', 'none', '--validate-on-copy',
        ], check=True, capture_output=True, text=True)
        with sqlite3.connect(self.base) as connection:
            connection.executescript((out / 'v3_patch.sql').read_text())
            self.assertEqual(connection.execute('SELECT maxspeed FROM ways WHERE way_id=10').fetchone()[0], '70')
            self.assertEqual(connection.execute('SELECT * FROM way_links ORDER BY way_id,shared_node_key').fetchall(),
                             [(10,20,1,'node-a'),(10,20,0,'node-b'),(20,30,0,'node-c')])
        self.assert_equivalent(self.base, self.target)

    def test_minimal_topology_schema_and_unmodified_road_edge_changes(self):
        for path in (self.base, self.target):
            with sqlite3.connect(path) as connection:
                connection.executescript("""
                    CREATE TABLE way_links(way_id INTEGER,linked_way_id INTEGER,PRIMARY KEY(way_id,linked_way_id));
                    INSERT INTO way_links VALUES(10,20);
                """)
        with sqlite3.connect(self.target) as connection:
            connection.execute('UPDATE way_links SET linked_way_id=30')
        statements, counts = build_context_delta(self.base, self.target)
        self.assertEqual(counts['way_links'], {'deleted':1,'inserted':1})
        with sqlite3.connect(self.base) as connection:
            connection.executescript('\n'.join(statements))
        self.assert_equivalent(self.base, self.target)

    def test_matcher_index_migration_and_null_capability_require_full_bundle(self):
        with sqlite3.connect(self.target) as connection:
            connection.execute('CREATE INDEX new_settlement_way_index ON settlement_segment(way_id)')
        with self.assertRaisesRegex(SystemExit, 'full bundle'):
            build_context_delta(self.base, self.target)
        for path in (self.base, self.target):
            with sqlite3.connect(path) as connection:
                connection.execute("UPDATE metadata SET value=NULL WHERE key='settlement_context_version'")
        with self.assertRaisesRegex(SystemExit, 'NULL settlement'):
            build_context_delta(self.base, self.target)

    def test_noop_context_delta_is_empty(self):
        self.assertEqual(build_context_delta(self.base, self.target)[0], [])
        self.assert_equivalent(self.base, self.target)

    def test_capability_migration_requires_full_bundle(self):
        with sqlite3.connect(self.target) as connection:
            connection.execute("UPDATE metadata SET value='2' WHERE key='settlement_context_version'")
        with self.assertRaisesRegex(SystemExit, "full bundle"):
            build_context_delta(self.base, self.target)

    def test_added_context_table_requires_full_bundle(self):
        with sqlite3.connect(self.base) as connection:
            connection.execute("DROP TABLE settlement_sign")
        with self.assertRaisesRegex(SystemExit, "full bundle"):
            build_context_delta(self.base, self.target)

    def test_equivalence_detects_geometry_drift_even_without_road_changes(self):
        with sqlite3.connect(self.target) as connection:
            connection.execute("UPDATE settlement_ring SET points_json='[]'")
        with self.assertRaisesRegex(SystemExit, "settlement_ring"):
            self.assert_equivalent(self.base, self.target)

    def test_equivalence_detects_city_table_drift(self):
        with sqlite3.connect(self.target) as connection:
            connection.execute("UPDATE city_place SET name='Changed'")
        with self.assertRaisesRegex(SystemExit, "city_place"):
            self.assert_equivalent(self.base, self.target)


if __name__ == "__main__":
    unittest.main()
