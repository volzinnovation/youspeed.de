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
    REPO_ROOT / "scripts" / "map" / "generate_v3_country_bundles.py",
    "generate_v3_country_bundles",
)


class GenerateV3CountryBundlesPlanTests(unittest.TestCase):
    def test_plan_targets_splits_large_country_into_children(self) -> None:
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
                },
                {
                    "properties": {
                        "id": "drenthe",
                        "name": "Drenthe",
                        "parent": "netherlands",
                        "urls": {
                            "pbf": "https://download.geofabrik.de/europe/netherlands/drenthe-latest.osm.pbf",
                        },
                    }
                },
                {
                    "properties": {
                        "id": "utrecht",
                        "name": "Utrecht",
                        "parent": "netherlands",
                        "urls": {
                            "pbf": "https://download.geofabrik.de/europe/netherlands/utrecht-latest.osm.pbf",
                            "poly": "https://download.geofabrik.de/europe/netherlands/utrecht.poly",
                        },
                    }
                },
                {
                    "properties": {
                        "id": "bermuda",
                        "name": "Bermuda",
                        "parent": "netherlands",
                        "urls": {
                            "pbf": "https://download.geofabrik.de/north-america/bermuda-latest.osm.pbf",
                        },
                    }
                },
                {
                    "properties": {
                        "id": "romania",
                        "name": "Romania",
                        "parent": "europe",
                        "urls": {
                            "pbf": "https://download.geofabrik.de/europe/romania-latest.osm.pbf",
                            "poly": "https://download.geofabrik.de/europe/romania.poly",
                        },
                        "iso3166-1:alpha2": ["RO"],
                    }
                },
            ]
        }
        by_id, children = MODULE._build_index_maps(index_payload)
        ranking = [
            MODULE.RankingCountry(
                rank=1,
                country="Netherlands",
                iso2="NL",
                geofabrik_id="netherlands",
                pbf_url="https://download.geofabrik.de/europe/netherlands-latest.osm.pbf",
                pbf_size_bytes=1_300_000_000,
            ),
            MODULE.RankingCountry(
                rank=2,
                country="Romania",
                iso2="RO",
                geofabrik_id="romania",
                pbf_url="https://download.geofabrik.de/europe/romania-latest.osm.pbf",
                pbf_size_bytes=300_000_000,
            ),
        ]

        targets = MODULE.plan_targets_from_top_countries(
            ranking_rows=ranking,
            index_by_id=by_id,
            child_regions_by_parent=children,
            top_n=2,
            max_country_pbf_bytes=1_000_000_000,
        )

        self.assertEqual(len(targets), 3)
        self.assertEqual(targets[0].region_id, "netherlands/drenthe")
        self.assertEqual(targets[0].iso3, "NLD")
        self.assertEqual(
            targets[0].poly_url,
            "https://download.geofabrik.de/europe/netherlands/drenthe.poly",
        )
        self.assertTrue(targets[0].is_shard)
        self.assertEqual(targets[1].region_id, "netherlands/utrecht")
        self.assertTrue(targets[1].is_shard)
        self.assertEqual(targets[2].region_id, "romania")
        self.assertFalse(targets[2].is_shard)

    def test_plan_targets_for_country_prefers_shards_when_large(self) -> None:
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
                        },
                    }
                },
                {
                    "properties": {
                        "id": "bermuda",
                        "name": "Bermuda",
                        "parent": "germany",
                        "urls": {
                            "pbf": "https://download.geofabrik.de/north-america/bermuda-latest.osm.pbf",
                        },
                    }
                },
            ]
        }
        by_id, children = MODULE._build_index_maps(index_payload)
        targets = MODULE.plan_targets_for_country(
            country_id="germany",
            index_by_id=by_id,
            child_regions_by_parent=children,
            max_country_pbf_bytes=1_000_000_000,
            country_pbf_size_bytes=4_000_000_000,
        )

        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].region_id, "germany/baden-wuerttemberg")
        self.assertEqual(targets[0].iso3, "DEU")
        self.assertTrue(targets[0].is_shard)

    def test_plan_targets_for_country_keeps_single_bundle_when_small(self) -> None:
        index_payload = {
            "features": [
                {
                    "properties": {
                        "id": "romania",
                        "name": "Romania",
                        "parent": "europe",
                        "urls": {
                            "pbf": "https://download.geofabrik.de/europe/romania-latest.osm.pbf",
                            "poly": "https://download.geofabrik.de/europe/romania.poly",
                        },
                        "iso3166-1:alpha2": ["RO"],
                    }
                },
                {
                    "properties": {
                        "id": "bucharest",
                        "name": "Bucharest",
                        "parent": "romania",
                        "urls": {
                            "pbf": "https://download.geofabrik.de/europe/romania/bucharest-latest.osm.pbf",
                        },
                    }
                },
            ]
        }
        by_id, children = MODULE._build_index_maps(index_payload)
        targets = MODULE.plan_targets_for_country(
            country_id="romania",
            index_by_id=by_id,
            child_regions_by_parent=children,
            max_country_pbf_bytes=1_000_000_000,
            country_pbf_size_bytes=300_000_000,
        )

        self.assertEqual(len(targets), 1)
        self.assertEqual(targets[0].region_id, "romania")
        self.assertEqual(targets[0].iso3, "ROU")
        self.assertFalse(targets[0].is_shard)

    def test_plan_single_region_target_uses_iso_override(self) -> None:
        index_payload = {
            "features": [
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
                }
            ]
        }
        by_id, _ = MODULE._build_index_maps(index_payload)

        target = MODULE.plan_single_region_target(
            region_id="germany/bayern",
            index_by_id=by_id,
            iso2_override="de",
        )

        self.assertEqual(target.region_id, "germany/bayern")
        self.assertEqual(target.iso2, "DE")
        self.assertEqual(target.iso3, "DEU")
        self.assertEqual(target.country_id, "germany")

    def test_plan_single_region_target_country_id_for_country_level_region(self) -> None:
        index_payload = {
            "features": [
                {
                    "properties": {
                        "id": "romania",
                        "name": "Romania",
                        "parent": "europe",
                        "urls": {
                            "pbf": "https://download.geofabrik.de/europe/romania-latest.osm.pbf",
                        },
                    }
                }
            ]
        }
        by_id, _ = MODULE._build_index_maps(index_payload)
        target = MODULE.plan_single_region_target(
            region_id="romania",
            index_by_id=by_id,
            iso2_override="ro",
        )
        self.assertEqual(target.country_id, "romania")

    def test_load_bundle_target_config_and_plan_country_targets(self) -> None:
        index_payload = {
            "features": [
                {
                    "properties": {
                        "id": "germany",
                        "name": "Germany",
                        "parent": "europe",
                        "urls": {
                            "pbf": "https://download.geofabrik.de/europe/germany-latest.osm.pbf",
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
                        },
                    }
                },
                {
                    "properties": {
                        "id": "germany/berlin",
                        "name": "Berlin",
                        "parent": "germany",
                        "urls": {
                            "pbf": "https://download.geofabrik.de/europe/germany/berlin-latest.osm.pbf",
                        },
                    }
                },
            ]
        }
        by_id, _ = MODULE._build_index_maps(index_payload)
        payload = {
            "format": "youspeed.v3.bundle.targets",
            "schema_version": 1,
            "variant": "v3",
            "max_country_pbf_bytes": 1000000000,
            "countries": [
                {
                    "rank": 8,
                    "country_id": "germany",
                    "country_code": "DEU",
                    "iso2": "DE",
                    "mode": "regional_shards",
                    "include_in_top_country_sequence": False,
                    "regions": [
                        {"region_id": "germany/bayern"},
                        {"region_id": "germany/berlin"},
                    ],
                }
            ],
        }
        with tempfile.TemporaryDirectory(prefix="youspeed-target-config-") as td:
            path = Path(td) / "BundleTargets.top10.json"
            path.write_text(json.dumps(payload), encoding="utf-8")
            cfg = MODULE._load_bundle_target_config(path)

        self.assertEqual(len(cfg), 1)
        self.assertFalse(cfg[0].include_in_top_country_sequence)
        self.assertEqual(MODULE._top_country_sequence_config(cfg), [])
        targets = MODULE.plan_targets_for_country_from_config(
            config_country=cfg[0],
            index_by_id=by_id,
        )
        self.assertEqual([t.region_id for t in targets], ["germany/bayern", "germany/berlin"])
        self.assertTrue(all(t.is_shard for t in targets))

        forced_targets = MODULE.plan_targets_for_country_from_config(
            config_country=cfg[0],
            index_by_id=by_id,
            force_single_country=True,
        )
        self.assertEqual([t.region_id for t in forced_targets], ["germany"])
        self.assertFalse(forced_targets[0].is_shard)

    def test_top_country_sequence_config_keeps_opted_in_countries_only(self) -> None:
        config_countries = [
            MODULE.BundleTargetConfigCountry(
                rank=1,
                country_id="netherlands",
                country_code="NLD",
                iso2="NL",
                mode="single_country",
                regions=[MODULE.BundleTargetConfigRegion(region_id="netherlands")],
            ),
            MODULE.BundleTargetConfigCountry(
                rank=8,
                country_id="germany",
                country_code="DEU",
                iso2="DE",
                mode="regional_shards",
                regions=[MODULE.BundleTargetConfigRegion(region_id="germany/bayern")],
                include_in_top_country_sequence=False,
            ),
            MODULE.BundleTargetConfigCountry(
                rank=10,
                country_id="united-kingdom",
                country_code="GBR",
                iso2="GB",
                mode="single_country",
                regions=[MODULE.BundleTargetConfigRegion(region_id="united-kingdom")],
            ),
        ]

        filtered = MODULE._top_country_sequence_config(config_countries)

        self.assertEqual([row.country_id for row in filtered], ["netherlands", "united-kingdom"])

    def test_derive_poly_url_from_pbf_url(self) -> None:
        self.assertEqual(
            MODULE._derive_poly_url_from_pbf_url(
                "https://download.geofabrik.de/europe/netherlands-latest.osm.pbf"
            ),
            "https://download.geofabrik.de/europe/netherlands.poly",
        )

    def test_catalog_command_uses_country_latest_path(self) -> None:
        cmd = MODULE._catalog_command(
            repo_root=Path("/tmp/repo"),
            country_id="germany",
            bundle_version="2026-03-02",
            region_ids=["germany/bayern", "germany/berlin"],
        )
        self.assertIn("--manifest", cmd)
        self.assertIn(
            "/tmp/repo/mapdata/bundles/v3/germany-bayern/latest/germany-bayern_manifest.json",
            cmd,
        )
        self.assertIn(
            "/tmp/repo/mapdata/bundles/v3/germany-berlin/latest/germany-berlin_manifest.json",
            cmd,
        )
        self.assertEqual(
            cmd[-1],
            "/tmp/repo/mapdata/bundles/v3/germany/latest/germany_catalog.json",
        )

    def test_id_based_asset_name_helpers(self) -> None:
        self.assertEqual(MODULE._db_asset_name("germany"), "germany_speeds.sqlite")
        self.assertEqual(MODULE._manifest_asset_name("germany"), "germany_manifest.json")
        self.assertEqual(MODULE._db_asset_name("germany/bayern"), "germany-bayern_speeds.sqlite")
        self.assertEqual(MODULE._manifest_asset_name("germany/bayern"), "germany-bayern_manifest.json")


if __name__ == "__main__":
    unittest.main()
