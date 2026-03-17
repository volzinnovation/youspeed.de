import json
import shutil
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PACKER = REPO_ROOT / "scripts/map/pack_runtime_artifacts_pyosmium.py"
MANIFEST = REPO_ROOT / "scripts/map/generate_manifest.sh"
CHECK_ARTIFACTS = REPO_ROOT / "scripts/map/check_artifacts.sh"
QUERY = REPO_ROOT / "scripts/map/query_speed_limit.py"

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


class MapPipelineIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir_ctx = tempfile.TemporaryDirectory()
        cls.tmpdir = Path(cls.tmpdir_ctx.name)

        cls.input_osm = cls.tmpdir / "fixture.osm"
        cls.dist_dir = cls.tmpdir / "dist"
        cls.dist_dir.mkdir(parents=True, exist_ok=True)

        cls.ways_idx = cls.dist_dir / "ways.idx"
        cls.ways_meta = cls.dist_dir / "ways.meta"
        cls.areas_idx = cls.dist_dir / "areas.idx"
        cls.ways_lookup = cls.dist_dir / "ways.lookup"
        cls.ways_geom = cls.dist_dir / "ways.geom"
        cls.ways_geom_lookup = cls.dist_dir / "ways.geom.lookup"
        cls.manifest = cls.dist_dir / "manifest.json"

        cls.input_osm.write_text(cls._fixture_osm(), encoding="utf-8")

        run_cmd(
            [
                sys.executable,
                str(PACKER),
                str(cls.input_osm),
                str(cls.ways_idx),
                str(cls.ways_meta),
                str(cls.areas_idx),
                str(cls.ways_lookup),
                str(cls.ways_geom),
                str(cls.ways_geom_lookup),
            ]
        )

        run_cmd(
            [
                str(MANIFEST),
                "test-fixture",
                str(cls.input_osm),
                str(cls.ways_idx),
                str(cls.ways_meta),
                str(cls.areas_idx),
                str(cls.ways_lookup),
                str(cls.ways_geom),
                str(cls.ways_geom_lookup),
                str(cls.manifest),
            ]
        )

        cls.way_rows = [
            json.loads(line)
            for line in cls.ways_meta.read_text(encoding="utf-8").splitlines()
            if line.strip()
        ]
        cls.area_rows = json.loads(cls.areas_idx.read_text(encoding="utf-8")).get("areas", [])

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir_ctx.cleanup()

    @staticmethod
    def _fixture_osm() -> str:
        return textwrap.dedent(
            """\
            <?xml version='1.0' encoding='UTF-8'?>
            <osm version='0.6' generator='youspeed-tests'>
              <node id='1' lat='49.0020' lon='8.0020'/>
              <node id='2' lat='49.0020' lon='8.0040'/>
              <node id='3' lat='49.0300' lon='8.0300'/>
              <node id='4' lat='49.0300' lon='8.0320'/>
              <node id='5' lat='49.0500' lon='8.0500'/>
              <node id='6' lat='49.0500' lon='8.0800'/>
              <node id='7' lat='49.0600' lon='8.0600'/>
              <node id='8' lat='49.0605' lon='8.0610'/>
              <node id='9' lat='49.0700' lon='8.0700'/>
              <node id='10' lat='49.0710' lon='8.0710'/>
              <node id='11' lat='49.0900' lon='8.0900'/>
              <node id='12' lat='49.0910' lon='8.0910'/>
              <node id='13' lat='49.0400' lon='8.0400'/>
              <node id='14' lat='49.0410' lon='8.0410'/>
              <node id='15' lat='49.0420' lon='8.0420'/>
              <node id='16' lat='49.0430' lon='8.0430'/>
              <node id='17' lat='49.2000' lon='8.2000'/>
              <node id='18' lat='49.2010' lon='8.2020'/>
              <node id='19' lat='49.1100' lon='8.1100'/>
              <node id='20' lat='49.1110' lon='8.1110'/>
              <node id='21' lat='49.1200' lon='8.1200'/>
              <node id='22' lat='49.1210' lon='8.1210'/>
              <node id='301' lat='49.0440' lon='8.0440'/>
              <node id='302' lat='49.0440' lon='8.0450'/>
              <node id='303' lat='49.0450' lon='8.0450'/>
              <node id='304' lat='49.0450' lon='8.0440'/>
              <node id='401' lat='49.0000' lon='8.0000'/>
              <node id='402' lat='49.0000' lon='8.0100'/>
              <node id='403' lat='49.0100' lon='8.0100'/>
              <node id='404' lat='49.0100' lon='8.0000'/>
              <node id='451' lat='49.1500' lon='8.1500'/>
              <node id='452' lat='49.1500' lon='8.1600'/>
              <node id='453' lat='49.1600' lon='8.1600'/>
              <node id='454' lat='49.1600' lon='8.1500'/>
              <node id='500' lat='49.0050' lon='8.0050'>
                <tag k='place' v='city'/>
                <tag k='name' v='Teststadt'/>
              </node>

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
                <tag k='highway' v='motorway'/>
                <tag k='maxspeed' v='120'/>
              </way>
              <way id='103'>
                <nd ref='7'/>
                <nd ref='8'/>
                <tag k='highway' v='living_street'/>
                <tag k='zone:maxspeed' v='20'/>
              </way>
              <way id='104'>
                <nd ref='9'/>
                <nd ref='10'/>
                <tag k='highway' v='primary_link'/>
                <tag k='source:maxspeed' v='DE:rural'/>
              </way>
              <way id='105'>
                <nd ref='11'/>
                <nd ref='12'/>
                <tag k='highway' v='tertiary'/>
                <tag k='maxspeed:conditional' v='30 @ (Mo-Fr 07:00-18:00)'/>
              </way>
              <way id='106'>
                <nd ref='17'/>
                <nd ref='18'/>
                <tag k='highway' v='service'/>
              </way>
              <way id='107'>
                <nd ref='19'/>
                <nd ref='20'/>
                <tag k='highway' v='trunk_link'/>
                <tag k='maxspeed' v='80 km/h'/>
              </way>
              <way id='108'>
                <nd ref='21'/>
                <nd ref='22'/>
                <tag k='highway' v='road'/>
                <tag k='maxspeed:type' v='DE:urban'/>
              </way>

              <way id='200'>
                <nd ref='13'/>
                <nd ref='14'/>
                <tag k='highway' v='footway'/>
                <tag k='maxspeed' v='5'/>
              </way>
              <way id='201'>
                <nd ref='14'/>
                <nd ref='15'/>
                <tag k='highway' v='cycleway'/>
              </way>
              <way id='202'>
                <nd ref='15'/>
                <nd ref='16'/>
                <tag k='highway' v='path'/>
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
              <way id='450'>
                <nd ref='451'/>
                <nd ref='452'/>
                <nd ref='453'/>
                <nd ref='454'/>
                <nd ref='451'/>
                <tag k='boundary' v='administrative'/>
                <tag k='admin_level' v='6'/>
              </way>

              <relation id='900'>
                <member type='way' ref='450' role='outer'/>
                <tag k='type' v='boundary'/>
                <tag k='boundary' v='administrative'/>
                <tag k='admin_level' v='6'/>
                <tag k='name' v='Testkreis'/>
              </relation>
            </osm>
            """
        )

    def run_query(
        self,
        lat,
        lon,
        heading=90.0,
        radius_cells=0,
        top_k=5,
        distance_mode=None,
        polyline_top_n=None,
    ):
        args = [
            sys.executable,
            str(QUERY),
            "--dist-dir",
            str(self.dist_dir),
            "--lat",
            str(lat),
            "--lon",
            str(lon),
            "--radius-cells",
            str(radius_cells),
            "--top-k",
            str(top_k),
        ]
        if heading is not None:
            args.extend(["--heading", str(heading)])
        if distance_mode is not None:
            args.extend(["--distance-mode", str(distance_mode)])
        if polyline_top_n is not None:
            args.extend(["--polyline-top-n", str(polyline_top_n)])

        result = run_cmd(args)
        payload = json.loads(result.stdout)
        return result, payload

    def test_dataset_excludes_non_car_ways_and_shapes(self):
        way_ids = {row["way_id"] for row in self.way_rows}
        highways = {row["highway"] for row in self.way_rows}

        self.assertNotIn("200", way_ids)
        self.assertNotIn("201", way_ids)
        self.assertNotIn("202", way_ids)
        self.assertNotIn("300", way_ids)

        self.assertTrue(highways.issubset(ALLOWED_CAR_HIGHWAYS))
        self.assertNotIn("footway", highways)
        self.assertNotIn("cycleway", highways)
        self.assertNotIn("path", highways)

    def test_dataset_contains_expected_car_road_types(self):
        highways = {row["highway"] for row in self.way_rows}
        expected = {"service", "residential", "motorway", "living_street", "primary_link", "tertiary", "trunk_link", "road"}
        self.assertTrue(expected.issubset(highways))

    def test_dataset_captures_named_admin_relation_areas(self):
        admin_rows = [row for row in self.area_rows if row.get("boundary") == "administrative"]
        rows_by_id = {row["area_id"]: row for row in admin_rows}

        self.assertEqual(rows_by_id["w:400"]["name"], "Teststadt Boundary")
        self.assertEqual(rows_by_id["r:900"]["name"], "Testkreis")
        self.assertEqual(rows_by_id["r:900"]["admin_level"], "6")
        self.assertNotIn("w:450", rows_by_id)
        self.assertFalse(any(not (row.get("name") or "").strip() for row in admin_rows))

    def test_query_uses_named_admin_relation_area(self):
        _, payload = self.run_query(49.1550, 8.1550, heading=None, radius_cells=1)
        summary = payload["summary"]

        self.assertEqual(summary["city_name"], "Testkreis")
        self.assertEqual(summary["city_admin_level"], 6)
        self.assertEqual(summary["city_source"], "admin_bbox")

    def test_check_artifacts_passes_for_valid_fixture(self):
        run_cmd([str(CHECK_ARTIFACTS), str(self.dist_dir)])

    def test_check_artifacts_negative_non_car_highway(self):
        bad_dir = self.tmpdir / "dist_bad"
        if bad_dir.exists():
            shutil.rmtree(bad_dir)
        shutil.copytree(self.dist_dir, bad_dir)

        ways_meta = bad_dir / "ways.meta"
        rows = [json.loads(line) for line in ways_meta.read_text(encoding="utf-8").splitlines() if line.strip()]
        rows[0]["highway"] = "footway"
        ways_meta.write_text("\n".join(json.dumps(row, sort_keys=True, separators=(",", ":")) for row in rows) + "\n", encoding="utf-8")

        run_cmd(
            [
                str(MANIFEST),
                "test-fixture-bad",
                str(self.input_osm),
                str(bad_dir / "ways.idx"),
                str(ways_meta),
                str(bad_dir / "areas.idx"),
                str(bad_dir / "ways.lookup"),
                str(bad_dir / "ways.geom"),
                str(bad_dir / "ways.geom.lookup"),
                str(bad_dir / "manifest.json"),
            ]
        )

        result = run_cmd([str(CHECK_ARTIFACTS), str(bad_dir)], check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("non-car-drivable", result.stderr)

    def test_query_logs_timing_and_exposes_timing_fields(self):
        result, payload = self.run_query(49.0300, 8.0310)
        self.assertIn("query_time_ms=", result.stderr)

        timing = payload.get("timing_ms", {})
        self.assertIn("load_index", timing)
        self.assertIn("load_candidates", timing)
        self.assertIn("polyline_refine", timing)
        self.assertIn("score_and_rank", timing)
        self.assertIn("total", timing)
        self.assertGreaterEqual(timing["total"], 0.0)
        self.assertEqual(payload["summary"]["candidate_load_mode"], "lookup")
        self.assertIn(payload["summary"]["distance_mode_effective"], {"bbox", "polyline"})

    def test_query_falls_back_to_scan_when_lookup_missing(self):
        scan_dir = self.tmpdir / "dist_scan_only"
        if scan_dir.exists():
            shutil.rmtree(scan_dir)
        scan_dir.mkdir(parents=True)
        shutil.copy2(self.ways_idx, scan_dir / "ways.idx")
        shutil.copy2(self.ways_meta, scan_dir / "ways.meta")
        shutil.copy2(self.areas_idx, scan_dir / "areas.idx")

        result = run_cmd(
            [
                sys.executable,
                str(QUERY),
                "--dist-dir",
                str(scan_dir),
                "--lat",
                "49.03",
                "--lon",
                "8.031",
            ],
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["summary"]["candidate_load_mode"], "scan")

    def test_query_polyline_mode_active(self):
        _, payload = self.run_query(49.0300, 8.0310, distance_mode="polyline")
        summary = payload["summary"]
        self.assertEqual(summary["distance_mode_requested"], "polyline")
        self.assertEqual(summary["distance_mode_effective"], "polyline")
        self.assertEqual(summary["polyline_refine_mode"], "active")
        self.assertGreater(summary["polyline_refined_rows"], 0)

    def test_query_polyline_mode_fallback_when_geom_missing(self):
        fallback_dir = self.tmpdir / "dist_no_geom"
        if fallback_dir.exists():
            shutil.rmtree(fallback_dir)
        fallback_dir.mkdir(parents=True)
        shutil.copy2(self.ways_idx, fallback_dir / "ways.idx")
        shutil.copy2(self.ways_meta, fallback_dir / "ways.meta")
        shutil.copy2(self.areas_idx, fallback_dir / "areas.idx")
        shutil.copy2(self.ways_lookup, fallback_dir / "ways.lookup")

        result = run_cmd(
            [
                sys.executable,
                str(QUERY),
                "--dist-dir",
                str(fallback_dir),
                "--lat",
                "49.03",
                "--lon",
                "8.031",
                "--distance-mode",
                "polyline",
            ],
        )
        payload = json.loads(result.stdout)
        self.assertEqual(payload["summary"]["distance_mode_requested"], "polyline")
        self.assertEqual(payload["summary"]["distance_mode_effective"], "bbox")
        self.assertEqual(payload["summary"]["polyline_refine_mode"], "missing_geom_artifacts")

    def test_inside_city_default_speed_without_explicit_limit(self):
        _, payload = self.run_query(49.0020, 8.0030, radius_cells=0)
        summary = payload["summary"]
        self.assertTrue(summary["inside_built_up_guess"])
        self.assertEqual(summary["effective_speed_source"], "default_rule")
        self.assertEqual(summary["effective_speed_kmh"], 50)

    def test_outside_city_default_speed_without_explicit_limit(self):
        _, payload = self.run_query(49.2005, 8.2010, radius_cells=0)
        summary = payload["summary"]
        self.assertFalse(summary["inside_built_up_guess"])
        self.assertEqual(summary["effective_speed_source"], "default_rule")
        self.assertEqual(summary["effective_speed_kmh"], 100)

    def test_residential_explicit_maxspeed_applies(self):
        _, payload = self.run_query(49.0300, 8.0310, radius_cells=0)
        summary = payload["summary"]
        self.assertEqual(summary["effective_speed_source"], "map_explicit")
        self.assertEqual(summary["effective_speed_kmh"], 30)

    def test_motorway_explicit_maxspeed_applies(self):
        _, payload = self.run_query(49.0500, 8.0600, radius_cells=0)
        summary = payload["summary"]
        self.assertEqual(summary["effective_speed_source"], "map_explicit")
        self.assertEqual(summary["effective_speed_kmh"], 120)

    def test_zone_maxspeed_applies(self):
        _, payload = self.run_query(49.06025, 8.0605, radius_cells=0)
        summary = payload["summary"]
        self.assertEqual(summary["effective_speed_source"], "map_explicit")
        self.assertEqual(summary["effective_speed_kmh"], 20)

    def test_maxspeed_with_units_applies(self):
        _, payload = self.run_query(49.1105, 8.1105, radius_cells=0)
        summary = payload["summary"]
        self.assertEqual(summary["effective_speed_source"], "map_explicit")
        self.assertEqual(summary["effective_speed_kmh"], 80)

    def test_maxspeed_type_urban_applies(self):
        _, payload = self.run_query(49.1205, 8.1205, radius_cells=0)
        summary = payload["summary"]
        self.assertEqual(summary["effective_speed_source"], "map_explicit")
        self.assertEqual(summary["effective_speed_kmh"], 50)

    def test_source_maxspeed_type_applies(self):
        _, payload = self.run_query(49.0705, 8.0705, radius_cells=0)
        summary = payload["summary"]
        self.assertEqual(summary["effective_speed_source"], "map_explicit")
        self.assertEqual(summary["effective_speed_kmh"], 100)

    def test_conditional_only_speed_falls_back_to_default(self):
        _, payload = self.run_query(49.0905, 8.0905, radius_cells=0)
        summary = payload["summary"]
        self.assertEqual(summary["effective_speed_source"], "default_rule")
        self.assertEqual(summary["effective_speed_kmh"], 100)

    def test_query_negative_invalid_coordinate(self):
        result = run_cmd(
            [
                sys.executable,
                str(QUERY),
                "--dist-dir",
                str(self.dist_dir),
                "--lat",
                "91",
                "--lon",
                "8.0",
            ],
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Invalid coordinate range", result.stderr)

    def test_query_negative_invalid_heading(self):
        result = run_cmd(
            [
                sys.executable,
                str(QUERY),
                "--dist-dir",
                str(self.dist_dir),
                "--lat",
                "49.0",
                "--lon",
                "8.0",
                "--heading",
                "361",
            ],
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Heading must be in range [0, 360]", result.stderr)

    def test_query_negative_missing_artifact(self):
        broken = self.tmpdir / "dist_missing"
        if broken.exists():
            shutil.rmtree(broken)
        broken.mkdir(parents=True)
        shutil.copy2(self.ways_idx, broken / "ways.idx")
        shutil.copy2(self.ways_meta, broken / "ways.meta")

        result = run_cmd(
            [
                sys.executable,
                str(QUERY),
                "--dist-dir",
                str(broken),
                "--lat",
                "49.0",
                "--lon",
                "8.0",
            ],
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing artifact", result.stderr)

    def test_check_artifacts_negative_hash_mismatch(self):
        bad_hash_dir = self.tmpdir / "dist_hash_mismatch"
        if bad_hash_dir.exists():
            shutil.rmtree(bad_hash_dir)
        shutil.copytree(self.dist_dir, bad_hash_dir)

        ways_idx = bad_hash_dir / "ways.idx"
        payload = json.loads(ways_idx.read_text(encoding="utf-8"))
        payload["ways_count"] = int(payload["ways_count"]) + 1
        ways_idx.write_text(json.dumps(payload, sort_keys=True, separators=(",", ":")), encoding="utf-8")

        result = run_cmd([str(CHECK_ARTIFACTS), str(bad_hash_dir)], check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("hash mismatch", result.stderr)


if __name__ == "__main__":
    unittest.main()
