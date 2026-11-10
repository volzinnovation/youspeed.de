#!/usr/bin/env python3
"""Build shared DE candidate presentation/mappings without replacing bundled packs.

The native exporter must first verify the checkpoint's actual class order. Its
receipt and the checkpoint bytes bind this catalog to that exact model. This
prepares an evaluation candidate, not a calibrated or deployment-approved pack.
"""
from __future__ import annotations

import argparse
from copy import deepcopy
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
# Runtime packs advance independently. Never derive the 134-class predecessor
# from whichever model happens to be deployed when this builder is rerun.
BASELINE = ROOT / "shared/tsr/baselines/de134-expanded-reference-2026-11-09"
CATALOG = BASELINE / "catalog.json"
BASE_PACK = BASELINE / "model-pack.json"
CATALOG_SHA256 = "caf88cdb00e3826867d5feb657c3065d66d8a48f1c289e165f6e717e46e953ad"
BASE_PACK_SHA256 = "7d5d679d1ad7f9a5036b7837f92b875154d93c85cba772d13f73992fd87debbd"
APPENDED_CLASSES = [
    "city:start", "city:end", "bus:stop", "supplementary:plate", "maxspeed:90",
    "DE:156-10", "DE:325.1", "DE:325.2",
]


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_baseline() -> tuple[dict, dict]:
    """Read the immutable source contracts and reject changed fixture bytes."""
    payloads = []
    for path, expected in ((CATALOG, CATALOG_SHA256), (BASE_PACK, BASE_PACK_SHA256)):
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected:
            raise ValueError(f"Immutable 134-class baseline digest mismatch: {path.name}")
        payloads.append(json.loads(raw))
    return payloads[0], payloads[1]


def build_catalog(source: dict, baseline: dict, classes: list[str], checkpoint_sha: str) -> tuple[dict, list[dict]]:
    """Pure contract construction, shared by the CLI and native fixture tests."""
    if len(checkpoint_sha) != 64 or any(c not in "0123456789abcdef" for c in checkpoint_sha):
        raise ValueError("Expected lowercase SHA-256 of the actual candidate checkpoint")
    if len(source["class_labels"]) != 134 or source["country"] != "DE":
        raise ValueError("Expected the pinned 134-class DE presentation catalog")
    if classes != source["class_labels"] + APPENDED_CLASSES:
        raise ValueError("Expansion must preserve all 136 predecessor indices and the frozen 142-class append order")
    if source["class_labels"] != [m["class_id"] for m in baseline["class_mapping"]]:
        raise ValueError("Baseline model mapping differs from the presentation order")
    if source["classifier_checkpoint_sha256"] != baseline["classifier"]["source_checkpoint"]["sha256"]:
        raise ValueError("Baseline checkpoint identity mismatch")
    if checkpoint_sha == source["classifier_checkpoint_sha256"]:
        raise ValueError("Expanded catalog cannot claim the 134-class checkpoint")
    by_id = {s["class_id"]: s for s in source["signs"]}
    if len(by_id) != len(source["signs"]) or not set(classes) <= set(by_id):
        raise ValueError("Missing or duplicated presentation metadata")
    result = deepcopy(source)
    result["class_labels"] = list(classes)
    result["classifier_checkpoint_sha256"] = checkpoint_sha
    result["signs"] = [deepcopy(by_id[c]) for c in classes]
    for sign in result["signs"][134:]:
        # Reference-only notes belong to the bundled model, not this candidate.
        sign["notes"] = "Candidate classifier output; evaluation and deployment approval remain separate."
        if sign["class_id"] == "supplementary:plate":
            if sign["display_eligible"] or sign["image_path"] is not None or sign["sign_code"] is not None:
                raise ValueError("Generic plate must not acquire a specific pictogram or restriction code")
            sign["notes"] += " Generic supplementary-plate family; content unresolved until OCR or review. No unique official family pictogram is available."
    result["signs"].extend(deepcopy(s) for s in source["signs"] if s["class_id"] not in classes)
    mapping = deepcopy(baseline["class_mapping"])
    for class_id in APPENDED_CLASSES:
        semantic = {"kind": "unknown"}
        if class_id == "city:start":
            semantic = {"kind": "city_entry"}
        elif class_id == "city:end":
            semantic = {"kind": "city_exit"}
        elif class_id == "maxspeed:90":
            semantic = {"kind": "maximum_speed", "value": 90, "unit": "km/h"}
        item = {"class_id": class_id, "label": by_id[class_id]["label"]["en"],
                "semantic": semantic, "threshold": 0.7}
        if class_id == "supplementary:plate":
            item.update(sign_role="supplementary_plate",
                        restriction={"kind": "unknown", "normalized_value": "unresolved"})
        mapping.append(item)
    return result, mapping


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--classes", type=Path, required=True)
    parser.add_argument("--class-index-sha256", required=True)
    parser.add_argument("--export-report", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Output must be a new candidate directory")
    if sha256(args.classes) != args.class_index_sha256:
        raise ValueError("Frozen class index digest mismatch")
    classes = json.loads(args.classes.read_text())["classes"]
    checkpoint_sha = sha256(args.checkpoint)
    export = json.loads(args.export_report.read_text())
    if (export.get("classes") != classes or export.get("checkpoint_sha256") != checkpoint_sha
            or export.get("class_index_sha256") != args.class_index_sha256):
        raise ValueError("Native export receipt does not bind this checkpoint and class index")
    source, baseline = load_baseline()
    catalog, mapping = build_catalog(source, baseline, classes, checkpoint_sha)
    args.output.mkdir(parents=True)
    for name, payload in [("prolix-de-class-catalog-v1.json", catalog), ("class-mapping.json", mapping)]:
        (args.output / name).write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    receipt = {
        "schema_version": 1, "purpose": "142-class DE native evaluation candidate",
        "checkpoint_sha256": checkpoint_sha, "class_index_sha256": args.class_index_sha256,
        "export_report_sha256": sha256(args.export_report), "class_count": len(classes),
        "source_catalog_sha256": sha256(CATALOG), "baseline_pack_sha256": sha256(BASE_PACK),
        "script_sha256": sha256(Path(__file__)),
        "catalog_sha256": sha256(args.output / "prolix-de-class-catalog-v1.json"),
        "class_mapping_sha256": sha256(args.output / "class-mapping.json"),
        "thresholds": "Existing 134 mappings preserved; new-class 0.7 thresholds are uncalibrated candidates.",
        "generic_plate": "supplementary_plate role; unknown/unresolved content; no inferred legal restriction or artwork",
        "platforms": ["iPhone Core ML", "Android TensorFlow Lite / LiteRT"],
        "deployment_approved": False,
    }
    (args.output / "catalog-build-report.json").write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
