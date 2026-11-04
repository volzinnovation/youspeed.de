"""Every imported MobiData class needs artwork or an explicit presentation reason."""

from collections import Counter
import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
RECEIPT = ROOT / "docs/MOBIDATA_BW_PICTOGRAM_COVERAGE_2026-11-04.json"
AUDIT = ROOT / "docs/MOBIDATA_BW_PICTOGRAM_AUDIT_V1_5.json"
CATALOG = ROOT / "shared/tsr/prolix-de-class-catalog-v1.json"
ARTWORK_ROOT = ROOT / "shared/tsr/sign-pictograms"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_coverage_accounts_for_every_pinned_incoming_source_class():
    receipt, audit = read(RECEIPT), read(AUDIT)
    assert receipt["source"] == audit["source"]
    assert receipt["source"]["sha256"] == "cb4c89d3d2b18a06a1d5956b94865310929ff455d7a33005053bccaac66b79c3"
    for relative, expected in receipt["inputs"].items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected
    rows = receipt["entries"]
    assert len(rows) == len({row[0] for row in rows}) == 53
    assert {row[0]: row[1] for row in rows} == {
        entry["source_code"]: entry["count"] for entry in audit["entries"]
    }
    assert sum(row[1] for row in rows) == 163504
    assert dict(Counter(row[2] for row in rows)) == receipt["counts_by_policy"]
    records = Counter()
    for _, count, policy, _ in rows:
        records[policy] += count
    assert dict(records) == receipt["records_by_policy"]
    assert set(records) == set(receipt["policy_rationales"])
    assert all(receipt["policy_rationales"].values())


def test_each_source_class_resolves_to_shared_artwork_or_a_specific_exception():
    receipt, audit, catalog = read(RECEIPT), read(AUDIT), read(CATALOG)
    source = {entry["source_code"]: entry for entry in audit["entries"]}
    artworks = {entry["sign_code"]: entry for entry in read(ARTWORK_ROOT / "manifest.json")["artworks"]}
    eligible = [sign for sign in catalog["signs"] if sign["display_eligible"]]
    blocked_annotations = {"DE:274-50[WVZ Rombachtunnel]", "DE:331.2[]"}
    reviewed_aliases = {"DE:117-10": "DE:117", "DE:142-10": "DE:142", "DE:350-10": "DE:350"}

    for code, _, policy, artwork_code in receipt["entries"]:
        entry = source[code]
        assert entry["pictogram_key"] == artwork_code
        if policy == "numeric_speed_schematic":
            assert re.fullmatch(r"DE:274-[1-9][0-9]{0,2}", code), code
            assert entry["pictogram_status"] == "numeric_speed_schematic_exception"
            assert entry["display_eligible"] is True
            continue
        if policy == "source_annotation_blocked":
            assert code in blocked_annotations
            assert entry["pictogram_status"] == "source_annotation_requires_review"
            assert entry["display_eligible"] is False
            continue
        if policy == "generic_without_printed_speed":
            assert code == "DE:278"
            assert entry["pictogram_status"] == "missing_printed_speed"
            assert entry["display_eligible"] is False
            assert artwork_code is entry["parameter_value"] is None
            continue

        if policy == "reviewed_pictogram_alias":
            assert reviewed_aliases[code] == artwork_code
            assert entry["pictogram_status"] == "existing_reviewed_alias"
        else:
            assert policy == "exact_pictogram", code
            assert entry["pictogram_status"] == "existing_exact"
            assert code == artwork_code
        assert entry["display_eligible"] is True
        artwork = artworks[artwork_code]
        assert any(sign["sign_code"] == artwork_code
                   and sign["image_path"] == "tsr/sign-pictograms/" + artwork["png_path"]
                   for sign in eligible), code
        for kind in ("original", "png"):
            relative = artwork[f"{kind}_path"]
            assert entry[f"pictogram_{kind}_path"] == "shared/tsr/sign-pictograms/" + relative
            actual_hash = hashlib.sha256((ARTWORK_ROOT / relative).read_bytes()).hexdigest()
            assert actual_hash == artwork[f"{kind}_sha256"], code


def test_unvalued_speed_end_fallback_does_not_hide_missing_numeric_support():
    signs = {sign["class_id"]: sign for sign in read(CATALOG)["signs"]}
    assert signs["maxspeed:end"]["display_eligible"] is False
    assert signs["maxspeed:end"]["image_path"] is None
    assert "DE:278" not in signs
    for speed in (5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130):
        sign = signs[f"DE:278-{speed}"]
        assert sign["display_eligible"] is True
        assert (ROOT / "shared" / sign["image_path"]).is_file()
    historical = read(RECEIPT)["historical_pilot_coverage"]
    assert hashlib.sha256((ROOT / historical["path"]).read_bytes()).hexdigest() == historical["sha256"]
