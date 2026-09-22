#!/usr/bin/env python3
"""Build reproducible foreign TSR manifests, catalogs and parity evidence.

The source checkpoints and national artwork remain outside the app's runtime
bundle. This generator binds their immutable revisions to the copied mobile
artifacts and records the exact preprocessing/parity contract used by the
German two-stage runtime.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.tsr.mapping_review import semantic as reviewed_semantic, mappings as reviewed_mappings, reconcile_catalog
COUNTRIES = ("FR", "NL", "BE")


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write(path: Path, payload: Any) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    raw = (json.dumps(payload, indent=2, ensure_ascii=False) + "\n").encode("utf-8")
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_sha256(path: Path) -> str:
    """Hash a bundle deterministically, including relative names and bytes."""
    if path.is_file():
        return sha256(path)
    digest = hashlib.sha256()
    for child in sorted(p for p in path.rglob("*") if p.is_file()):
        relative = child.relative_to(path).as_posix().encode("utf-8")
        digest.update(relative)
        digest.update(b"\0")
        with child.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        digest.update(b"\0")
    return digest.hexdigest()


def ordered_names(class_names: dict[str, str]) -> list[str]:
    return [class_names[key] for key in sorted(class_names, key=lambda value: int(value))]


def semantic(semantic_id: str) -> dict[str, Any]:
    return reviewed_semantic(semantic_id, "FR" if re.fullmatch(r"[A-Z]+[0-9]+(?:-[0-9]+)?", semantic_id) else "")


def add_schematic_speed_mappings(
    mappings: list[dict[str, Any]], names: list[str]
) -> None:
    """Numeric speed classes do not depend on the pictogram inventory."""
    present = {entry["class_id"] for entry in mappings}
    for name in names:
        if name in present or not re.fullmatch(r"(maxspeed|zone):[0-9]+(:end)?|B(?:14|33)-[0-9]+|B30|B51", name):
            continue
        meaning = semantic(name)
        if meaning["kind"] == "unknown":
            continue
        mappings.append({"class_id": name, "label": name, "semantic": meaning, "threshold": 0.70})
        present.add(name)


def runtime_class(entry: dict[str, Any], names: set[str]) -> str | None:
    source = entry.get("source_model_class")
    if source in names:
        return source
    candidates = [
        entry.get("semantic_id", ""),
        entry.get("semantic_id", "").replace("_", ":"),
        entry.get("semantic_id", "").replace("_", "-"),
        entry.get("sign_code", ""),
        entry.get("sign_code", "").replace("[", "-").replace("]", ""),
    ]
    aliases = {
        "built_up_area_start": "city:start",
        "built_up_area_end": "city:end",
        "motorway_start": "motorway:start",
        "motorway_end": "motorway:end",
        "trunk_start": "trunk:start",
        "trunk_end": "trunk:end",
    }
    candidates.append(aliases.get(entry.get("semantic_id", ""), ""))
    return next((candidate for candidate in candidates if candidate in names), None)


def label_for(class_id: str, sign_code: str, semantic_id: str) -> dict[str, str]:
    value = f"{sign_code} — {semantic_id.replace('_', ' ')}"
    return {"en": value, "de": value, "fr": value, "nl": value}


def parity_report(
    country: str,
    direct: dict[str, Any],
    coreml: dict[str, Any],
    litert: dict[str, Any],
    coreml_artifact_sha256: str,
    litert_artifact_sha256: str,
) -> dict[str, Any]:
    names = direct["class_names"]
    reference = direct["scores"]
    converted = [coreml["scores"][name] for name in names]
    differences = [abs(float(a) - float(b)) for a, b in zip(reference, converted)]
    coreml_passed = (
        coreml.get("top_class") == direct.get("top_class")
        and max(differences) <= 0.02
    )
    return {
        "schema_version": 1,
        "country": country,
        "scope": "fixed RGB crop; source PyTorch vs Core ML and ONNX vs LiteRT",
        "input": {
            "sha256": coreml["input_sha256"],
            "shape": [1, 224, 224, 3],
            "source_dtype": "uint8",
            "coreml_input": "RGB pixel buffer; Core ML graph scale 1/255",
            "litert_input": "RGB float32 tensor; runtime scale 1/255",
        },
        "source": {
            "format": "pytorch",
            "top_class": direct["top_class"],
            "top_score": direct["top_score"],
            "class_count": len(names),
        },
        "coreml": {
            "compute_units": coreml.get("compute_units", "all"),
            "artifact_sha256": coreml_artifact_sha256,
            "top_class": coreml["top_class"],
            "top_score": coreml["top_score"],
            "max_abs_difference": max(differences),
            "mean_abs_difference": sum(differences) / len(differences),
            "tolerance": 0.02,
            "passed": coreml_passed,
        },
        "litert": {
            "artifact_sha256": litert_artifact_sha256,
            "reference_format": "onnx",
            "top1_reference": litert["top1_reference"],
            "top1_converted": litert["top1_converted"],
            "max_abs_difference": litert["max_abs_difference"],
            "mean_abs_difference": litert["mean_abs_difference"],
            "tolerance": litert["tolerance"],
            "passed": litert["passed"],
        },
        "passed": bool(coreml_passed and litert["passed"]),
        "device_execution": {
            "ios": "not measured on attached device",
            "android": "not measured on attached device",
            "runtime_acceleration_contract": {
                "ios": "MLComputeUnits.all",
                "android": "LiteRT GPU delegate with CPU fallback after GPU failure",
            },
        },
    }


def licenses(country: str, revision: str) -> list[dict[str, str]]:
    dataset_spdx = "Etalab-2.0" if country == "FR" else "CC-BY-SA-4.0"
    dataset_url = {
        "FR": "https://huggingface.co/datasets/Panoramax/classified_fr_road_signs",
        "NL": "https://huggingface.co/datasets/Panoramax/classified_nl_road_signs",
        "BE": "https://huggingface.co/datasets/Panoramax/classified_be_road_signs",
    }[country]
    model_url = f"https://huggingface.co/Panoramax/classify_{country.lower()}_road_signs/tree/{revision}"
    return [
        {"name": "sgblur Panoramax detector", "spdx": "MIT", "source": "https://github.com/cquest/sgblur/tree/169451970702aca0dde9ff3106dba0f67e0b88a8"},
        {"name": f"Panoramax {country} road-sign classifier", "spdx": "Etalab-2.0", "source": model_url},
        {"name": f"Panoramax {country} classified road-sign dataset", "spdx": dataset_spdx, "source": dataset_url},
        {"name": "Wikimedia Commons national sign renditions", "spdx": "CC-BY-SA-4.0", "source": f"https://commons.wikimedia.org/wiki/Commons:Reusing_content_outside_Wikimedia"},
        {"name": "Ultralytics YOLO architecture and export tooling", "spdx": "AGPL-3.0-only", "source": "https://github.com/ultralytics/ultralytics/tree/v8.4.56"},
        {"name": "Core ML Tools 9.0 conversion tooling", "spdx": "BSD-3-Clause", "source": "https://github.com/apple/coremltools/tree/9.0"},
        {"name": "PyTorch conversion dependency", "spdx": "BSD-3-Clause", "source": "https://github.com/pytorch/pytorch/tree/v2.7.0"},
        {"name": "ONNX and onnx2tf conversion tooling", "spdx": "Apache-2.0", "source": "https://github.com/MPolaris/onnx2tf/tree/1.28.8"},
        {"name": "TensorFlow and LiteRT conversion/runtime tooling", "spdx": "Apache-2.0", "source": "https://github.com/tensorflow/tensorflow/tree/v2.19.0"},
    ]


def build(country: str, args: argparse.Namespace) -> None:
    lower = country.lower()
    readiness = load(ROOT / "shared/tsr/foreign-runtime-readiness-v1.json")
    item = next(value for value in readiness["countries"] if value["country"] == country)
    source = item["classifier_source"]
    calibration = load(ROOT / item["calibration"]["evidence_path"])
    calibration_sha = sha256(ROOT / item["calibration"]["evidence_path"])
    national = load(ROOT / f"shared/tsr/sign-pictograms/national/{country}/manifest.json")
    selection_path = ROOT / f"shared/tsr/sign-pictograms/national/{country}/selection.json"
    selection = load(selection_path)
    coreml_export = load(args.coreml_export)
    litert_export = load(args.litert_export)
    direct = load(args.direct)
    coreml = load(args.coreml_parity)
    litert = load(args.litert_parity)
    names = ordered_names(coreml_export["class_names"])
    name_set = set(names)

    by_artwork = {entry["asset_id"]: entry for entry in national["artworks"]}
    catalog_signs: list[dict[str, Any]] = []
    class_mappings: list[dict[str, Any]] = []
    seen_runtime: set[str] = set()
    for entry in selection["entries"]:
        mapped = runtime_class(entry, name_set)
        entry["runtime_model_class"] = mapped
        artwork = by_artwork[entry["artwork_id"]]
        if mapped is None:
            continue
        if mapped not in seen_runtime:
            seen_runtime.add(mapped)
            class_mappings.append({
                "class_id": mapped,
                "label": mapped,
                "semantic": reviewed_semantic(mapped, country),
                "threshold": 0.70,
            })
            catalog_signs.append({
                "class_id": mapped,
                "sign_code": entry["sign_code"],
                # Keep the national/ prefix: both Android's shared asset
                # source set and the iOS folder resource mirror the shared
                # repository path exactly.
                "image_path": "tsr/sign-pictograms/" + artwork["png_path"],
                "label": label_for(mapped, entry["sign_code"], entry["semantic_id"]),
                "display_eligible": True,
                "artwork_id": entry["artwork_id"],
                "source_provenance": {
                    "commons_title": artwork["commons_title"],
                    "license": artwork["license"],
                    "license_source_url": artwork["license_source_url"],
                    "original_sha256": artwork["original_sha256"],
                    "png_sha256": artwork["png_sha256"],
                },
            })
    class_mappings = reviewed_mappings(names, country, class_mappings)
    write(selection_path, selection)

    ios_pack = ROOT / f"iphone/SpeedConsumerApp/TSRModelPacks/{country}.panoramax-bootstrap.tsrmodelpack"
    android_pack = ROOT / f"android/app/src/main/assets/tsr/{country}.panoramax-bootstrap.tsrmodelpack"
    ios_classifier = ios_pack / f"classify_{lower}_road_signs.mlmodelc"
    android_classifier = android_pack / f"classify_{lower}_road_signs_float16.tflite"
    ios_hash = tree_sha256(ios_classifier)
    android_hash = sha256(android_classifier)
    parity = parity_report(country, direct, coreml, litert, ios_hash, android_hash)
    parity_path = ROOT / f"shared/tsr/foreign-calibration/{country}-mobile-parity-v1.json"
    parity_sha = write(parity_path, parity)

    german_ios = load(ROOT / "iphone/SpeedConsumerApp/TSRModelPacks/DE.panoramax-bootstrap.tsrmodelpack/manifest.json")
    german_android = load(ROOT / "android/app/src/main/assets/tsr/DE.panoramax-bootstrap.tsrmodelpack/manifest.json")
    detector_ios = german_ios["detector"]["artifacts"][0].copy()
    detector_android = german_android["detector"]["artifacts"][0].copy()
    for artifact in (detector_ios, detector_android):
        artifact["calibration_dataset_sha256"] = calibration["dataset"]["inventory_sha256"]

    common = {
        "schema_version": 1,
        "pack_id": f"{lower}-panoramax-bootstrap-evaluation-v1",
        "countries": [country],
        "pipeline": "proposal_classification",
        "taxonomy_version": "tsr-semantic-v1",
        "preprocessing": german_ios["preprocessing"],
        "thresholds": german_ios["thresholds"],
        "calibration": {
            "kind": "none",
            "revision": calibration["calibration_id"],
            "dataset_sha256": calibration["dataset"]["inventory_sha256"],
            "calibrated": False,
            "runtime_output": "raw_score",
        },
        "class_mapping": class_mappings,
        "lineage": {
            "source_manifest_sha256": sha256(ROOT / f"shared/tsr/sign-pictograms/national/{country}/manifest.json"),
            "dataset_inventory_sha256s": [calibration["dataset"]["inventory_sha256"]],
            "training_run_id": f"panoramax-{lower}-mobile-export-2026-09-16",
            "training_run_sha256": hashlib.sha256(f"{country}:{source['revision']}:{source['sha256']}".encode()).hexdigest(),
            "evaluation_report_sha256": calibration_sha,
            "parity_report_sha256": parity_sha,
        },
        "licenses": licenses(country, source["revision"]),
        "minimum_app_version": "1.1.0",
        "signature": None,
    }
    ios = dict(common)
    ios["detector"] = {**german_ios["detector"], "artifacts": [detector_ios]}
    ios["classifier"] = {
        "component_id": f"panoramax-classify-{lower}-road-signs-{source['revision'][:16]}",
        "source_checkpoint": {
            "uri": source["uri"].replace("/resolve/", "/blob/"),
            "revision": source["revision"],
            "sha256": source["sha256"],
        },
        "artifacts": [{
            "platform": "ios",
            "minimum_runtime": "17.0",
            "format": "coreml",
            "precision": "float16",
            "input_shape": [1, 3, 224, 224],
            "output_schema": "vision_classifications_v1",
            "path": ios_classifier.name,
            "sha256": ios_hash,
            "source_checkpoint_sha256": source["sha256"],
            "exporter": {
                "name": "ultralytics+coremltools",
                "version": f"{coreml_export['exporter']['ultralytics']}+{coreml_export['exporter']['torch']}+coremltools-9.0",
                "configuration": coreml_export["exporter"]["configuration"],
            },
            "calibration_dataset_sha256": calibration["dataset"]["inventory_sha256"],
            "parity": {
                "tolerance": parity["coreml"]["tolerance"],
                "measured_max_abs_difference": parity["coreml"]["max_abs_difference"],
                "passed": parity["coreml"]["passed"],
            },
        }],
    }
    android = dict(common)
    android["detector"] = {**german_android["detector"], "artifacts": [detector_android]}
    android["classifier"] = {
        **ios["classifier"],
        "artifacts": [{
            "platform": "android",
            "minimum_runtime": "34",
            "format": "tflite",
            "precision": "float16",
            "input_shape": [1, 224, 224, 3],
            "output_schema": "classification_probabilities_v1",
            "path": android_classifier.name,
            "sha256": android_hash,
            "source_checkpoint_sha256": source["sha256"],
            "exporter": {
                "name": "ultralytics+onnx2tf+litert",
                "version": "8.4.56+1.17.0+1.28.8+2.19.0+ai-edge-litert-1.3.0",
                "configuration": litert_export["exporter"]["configuration"],
            },
            "calibration_dataset_sha256": calibration["dataset"]["inventory_sha256"],
            "parity": {
                "tolerance": parity["litert"]["tolerance"],
                "measured_max_abs_difference": parity["litert"]["max_abs_difference"],
                "passed": parity["litert"]["passed"],
            },
        }],
    }
    write(ios_pack / "manifest.json", ios)
    write(android_pack / "manifest.json", android)

    catalog = {
        "schema_version": 1,
        "country": country,
        "classifier_checkpoint_sha256": source["sha256"],
        "class_labels": names,
        "signs": catalog_signs,
        "policy": {
            "display_only": True,
            "numeric_speed_signs_are_schematic": True,
            "validated_passage_required_for_speed_context": True,
        },
        "provenance": {
            "national_artwork_manifest": f"shared/tsr/sign-pictograms/national/{country}/manifest.json",
            "national_selection": f"shared/tsr/sign-pictograms/national/{country}/selection.json",
            "classifier_checkpoint_revision": source["revision"],
            "parity_report": str(parity_path.relative_to(ROOT)),
        },
    }
    catalog_name = f"prolix-{lower}-class-catalog-v1.json"
    write(ROOT / "shared/tsr" / catalog_name, reconcile_catalog(catalog))
    # Android's main asset source set already includes ../../shared, so a
    # second copied catalog would make Gradle fail with duplicate resources.

    for pack in (ios_pack, android_pack):
        shutil.copy2(args.coreml_export, pack / "provenance" / f"{lower}-coreml-export-report.json")
        shutil.copy2(args.litert_export, pack / "provenance" / f"{lower}-tflite-export-report.json")
        shutil.copy2(args.direct, pack / "provenance" / f"{lower}-pytorch27-direct-parity.json")
        shutil.copy2(args.coreml_parity, pack / "provenance" / f"{lower}-coreml-all.json")
        shutil.copy2(args.litert_parity, pack / "provenance" / f"{lower}-onnx-litert-parity.json")
        source_record = {
            "country": country,
            "classifier": source,
            "dataset": calibration["dataset"],
            "national_artwork_manifest": f"shared/tsr/sign-pictograms/national/{country}/manifest.json",
            "coreml_artifact_sha256": ios_hash,
            "litert_artifact_sha256": android_hash,
            "mobile_parity_report_sha256": parity_sha,
            "runtime_acceleration": {
                "ios": "MLComputeUnits.all",
                "android": "LiteRT GPU delegate with CPU fallback after GPU failure",
            },
        }
        write(pack / "provenance" / "source-checkpoints.json", source_record)
        notice = (ROOT / "android/app/src/main/assets/tsr/DE.panoramax-bootstrap.tsrmodelpack/THIRD_PARTY_NOTICES.txt").read_text(encoding="utf-8")
        notice += f"\n\n================================================================================\n\nForeign {country} evaluation pack additions\n\n"
        notice += f"Classifier checkpoint: {source['uri']}\nRevision: {source['revision']}\nLicense: Etalab-2.0 (see the source model card and manifest.json).\n"
        notice += f"Calibration/data lineage: {dataset_license_line(country)}\n"
        notice += f"National artwork: shared/tsr/sign-pictograms/national/{country}/manifest.json; every selected SVG/PNG retains its Commons title, revision/source URL, declared license, SHA-256 and rasterization record.\n"
        notice += "The model files are evaluation artifacts. The runtime manifests remain unsigned until legal/action review and attached-device parity are complete.\n"
        (pack / "THIRD_PARTY_NOTICES.txt").write_text(notice, encoding="utf-8")

    print(json.dumps({
        "country": country,
        "class_count": len(names),
        "runtime_mapped_classes": len(class_mappings),
        "display_assets": len(catalog_signs),
        "coreml_sha256": ios_hash,
        "litert_sha256": android_hash,
        "parity_sha256": parity_sha,
        "parity_passed": parity["passed"],
    }, sort_keys=True))


def dataset_license_line(country: str) -> str:
    if country == "FR":
        return "Panoramax classified_fr_road_signs, Etalab Open Licence 2.0; commercial use approved by owner, attribution retained."
    return "Panoramax classified_{}_road_signs, CC BY-SA 4.0; commercial use approved by owner, attribution and share-alike retained.".format(country.lower())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--country", choices=COUNTRIES, required=True)
    parser.add_argument("--coreml-export", type=Path, required=True)
    parser.add_argument("--litert-export", type=Path, required=True)
    parser.add_argument("--direct", type=Path, required=True)
    parser.add_argument("--coreml-parity", type=Path, required=True)
    parser.add_argument("--litert-parity", type=Path, required=True)
    args = parser.parse_args()
    build(args.country, args)


if __name__ == "__main__":
    main()
