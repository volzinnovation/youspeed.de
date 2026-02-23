import copy
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = REPO_ROOT / "scripts/map/check_tile_assets_v2.py"
CATALOG_EXAMPLE = REPO_ROOT / "mapdata/spec/examples/catalog.v2.example.json"
MANIFEST_EXAMPLE = REPO_ROOT / "mapdata/spec/examples/tile_manifest.v2.example.json"


def run_cmd(args, *, check=True):
    return subprocess.run(args, check=check, text=True, capture_output=True)


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


class TileAssetSpecValidationTests(unittest.TestCase):
    def setUp(self):
        self.tmpdir_ctx = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self.tmpdir_ctx.name)
        self.catalog_path = self.tmpdir / "catalog.v2.json"
        self.manifest_path = self.tmpdir / "tile_manifest.v2.json"

        self.catalog = load_json(CATALOG_EXAMPLE)
        self.manifest = load_json(MANIFEST_EXAMPLE)

        self.catalog_path.write_text(json.dumps(self.catalog, indent=2), encoding="utf-8")
        self.manifest_path.write_text(json.dumps(self.manifest, indent=2), encoding="utf-8")

    def tearDown(self):
        self.tmpdir_ctx.cleanup()

    def validate_ok(self):
        return run_cmd(
            [
                sys.executable,
                str(VALIDATOR),
                "--catalog",
                str(self.catalog_path),
                "--tile-manifest",
                str(self.manifest_path),
            ]
        )

    def validate_fail(self):
        return run_cmd(
            [
                sys.executable,
                str(VALIDATOR),
                "--catalog",
                str(self.catalog_path),
                "--tile-manifest",
                str(self.manifest_path),
            ],
            check=False,
        )

    def test_examples_pass_validation(self):
        result = self.validate_ok()
        self.assertIn("v2 asset validation passed", result.stdout)

    def test_catalog_negative_invalid_tile_id(self):
        catalog = copy.deepcopy(self.catalog)
        catalog["tiles"][0]["tile_id"] = "tile-1"
        self.catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
        result = self.validate_fail()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("tile_id must match", result.stderr)

    def test_catalog_negative_duplicate_tile_id(self):
        catalog = copy.deepcopy(self.catalog)
        catalog["tiles"][1]["tile_id"] = catalog["tiles"][0]["tile_id"]
        self.catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
        result = self.validate_fail()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("duplicates", result.stderr)

    def test_catalog_negative_invalid_app_compat_range(self):
        catalog = copy.deepcopy(self.catalog)
        catalog["app_compat"]["min_data_runtime_version"] = 5
        catalog["app_compat"]["max_data_runtime_version"] = 4
        self.catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
        result = self.validate_fail()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("min_data_runtime_version must be <=", result.stderr)

    def test_catalog_negative_missing_stable_channel(self):
        catalog = copy.deepcopy(self.catalog)
        catalog["channels"] = ["canary"]
        self.catalog_path.write_text(json.dumps(catalog), encoding="utf-8")
        result = self.validate_fail()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("channels must include 'stable'", result.stderr)

    def test_manifest_negative_invalid_sha(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["tile_pack_sha256"] = "1234"
        self.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        result = self.validate_fail()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("tile_pack_sha256", result.stderr)

    def test_manifest_negative_invalid_bbox(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["bbox_wgs84"]["min_lat"] = 95.0
        self.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        result = self.validate_fail()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("bbox_wgs84 lat must be in [-90, 90]", result.stderr)

    def test_manifest_negative_chunk_overlap(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["chunks"][1]["offset"] = manifest["chunks"][0]["offset"] + 1
        self.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        result = self.validate_fail()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must not overlap previous chunk", result.stderr)

    def test_manifest_negative_chunk_not_increasing(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["chunks"][1]["offset"] = manifest["chunks"][0]["offset"]
        self.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        result = self.validate_fail()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be strictly increasing", result.stderr)

    def test_manifest_negative_chunk_exceeds_tilepack_bytes(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["chunks"][-1]["length"] = manifest["chunks"][-1]["length"] + 16
        self.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        result = self.validate_fail()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("exceeds tile_pack_bytes", result.stderr)

    def test_manifest_negative_missing_required_chunk(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["chunks"] = [chunk for chunk in manifest["chunks"] if chunk["name"] != "speed_rules"]
        self.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        result = self.validate_fail()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("missing required chunk names", result.stderr)

    def test_manifest_negative_invalid_chunk_name(self):
        manifest = copy.deepcopy(self.manifest)
        manifest["chunks"][0]["name"] = "ways_meta"
        self.manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        result = self.validate_fail()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("must be one of", result.stderr)


if __name__ == "__main__":
    unittest.main()
