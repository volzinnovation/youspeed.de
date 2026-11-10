"""Expanded native catalogs preserve identities and never infer plate content."""
from copy import deepcopy
import importlib.util
import json
from pathlib import Path

import jsonschema
import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("expanded_catalog", ROOT / "scripts/tsr/build_de_expanded_catalog.py")
subject = importlib.util.module_from_spec(spec)
spec.loader.exec_module(subject)


def sources():
    catalog, baseline = subject.load_baseline()
    return catalog, baseline, catalog["class_labels"] + subject.APPENDED_CLASSES


@pytest.mark.parametrize("name", ["CATALOG", "BASE_PACK"])
def test_expansion_refuses_changed_baseline_bytes(name, tmp_path, monkeypatch):
    original = getattr(subject, name)
    changed = tmp_path / original.name
    changed.write_bytes(original.read_bytes() + b"\n")
    monkeypatch.setattr(subject, name, changed)
    with pytest.raises(ValueError, match="Immutable 134-class baseline digest mismatch"):
        subject.load_baseline()


def test_expansion_preserves_outputs_and_native_pack_schema():
    source, baseline, classes = sources()
    catalog, mapping = subject.build_catalog(source, baseline, classes, "a" * 64)
    assert len(catalog["class_labels"]) == 142
    assert catalog["class_labels"][:136] == source["class_labels"] + ["city:start", "city:end"]
    assert [s["class_id"] for s in catalog["signs"][:142]] == classes
    assert len({s["class_id"] for s in catalog["signs"]}) == len(catalog["signs"])
    assert mapping[:134] == baseline["class_mapping"]
    assert catalog["classifier_checkpoint_sha256"] == "a" * 64
    candidate = deepcopy(baseline)
    candidate["class_mapping"] = mapping
    candidate["classifier"]["source_checkpoint"]["sha256"] = "a" * 64
    schema = json.loads((ROOT / "shared/tsr/model-pack.schema.json").read_text())
    jsonschema.Draft202012Validator(schema).validate(candidate)
    assert source["class_labels"] != classes  # Pure construction preserves the historical baseline.


def test_plate_is_unresolved_and_bus_stop_is_distinct_from_bus_lane():
    source, baseline, classes = sources()
    catalog, mapping = subject.build_catalog(source, baseline, classes, "a" * 64)
    signs = {s["class_id"]: s for s in catalog["signs"]}
    plate = next(m for m in mapping if m["class_id"] == "supplementary:plate")
    assert plate["semantic"] == {"kind": "unknown"}
    assert plate["sign_role"] == "supplementary_plate"
    assert plate["restriction"] == {"kind": "unknown", "normalized_value": "unresolved"}
    assert signs["supplementary:plate"]["display_eligible"] is False
    assert signs["supplementary:plate"]["image_path"] is None
    assert signs["supplementary:plate"]["sign_code"] is None
    assert signs["bus:stop"]["sign_code"] == "DE:224"
    assert signs["bus:start"]["sign_code"] == "DE:245"
    assert next(m for m in mapping if m["class_id"] == "maxspeed:90")["semantic"] == {
        "kind": "maximum_speed", "value": 90, "unit": "km/h"}
    for class_id in subject.APPENDED_CLASSES:
        assert set(signs[class_id]["label"]) == {"de", "en", "fr", "nl"}
        if class_id != "supplementary:plate":
            assert (ROOT / "shared" / signs[class_id]["image_path"]).is_file()


@pytest.mark.parametrize("change", ["reorder_base", "reorder_append", "duplicate", "missing", "old_identity"])
def test_rejects_index_and_checkpoint_drift(change):
    source, baseline, classes = sources()
    checkpoint = "a" * 64
    if change == "reorder_base":
        classes[0], classes[1] = classes[1], classes[0]
    elif change == "reorder_append":
        classes[136], classes[137] = classes[137], classes[136]
    elif change == "duplicate":
        classes[-1] = classes[-2]
    elif change == "missing":
        classes.pop()
    else:
        checkpoint = source["classifier_checkpoint_sha256"]
    with pytest.raises(ValueError):
        subject.build_catalog(source, baseline, classes, checkpoint)


def test_rejects_invented_generic_plate_artwork():
    source, baseline, classes = sources()
    next(s for s in source["signs"] if s["class_id"] == "supplementary:plate")["image_path"] = "tsr/sign-pictograms/png/de-1000-10.png"
    with pytest.raises(ValueError, match="Generic plate"):
        subject.build_catalog(source, baseline, classes, "a" * 64)


def test_exact_curve_board_is_reference_only_and_preserves_broad_red_arrow_family():
    source, baseline, classes = sources()
    catalog, _ = subject.build_catalog(source, baseline, classes, "a" * 64)
    signs = {s["class_id"]: s for s in catalog["signs"]}
    assert len(catalog["class_labels"]) == 142
    assert catalog["class_labels"][0] == "arrow:red"
    assert "DE:625-20" not in catalog["class_labels"]
    exact = signs["DE:625-20"]
    assert exact["display_eligible"] is True
    assert exact["image_path"] == "tsr/sign-pictograms/png/de-625-20.png"
    assert exact["classifier_family"] == {
        "class_id": "arrow:red", "scope": "broad_visual_family", "exact_subtype_inferred": False}
    assert signs["arrow:red"]["display_eligible"] is False
    assert signs["arrow:red"]["image_path"] is None
    assert signs["arrow:red"]["sign_code"] is None
    assert "rechtsweisend" in exact["label"]["de"]


def test_cli_binds_export_receipt_and_rejects_mismatched_checkpoint(tmp_path, monkeypatch):
    _, _, classes = sources()
    checkpoint = tmp_path / "fixture.pt"
    checkpoint.write_bytes(b"Test checkpoint bytes; not a deployable model")
    index = tmp_path / "classes.json"
    index.write_text(json.dumps({"classes": classes}))
    receipt = tmp_path / "export-report.json"
    export = {"classes": classes, "checkpoint_sha256": subject.sha256(checkpoint),
              "class_index_sha256": subject.sha256(index)}
    receipt.write_text(json.dumps(export))
    output = tmp_path / "candidate"
    monkeypatch.setattr("sys.argv", ["build_de_expanded_catalog.py", "--checkpoint", str(checkpoint),
        "--classes", str(index), "--class-index-sha256", subject.sha256(index),
        "--export-report", str(receipt), "--output", str(output)])
    checkpoint.write_bytes(b"Different checkpoint must fail before writing any candidate files")
    with pytest.raises(ValueError, match="export receipt"):
        subject.main()
    assert not output.exists()
    checkpoint.write_bytes(b"Test checkpoint bytes; not a deployable model")
    subject.main()
    report = json.loads((output / "catalog-build-report.json").read_text())
    assert report["class_count"] == 142
    assert report["checkpoint_sha256"] == subject.sha256(checkpoint)
    assert report["deployment_approved"] is False
    with pytest.raises(ValueError, match="new candidate directory"):
        subject.main()
