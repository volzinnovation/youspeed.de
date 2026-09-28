"""Check downloadable bundle bytes and publication gates without network access."""

import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from urllib.parse import quote


SCRIPT_DIR = Path(__file__).resolve().parents[2] / "scripts/map"
with patch.object(sys, "path", [str(SCRIPT_DIR), *sys.path]):
    spec = importlib.util.spec_from_file_location("rebuild_release_bundle", SCRIPT_DIR / "rebuild_release_bundle.py")
    rebuild = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(rebuild)


class VerifyPackageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.manifest = {
            "db": self.artifact("versioned_speeds.sqlite.gz", b"downloaded gzip bytes", logical="logical_speeds.sqlite"),
            "coverage": {"poly": self.artifact("versioned.poly", b"coverage")},
            "delta_index": self.artifact("versioned_delta_index.json", b'{"entries":[]}'),
            "penalty_rules": self.artifact("versioned_CHE-rules.json", b'{"country_code":"CHE"}'),
        }
        self.manifest["db"].update(compression="gzip", uncompressed_bytes=123456, uncompressed_sha256="0" * 64)

    def artifact(self, name, content, logical=None):
        (self.directory / name).write_bytes(content)
        return {
            "file": logical or name,
            "url": "https://github.com/owner/repo/releases/download/rolling/" + quote(name),
            "bytes": len(content), "sha256": hashlib.sha256(content).hexdigest(),
        }

    def test_compressed_database_uses_download_url_name_and_compressed_digest(self):
        self.assertFalse((self.directory / "logical_speeds.sqlite").exists())
        rebuild.verify_package(self.directory, self.manifest)

    def test_split_parts_are_checked_without_materialized_or_unsplit_database(self):
        self.manifest["db_parts"] = [
            self.artifact("versioned_speeds.sqlite.gz.part000", b"downloaded "),
            self.artifact("versioned_speeds.sqlite.gz.part001", b"gzip bytes"),
        ]
        self.manifest["db"]["url"] = None
        (self.directory / "versioned_speeds.sqlite.gz").unlink()
        rebuild.verify_package(self.directory, self.manifest)
        (self.directory / "versioned_speeds.sqlite.gz.part001").unlink()
        with self.assertRaisesRegex(ValueError, "Missing or wrong-sized release asset.*part001"):
            rebuild.verify_package(self.directory, self.manifest)

    def test_missing_rule_prevents_publication_verification(self):
        (self.directory / "versioned_CHE-rules.json").unlink()
        with self.assertRaisesRegex(ValueError, "Missing or wrong-sized release asset.*CHE-rules"):
            rebuild.verify_package(self.directory, self.manifest)

    def test_wrong_size_fails_for_every_required_artifact(self):
        for label, artifact in [
            ("database", self.manifest["db"]),
            ("coverage", self.manifest["coverage"]["poly"]),
            ("delta_index", self.manifest["delta_index"]),
            ("rules", self.manifest["penalty_rules"]),
        ]:
            with self.subTest(artifact=label):
                original = artifact["bytes"]
                artifact["bytes"] += 1
                with self.assertRaisesRegex(ValueError, "Missing or wrong-sized release asset"):
                    rebuild.verify_package(self.directory, self.manifest)
                artifact["bytes"] = original

    def test_matching_size_with_wrong_hash_fails(self):
        (self.directory / "versioned_speeds.sqlite.gz").write_bytes(b"changed___ gzip bytes")
        self.assertEqual((self.directory / "versioned_speeds.sqlite.gz").stat().st_size, self.manifest["db"]["bytes"])
        with self.assertRaisesRegex(ValueError, "Release asset hash mismatch.*speeds"):
            rebuild.verify_package(self.directory, self.manifest)

    def test_split_part_matching_size_with_wrong_hash_fails(self):
        self.manifest["db_parts"] = [self.artifact("part000", b"good")]
        (self.directory / "part000").write_bytes(b"evil")
        with self.assertRaisesRegex(ValueError, "Release asset hash mismatch.*part000"):
            rebuild.verify_package(self.directory, self.manifest)

    def test_optional_rules_can_be_absent_from_manifest(self):
        self.manifest.pop("penalty_rules")
        rebuild.verify_package(self.directory, self.manifest)

    def test_url_encoded_asset_basename_is_supported(self):
        self.manifest["penalty_rules"] = self.artifact("rules with spaces.json", b"{}")
        rebuild.verify_package(self.directory, self.manifest)

    def test_url_encoded_path_traversal_is_rejected(self):
        self.manifest["penalty_rules"]["url"] = "https://example.org/%2e%2e%2Fsecret.json"
        with self.assertRaisesRegex(ValueError, "Invalid asset name"):
            rebuild.verify_package(self.directory, self.manifest)


class ReleaseGateTests(unittest.TestCase):
    def test_failed_structural_validation_never_invokes_release_publisher(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            fake_script = root / "scripts/map/rebuild_release_bundle.py"
            commit = "a" * 40
            version = "2026-09-28-test"
            plan = {
                "region_slug": "switzerland", "iso2": "CH", "country_code": "CHE",
                "input_pbf_path": "mapdata/raw/switzerland.osm.pbf", "pbf_url": "https://example.org/source.pbf",
                "input_poly_path": "mapdata/raw/switzerland.poly", "poly_url": "https://example.org/source.poly",
                "bundle_manifest_asset": "switzerland_manifest.json", "bundle_release_tag_default": "switzerland-latest",
                "bundle_release_title_default": "Switzerland", "penalty_rules_source_path": "",
            }
            commands = []

            def fake_run(*args):
                args = list(map(str, args))
                commands.append(args)
                if args[0] == "curl":
                    Path(args[args.index("--output") + 1]).write_bytes(b"fake source bytes")
                elif "scripts/map/publish_v3_bundle.py" in args:
                    package = root / "mapdata/bundles/v3/switzerland" / version
                    (package / "switzerland_manifest.json").write_text(json.dumps({"format": "youspeed.v3.bundle.manifest"}))

            class Reader:
                def __init__(self, _path):
                    pass

                def __enter__(self):
                    return self

                def __exit__(self, *args):
                    return False

                def header(self):
                    return {"osmosis_replication_timestamp": "2026-09-28T00:00:00Z"}

            original_directory = Path.cwd()
            try:
                with patch.object(rebuild, "__file__", str(fake_script)), \
                     patch.object(rebuild.subprocess, "check_output", return_value=commit), \
                     patch.object(rebuild, "resolve_country_release_plan", return_value=plan), \
                     patch.object(rebuild, "run", side_effect=fake_run), \
                     patch.object(rebuild, "validate_bundle", return_value={"ready": False, "errors": ["missing way links"]}), \
                     patch.dict(sys.modules, {"osmium": SimpleNamespace(io=SimpleNamespace(Reader=Reader))}):
                    with self.assertRaisesRegex(ValueError, "Bundle failed structural validation"):
                        rebuild.main(["--target", "switzerland", "--bundle-version", version,
                                      "--source-commit", commit, "--repo", "owner/repo"])
            finally:
                os.chdir(original_directory)
            self.assertTrue(any("scripts/map/publish_v3_bundle.py" in command for command in commands))
            self.assertFalse(any("scripts/map/publish_v3_release_assets.sh" in command for command in commands))
            report = root / "mapdata/reports/full-refresh/switzerland/validation.json"
            self.assertFalse(json.loads(report.read_text())["ready"])


if __name__ == "__main__":
    unittest.main()
