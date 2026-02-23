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
BUILD_V2 = REPO_ROOT / "scripts/map/build_tile_assets_v2.py"
QUERY_V2 = REPO_ROOT / "scripts/map/query_speed_limit_v2.py"
CHECK_V2 = REPO_ROOT / "scripts/map/check_tile_assets_v2.py"


def run_cmd(args, *, check=True):
    return subprocess.run(args, check=check, text=True, capture_output=True)


class TileAssetsV2PipelineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmpdir_ctx = tempfile.TemporaryDirectory()
        cls.tmpdir = Path(cls.tmpdir_ctx.name)
        cls.input_osm = cls.tmpdir / "fixture.osm"
        cls.dist_v1 = cls.tmpdir / "dist_v1"
        cls.dist_v2 = cls.tmpdir / "dist_v2"
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
                str(BUILD_V2),
                "--v1-dist",
                str(cls.dist_v1),
                "--out-dir",
                str(cls.dist_v2),
                "--region",
                "test-fixture-v2",
                "--tile-size-m",
                "1024",
                "--subgrid",
                "16",
                "--content-version",
                "1",
            ]
        )
        cls.catalog_path = cls.dist_v2 / "catalog.v2.json"
        cls.catalog = json.loads(cls.catalog_path.read_text(encoding="utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls.tmpdir_ctx.cleanup()

    @staticmethod
    def _fixture_osm() -> str:
        return textwrap.dedent(
            """\
            <?xml version='1.0' encoding='UTF-8'?>
            <osm version='0.6' generator='youspeed-tests-v2'>
              <node id='1' lat='49.0020' lon='8.0020'/>
              <node id='2' lat='49.0020' lon='8.0040'/>
              <node id='3' lat='49.0300' lon='8.0300'/>
              <node id='4' lat='49.0300' lon='8.0320'/>
              <node id='401' lat='49.0000' lon='8.0000'/>
              <node id='402' lat='49.0000' lon='8.0100'/>
              <node id='403' lat='49.0100' lon='8.0100'/>
              <node id='404' lat='49.0100' lon='8.0000'/>

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
            </osm>
            """
        )

    def run_query(self, lat, lon, heading=90):
        result = run_cmd(
            [
                sys.executable,
                str(QUERY_V2),
                "--dist-dir",
                str(self.dist_v2),
                "--lat",
                str(lat),
                "--lon",
                str(lon),
                "--heading",
                str(heading),
            ]
        )
        return result, json.loads(result.stdout)

    def test_build_outputs_catalog_and_tile_files(self):
        self.assertTrue(self.catalog_path.exists())
        tiles = self.catalog["tiles"]
        self.assertGreater(len(tiles), 0)
        for tile in tiles[:5]:
            tile_id = tile["tile_id"]
            self.assertIn("/", tile_id)
            self.assertNotIn("g3857_x", tile_id)
            tile_dir = self.dist_v2 / "tiles" / tile_id
            self.assertTrue((tile_dir / "tile_manifest.v2.json").exists())
            self.assertTrue((tile_dir / f"{tile['content_sha256']}.tilepack").exists())

    def test_generated_assets_validate_against_v2_checker(self):
        tiles = self.catalog["tiles"][:3]
        args = [
            sys.executable,
            str(CHECK_V2),
            "--catalog",
            str(self.catalog_path),
        ]
        for tile in tiles:
            args.extend(
                [
                    "--tile-manifest",
                    str(self.dist_v2 / "tiles" / tile["tile_id"] / "tile_manifest.v2.json"),
                ]
            )
        run_cmd(args)

    def test_query_v2_explicit_limit(self):
        _, payload = self.run_query(49.0300, 8.0310, heading=90)
        summary = payload["summary"]
        self.assertEqual(summary["effective_speed_source"], "map_explicit")
        self.assertEqual(summary["effective_speed_kmh"], 30)
        self.assertGreaterEqual(summary["loaded_tiles"], 1)

    def test_query_v2_inside_city_default(self):
        _, payload = self.run_query(49.0020, 8.0030, heading=90)
        summary = payload["summary"]
        self.assertTrue(summary["inside_built_up_guess"])
        self.assertEqual(summary["effective_speed_source"], "default_rule")
        self.assertEqual(summary["effective_speed_kmh"], 50)

    def test_query_v2_negative_missing_catalog(self):
        missing = self.tmpdir / "dist_missing_v2"
        if missing.exists():
            shutil.rmtree(missing)
        missing.mkdir(parents=True)
        result = run_cmd(
            [
                sys.executable,
                str(QUERY_V2),
                "--dist-dir",
                str(missing),
                "--lat",
                "49.0",
                "--lon",
                "8.0",
            ],
            check=False,
        )
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("Missing artifact", result.stderr)


if __name__ == "__main__":
    unittest.main()
