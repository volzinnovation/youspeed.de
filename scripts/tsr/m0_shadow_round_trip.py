#!/usr/bin/env python3
"""Verify the M0 two-stage shadow round trip on reviewed frames.

The harness intentionally separates three kinds of evidence:

* source evidence: exact image bytes and reviewed full-scene boxes;
* pipeline evidence: independent detector and classifier preprocessing;
* runtime evidence: schema-valid shadow events with immutable temporal history.

It does not run a detector or classifier.  A successful fixture verification is
therefore never reported as model accuracy or as an override-readiness gate.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import jsonschema
from PIL import Image

try:
    from scripts.tsr.preprocessing_v2 import (
        PreprocessedInput,
        preprocess_classifier,
        preprocess_detector,
    )
except ModuleNotFoundError:  # pragma: no cover - direct script execution
    from preprocessing_v2 import (  # type: ignore[no-redef]
        PreprocessedInput,
        preprocess_classifier,
        preprocess_detector,
    )


ROOT = Path(__file__).resolve().parents[2]
TSR_ROOT = ROOT / "shared" / "tsr"
DEFAULT_PACK = TSR_ROOT / "fixtures" / "de-yolox-mnv3-shadow-pack-v2.json"
DEFAULT_FIXTURE = TSR_ROOT / "fixtures" / "panoramax-m0-round-trip-v2.json"
DEFAULT_EVENTS = TSR_ROOT / "fixtures" / "recognition-events-v2.json"


class RoundTripV2Error(ValueError):
    """Raised when evidence violates the fail-closed M0 contract."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RoundTripV2Error(message)


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RoundTripV2Error(f"cannot read JSON {path}: {error}") from error


def _schema_validator(name: str) -> jsonschema.Draft202012Validator:
    schema = load_json(TSR_ROOT / name)
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(
        schema,
        format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
    )


def _validate_instance(
    validator: jsonschema.Draft202012Validator,
    instance: Any,
    label: str,
) -> None:
    errors = sorted(validator.iter_errors(instance), key=lambda item: list(item.path))
    if not errors:
        return
    first = errors[0]
    location = ".".join(str(item) for item in first.absolute_path) or "<root>"
    raise RoundTripV2Error(f"{label} fails schema at {location}: {first.message}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as source:
            for chunk in iter(lambda: source.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as error:
        raise RoundTripV2Error(f"cannot read image {path}: {error}") from error
    return digest.hexdigest()


def _timestamp(value: str) -> datetime:
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as error:
        raise RoundTripV2Error(f"invalid fixture timestamp: {value!r}") from error


def _normalized_box(box: Mapping[str, Any], width: int, height: int) -> dict[str, float]:
    return {
        "x": box["x"] / width,
        "y": box["y"] / height,
        "width": box["width"] / width,
        "height": box["height"] / height,
    }


def _iou(left: Mapping[str, Any], right: Mapping[str, Any]) -> float:
    x1 = max(float(left["x"]), float(right["x"]))
    y1 = max(float(left["y"]), float(right["y"]))
    x2 = min(float(left["x"] + left["width"]), float(right["x"] + right["width"]))
    y2 = min(float(left["y"] + left["height"]), float(right["y"] + right["height"]))
    intersection = max(0.0, x2 - x1) * max(0.0, y2 - y1)
    union = float(left["width"] * left["height"] + right["width"] * right["height"]) - intersection
    return intersection / union if union > 0 else 0.0


def validate_pack(pack: Mapping[str, Any]) -> None:
    _validate_instance(_schema_validator("model-pack-v2.schema.json"), pack, "model pack")
    _require(pack["execution_policy"]["initial_mode"] == "shadow", "pack must start in shadow mode")
    _require(pack["execution_policy"]["override_eligible"] is False, "pack must forbid speed overrides")

    artifact_ids: set[str] = set()
    artifact_paths: set[str] = set()
    artifact_hashes: set[str] = set()
    for stage_name in ("detector", "classifier"):
        stage = pack["stages"][stage_name]
        expected_source = "full_frame" if stage_name == "detector" else "proposal_crop"
        _require(stage["preprocessing"]["source"] == expected_source, f"{stage_name} preprocessing source is wrong")
        _require(set(stage["artifacts"]) == {"checkpoint", "onnx", "coreml", "litert"}, f"{stage_name} lacks sibling artifacts")
        for role, artifact in stage["artifacts"].items():
            _require(artifact["role"] == role and artifact["format"] == role, f"{stage_name} {role} identity is incoherent")
            _require(artifact["artifact_id"] not in artifact_ids, "artifact IDs must be globally unique")
            _require(artifact["path"] not in artifact_paths, "artifact paths must be globally unique")
            _require(artifact["sha256"] not in artifact_hashes, "artifact hashes must be globally unique")
            artifact_ids.add(artifact["artifact_id"])
            artifact_paths.add(artifact["path"])
            artifact_hashes.add(artifact["sha256"])


def validate_fixture(fixture: Mapping[str, Any], pack: Mapping[str, Any]) -> dict[str, Any]:
    _require(fixture.get("fixture_schema_version") == 2, "fixture schema version must be 2")
    observations = fixture.get("observations")
    _require(isinstance(observations, list) and len(observations) == 2, "M0 fixture must have exactly two observations")
    hard, readable = observations
    _require(
        [hard.get("observation_id"), readable.get("observation_id")]
        == ["hard-preceding-frame", "later-readable-frame"],
        "M0 observations are missing or out of order",
    )
    _require(hard["neighbors"]["next_picture_id"] == readable["picture_id"], "hard frame does not link to the later frame")
    _require(readable["neighbors"]["previous_picture_id"] == hard["picture_id"], "later frame does not link to the hard frame")

    gap_ms = (_timestamp(readable["timestamp_utc"]) - _timestamp(hard["timestamp_utc"])).total_seconds() * 1000
    _require(gap_ms > 0, "observations must be chronological")
    _require(gap_ms <= pack["thresholds"]["confirmation_window_ms"], "real frame gap exceeds the pack association window")
    _require(pack["thresholds"]["stable_observation_hint_can_override_iou"] is True, "pack must allow the reviewed stable observation hint")
    _require(pack["thresholds"]["fallback_requires_unique_candidate"] is True, "association fallback must require a unique candidate")

    hard_review = hard["review"]
    readable_review = readable["review"]
    _require(hard_review["primary"]["semantic"]["value"] == 70, "hard frame must contain reviewed speed 70")
    _require(hard_review["supplementary_plate"]["present"] is True, "hard frame must retain the visible plate")
    _require(hard_review["supplementary_plate"]["readability"] == "unreadable", "hard plate must remain unreadable")
    _require(hard_review["supplementary_plate"]["restriction"] is None, "hard frame must never infer the 2 km restriction")
    restriction = readable_review["supplementary_plate"]["restriction"]
    _require(restriction["kind"] == "extent" and restriction["extent_m"] == 2000, "later frame must encode a 2 km extent")

    for observation in observations:
        asset = observation["hd_asset"]
        width, height = asset["width"], asset["height"]
        for label in ("primary", "supplementary_plate"):
            box = observation["review"][label]["bounding_box"]
            _require(box["width"] > 0 and box["height"] > 0, f"{observation['observation_id']} {label} box is empty")
            _require(box["x"] >= 0 and box["y"] >= 0, f"{observation['observation_id']} {label} box is negative")
            _require(box["x"] + box["width"] <= width and box["y"] + box["height"] <= height, f"{observation['observation_id']} {label} box exceeds the frame")
        expected = observation["review"]["expected_shadow"]
        road = expected["road_context"]
        _require(expected["override_eligible"] is False, "fixture must forbid overrides")
        _require(road["way_id"] == fixture["map_context_reference"]["way_id"], "fixture way ID is inconsistent")
        _require(road["travel_direction"] == "reverse", "fixture travel direction must be reverse")
        _require(math.isclose(road["latitude"], observation["coordinate"]["latitude"]), "fixture latitude is inconsistent")
        _require(math.isclose(road["longitude"], observation["coordinate"]["longitude"]), "fixture longitude is inconsistent")

    hard_box = _normalized_box(hard_review["primary"]["bounding_box"], hard["hd_asset"]["width"], hard["hd_asset"]["height"])
    readable_box = _normalized_box(readable_review["primary"]["bounding_box"], readable["hd_asset"]["width"], readable["hd_asset"]["height"])
    image_iou = _iou(hard_box, readable_box)
    _require(image_iou < pack["thresholds"]["minimum_track_iou"], "fixture no longer exercises non-IoU association")
    return {
        "frame_gap_ms": gap_ms,
        "cross_frame_image_iou": image_iou,
        "association_basis": "reviewed_stable_physical_sign_hint",
    }


def _events_list(raw: Any) -> list[Mapping[str, Any]]:
    if isinstance(raw, list):
        return raw
    if isinstance(raw, Mapping) and isinstance(raw.get("events"), list):
        return raw["events"]
    raise RoundTripV2Error("recognition event fixture must be an array or an events envelope")


def _assert_stage_identity(event: Mapping[str, Any], pack: Mapping[str, Any]) -> None:
    for stage_name in ("detector", "classifier"):
        stage = pack["stages"][stage_name]
        run = event["stage_runs"][stage_name]
        artifact = stage["artifacts"][run["artifact_format"]]
        for field in ("component_id",):
            _require(run[field] == stage[field], f"event {stage_name} {field} does not match pack")
        _require(run["artifact_id"] == artifact["artifact_id"], f"event {stage_name} artifact ID does not match pack")
        _require(run["artifact_sha256"] == artifact["sha256"], f"event {stage_name} artifact hash does not match pack")
        _require(run["preprocessing_version"] == stage["preprocessing"]["version"], f"event {stage_name} preprocessing does not match pack")
        _require(run["calibration_id"] == stage["calibration"]["calibration_id"], f"event {stage_name} calibration does not match pack")


def _assert_normalized_box(
    actual: Mapping[str, Any],
    reviewed_pixel_box: Mapping[str, Any],
    *,
    width: int,
    height: int,
    label: str,
) -> None:
    expected = _normalized_box(reviewed_pixel_box, width, height)
    _require(set(actual) == set(expected), f"{label} normalized box fields are invalid")
    for field, expected_value in expected.items():
        _require(
            math.isclose(float(actual[field]), expected_value, rel_tol=0, abs_tol=1e-10),
            f"{label} normalized box does not match the reviewed full-scene box",
        )


def validate_events(
    raw_events: Any,
    fixture: Mapping[str, Any],
    pack: Mapping[str, Any],
) -> list[Mapping[str, Any]]:
    events = _events_list(raw_events)
    _require(len(events) == 2, "M0 event fixture must have exactly two events")
    validator = _schema_validator("recognition-event-v2.schema.json")
    events_by_frame: dict[str, Mapping[str, Any]] = {}
    for index, event in enumerate(events):
        _validate_instance(validator, event, f"recognition event {index}")
        frame_id = event["frame"]["frame_id"]
        _require(frame_id not in events_by_frame, "event frame IDs must be unique")
        events_by_frame[frame_id] = event
        _require(event["execution_mode"] == "shadow", "v2 events must remain in shadow mode")
        _require(event["evidence_origin"] == "reviewed_expectation", "M0 oracle fixture events must be reviewed expectations")
        _require(event["override_eligible"] is False, "v2 events must never be override eligible")
        _require(event["override_disposition"] == "shadow_evidence_only", "v2 event override disposition is unsafe")
        _require(event["qa_disposition"] == "emit", "v2 event must be emitted to QA")
        _require(event["source"] == "panoramax_replay", "M0 oracle fixture events must be Panoramax replays")
        _assert_stage_identity(event, pack)
        for stage_name in ("detector", "classifier"):
            run = event["stage_runs"][stage_name]
            _require(run["invoked"] is False and run["latency_ms"] == 0, "reviewed expectation stages must be uninvoked with zero latency")

    observations = fixture["observations"]
    _require(set(events_by_frame) == {item["picture_id"] for item in observations}, "events do not cover the exact M0 frames")
    hard = events_by_frame[observations[0]["picture_id"]]
    readable = events_by_frame[observations[1]["picture_id"]]
    hard_assembly = hard["assemblies"][0]
    readable_assembly = readable["assemblies"][0]
    _require(hard["state"] == "provisional", "hard frame must remain provisional after one observation")
    _require(readable["state"] == "confirmed", "later frame must confirm the two-frame track")
    _require(hard_assembly["physical_sign_track_id"] == readable_assembly["physical_sign_track_id"] == fixture["physical_sign_id"], "events do not use the reviewed physical-sign track")
    _require(hard_assembly["primary"]["semantic"] == {"kind": "maximum_speed", "value": 70, "unit": "km/h"}, "hard event must recognize speed 70")

    hard_plate = hard_assembly["supplementary_plates"][0]
    _require(hard_plate["readability"] == "unreadable", "hard event plate must be unreadable")
    _require(hard_plate["class_id"] is None and hard_plate["restriction"] is None, "hard event must not infer plate semantics")
    _require(hard_assembly["condition_state"] == "unresolved", "hard event condition must remain unresolved")
    _require(hard_assembly["temporal_evidence"]["evidence_frame_count"] == 1, "hard event cannot claim later evidence")
    _require(hard_assembly["temporal_evidence"]["prior_event_id"] is None, "hard event cannot refer to a future event")

    readable_plate = readable_assembly["supplementary_plates"][0]
    _require(readable_plate["readability"] == "readable", "later event plate must be readable")
    _require(readable_plate["restriction"]["kind"] == "extent" and readable_plate["restriction"]["extent_m"] == 2000, "later event must resolve the 2 km extent")
    _require(readable_assembly["condition_state"] == "resolved", "later event condition must be resolved")
    _require(readable_assembly["temporal_evidence"]["evidence_frame_count"] == 2, "later event must cite two frames")
    _require(readable_assembly["temporal_evidence"]["prior_event_id"] == hard["event_id"], "later event must reference the hard event")
    _require(readable_assembly["temporal_evidence"]["restriction_transition"] == "upgraded_from_later_readable_evidence", "later event must name the temporal upgrade")

    for observation in observations:
        event = events_by_frame[observation["picture_id"]]
        assembly = event["assemblies"][0]
        reviewed = observation["review"]
        width = observation["hd_asset"]["width"]
        height = observation["hd_asset"]["height"]
        _require(event["frame"]["timestamp_utc"] == observation["timestamp_utc"], "event timestamp is not frame-time evidence")
        _require(event["frame"]["width"] == width and event["frame"]["height"] == height, "event dimensions do not match the reviewed source")
        _require(event["road_context"] == observation["review"]["expected_shadow"]["road_context"], "event road context is not bound to its frame")
        _assert_normalized_box(
            assembly["primary"]["bounding_box"],
            reviewed["primary"]["bounding_box"],
            width=width,
            height=height,
            label=f"{observation['observation_id']} primary",
        )
        _assert_normalized_box(
            assembly["supplementary_plates"][0]["bounding_box"],
            reviewed["supplementary_plate"]["bounding_box"],
            width=width,
            height=height,
            label=f"{observation['observation_id']} supplementary plate",
        )
        _require(assembly["primary"]["detector_score"] is None, "reviewed primary detector score must be null")
        _require(assembly["primary"]["classifier_score"] is None, "reviewed primary classifier score must be null")
        for plate in assembly["supplementary_plates"]:
            _require(plate["detector_score"] is None, "reviewed plate detector score must be null")
            _require(plate["classifier_score"] is None, "reviewed plate classifier score must be null")
    return [hard, readable]


def _preprocessing_record(value: PreprocessedInput) -> dict[str, Any]:
    return {
        "preprocessing_version": value.metadata["preprocessing_version"],
        "tensor_sha256": value.tensor_sha256,
        "tensor_shape": list(value.tensor.shape),
        "tensor_dtype": str(value.tensor.dtype),
        "pixel_size": [value.pixels.width, value.pixels.height],
        "metadata": dict(value.metadata),
    }


def verify_asset(
    observation: Mapping[str, Any],
    path: Path,
    pack: Mapping[str, Any],
    capture_dir: Path | None = None,
) -> dict[str, Any]:
    expected = observation["hd_asset"]
    _require(path.is_file(), f"HD asset is missing: {path}")
    digest = _sha256(path)
    _require(digest == expected["sha256"], f"HD asset hash mismatch for {observation['observation_id']}")
    try:
        with Image.open(path) as source:
            source.load()
            image = source.copy()
    except (OSError, Image.DecompressionBombError) as error:
        raise RoundTripV2Error(f"cannot decode image {path}: {error}") from error
    _require(image.size == (expected["width"], expected["height"]), f"HD asset dimensions mismatch for {observation['observation_id']}")

    detector = preprocess_detector(image, pack["stages"]["detector"]["preprocessing"])
    classifier_spec = pack["stages"]["classifier"]["preprocessing"]
    primary = preprocess_classifier(
        image,
        observation["review"]["primary"]["bounding_box"],
        classifier_spec,
        role_hint="primary_sign",
    )
    plate = preprocess_classifier(
        image,
        observation["review"]["supplementary_plate"]["bounding_box"],
        classifier_spec,
        role_hint="supplementary_plate",
    )
    _require(primary.tensor_sha256 != plate.tensor_sha256, "primary and plate classifier inputs must remain separate")

    captures: dict[str, str] = {}
    if capture_dir is not None:
        observation_dir = capture_dir / observation["observation_id"]
        observation_dir.mkdir(parents=True, exist_ok=True)
        for name, value in (("detector", detector), ("primary", primary), ("supplementary", plate)):
            destination = observation_dir / f"{name}-preprocessed.png"
            value.pixels.save(destination, format="PNG")
            captures[name] = str(destination)

    return {
        "observation_id": observation["observation_id"],
        "picture_id": observation["picture_id"],
        "asset_path": str(path),
        "asset_sha256": digest,
        "asset_size": list(image.size),
        "detector": _preprocessing_record(detector),
        "classifier": {
            "primary_sign": _preprocessing_record(primary),
            "supplementary_plate": _preprocessing_record(plate),
        },
        "diagnostic_captures": captures,
    }


def build_report(
    pack: Mapping[str, Any],
    fixture: Mapping[str, Any],
    raw_events: Any,
    assets: Mapping[str, Path] | None = None,
    capture_dir: Path | None = None,
) -> dict[str, Any]:
    validate_pack(pack)
    temporal = validate_fixture(fixture, pack)
    events = validate_events(raw_events, fixture, pack)

    assets = assets or {}
    unknown_assets = set(assets) - {item["observation_id"] for item in fixture["observations"]}
    _require(not unknown_assets, f"unknown asset observation IDs: {sorted(unknown_assets)}")
    preprocessing = [
        verify_asset(observation, assets[observation["observation_id"]], pack, capture_dir)
        for observation in fixture["observations"]
        if observation["observation_id"] in assets
    ]
    return {
        "report_schema_version": 1,
        "milestone": "M0 shadow round trip",
        "pack_id": pack["pack_id"],
        "fixture_id": fixture["fixture_id"],
        "contract_status": "passed",
        "source_asset_status": "passed" if len(preprocessing) == len(fixture["observations"]) else "not_run",
        "preprocessing_status": "passed" if len(preprocessing) == len(fixture["observations"]) else "not_run",
        "shadow_event_status": "passed",
        "model_inference_status": "not_run_missing_trained_artifacts",
        "override_gate_status": "blocked_shadow_only",
        "reviewed_oracle_used_for_semantic_expectations": True,
        "model_inference_claimed": False,
        "temporal_association": temporal,
        "event_ids": [event["event_id"] for event in events],
        "preprocessing": preprocessing,
        "limitations": [
            "Reviewed labels validate the expected semantics but are not detector or classifier output.",
            "No holdout, parity, device, temporal-production, or license gate is passed by this harness.",
            "The hard frame restriction remains null even after the later event resolves the track.",
        ],
    }


def _parse_assets(values: Sequence[str]) -> dict[str, Path]:
    assets: dict[str, Path] = {}
    for value in values:
        observation_id, separator, raw_path = value.partition("=")
        _require(bool(separator) and bool(observation_id) and bool(raw_path), "--asset must be OBSERVATION_ID=PATH")
        _require(observation_id not in assets, f"duplicate asset for {observation_id}")
        assets[observation_id] = Path(raw_path).expanduser().resolve()
    return assets


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pack", type=Path, default=DEFAULT_PACK)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--events", type=Path, default=DEFAULT_EVENTS)
    parser.add_argument(
        "--asset",
        action="append",
        default=[],
        metavar="OBSERVATION_ID=PATH",
        help="Verify and preprocess one exact HD source asset (repeat for both frames).",
    )
    parser.add_argument("--require-assets", action="store_true", help="Fail unless both exact HD assets are supplied.")
    parser.add_argument("--capture-dir", type=Path, help="Write reviewable preprocessed detector/primary/plate PNGs.")
    parser.add_argument("--output", type=Path, help="Write the evidence report as JSON.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    assets = _parse_assets(args.asset)
    pack = load_json(args.pack)
    fixture = load_json(args.fixture)
    events = load_json(args.events)
    if args.require_assets:
        required = {item["observation_id"] for item in fixture["observations"]}
        _require(set(assets) == required, f"--require-assets needs exactly {sorted(required)}")
    report = build_report(pack, fixture, events, assets, args.capture_dir)
    rendered = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered, encoding="utf-8")
    print(rendered, end="")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except RoundTripV2Error as error:
        raise SystemExit(f"M0 shadow round trip failed: {error}") from error
