import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


def _load_module(module_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module at {module_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


REPO_ROOT = Path(__file__).resolve().parents[3]
PLAN_MODULE = _load_module(REPO_ROOT / "scripts" / "map" / "plan_country_region_bundles.py", "plan_country_region_bundles")
PUBLISH_MODULE = _load_module(REPO_ROOT / "scripts" / "map" / "publish_v3_bundle.py", "publish_v3_bundle")
build_plan = PLAN_MODULE.build_plan
_parse_poly_bbox = PUBLISH_MODULE._parse_poly_bbox


class CountryRegionBundlePlanTests(unittest.TestCase):
    def test_build_plan_uses_single_country_below_threshold(self) -> None:
        index_payload = {
            "features": [
                {
                    "properties": {
                        "id": "germany",
                        "name": "Germany",
                        "parent": "europe",
                        "urls": {
                            "pbf": "https://download.geofabrik.de/europe/germany-latest.osm.pbf",
                            "poly": "https://download.geofabrik.de/europe/germany.poly",
                        },
                        "iso3166-1:alpha2": ["DE"],
                    }
                },
                {
                    "properties": {
                        "id": "germany/baden-wuerttemberg",
                        "name": "Baden-Wuerttemberg",
                        "parent": "germany",
                        "urls": {
                            "pbf": "https://download.geofabrik.de/europe/germany/baden-wuerttemberg-latest.osm.pbf",
                            "poly": "https://download.geofabrik.de/europe/germany/baden-wuerttemberg.poly",
                        },
                    }
                },
            ]
        }
        plan = build_plan(
            index_payload=index_payload,
            country_id="germany",
            country_pbf_bytes=950_000_000,
            max_country_pbf_bytes=1_000_000_000,
        )
        self.assertEqual(plan["mode"], "single_country_bundle")
        self.assertEqual(len(plan["regions"]), 1)
        self.assertEqual(plan["regions"][0]["id"], "germany")

    def test_build_plan_uses_subregions_above_threshold(self) -> None:
        index_payload = {
            "features": [
                {
                    "properties": {
                        "id": "germany",
                        "name": "Germany",
                        "parent": "europe",
                        "urls": {
                            "pbf": "https://download.geofabrik.de/europe/germany-latest.osm.pbf",
                            "poly": "https://download.geofabrik.de/europe/germany.poly",
                        },
                        "iso3166-1:alpha2": ["DE"],
                    }
                },
                {
                    "properties": {
                        "id": "germany/baden-wuerttemberg",
                        "name": "Baden-Wuerttemberg",
                        "parent": "germany",
                        "urls": {
                            "pbf": "https://download.geofabrik.de/europe/germany/baden-wuerttemberg-latest.osm.pbf",
                            "poly": "https://download.geofabrik.de/europe/germany/baden-wuerttemberg.poly",
                        },
                    }
                },
                {
                    "properties": {
                        "id": "germany/bayern",
                        "name": "Bayern",
                        "parent": "germany",
                        "urls": {
                            "pbf": "https://download.geofabrik.de/europe/germany/bayern-latest.osm.pbf",
                            "poly": "https://download.geofabrik.de/europe/germany/bayern.poly",
                        },
                    }
                },
            ]
        }
        plan = build_plan(
            index_payload=index_payload,
            country_id="germany",
            country_pbf_bytes=1_600_000_000,
            max_country_pbf_bytes=1_000_000_000,
        )
        self.assertEqual(plan["mode"], "regional_shards")
        self.assertEqual(len(plan["regions"]), 2)
        self.assertEqual(plan["regions"][0]["id"], "germany/baden-wuerttemberg")
        self.assertEqual(plan["regions"][1]["id"], "germany/bayern")


class PublishCoverageBBoxTests(unittest.TestCase):
    def test_parse_poly_bbox(self) -> None:
        with tempfile.TemporaryDirectory(prefix="youspeed-poly-test-") as td:
            poly_path = Path(td) / "region.poly"
            poly_path.write_text(
                "\n".join(
                    [
                        "region",
                        "1",
                        "  8.0 48.0",
                        "  10.0 48.0",
                        "  10.0 50.0",
                        "  8.0 50.0",
                        "  8.0 48.0",
                        "END",
                        "END",
                    ]
                )
                + "\n",
                encoding="utf-8",
            )
            bbox = _parse_poly_bbox(poly_path)
            self.assertEqual(bbox, (8.0, 48.0, 10.0, 50.0))

    def test_publish_bundle_emits_gzip_db_artifact(self) -> None:
        with tempfile.TemporaryDirectory(prefix="youspeed-publish-test-") as td:
            temp_root = Path(td)
            db_path = temp_root / "fixture.sqlite"
            out_root = temp_root / "out"
            db_path.write_bytes((b"fixture-db-row\n" * 4096))

            argv = [
                "publish_v3_bundle.py",
                "--region",
                "bayern",
                "--db",
                str(db_path),
                "--bundle-version",
                "2026-03-17",
                "--out-root",
                str(out_root),
                "--db-file-name",
                "bayern.sqlite",
                "--db-compression",
                "gzip",
                "--manifest-name",
                "bundle.json",
            ]
            with mock.patch.object(sys, "argv", argv):
                rc = PUBLISH_MODULE.main()
            self.assertEqual(rc, 0)

            bundle_dir = out_root / "bayern" / "2026-03-17"
            manifest = json.loads((bundle_dir / "bundle.json").read_text(encoding="utf-8"))
            self.assertFalse((bundle_dir / "bayern.sqlite").exists())
            self.assertTrue((bundle_dir / "bayern.sqlite.gz").exists())
            self.assertEqual(manifest["db"]["file"], "bayern.sqlite")
            self.assertEqual(manifest["db"]["compression"], "gzip")
            self.assertEqual(manifest["db"]["url"], "bayern.sqlite.gz")
            self.assertEqual(manifest["db"]["uncompressed_bytes"], db_path.stat().st_size)


if __name__ == "__main__":
    unittest.main()
