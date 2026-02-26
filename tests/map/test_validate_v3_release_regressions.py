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
                  row_id INTEGER PRIMARY KEY,
                  way_id TEXT NOT NULL UNIQUE,
                  highway TEXT,
                  street_name TEXT,
                  maxspeed TEXT,
                  maxspeed_type TEXT,
                  source_maxspeed TEXT,
                  zone_maxspeed TEXT,
                  traffic_sign TEXT,
                  approx_heading_deg REAL,
                  min_lon REAL NOT NULL,
                  min_lat REAL NOT NULL,
                  max_lon REAL NOT NULL,
                  max_lat REAL NOT NULL
                );

                CREATE VIRTUAL TABLE ways_rtree USING rtree(
                  row_id,
                  min_lon, max_lon,
                  min_lat, max_lat
                );

                CREATE TABLE way_geom (
                  row_id INTEGER PRIMARY KEY,
                  way_id TEXT NOT NULL UNIQUE,
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

                INSERT INTO ways(row_id, way_id, highway, street_name, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, min_lon, min_lat, max_lon, max_lat)
                VALUES (1, '100', 'residential', 'Fixture Street', '30', NULL, NULL, NULL, NULL, 90.0, 13.4050, 52.5200, 13.4060, 52.5210);

                INSERT INTO ways_rtree(row_id, min_lon, max_lon, min_lat, max_lat)
                VALUES (1, 13.4050, 13.4060, 52.5200, 52.5210);

                INSERT INTO way_geom(row_id, way_id, points_json)
                VALUES (1, '100', '[[52.5200,13.4050],[52.5210,13.4060]]');

                INSERT INTO areas(row_id, area_id, geometry_type, name, place, boundary, admin_level, min_lon, min_lat, max_lon, max_lat)
                VALUES (1, 'w:400', 'Polygon', 'Fixture City', 'city', 'administrative', '8', 13.4040, 52.5190, 13.4090, 52.5240);

                INSERT INTO areas_rtree(row_id, min_lon, max_lon, min_lat, max_lat)
                VALUES (1, 13.4040, 13.4090, 52.5190, 52.5240);
                """
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _create_fixture_db_missing_columns(
        path: Path, *, include_street_name: bool, include_area_name: bool
    ) -> None:
        ways_street_col = "street_name TEXT," if include_street_name else ""
        ways_insert_cols = (
            "row_id, way_id, highway, street_name, maxspeed, maxspeed_type, source_maxspeed, "
            "zone_maxspeed, traffic_sign, approx_heading_deg, min_lon, min_lat, max_lon, max_lat"
            if include_street_name
            else "row_id, way_id, highway, maxspeed, maxspeed_type, source_maxspeed, "
            "zone_maxspeed, traffic_sign, approx_heading_deg, min_lon, min_lat, max_lon, max_lat"
        )
        ways_insert_vals = (
            "1, '100', 'residential', 'Fixture Street', '30', NULL, NULL, NULL, NULL, 90.0, 13.4050, 52.5200, 13.4060, 52.5210"
            if include_street_name
            else "1, '100', 'residential', '30', NULL, NULL, NULL, NULL, 90.0, 13.4050, 52.5200, 13.4060, 52.5210"
        )
        areas_name_col = "name TEXT," if include_area_name else ""
        areas_insert_cols = (
            "row_id, area_id, geometry_type, name, place, boundary, admin_level, min_lon, min_lat, max_lon, max_lat"
            if include_area_name
            else "row_id, area_id, geometry_type, place, boundary, admin_level, min_lon, min_lat, max_lon, max_lat"
        )
        areas_insert_vals = (
            "1, 'w:400', 'Polygon', 'Fixture City', 'city', 'administrative', '8', 13.4040, 52.5190, 13.4090, 52.5240"
            if include_area_name
            else "1, 'w:400', 'Polygon', 'city', 'administrative', '8', 13.4040, 52.5190, 13.4090, 52.5240"
        )

        conn = sqlite3.connect(path)
        try:
            conn.executescript(
                f"""
                CREATE TABLE ways (
                  row_id INTEGER PRIMARY KEY,
                  way_id TEXT NOT NULL UNIQUE,
                  highway TEXT,
                  {ways_street_col}
                  maxspeed TEXT,
                  maxspeed_type TEXT,
                  source_maxspeed TEXT,
                  zone_maxspeed TEXT,
                  traffic_sign TEXT,
                  approx_heading_deg REAL,
                  min_lon REAL NOT NULL,
                  min_lat REAL NOT NULL,
                  max_lon REAL NOT NULL,
                  max_lat REAL NOT NULL
                );

                CREATE VIRTUAL TABLE ways_rtree USING rtree(
                  row_id,
                  min_lon, max_lon,
                  min_lat, max_lat
                );

                CREATE TABLE way_geom (
                  row_id INTEGER PRIMARY KEY,
                  way_id TEXT NOT NULL UNIQUE,
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

                INSERT INTO ways_rtree(row_id, min_lon, max_lon, min_lat, max_lat)
                VALUES (1, 13.4050, 13.4060, 52.5200, 52.5210);

                INSERT INTO way_geom(row_id, way_id, points_json)
                VALUES (1, '100', '[[52.5200,13.4050],[52.5210,13.4060]]');

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


if __name__ == "__main__":
    unittest.main()
