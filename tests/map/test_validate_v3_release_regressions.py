import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "map" / "validate_v3_release_regressions.py"


def run_cmd(args, *, check=True):
    return subprocess.run(args, check=check, text=True, capture_output=True)


class ValidateV3ReleaseRegressionsTests(unittest.TestCase):
    def setUp(self):
        self.tmp_ctx = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self.tmp_ctx.name)
        self.db_path = self.tmpdir / "speeds_v3.sqlite"
        self.out_json = self.tmpdir / "regression.json"
        self._create_fixture_db(self.db_path)

    def tearDown(self):
        self.tmp_ctx.cleanup()

    @staticmethod
    def _create_fixture_db(path: Path) -> None:
        conn = sqlite3.connect(path)
        try:
            conn.executescript(
                """
                CREATE TABLE ways (
                  way_id INTEGER PRIMARY KEY,
                  highway TEXT,
                  street_name TEXT,
                  ref TEXT,
                  maxspeed TEXT,
                  maxspeed_type TEXT,
                  source_maxspeed TEXT,
                  zone_maxspeed TEXT,
                  traffic_sign TEXT,
                  approx_heading_deg REAL,
                  service TEXT,
                  tunnel TEXT,
                  min_lon REAL NOT NULL,
                  min_lat REAL NOT NULL,
                  max_lon REAL NOT NULL,
                  max_lat REAL NOT NULL
                );

                CREATE VIRTUAL TABLE ways_rtree USING rtree(
                  way_id,
                  min_lon, max_lon,
                  min_lat, max_lat
                );

                CREATE TABLE way_geom (
                  way_id INTEGER PRIMARY KEY,
                  points_json TEXT NOT NULL
                );

                CREATE TABLE areas (
                  row_id INTEGER PRIMARY KEY,
                  area_id TEXT NOT NULL UNIQUE,
                  geometry_type TEXT,
                  name TEXT,
                  place TEXT,
                  boundary TEXT,
                  admin_level TEXT,
                  residential TEXT,
                  points_json TEXT,
                  min_lon REAL NOT NULL,
                  min_lat REAL NOT NULL,
                  max_lon REAL NOT NULL,
                  max_lat REAL NOT NULL
                );

                CREATE VIRTUAL TABLE areas_rtree USING rtree(
                  row_id,
                  min_lon, max_lon,
                  min_lat, max_lat
                );

                CREATE TABLE city_boundary (
                  row_id INTEGER PRIMARY KEY,
                  osm_type TEXT NOT NULL,
                  osm_id INTEGER NOT NULL,
                  admin_level INTEGER NOT NULL,
                  name TEXT,
                  min_lon REAL NOT NULL,
                  min_lat REAL NOT NULL,
                  max_lon REAL NOT NULL,
                  max_lat REAL NOT NULL
                );

                CREATE VIRTUAL TABLE city_boundary_rtree USING rtree(
                  row_id,
                  min_lon, max_lon,
                  min_lat, max_lat
                );

                CREATE TABLE city_ring (
                  boundary_row_id INTEGER NOT NULL,
                  ring_index INTEGER NOT NULL,
                  outer_index INTEGER NOT NULL,
                  is_hole INTEGER NOT NULL,
                  points_json TEXT NOT NULL
                );

                CREATE TABLE city_place (
                  row_id INTEGER PRIMARY KEY,
                  place TEXT NOT NULL,
                  name TEXT NOT NULL,
                  lon REAL NOT NULL,
                  lat REAL NOT NULL
                );

                CREATE VIRTUAL TABLE city_place_rtree USING rtree(
                  row_id,
                  min_lon, max_lon,
                  min_lat, max_lat
                );

                INSERT INTO ways(way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, min_lon, min_lat, max_lon, max_lat)
                VALUES (100, 'residential', 'Fixture Street', 'K 9652', '30', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, 13.4050, 52.5200, 13.4060, 52.5210);

                INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
                VALUES (100, 13.4050, 13.4060, 52.5200, 52.5210);

                INSERT INTO way_geom(way_id, points_json)
                VALUES (100, '[[52.5200,13.4050],[52.5210,13.4060]]');

                INSERT INTO areas(row_id, area_id, geometry_type, name, place, boundary, admin_level, residential, points_json, min_lon, min_lat, max_lon, max_lat)
                VALUES (1, 'w:400', 'Polygon', 'Fixture City', 'city', 'administrative', '8', NULL, NULL, 13.4040, 52.5190, 13.4090, 52.5240);
                INSERT INTO areas(row_id, area_id, geometry_type, name, place, boundary, admin_level, residential, points_json, min_lon, min_lat, max_lon, max_lat)
                VALUES (2, 'w:410', 'Polygon', 'Fixture Residential', NULL, NULL, NULL, 'yes', '[[13.4050,52.5200],[13.4060,52.5200],[13.4060,52.5210],[13.4050,52.5210],[13.4050,52.5200]]', 13.4050, 52.5200, 13.4060, 52.5210);

                INSERT INTO areas_rtree(row_id, min_lon, max_lon, min_lat, max_lat)
                VALUES (1, 13.4040, 13.4090, 52.5190, 52.5240);
                INSERT INTO areas_rtree(row_id, min_lon, max_lon, min_lat, max_lat)
                VALUES (2, 13.4050, 13.4060, 52.5200, 52.5210);

                INSERT INTO city_boundary(row_id, osm_type, osm_id, admin_level, name, min_lon, min_lat, max_lon, max_lat)
                VALUES (1, 'relation', 9001, 8, 'Fixture City', 13.4040, 52.5190, 13.4090, 52.5240);
                INSERT INTO city_boundary(row_id, osm_type, osm_id, admin_level, name, min_lon, min_lat, max_lon, max_lat)
                VALUES (2, 'relation', 9002, 6, 'Fixture District', 13.4000, 52.5100, 13.4200, 52.5300);

                INSERT INTO city_boundary_rtree(row_id, min_lon, max_lon, min_lat, max_lat)
                VALUES (1, 13.4040, 13.4090, 52.5190, 52.5240);
                INSERT INTO city_boundary_rtree(row_id, min_lon, max_lon, min_lat, max_lat)
                VALUES (2, 13.4000, 13.4200, 52.5100, 52.5300);

                INSERT INTO city_ring(boundary_row_id, ring_index, outer_index, is_hole, points_json)
                VALUES (1, 0, 0, 0, '[[13.4040,52.5190],[13.4090,52.5190],[13.4090,52.5240],[13.4040,52.5240],[13.4040,52.5190]]');
                INSERT INTO city_ring(boundary_row_id, ring_index, outer_index, is_hole, points_json)
                VALUES (2, 0, 0, 0, '[[13.4000,52.5100],[13.4200,52.5100],[13.4200,52.5300],[13.4000,52.5300],[13.4000,52.5100]]');

                INSERT INTO city_place(row_id, place, name, lon, lat)
                VALUES (1, 'city', 'Fixture City', 13.4055, 52.5205);

                INSERT INTO city_place_rtree(row_id, min_lon, max_lon, min_lat, max_lat)
                VALUES (1, 13.1055, 13.7055, 52.2205, 52.8205);
                """
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _create_fixture_db_missing_columns(
        path: Path,
        *,
        include_street_name: bool,
        include_area_name: bool,
        include_ref: bool = True,
        include_area_residential: bool = True,
        include_area_points: bool = True,
    ) -> None:
        ways_street_col = "street_name TEXT," if include_street_name else ""
        ways_ref_col = "ref TEXT," if include_ref else ""
        if include_street_name and include_ref:
            ways_insert_cols = (
                "way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, "
                "zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, min_lon, min_lat, max_lon, max_lat"
            )
            ways_insert_vals = (
                "100, 'residential', 'Fixture Street', 'K 9652', '30', NULL, NULL, NULL, NULL, "
                "90.0, 'main', NULL, 13.4050, 52.5200, 13.4060, 52.5210"
            )
        elif include_street_name and not include_ref:
            ways_insert_cols = (
                "way_id, highway, street_name, maxspeed, maxspeed_type, source_maxspeed, "
                "zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, min_lon, min_lat, max_lon, max_lat"
            )
            ways_insert_vals = (
                "100, 'residential', 'Fixture Street', '30', NULL, NULL, NULL, NULL, "
                "90.0, 'main', NULL, 13.4050, 52.5200, 13.4060, 52.5210"
            )
        elif include_ref:
            ways_insert_cols = (
                "way_id, highway, ref, maxspeed, maxspeed_type, source_maxspeed, "
                "zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, min_lon, min_lat, max_lon, max_lat"
            )
            ways_insert_vals = (
                "100, 'residential', 'K 9652', '30', NULL, NULL, NULL, NULL, "
                "90.0, 'main', NULL, 13.4050, 52.5200, 13.4060, 52.5210"
            )
        else:
            ways_insert_cols = (
                "way_id, highway, maxspeed, maxspeed_type, source_maxspeed, "
                "zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, min_lon, min_lat, max_lon, max_lat"
            )
            ways_insert_vals = (
                "100, 'residential', '30', NULL, NULL, NULL, NULL, "
                "90.0, 'main', NULL, 13.4050, 52.5200, 13.4060, 52.5210"
            )
        areas_name_col = "name TEXT," if include_area_name else ""
        areas_residential_col = "residential TEXT," if include_area_residential else ""
        areas_points_col = "points_json TEXT," if include_area_points else ""
        area_insert_cols_list = ["row_id", "area_id", "geometry_type"]
        area_insert_vals_list = ["1", "'w:400'", "'Polygon'"]
        if include_area_name:
            area_insert_cols_list.append("name")
            area_insert_vals_list.append("'Fixture City'")
        area_insert_cols_list.extend(["place", "boundary", "admin_level"])
        area_insert_vals_list.extend(["'city'", "'administrative'", "'8'"])
        if include_area_residential:
            area_insert_cols_list.append("residential")
            area_insert_vals_list.append("'yes'")
        if include_area_points:
            area_insert_cols_list.append("points_json")
            area_insert_vals_list.append("'[[13.4050,52.5200],[13.4060,52.5200],[13.4060,52.5210],[13.4050,52.5210],[13.4050,52.5200]]'")
        area_insert_cols_list.extend(["min_lon", "min_lat", "max_lon", "max_lat"])
        area_insert_vals_list.extend(["13.4040", "52.5190", "13.4090", "52.5240"])
        areas_insert_cols = ", ".join(area_insert_cols_list)
        areas_insert_vals = ", ".join(area_insert_vals_list)

        conn = sqlite3.connect(path)
        try:
            conn.executescript(
                f"""
                CREATE TABLE ways (
                  way_id INTEGER PRIMARY KEY,
                  highway TEXT,
                  {ways_street_col}
                  {ways_ref_col}
                  maxspeed TEXT,
                  maxspeed_type TEXT,
                  source_maxspeed TEXT,
                  zone_maxspeed TEXT,
                  traffic_sign TEXT,
                  approx_heading_deg REAL,
                  service TEXT,
                  tunnel TEXT,
                  min_lon REAL NOT NULL,
                  min_lat REAL NOT NULL,
                  max_lon REAL NOT NULL,
                  max_lat REAL NOT NULL
                );

                CREATE VIRTUAL TABLE ways_rtree USING rtree(
                  way_id,
                  min_lon, max_lon,
                  min_lat, max_lat
                );

                CREATE TABLE way_geom (
                  way_id INTEGER PRIMARY KEY,
                  points_json TEXT NOT NULL
                );

                CREATE TABLE areas (
                  row_id INTEGER PRIMARY KEY,
                  area_id TEXT NOT NULL UNIQUE,
                  geometry_type TEXT,
                  {areas_name_col}
                  place TEXT,
                  boundary TEXT,
                  admin_level TEXT,
                  {areas_residential_col}
                  {areas_points_col}
                  min_lon REAL NOT NULL,
                  min_lat REAL NOT NULL,
                  max_lon REAL NOT NULL,
                  max_lat REAL NOT NULL
                );

                CREATE VIRTUAL TABLE areas_rtree USING rtree(
                  row_id,
                  min_lon, max_lon,
                  min_lat, max_lat
                );

                INSERT INTO ways({ways_insert_cols})
                VALUES ({ways_insert_vals});

                INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
                VALUES (100, 13.4050, 13.4060, 52.5200, 52.5210);

                INSERT INTO way_geom(way_id, points_json)
                VALUES (100, '[[52.5200,13.4050],[52.5210,13.4060]]');

                INSERT INTO areas({areas_insert_cols})
                VALUES ({areas_insert_vals});

                INSERT INTO areas_rtree(row_id, min_lon, max_lon, min_lat, max_lat)
                VALUES (1, 13.4040, 13.4090, 52.5190, 52.5240);
                """
            )
            conn.commit()
        finally:
            conn.close()

    def test_regression_validator_passes(self):
        result = run_cmd(
            [
                sys.executable,
                str(SCRIPT),
                "--db",
                str(self.db_path),
                "--probe-way-id",
                "100",
                "--expected-maxspeed-kmh",
                "30",
                "--probe-ref-way-id",
                "100",
                "--expected-ref",
                "K 9652",
                "--out-json",
                str(self.out_json),
            ]
        )
        self.assertEqual(result.returncode, 0)
        self.assertTrue(self.out_json.exists())
        payload = json.loads(self.out_json.read_text(encoding="utf-8"))
        self.assertEqual(payload["probe_way_id"], "100")
        self.assertIn("paper_benchmark_smoke", payload)
        self.assertIn("hybrid", payload["paper_benchmark_smoke"])
        self.assertEqual(payload["ref_probe"]["probe_ref_way_id"], "100")
        self.assertEqual(payload["ref_probe"]["expected_ref"], "K 9652")
        self.assertEqual(payload["ref_probe"]["actual_ref"], "K 9652")

    def test_regression_validator_fails_on_expected_speed_mismatch(self):
        result = run_cmd(
            [
                sys.executable,
                str(SCRIPT),
                "--db",
                str(self.db_path),
                "--probe-way-id",
                "100",
                "--expected-maxspeed-kmh",
                "50",
            ],
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("explicit speed mismatch", result.stderr)

    def test_regression_validator_fails_on_expected_ref_mismatch(self):
        result = run_cmd(
            [
                sys.executable,
                str(SCRIPT),
                "--db",
                str(self.db_path),
                "--probe-way-id",
                "100",
                "--expected-maxspeed-kmh",
                "30",
                "--probe-ref-way-id",
                "100",
                "--expected-ref",
                "L 564",
            ],
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ref mismatch at probe", result.stderr)

    def test_regression_validator_fails_on_missing_street_name_column(self):
        db_path = self.tmpdir / "legacy_no_street_name.sqlite"
        self._create_fixture_db_missing_columns(db_path, include_street_name=False, include_area_name=True)
        result = run_cmd(
            [
                sys.executable,
                str(SCRIPT),
                "--db",
                str(db_path),
                "--probe-way-id",
                "100",
                "--expected-maxspeed-kmh",
                "30",
            ],
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ways.street_name column missing", result.stderr)

    def test_regression_validator_fails_on_missing_area_name_column(self):
        db_path = self.tmpdir / "legacy_no_area_name.sqlite"
        self._create_fixture_db_missing_columns(db_path, include_street_name=True, include_area_name=False)
        result = run_cmd(
            [
                sys.executable,
                str(SCRIPT),
                "--db",
                str(db_path),
                "--probe-way-id",
                "100",
                "--expected-maxspeed-kmh",
                "30",
            ],
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("areas.name column missing", result.stderr)

    def test_regression_validator_fails_on_missing_ref_column(self):
        db_path = self.tmpdir / "legacy_no_ref.sqlite"
        self._create_fixture_db_missing_columns(
            db_path,
            include_street_name=True,
            include_area_name=True,
            include_ref=False,
        )
        result = run_cmd(
            [
                sys.executable,
                str(SCRIPT),
                "--db",
                str(db_path),
                "--probe-way-id",
                "100",
                "--expected-maxspeed-kmh",
                "30",
            ],
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("ways.ref column missing", result.stderr)

    def test_regression_validator_fails_on_missing_area_residential_column(self):
        db_path = self.tmpdir / "legacy_no_area_residential.sqlite"
        self._create_fixture_db_missing_columns(
            db_path,
            include_street_name=True,
            include_area_name=True,
            include_area_residential=False,
            include_area_points=True,
        )
        result = run_cmd(
            [
                sys.executable,
                str(SCRIPT),
                "--db",
                str(db_path),
                "--probe-way-id",
                "100",
                "--expected-maxspeed-kmh",
                "30",
            ],
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("areas.residential column missing", result.stderr)

    def test_regression_validator_fails_on_missing_area_points_json_column(self):
        db_path = self.tmpdir / "legacy_no_area_points.sqlite"
        self._create_fixture_db_missing_columns(
            db_path,
            include_street_name=True,
            include_area_name=True,
            include_area_residential=True,
            include_area_points=False,
        )
        result = run_cmd(
            [
                sys.executable,
                str(SCRIPT),
                "--db",
                str(db_path),
                "--probe-way-id",
                "100",
                "--expected-maxspeed-kmh",
                "30",
            ],
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("areas.points_json column missing", result.stderr)

if __name__ == "__main__":
    unittest.main()
