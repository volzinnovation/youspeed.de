import copy
import hashlib
import json
from pathlib import Path

import jsonschema
import pytest
from referencing import Registry, Resource

from scripts.map.build_mobile_region_catalog import build_catalog, geometry_coordinates

ROOT = Path(__file__).resolve().parents[2]
TSR = ROOT / "shared/tsr"


def load(path):
    return json.loads(path.read_text())


def validator(name):
    schema = load(TSR / name)
    jsonschema.Draft202012Validator.check_schema(schema)
    model = load(TSR / "model-pack.schema.json")
    registry = Registry().with_resource(model["$id"], Resource.from_contents(model))
    return jsonschema.Draft202012Validator(schema, registry=registry)


def test_country_registry_and_real_fixture_manifest_hashes():
    check = validator("country-pack-registry-v1.schema.json")
    production = load(TSR / "country-pack-registry-v1.json")
    fixtures = load(TSR / "fixtures/country-pack-registry-v1.json")
    check.validate(production)
    check.validate(fixtures)
    assert {p["countries"][0] for p in production["packs"]} == {"DE", "FR", "BE", "NL"}
    assert all(p["manifest"] is None and not p["calibrated"] for p in production["packs"])
    for pack in fixtures["packs"]:
        country = pack["countries"][0]
        if country in {"BE", "NL"}:
            assert pack["manifest"] is None
            continue
        path = TSR / f"fixtures/country-packs/{country.lower()}-release-v1.json"
        manifest = load(path)
        validator("country-pack-release-v1.schema.json").validate(manifest)
        assert pack["manifest"]["sha256"] == hashlib.sha256(path.read_bytes()).hexdigest()
        assert pack["manifest"]["size_bytes"] == path.stat().st_size
        assert manifest["pack_id"] == manifest["runtime_manifest"]["pack_id"] == pack["pack_id"]
        assert manifest["countries"] == manifest["runtime_manifest"]["countries"] == pack["countries"]
        assert not manifest["runtime_manifest"]["calibration"]["calibrated"]


@pytest.mark.parametrize("field,value", [("generation",0),("schema_version",2),("environment","development"),("expires_at",-1)])
def test_registry_rejects_invalid_versions_and_environment(field, value):
    registry = load(TSR / "country-pack-registry-v1.json")
    registry[field] = value
    with pytest.raises(jsonschema.ValidationError):
        validator("country-pack-registry-v1.schema.json").validate(registry)


@pytest.mark.parametrize("mutate", [
    lambda p: p["provenance"][0].update(revision="main"),
    lambda p: p["files"][0].update(path="../detector.tflite"),
    lambda p: p["files"][0]["artifact"].update(url="https://user:token@example.invalid/file"),
    lambda p: p["files"][0]["artifact"].update(url="https://example.invalid/file?token=secret"),
    lambda p: p["files"][0]["artifact"].update(size_bytes=0),
    lambda p: p["files"][0]["artifact"].update(sha256=""),
    lambda p: p.pop("acceptance"),
    lambda p: p.pop("provenance"),
])
def test_release_envelope_rejects_unsafe_or_missing_metadata(mutate):
    manifest = load(TSR / "fixtures/country-packs/de-release-v1.json")
    mutate(manifest)
    with pytest.raises(jsonschema.ValidationError):
        validator("country-pack-release-v1.schema.json").validate(manifest)


def test_mobile_catalog_covers_every_configured_bundle_and_pins_targets():
    targets_path = ROOT / "iphone/SpeedConsumerApp/BundleTargets.top10.json"
    catalog = load(ROOT / "shared/RegionalCoverage/catalog-v1.json")
    targets = load(targets_path)
    assert targets == load(ROOT / "android/app/src/main/assets/BundleTargets.top10.json")
    rule_file_codes = {"DE": "DEU", "FR": "FRA", "BE": "BEL", "NL": "NLD"}
    for country in targets["countries"]:
        code = country["iso2"]
        rules = country.get("penalty_rules")
        if code not in rule_file_codes:
            assert rules is None
            continue
        assert rules and rules["file"] == f"{rule_file_codes[code]}-rules.json"
        assert (ROOT / rules["source"]).is_file()
        rule_data = load(ROOT / rules["source"])
        assert rule_data.get("country_code", rule_data.get("land_code")) == rule_file_codes[code]
    assert hashlib.sha256(targets_path.read_bytes()).hexdigest() == catalog["targets_sha256"]
    expected = {c["country_id"] + "|" + r["region_id"].rsplit("/", 1)[-1]
                for c in targets["countries"] for r in c["regions"]}
    assert len(catalog["regions"]) == len(expected)
    assert {r["id"] for r in catalog["regions"]} == expected
    for entry in catalog["regions"]:
        geometry_coordinates({"type": "MultiPolygon", "coordinates": entry["polygons"]})
        assert entry["source_poly"] == entry["source_pbf"].removesuffix("-latest.osm.pbf") + ".poly"
        assert entry["source_poly"].startswith("https://download.geofabrik.de/")


def test_catalog_generator_is_deterministic_and_rejects_missing_or_wrong_parent():
    targets = {"countries": [{"country_id":"germany","iso2":"DE","mode":"regional_shards","regions":[{"region_id":"test"}]}]}
    index = {"features":[{"properties":{"id":"test","parent":"germany","urls":{"pbf":"https://download.geofabrik.de/europe/germany/test-latest.osm.pbf"}},
        "geometry":{"type":"Polygon","coordinates":[[[0,0],[1,0],[0,1],[0,0]]]}}]}
    target_bytes = json.dumps(targets).encode()
    data = json.dumps(index).encode()
    assert build_catalog(data, target_bytes) == build_catalog(data, target_bytes)
    invalid = copy.deepcopy(index)
    invalid["features"][0]["properties"]["parent"] = "france"
    with pytest.raises(ValueError, match="parent"):
        build_catalog(json.dumps(invalid).encode(), target_bytes)
    with pytest.raises(ValueError, match="Missing"):
        build_catalog(b'{"features":[]}', target_bytes)


@pytest.mark.parametrize("coordinates", [[],[[]],[[[0,0],[1,0],[0,1]]],[[[0,0],[181,0],[0,1],[0,0]]]])
def test_catalog_generator_rejects_invalid_geometry(coordinates):
    with pytest.raises(ValueError):
        geometry_coordinates({"type":"Polygon","coordinates":coordinates})
