import json
from pathlib import Path
import sqlite3
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/map"))
import build_mobidata_v1_5_pilot as pilot


class NormalizationTests(unittest.TestCase):
    def test_parameter_values_and_units(self):
        cases = [("DE:274-50", "speed_limit", 50, "km/h"),
                 ("DE:278-30", "speed_limit_end", 30, "km/h"),
                 ("DE:108-12", "descent", 12, "%"),
                 ("DE:110[15 %]", "incline", 15, "%"),
                 ("DE:262-7,5", "maximum_weight", 7.5, "t"),
                 ("DE:263[11.5 t]", "maximum_axle_weight", 11.5, "t"),
                 ("DE:264-2.2", "maximum_width", 2.2, "m"),
                 ("DE:265-3,8", "maximum_height", 3.8, "m"),
                 ("DE:266-12", "maximum_length", 12, "m")]
        for code, kind, value, unit in cases:
            with self.subTest(code=code):
                result = pilot.normalize_sign(code)
                self.assertEqual((result["kind"], result["numeric_value"], result["unit"]), (kind, value, unit))
                self.assertEqual(result["parameter_status"], "parsed_source_value")

    def test_missing_invalid_and_unknown_values_are_not_guessed(self):
        for code in ["DE:278", "DE:108", "DE:265[]", "DE:274-banana", "DE:274-0", "DE:274-30.5", "DE:265[4 t]", "DE:274-500"]:
            with self.subTest(code=code):
                self.assertIsNone(pilot.normalize_sign(code)["numeric_value"])
        unknown = pilot.normalize_sign("DE:999-42")
        self.assertIsNone(unknown["numeric_value"])
        self.assertEqual(unknown["literal_code"], "DE:999-42")
        self.assertEqual(pilot.normalize_sign("DE:331.2[]")["parameter_status"], "annotation_unverified")
        self.assertEqual(pilot.normalize_sign("DE:274-50[broken")["parameter_status"], "malformed_code")

    def test_dynamic_code_keeps_source_number_but_is_unverified(self):
        result = pilot.normalize_sign("DE:274-50[WVZ Rombachtunnel]")
        self.assertEqual(result["numeric_value"], 50)
        self.assertEqual(result["normalized_code"], "DE:274-50")
        self.assertEqual(result["literal_code"], "DE:274-50[WVZ Rombachtunnel]")
        self.assertEqual(result["parameter_status"], "dynamic_unverified")

    def test_exact_boundaries_have_thirty_metre_radius_and_reset_proposal(self):
        for code, event in [("DE:310", "city_entry"), ("DE:311", "city_exit")]:
            result = pilot.normalize_sign(code)
            self.assertEqual((result["display_radius_m"], result["proposed_boundary_event"], result["proposed_reset_prior_speed_limits"]), (30, event, 1))
        self.assertEqual(pilot.normalize_sign("DE:310[unknown]")["display_radius_m"], 10)
        self.assertIsNone(pilot.normalize_sign("DE:310[unknown]")["proposed_boundary_event"])
        self.assertEqual(pilot.normalize_sign("DE:274-30")["display_radius_m"], 10)


class ProjectionTests(unittest.TestCase):
    def test_curved_polyline_uses_local_segment_and_chainage(self):
        # A right angle: global endpoint bearing is wrong for the nearest segment.
        result = pilot.project_polyline(48.0005, 8.00105, [[48, 8], [48, 8.001], [48.001, 8.001]])
        self.assertEqual(result["segment_index"], 1)
        self.assertAlmostEqual(result["local_heading_deg"], 0, places=6)
        self.assertAlmostEqual(result["projection_lat"], 48.0005, places=6)
        self.assertAlmostEqual(result["projection_lon"], 8.001, places=6)
        self.assertGreater(result["chainage_m"], 100)
        self.assertLess(result["distance_m"], 5)

    def test_segment_clamps_and_invalid_geometry(self):
        result = pilot.project_polyline(48, 8.002, [[48, 8], [48, 8.001]])
        self.assertAlmostEqual(result["projection_lon"], 8.001)
        self.assertAlmostEqual(result["local_heading_deg"], 90)
        self.assertIsNone(pilot.project_polyline(48, 8, [[48, 8], [48, 8]]))
        with self.assertRaises(ValueError):
            pilot.project_polyline(48, 8, [[48, 8], [float("nan"), 8]])

    def test_invalid_query_poles_and_antimeridian_are_rejected(self):
        points = [[48, 8], [48.001, 8]]
        for lat, lon in [(float("nan"), 8), (48, float("inf")), (None, 8), (True, 8),
                         (91, 8), (48, 181), (85, 8), (-90, 8)]:
            with self.subTest(lat=lat, lon=lon), self.assertRaises(ValueError):
                pilot.project_polyline(lat, lon, points)
        with self.assertRaisesRegex(ValueError, "Antimeridian"):
            pilot.project_polyline(48, 179.9, [[48, 179.8], [48, -179.8]])
        with self.assertRaisesRegex(ValueError, "latitude"):
            pilot.project_polyline(48, 8, [[48, 8], [85, 8]])


class EnrichmentTests(unittest.TestCase):
    def setUp(self):
        self.db = sqlite3.connect(":memory:")
        self.db.executescript("""
            CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
            INSERT INTO metadata VALUES('schema_version','1');
            CREATE TABLE settlement_sign(sign_id TEXT);
            INSERT INTO settlement_sign VALUES('existing-osm-sign');
            CREATE TABLE traffic_sign_source(source_id TEXT PRIMARY KEY,snapshot_sha256 TEXT,snapshot_timestamp TEXT,record_count INTEGER,usage_role TEXT);
            INSERT INTO traffic_sign_source VALUES('test','abc','2026-10-17',3,'inventory_only');
            CREATE TABLE traffic_sign_inventory(row_id INTEGER PRIMARY KEY,source_id TEXT,record_key TEXT,sign_code TEXT,latitude REAL,longitude REAL);
            INSERT INTO traffic_sign_inventory VALUES(1,'test','one','DE:310',48.0005,8.0005);
            INSERT INTO traffic_sign_inventory VALUES(2,'test','two','DE:274-30',48.0005,8.0005);
            INSERT INTO traffic_sign_inventory VALUES(3,'test','three','DE:265-3.8',49,9);
            CREATE TABLE ways(way_id INTEGER PRIMARY KEY,maxspeed TEXT);
            CREATE VIRTUAL TABLE ways_rtree USING rtree(way_id,min_lon,max_lon,min_lat,max_lat);
            CREATE TABLE way_geom(way_id INTEGER PRIMARY KEY,points_json TEXT);
            """)
        self.add_way(10, [[48, 8.0004], [48.001, 8.0004]], "50")
        self.add_way(20, [[48, 8.0006], [48.001, 8.0006]], "70")

    def tearDown(self):
        self.db.close()

    def add_way(self, way_id, points, speed):
        self.db.execute("INSERT INTO ways VALUES(?,?)", (way_id, speed))
        self.db.execute("INSERT INTO way_geom VALUES(?,?)", (way_id, json.dumps(points)))
        self.db.execute("INSERT INTO ways_rtree VALUES(?,?,?,?,?)", (way_id, min(p[1] for p in points), max(p[1] for p in points), min(p[0] for p in points), max(p[0] for p in points)))

    def snapshot_runtime(self):
        return {name: self.db.execute("SELECT * FROM " + name + " ORDER BY 1").fetchall()
                for name in ["metadata", "settlement_sign", "traffic_sign_source", "traffic_sign_inventory", "ways", "ways_rtree", "way_geom"]}

    def test_parallel_roads_stay_ambiguous_and_no_candidate_is_explicit(self):
        before = self.snapshot_runtime()
        report = pilot.enrich_pilot(self.db)
        self.assertEqual(self.snapshot_runtime(), before)
        self.assertEqual(report["counts"], {"signs": 3, "way_candidates": 4})
        self.assertEqual(report["associations"], {"ambiguous": 2, "no_candidate": 1})
        self.assertFalse(report["field_ready"])
        self.assertEqual(self.db.execute("SELECT inventory_row_id,association_status,candidate_count,enabled FROM traffic_sign_v15_rule ORDER BY 1").fetchall(), [(1, "ambiguous", 2, 0), (2, "ambiguous", 2, 0), (3, "no_candidate", 0, 0)])
        self.assertEqual(set(self.db.execute("SELECT travel_direction,enabled FROM traffic_sign_v15_way_candidate")), {("unknown", 0)})
        self.assertEqual(set(row[0] for row in self.db.execute("SELECT osm_maxspeed FROM traffic_sign_v15_way_candidate")), {"50", "70"})
        with self.assertRaises(sqlite3.IntegrityError):
            self.db.execute("UPDATE traffic_sign_v15_rule SET enabled=1")

    def test_single_candidate_is_still_direction_unverified(self):
        self.db.execute("DELETE FROM ways_rtree WHERE way_id=20")
        report = pilot.enrich_pilot(self.db)
        self.assertEqual(report["associations"]["single_candidate_direction_unverified"], 2)

    def test_rebuild_is_deterministic_and_removes_stale_rows(self):
        first_report = pilot.enrich_pilot(self.db)
        first = self.db.execute("SELECT * FROM traffic_sign_v15_rule ORDER BY 1").fetchall()
        candidates = self.db.execute("SELECT * FROM traffic_sign_v15_way_candidate ORDER BY 1,2").fetchall()
        self.assertEqual(pilot.enrich_pilot(self.db), first_report)
        self.assertEqual(self.db.execute("SELECT * FROM traffic_sign_v15_rule ORDER BY 1").fetchall(), first)
        self.assertEqual(self.db.execute("SELECT * FROM traffic_sign_v15_way_candidate ORDER BY 1,2").fetchall(), candidates)
        self.db.execute("DELETE FROM traffic_sign_inventory WHERE row_id=2")
        pilot.enrich_pilot(self.db)
        self.assertEqual(self.db.execute("SELECT count(*) FROM traffic_sign_v15_rule").fetchone()[0], 2)
        self.assertIsNone(self.db.execute("SELECT 1 FROM traffic_sign_v15_way_candidate WHERE inventory_row_id=2").fetchone())

    def test_failed_rebuild_rolls_back_existing_pilot(self):
        pilot.enrich_pilot(self.db)
        before = self.db.execute("SELECT * FROM traffic_sign_v15_rule ORDER BY 1").fetchall()
        self.db.execute("CREATE TRIGGER fail_pilot BEFORE INSERT ON traffic_sign_v15_rule BEGIN SELECT RAISE(ABORT,'test rollback'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            pilot.enrich_pilot(self.db)
        self.assertEqual(self.db.execute("SELECT * FROM traffic_sign_v15_rule ORDER BY 1").fetchall(), before)

    def test_no_way_candidates_and_corrupt_geometry_are_visible(self):
        report = pilot.enrich_pilot(self.db, include_way_candidates=False)
        self.assertEqual(report["associations"], {"not_computed": 3})
        self.db.execute("UPDATE way_geom SET points_json='invalid' WHERE way_id=10")
        report = pilot.enrich_pilot(self.db)
        self.assertEqual(report["invalid_geometry_ways"], 1)

    def test_invalid_source_query_and_antimeridian_bounds_roll_back(self):
        pilot.enrich_pilot(self.db)
        before = self.db.execute("SELECT * FROM traffic_sign_v15_rule ORDER BY 1").fetchall()
        for lat, lon in [(None, 8), (90, 8), (48, float("inf")), (48, 179.999999)]:
            with self.subTest(lat=lat, lon=lon):
                self.db.execute("UPDATE traffic_sign_inventory SET latitude=?,longitude=? WHERE row_id=1", (lat, lon))
                with self.assertRaises(ValueError):
                    pilot.enrich_pilot(self.db)
                self.assertEqual(self.db.execute("SELECT * FROM traffic_sign_v15_rule ORDER BY 1").fetchall(), before)
        self.db.execute("UPDATE traffic_sign_inventory SET latitude=NULL WHERE row_id=1")
        with self.assertRaises(ValueError):
            pilot.enrich_pilot(self.db, include_way_candidates=False)


if __name__ == "__main__":
    unittest.main()
