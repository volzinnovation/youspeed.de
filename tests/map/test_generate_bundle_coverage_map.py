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
    south, north = MODULE.MAIN_VIEW[2:]
    _, y_south = MODULE.project(0, south)
    _, y_north = MODULE.project(0, north)
    assert abs(y_south - MODULE.MAP[3]) < 1e-9
    assert abs(y_north - MODULE.MAP[1]) < 1e-9
    # Equal latitude spans grow toward the north in Web Mercator.
    quarter = (north - south) / 4
    _, y_lower = MODULE.project(0, south + quarter)
    _, y_upper = MODULE.project(0, north - quarter)
    assert y_south > y_lower > y_upper > y_north
    assert y_upper - y_north > y_south - y_lower


def test_official_geometry_covers_every_catalog_bundle():
    import json

    catalog = json.loads((ROOT / "shared/RegionalCoverage/catalog-v1.json").read_text())
    official = json.loads((ROOT / "shared/RegionalCoverage/official-regions-v1.json").read_text())
    catalog_ids = {entry["id"] for entry in catalog["regions"]}
    official_ids = {entry["id"] for entry in official["regions"]}
    assert official["boundary_kind"] == "official_administrative_and_statistical_boundaries"
    assert official_ids == catalog_ids
