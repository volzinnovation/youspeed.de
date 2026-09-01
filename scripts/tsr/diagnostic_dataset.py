#!/usr/bin/env python3
"""Validate consented TSR captures and materialize leakage-safe datasets.

The mobile apps write a diagnostic bundle only after the separate diagnostic
capture consent is enabled. This tool is deliberately independent of the model
framework: it verifies hashes and relational sign annotations, keeps every
drive/import group in one split, and emits proposal-detector plus crop-
classifier layouts that a training runner can consume.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Sequence


REVIEWED_STATUSES = {"accepted", "corrected", "negative"}
OBJECT_ROLES = {"primary_sign": 0, "supplementary_plate": 1}
RESTRICTION_KINDS = {
    "weather",
    "time_window",
    "days_of_week",
    "vehicle",
    "max_weight",
    "school",
    "resident",
    "exception",
    "distance",
    "direction",
    "extent",
    "text",
    "other",
    "unknown",
}
SAFE_CLASS_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


class DiagnosticBundleError(ValueError):
    """Raised when a bundle cannot safely enter training or evaluation."""


@dataclass(frozen=True)
class ValidatedBundle:
    root: Path
    manifest_path: Path
    manifest_sha256: str
    payload: dict[str, Any]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise DiagnosticBundleError(message)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_relative_path(root: Path, value: Any, field: str) -> Path:
    _require(isinstance(value, str) and value, f"{field} must be a non-empty relative path")
    relative = Path(value)
    _require(not relative.is_absolute(), f"{field} must be relative")
    _require(".." not in relative.parts, f"{field} cannot contain '..'")
    candidate = (root / relative).resolve()
    resolved_root = root.resolve()
    _require(candidate == resolved_root or resolved_root in candidate.parents, f"{field} escapes its bundle")
    return candidate


def _validate_rect(value: Any, field: str) -> None:
    _require(isinstance(value, dict), f"{field} must be an object")
    _require(set(value) == {"x", "y", "width", "height"}, f"{field} has unexpected fields")
    numbers = [value[key] for key in ("x", "y", "width", "height")]
    _require(all(isinstance(number, (int, float)) and math.isfinite(number) for number in numbers), f"{field} must be finite")
    x, y, width, height = (float(number) for number in numbers)
    _require(x >= 0 and y >= 0 and width > 0 and height > 0, f"{field} has invalid dimensions")
    _require(x + width <= 1.0000001 and y + height <= 1.0000001, f"{field} exceeds the normalized frame")


def _validate_capture_context(context: Any, field: str, *, require_complete: bool) -> None:
    _require(isinstance(context, dict), f"{field} must be an object")
    complete = context.get("road_context_complete") is True
    if require_complete:
        _require(complete, f"{field} must contain synchronized road context")
    if not complete:
        return

    way_id = context.get("way_id")
    _require(isinstance(way_id, str) and way_id.strip(), f"{field}.way_id is required")
    latitude = context.get("latitude")
    longitude = context.get("longitude")
    heading = context.get("heading_degrees")
    _require(isinstance(latitude, (int, float)) and -90 <= latitude <= 90, f"{field}.latitude is invalid")
    _require(isinstance(longitude, (int, float)) and -180 <= longitude <= 180, f"{field}.longitude is invalid")
    _require(isinstance(heading, (int, float)) and 0 <= heading < 360, f"{field}.heading_degrees is invalid")
    _require(context.get("travel_direction") in {"forward", "reverse", "unknown"}, f"{field}.travel_direction is invalid")
    revision = context.get("map_context_revision")
    _require(isinstance(revision, int) and revision >= 0, f"{field}.map_context_revision is required")
    signature = context.get("map_source_signature")
    _require(isinstance(signature, str) and signature, f"{field}.map_source_signature is required")


def _validate_annotation(annotation: Any, field: str) -> None:
    _require(isinstance(annotation, dict), f"{field} must be an object")
    status = annotation.get("status")
    _require(status in {"unreviewed", "accepted", "corrected", "rejected", "negative"}, f"{field}.status is invalid")
    objects = annotation.get("objects")
    assemblies = annotation.get("assemblies")
    _require(isinstance(objects, list), f"{field}.objects must be an array")
    _require(isinstance(assemblies, list), f"{field}.assemblies must be an array")
    if status == "negative":
        _require(not objects and not assemblies, f"{field} negative samples cannot carry positive labels")
        return
    if status in {"accepted", "corrected"}:
        _require(bool(objects) and bool(assemblies), f"{field} reviewed positive samples need an assembly")

    objects_by_id: dict[str, dict[str, Any]] = {}
    for index, item in enumerate(objects):
        item_field = f"{field}.objects[{index}]"
        _require(isinstance(item, dict), f"{item_field} must be an object")
        object_id = item.get("object_id")
        _require(isinstance(object_id, str) and object_id, f"{item_field}.object_id is required")
        _require(object_id not in objects_by_id, f"{field} contains duplicate object_id {object_id}")
        role = item.get("role")
        _require(role in OBJECT_ROLES, f"{item_field}.role is invalid")
        class_id = item.get("class_id")
        _require(isinstance(class_id, str) and SAFE_CLASS_ID.fullmatch(class_id) is not None, f"{item_field}.class_id is unsafe")
        assembly_id = item.get("assembly_id")
        _require(isinstance(assembly_id, str) and assembly_id, f"{item_field}.assembly_id is required")
        _validate_rect(item.get("bounding_box"), f"{item_field}.bounding_box")
        if role == "primary_sign":
            semantic = item.get("primary_semantic")
            _require(isinstance(semantic, dict) and isinstance(semantic.get("kind"), str), f"{item_field}.primary_semantic is required")
            _require(item.get("restriction") is None, f"{item_field} primary signs cannot carry a plate restriction")
        else:
            parent_id = item.get("parent_object_id")
            _require(isinstance(parent_id, str) and parent_id, f"{item_field}.parent_object_id is required")
            restriction = item.get("restriction")
            _require(isinstance(restriction, dict), f"{item_field}.restriction is required")
            _require(restriction.get("kind") in RESTRICTION_KINDS, f"{item_field}.restriction.kind is invalid")
            _require(isinstance(restriction.get("normalized_value"), str) and restriction["normalized_value"], f"{item_field}.restriction.normalized_value is required")
            _require(item.get("primary_semantic") is None, f"{item_field} supplementary plates cannot carry a primary semantic")
        objects_by_id[object_id] = item

    for object_id, item in objects_by_id.items():
        if item["role"] != "supplementary_plate":
            continue
        parent = objects_by_id.get(item["parent_object_id"])
        _require(parent is not None and parent.get("role") == "primary_sign", f"{field} plate {object_id} must reference a primary sign")
        _require(parent.get("assembly_id") == item.get("assembly_id"), f"{field} plate {object_id} crosses assemblies")

    assembly_ids: set[str] = set()
    for index, assembly in enumerate(assemblies):
        assembly_field = f"{field}.assemblies[{index}]"
        _require(isinstance(assembly, dict), f"{assembly_field} must be an object")
        assembly_id = assembly.get("assembly_id")
        _require(isinstance(assembly_id, str) and assembly_id, f"{assembly_field}.assembly_id is required")
        _require(assembly_id not in assembly_ids, f"{field} contains duplicate assembly_id {assembly_id}")
        assembly_ids.add(assembly_id)
        _validate_rect(assembly.get("bounding_box"), f"{assembly_field}.bounding_box")
        primary_id = assembly.get("primary_object_id")
        primary = objects_by_id.get(primary_id)
        _require(primary is not None and primary.get("role") == "primary_sign", f"{assembly_field} must reference a primary sign")
        _require(primary.get("assembly_id") == assembly_id, f"{assembly_field} primary belongs to another assembly")
        supplementary_ids = assembly.get("supplementary_object_ids")
        _require(isinstance(supplementary_ids, list), f"{assembly_field}.supplementary_object_ids must be an array")
        _require(len(supplementary_ids) == len(set(supplementary_ids)), f"{assembly_field} repeats a supplementary object")
        for supplementary_id in supplementary_ids:
            plate = objects_by_id.get(supplementary_id)
            _require(plate is not None and plate.get("role") == "supplementary_plate", f"{assembly_field} references a non-plate")
            _require(plate.get("assembly_id") == assembly_id, f"{assembly_field} plate belongs to another assembly")
            _require(plate.get("parent_object_id") == primary_id, f"{assembly_field} plate references another primary")
        condition_state = assembly.get("condition_state")
        expected_states = {"none"} if not supplementary_ids else {"resolved", "unresolved"}
        _require(condition_state in expected_states, f"{assembly_field}.condition_state does not match its plates")


def validate_bundle(path: Path | str, *, verify_assets: bool = True, require_export_approval: bool = False) -> ValidatedBundle:
    root = Path(path).expanduser().resolve()
    manifest_path = root / "manifest.json" if root.is_dir() else root
    root = manifest_path.parent.resolve()
    _require(manifest_path.is_file(), f"missing diagnostic manifest: {manifest_path}")
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DiagnosticBundleError(f"cannot read {manifest_path}: {error}") from error
    _require(isinstance(payload, dict), "diagnostic manifest must be an object")
    _require(payload.get("schema_version") == 1, "unsupported diagnostic schema")
    for key in ("bundle_id", "capture_group_id"):
        _require(isinstance(payload.get(key), str) and payload[key], f"{key} is required")

    consent = payload.get("consent")
    _require(isinstance(consent, dict), "consent is required")
    _require(consent.get("scope") == "tsr_diagnostic_dataset", "diagnostic consent scope is invalid")
    if require_export_approval:
        _require(consent.get("export_approved") is True, "diagnostic export is not approved")

    privacy = payload.get("privacy")
    _require(isinstance(privacy, dict), "privacy declaration is required")
    _require(privacy.get("raw_dashcam_video_included") is False, "raw Dashcam video cannot enter a diagnostic bundle")
    _require(privacy.get("direct_device_identifier_included") is False, "direct device identifiers cannot enter a diagnostic bundle")
    if require_export_approval and privacy.get("full_frame_retention") is True:
        _require(privacy.get("redaction_state") == "verified", "exported full frames require verified redaction")

    samples = payload.get("samples")
    _require(isinstance(samples, list) and samples, "samples must be a non-empty array")
    sample_ids: set[str] = set()
    for sample_index, sample in enumerate(samples):
        sample_field = f"samples[{sample_index}]"
        _require(isinstance(sample, dict), f"{sample_field} must be an object")
        sample_id = sample.get("sample_id")
        _require(isinstance(sample_id, str) and sample_id, f"{sample_field}.sample_id is required")
        _require(sample_id not in sample_ids, f"duplicate sample_id {sample_id}")
        sample_ids.add(sample_id)
        source = sample.get("source")
        trigger = sample.get("trigger")
        require_road_context = source == "live_shared_frame" and trigger in {"candidate", "uncertainty"}
        _validate_capture_context(sample.get("capture_context"), f"{sample_field}.capture_context", require_complete=require_road_context)

        assets = sample.get("assets")
        _require(isinstance(assets, list) and assets, f"{sample_field}.assets must be non-empty")
        asset_paths: set[str] = set()
        for asset_index, asset in enumerate(assets):
            asset_field = f"{sample_field}.assets[{asset_index}]"
            _require(isinstance(asset, dict), f"{asset_field} must be an object")
            asset_path_value = asset.get("path")
            asset_path = _safe_relative_path(root, asset_path_value, f"{asset_field}.path")
            _require(asset_path_value not in asset_paths, f"{sample_field} repeats asset path {asset_path_value}")
            asset_paths.add(asset_path_value)
            expected_hash = asset.get("sha256")
            _require(isinstance(expected_hash, str) and re.fullmatch(r"[a-f0-9]{64}", expected_hash) is not None, f"{asset_field}.sha256 is invalid")
            _require(isinstance(asset.get("width"), int) and asset["width"] > 0, f"{asset_field}.width is invalid")
            _require(isinstance(asset.get("height"), int) and asset["height"] > 0, f"{asset_field}.height is invalid")
            if asset.get("source_bounding_box") is not None:
                _validate_rect(asset["source_bounding_box"], f"{asset_field}.source_bounding_box")
            if verify_assets:
                _require(asset_path.is_file(), f"missing asset {asset_path_value}")
                _require(_sha256(asset_path) == expected_hash, f"asset hash mismatch for {asset_path_value}")

        predictions = sample.get("predictions")
        _require(isinstance(predictions, list), f"{sample_field}.predictions must be an array")
        for prediction_index, prediction in enumerate(predictions):
            prediction_field = f"{sample_field}.predictions[{prediction_index}]"
            _require(isinstance(prediction, dict), f"{prediction_field} must be an object")
            _require(prediction.get("role") in OBJECT_ROLES, f"{prediction_field}.role is invalid")
            _validate_rect(prediction.get("bounding_box"), f"{prediction_field}.bounding_box")
        _validate_annotation(sample.get("annotation"), f"{sample_field}.annotation")

    return ValidatedBundle(
        root=root,
        manifest_path=manifest_path,
        manifest_sha256=_sha256(manifest_path),
        payload=payload,
    )


def split_for_group(
    capture_group_id: str,
    *,
    seed: str,
    train_fraction: float = 0.8,
    validation_fraction: float = 0.1,
) -> str:
    _require(0 < train_fraction < 1, "train fraction must be between zero and one")
    _require(0 <= validation_fraction < 1, "validation fraction must be between zero and one")
    _require(train_fraction + validation_fraction < 1, "test fraction must be positive")
    value = int.from_bytes(hashlib.sha256(f"{seed}\0{capture_group_id}".encode("utf-8")).digest()[:8], "big")
    bucket = value / float(2**64)
    if bucket < train_fraction:
        return "train"
    if bucket < train_fraction + validation_fraction:
        return "validation"
    return "test"


def _safe_name(value: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-.")
    return normalized or hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _copy_asset(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _yolo_line(role: str, rect: dict[str, Any]) -> str:
    class_index = OBJECT_ROLES[role]
    center_x = float(rect["x"]) + float(rect["width"]) / 2
    center_y = float(rect["y"]) + float(rect["height"]) / 2
    return f"{class_index} {center_x:.8f} {center_y:.8f} {float(rect['width']):.8f} {float(rect['height']):.8f}"


def materialize_dataset(
    bundles: Sequence[ValidatedBundle],
    output: Path | str,
    *,
    seed: str,
) -> dict[str, Any]:
    output_root = Path(output).expanduser().resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    index_samples: list[dict[str, Any]] = []
    seen_sample_keys: set[tuple[str, str]] = set()
    split_groups: dict[str, set[str]] = {"train": set(), "validation": set(), "test": set()}

    for bundle in sorted(bundles, key=lambda item: item.payload["bundle_id"]):
        bundle_id = bundle.payload["bundle_id"]
        group_id = bundle.payload["capture_group_id"]
        split = split_for_group(group_id, seed=seed)
        split_groups[split].add(group_id)
        for sample in sorted(bundle.payload["samples"], key=lambda item: item["sample_id"]):
            annotation = sample["annotation"]
            if annotation["status"] not in REVIEWED_STATUSES:
                continue
            sample_key = (bundle_id, sample["sample_id"])
            _require(sample_key not in seen_sample_keys, f"duplicate bundle/sample pair {sample_key}")
            seen_sample_keys.add(sample_key)
            prefix = f"{_safe_name(bundle_id)}-{_safe_name(sample['sample_id'])}"
            assets = sample["assets"]
            full_frame = next((asset for asset in assets if asset["role"] == "full_frame"), None)
            detector_image: str | None = None
            detector_label: str | None = None
            if full_frame is not None:
                source = _safe_relative_path(bundle.root, full_frame["path"], "asset.path")
                extension = source.suffix.lower() or ".image"
                image_destination = output_root / "detector" / "images" / split / f"{prefix}{extension}"
                label_destination = output_root / "detector" / "labels" / split / f"{prefix}.txt"
                _copy_asset(source, image_destination)
                label_destination.parent.mkdir(parents=True, exist_ok=True)
                lines = [
                    _yolo_line(item["role"], item["bounding_box"])
                    for item in annotation["objects"]
                ]
                label_destination.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
                detector_image = str(image_destination.relative_to(output_root))
                detector_label = str(label_destination.relative_to(output_root))

            objects_by_id = {item["object_id"]: item for item in annotation["objects"]}
            classifier_assets: list[dict[str, str]] = []
            for asset in assets:
                object_id = asset.get("object_id")
                if asset["role"] not in {"primary_crop", "supplementary_crop"} or object_id not in objects_by_id:
                    continue
                item = objects_by_id[object_id]
                source = _safe_relative_path(bundle.root, asset["path"], "asset.path")
                extension = source.suffix.lower() or ".image"
                role_directory = "primary" if item["role"] == "primary_sign" else "supplementary"
                class_id = item["class_id"]
                destination = output_root / "classifier" / role_directory / split / class_id / f"{prefix}-{_safe_name(object_id)}{extension}"
                _copy_asset(source, destination)
                classifier_assets.append({
                    "object_id": object_id,
                    "class_id": class_id,
                    "path": str(destination.relative_to(output_root)),
                })

            index_samples.append({
                "bundle_id": bundle_id,
                "bundle_manifest_sha256": bundle.manifest_sha256,
                "capture_group_id": group_id,
                "sample_id": sample["sample_id"],
                "split": split,
                "source": sample["source"],
                "trigger": sample["trigger"],
                "annotation_status": annotation["status"],
                "detector_image": detector_image,
                "detector_label": detector_label,
                "classifier_assets": classifier_assets,
                "road_context": sample["capture_context"],
            })

    index = {
        "schema_version": 1,
        "split_strategy": "sha256_capture_group_v1",
        "split_seed": seed,
        "role_classes": ["primary_sign", "supplementary_plate"],
        "bundle_count": len(bundles),
        "sample_count": len(index_samples),
        "groups_by_split": {key: sorted(value) for key, value in split_groups.items()},
        "samples": index_samples,
    }
    (output_root / "dataset-index.json").write_text(
        json.dumps(index, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output_root / "detector" / "data.yaml").parent.mkdir(parents=True, exist_ok=True)
    (output_root / "detector" / "data.yaml").write_text(
        "path: .\ntrain: images/train\nval: images/validation\ntest: images/test\nnames:\n  0: primary_sign\n  1: supplementary_plate\n",
        encoding="utf-8",
    )
    return index


def _validated_bundles(paths: Iterable[str], *, require_export_approval: bool) -> list[ValidatedBundle]:
    return [
        validate_bundle(path, verify_assets=True, require_export_approval=require_export_approval)
        for path in paths
    ]


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="validate manifests and asset hashes")
    validate_parser.add_argument("bundles", nargs="+", help="bundle directories or manifest paths")
    validate_parser.add_argument("--for-export", action="store_true", help="also require export approval and redaction")

    build_parser = subparsers.add_parser("build", help="build detector/classifier datasets")
    build_parser.add_argument("--output", required=True, help="generated dataset directory")
    build_parser.add_argument("--seed", required=True, help="versioned split seed")
    build_parser.add_argument("bundles", nargs="+", help="approved bundle directories or manifest paths")

    args = parser.parse_args(argv)
    if args.command == "validate":
        bundles = _validated_bundles(args.bundles, require_export_approval=args.for_export)
        print(json.dumps({"valid": True, "bundle_count": len(bundles)}, sort_keys=True))
        return 0

    bundles = _validated_bundles(args.bundles, require_export_approval=True)
    index = materialize_dataset(bundles, args.output, seed=args.seed)
    print(json.dumps({"built": True, "sample_count": index["sample_count"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
