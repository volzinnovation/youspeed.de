from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/map/generate_bundle_coverage_map.py"
SPEC = importlib.util.spec_from_file_location("generate_bundle_coverage_map", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def test_web_mercator_y_is_monotonic_and_symmetric():
    assert abs(MODULE.web_mercator_y(0)) < 1e-12
    assert MODULE.web_mercator_y(50) > MODULE.web_mercator_y(40)
    assert abs(MODULE.web_mercator_y(-50) + MODULE.web_mercator_y(50)) < 1e-12


def test_project_uses_mercator_latitude_scaling():
    _, y_41 = MODULE.project(0, 41)
    _, y_50 = MODULE.project(0, 50)
    _, y_56 = MODULE.project(0, 56)
    assert y_41 > y_50 > y_56
    assert y_41 == MODULE.MAP[3]
    assert y_56 < MODULE.MAP[1] + 20


def test_official_geometry_covers_every_catalog_bundle():
    import json

    catalog = json.loads((ROOT / "shared/RegionalCoverage/catalog-v1.json").read_text())
    official = json.loads((ROOT / "shared/RegionalCoverage/official-regions-v1.json").read_text())
    catalog_ids = {entry["id"] for entry in catalog["regions"]}
    official_ids = {entry["id"] for entry in official["regions"]}
    assert official["boundary_kind"] == "official_administrative_and_statistical_boundaries"
    assert official_ids == catalog_ids
