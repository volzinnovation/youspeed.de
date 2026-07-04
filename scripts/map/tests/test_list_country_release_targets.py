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
    REPO_ROOT / "scripts" / "map" / "list_country_release_targets.py",
    "list_country_release_targets",
)


class ListCountryReleaseTargetsTests(unittest.TestCase):
    def _write_config(self, root: Path) -> Path:
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
                    "include_in_top_country_sequence": False,
                    "regions": [
                        {"region_id": "alsace"},
                        {"region_id": "france/ile-de-france"},
                    ],
                }
            ],
        }
        config_path = root / "BundleTargets.top10.json"
        config_path.write_text(json.dumps(config_payload), encoding="utf-8")
        return config_path

    def test_all_selector_includes_configured_regions(self) -> None:
        with tempfile.TemporaryDirectory(prefix="youspeed-country-targets-") as td:
            root = Path(td)
            config_path = self._write_config(root)
            targets = MODULE.resolve_targets(
                country_id="france",
                selector="all",
                config_path=config_path,
                extra_shards=[],
            )

        self.assertEqual(targets, ["alsace", "ile-de-france"])

    def test_explicit_selector_accepts_root_and_prefixed_region_ids(self) -> None:
        with tempfile.TemporaryDirectory(prefix="youspeed-country-targets-") as td:
            root = Path(td)
            config_path = self._write_config(root)
            targets = MODULE.resolve_targets(
                country_id="france",
                selector="france,france/ile-de-france",
                config_path=config_path,
                extra_shards=[],
            )

        self.assertEqual(targets, ["france", "ile-de-france"])


if __name__ == "__main__":
    unittest.main()
