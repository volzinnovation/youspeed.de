"""Review clones preserve crop identity and never inherit an old approval."""
import json
from pathlib import Path

import pytest

from scripts.tsr import prepare_de_expanded_review as subject


@pytest.fixture
def inputs(tmp_path):
    source = tmp_path / "source"
    target = tmp_path / "target"
    base = [f"base:{i}" for i in range(134)] + ["city:start", "city:end"]
    classes = tmp_path / "class-index.json"
    subject.write(classes, {"classes": base + ["bus:stop", "supplementary:plate", "maxspeed:90", "DE:156-10", "DE:325.1", "DE:325.2"]})
    subject.write(source / "class-index.json", {"classes": base})
    catalog = tmp_path / "catalog.json"
    subject.write(catalog, {"signs": [{"class_id": c, "label": {"en": c}} for c in base + ["bus:stop"]]})
    images = []
    for key in ("A006", "P002"):
        for kind in ("native", "canonical", "blind"):
            path = source / f"intake/{kind}/{key}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((kind + key).encode())
        images.append({"id": key, "source": "android" if key.startswith("A") else "panoramax",
                       "path": f"native/{key}.png", "canonicalPath": f"canonical/{key}.png",
                       "sha256": subject.sha(source / f"intake/native/{key}.png"),
                       "canonicalSha256": subject.sha(source / f"intake/canonical/{key}.png")})
    subject.write(source / "intake/benchmark-all120.json", {"images": images})
    subject.write(source / "intake/evaluation-blind.json", {"classes": base, "samples": [
        {"blind_id": r["id"], "truth_label": None, "route_component": "frozen-route"} for r in images]})
    for name, key in (("phone", "A006"), ("panoramax", "P002")):
        subject.write(source / f"intake/blind/proposed-{name}-labels.json", {"labels": [{
            "id": key, "proposed_class_id": None, "confidence": "out_of_catalog",
            "visual_reason": "Original assistant proposal", "human_reviewed": False, "approved": False}]})
    return source, target, classes, catalog


def test_clone_preserves_bytes_and_archives_existing_manual_review(inputs):
    source, target, classes, catalog = inputs
    manual = source / "intake/blind/review-approved.json"
    subject.write(manual, {"status": "human_approved", "records": [{"id": "A006", "reviewed": True}]})
    original = {str(p.relative_to(source)): p.read_bytes() for p in source.rglob("*") if p.is_file()}
    report = subject.prepare_one(source, target, classes, catalog, 2,
        {"A006": subject.visual_updates()["A006"]}, {"scope": "Previously inspected diagnostic review"})
    assert {str(p.relative_to(source)): p.read_bytes() for p in source.rglob("*") if p.is_file()} == original
    assert (target / "provenance/intake/blind/review-approved.json").read_bytes() == manual.read_bytes()
    assert not (target / "intake/blind/review-approved.json").exists()
    package = json.loads((target / "intake/blind/review-package.json").read_text())
    assert all(r["reviewed"] is False for r in package["records"])
    assert package["records"][0]["decision"] == "bus:stop"
    assert report["manifest_preserved_byte_for_byte"] is True
    assert report["final_f1_allowed"] is False
    assert len(report["manual_reviews_preserved"]) == 1
    assert len(report["proposal_changes"]) == 1
    for row in report["image_files"]:
        assert subject.sha(target / "intake" / row["path"]) == row["sha256"]


def test_changed_crop_fails_without_touching_original(inputs):
    source, target, classes, catalog = inputs
    crop = source / "intake/native/A006.png"
    crop.write_bytes(b"changed pixels")
    with pytest.raises(ValueError, match="digest mismatch"):
        subject.prepare_one(source, target, classes, catalog, 2, {}, {})
    assert crop.read_bytes() == b"changed pixels"


def test_training_or_non_intake_ids_cannot_be_added(inputs):
    source, target, classes, catalog = inputs
    with pytest.raises(ValueError, match="outside the frozen intake"):
        subject.prepare_one(source, target, classes, catalog, 2, {"Z999": {}}, {})
    assert not target.exists()


def test_class_reordering_is_rejected(inputs):
    source, target, classes, catalog = inputs
    value = json.loads(classes.read_text())
    value["classes"][0], value["classes"][1] = value["classes"][1], value["classes"][0]
    subject.write(classes, value)
    with pytest.raises(ValueError, match="136 predecessor"):
        subject.prepare_one(source, target, classes, catalog, 2, {}, {})
