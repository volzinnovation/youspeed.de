import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts/map'))
import build_upcoming_path as path
from validate_upcoming_path import validate


class TopologyTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(':memory:')
        self.db.executescript('''CREATE TABLE ways(way_id INTEGER PRIMARY KEY);
            CREATE TABLE traffic_sign_way_direction(way_id INTEGER PRIMARY KEY,forward_allowed INTEGER,backward_allowed INTEGER,way_length_m REAL);
            CREATE TABLE traffic_sign_capability(key TEXT PRIMARY KEY,value TEXT);
            INSERT INTO traffic_sign_capability VALUES('road_snapshot_sha256','fixture');''')
        self.db.executescript((ROOT/'mapdata/spec/upcoming_path_v1.sql').read_text())
        self.incidence = path.Incidence()

    def tearDown(self):
        self.db.close()

    def add(self, way, refs, points=None, tags=None, stored=None):
        points = points or [(48.0, 8.0+node*.0001) for node in refs]
        length = sum(path.distance(a, b) for a, b in zip(points, points[1:]))
        tags = tags or {'highway': 'residential'}
        permission = stored or path.way_direction(tags, tags['highway'])[1:]
        self.db.execute('INSERT INTO ways VALUES(?)', (way,))
        self.db.execute('INSERT INTO traffic_sign_way_direction VALUES(?,?,?,?)', (way, *permission, length))
        return path.insert_way(self.db, self.incidence, way, refs, points, tags, permission, points, length)

    def capability(self):
        self.db.executemany('INSERT INTO upcoming_path_capability VALUES(?,?)', {
            'version': '1', 'completeness': 'complete', 'geometry_convention': path.GEOMETRY,
            'road_snapshot_sha256': 'fixture', 'source_node_incidence': 'complete_pbf_highway_v1',
            'restrictions': 'all_involved_ways_stop_v1', 'motorcar_profile': 'existing_runtime_direction_v1'}.items())

    def successor(self, way, direction=1):
        return self.db.execute('''SELECT x.status,b.way_id,b.direction FROM upcoming_path_segment a
            JOIN upcoming_path_successor x ON x.from_segment_id=a.segment_id
            LEFT JOIN upcoming_path_segment b ON b.segment_id=x.to_segment_id
            WHERE a.way_id=? AND a.direction=? ORDER BY a.start_chainage_m''', (way, direction)).fetchall()

    def test_ordinary_split_certifies_both_directions_without_coordinates_as_identity(self):
        self.incidence.add_way([1, 2]); self.incidence.add_way([2, 3])
        self.add(10, [1, 2]); self.add(20, [2, 3]); path.certify(self.db)
        self.assertEqual(self.successor(10), [('certified', 20, 1)])
        self.assertEqual(self.successor(20, -1), [('certified', 10, -1)])
        self.capability(); self.assertTrue(validate(self.db, True)['ready'])

    def test_interior_nonadmitted_side_road_splits_and_blocks(self):
        self.incidence.add_way([1, 2, 3]); self.incidence.add_way([2, 4])
        self.add(10, [1, 2, 3]); path.certify(self.db)
        self.assertEqual(self.successor(10), [('stop', None, None), ('stop', None, None)])
        self.assertEqual(self.db.execute('SELECT count(*) FROM upcoming_path_segment').fetchone()[0], 4)

    def test_merge_and_fork_are_stops_even_when_omitted_branch_is_blocked(self):
        for refs in ([1, 2], [2, 3], [4, 2]): self.incidence.add_way(refs)
        self.add(10, [1, 2]); self.add(20, [2, 3]); self.add(30, [4, 2], tags={'highway': 'residential', 'motorcar': 'no'})
        path.certify(self.db)
        self.assertEqual(self.successor(10), [('stop', None, None)])

    def test_coincident_coordinates_do_not_connect_different_source_nodes(self):
        self.incidence.add_way([1, 2]); self.incidence.add_way([3, 4])
        self.add(10, [1, 2], points=[(48, 8), (48, 8.001)])
        self.add(20, [3, 4], points=[(48, 8.001), (48, 8.002)])
        path.certify(self.db); self.assertEqual(self.successor(10), [('stop', None, None)])

    def test_restriction_involved_way_and_access_barrier_stop(self):
        self.incidence.add_way([1, 2]); self.incidence.add_way([2, 3])
        self.incidence.restricted_ways.add(20)
        self.add(10, [1, 2]); self.add(20, [2, 3]); path.certify(self.db)
        self.assertEqual(self.successor(10), [('stop', None, None)])
        self.assertEqual(self.successor(20, -1), [('stop', None, None)])

    def test_conditional_access_and_unresolved_private_access_are_unknown(self):
        self.assertEqual(path.permissions({'access:conditional': 'no @ (wet)'}, 'residential', (1, 1)), {1: 'unknown', -1: 'unknown'})
        self.assertEqual(path.permissions({'motorcar': 'private'}, 'residential', (1, 1)), {1: 'unknown', -1: 'unknown'})
        self.assertEqual(path.permissions({'oneway': '-1'}, 'residential', (0, 1)), {1: 'blocked', -1: 'allowed'})

    def test_reverse_source_geometry_and_shape_vertices_keep_chainage(self):
        self.incidence.add_way([1, 2, 3]); self.incidence.add_way([4, 3])
        self.add(10, [1, 2, 3]); self.add(20, [4, 3]); path.certify(self.db)
        self.assertEqual(self.successor(10), [('certified', 20, -1)])
        self.assertEqual(self.db.execute('SELECT count(*) FROM upcoming_path_segment WHERE way_id=10').fetchone()[0], 2)

    def test_loop_never_certifies_its_own_reverse_or_self(self):
        self.incidence.add_way([1, 2, 3, 1]); self.add(10, [1, 2, 3, 1]); path.certify(self.db)
        self.assertTrue(all(row[0] == 'stop' for row in self.successor(10)))

    def test_validator_rejects_certificate_when_incidence_proof_changes(self):
        self.incidence.add_way([1, 2]); self.incidence.add_way([2, 3])
        self.add(10, [1, 2]); self.add(20, [2, 3]); path.certify(self.db); self.capability()
        self.db.execute('UPDATE upcoming_path_node SET source_degree=3 WHERE node_id=2')
        result = validate(self.db, True)
        self.assertFalse(result['ready']); self.assertEqual(result['failed_rows']['invalid_certified_successor'], 2)

    def test_mismatched_source_geometry_is_not_certifiable(self):
        self.incidence.add_way([1, 2])
        self.db.execute('INSERT INTO ways VALUES(10)')
        self.db.execute('INSERT INTO traffic_sign_way_direction VALUES(10,1,1,10)')
        self.assertFalse(path.insert_way(self.db, self.incidence, 10, [1, 2], [(48, 8), (48, 8.001)],
            {'highway': 'residential'}, (1, 1), [(48, 8), (48, 8.002)], 10))
        self.assertEqual(self.db.execute('SELECT geometry_verified FROM upcoming_path_way').fetchone()[0], 0)

    def test_validator_requires_both_complete_direction_sets(self):
        self.incidence.add_way([1, 2]); self.add(10, [1, 2]); path.certify(self.db); self.capability()
        self.db.execute('DELETE FROM upcoming_path_successor WHERE from_segment_id IN (SELECT segment_id FROM upcoming_path_segment WHERE direction=-1)')
        self.db.execute('DELETE FROM upcoming_path_segment WHERE direction=-1')
        result = validate(self.db, True)
        self.assertFalse(result['ready']); self.assertEqual(result['failed_rows']['segment_coverage_bounds'], 1)

    def test_validator_rejects_nonfinite_stored_length(self):
        self.incidence.add_way([1, 2]); self.add(10, [1, 2]); path.certify(self.db); self.capability()
        self.db.execute("UPDATE upcoming_path_segment SET length_m=? WHERE direction=1", (float('inf'),))
        result = validate(self.db, True)
        self.assertFalse(result['ready']); self.assertEqual(result['failed_rows']['invalid_segment_geometry_or_permission'], 1)


class SourceIntegrationTests(unittest.TestCase):
    def test_source_restriction_relations_and_physical_barriers_are_not_dropped(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/'restriction.osm'
            source.write_text('''<osm version="0.6"><node id="1" lat="48" lon="8" version="1"/>
                <node id="2" lat="48" lon="8.001" version="1"><tag k="barrier" v="gate"/></node>
                <node id="3" lat="48" lon="8.002" version="1"/>
                <way id="10" version="1"><nd ref="1"/><nd ref="2"/><tag k="highway" v="residential"/></way>
                <way id="20" version="1"><nd ref="2"/><nd ref="3"/><tag k="highway" v="residential"/></way>
                <relation id="100" version="1"><member type="way" ref="10" role="from"/>
                  <member type="node" ref="2" role="via"/><member type="way" ref="20" role="to"/>
                  <tag k="type" v="restriction"/><tag k="restriction:conditional" v="no_left_turn @ (wet)"/>
                </relation></osm>''')
            incidence = path.Incidence(); incidence.apply_file(str(source), locations=False)
            self.assertEqual(incidence.restricted_ways, {10, 20})
            self.assertIn(2, incidence.barrier_nodes)
            self.assertEqual(incidence.degree[2], 2)
            self.assertEqual(incidence.restrictions, 1)

    def test_pbf_builder_pins_source_and_preserves_conflict_event_index(self):
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/'source.osm'
            source.write_text('''<osm version="0.6"><node id="1" lat="48" lon="8" version="1"/>
                <node id="2" lat="48" lon="8.001" version="1"/><node id="3" lat="48" lon="8.002" version="1"/>
                <way id="10" version="1"><nd ref="1"/><nd ref="2"/><tag k="highway" v="residential"/></way>
                <way id="20" version="1"><nd ref="2"/><nd ref="3"/><tag k="highway" v="residential"/></way></osm>''')
            db = sqlite3.connect(':memory:')
            db.executescript('''CREATE TABLE ways(way_id INTEGER PRIMARY KEY);
                CREATE TABLE way_geom(way_id INTEGER PRIMARY KEY,points_json TEXT);
                CREATE TABLE traffic_sign_way_direction(way_id INTEGER PRIMARY KEY,forward_allowed INTEGER,backward_allowed INTEGER,way_length_m REAL);
                CREATE TABLE traffic_sign_capability(key TEXT PRIMARY KEY,value TEXT);
                CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
                INSERT INTO metadata VALUES('road_geometry_policy','source_vertices_v1');
                CREATE TABLE traffic_sign_association(sign_id TEXT PRIMARY KEY,way_id INTEGER,direction INTEGER,status TEXT,station_chainage_m REAL);''')
            db.execute('INSERT INTO traffic_sign_capability VALUES(?,?)', ('road_snapshot_sha256', path.sha256(source)))
            for way, points in [(10, [(48, 8), (48, 8.001)]), (20, [(48, 8.001), (48, 8.002)])]:
                db.execute('INSERT INTO ways VALUES(?)', (way,))
                db.execute('INSERT INTO way_geom VALUES(?,?)', (way, json.dumps(points)))
                db.execute('INSERT INTO traffic_sign_way_direction VALUES(?,?,?,?)', (way, 1, 1, path.distance(*points)))
            report = path.build(db, source)
            self.assertEqual(report['successors']['certified'], 2)
            self.assertTrue(validate(db, True)['ready'])
            index = db.execute("SELECT sql FROM sqlite_master WHERE name='idx_traffic_sign_association_station'").fetchone()[0]
            self.assertNotIn('WHERE', index)
            db.execute("UPDATE traffic_sign_capability SET value='wrong' WHERE key='road_snapshot_sha256'")
            with self.assertRaisesRegex(ValueError, 'hash does not match'): path.build(db, source)
            db.close()


if __name__ == '__main__':
    unittest.main()
