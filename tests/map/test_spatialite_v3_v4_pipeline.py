import json
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKER = REPO_ROOT / "scripts/map/pack_runtime_artifacts_pyosmium.py"
BUILD_V3 = REPO_ROOT / "scripts/map/build_spatialite_v3.py"
BUILD_V4 = REPO_ROOT / "scripts/map/build_spatialite_v4.py"
QUERY_V3 = REPO_ROOT / "scripts/map/query_speed_limit_v3.py"
QUERY_V4 = REPO_ROOT / "scripts/map/query_speed_limit_v4.py"

ALLOWED_CAR_HIGHWAYS = {
    "motorway",
    "trunk",
    "primary",
    "secondary",
    "tertiary",
    "unclassified",
    "residential",
    "service",
    "living_street",
    "motorway_link",
    "trunk_link",
    "primary_link",
    "secondary_link",
    "tertiary_link",
    "road",
}


def run_cmd(args, *, check=True):
    return subprocess.run(args, check=check, text=True, capture_output=True)


class SpatialiteV3V4PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir_ctx = tempfile.TemporaryDirectory()
        cls.tmpdir = Path(cls.tmpdir_ctx.name)

        cls.input_osm = cls.tmpdir / "fixture.osm"
        cls.dist_v1 = cls.tmpdir / "dist_v1"
        cls.db_v3 = cls.tmpdir / "speeds_v3.sqlite"
        cls.db_v4 = cls.tmpdir / "speeds_v4.sqlite"
        cls.dist_v1.mkdir(parents=True, exist_ok=True)
        cls.input_osm.write_text(cls._fixture_osm(), encoding="utf-8")

        run_cmd(
            [
                sys.executable,
                str(PACKER),
                str(cls.input_osm),
                str(cls.dist_v1 / "ways.idx"),
                str(cls.dist_v1 / "ways.meta"),
                str(cls.dist_v1 / "areas.idx"),
                str(cls.dist_v1 / "ways.lookup"),
                str(cls.dist_v1 / "ways.geom"),
                str(cls.dist_v1 / "ways.geom.lookup"),
            ]
        )

        run_cmd(
            [
                sys.executable,
                str(BUILD_V3),
                "--v1-dist",
                str(cls.dist_v1),
                "--out-db",
                str(cls.db_v3),
            ]
        )
        run_cmd(
            [
                sys.executable,
                str(BUILD_V4),
                "--v1-dist",
                str(cls.dist_v1),
                "--out-db",
                str(cls.db_v4),
                "--tile-size-m",
                "1024",
            ]
        )

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir_ctx.cleanup()

    @staticmethod
    def _fixture_osm() -> str:
        return textwrap.dedent(
            """\
            <?xml version='1.0' encoding='UTF-8'?>
            <osm version='0.6' generator='youspeed-tests-v3v4'>
              <node id='1' lat='49.0020' lon='8.0020'/>
              <node id='2' lat='49.0020' lon='8.0040'/>
              <node id='3' lat='49.0300' lon='8.0300'/>
              <node id='4' lat='49.0300' lon='8.0320'/>
              <node id='5' lat='49.0500' lon='8.0500'/>
              <node id='6' lat='49.0500' lon='8.0520'/>
              <node id='7' lat='49.0310' lon='8.0310'/>
              <node id='8' lat='49.0320' lon='8.0320'/>
              <node id='301' lat='49.0340' lon='8.0340'/>
              <node id='302' lat='49.0340' lon='8.0350'/>
              <node id='303' lat='49.0350' lon='8.0350'/>
              <node id='304' lat='49.0350' lon='8.0340'/>
              <node id='401' lat='49.0000' lon='8.0000'/>
              <node id='402' lat='49.0000' lon='8.0100'/>
              <node id='403' lat='49.0100' lon='8.0100'/>
              <node id='404' lat='49.0100' lon='8.0000'/>
              <node id='501' lat='49.0010' lon='8.0010'/>
              <node id='502' lat='49.0010' lon='8.0060'/>
              <node id='503' lat='49.0060' lon='8.0060'/>
              <node id='504' lat='49.0060' lon='8.0010'/>

              <way id='100'>
                <nd ref='1'/>
                <nd ref='2'/>
                <tag k='highway' v='service'/>
              </way>
              <way id='101'>
                <nd ref='3'/>
                <nd ref='4'/>
                <tag k='highway' v='residential'/>
                <tag k='maxspeed' v='30'/>
              </way>
              <way id='102'>
                <nd ref='5'/>
                <nd ref='6'/>
                <tag k='highway' v='service'/>
              </way>
              <way id='200'>
                <nd ref='7'/>
                <nd ref='8'/>
                <tag k='highway' v='footway'/>
                <tag k='maxspeed' v='5'/>
              </way>
              <way id='300'>
                <nd ref='301'/>
                <nd ref='302'/>
                <nd ref='303'/>
                <nd ref='304'/>
                <nd ref='301'/>
                <tag k='building' v='yes'/>
              </way>
              <way id='400'>
                <nd ref='401'/>
                <nd ref='402'/>
                <nd ref='403'/>
                <nd ref='404'/>
                <nd ref='401'/>
                <tag k='boundary' v='administrative'/>
                <tag k='admin_level' v='8'/>
                <tag k='name' v='Teststadt Boundary'/>
              </way>
              <way id='410'>
                <nd ref='501'/>
                <nd ref='502'/>
                <nd ref='503'/>
                <nd ref='504'/>
                <nd ref='501'/>
                <tag k='residential' v='yes'/>
                <tag k='name' v='Teststadt Residential Zone'/>
              </way>
            </osm>
            """
        )

    def run_query_v3(self, lat, lon, heading=90.0, distance_mode=None):
        args = [
            sys.executable,
            str(QUERY_V3),
            "--db",
            str(self.db_v3),
            "--lat",
            str(lat),
            "--lon",
            str(lon),
            "--heading",
            str(heading),
        ]
        if distance_mode:
            args.extend(["--distance-mode", distance_mode])
        result = run_cmd(args)
        return result, json.loads(result.stdout)

    def run_query_v4(self, lat, lon, heading=90.0, distance_mode=None):
        args = [
            sys.executable,
            str(QUERY_V4),
            "--db",
            str(self.db_v4),
            "--lat",
            str(lat),
            "--lon",
            str(lon),
            "--heading",
            str(heading),
            "--tile-radius",
            "1",
        ]
        if distance_mode:
            args.extend(["--distance-mode", distance_mode])
        result = run_cmd(args)
        return result, json.loads(result.stdout)

    def test_build_outputs_databases(self):
        self.assertTrue(self.db_v3.exists())
        self.assertTrue(self.db_v4.exists())
        self.assertGreater(self.db_v3.stat().st_size, 0)
        self.assertGreater(self.db_v4.stat().st_size, 0)

    def test_non_car_ways_not_present_in_v3_v4(self):
        with sqlite3.connect(self.db_v3) as conn:
            rows = conn.execute("SELECT DISTINCT highway FROM ways").fetchall()
            values = {r[0] for r in rows if r[0] is not None}
        self.assertTrue(values.issubset(ALLOWED_CAR_HIGHWAYS))
        self.assertNotIn("footway", values)

        with sqlite3.connect(self.db_v4) as conn:
            rows = conn.execute("SELECT DISTINCT highway FROM ways").fetchall()
            values = {r[0] for r in rows if r[0] is not None}
        self.assertTrue(values.issubset(ALLOWED_CAR_HIGHWAYS))
        self.assertNotIn("footway", values)

    def test_query_v3_explicit_speed(self):
        _, payload = self.run_query_v3(49.0300, 8.0310)
        summary = payload["summary"]
        self.assertEqual(summary["effective_speed_source"], "map_explicit")
        self.assertEqual(summary["effective_speed_kmh"], 30)
        self.assertGreaterEqual(summary["matched_way_rows"], 1)
        self.assertIn("query_time_ms=", _.stderr)

    def test_query_v4_explicit_speed(self):
        _, payload = self.run_query_v4(49.0300, 8.0310)
        summary = payload["summary"]
        self.assertEqual(summary["effective_speed_source"], "map_explicit")
        self.assertEqual(summary["effective_speed_kmh"], 30)
        self.assertGreaterEqual(summary["matched_way_rows"], 1)
        self.assertIn("/", payload["input"]["query_tile"])

    def test_query_defaults_inside_and_outside_city(self):
        _, inside_v3 = self.run_query_v3(49.0020, 8.0030)
        _, outside_v3 = self.run_query_v3(49.0500, 8.0510)
        self.assertTrue(inside_v3["summary"]["inside_built_up_guess"])
        self.assertEqual(inside_v3["summary"]["effective_speed_kmh"], 50)
        self.assertFalse(outside_v3["summary"]["inside_built_up_guess"])
        self.assertEqual(outside_v3["summary"]["effective_speed_kmh"], 100)

        _, inside_v4 = self.run_query_v4(49.0020, 8.0030)
        _, outside_v4 = self.run_query_v4(49.0500, 8.0510)
        self.assertTrue(inside_v4["summary"]["inside_built_up_guess"])
        self.assertEqual(inside_v4["summary"]["effective_speed_kmh"], 50)
        self.assertFalse(outside_v4["summary"]["inside_built_up_guess"])
        self.assertEqual(outside_v4["summary"]["effective_speed_kmh"], 100)

    def test_query_modes_polyline_active(self):
        _, payload_v3 = self.run_query_v3(49.0300, 8.0310, distance_mode="polyline")
        _, payload_v4 = self.run_query_v4(49.0300, 8.0310, distance_mode="polyline")
        self.assertEqual(payload_v3["summary"]["distance_mode_effective"], "polyline")
        self.assertEqual(payload_v4["summary"]["distance_mode_effective"], "polyline")

    def test_query_v3_negative_missing_db(self):
        missing_db = self.tmpdir / "missing.sqlite"
        result = run_cmd(
            [
                sys.executable,
                str(QUERY_V3),
                "--db",
                str(missing_db),
                "--lat",
                "49.0",
                "--lon",
                "8.0",
            ],
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing artifact", result.stderr)

    def test_query_v4_negative_invalid_coordinates(self):
        result = run_cmd(
            [
                sys.executable,
                str(QUERY_V4),
                "--db",
                str(self.db_v4),
                "--lat",
                "200.0",
                "--lon",
                "8.0",
            ],
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid coordinate range", result.stderr)

    def test_query_v3_v4_consistent_effective_limits(self):
        probe_points = [
            (49.0300, 8.0310),  # explicit 30
            (49.0020, 8.0030),  # inside city default
            (49.0500, 8.0510),  # outside city default
        ]
        for lat, lon in probe_points:
            _, p3 = self.run_query_v3(lat, lon)
            _, p4 = self.run_query_v4(lat, lon)
            self.assertEqual(p3["summary"]["effective_speed_kmh"], p4["summary"]["effective_speed_kmh"])
            self.assertEqual(p3["summary"]["effective_speed_source"], p4["summary"]["effective_speed_source"])


if __name__ == "__main__":
    unittest.main()
