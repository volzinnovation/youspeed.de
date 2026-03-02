import importlib.util
import tempfile
import unittest
from pathlib import Path


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


if __name__ == "__main__":
    unittest.main()
