import hashlib
import json
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[2]
SIGN_ROOT = ROOT / "shared/tsr/sign-pictograms"


def load(name):
    return json.loads((SIGN_ROOT / name).read_text())


def test_national_sign_set_index_is_explicit_and_schema_valid():
    index = load("national-set-index-v1.json")
    schema = load("national-set-schema-v1.json")
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(schema).validate(index)

    by_country = {entry["country"]: entry for entry in index["sets"]}
    assert set(by_country) == {"DE", "FR", "NL", "BE", "CH"}
    assert by_country["DE"]["status"] == "active"
    assert by_country["CH"]["status"] == "not_ready"
    assert by_country["CH"]["runtime_status"] == "not_ready"
    assert by_country["CH"]["display_eligible_assets"] == 0
    assert len(list((SIGN_ROOT / "originals").glob("de-*.svg"))) == 111
    assert len(list((SIGN_ROOT / "png").glob("de-*.png"))) == 111

    for country in ("FR", "NL", "BE"):
        entry = by_country[country]
        assert entry["status"] == "artwork_ready"
        assert entry["runtime_status"] == "not_ready"
        manifest = load(ROOT / "shared/tsr/sign-pictograms" / entry["asset_manifest"])
        assert manifest["country"] == country
        assert manifest["status"] == "core_reviewed_artwork"
        assert manifest["runtime_status"] == "not_ready"
        assert manifest["artwork_approval"]["decision"] == "approved_commons_renditions"
        assert manifest["artwork_approval"]["commercial_use_policy"] == (
            "exclude_only_if_commercial_use_is_not_permitted"
        )
        assert manifest["license_review"]["commercial_use_approved"] is True
        assert len(manifest["artworks"]) == entry["display_eligible_assets"]
        assert len(load(ROOT / "shared/tsr/sign-pictograms" / entry["selection"])["entries"]) == len(manifest["artworks"])
        for artwork in manifest["artworks"]:
            # The manifest paths are rooted at shared/tsr/sign-pictograms.
            original = ROOT / "shared/tsr/sign-pictograms" / artwork["original_path"]
            png = ROOT / "shared/tsr/sign-pictograms" / artwork["png_path"]
            assert original.is_file()
            assert png.is_file()
            assert hashlib.sha256(original.read_bytes()).hexdigest() == artwork["original_sha256"]
            assert hashlib.sha256(png.read_bytes()).hexdigest() == artwork["png_sha256"]
            assert artwork["mapping_status"].startswith("reviewed")
            assert artwork["attribution_required"] in (True, False)
            assert artwork["commercial_use_permitted"] is True
            assert artwork["license_source_url"].startswith(
                "https://commons.wikimedia.org/"
            )
            provenance = artwork["license_provenance"]
            assert provenance["repository"] == "Wikimedia Commons"
            assert provenance["declared_license"] == artwork["license"]
            assert provenance["commons_sha1"] == artwork["original_commons_sha1"]
        assert entry["catalog_path"] is None

    be_selection = load(ROOT / "shared/tsr/sign-pictograms/national/BE/selection.json")
    be_by_code = {entry["sign_code"]: entry for entry in be_selection["entries"]}
    assert be_by_code["B1"]["semantic_id"] == "give_way"
    assert be_by_code["B5"]["semantic_id"] == "stop"
    assert be_by_code["B7"]["semantic_id"] == "stop_ahead"
    assert be_by_code["B7"]["mapping_status"] == "reviewed_legacy_transition"


def test_foreign_country_code_mapping_and_runtime_readiness_are_explicit():
    mapping = load(ROOT / "shared/tsr/sign-pictograms/sources/panoramax-country-code-mapping-v1.json")
    assert mapping["source"]["revision"] == "7a811057049f6de207f909c0f1be2905fa9baf01"
    assert mapping["mapping_policy"]["country_code_map"] == "complete_for_all_rows_with_a_country_column"
    assert mapping["country_code_counts"] == {"FR": 144, "NL": 159, "BE": 135, "CH": 139}
    assert len(mapping["entries"]) == 225

    readiness = load(ROOT / "shared/tsr/foreign-runtime-readiness-v1.json")
    readiness_schema = load(ROOT / "shared/tsr/foreign-runtime-readiness-v1.schema.json")
    jsonschema.Draft202012Validator.check_schema(readiness_schema)
    jsonschema.Draft202012Validator(readiness_schema).validate(readiness)
    assert readiness["source_manifest_sha256"] == hashlib.sha256(
        (ROOT / "shared/tsr/training-sources-v1.json").read_bytes()
    ).hexdigest()
    assert readiness["shared_pipeline"]["pipeline"] == "proposal_classification"
    assert readiness["shared_pipeline"]["temporal_contract"]["validated_passage_required"] is True
    by_country = {item["country"]: item for item in readiness["countries"]}
    assert set(by_country) == {"FR", "NL", "BE"}
    for country, minimum_assets in {"FR": 114, "NL": 111, "BE": 115}.items():
        item = by_country[country]
        assert item["artwork"]["display_assets"] == minimum_assets
        for export_key in ("classifier_coreml", "classifier_litert"):
            export = item["exports"][export_key]
            assert export["status"] == "passed"
            evidence = ROOT / export["evidence_path"]
            assert evidence.is_file()
            assert hashlib.sha256(evidence.read_bytes()).hexdigest() == export["evidence_sha256"]
        parity = item["parity"]
        assert parity["status"] == "passed"
        parity_evidence = ROOT / parity["evidence_path"]
        assert parity_evidence.is_file()
        assert hashlib.sha256(parity_evidence.read_bytes()).hexdigest() == parity["evidence_sha256"]
        calibration = item["calibration"]
        assert calibration["status"] == "accepted_operational_benchmark"
        report = ROOT / calibration["evidence_path"]
        assert report.is_file()
        assert hashlib.sha256(report.read_bytes()).hexdigest() == calibration["evidence_sha256"]
        assert calibration["runtime_output"] == "raw_score"
        assert calibration["holdout_policy"] == (
            "published_panoramax_validation_is_operational_benchmark_not_independent_holdout"
        )
        runtime_manifest = item["runtime_manifest"]
        assert runtime_manifest["status"] == "evaluation"
        manifest = ROOT / runtime_manifest["path"]
        assert manifest.is_file()
        assert hashlib.sha256(manifest.read_bytes()).hexdigest() == runtime_manifest["manifest_sha256"]
