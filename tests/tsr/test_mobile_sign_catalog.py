"""Guard the shared display catalog against model-index and platform drift."""

import hashlib
import json
from pathlib import Path

import jsonschema


ROOT = Path(__file__).resolve().parents[2]
SHARED = ROOT / "shared"
TSR = SHARED / "tsr"
ANDROID_PACK = ROOT / "android/app/src/main/assets/tsr/DE.panoramax-bootstrap.tsrmodelpack"
IPHONE_PACK = ROOT / "iphone/SpeedConsumerApp/TSRModelPacks/DE.panoramax-bootstrap.tsrmodelpack"


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_mobile_semantic_mappings_match_and_only_use_real_model_outputs():
    android = read_json(ANDROID_PACK / "manifest.json")
    iphone = read_json(IPHONE_PACK / "manifest.json")
    schema = read_json(TSR / "model-pack.schema.json")
    for manifest in (android, iphone):
        jsonschema.Draft202012Validator(schema).validate(manifest)

    assert android["class_mapping"] == iphone["class_mapping"]
    assert android["classifier"]["source_checkpoint"] == iphone["classifier"]["source_checkpoint"]
    labels = read_json(IPHONE_PACK / "classify_de_road_signs.mlmodelc/metadata.json")[0]["classLabels"]
    mappings = {entry["class_id"]: entry["semantic"] for entry in android["class_mapping"]}
    assert set(mappings) <= set(labels)
    for label in ("maxspeed:end", "no:end", "motorway:end", "trunk:end"):
        assert mappings[label] == {"kind": "restriction_end"}
    # Overtaking ends must never become actionable speed-limit changes.
    for label in ("no_overtaking:end", "no_overtaking:end:hgv", "DE:280", "DE:281"):
        assert label not in mappings
    # Typed town-boundary support is not evidence that this model recognizes it.
    assert "DE:310" not in mappings
    assert "city_entry" not in mappings


def test_shared_catalog_preserves_every_classifier_index_and_real_capabilities():
    catalog = read_json(TSR / "prolix-de-class-catalog-v1.json")
    metadata = read_json(IPHONE_PACK / "classify_de_road_signs.mlmodelc/metadata.json")[0]
    manifest = read_json(IPHONE_PACK / "manifest.json")
    assert catalog["schema_version"] == 1
    assert catalog["country"] == "DE"
    assert catalog["class_labels"] == metadata["classLabels"]
    assert len(catalog["class_labels"]) == 134
    assert catalog["classifier_checkpoint_sha256"] == manifest["classifier"]["source_checkpoint"]["sha256"]
    signs = {entry["class_id"]: entry for entry in catalog["signs"]}
    assert len(signs) == len(catalog["signs"])
    assert set(catalog["class_labels"]) <= set(signs)
    assert signs["pedestrian_crossing"]["sign_code"] == "DE:350"
    assert signs["pedestrian_crossing"]["image_path"] == "tsr/sign-pictograms/png/de-350.png"
    assert signs["pedestrian_crossing"]["display_eligible"] is True
    for label in ("DE:310", "DE:311", "no_overtaking:end:hgv"):
        assert label not in catalog["class_labels"]


def test_display_artworks_are_local_and_all_labels_are_translated():
    catalog = read_json(TSR / "prolix-de-class-catalog-v1.json")
    for sign in catalog["signs"]:
        assert set(sign["label"]) == {"de", "en", "fr", "nl"}, sign["class_id"]
        assert all(label.strip() for label in sign["label"].values())
        if sign["display_eligible"]:
            assert sign["sign_code"]
            assert sign["image_path"]
        if sign["image_path"]:
            image_path = SHARED / sign["image_path"]
            assert image_path.resolve().is_relative_to((TSR / "sign-pictograms/png").resolve())
            assert image_path.suffix == ".png"
            assert image_path.is_file(), sign["image_path"]
            assert image_path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n")


def test_pictogram_bytes_match_recorded_commons_provenance():
    directory = TSR / "sign-pictograms"
    manifest = read_json(directory / "manifest.json")
    catalog = read_json(TSR / "prolix-de-class-catalog-v1.json")
    recorded_pngs = set()
    for artwork in manifest["artworks"]:
        assert artwork["license"] == "Public domain"
        assert artwork["license_basis"]
        assert artwork["source_page_url"].startswith("https://commons.wikimedia.org/")
        assert artwork["commons_page_revision"]
        for kind in ("original", "png"):
            path = directory / artwork[f"{kind}_path"]
            assert path.resolve().is_relative_to(directory.resolve())
            content = path.read_bytes()
            assert hashlib.sha256(content).hexdigest() == artwork[f"{kind}_sha256"]
            assert len(content) == artwork[f"{kind}_bytes"]
        assert max(artwork["png_width"], artwork["png_height"]) <= 256
        recorded_pngs.add(f"tsr/sign-pictograms/{artwork['png_path']}")
    used_pngs = {sign["image_path"] for sign in catalog["signs"] if sign["image_path"]}
    assert used_pngs <= recorded_pngs
