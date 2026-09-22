#!/usr/bin/env python3
"""Stage the CH source-preparation model as an evaluation-only mobile pack."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.tsr.mapping_review import semantic as reviewed_semantic, reconcile_catalog


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_sha256(path: Path) -> str:
    if path.is_file():
        return sha256(path)
    digest = hashlib.sha256()
    for child in sorted(item for item in path.rglob("*") if item.is_file()):
        digest.update(child.relative_to(path).as_posix().encode())
        digest.update(b"\0")
        digest.update(child.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.name == "prolix-ch-class-catalog-v1.json":
        payload = reconcile_catalog(payload)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def semantic(label: str) -> dict[str, Any]:
    return reviewed_semantic(label, "CH")


def class_mapping(labels: list[str]) -> list[dict[str, Any]]:
    return [
        {"class_id": label, "label": label, "semantic": semantic(label), "threshold": 0.70}
        for label in labels
    ]


def copy_artwork(source_manifest: Path, source_root: Path) -> tuple[Path, list[dict[str, Any]]]:
    source = load(source_manifest)
    target_root = ROOT / "shared/tsr/sign-pictograms/national/CH"
    for directory in (target_root / "originals", target_root / "png"):
        directory.mkdir(parents=True, exist_ok=True)
    source_manifest_copy = target_root / "source-preparation-manifest.json"
    shutil.copy2(source_manifest, source_manifest_copy)
    artworks: list[dict[str, Any]] = []
    for item in source["artworks"]:
        original_name = Path(item["original_path"]).name
        png_name = Path(item["png_path"]).name
        original = target_root / "originals" / original_name
        png = target_root / "png" / png_name
        shutil.copy2(source_root / item["original_path"], original)
        shutil.copy2(source_root / item["png_path"], png)
        copied = dict(item)
        copied["original_path"] = f"national/CH/originals/{original_name}"
        copied["png_path"] = f"national/CH/png/{png_name}"
        copied["mapping_status"] = "source_preparation_only"
        copied["mapping_basis"] = (
            "Panoramax CH mapping joined to the ASTRA official sign archive; "
            "source and redistribution review remains pending."
        )
        copied["original_sha256"] = sha256(original)
        copied["png_sha256"] = sha256(png)
        artworks.append(copied)
    manifest = {
        "schema_version": 1,
        "country": "CH",
        "reviewed_at": "2026-09-17",
        "status": "source_preparation_only",
        "runtime_status": "not_ready",
        "artwork_approval": {
            "decision": "pending_source_and_redistribution_review",
            "commercial_use_policy": "do_not_treat_source_availability_as_permission",
            "provenance_required_in_license_record": True,
        },
        "license_review": {
            "commercial_use_approved": False,
            "basis": "ASTRA archive source availability is not treated as app-redistribution permission.",
            "reviewed_by_owner": False,
        },
        "regulation_sources": [{"title": "ASTRA Swiss traffic-sign archive", "url": "https://www.astra.admin.ch/de/signale"}],
        "source_manifest": str(source_manifest_copy.relative_to(ROOT)),
        "source_policy": source["source_policy"],
        "scope": source["scope"],
        "artworks": artworks,
    }
    manifest_path = target_root / "manifest.json"
    write(manifest_path, manifest)
    selection = {
        "schema_version": 1,
        "country": "CH",
        "status": "source_preparation_only",
        "runtime_status": "not_ready",
        "entries": [
            {
                "semantic_id": item["model_class_label"],
                "sign_code": item["sign_code"],
                "artwork_id": item["asset_id"],
                "mapping_status": "source_preparation_only",
                "mapping_basis": item["mapping_basis"],
                "source_model_class": item["model_class_label"],
                "runtime_model_class": item["model_class_label"],
            }
            for item in artworks
        ],
    }
    write(target_root / "selection.json", selection)
    return manifest_path, artworks


def build(args: argparse.Namespace) -> None:
    artwork_manifest, artworks = copy_artwork(args.artwork_manifest, args.artwork_root)
    export = load(args.coreml_export)
    labels = [export["class_names"][str(index)] for index in sorted(map(int, export["class_names"]))]
    tflite = args.tflite
    coreml = args.coreml_compiled
    detector_android = ROOT / "android/app/src/main/assets/tsr/DE.panoramax-bootstrap.tsrmodelpack/yolo11n_panoramax_float16.tflite"
    detector_ios = ROOT / "iphone/SpeedConsumerApp/TSRModelPacks/DE.panoramax-bootstrap.tsrmodelpack/yolo11n_panoramax.mlmodelc"
    source_sha = export["source_checkpoint_sha256"]
    dataset_sha = sha256(args.dataset_summary)
    evaluation_sha = sha256(args.real_evaluation)
    coreml_probe = load(args.coreml_parity)
    parity = {
        "schema_version": 1,
        "country": "CH",
        "status": "evaluation_only",
        "source_checkpoint_sha256": source_sha,
        "coreml": coreml_probe.get("coreml", coreml_probe),
        "litert": load(args.litert_parity),
        "device_execution": {"ios": "not measured", "android": "not measured"},
    }
    parity_path = ROOT / "shared/tsr/foreign-calibration/CH-mobile-parity-v1.json"
    write(parity_path, parity)
    parity_sha = sha256(parity_path)
    ch_manifest_sha = sha256(artwork_manifest)
    source_checkpoint = {
        "uri": "local://youspeed-tsr-ch-panoramax-20260917/model/ch-classifier-bootstrap-v9/weights/best.pt",
        "revision": "ch-classifier-bootstrap-v9",
        "sha256": source_sha,
    }
    common = {
        "schema_version": 1,
        "pack_id": "ch-panoramax-bootstrap-evaluation-v1",
        "countries": ["CH"],
        "pipeline": "proposal_classification",
        "taxonomy_version": "tsr-semantic-v1",
        "preprocessing": {
            "version": "vision-scale-fit-rgb-v1",
            "input_width": 1280,
            "input_height": 1280,
            "color_space": "rgb",
            "resize": "scale_fit_letterbox",
            "orientation": "normalize_exif_and_mirroring",
        },
        "thresholds": {
            "provisional": 0.45,
            "confirmed": 0.70,
            "unknown": 0.25,
            "confirmation_frames": 2,
            "confirmation_window_ms": 1500,
            "minimum_track_iou": 0.20,
        },
        "calibration": {
            "kind": "none",
            "revision": "uncalibrated-ch-source-preparation-v9",
            "dataset_sha256": dataset_sha,
            "calibrated": False,
            "runtime_output": "raw_score",
        },
        "class_mapping": class_mapping(labels),
        "detector": {},
        "lineage": {
            "source_manifest_sha256": ch_manifest_sha,
            "dataset_inventory_sha256s": [dataset_sha],
            "training_run_id": "ch-classifier-bootstrap-v9",
            "training_run_sha256": sha256(args.training_summary),
            "evaluation_report_sha256": evaluation_sha,
            "parity_report_sha256": parity_sha,
        },
        "licenses": [
            {"name": "ASTRA Swiss traffic-sign vector archive", "spdx": "NOASSERTION", "source": "https://www.astra.admin.ch/de/signale"},
            {"name": "Wikimedia Commons Swiss sign category used for research comparison", "spdx": "NOASSERTION", "source": "https://commons.wikimedia.org/wiki/Category:SVG_road_signs_in_Switzerland"},
            {"name": "Panoramax CH imagery and DE classifier initialization", "spdx": "NOASSERTION", "source": "local://youspeed-tsr-ch-panoramax-20260917"},
            {"name": "Ultralytics YOLO architecture and export tooling", "spdx": "AGPL-3.0-only", "source": "https://github.com/ultralytics/ultralytics/tree/v8.4.56"},
        ],
        "minimum_app_version": "1.1.0",
        "signature": None,
    }
    detector_source = load(ROOT / "android/app/src/main/assets/tsr/DE.panoramax-bootstrap.tsrmodelpack/manifest.json")["detector"]
    common["detector"] = json.loads(json.dumps(detector_source))
    common["lineage"]["dataset_inventory_sha256s"] = list(dict.fromkeys([
        dataset_sha, *[a["calibration_dataset_sha256"] for a in detector_source["artifacts"]],
    ]))
    common["detector"]["artifacts"] = [common["detector"]["artifacts"][0]]
    common["detector"]["artifacts"][0]["path"] = "yolo11n_panoramax_float16.tflite"
    common["detector"]["artifacts"][0]["platform"] = "android"
    ios = json.loads(json.dumps(common))
    ios["detector"]["artifacts"][0] = load(ROOT / "iphone/SpeedConsumerApp/TSRModelPacks/DE.panoramax-bootstrap.tsrmodelpack/manifest.json")["detector"]["artifacts"][0]
    ios["classifier"] = {
        "component_id": "panoramax-classify-ch-road-signs-ch-classifier-bootstrap-v9",
        "source_checkpoint": source_checkpoint,
        "artifacts": [{
            "platform": "ios", "minimum_runtime": "17.0", "format": "coreml", "precision": "float16",
            "input_shape": [1, 3, 224, 224], "output_schema": "vision_classifications_v1",
            "path": "classify_ch_road_signs.mlmodelc", "sha256": tree_sha256(coreml),
            "source_checkpoint_sha256": source_sha, "exporter": {"name": "ultralytics+coremltools", "version": "8.4.56+9.0", "configuration": "imgsz=224,batch=1,half=true,nms=false,device=cpu"},
            "calibration_dataset_sha256": dataset_sha, "parity": {"tolerance": 0.02, "measured_max_abs_difference": parity["coreml"]["max_abs_difference"], "passed": parity["coreml"]["passed"]},
        }],
    }
    android = json.loads(json.dumps(common))
    android["detector"]["artifacts"][0] = load(ROOT / "android/app/src/main/assets/tsr/DE.panoramax-bootstrap.tsrmodelpack/manifest.json")["detector"]["artifacts"][0]
    android["detector"]["artifacts"][0]["path"] = "yolo11n_panoramax_float16.tflite"
    android["detector"]["artifacts"][0]["platform"] = "android"
    android["classifier"] = {
        "component_id": ios["classifier"]["component_id"], "source_checkpoint": source_checkpoint,
        "artifacts": [{
            "platform": "android", "minimum_runtime": "34", "format": "tflite", "precision": "float16",
            "input_shape": [1, 224, 224, 3], "output_schema": "classification_probabilities_v1",
            "path": "classify_ch_road_signs_float16.tflite", "sha256": sha256(tflite),
            "source_checkpoint_sha256": source_sha, "exporter": {"name": "ultralytics+onnx2tf+litert", "version": "8.4.56+1.17.0+1.28.8+2.19.0+ai-edge-litert-1.3.0", "configuration": "imgsz=224,batch=1,half=true,nms=false,device=cpu"},
            "calibration_dataset_sha256": dataset_sha, "parity": {"tolerance": 0.02, "measured_max_abs_difference": parity["litert"]["max_abs_difference"], "passed": parity["litert"]["passed"]},
        }],
    }
    ios_pack = ROOT / "iphone/SpeedConsumerApp/TSRModelPacks/CH.panoramax-bootstrap.tsrmodelpack"
    android_pack = ROOT / "android/app/src/main/assets/tsr/CH.panoramax-bootstrap.tsrmodelpack"
    for pack in (ios_pack, android_pack):
        (pack / "provenance").mkdir(parents=True, exist_ok=True)
        shutil.copytree(detector_ios, pack / "yolo11n_panoramax.mlmodelc", dirs_exist_ok=True) if pack == ios_pack else shutil.copy2(detector_android, pack / "yolo11n_panoramax_float16.tflite")
        shutil.copytree(coreml, pack / "classify_ch_road_signs.mlmodelc", dirs_exist_ok=True) if pack == ios_pack else shutil.copy2(tflite, pack / "classify_ch_road_signs_float16.tflite")
        write(pack / "manifest.json", ios if pack == ios_pack else android)
        for name, path in (("ch-training-summary.json", args.training_summary), ("ch-real-evaluation.json", args.real_evaluation), ("ch-coreml-export-report.json", args.coreml_export), ("ch-tflite-export-report.json", args.litert_export), ("ch-coreml-parity.json", args.coreml_parity), ("ch-litert-parity.json", args.litert_parity), ("ch-mobile-parity.json", parity_path)):
            shutil.copy2(path, pack / "provenance" / name)
        (pack / "THIRD_PARTY_NOTICES.txt").write_text("CH evaluation-only pack.\n\nThe model and ASTRA-derived artwork are source-preparation artifacts. They are not cleared for production redistribution; do not enable CH runtime selection until the recorded source/licence review and device validation pass.\n", encoding="utf-8")
    signs = []
    for item in artworks:
        signs.append({
            "class_id": item["model_class_label"], "sign_code": item["sign_code"],
            "image_path": "tsr/sign-pictograms/" + item["png_path"],
            "label": {language: f"{item['sign_code']} — {item['model_class_label']}" for language in ("en", "de", "fr", "nl")},
            "display_eligible": True, "artwork_id": item["asset_id"],
            "source_provenance": {"source_archive": item["source_archive"], "source_member": item["source_member"], "source_member_sha256": item["source_member_sha256"], "license_status": item["license_status"], "original_sha256": item["original_sha256"], "png_sha256": item["png_sha256"]},
        })
    write(ROOT / "shared/tsr/prolix-ch-class-catalog-v1.json", {"schema_version": 1, "country": "CH", "classifier_checkpoint_sha256": source_sha, "class_labels": labels, "signs": signs, "policy": {"display_only": True, "numeric_speed_signs_are_schematic": True, "validated_passage_required_for_speed_context": True}, "provenance": {"national_artwork_manifest": "shared/tsr/sign-pictograms/national/CH/manifest.json", "national_selection": "shared/tsr/sign-pictograms/national/CH/selection.json", "classifier_checkpoint_revision": "ch-classifier-bootstrap-v9", "parity_report": str(parity_path.relative_to(ROOT))}})
    print(json.dumps({"country": "CH", "class_count": len(labels), "artwork_count": len(artworks), "ios_classifier_sha256": tree_sha256(coreml), "android_classifier_sha256": sha256(tflite), "parity_passed": parity["coreml"]["passed"] and parity["litert"]["passed"]}, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--artwork-manifest", type=Path, required=True)
    parser.add_argument("--artwork-root", type=Path, required=True)
    parser.add_argument("--training-summary", type=Path, required=True)
    parser.add_argument("--dataset-summary", type=Path, required=True)
    parser.add_argument("--real-evaluation", type=Path, required=True)
    parser.add_argument("--coreml-export", type=Path, required=True)
    parser.add_argument("--litert-export", type=Path, required=True)
    parser.add_argument("--coreml-compiled", type=Path, required=True)
    parser.add_argument("--tflite", type=Path, required=True)
    parser.add_argument("--coreml-parity", type=Path, required=True)
    parser.add_argument("--litert-parity", type=Path, required=True)
    build(parser.parse_args())


if __name__ == "__main__":
    main()
