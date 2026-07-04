import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path


def _load_module(module_path: Path, module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module at {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


REPO_ROOT = Path(__file__).resolve().parents[3]
MODULE = _load_module(
    REPO_ROOT / "scripts" / "map" / "resolve_country_release_plan.py",
    "resolve_country_release_plan",
)


class ResolveCountryReleasePlanTests(unittest.TestCase):
    def test_resolves_country_release_plan_from_config_and_index(self) -> None:
        index_payload = {
            "features": [
                {
                    "properties": {
                        "id": "netherlands",
                        "name": "Netherlands",
                        "parent": "europe",
                        "urls": {
                            "pbf": "https://download.geofabrik.de/europe/netherlands-latest.osm.pbf",
                            "poly": "https://download.geofabrik.de/europe/netherlands.poly",
                        },
                        "iso3166-1:alpha2": ["NL"],
                    }
                }
            ]
        }
        config_payload = {
            "format": "youspeed.v3.bundle.targets",
            "schema_version": 1,
            "variant": "v3",
            "countries": [
                {
                    "rank": 1,
                    "country_id": "netherlands",
                    "country_code": "NLD",
                    "iso2": "NL",
                    "mode": "single_country",
                    "regions": [{"region_id": "netherlands"}],
                }
            ],
        }

        with tempfile.TemporaryDirectory(prefix="youspeed-release-plan-") as td:
            root = Path(td)
            index_path = root / "index-v1.json"
            config_path = root / "BundleTargets.top10.json"
            index_path.write_text(json.dumps(index_payload), encoding="utf-8")
            config_path.write_text(json.dumps(config_payload), encoding="utf-8")

            plan = MODULE.resolve_country_release_plan(
                repo_root=root,
                bundle_country="netherlands",
                geofabrik_index=index_path,
                bundle_target_config=config_path,
                geofabrik_index_url="https://download.geofabrik.de/index-v1.json",
            )

        self.assertEqual(plan["country_code"], "NLD")
        self.assertEqual(plan["iso2"], "NL")
        self.assertEqual(plan["bundle_release_tag_default"], "netherlands")
        self.assertEqual(plan["pbf_release_tag_default"], "nld-pbf-latest")
        self.assertEqual(plan["pbf_asset_name"], "NLD-latest.osm.pbf")
        self.assertEqual(plan["state_asset_name"], "NLD.diff_state.json")
        self.assertEqual(plan["report_asset_name"], "diff_update.NLD.latest.json")
        self.assertEqual(plan["daily_delta_glob"], "NLD-*.osc.gz")
        self.assertEqual(
            plan["updates_url"],
            "https://download.geofabrik.de/europe/netherlands-updates/",
        )
        self.assertEqual(
            plan["bundle_db_asset"],
            "netherlands_speeds.sqlite",
        )
        self.assertEqual(
            plan["bundle_manifest_asset"],
            "netherlands_manifest.json",
        )
        self.assertEqual(
            plan["delta_index_asset"],
            "netherlands_delta_index.json",
        )

    def test_resolves_germany_state_release_plan_with_parent_iso2_override(self) -> None:
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
                        "id": "baden-wuerttemberg",
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
        config_payload = {
            "format": "youspeed.v3.bundle.targets",
            "schema_version": 1,
            "variant": "v3",
            "countries": [
                {
                    "rank": 8,
                    "country_id": "germany",
                    "country_code": "DEU",
                    "iso2": "DE",
                    "mode": "regional_shards",
                    "regions": [{"region_id": "baden-wuerttemberg"}],
                }
            ],
        }

        with tempfile.TemporaryDirectory(prefix="youspeed-release-plan-") as td:
            root = Path(td)
            index_path = root / "index-v1.json"
            config_path = root / "BundleTargets.top10.json"
            index_path.write_text(json.dumps(index_payload), encoding="utf-8")
            config_path.write_text(json.dumps(config_payload), encoding="utf-8")

            plan = MODULE.resolve_country_release_plan(
                repo_root=root,
                bundle_country="baden-wuerttemberg",
                geofabrik_index=index_path,
                bundle_target_config=config_path,
                geofabrik_index_url="https://download.geofabrik.de/index-v1.json",
            )

        self.assertEqual(plan["country_code"], "DEU")
        self.assertEqual(plan["iso2"], "DE")
        self.assertEqual(plan["root_country_id"], "germany")
        self.assertEqual(plan["bundle_release_tag_default"], "baden-wuerttemberg")
        self.assertEqual(plan["pbf_release_tag_default"], "baden-wuerttemberg-pbf-latest")
        self.assertEqual(plan["pbf_asset_name"], "baden-wuerttemberg-latest.osm.pbf")
        self.assertEqual(plan["state_asset_name"], "baden-wuerttemberg.diff_state.json")
        self.assertEqual(plan["report_asset_name"], "diff_update.baden-wuerttemberg.latest.json")
        self.assertEqual(plan["daily_delta_glob"], "baden-wuerttemberg-*.osc.gz")

    def test_resolves_germany_shard_from_prefixed_selector(self) -> None:
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
                        "id": "baden-wuerttemberg",
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
                        "id": "karlsruhe-regbez",
                        "name": "Karlsruhe Regbez",
                        "parent": "baden-wuerttemberg",
                        "urls": {
                            "pbf": "https://download.geofabrik.de/europe/germany/baden-wuerttemberg/karlsruhe-regbez-latest.osm.pbf",
                            "poly": "https://download.geofabrik.de/europe/germany/baden-wuerttemberg/karlsruhe-regbez.poly",
                        },
                    }
                },
            ]
        }
        config_payload = {
            "format": "youspeed.v3.bundle.targets",
            "schema_version": 1,
            "variant": "v3",
            "countries": [
                {
                    "rank": 8,
                    "country_id": "germany",
                    "country_code": "DEU",
                    "iso2": "DE",
                    "mode": "regional_shards",
                    "regions": [{"region_id": "baden-wuerttemberg"}],
                }
            ],
        }

        with tempfile.TemporaryDirectory(prefix="youspeed-release-plan-") as td:
            root = Path(td)
            index_path = root / "index-v1.json"
            config_path = root / "BundleTargets.top10.json"
            index_path.write_text(json.dumps(index_payload), encoding="utf-8")
            config_path.write_text(json.dumps(config_payload), encoding="utf-8")

            plan = MODULE.resolve_country_release_plan(
                repo_root=root,
                bundle_country="germany/karlsruhe-regbez",
                geofabrik_index=index_path,
                bundle_target_config=config_path,
                geofabrik_index_url="https://download.geofabrik.de/index-v1.json",
            )

        self.assertEqual(plan["bundle_country"], "karlsruhe-regbez")
        self.assertEqual(plan["root_country_id"], "germany")
        self.assertEqual(plan["pbf_release_tag_default"], "karlsruhe-regbez-pbf-latest")
        self.assertEqual(plan["pbf_asset_name"], "karlsruhe-regbez-latest.osm.pbf")
        self.assertEqual(plan["daily_delta_prefix"], "karlsruhe-regbez")

    def test_resolves_france_regional_shard_with_parent_country(self) -> None:
        index_payload = {
            "features": [
                {
                    "properties": {
                        "id": "france",
                        "name": "France",
                        "parent": "europe",
                        "urls": {
                            "pbf": "https://download.geofabrik.de/europe/france-latest.osm.pbf",
                        },
                        "iso3166-1:alpha2": ["FR"],
                    }
                },
                {
                    "properties": {
                        "id": "ile-de-france",
                        "name": "Ile-de-France",
                        "parent": "france",
                        "urls": {
                            "pbf": "https://download.geofabrik.de/europe/france/ile-de-france-latest.osm.pbf",
                        },
                    }
                },
            ]
        }
        config_payload = {
            "format": "youspeed.v3.bundle.targets",
            "schema_version": 1,
            "variant": "v3",
            "countries": [
                {
                    "rank": 9,
                    "country_id": "france",
                    "country_code": "FRA",
                    "iso2": "FR",
                    "mode": "regional_shards",
                    "regions": [{"region_id": "ile-de-france"}],
                }
            ],
        }

        with tempfile.TemporaryDirectory(prefix="youspeed-release-plan-") as td:
            root = Path(td)
            index_path = root / "index-v1.json"
            config_path = root / "BundleTargets.top10.json"
            index_path.write_text(json.dumps(index_payload), encoding="utf-8")
            config_path.write_text(json.dumps(config_payload), encoding="utf-8")

            plan = MODULE.resolve_country_release_plan(
                repo_root=root,
                bundle_country="france/ile-de-france",
                geofabrik_index=index_path,
                bundle_target_config=config_path,
                geofabrik_index_url="https://download.geofabrik.de/index-v1.json",
            )

        self.assertEqual(plan["country_code"], "FRA")
        self.assertEqual(plan["iso2"], "FR")
        self.assertEqual(plan["root_country_id"], "france")
        self.assertEqual(plan["bundle_release_tag_default"], "ile-de-france")
        self.assertEqual(plan["pbf_release_tag_default"], "ile-de-france-pbf-latest")
        self.assertEqual(plan["pbf_asset_name"], "ile-de-france-latest.osm.pbf")
        self.assertEqual(plan["state_asset_name"], "ile-de-france.diff_state.json")
        self.assertEqual(plan["daily_delta_prefix"], "ile-de-france")

    def test_rejects_non_latest_geofabrik_url(self) -> None:
        with self.assertRaises(SystemExit):
            MODULE._updates_url_from_pbf_url("https://example.com/netherlands.osm.pbf")


if __name__ == "__main__":
    unittest.main()
