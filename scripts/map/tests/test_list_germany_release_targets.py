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
    REPO_ROOT / "scripts" / "map" / "list_germany_release_targets.py",
    "list_germany_release_targets",
)


class ListGermanyReleaseTargetsTests(unittest.TestCase):
    def _write_config(self, root: Path) -> Path:
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
                    "regions": [
                        {"region_id": "baden-wuerttemberg"},
                        {"region_id": "bayern"},
                    ],
                }
            ],
        }
        config_path = root / "BundleTargets.top10.json"
        config_path.write_text(json.dumps(config_payload), encoding="utf-8")
        return config_path

    def test_all_selector_includes_regions_and_default_extra_shards(self) -> None:
        with tempfile.TemporaryDirectory(prefix="youspeed-germany-targets-") as td:
            root = Path(td)
            config_path = self._write_config(root)
            targets = MODULE.resolve_targets(
                selector="all",
                config_path=config_path,
                extra_shards=MODULE.DEFAULT_EXTRA_SHARDS,
            )

        self.assertEqual(targets, ["baden-wuerttemberg", "bayern", "karlsruhe-regbez"])

    def test_explicit_selector_accepts_root_and_prefixed_region_ids(self) -> None:
        with tempfile.TemporaryDirectory(prefix="youspeed-germany-targets-") as td:
            root = Path(td)
            config_path = self._write_config(root)
            targets = MODULE.resolve_targets(
                selector="germany,germany/bayern",
                config_path=config_path,
                extra_shards=[],
            )

        self.assertEqual(targets, ["germany", "bayern"])


if __name__ == "__main__":
    unittest.main()
