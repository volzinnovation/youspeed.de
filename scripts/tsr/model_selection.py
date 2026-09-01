#!/usr/bin/env python3
"""Validate the TSR candidate registry and evaluate internal scorecard evidence.

The evaluator validates JSON counts and measurements and hashes every
bundle-relative evidence file. It never imports a model runtime or deserializes
checkpoint/model bytes. Selection is deliberately read-only: the checked-in
``selected_candidate_id`` remains null until a separate reviewed decision
changes the versioned registry.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path, PurePosixPath
from statistics import NormalDist
from typing import Any, Mapping, Sequence

try:
    from scripts.tsr.bootstrap_sources import (
        DEFAULT_MANIFEST as DEFAULT_SOURCE_MANIFEST,
        SourceManifestError,
        ValidatedSourceManifest,
        validate_manifest,
    )
except ModuleNotFoundError:  # Direct ``python scripts/tsr/model_selection.py``.
    from bootstrap_sources import (  # type: ignore[no-redef]
        DEFAULT_MANIFEST as DEFAULT_SOURCE_MANIFEST,
        SourceManifestError,
        ValidatedSourceManifest,
        validate_manifest,
    )


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = REPOSITORY_ROOT / "shared" / "tsr" / "model-selection-v1.json"
DEFAULT_EVALUATION_SCHEMA = (
    REPOSITORY_ROOT / "shared" / "tsr" / "model-evaluation.schema.json"
)
SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
PROFILE_TOKEN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.,_+:/-]{0,127}$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
SAFE_EVIDENCE_PATH = re.compile(
    r"^(?!.*(?:^|/)\.{1,2}(?:/|$))(?!.*//)"
    r"[A-Za-z0-9](?:[A-Za-z0-9._/-]*[A-Za-z0-9._-])?$"
)
RFC3339_DATE_TIME = re.compile(
    r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}"
    r"(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$"
)
MAX_JSON_BYTES = 5 * 1024 * 1024
MAX_EVIDENCE_BYTES = 512 * 1024 * 1024
MAX_CASE_INVENTORY_CASES = 100_000
MAX_INVENTORY_STRATA = 1_000
MAX_PARITY_OUTPUTS = 1_000_000
MAX_COMPONENTS = 16
MAX_GROUND_TRUTH_PER_CASE = 1_000
ALLOWED_STATUSES = {"not_evaluated", "blocked"}
ALLOWED_PLATFORMS = {"android", "ios", "offline"}
ALLOWED_PIPELINES = {
    "proposal_classification",
    "direct_detection",
    "crop_classification_external",
}
ALLOWED_LANES = {
    "target",
    "immediate_ios_shadow",
    "challenger",
    "external_benchmark",
}
REQUIRED_STRATA = (
    "adjacent_road",
    "construction",
    "day",
    "night",
    "weather",
)
DEVICE_BENCHMARK_MEASUREMENT_FIELDS = (
    "drive_duration_seconds",
    "camera_frame_count",
    "dropped_frame_count",
    "backpressure_event_count",
    "peak_memory_bytes",
    "detector_inference_count",
    "detector_p95_ms",
    "end_to_end_inference_count",
    "end_to_end_p95_ms",
    "maximum_in_flight",
)
DEVICE_PROFILE_FIELDS = (
    "tier_id",
    "platform",
    "hardware_model_id",
    "os_build_id",
    "app_build_sha256",
)
TRAINED_ARTIFACT_FORMATS = {
    "trained_checkpoint": "safetensors",
    "reference_onnx": "onnx",
    "coreml": "coreml-compiled-model",
    "litert": "litert-flatbuffer",
}


class ModelSelectionError(ValueError):
    """Raised when selection metadata or evaluation evidence is unsafe."""


@dataclass(frozen=True)
class ValidatedSelectionRegistry:
    path: Path
    sha256: str
    payload: dict[str, Any]
    candidates_by_id: Mapping[str, dict[str, Any]]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ModelSelectionError(message)


def _require_exact_keys(
    value: Any,
    required: Sequence[str],
    field: str,
) -> dict[str, Any]:
    _require(isinstance(value, dict), f"{field} must be an object")
    required_set = set(required)
    actual = set(value)
    missing = sorted(required_set - actual)
    unexpected = sorted(actual - required_set)
    _require(not missing, f"{field} is missing fields: {', '.join(missing)}")
    _require(
        not unexpected,
        f"{field} has unexpected fields: {', '.join(unexpected)}",
    )
    return value


def _require_id(value: Any, field: str) -> str:
    _require(
        isinstance(value, str) and SAFE_ID.fullmatch(value) is not None,
        f"{field} is not a safe id",
    )
    return value


def _require_profile_token(value: Any, field: str) -> str:
    _require(
        isinstance(value, str) and PROFILE_TOKEN.fullmatch(value) is not None,
        f"{field} must be a safe non-empty device/build identifier",
    )
    return value


def _require_sha256(value: Any, field: str) -> str:
    _require(
        isinstance(value, str) and SHA256.fullmatch(value) is not None,
        f"{field} must be a lowercase SHA-256",
    )
    return value


def _require_bool(value: Any, field: str) -> bool:
    _require(type(value) is bool, f"{field} must be boolean")
    return value


def _require_count(value: Any, field: str) -> int:
    _require(
        type(value) is int and value >= 0, f"{field} must be a non-negative integer"
    )
    return value


def _require_number(
    value: Any,
    field: str,
    *,
    minimum: float | None = None,
    maximum: float | None = None,
) -> float:
    _require(type(value) in {int, float}, f"{field} must be a finite number")
    try:
        number = float(value)
    except OverflowError as error:
        raise ModelSelectionError(f"{field} must be a finite number") from error
    _require(math.isfinite(number), f"{field} must be a finite number")
    if minimum is not None:
        _require(number >= minimum, f"{field} must be at least {minimum}")
    if maximum is not None:
        _require(number <= maximum, f"{field} must be at most {maximum}")
    return number


def _require_id_list(value: Any, field: str, *, nonempty: bool = False) -> list[str]:
    _require(isinstance(value, list), f"{field} must be an array")
    if nonempty:
        _require(bool(value), f"{field} must not be empty")
    result = [
        _require_id(item, f"{field}[{index}]") for index, item in enumerate(value)
    ]
    _require(len(result) == len(set(result)), f"{field} contains duplicate ids")
    return result


def _duplicate_rejecting_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ModelSelectionError(f"JSON contains duplicate key {key!r}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise ModelSelectionError(f"JSON contains non-finite number {value}")


def _load_json(path: Path | str, label: str) -> tuple[Path, bytes, dict[str, Any]]:
    resolved = Path(path).expanduser().resolve()
    _require(resolved.is_file(), f"missing {label}: {resolved}")
    try:
        size = resolved.stat().st_size
        _require(size <= MAX_JSON_BYTES, f"{label} exceeds {MAX_JSON_BYTES} bytes")
        raw = resolved.read_bytes()
    except ModelSelectionError:
        raise
    except OSError as error:
        raise ModelSelectionError(f"cannot read {label} {resolved}: {error}") from error
    payload = _parse_json_object(raw, label, resolved)
    return resolved, raw, payload


def _parse_json_object(
    raw: bytes,
    label: str,
    source: Path | str,
) -> dict[str, Any]:
    _require(len(raw) <= MAX_JSON_BYTES, f"{label} exceeds {MAX_JSON_BYTES} bytes")
    try:
        text = raw.decode("utf-8")
        payload = json.loads(
            text,
            object_pairs_hook=_duplicate_rejecting_object,
            parse_constant=_reject_nonfinite,
        )
    except ModelSelectionError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise ModelSelectionError(f"cannot read {label} {source}: {error}") from error
    _require(isinstance(payload, dict), f"{label} must be a JSON object")
    return payload


def _json_values_equal(left: Any, right: Any) -> bool:
    """Compare decoded JSON without Python's bool/int numeric coercion."""

    if type(left) is not type(right):
        return False
    if isinstance(left, dict):
        return set(left) == set(right) and all(
            _json_values_equal(left[key], right[key]) for key in left
        )
    if isinstance(left, list):
        return len(left) == len(right) and all(
            _json_values_equal(left_item, right_item)
            for left_item, right_item in zip(left, right)
        )
    return left == right


def _device_measurement_sha256(tier: Mapping[str, Any]) -> str:
    payload = {field: tier[field] for field in DEVICE_BENCHMARK_MEASUREMENT_FIELDS}
    encoded = json.dumps(
        payload,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _file_sha256(path: Path | str) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_source_ref(
    reference: Any,
    field: str,
    sources: ValidatedSourceManifest,
) -> tuple[str, str, str]:
    item = _require_exact_keys(reference, ("source_id", "artifact_id"), field)
    source_id = _require_id(item["source_id"], f"{field}.source_id")
    artifact_id = _require_id(item["artifact_id"], f"{field}.artifact_id")
    source = sources.sources_by_id.get(source_id)
    artifact = sources.artifacts_by_id.get(artifact_id)
    _require(source is not None, f"{field} references unknown source_id {source_id}")
    _require(
        artifact is not None, f"{field} references unknown artifact_id {artifact_id}"
    )
    _require(
        artifact["source_id"] == source_id,
        f"{field} artifact {artifact_id} belongs to {artifact['source_id']}, not {source_id}",
    )
    source_gate = source["license"]["release_gate"]
    _require(
        artifact["release_gate"] == source_gate,
        f"{field} source and artifact release gates differ",
    )
    return source_id, artifact_id, source_gate


def _expand_license_gate_ids(
    gate_ids: set[str],
    gate_definitions: Mapping[str, Any],
) -> set[str]:
    expanded: set[str] = set()
    pending = sorted(gate_ids, reverse=True)
    while pending:
        gate_id = pending.pop()
        if gate_id in expanded:
            continue
        definition = gate_definitions.get(gate_id)
        _require(definition is not None, f"unknown license gate {gate_id}")
        _require(
            isinstance(definition, dict), f"license gate {gate_id} must be an object"
        )
        requirements = definition.get("requires", [])
        _require(
            isinstance(requirements, list),
            f"license gate {gate_id}.requires must be an array",
        )
        for index, required_gate in enumerate(requirements):
            _require_id(required_gate, f"license gate {gate_id}.requires[{index}]")
            _require(
                required_gate in gate_definitions,
                f"license gate {gate_id} requires unknown gate {required_gate}",
            )
            pending.append(required_gate)
        expanded.add(gate_id)
    return expanded


def validate_registry(
    path: Path | str = DEFAULT_REGISTRY,
    source_manifest_path: Path | str = DEFAULT_SOURCE_MANIFEST,
) -> ValidatedSelectionRegistry:
    try:
        sources = validate_manifest(source_manifest_path)
    except SourceManifestError as error:
        raise ModelSelectionError(str(error)) from error

    registry_path, raw, payload = _load_json(path, "model-selection registry")
    _require_exact_keys(
        payload,
        (
            "schema_version",
            "registry_id",
            "as_of_date",
            "target_candidate_id",
            "selected_candidate_id",
            "selection_status",
            "evaluation_schema",
            "source_manifest_id",
            "source_manifest_sha256",
            "scorecard_policy",
            "scorecard_gates",
            "candidates",
        ),
        "registry",
    )
    _require(
        type(payload["schema_version"]) is int and payload["schema_version"] == 1,
        "selection registry schema_version must be integer 1",
    )
    _require(
        payload["registry_id"] == "youspeed-tsr-model-selection-v1",
        "unexpected selection registry id",
    )
    _require(
        isinstance(payload["as_of_date"], str) and payload["as_of_date"],
        "registry.as_of_date is required",
    )
    target_candidate_id = _require_id(
        payload["target_candidate_id"], "registry.target_candidate_id"
    )
    _require(
        payload["selected_candidate_id"] is None,
        "selected_candidate_id must remain null until a reviewed selection",
    )
    _require(
        payload["selection_status"] == "not_evaluated",
        "selection_status must remain not_evaluated",
    )
    _require(
        payload["evaluation_schema"] == DEFAULT_EVALUATION_SCHEMA.name,
        "registry must reference model-evaluation.schema.json",
    )
    _require(
        payload["source_manifest_id"] == sources.payload["manifest_id"],
        "registry source_manifest_id does not match the source manifest",
    )
    pinned_source_hash = _require_sha256(
        payload["source_manifest_sha256"], "registry.source_manifest_sha256"
    )
    actual_source_hash = _file_sha256(sources.path)
    _require(
        pinned_source_hash == actual_source_hash,
        "registry source_manifest_sha256 does not match current source-manifest bytes",
    )

    scorecard_policy = _require_exact_keys(
        payload["scorecard_policy"],
        ("scope", "authority", "disclaimer"),
        "registry.scorecard_policy",
    )
    _require(
        scorecard_policy
        == {
            "scope": "internal_candidate_comparison",
            "authority": "engineering_evidence_only",
            "disclaimer": (
                "Thresholds are internal candidate-comparison floors, not "
                "production release, legal, or regulatory approval."
            ),
        },
        "registry scorecard policy changed",
    )

    gates = _require_exact_keys(
        payload["scorecard_gates"],
        (
            "approved_holdout_dataset_id",
            "approved_holdout_case_inventory_sha256",
            "approved_holdout_group_split_sha256",
            "approved_parity_case_inventory_sha256",
            "approved_parity_reference_outputs_sha256",
            "approved_device_tier_profiles",
            "wilson_confidence_level",
            "minimum_confirmed_numeric_precision_lower_bound",
            "minimum_confirmed_numeric_recall_lower_bound",
            "maximum_dangerous_substitution_rate",
            "minimum_resolved_restriction_precision_lower_bound",
            "minimum_resolved_restriction_recall_lower_bound",
            "maximum_expected_calibration_error",
            "maximum_semantic_mismatch_count",
            "maximum_assembly_mismatch_count",
            "minimum_matched_box_iou",
            "maximum_calibrated_confidence_delta",
            "maximum_pack_bytes",
            "maximum_artifact_total_bytes",
            "maximum_detector_p95_ms",
            "maximum_end_to_end_p95_ms",
            "minimum_device_inference_count",
            "minimum_device_drive_duration_seconds",
            "minimum_detector_inference_rate_hz",
            "maximum_detector_inference_rate_hz",
            "minimum_camera_frame_rate_hz",
            "minimum_parity_case_count",
            "minimum_parity_reference_output_count",
            "maximum_device_peak_memory_bytes",
            "maximum_dropped_frame_rate",
            "maximum_backpressure_event_rate",
            "required_real_route_strata",
            "maximum_duplicate_confirmation_rate",
            "maximum_wrong_way_confirmation_rate",
        ),
        "registry.scorecard_gates",
    )
    confidence = _require_number(
        gates["wilson_confidence_level"],
        "registry.scorecard_gates.wilson_confidence_level",
        minimum=0.5,
        maximum=0.999999,
    )
    _require(confidence == 0.95, "v1 Wilson confidence level must be 0.95")
    corpus_pin_fields = (
        "approved_holdout_dataset_id",
        "approved_holdout_case_inventory_sha256",
        "approved_holdout_group_split_sha256",
        "approved_parity_case_inventory_sha256",
        "approved_parity_reference_outputs_sha256",
    )
    configured_corpus_pins = [gates[field] is not None for field in corpus_pin_fields]
    _require(
        not any(configured_corpus_pins) or all(configured_corpus_pins),
        "approved evaluation corpus pins must be configured atomically",
    )
    if all(configured_corpus_pins):
        _require_id(
            gates["approved_holdout_dataset_id"],
            "registry.scorecard_gates.approved_holdout_dataset_id",
        )
        for field in corpus_pin_fields[1:]:
            _require_sha256(gates[field], f"registry.scorecard_gates.{field}")
    approved_device_profiles = gates["approved_device_tier_profiles"]
    if approved_device_profiles is not None:
        _require(
            isinstance(approved_device_profiles, list) and approved_device_profiles,
            "registry.scorecard_gates.approved_device_tier_profiles must be null or a non-empty array",
        )
        _require(
            len(approved_device_profiles) <= 16,
            "registry.scorecard_gates.approved_device_tier_profiles exceeds 16 items",
        )
        tier_ids: set[str] = set()
        for index, profile_value in enumerate(approved_device_profiles):
            field = f"registry.scorecard_gates.approved_device_tier_profiles[{index}]"
            profile = _require_exact_keys(
                profile_value,
                DEVICE_PROFILE_FIELDS,
                field,
            )
            tier_id = _require_id(profile["tier_id"], f"{field}.tier_id")
            _require(
                tier_id not in tier_ids, f"duplicate approved device tier {tier_id}"
            )
            tier_ids.add(tier_id)
            _require(
                profile["platform"] in {"android", "ios"},
                f"{field}.platform is invalid",
            )
            for token_field in (
                "hardware_model_id",
                "os_build_id",
            ):
                _require_profile_token(profile[token_field], f"{field}.{token_field}")
            _require_sha256(profile["app_build_sha256"], f"{field}.app_build_sha256")
        _require(
            [profile["tier_id"] for profile in approved_device_profiles]
            == sorted(tier_ids),
            "registry.scorecard_gates.approved_device_tier_profiles must be sorted by tier_id",
        )
    probability_fields = (
        "minimum_confirmed_numeric_precision_lower_bound",
        "minimum_confirmed_numeric_recall_lower_bound",
        "maximum_dangerous_substitution_rate",
        "minimum_resolved_restriction_precision_lower_bound",
        "minimum_resolved_restriction_recall_lower_bound",
        "maximum_expected_calibration_error",
        "minimum_matched_box_iou",
        "maximum_calibrated_confidence_delta",
        "maximum_dropped_frame_rate",
        "maximum_backpressure_event_rate",
    )
    for field in probability_fields:
        _require_number(
            gates[field], f"registry.scorecard_gates.{field}", minimum=0, maximum=1
        )
    for field in ("maximum_semantic_mismatch_count", "maximum_assembly_mismatch_count"):
        _require_count(gates[field], f"registry.scorecard_gates.{field}")
    for field in (
        "maximum_pack_bytes",
        "maximum_artifact_total_bytes",
        "maximum_detector_p95_ms",
        "maximum_end_to_end_p95_ms",
        "minimum_device_inference_count",
        "minimum_device_drive_duration_seconds",
        "minimum_detector_inference_rate_hz",
        "maximum_detector_inference_rate_hz",
        "minimum_camera_frame_rate_hz",
        "minimum_parity_case_count",
        "minimum_parity_reference_output_count",
        "maximum_device_peak_memory_bytes",
    ):
        _require_number(gates[field], f"registry.scorecard_gates.{field}", minimum=1)
    _require(
        gates["minimum_confirmed_numeric_precision_lower_bound"] == 0.99
        and gates["minimum_confirmed_numeric_recall_lower_bound"] == 0.90
        and gates["maximum_dangerous_substitution_rate"] == 0.001
        and gates["minimum_resolved_restriction_precision_lower_bound"] == 0.98
        and gates["minimum_resolved_restriction_recall_lower_bound"] == 0.80
        and gates["maximum_expected_calibration_error"] == 0.03,
        "v1 semantic, recall, dangerous-substitution, restriction, and ECE gates changed",
    )
    _require(
        gates["maximum_semantic_mismatch_count"] == 0
        and gates["maximum_assembly_mismatch_count"] == 0
        and gates["minimum_matched_box_iou"] == 0.995
        and gates["maximum_calibrated_confidence_delta"] == 0.02,
        "v1 parity gates changed",
    )
    _require(
        gates["maximum_pack_bytes"] == 25_000_000
        and gates["maximum_artifact_total_bytes"] == 25_000_000
        and gates["maximum_detector_p95_ms"] == 250
        and gates["maximum_end_to_end_p95_ms"] == 250
        and gates["minimum_device_inference_count"] == 3_600
        and gates["minimum_device_drive_duration_seconds"] == 1_800
        and gates["minimum_detector_inference_rate_hz"] == 2
        and gates["maximum_detector_inference_rate_hz"] == 10
        and gates["minimum_camera_frame_rate_hz"] == 15
        and gates["minimum_parity_case_count"] == 1_000
        and gates["minimum_parity_reference_output_count"] == 1_000
        and gates["maximum_device_peak_memory_bytes"] == 256_000_000
        and gates["maximum_dropped_frame_rate"] == 0.01
        and gates["maximum_backpressure_event_rate"] == 0.001,
        "v1 mobile size or latency gates changed",
    )
    strata = _require_id_list(
        gates["required_real_route_strata"],
        "registry.scorecard_gates.required_real_route_strata",
        nonempty=True,
    )
    _require(tuple(sorted(strata)) == REQUIRED_STRATA, "v1 required strata changed")
    for field in (
        "maximum_duplicate_confirmation_rate",
        "maximum_wrong_way_confirmation_rate",
    ):
        threshold = gates[field]
        if threshold is not None:
            _require_number(
                threshold,
                f"registry.scorecard_gates.{field}",
                minimum=0,
                maximum=1,
            )

    candidates = payload["candidates"]
    _require(
        isinstance(candidates, list) and candidates,
        "registry.candidates must be non-empty",
    )
    candidates_by_id: dict[str, dict[str, Any]] = {}
    target_count = 0
    lane_counts = {lane: 0 for lane in ALLOWED_LANES}
    known_license_gates = set(sources.payload["release_policy"]["license_gates"])
    for index, candidate_value in enumerate(candidates):
        field = f"registry.candidates[{index}]"
        candidate = _require_exact_keys(
            candidate_value,
            (
                "candidate_id",
                "display_name",
                "lane",
                "status",
                "eligible_for_selection",
                "pipeline",
                "supported_platforms",
                "runtime_status",
                "components",
                "benchmark_dataset_refs",
                "required_license_gate_ids",
                "blocking_reasons",
            ),
            field,
        )
        candidate_id = _require_id(candidate["candidate_id"], f"{field}.candidate_id")
        _require(
            candidate_id not in candidates_by_id,
            f"duplicate candidate_id {candidate_id}",
        )
        _require(
            isinstance(candidate["display_name"], str) and candidate["display_name"],
            f"{field}.display_name is required",
        )
        lane = candidate["lane"]
        _require(lane in ALLOWED_LANES, f"{field}.lane is invalid")
        lane_counts[lane] += 1
        target_count += int(lane == "target")
        _require(candidate["status"] in ALLOWED_STATUSES, f"{field}.status is invalid")
        eligible = _require_bool(
            candidate["eligible_for_selection"], f"{field}.eligible_for_selection"
        )
        _require(
            candidate["pipeline"] in ALLOWED_PIPELINES, f"{field}.pipeline is invalid"
        )
        platforms = _require_id_list(
            candidate["supported_platforms"],
            f"{field}.supported_platforms",
            nonempty=True,
        )
        _require(
            set(platforms) <= ALLOWED_PLATFORMS,
            f"{field}.supported_platforms is invalid",
        )
        _require(
            platforms == sorted(platforms),
            f"{field}.supported_platforms must be sorted",
        )
        runtime_status = candidate["runtime_status"]
        _require(
            isinstance(runtime_status, dict),
            f"{field}.runtime_status must be an object",
        )
        _require(
            set(runtime_status) == set(platforms),
            f"{field}.runtime_status must cover every and only supported platform",
        )
        for platform in sorted(runtime_status):
            platform_status = _require_exact_keys(
                runtime_status[platform],
                ("status", "blockers"),
                f"{field}.runtime_status.{platform}",
            )
            _require(
                platform_status["status"] == "blocked",
                f"{field}.runtime_status.{platform} must remain blocked in v1",
            )
            blockers = platform_status["blockers"]
            _require(
                isinstance(blockers, list)
                and blockers
                and all(isinstance(reason, str) and reason for reason in blockers),
                f"{field}.runtime_status.{platform}.blockers must be non-empty strings",
            )

        components = candidate["components"]
        _require(
            isinstance(components, list) and components,
            f"{field}.components must be non-empty",
        )
        component_roles: set[str] = set()
        derived_gate_ids: set[str] = set()
        has_unpinned = False
        for component_index, component_value in enumerate(components):
            component_field = f"{field}.components[{component_index}]"
            component = _require_exact_keys(
                component_value,
                ("role", "family", "pin_status", "source_refs", "license_gate_ids"),
                component_field,
            )
            role = _require_id(component["role"], f"{component_field}.role")
            _require(
                role not in component_roles,
                f"{field} has duplicate component role {role}",
            )
            component_roles.add(role)
            _require(
                isinstance(component["family"], str) and component["family"],
                f"{component_field}.family is required",
            )
            pin_status = component["pin_status"]
            _require(
                pin_status in {"pinned", "unpinned"},
                f"{component_field}.pin_status is invalid",
            )
            source_refs = component["source_refs"]
            _require(
                isinstance(source_refs, list),
                f"{component_field}.source_refs must be an array",
            )
            component_gate_ids = set(
                _require_id_list(
                    component["license_gate_ids"],
                    f"{component_field}.license_gate_ids",
                    nonempty=True,
                )
            )
            _require(
                component_gate_ids <= known_license_gates,
                f"{component_field} references unknown license gate",
            )
            referenced_gates: set[str] = set()
            ref_pairs: set[tuple[str, str]] = set()
            for ref_index, reference in enumerate(source_refs):
                source_id, artifact_id, gate_id = _validate_source_ref(
                    reference,
                    f"{component_field}.source_refs[{ref_index}]",
                    sources,
                )
                _require(
                    (source_id, artifact_id) not in ref_pairs,
                    f"{component_field}.source_refs contains a duplicate",
                )
                ref_pairs.add((source_id, artifact_id))
                referenced_gates.add(gate_id)
            if pin_status == "pinned":
                _require(
                    bool(source_refs),
                    f"{component_field} is pinned without a source reference",
                )
                _require(
                    component_gate_ids == referenced_gates,
                    f"{component_field}.license_gate_ids do not match referenced sources",
                )
            else:
                has_unpinned = True
                _require(
                    not source_refs,
                    f"{component_field} must not fake refs while unpinned",
                )
            derived_gate_ids.update(component_gate_ids)

        benchmark_refs = candidate["benchmark_dataset_refs"]
        _require(
            isinstance(benchmark_refs, list),
            f"{field}.benchmark_dataset_refs must be an array",
        )
        benchmark_pairs: set[tuple[str, str]] = set()
        for ref_index, reference in enumerate(benchmark_refs):
            source_id, artifact_id, gate_id = _validate_source_ref(
                reference,
                f"{field}.benchmark_dataset_refs[{ref_index}]",
                sources,
            )
            _require(
                (source_id, artifact_id) not in benchmark_pairs,
                f"{field}.benchmark_dataset_refs contains a duplicate",
            )
            benchmark_pairs.add((source_id, artifact_id))
            derived_gate_ids.add(gate_id)

        required_gate_ids = set(
            _require_id_list(
                candidate["required_license_gate_ids"],
                f"{field}.required_license_gate_ids",
                nonempty=True,
            )
        )
        expanded_gate_ids = _expand_license_gate_ids(
            derived_gate_ids,
            sources.payload["release_policy"]["license_gates"],
        )
        _require(
            required_gate_ids == expanded_gate_ids,
            f"{field}.required_license_gate_ids do not match component/dataset lineage",
        )
        blocking_reasons = candidate["blocking_reasons"]
        _require(
            isinstance(blocking_reasons, list),
            f"{field}.blocking_reasons must be an array",
        )
        _require(
            all(isinstance(reason, str) and reason for reason in blocking_reasons),
            f"{field}.blocking_reasons must contain non-empty strings",
        )
        if has_unpinned or not eligible:
            _require(candidate["status"] == "blocked", f"{field} must be blocked")
            _require(bool(blocking_reasons), f"{field} needs explicit blocking reasons")
        candidates_by_id[candidate_id] = candidate

    _require(target_count == 1, "registry must have exactly one target lane")
    _require(
        lane_counts["immediate_ios_shadow"] == 1,
        "registry must have one immediate iOS shadow lane",
    )
    _require(target_candidate_id in candidates_by_id, "target_candidate_id is unknown")
    target = candidates_by_id[target_candidate_id]
    _require(
        target["lane"] == "target",
        "target_candidate_id does not identify the target lane",
    )
    target_families = {
        component["role"]: component["family"] for component in target["components"]
    }
    _require(
        target["pipeline"] == "proposal_classification"
        and target_families.get("proposal_detector") == "YOLOX-Nano"
        and target_families.get("classifier") == "MobileNetV3-Large",
        "target lane must be YOLOX-Nano proposals plus MobileNetV3-Large classification",
    )
    _require(
        target["status"] == "blocked"
        and any(
            "full-scene supplementary_plate detector-label coverage" in reason
            for reason in target["blocking_reasons"]
        ),
        "target lane must remain blocked on full-scene supplementary-plate label coverage",
    )
    yolox_small = candidates_by_id.get(
        "de-yolox-nano-mnv3-small-proposal-classification"
    )
    _require(
        yolox_small is not None
        and yolox_small["status"] == "blocked"
        and any(
            "full-scene supplementary_plate detector-label coverage" in reason
            for reason in yolox_small["blocking_reasons"]
        ),
        "YOLOX/MobileNetV3-Small challenger must remain blocked on full-scene supplementary-plate label coverage",
    )
    shadow = next(
        candidate
        for candidate in candidates
        if candidate["lane"] == "immediate_ios_shadow"
    )
    _require(
        shadow["pipeline"] == "direct_detection"
        and shadow["supported_platforms"] == ["ios"]
        and any(
            component["family"] == "YOLOX-Nano" for component in shadow["components"]
        ),
        "immediate shadow lane must be direct YOLOX-Nano on iOS",
    )
    families = {
        component["family"]
        for candidate in candidates
        for component in candidate["components"]
    }
    _require(
        {"MobileNetV3-Small", "RF-DETR-Nano", "D-FINE-N"} <= families,
        "registry is missing a required challenger",
    )
    _require(
        any(
            entry["lane"] == "external_benchmark"
            and component["family"] == "Panoramax German YOLO26 classifier"
            for entry in candidates
            for component in entry["components"]
        ),
        "registry is missing the Panoramax German classifier benchmark",
    )
    gtsign = candidates_by_id.get("gtsign-220-vit-all-classes-external")
    _require(gtsign is not None, "registry is missing the GTSIGN-220 ViT benchmark")
    _require(
        gtsign["lane"] == "external_benchmark"
        and gtsign["status"] == "blocked"
        and not gtsign["eligible_for_selection"]
        and gtsign["pipeline"] == "crop_classification_external"
        and gtsign["supported_platforms"] == ["offline"]
        and gtsign["required_license_gate_ids"] == ["attribution_share_alike_review"]
        and len(gtsign["components"]) == 1
        and gtsign["components"][0]["role"] == "classifier"
        and gtsign["components"][0]["family"] == "GTSIGN-220 ViT all classes"
        and gtsign["components"][0]["source_refs"]
        == [
            {
                "source_id": "gtsign-220-e235536",
                "artifact_id": "gtsign-220-vit-all-classes",
            }
        ],
        "GTSIGN-220 must remain a blocked offline-only external benchmark",
    )
    return ValidatedSelectionRegistry(
        path=registry_path,
        sha256=hashlib.sha256(raw).hexdigest(),
        payload=payload,
        candidates_by_id=candidates_by_id,
    )


def _validate_datetime(value: Any, field: str) -> str:
    _require(
        isinstance(value, str) and RFC3339_DATE_TIME.fullmatch(value) is not None,
        f"{field} must be an RFC 3339 date-time",
    )
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ModelSelectionError(f"{field} must be an RFC 3339 date-time") from error
    _require(parsed.tzinfo is not None, f"{field} must include a timezone")
    return value


def _require_positive_count(value: Any, field: str) -> int:
    count = _require_count(value, field)
    _require(count > 0, f"{field} must be a positive integer")
    return count


def _validate_dataset_bundle(value: Any, field: str) -> dict[str, Any]:
    bundle = _require_exact_keys(
        value,
        (
            "bundle_id",
            "source_ids",
            "artifact_refs",
            "inventory_file",
            "group_split_file",
        ),
        field,
    )
    _require_id(bundle["bundle_id"], f"{field}.bundle_id")
    source_ids = _require_id_list(
        bundle["source_ids"], f"{field}.source_ids", nonempty=True
    )
    _require(len(source_ids) <= 32, f"{field}.source_ids exceeds 32 items")
    _require(source_ids == sorted(source_ids), f"{field}.source_ids must be sorted")
    artifact_refs = bundle["artifact_refs"]
    _require(isinstance(artifact_refs, list), f"{field}.artifact_refs must be an array")
    _require(len(artifact_refs) <= 64, f"{field}.artifact_refs exceeds 64 items")
    pairs: set[tuple[str, str]] = set()
    for index, reference in enumerate(artifact_refs):
        reference_field = f"{field}.artifact_refs[{index}]"
        ref = _require_exact_keys(
            reference, ("source_id", "artifact_id"), reference_field
        )
        source_id = _require_id(ref["source_id"], f"{reference_field}.source_id")
        artifact_id = _require_id(ref["artifact_id"], f"{reference_field}.artifact_id")
        _require(
            (source_id, artifact_id) not in pairs,
            f"{field}.artifact_refs contains a duplicate",
        )
        pairs.add((source_id, artifact_id))
    _validate_evidence_file(bundle["inventory_file"], f"{field}.inventory_file")
    _validate_evidence_file(bundle["group_split_file"], f"{field}.group_split_file")
    return bundle


def _dataset_bundle_license_gates(
    bundle: Mapping[str, Any],
    sources: ValidatedSourceManifest,
    field: str,
) -> set[str]:
    source_ids = set(bundle["source_ids"])
    gates: set[str] = set()
    for source_id in sorted(source_ids):
        source = sources.sources_by_id.get(source_id)
        _require(
            source is not None, f"{field} references unknown source_id {source_id}"
        )
        _require(
            source["kind"] == "dataset",
            f"{field} source_id {source_id} is not a dataset source",
        )
        gates.add(source["license"]["release_gate"])
    for index, reference in enumerate(bundle["artifact_refs"]):
        reference_field = f"{field}.artifact_refs[{index}]"
        source_id, artifact_id, gate_id = _validate_source_ref(
            reference,
            reference_field,
            sources,
        )
        _require(
            source_id in source_ids,
            f"{reference_field} source_id is absent from bundle.source_ids",
        )
        artifact = sources.artifacts_by_id[artifact_id]
        _require(
            "dataset" in artifact["role"],
            f"{reference_field} is not a dataset artifact",
        )
        gates.add(gate_id)
    return gates


def _validate_evidence_file(value: Any, field: str) -> dict[str, Any]:
    reference = _require_exact_keys(value, ("path", "sha256"), field)
    path = reference["path"]
    _require(
        isinstance(path, str) and SAFE_EVIDENCE_PATH.fullmatch(path) is not None,
        f"{field}.path must be a safe relative POSIX path",
    )
    pure = PurePosixPath(path)
    _require(not pure.is_absolute(), f"{field}.path must be relative")
    _require(
        all(part not in {"", ".", ".."} for part in pure.parts),
        f"{field}.path contains an unsafe segment",
    )
    _require_sha256(reference["sha256"], f"{field}.sha256")
    return reference


def _validate_source_refs(value: Any, field: str) -> list[dict[str, Any]]:
    _require(isinstance(value, list) and value, f"{field} must be a non-empty array")
    refs: list[dict[str, Any]] = []
    pairs: set[tuple[str, str]] = set()
    for index, ref_value in enumerate(value):
        ref_field = f"{field}[{index}]"
        ref = _require_exact_keys(ref_value, ("source_id", "artifact_id"), ref_field)
        source_id = _require_id(ref["source_id"], f"{ref_field}.source_id")
        artifact_id = _require_id(ref["artifact_id"], f"{ref_field}.artifact_id")
        pair = (source_id, artifact_id)
        _require(pair not in pairs, f"{field} contains duplicate source refs")
        pairs.add(pair)
        refs.append(ref)
    return refs


def _validate_training_manifest(value: Any, field: str) -> dict[str, Any]:
    manifest = _require_exact_keys(
        value,
        (
            "schema_version",
            "training_run_id",
            "candidate_id",
            "source_manifest_id",
            "source_manifest_sha256",
            "training_dataset_bundle",
            "calibration_dataset_bundle",
            "components",
        ),
        field,
    )
    _require(
        type(manifest["schema_version"]) is int and manifest["schema_version"] == 1,
        f"{field}.schema_version must be integer 1",
    )
    _require_id(manifest["training_run_id"], f"{field}.training_run_id")
    _require_id(manifest["candidate_id"], f"{field}.candidate_id")
    _require(
        manifest["source_manifest_id"] == "youspeed-tsr-training-sources-v1",
        f"{field}.source_manifest_id is invalid",
    )
    _require_sha256(
        manifest["source_manifest_sha256"], f"{field}.source_manifest_sha256"
    )
    _validate_dataset_bundle(
        manifest["training_dataset_bundle"],
        f"{field}.training_dataset_bundle",
    )
    _validate_dataset_bundle(
        manifest["calibration_dataset_bundle"],
        f"{field}.calibration_dataset_bundle",
    )
    components = manifest["components"]
    _require(
        isinstance(components, list) and components,
        f"{field}.components must be non-empty",
    )
    _require(
        len(components) <= MAX_COMPONENTS,
        f"{field}.components exceeds {MAX_COMPONENTS} items",
    )
    roles: set[str] = set()
    artifact_paths: dict[str, str] = {}
    artifact_hashes: dict[str, str] = {}
    for index, component_value in enumerate(components):
        component_field = f"{field}.components[{index}]"
        component = _require_exact_keys(
            component_value,
            (
                "role",
                "family",
                "source_refs",
                "artifact_formats",
                "trained_checkpoint",
                "reference_onnx",
                "coreml",
                "litert",
            ),
            component_field,
        )
        role = _require_id(component["role"], f"{component_field}.role")
        _require(
            role not in roles, f"{field}.components contains duplicate role {role}"
        )
        roles.add(role)
        _require(
            isinstance(component["family"], str) and component["family"],
            f"{component_field}.family is required",
        )
        _validate_source_refs(
            component["source_refs"], f"{component_field}.source_refs"
        )
        formats = _require_exact_keys(
            component["artifact_formats"],
            tuple(TRAINED_ARTIFACT_FORMATS),
            f"{component_field}.artifact_formats",
        )
        _require(
            formats == TRAINED_ARTIFACT_FORMATS,
            f"{component_field}.artifact_formats must attest the v1 role/format mapping",
        )
        for artifact_field in (
            "trained_checkpoint",
            "reference_onnx",
            "coreml",
            "litert",
        ):
            artifact = _validate_evidence_file(
                component[artifact_field],
                f"{component_field}.{artifact_field}",
            )
            slot = f"{role}.{artifact_field}"
            previous_path_slot = artifact_paths.get(artifact["path"])
            _require(
                previous_path_slot is None,
                f"trained model artifact path aliases {previous_path_slot} and {slot}",
            )
            artifact_paths[artifact["path"]] = slot
            previous_hash_slot = artifact_hashes.get(artifact["sha256"])
            _require(
                previous_hash_slot is None,
                f"trained model artifact SHA-256 aliases {previous_hash_slot} and {slot}",
            )
            artifact_hashes[artifact["sha256"]] = slot
    return manifest


def _validate_case_inventory(value: Any, field: str) -> dict[str, Any]:
    inventory = _require_exact_keys(
        value,
        (
            "schema_version",
            "dataset_id",
            "sample_count",
            "primary_ground_truth_count",
            "restriction_ground_truth_count",
            "cases",
            "strata",
        ),
        field,
    )
    _require(
        type(inventory["schema_version"]) is int and inventory["schema_version"] == 1,
        f"{field}.schema_version must be integer 1",
    )
    _require_id(inventory["dataset_id"], f"{field}.dataset_id")
    for count_field in (
        "sample_count",
        "primary_ground_truth_count",
        "restriction_ground_truth_count",
    ):
        _require_positive_count(inventory[count_field], f"{field}.{count_field}")
    cases = inventory["cases"]
    _require(isinstance(cases, list) and cases, f"{field}.cases must be non-empty")
    _require(
        len(cases) <= MAX_CASE_INVENTORY_CASES,
        f"{field}.cases exceeds {MAX_CASE_INVENTORY_CASES} items",
    )
    case_ids: set[str] = set()
    computed_strata: dict[str, dict[str, int]] = {}
    computed_primary_count = 0
    computed_restriction_count = 0
    for index, case_value in enumerate(cases):
        case_field = f"{field}.cases[{index}]"
        case = _require_exact_keys(
            case_value,
            (
                "case_id",
                "annotation_sha256",
                "strata",
                "primary_ground_truth_count",
                "restriction_ground_truth_count",
            ),
            case_field,
        )
        case_id = _require_id(case["case_id"], f"{case_field}.case_id")
        _require(case_id not in case_ids, f"{field}.cases contains duplicate case_id")
        case_ids.add(case_id)
        _require_sha256(case["annotation_sha256"], f"{case_field}.annotation_sha256")
        case_strata = _require_id_list(
            case["strata"], f"{case_field}.strata", nonempty=True
        )
        _require(
            len(case_strata) <= MAX_INVENTORY_STRATA,
            f"{case_field}.strata exceeds {MAX_INVENTORY_STRATA} items",
        )
        primary_count = _require_count(
            case["primary_ground_truth_count"],
            f"{case_field}.primary_ground_truth_count",
        )
        restriction_count = _require_count(
            case["restriction_ground_truth_count"],
            f"{case_field}.restriction_ground_truth_count",
        )
        _require(
            primary_count <= MAX_GROUND_TRUTH_PER_CASE
            and restriction_count <= MAX_GROUND_TRUTH_PER_CASE,
            f"{case_field} task ground-truth count exceeds {MAX_GROUND_TRUTH_PER_CASE}",
        )
        computed_primary_count += primary_count
        computed_restriction_count += restriction_count
        for name in case_strata:
            aggregate = computed_strata.setdefault(
                name,
                {
                    "case_count": 0,
                    "primary_ground_truth_count": 0,
                    "restriction_ground_truth_count": 0,
                },
            )
            aggregate["case_count"] += 1
            aggregate["primary_ground_truth_count"] += primary_count
            aggregate["restriction_ground_truth_count"] += restriction_count
    _require(
        len(cases) == inventory["sample_count"],
        f"{field}.sample_count differs from immutable case identities",
    )
    _require(
        computed_primary_count == inventory["primary_ground_truth_count"],
        f"{field}.primary_ground_truth_count differs from per-case annotations",
    )
    _require(
        computed_restriction_count == inventory["restriction_ground_truth_count"],
        f"{field}.restriction_ground_truth_count differs from per-case annotations",
    )
    strata = inventory["strata"]
    _require(isinstance(strata, list) and strata, f"{field}.strata must be non-empty")
    _require(
        len(strata) <= MAX_INVENTORY_STRATA,
        f"{field}.strata exceeds {MAX_INVENTORY_STRATA} items",
    )
    names: set[str] = set()
    for index, stratum_value in enumerate(strata):
        stratum_field = f"{field}.strata[{index}]"
        stratum = _require_exact_keys(
            stratum_value,
            (
                "name",
                "case_count",
                "primary_ground_truth_count",
                "restriction_ground_truth_count",
            ),
            stratum_field,
        )
        name = _require_id(stratum["name"], f"{stratum_field}.name")
        _require(name not in names, f"{field}.strata contains duplicate name {name}")
        names.add(name)
        _require_positive_count(stratum["case_count"], f"{stratum_field}.case_count")
        for count_field in (
            "primary_ground_truth_count",
            "restriction_ground_truth_count",
        ):
            _require_count(stratum[count_field], f"{stratum_field}.{count_field}")
        _require(
            stratum["case_count"] <= inventory["sample_count"],
            f"{stratum_field}.case_count exceeds inventory sample_count",
        )
        _require(
            stratum["primary_ground_truth_count"]
            <= inventory["primary_ground_truth_count"],
            f"{stratum_field}.primary_ground_truth_count exceeds inventory total",
        )
        _require(
            stratum["restriction_ground_truth_count"]
            <= inventory["restriction_ground_truth_count"],
            f"{stratum_field}.restriction_ground_truth_count exceeds inventory total",
        )
        _require(
            computed_strata.get(name)
            == {
                "case_count": stratum["case_count"],
                "primary_ground_truth_count": stratum["primary_ground_truth_count"],
                "restriction_ground_truth_count": stratum[
                    "restriction_ground_truth_count"
                ],
            },
            f"{stratum_field} differs from per-case identities and annotations",
        )
    _require(
        names == set(computed_strata),
        f"{field}.strata must exactly cover per-case stratum identities",
    )
    return inventory


def _validate_parity_case_inventory(value: Any, field: str) -> dict[str, Any]:
    inventory = _require_exact_keys(
        value,
        ("schema_version", "inventory_id", "cases"),
        field,
    )
    _require(
        type(inventory["schema_version"]) is int and inventory["schema_version"] == 1,
        f"{field}.schema_version must be integer 1",
    )
    _require_id(inventory["inventory_id"], f"{field}.inventory_id")
    cases = inventory["cases"]
    _require(isinstance(cases, list) and cases, f"{field}.cases must be non-empty")
    _require(
        len(cases) <= MAX_CASE_INVENTORY_CASES,
        f"{field}.cases exceeds {MAX_CASE_INVENTORY_CASES} items",
    )
    case_ids: set[str] = set()
    for index, case_value in enumerate(cases):
        case_field = f"{field}.cases[{index}]"
        case = _require_exact_keys(
            case_value,
            ("case_id", "input_sha256"),
            case_field,
        )
        case_id = _require_id(case["case_id"], f"{case_field}.case_id")
        _require(case_id not in case_ids, f"{field}.cases contains duplicate case_id")
        case_ids.add(case_id)
        _require_sha256(case["input_sha256"], f"{case_field}.input_sha256")
    return inventory


def _validate_normalized_outputs(value: Any, field: str) -> dict[str, Any]:
    payload = _require_exact_keys(
        value,
        (
            "schema_version",
            "output_kind",
            "runtime",
            "training_run_manifest_sha256",
            "case_inventory_sha256",
            "artifact_sha256s",
            "evaluated_case_ids",
            "outputs",
        ),
        field,
    )
    _require(
        type(payload["schema_version"]) is int and payload["schema_version"] == 1,
        f"{field}.schema_version must be integer 1",
    )
    _require(
        payload["output_kind"] in {"reference", "measured"},
        f"{field}.output_kind is invalid",
    )
    _require(
        payload["runtime"] in {"coreml", "litert", "onnx"},
        f"{field}.runtime is invalid",
    )
    _require_sha256(
        payload["training_run_manifest_sha256"],
        f"{field}.training_run_manifest_sha256",
    )
    _require_sha256(payload["case_inventory_sha256"], f"{field}.case_inventory_sha256")
    artifact_sha256s = payload["artifact_sha256s"]
    _require(
        isinstance(artifact_sha256s, list) and artifact_sha256s,
        f"{field}.artifact_sha256s must be a non-empty array",
    )
    _require(
        len(artifact_sha256s) <= MAX_COMPONENTS,
        f"{field}.artifact_sha256s exceeds {MAX_COMPONENTS} items",
    )
    validated_artifact_sha256s = [
        _require_sha256(value, f"{field}.artifact_sha256s[{index}]")
        for index, value in enumerate(artifact_sha256s)
    ]
    _require(
        len(validated_artifact_sha256s) == len(set(validated_artifact_sha256s)),
        f"{field}.artifact_sha256s contains duplicates",
    )
    evaluated_case_ids = _require_id_list(
        payload["evaluated_case_ids"],
        f"{field}.evaluated_case_ids",
    )
    _require(
        len(evaluated_case_ids) <= MAX_CASE_INVENTORY_CASES,
        f"{field}.evaluated_case_ids exceeds {MAX_CASE_INVENTORY_CASES} items",
    )
    evaluated_case_id_set = set(evaluated_case_ids)
    outputs = payload["outputs"]
    _require(isinstance(outputs, list), f"{field}.outputs must be an array")
    _require(
        len(outputs) <= MAX_PARITY_OUTPUTS,
        f"{field}.outputs exceeds {MAX_PARITY_OUTPUTS} items",
    )
    output_ids: set[str] = set()
    for index, output_value in enumerate(outputs):
        output_field = f"{field}.outputs[{index}]"
        output = _require_exact_keys(
            output_value,
            (
                "output_id",
                "case_id",
                "semantic_label",
                "assembly_label",
                "box_xyxy",
                "calibrated_confidence",
            ),
            output_field,
        )
        output_id = _require_id(output["output_id"], f"{output_field}.output_id")
        _require(
            output_id not in output_ids,
            f"{field}.outputs contains duplicate output_id {output_id}",
        )
        output_ids.add(output_id)
        case_id = _require_id(output["case_id"], f"{output_field}.case_id")
        _require(
            case_id in evaluated_case_id_set,
            f"{output_field}.case_id is not in evaluated_case_ids",
        )
        _require_id(output["semantic_label"], f"{output_field}.semantic_label")
        _require_id(output["assembly_label"], f"{output_field}.assembly_label")
        box = output["box_xyxy"]
        _require(
            isinstance(box, list) and len(box) == 4,
            f"{output_field}.box must contain four coordinates",
        )
        coordinates = [
            _require_number(
                coordinate,
                f"{output_field}.box_xyxy[{coordinate_index}]",
                minimum=0,
                maximum=1,
            )
            for coordinate_index, coordinate in enumerate(box)
        ]
        _require(
            coordinates[2] > coordinates[0] and coordinates[3] > coordinates[1],
            f"{output_field}.box must have positive area",
        )
        _require_number(
            output["calibrated_confidence"],
            f"{output_field}.calibrated_confidence",
            minimum=0,
            maximum=1,
        )
    return payload


def _box_iou(left: Sequence[Any], right: Sequence[Any]) -> float:
    left_values = [float(value) for value in left]
    right_values = [float(value) for value in right]
    intersection_width = max(
        0.0, min(left_values[2], right_values[2]) - max(left_values[0], right_values[0])
    )
    intersection_height = max(
        0.0, min(left_values[3], right_values[3]) - max(left_values[1], right_values[1])
    )
    intersection = intersection_width * intersection_height
    left_area = (left_values[2] - left_values[0]) * (left_values[3] - left_values[1])
    right_area = (right_values[2] - right_values[0]) * (
        right_values[3] - right_values[1]
    )
    union = left_area + right_area - intersection
    _require(union > 0, "normalized parity boxes must have positive union area")
    return intersection / union


def _derive_parity_metrics(
    case_inventory: Mapping[str, Any],
    case_inventory_sha256: str,
    reference_outputs: Mapping[str, Any],
    runtime_outputs: Mapping[str, Mapping[str, Any]],
    training_run_manifest_sha256: str,
    components: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    case_ids = {case["case_id"] for case in case_inventory["cases"]}
    reference_evaluated = set(reference_outputs["evaluated_case_ids"])
    _require(
        reference_outputs["case_inventory_sha256"] == case_inventory_sha256,
        "reference parity outputs identify another case inventory",
    )
    _require(
        reference_outputs["output_kind"] == "reference"
        and reference_outputs["runtime"] == "onnx",
        "reference parity outputs must identify the reference ONNX runtime",
    )
    _require(
        reference_outputs["training_run_manifest_sha256"]
        == training_run_manifest_sha256,
        "reference parity outputs identify another training run",
    )
    expected_artifact_hashes = {
        "onnx": sorted(component["reference_onnx_sha256"] for component in components),
        "coreml": sorted(component["coreml_sha256"] for component in components),
        "litert": sorted(component["litert_sha256"] for component in components),
    }
    _require(
        sorted(reference_outputs["artifact_sha256s"])
        == expected_artifact_hashes["onnx"],
        "reference parity outputs identify other ONNX artifacts",
    )
    reference_by_id = {
        (output["case_id"], output["output_id"]): output
        for output in reference_outputs["outputs"]
    }
    runtime_metrics: list[dict[str, Any]] = []
    total_semantic_mismatches = 0
    total_assembly_mismatches = 0
    matched_ious: list[float] = []
    matched_confidence_deltas: list[float] = []
    for runtime_name in sorted(runtime_outputs):
        runtime_payload = runtime_outputs[runtime_name]
        _require(
            runtime_payload["case_inventory_sha256"] == case_inventory_sha256,
            f"{runtime_name} parity outputs identify another case inventory",
        )
        _require(
            runtime_payload["output_kind"] == "measured"
            and runtime_payload["runtime"] == runtime_name,
            f"{runtime_name} parity outputs identify another runtime",
        )
        _require(
            runtime_payload["training_run_manifest_sha256"]
            == training_run_manifest_sha256,
            f"{runtime_name} parity outputs identify another training run",
        )
        _require(
            sorted(runtime_payload["artifact_sha256s"])
            == expected_artifact_hashes[runtime_name],
            f"{runtime_name} parity outputs identify other runtime artifacts",
        )
        runtime_evaluated = set(runtime_payload["evaluated_case_ids"])
        runtime_by_id = {
            (output["case_id"], output["output_id"]): output
            for output in runtime_payload["outputs"]
        }
        matched_ids = set(reference_by_id) & set(runtime_by_id)
        semantic_mismatch_count = 0
        assembly_mismatch_count = 0
        runtime_ious: list[float] = []
        runtime_confidence_deltas: list[float] = []
        for output_id in sorted(matched_ids):
            reference = reference_by_id[output_id]
            actual = runtime_by_id[output_id]
            if actual["semantic_label"] != reference["semantic_label"]:
                semantic_mismatch_count += 1
            if actual["assembly_label"] != reference["assembly_label"]:
                assembly_mismatch_count += 1
            runtime_ious.append(_box_iou(actual["box_xyxy"], reference["box_xyxy"]))
            runtime_confidence_deltas.append(
                abs(
                    float(actual["calibrated_confidence"])
                    - float(reference["calibrated_confidence"])
                )
            )
        total_semantic_mismatches += semantic_mismatch_count
        total_assembly_mismatches += assembly_mismatch_count
        matched_ious.extend(runtime_ious)
        matched_confidence_deltas.extend(runtime_confidence_deltas)
        runtime_metrics.append(
            {
                "runtime": runtime_name,
                "evaluated_case_count": len(runtime_evaluated),
                "missing_case_count": len(case_ids - runtime_evaluated),
                "unexpected_case_count": len(runtime_evaluated - case_ids),
                "output_count": len(runtime_by_id),
                "matched_reference_output_count": len(matched_ids),
                "missing_reference_output_count": len(
                    set(reference_by_id) - set(runtime_by_id)
                ),
                "unexpected_output_count": len(
                    set(runtime_by_id) - set(reference_by_id)
                ),
                "semantic_mismatch_count": semantic_mismatch_count,
                "assembly_mismatch_count": assembly_mismatch_count,
                "minimum_matched_box_iou": min(runtime_ious) if runtime_ious else None,
                "maximum_calibrated_confidence_delta": max(runtime_confidence_deltas)
                if runtime_confidence_deltas
                else None,
            }
        )
    return {
        "case_count": len(case_ids),
        "reference_evaluated_case_count": len(reference_evaluated),
        "reference_missing_case_count": len(case_ids - reference_evaluated),
        "reference_unexpected_case_count": len(reference_evaluated - case_ids),
        "reference_output_count": len(reference_by_id),
        "runtime_counts": runtime_metrics,
        "semantic_mismatch_count": total_semantic_mismatches,
        "assembly_mismatch_count": total_assembly_mismatches,
        "minimum_matched_box_iou": min(matched_ious) if matched_ious else None,
        "maximum_calibrated_confidence_delta": max(matched_confidence_deltas)
        if matched_confidence_deltas
        else None,
    }


def _iter_evidence_files(
    value: Any,
    field: str = "report",
) -> Sequence[tuple[str, Mapping[str, Any]]]:
    found: list[tuple[str, Mapping[str, Any]]] = []
    if isinstance(value, dict):
        if set(value) == {"path", "sha256"}:
            found.append((field, value))
        else:
            for key, child in value.items():
                found.extend(_iter_evidence_files(child, f"{field}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(_iter_evidence_files(child, f"{field}[{index}]"))
    return found


def _resolve_evidence_path(bundle_root: Path, relative_path: str, field: str) -> Path:
    pure = PurePosixPath(relative_path)
    candidate = bundle_root
    for part in pure.parts:
        candidate /= part
        _require(
            not candidate.is_symlink(),
            f"{field}.path must not traverse symlinks",
        )
    resolved = candidate.resolve()
    try:
        resolved.relative_to(bundle_root)
    except ValueError as error:
        raise ModelSelectionError(
            f"{field}.path escapes the evaluation bundle"
        ) from error
    _require(resolved.is_file(), f"missing evidence file: {relative_path}")
    return resolved


def _verify_report_evidence(
    report_path: Path,
    report: dict[str, Any],
) -> Mapping[str, Path]:
    bundle_root = report_path.parent.resolve()
    training_run = report["lineage"]["training_run"]
    holdout = report["holdout"]
    parity = report["parity"]
    section_bindings = (
        (holdout, "report_file", "holdout evaluation"),
        (report["leakage_audit"], "audit_file", "leakage audit"),
        (report["primary_semantics"], "metrics_file", "primary-semantics metrics"),
        (report["restrictions"], "metrics_file", "restriction metrics"),
        (
            report["calibration"],
            "reliability_report_file",
            "calibration reliability report",
        ),
        (report["parity"], "report_file", "cross-runtime parity report"),
        (report["temporal_behavior"], "report_file", "temporal-behavior report"),
        (report["mobile"], "pack_manifest_file", "mobile pack manifest"),
    )
    attestation_references = [
        tier[evidence_field]
        for tier in report["mobile"]["device_tiers"]
        for evidence_field in (
            "thermal_evidence_file",
            "recording_evidence_file",
        )
    ]
    parsed_json_references = [
        training_run["manifest_file"],
        holdout["case_inventory_file"],
        parity["case_inventory_file"],
        parity["reference_outputs_file"],
        *(runtime["output_file"] for runtime in parity["runtime_outputs"]),
        *(
            section[reference_field]
            for section, reference_field, _label in section_bindings
        ),
        *attestation_references,
    ]
    parsed_json_paths = [reference["path"] for reference in parsed_json_references]
    _require(
        len(parsed_json_paths) == len(set(parsed_json_paths)),
        "parsed JSON evidence files must use globally distinct paths",
    )
    direct_references = list(_iter_evidence_files(report))
    for parsed_path in parsed_json_paths:
        _require(
            sum(
                reference["path"] == parsed_path
                for _field, reference in direct_references
            )
            == 1,
            f"parsed JSON evidence path must not alias another artifact: {parsed_path}",
        )
    model_paths = {
        component[artifact_field]["path"]
        for component in training_run["manifest"]["components"]
        for artifact_field in (
            "trained_checkpoint",
            "reference_onnx",
            "coreml",
            "litert",
        )
    }
    _require(
        not (set(parsed_json_paths) & model_paths),
        "parsed JSON evidence paths must be disjoint from model artifacts",
    )

    verified: dict[str, Path] = {}
    verified_sizes: dict[str, int] = {}
    verified_json_bytes: dict[str, bytes] = {}
    expected_hashes: dict[str, str] = {}
    parsed_json_path_set = set(parsed_json_paths)

    def verify_reference(field: str, reference: Mapping[str, Any]) -> Path:
        relative_path = reference["path"]
        expected_hash = reference["sha256"]
        previous_hash = expected_hashes.get(relative_path)
        _require(
            previous_hash is None or previous_hash == expected_hash,
            f"evidence path {relative_path} is referenced with conflicting hashes",
        )
        expected_hashes[relative_path] = expected_hash
        if relative_path in verified:
            return verified[relative_path]
        resolved = _resolve_evidence_path(bundle_root, relative_path, field)
        try:
            flags = os.O_RDONLY
            if hasattr(os, "O_CLOEXEC"):
                flags |= os.O_CLOEXEC
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(resolved, flags)
            digest = hashlib.sha256()
            retained_chunks: list[bytes] | None = (
                [] if relative_path in parsed_json_path_set else None
            )
            size = 0
            with os.fdopen(descriptor, "rb") as handle:
                file_stat = os.fstat(handle.fileno())
                _require(
                    stat.S_ISREG(file_stat.st_mode),
                    f"evidence path is not a regular file: {relative_path}",
                )
                _require(
                    file_stat.st_size <= MAX_EVIDENCE_BYTES,
                    f"evidence file exceeds {MAX_EVIDENCE_BYTES} bytes: {relative_path}",
                )
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    size += len(chunk)
                    _require(
                        size <= MAX_EVIDENCE_BYTES,
                        f"evidence file exceeds {MAX_EVIDENCE_BYTES} bytes: {relative_path}",
                    )
                    digest.update(chunk)
                    if retained_chunks is not None:
                        retained_chunks.append(chunk)
                _require(
                    size == file_stat.st_size,
                    f"evidence file changed while hashing: {relative_path}",
                )
            actual_hash = digest.hexdigest()
            _require(
                actual_hash == expected_hash,
                f"evidence SHA-256 mismatch: {relative_path}",
            )
            if retained_chunks is not None:
                verified_json_bytes[relative_path] = b"".join(retained_chunks)
        except OSError as error:
            raise ModelSelectionError(
                f"cannot read evidence file {relative_path}: {error}"
            ) from error
        verified[relative_path] = resolved
        verified_sizes[relative_path] = size
        return resolved

    def load_reference_json(reference: Mapping[str, Any], label: str) -> dict[str, Any]:
        relative_path = reference["path"]
        return _parse_json_object(
            verified_json_bytes[relative_path],
            label,
            relative_path,
        )

    for field, reference in direct_references:
        verify_reference(field, reference)

    loaded_manifest = load_reference_json(
        training_run["manifest_file"], "training-run manifest"
    )
    _validate_training_manifest(loaded_manifest, "training-run manifest file")
    _require(
        _json_values_equal(loaded_manifest, training_run["manifest"]),
        "training-run manifest file differs from embedded manifest",
    )
    loaded_inventory = load_reference_json(
        holdout["case_inventory_file"], "holdout case inventory"
    )
    _validate_case_inventory(loaded_inventory, "holdout case-inventory file")
    _require(
        _json_values_equal(loaded_inventory, holdout["case_inventory"]),
        "holdout case-inventory file differs from embedded inventory",
    )

    for section, reference_field, label in section_bindings:
        loaded_payload = load_reference_json(section[reference_field], label)
        expected_payload = {
            key: value for key, value in section.items() if key != reference_field
        }
        _require(
            _json_values_equal(loaded_payload, expected_payload),
            f"{label} file differs from scored report fields",
        )

    loaded_parity_inventory = load_reference_json(
        parity["case_inventory_file"], "parity case inventory"
    )
    _validate_parity_case_inventory(
        loaded_parity_inventory, "parity case-inventory file"
    )
    loaded_reference_outputs = load_reference_json(
        parity["reference_outputs_file"], "parity reference outputs"
    )
    _validate_normalized_outputs(
        loaded_reference_outputs, "parity reference-outputs file"
    )
    loaded_runtime_outputs: dict[str, dict[str, Any]] = {}
    for runtime in parity["runtime_outputs"]:
        runtime_name = runtime["runtime"]
        loaded_outputs = load_reference_json(
            runtime["output_file"], f"{runtime_name} parity outputs"
        )
        _validate_normalized_outputs(
            loaded_outputs, f"{runtime_name} parity outputs file"
        )
        loaded_runtime_outputs[runtime_name] = loaded_outputs
    report["_verified_parity_metrics"] = _derive_parity_metrics(
        loaded_parity_inventory,
        parity["case_inventory_file"]["sha256"],
        loaded_reference_outputs,
        loaded_runtime_outputs,
        parity["training_run_manifest_sha256"],
        parity["components"],
    )

    for index, artifact in enumerate(report["mobile"]["artifacts"]):
        _require(
            verified_sizes[artifact["file"]["path"]] == artifact["size_bytes"],
            f"report.mobile.artifacts[{index}].size_bytes differs from evidence file",
        )
    for index, tier in enumerate(report["mobile"]["device_tiers"]):
        tier_field = f"report.mobile.device_tiers[{index}]"
        attestation_definitions = (
            (
                "thermal_evidence_file",
                "thermal_downshift_verified",
            ),
            (
                "recording_evidence_file",
                "recording_unaffected",
            ),
        )
        for evidence_field, claim_field in attestation_definitions:
            reference = tier[evidence_field]
            attestation_field = f"{tier_field}.{evidence_field}"
            attestation = _require_exact_keys(
                load_reference_json(reference, f"{claim_field} attestation"),
                (
                    "schema_version",
                    "tier_id",
                    "benchmark_run_id",
                    "device_instance_id",
                    "platform",
                    "hardware_model_id",
                    "os_build_id",
                    "app_build_sha256",
                    "training_run_manifest_sha256",
                    "artifact_sha256s",
                    "measurement_sha256",
                    "claim",
                    "value",
                    "log_file",
                ),
                f"{attestation_field} payload",
            )
            _require(
                type(attestation["schema_version"]) is int
                and attestation["schema_version"] == 1,
                f"{attestation_field} schema_version must be integer 1",
            )
            _require_id(attestation["tier_id"], f"{attestation_field}.tier_id")
            _require(
                attestation["tier_id"] == tier["tier_id"],
                f"{attestation_field} identifies another device tier",
            )
            _require_id(
                attestation["benchmark_run_id"],
                f"{attestation_field}.benchmark_run_id",
            )
            _require(
                attestation["benchmark_run_id"] == tier["benchmark_run_id"],
                f"{attestation_field} identifies another benchmark run",
            )
            _require_profile_token(
                attestation["device_instance_id"],
                f"{attestation_field}.device_instance_id",
            )
            _require(
                attestation["device_instance_id"] == tier["device_instance_id"],
                f"{attestation_field} identifies another device instance",
            )
            _require(
                attestation["platform"] in {"android", "ios"},
                f"{attestation_field}.platform is invalid",
            )
            _require(
                attestation["platform"] == tier["platform"],
                f"{attestation_field} identifies another platform",
            )
            for profile_field in (
                "hardware_model_id",
                "os_build_id",
            ):
                _require_profile_token(
                    attestation[profile_field],
                    f"{attestation_field}.{profile_field}",
                )
                _require(
                    attestation[profile_field] == tier[profile_field],
                    f"{attestation_field} identifies another {profile_field}",
                )
            _require_sha256(
                attestation["app_build_sha256"],
                f"{attestation_field}.app_build_sha256",
            )
            _require(
                attestation["app_build_sha256"] == tier["app_build_sha256"],
                f"{attestation_field} identifies another app_build_sha256",
            )
            _require_sha256(
                attestation["training_run_manifest_sha256"],
                f"{attestation_field}.training_run_manifest_sha256",
            )
            _require(
                attestation["training_run_manifest_sha256"]
                == tier["training_run_manifest_sha256"],
                f"{attestation_field} identifies another training run",
            )
            artifact_hashes = attestation["artifact_sha256s"]
            _require(
                isinstance(artifact_hashes, list) and artifact_hashes,
                f"{attestation_field}.artifact_sha256s must be a non-empty array",
            )
            validated_artifact_hashes = [
                _require_sha256(
                    artifact_hash,
                    f"{attestation_field}.artifact_sha256s[{artifact_index}]",
                )
                for artifact_index, artifact_hash in enumerate(artifact_hashes)
            ]
            _require(
                len(validated_artifact_hashes) == len(set(validated_artifact_hashes)),
                f"{attestation_field}.artifact_sha256s contains duplicates",
            )
            _require(
                validated_artifact_hashes == tier["artifact_sha256s"],
                f"{attestation_field} identifies another artifact set",
            )
            _require_sha256(
                attestation["measurement_sha256"],
                f"{attestation_field}.measurement_sha256",
            )
            _require(
                attestation["measurement_sha256"] == _device_measurement_sha256(tier),
                f"{attestation_field} identifies other benchmark measurements",
            )
            _require(
                attestation["claim"] == claim_field,
                f"{attestation_field} identifies another claim",
            )
            _require_bool(attestation["value"], f"{attestation_field}.value")
            _require(
                attestation["value"] == tier[claim_field],
                f"{attestation_field} value differs from the scored claim",
            )
            log_reference = _validate_evidence_file(
                attestation["log_file"], f"{attestation_field}.log_file"
            )
            _require(
                log_reference["path"] not in expected_hashes,
                f"{attestation_field} must reference a globally distinct opaque log",
            )
            verify_reference(f"{attestation_field}.log_file", log_reference)
    return verified


COMPONENT_IDENTITY_FIELDS = (
    "role",
    "trained_checkpoint_sha256",
    "reference_onnx_sha256",
    "coreml_sha256",
    "litert_sha256",
)


def _validate_component_identities(value: Any, field: str) -> list[dict[str, Any]]:
    _require(isinstance(value, list) and value, f"{field} must be a non-empty array")
    _require(
        len(value) <= MAX_COMPONENTS,
        f"{field} exceeds {MAX_COMPONENTS} items",
    )
    components: list[dict[str, Any]] = []
    roles: set[str] = set()
    for index, component_value in enumerate(value):
        component_field = f"{field}[{index}]"
        component = _require_exact_keys(
            component_value,
            COMPONENT_IDENTITY_FIELDS,
            component_field,
        )
        role = _require_id(component["role"], f"{component_field}.role")
        _require(role not in roles, f"{field} contains duplicate role {role}")
        roles.add(role)
        for hash_field in COMPONENT_IDENTITY_FIELDS[1:]:
            _require_sha256(component[hash_field], f"{component_field}.{hash_field}")
        components.append(component)
    return components


def _validate_recall_strata(value: Any, field: str) -> list[dict[str, Any]]:
    _require(isinstance(value, list) and value, f"{field} must be a non-empty array")
    strata: list[dict[str, Any]] = []
    names: set[str] = set()
    for index, stratum_value in enumerate(value):
        stratum_field = f"{field}[{index}]"
        stratum = _require_exact_keys(
            stratum_value,
            (
                "name",
                "case_count",
                "ground_truth_count",
                "true_positive_count",
                "false_negative_count",
            ),
            stratum_field,
        )
        name = _require_id(stratum["name"], f"{stratum_field}.name")
        _require(name not in names, f"{field} contains duplicate stratum {name}")
        names.add(name)
        _require_positive_count(stratum["case_count"], f"{stratum_field}.case_count")
        _require_count(
            stratum["ground_truth_count"],
            f"{stratum_field}.ground_truth_count",
        )
        _require_count(
            stratum["true_positive_count"], f"{stratum_field}.true_positive_count"
        )
        _require_count(
            stratum["false_negative_count"], f"{stratum_field}.false_negative_count"
        )
        strata.append(stratum)
    return strata


def validate_evaluation_report(path: Path | str) -> tuple[Path, dict[str, Any]]:
    report_path, _raw, report = _load_json(path, "model evaluation report")
    _require_exact_keys(
        report,
        (
            "schema_version",
            "report_id",
            "candidate_id",
            "evaluated_at",
            "lineage",
            "holdout",
            "leakage_audit",
            "primary_semantics",
            "restrictions",
            "calibration",
            "parity",
            "temporal_behavior",
            "mobile",
        ),
        "report",
    )
    _require(
        type(report["schema_version"]) is int and report["schema_version"] == 1,
        "model evaluation schema_version must be integer 1",
    )
    _require_id(report["report_id"], "report.report_id")
    _require_id(report["candidate_id"], "report.candidate_id")
    _validate_datetime(report["evaluated_at"], "report.evaluated_at")

    lineage = _require_exact_keys(
        report["lineage"],
        (
            "source_manifest_id",
            "source_manifest_sha256",
            "selection_registry_sha256",
            "bootstrap_artifact_ids",
            "training_run",
        ),
        "report.lineage",
    )
    _require(
        lineage["source_manifest_id"] == "youspeed-tsr-training-sources-v1",
        "report.lineage.source_manifest_id is invalid",
    )
    _require_sha256(
        lineage["source_manifest_sha256"], "report.lineage.source_manifest_sha256"
    )
    _require_sha256(
        lineage["selection_registry_sha256"], "report.lineage.selection_registry_sha256"
    )
    _require_id_list(
        lineage["bootstrap_artifact_ids"],
        "report.lineage.bootstrap_artifact_ids",
        nonempty=True,
    )
    training_run = _require_exact_keys(
        lineage["training_run"],
        ("manifest_file", "manifest"),
        "report.lineage.training_run",
    )
    _validate_evidence_file(
        training_run["manifest_file"],
        "report.lineage.training_run.manifest_file",
    )
    _validate_training_manifest(
        training_run["manifest"],
        "report.lineage.training_run.manifest",
    )

    holdout = _require_exact_keys(
        report["holdout"],
        (
            "dataset_id",
            "case_inventory_file",
            "case_inventory",
            "group_split_file",
            "kind",
            "frozen",
            "threshold_fitted_on_holdout",
            "sample_count",
            "real_case_count",
            "synthetic_case_count",
            "independent_route_count",
            "strata",
            "report_file",
        ),
        "report.holdout",
    )
    _require_id(holdout["dataset_id"], "report.holdout.dataset_id")
    _validate_evidence_file(
        holdout["case_inventory_file"],
        "report.holdout.case_inventory_file",
    )
    _validate_case_inventory(
        holdout["case_inventory"],
        "report.holdout.case_inventory",
    )
    _validate_evidence_file(
        holdout["group_split_file"],
        "report.holdout.group_split_file",
    )
    _validate_evidence_file(holdout["report_file"], "report.holdout.report_file")
    _require(
        holdout["kind"] in {"real_route_held_out", "mixed", "synthetic"},
        "report.holdout.kind is invalid",
    )
    _require_bool(holdout["frozen"], "report.holdout.frozen")
    _require_bool(
        holdout["threshold_fitted_on_holdout"],
        "report.holdout.threshold_fitted_on_holdout",
    )
    _require_positive_count(holdout["sample_count"], "report.holdout.sample_count")
    _require_count(holdout["real_case_count"], "report.holdout.real_case_count")
    _require_count(
        holdout["synthetic_case_count"], "report.holdout.synthetic_case_count"
    )
    _require_positive_count(
        holdout["independent_route_count"],
        "report.holdout.independent_route_count",
    )
    _require(
        isinstance(holdout["strata"], list) and holdout["strata"],
        "report.holdout.strata must be a non-empty array",
    )
    stratum_names: set[str] = set()
    for index, stratum_value in enumerate(holdout["strata"]):
        field = f"report.holdout.strata[{index}]"
        stratum = _require_exact_keys(
            stratum_value, ("name", "case_count", "failure_count"), field
        )
        name = _require_id(stratum["name"], f"{field}.name")
        _require(name not in stratum_names, f"duplicate holdout stratum {name}")
        stratum_names.add(name)
        _require_positive_count(stratum["case_count"], f"{field}.case_count")
        _require_count(stratum["failure_count"], f"{field}.failure_count")

    leakage = _require_exact_keys(
        report["leakage_audit"],
        (
            "audit_file",
            "training_run_manifest_sha256",
            "training_dataset_inventory_sha256",
            "training_group_split_sha256",
            "calibration_dataset_inventory_sha256",
            "calibration_group_split_sha256",
            "holdout_case_inventory_sha256",
            "holdout_group_split_sha256",
            "capture_group_overlap_count",
            "physical_sign_cluster_overlap_count",
            "near_duplicate_overlap_count",
        ),
        "report.leakage_audit",
    )
    _validate_evidence_file(leakage["audit_file"], "report.leakage_audit.audit_file")
    for hash_field in (
        "training_run_manifest_sha256",
        "training_dataset_inventory_sha256",
        "training_group_split_sha256",
        "calibration_dataset_inventory_sha256",
        "calibration_group_split_sha256",
        "holdout_case_inventory_sha256",
        "holdout_group_split_sha256",
    ):
        _require_sha256(leakage[hash_field], f"report.leakage_audit.{hash_field}")
    for field in (
        "capture_group_overlap_count",
        "physical_sign_cluster_overlap_count",
        "near_duplicate_overlap_count",
    ):
        _require_count(leakage[field], f"report.leakage_audit.{field}")

    primary = _require_exact_keys(
        report["primary_semantics"],
        (
            "training_run_manifest_sha256",
            "components",
            "holdout_case_inventory_sha256",
            "evaluated_case_count",
            "ground_truth_count",
            "true_positive_count",
            "false_positive_count",
            "false_negative_count",
            "confirmed_numeric_prediction_count",
            "dangerous_substitution_count",
            "strata",
            "metrics_file",
        ),
        "report.primary_semantics",
    )
    _require_sha256(
        primary["training_run_manifest_sha256"],
        "report.primary_semantics.training_run_manifest_sha256",
    )
    _validate_component_identities(
        primary["components"], "report.primary_semantics.components"
    )
    _require_sha256(
        primary["holdout_case_inventory_sha256"],
        "report.primary_semantics.holdout_case_inventory_sha256",
    )
    _require_positive_count(
        primary["evaluated_case_count"], "report.primary_semantics.evaluated_case_count"
    )
    _require_positive_count(
        primary["ground_truth_count"], "report.primary_semantics.ground_truth_count"
    )
    for field in (
        "true_positive_count",
        "false_positive_count",
        "false_negative_count",
        "confirmed_numeric_prediction_count",
        "dangerous_substitution_count",
    ):
        _require_count(primary[field], f"report.primary_semantics.{field}")
    _validate_recall_strata(primary["strata"], "report.primary_semantics.strata")
    _validate_evidence_file(
        primary["metrics_file"], "report.primary_semantics.metrics_file"
    )

    restrictions = _require_exact_keys(
        report["restrictions"],
        (
            "training_run_manifest_sha256",
            "components",
            "holdout_case_inventory_sha256",
            "evaluated_case_count",
            "ground_truth_count",
            "true_positive_count",
            "false_positive_count",
            "false_negative_count",
            "resolved_prediction_count",
            "unresolved_promoted_unconditional_count",
            "strata",
            "metrics_file",
        ),
        "report.restrictions",
    )
    _require_sha256(
        restrictions["training_run_manifest_sha256"],
        "report.restrictions.training_run_manifest_sha256",
    )
    _validate_component_identities(
        restrictions["components"], "report.restrictions.components"
    )
    _require_sha256(
        restrictions["holdout_case_inventory_sha256"],
        "report.restrictions.holdout_case_inventory_sha256",
    )
    _require_positive_count(
        restrictions["evaluated_case_count"], "report.restrictions.evaluated_case_count"
    )
    _require_positive_count(
        restrictions["ground_truth_count"], "report.restrictions.ground_truth_count"
    )
    for field in (
        "true_positive_count",
        "false_positive_count",
        "false_negative_count",
        "resolved_prediction_count",
        "unresolved_promoted_unconditional_count",
    ):
        _require_count(restrictions[field], f"report.restrictions.{field}")
    _validate_recall_strata(restrictions["strata"], "report.restrictions.strata")
    _validate_evidence_file(
        restrictions["metrics_file"], "report.restrictions.metrics_file"
    )

    calibration = _require_exact_keys(
        report["calibration"],
        (
            "training_run_manifest_sha256",
            "dataset_inventory_sha256",
            "group_split_sha256",
            "sample_count",
            "bins",
            "reliability_report_file",
        ),
        "report.calibration",
    )
    for hash_field in (
        "training_run_manifest_sha256",
        "dataset_inventory_sha256",
        "group_split_sha256",
    ):
        _require_sha256(calibration[hash_field], f"report.calibration.{hash_field}")
    _validate_evidence_file(
        calibration["reliability_report_file"],
        "report.calibration.reliability_report_file",
    )
    _require_positive_count(
        calibration["sample_count"], "report.calibration.sample_count"
    )
    _require(
        isinstance(calibration["bins"], list) and calibration["bins"],
        "report.calibration.bins must be a non-empty array",
    )
    bin_indexes: set[int] = set()
    for index, bin_value in enumerate(calibration["bins"]):
        field = f"report.calibration.bins[{index}]"
        bin_item = _require_exact_keys(
            bin_value,
            ("index", "sample_count", "confidence_sum", "correct_count"),
            field,
        )
        bin_index = _require_count(bin_item["index"], f"{field}.index")
        _require(
            bin_index not in bin_indexes, f"duplicate calibration bin index {bin_index}"
        )
        bin_indexes.add(bin_index)
        _require_positive_count(bin_item["sample_count"], f"{field}.sample_count")
        _require_number(
            bin_item["confidence_sum"], f"{field}.confidence_sum", minimum=0
        )
        _require_count(bin_item["correct_count"], f"{field}.correct_count")

    parity = _require_exact_keys(
        report["parity"],
        (
            "training_run_manifest_sha256",
            "components",
            "case_inventory_file",
            "reference_outputs_file",
            "runtime_outputs",
            "report_file",
        ),
        "report.parity",
    )
    _require_sha256(
        parity["training_run_manifest_sha256"],
        "report.parity.training_run_manifest_sha256",
    )
    _validate_component_identities(parity["components"], "report.parity.components")
    _validate_evidence_file(
        parity["case_inventory_file"], "report.parity.case_inventory_file"
    )
    _validate_evidence_file(
        parity["reference_outputs_file"], "report.parity.reference_outputs_file"
    )
    _require(
        isinstance(parity["runtime_outputs"], list)
        and len(parity["runtime_outputs"]) == 3,
        "report.parity.runtime_outputs must contain exactly three runtimes",
    )
    runtime_names: set[str] = set()
    for index, runtime_value in enumerate(parity["runtime_outputs"]):
        field = f"report.parity.runtime_outputs[{index}]"
        runtime = _require_exact_keys(
            runtime_value,
            ("runtime", "output_file"),
            field,
        )
        runtime_name = runtime["runtime"]
        _require(
            runtime_name in {"coreml", "litert", "onnx"}, f"{field}.runtime is invalid"
        )
        _require(
            runtime_name not in runtime_names,
            f"duplicate parity runtime {runtime_name}",
        )
        runtime_names.add(runtime_name)
        _validate_evidence_file(runtime["output_file"], f"{field}.output_file")
    _require(
        runtime_names == {"coreml", "litert", "onnx"},
        "report.parity.runtime_outputs must cover ONNX, Core ML, and LiteRT",
    )
    _validate_evidence_file(parity["report_file"], "report.parity.report_file")

    temporal = _require_exact_keys(
        report["temporal_behavior"],
        (
            "training_run_manifest_sha256",
            "components",
            "physical_assembly_count",
            "duplicate_confirmation_count",
            "direction_evaluable_confirmation_count",
            "wrong_way_confirmation_count",
            "report_file",
        ),
        "report.temporal_behavior",
    )
    _require_sha256(
        temporal["training_run_manifest_sha256"],
        "report.temporal_behavior.training_run_manifest_sha256",
    )
    _validate_component_identities(
        temporal["components"], "report.temporal_behavior.components"
    )
    _require_positive_count(
        temporal["physical_assembly_count"],
        "report.temporal_behavior.physical_assembly_count",
    )
    _require_count(
        temporal["duplicate_confirmation_count"],
        "report.temporal_behavior.duplicate_confirmation_count",
    )
    _require_positive_count(
        temporal["direction_evaluable_confirmation_count"],
        "report.temporal_behavior.direction_evaluable_confirmation_count",
    )
    _require_count(
        temporal["wrong_way_confirmation_count"],
        "report.temporal_behavior.wrong_way_confirmation_count",
    )
    _validate_evidence_file(
        temporal["report_file"], "report.temporal_behavior.report_file"
    )

    mobile = _require_exact_keys(
        report["mobile"],
        (
            "training_run_manifest_sha256",
            "pack_manifest_file",
            "pack_size_bytes",
            "artifacts",
            "supported_device_tier_ids",
            "device_tiers",
        ),
        "report.mobile",
    )
    _require_sha256(
        mobile["training_run_manifest_sha256"],
        "report.mobile.training_run_manifest_sha256",
    )
    _validate_evidence_file(
        mobile["pack_manifest_file"], "report.mobile.pack_manifest_file"
    )
    _require_positive_count(mobile["pack_size_bytes"], "report.mobile.pack_size_bytes")
    _require(
        isinstance(mobile["artifacts"], list) and mobile["artifacts"],
        "report.mobile.artifacts must be a non-empty array",
    )
    artifact_ids: set[str] = set()
    artifact_pairs: set[tuple[str, str]] = set()
    for index, artifact_value in enumerate(mobile["artifacts"]):
        field = f"report.mobile.artifacts[{index}]"
        artifact = _require_exact_keys(
            artifact_value,
            ("role", "platform", "artifact_id", "file", "size_bytes"),
            field,
        )
        role = _require_id(artifact["role"], f"{field}.role")
        _require(
            artifact["platform"] in {"android", "ios"}, f"{field}.platform is invalid"
        )
        pair = (role, artifact["platform"])
        _require(
            pair not in artifact_pairs, f"duplicate mobile role/platform pair {pair}"
        )
        artifact_pairs.add(pair)
        artifact_id = _require_id(artifact["artifact_id"], f"{field}.artifact_id")
        _require(
            artifact_id not in artifact_ids,
            f"duplicate mobile artifact_id {artifact_id}",
        )
        artifact_ids.add(artifact_id)
        _validate_evidence_file(artifact["file"], f"{field}.file")
        _require_positive_count(artifact["size_bytes"], f"{field}.size_bytes")
    _require_id_list(
        mobile["supported_device_tier_ids"],
        "report.mobile.supported_device_tier_ids",
        nonempty=True,
    )
    _require(
        isinstance(mobile["device_tiers"], list) and mobile["device_tiers"],
        "report.mobile.device_tiers must be a non-empty array",
    )
    measured_tiers: set[str] = set()
    for index, tier_value in enumerate(mobile["device_tiers"]):
        field = f"report.mobile.device_tiers[{index}]"
        tier = _require_exact_keys(
            tier_value,
            (
                "tier_id",
                "benchmark_run_id",
                "device_instance_id",
                "platform",
                "hardware_model_id",
                "os_build_id",
                "app_build_sha256",
                "training_run_manifest_sha256",
                "artifact_sha256s",
                "drive_duration_seconds",
                "camera_frame_count",
                "dropped_frame_count",
                "backpressure_event_count",
                "peak_memory_bytes",
                "detector_inference_count",
                "detector_p95_ms",
                "end_to_end_inference_count",
                "end_to_end_p95_ms",
                "maximum_in_flight",
                "thermal_downshift_verified",
                "thermal_evidence_file",
                "recording_unaffected",
                "recording_evidence_file",
            ),
            field,
        )
        tier_id = _require_id(tier["tier_id"], f"{field}.tier_id")
        _require_id(tier["benchmark_run_id"], f"{field}.benchmark_run_id")
        _require_profile_token(
            tier["device_instance_id"], f"{field}.device_instance_id"
        )
        _require(tier_id not in measured_tiers, f"duplicate device tier {tier_id}")
        measured_tiers.add(tier_id)
        _require(tier["platform"] in {"android", "ios"}, f"{field}.platform is invalid")
        for profile_field in (
            "hardware_model_id",
            "os_build_id",
        ):
            _require_profile_token(tier[profile_field], f"{field}.{profile_field}")
        _require_sha256(tier["app_build_sha256"], f"{field}.app_build_sha256")
        _require_sha256(
            tier["training_run_manifest_sha256"],
            f"{field}.training_run_manifest_sha256",
        )
        artifact_hashes = tier["artifact_sha256s"]
        _require(
            isinstance(artifact_hashes, list) and artifact_hashes,
            f"{field}.artifact_sha256s must be a non-empty array",
        )
        validated_hashes = [
            _require_sha256(value, f"{field}.artifact_sha256s[{hash_index}]")
            for hash_index, value in enumerate(artifact_hashes)
        ]
        _require(
            len(validated_hashes) == len(set(validated_hashes)),
            f"{field}.artifact_sha256s contains duplicates",
        )
        _require_number(
            tier["drive_duration_seconds"], f"{field}.drive_duration_seconds", minimum=0
        )
        _require(
            tier["drive_duration_seconds"] > 0,
            f"{field}.drive_duration_seconds must be positive",
        )
        _require_positive_count(
            tier["camera_frame_count"], f"{field}.camera_frame_count"
        )
        _require_count(tier["dropped_frame_count"], f"{field}.dropped_frame_count")
        _require_count(
            tier["backpressure_event_count"], f"{field}.backpressure_event_count"
        )
        _require_positive_count(tier["peak_memory_bytes"], f"{field}.peak_memory_bytes")
        _require_positive_count(
            tier["detector_inference_count"], f"{field}.detector_inference_count"
        )
        _require_number(tier["detector_p95_ms"], f"{field}.detector_p95_ms", minimum=0)
        _require_positive_count(
            tier["end_to_end_inference_count"], f"{field}.end_to_end_inference_count"
        )
        _require_number(
            tier["end_to_end_p95_ms"], f"{field}.end_to_end_p95_ms", minimum=0
        )
        _require_positive_count(tier["maximum_in_flight"], f"{field}.maximum_in_flight")
        _require_bool(
            tier["thermal_downshift_verified"], f"{field}.thermal_downshift_verified"
        )
        _validate_evidence_file(
            tier["thermal_evidence_file"], f"{field}.thermal_evidence_file"
        )
        _require_bool(tier["recording_unaffected"], f"{field}.recording_unaffected")
        _validate_evidence_file(
            tier["recording_evidence_file"], f"{field}.recording_evidence_file"
        )
    _verify_report_evidence(report_path, report)
    return report_path, report


def wilson_lower_bound(
    success_count: int, total_count: int, confidence: float = 0.95
) -> float:
    """Return the two-sided Wilson interval's lower bound.

    A zero denominator is invalid evidence rather than a zero score.
    """

    _require(
        type(success_count) is int and success_count >= 0,
        "success_count must be non-negative",
    )
    _require(
        type(total_count) is int and total_count > 0, "total_count must be positive"
    )
    _require(success_count <= total_count, "success_count exceeds total_count")
    _require(0.5 <= confidence < 1, "confidence must be in [0.5, 1)")
    z = NormalDist().inv_cdf(1 - (1 - confidence) / 2)
    proportion = success_count / total_count
    denominator = 1 + z * z / total_count
    center = proportion + z * z / (2 * total_count)
    margin = z * math.sqrt(
        (proportion * (1 - proportion) + z * z / (4 * total_count)) / total_count
    )
    return max(0.0, (center - margin) / denominator)


def _rounded(value: float | None) -> float | None:
    return None if value is None else round(value, 12)


def _gate(
    gate_id: str,
    status: str,
    observed: Mapping[str, Any],
    threshold: Mapping[str, Any],
    reasons: Sequence[str] = (),
) -> dict[str, Any]:
    _require(
        status in {"pass", "fail", "pending_policy"}, f"invalid gate status {status}"
    )
    return {
        "gate_id": gate_id,
        "status": status,
        "observed": dict(observed),
        "threshold": dict(threshold),
        "reasons": list(reasons),
    }


def _candidate_bootstrap_artifact_ids(candidate: Mapping[str, Any]) -> set[str]:
    return {
        reference["artifact_id"]
        for component in candidate["components"]
        for reference in component["source_refs"]
    } | {reference["artifact_id"] for reference in candidate["benchmark_dataset_refs"]}


def _recall_coverage_gate(
    gate_id: str,
    metrics: Mapping[str, Any],
    holdout: Mapping[str, Any],
    task_prefix: str,
    required_strata: Sequence[str],
    minimum_lower_bound: float,
    confidence: float,
) -> dict[str, Any]:
    reasons: list[str] = []
    inventory = holdout["case_inventory"]
    expected_ground_truth_count = inventory[f"{task_prefix}_ground_truth_count"]
    ground_truth_count = metrics["ground_truth_count"]
    if metrics["evaluated_case_count"] != inventory["sample_count"]:
        reasons.append("evaluated case count differs from the holdout inventory")
    if ground_truth_count != expected_ground_truth_count:
        reasons.append("ground-truth count differs from the holdout inventory")
    if ground_truth_count <= 0:
        reasons.append("ground-truth denominator is zero")
    if (
        ground_truth_count
        != metrics["true_positive_count"] + metrics["false_negative_count"]
    ):
        reasons.append("ground truth does not equal TP + FN")
    overall_lower: float | None = None
    if ground_truth_count > 0 and metrics["true_positive_count"] <= ground_truth_count:
        overall_lower = wilson_lower_bound(
            metrics["true_positive_count"],
            ground_truth_count,
            confidence,
        )
        if overall_lower < minimum_lower_bound:
            reasons.append("overall Wilson recall lower bound is below threshold")
    elif metrics["true_positive_count"] > ground_truth_count:
        reasons.append("true positives exceed the ground-truth denominator")

    inventory_strata = {item["name"]: item for item in inventory["strata"]}
    metric_strata = {item["name"]: item for item in metrics["strata"]}
    if set(metric_strata) != set(inventory_strata):
        missing = sorted(set(inventory_strata) - set(metric_strata))
        unexpected = sorted(set(metric_strata) - set(inventory_strata))
        if missing:
            reasons.append(
                f"missing holdout-inventory recall strata: {', '.join(missing)}"
            )
        if unexpected:
            reasons.append(
                f"unexpected recall strata outside holdout inventory: {', '.join(unexpected)}"
            )
    missing_required_inventory = sorted(set(required_strata) - set(inventory_strata))
    if missing_required_inventory:
        reasons.append(
            "holdout inventory lacks required recall strata: "
            + ", ".join(missing_required_inventory)
        )
    observed_strata: list[dict[str, Any]] = []
    for name in sorted(inventory_strata):
        stratum = metric_strata.get(name)
        inventory_stratum = inventory_strata[name]
        if stratum is None:
            continue
        stratum_lower: float | None = None
        if stratum["case_count"] != inventory_stratum["case_count"]:
            reasons.append(
                f"recall stratum case count differs from holdout inventory: {name}"
            )
        expected_stratum_ground_truth = inventory_stratum[
            f"{task_prefix}_ground_truth_count"
        ]
        if stratum["ground_truth_count"] != expected_stratum_ground_truth:
            reasons.append(
                f"recall stratum ground truth differs from holdout inventory: {name}"
            )
        if stratum["ground_truth_count"] != (
            stratum["true_positive_count"] + stratum["false_negative_count"]
        ):
            reasons.append(f"ground truth does not equal TP + FN for stratum: {name}")
        elif stratum["ground_truth_count"] <= 0:
            if name in required_strata:
                reasons.append(
                    f"ground-truth denominator is zero for required stratum: {name}"
                )
        elif stratum["true_positive_count"] <= stratum["ground_truth_count"]:
            stratum_lower = wilson_lower_bound(
                stratum["true_positive_count"],
                stratum["ground_truth_count"],
                confidence,
            )
            if stratum_lower < minimum_lower_bound:
                reasons.append(
                    f"Wilson recall lower bound is below threshold for stratum: {name}"
                )
        else:
            reasons.append(f"true positives exceed ground truth for stratum: {name}")
        observed_strata.append(
            {
                "case_count": stratum["case_count"],
                "false_negative_count": stratum["false_negative_count"],
                "ground_truth_count": stratum["ground_truth_count"],
                "name": name,
                "true_positive_count": stratum["true_positive_count"],
                "wilson_lower_bound": _rounded(stratum_lower),
            }
        )
    return _gate(
        gate_id,
        "pass" if not reasons else "fail",
        {
            "evaluated_case_count": metrics["evaluated_case_count"],
            "false_negative_count": metrics["false_negative_count"],
            "ground_truth_count": ground_truth_count,
            "strata": observed_strata,
            "true_positive_count": metrics["true_positive_count"],
            "wilson_lower_bound": _rounded(overall_lower),
        },
        {
            "confidence_level": confidence,
            "minimum_wilson_lower_bound": minimum_lower_bound,
            "required_strata": sorted(required_strata),
            "required_ground_truth_count": expected_ground_truth_count,
            "required_holdout_case_count": inventory["sample_count"],
            "required_inventory_strata": sorted(inventory_strata),
        },
        reasons,
    )


def evaluate_candidate(
    registry: ValidatedSelectionRegistry,
    sources: ValidatedSourceManifest,
    report: Mapping[str, Any],
    *,
    approved_license_gates: Sequence[str] = (),
) -> dict[str, Any]:
    candidate_id = report["candidate_id"]
    candidate = registry.candidates_by_id.get(candidate_id)
    _require(candidate is not None, f"unknown candidate_id {candidate_id}")
    known_license_gates = set(sources.payload["release_policy"]["license_gates"])
    approved = set(approved_license_gates)
    _require(
        len(approved) == len(list(approved_license_gates)),
        "duplicate approved license gate",
    )
    unknown_approvals = sorted(approved - known_license_gates)
    _require(
        not unknown_approvals,
        f"unknown approved license gate: {', '.join(unknown_approvals)}",
    )
    policy = registry.payload["scorecard_gates"]
    gates: list[dict[str, Any]] = []

    readiness_reasons: list[str] = []
    if candidate["status"] != "not_evaluated":
        readiness_reasons.append(f"candidate status is {candidate['status']}")
    if not candidate["eligible_for_selection"]:
        readiness_reasons.append("candidate is not eligible for selection")
    unpinned = sorted(
        component["family"]
        for component in candidate["components"]
        if component["pin_status"] != "pinned"
    )
    if unpinned:
        readiness_reasons.append(f"unpinned components: {', '.join(unpinned)}")
    runtime_blockers = {
        platform: list(candidate["runtime_status"][platform]["blockers"])
        for platform in sorted(candidate["runtime_status"])
        if candidate["runtime_status"][platform]["status"] != "ready"
    }
    for platform, blockers in runtime_blockers.items():
        readiness_reasons.append(
            f"{platform} runtime is blocked: {'; '.join(blockers)}"
        )
    gates.append(
        _gate(
            "candidate_readiness",
            "pass" if not readiness_reasons else "fail",
            {
                "eligible_for_selection": candidate["eligible_for_selection"],
                "registry_status": candidate["status"],
                "runtime_blockers": runtime_blockers,
                "unpinned_components": unpinned,
            },
            {
                "eligible_for_selection": True,
                "registry_status": "not_evaluated",
                "runtime_blockers": {},
                "unpinned_components": [],
            },
            readiness_reasons,
        )
    )

    lineage = report["lineage"]
    training_run = lineage["training_run"]
    training_manifest = training_run["manifest"]
    training_manifest_hash = training_run["manifest_file"]["sha256"]
    manifest_components = {
        component["role"]: component for component in training_manifest["components"]
    }
    lineage_components = {
        role: {
            "role": role,
            "trained_checkpoint_sha256": component["trained_checkpoint"]["sha256"],
            "reference_onnx_sha256": component["reference_onnx"]["sha256"],
            "coreml_sha256": component["coreml"]["sha256"],
            "litert_sha256": component["litert"]["sha256"],
        }
        for role, component in manifest_components.items()
    }
    candidate_components = {
        component["role"]: component for component in candidate["components"]
    }
    candidate_roles = set(candidate_components)
    expected_bootstrap_ids = _candidate_bootstrap_artifact_ids(candidate)
    actual_bootstrap_ids = set(lineage["bootstrap_artifact_ids"])
    source_hash = _file_sha256(sources.path)
    lineage_reasons: list[str] = []
    if lineage["source_manifest_id"] != registry.payload["source_manifest_id"]:
        lineage_reasons.append("source manifest id differs from the registry")
    if lineage["source_manifest_sha256"] != source_hash:
        lineage_reasons.append("source manifest SHA-256 does not match current bytes")
    if lineage["selection_registry_sha256"] != registry.sha256:
        lineage_reasons.append(
            "selection registry SHA-256 does not match current bytes"
        )
    if actual_bootstrap_ids != expected_bootstrap_ids:
        lineage_reasons.append(
            "bootstrap artifact ids do not exactly match candidate lineage"
        )
    if training_manifest["candidate_id"] != candidate_id:
        lineage_reasons.append("training-run manifest identifies another candidate")
    if training_manifest["source_manifest_id"] != lineage["source_manifest_id"]:
        lineage_reasons.append(
            "training-run manifest source id differs from report lineage"
        )
    if training_manifest["source_manifest_sha256"] != source_hash:
        lineage_reasons.append(
            "training-run manifest source SHA-256 does not match current bytes"
        )
    if set(lineage_components) != candidate_roles:
        lineage_reasons.append(
            "trained component roles do not exactly match candidate roles"
        )
    for role in sorted(set(manifest_components) & candidate_roles):
        manifest_component = manifest_components[role]
        candidate_component = candidate_components[role]
        if manifest_component["family"] != candidate_component["family"]:
            lineage_reasons.append(
                f"trained component family differs from candidate for role {role}"
            )
        manifest_refs = {
            (reference["source_id"], reference["artifact_id"])
            for reference in manifest_component["source_refs"]
        }
        candidate_refs = {
            (reference["source_id"], reference["artifact_id"])
            for reference in candidate_component["source_refs"]
        }
        if manifest_refs != candidate_refs:
            lineage_reasons.append(
                f"trained component source refs differ from candidate for role {role}"
            )

    parity = report["parity"]
    parity_components = {
        component["role"]: component for component in parity["components"]
    }
    if parity["training_run_manifest_sha256"] != training_manifest_hash:
        lineage_reasons.append(
            "parity evidence references a different training-run manifest"
        )
    if parity_components != lineage_components:
        lineage_reasons.append(
            "parity component identities differ from training-run identities"
        )

    calibration = report["calibration"]
    calibration_bundle = training_manifest["calibration_dataset_bundle"]
    if calibration["training_run_manifest_sha256"] != training_manifest_hash:
        lineage_reasons.append(
            "calibration evidence references a different training-run manifest"
        )
    if (
        calibration["dataset_inventory_sha256"]
        != calibration_bundle["inventory_file"]["sha256"]
    ):
        lineage_reasons.append(
            "calibration inventory differs from the training-run manifest"
        )
    if (
        calibration["group_split_sha256"]
        != calibration_bundle["group_split_file"]["sha256"]
    ):
        lineage_reasons.append(
            "calibration group split differs from the training-run manifest"
        )

    holdout = report["holdout"]
    leakage = report["leakage_audit"]
    training_bundle = training_manifest["training_dataset_bundle"]
    if leakage["training_run_manifest_sha256"] != training_manifest_hash:
        lineage_reasons.append(
            "leakage audit references a different training-run manifest"
        )
    if (
        leakage["training_dataset_inventory_sha256"]
        != training_bundle["inventory_file"]["sha256"]
    ):
        lineage_reasons.append(
            "leakage audit references a different training inventory"
        )
    if (
        leakage["training_group_split_sha256"]
        != training_bundle["group_split_file"]["sha256"]
    ):
        lineage_reasons.append(
            "leakage audit references a different training group split"
        )
    if (
        leakage["calibration_dataset_inventory_sha256"]
        != calibration_bundle["inventory_file"]["sha256"]
    ):
        lineage_reasons.append(
            "leakage audit references a different calibration inventory"
        )
    if (
        leakage["calibration_group_split_sha256"]
        != calibration_bundle["group_split_file"]["sha256"]
    ):
        lineage_reasons.append(
            "leakage audit references a different calibration group split"
        )
    if (
        leakage["holdout_case_inventory_sha256"]
        != holdout["case_inventory_file"]["sha256"]
    ):
        lineage_reasons.append("leakage audit references a different holdout inventory")
    if leakage["holdout_group_split_sha256"] != holdout["group_split_file"]["sha256"]:
        lineage_reasons.append(
            "leakage audit references a different holdout group split"
        )
    for metrics_name in (
        "primary_semantics",
        "restrictions",
        "temporal_behavior",
    ):
        metrics = report[metrics_name]
        metrics_components = {
            component["role"]: component for component in metrics["components"]
        }
        if metrics["training_run_manifest_sha256"] != training_manifest_hash:
            lineage_reasons.append(
                f"{metrics_name} references a different training-run manifest"
            )
        if metrics_components != lineage_components:
            lineage_reasons.append(
                f"{metrics_name} component identities differ from training-run identities"
            )
    for metrics_name in ("primary_semantics", "restrictions"):
        metrics = report[metrics_name]
        if (
            metrics["holdout_case_inventory_sha256"]
            != holdout["case_inventory_file"]["sha256"]
        ):
            lineage_reasons.append(
                f"{metrics_name} references a different holdout inventory"
            )

    mobile = report["mobile"]
    if mobile["training_run_manifest_sha256"] != training_manifest_hash:
        lineage_reasons.append(
            "mobile pack references a different training-run manifest"
        )
    required_platforms = set(candidate["supported_platforms"]) - {"offline"}
    expected_mobile_hashes: dict[tuple[str, str], str] = {}
    for role, component in lineage_components.items():
        if "ios" in required_platforms:
            expected_mobile_hashes[(role, "ios")] = component["coreml_sha256"]
        if "android" in required_platforms:
            expected_mobile_hashes[(role, "android")] = component["litert_sha256"]
    actual_mobile_hashes = {
        (artifact["role"], artifact["platform"]): artifact["file"]["sha256"]
        for artifact in mobile["artifacts"]
    }
    if actual_mobile_hashes != expected_mobile_hashes:
        lineage_reasons.append(
            "mobile artifacts do not exactly match component/platform identities"
        )
    mobile_hashes_by_platform = {
        platform: {
            sha256
            for (role, artifact_platform), sha256 in actual_mobile_hashes.items()
            if artifact_platform == platform
        }
        for platform in required_platforms
    }
    for tier in mobile["device_tiers"]:
        if tier["training_run_manifest_sha256"] != training_manifest_hash:
            lineage_reasons.append(
                f"device tier {tier['tier_id']} references a different training-run manifest"
            )
        expected_hashes = mobile_hashes_by_platform.get(tier["platform"], set())
        if set(tier["artifact_sha256s"]) != expected_hashes:
            lineage_reasons.append(
                f"device tier {tier['tier_id']} artifact identities differ from its mobile pack"
            )
    gates.append(
        _gate(
            "lineage",
            "pass" if not lineage_reasons else "fail",
            {
                "bootstrap_artifact_ids": sorted(actual_bootstrap_ids),
                "component_roles": sorted(lineage_components),
                "training_run_manifest_sha256": training_manifest_hash,
                "selection_registry_sha256": lineage["selection_registry_sha256"],
                "source_manifest_sha256": lineage["source_manifest_sha256"],
            },
            {
                "bootstrap_artifact_ids": sorted(expected_bootstrap_ids),
                "component_roles": sorted(candidate_roles),
                "training_run_manifest_sha256": training_manifest_hash,
                "selection_registry_sha256": registry.sha256,
                "source_manifest_sha256": source_hash,
            },
            lineage_reasons,
        )
    )

    dataset_gate_ids: set[str] = set()
    dataset_source_ids: set[str] = set()
    for bundle_field in (
        "training_dataset_bundle",
        "calibration_dataset_bundle",
    ):
        bundle = training_manifest[bundle_field]
        dataset_source_ids.update(bundle["source_ids"])
        dataset_gate_ids.update(
            _dataset_bundle_license_gates(
                bundle,
                sources,
                f"training-run manifest.{bundle_field}",
            )
        )
    required_scorecard_license_gates = _expand_license_gate_ids(
        set(candidate["required_license_gate_ids"]) | dataset_gate_ids,
        sources.payload["release_policy"]["license_gates"],
    )
    missing_license_gates = sorted(required_scorecard_license_gates - approved)
    gates.append(
        _gate(
            "licensing",
            "pass" if not missing_license_gates else "fail",
            {
                "approved_license_gate_ids": sorted(approved),
                "training_dataset_source_ids": sorted(dataset_source_ids),
            },
            {"required_license_gate_ids": sorted(required_scorecard_license_gates)},
            [
                f"unapproved license gate: {gate_id}"
                for gate_id in missing_license_gates
            ],
        )
    )

    holdout = report["holdout"]
    approved_corpus_pins = {
        "holdout_dataset_id": policy["approved_holdout_dataset_id"],
        "holdout_case_inventory_sha256": policy[
            "approved_holdout_case_inventory_sha256"
        ],
        "holdout_group_split_sha256": policy["approved_holdout_group_split_sha256"],
        "parity_case_inventory_sha256": policy["approved_parity_case_inventory_sha256"],
        "parity_reference_outputs_sha256": policy[
            "approved_parity_reference_outputs_sha256"
        ],
    }
    observed_corpus_pins = {
        "holdout_dataset_id": holdout["dataset_id"],
        "holdout_case_inventory_sha256": holdout["case_inventory_file"]["sha256"],
        "holdout_group_split_sha256": holdout["group_split_file"]["sha256"],
        "parity_case_inventory_sha256": parity["case_inventory_file"]["sha256"],
        "parity_reference_outputs_sha256": parity["reference_outputs_file"]["sha256"],
    }
    corpus_reasons: list[str] = []
    if any(value is None for value in approved_corpus_pins.values()):
        corpus_status = "pending_policy"
        corpus_reasons.append(
            "versioned trusted holdout and parity corpus pins are pending approval"
        )
    else:
        for field, approved_value in approved_corpus_pins.items():
            if observed_corpus_pins[field] != approved_value:
                corpus_reasons.append(f"{field} differs from the approved corpus pin")
        corpus_status = "pass" if not corpus_reasons else "fail"
    gates.append(
        _gate(
            "approved_evaluation_corpora",
            corpus_status,
            observed_corpus_pins,
            approved_corpus_pins,
            corpus_reasons,
        )
    )

    approved_device_profiles = policy["approved_device_tier_profiles"]
    measured_profiles = {
        tier["tier_id"]: {field: tier[field] for field in DEVICE_PROFILE_FIELDS}
        for tier in mobile["device_tiers"]
    }
    supported_profile_ids = set(mobile["supported_device_tier_ids"])
    device_profile_reasons: list[str] = []
    if approved_device_profiles is None:
        device_profile_status = "pending_policy"
        device_profile_reasons.append(
            "versioned device tier profiles are pending approval"
        )
        expected_profiles: dict[str, dict[str, Any]] = {}
    else:
        expected_profiles = {
            profile["tier_id"]: profile for profile in approved_device_profiles
        }
        missing_profile_ids = sorted(set(expected_profiles) - set(measured_profiles))
        unexpected_profile_ids = sorted(set(measured_profiles) - set(expected_profiles))
        if missing_profile_ids:
            device_profile_reasons.append(
                "missing approved device tiers: " + ", ".join(missing_profile_ids)
            )
        if unexpected_profile_ids:
            device_profile_reasons.append(
                "unapproved device tiers were substituted: "
                + ", ".join(unexpected_profile_ids)
            )
        if supported_profile_ids != set(expected_profiles):
            device_profile_reasons.append(
                "supported device tier ids do not exactly match approved profiles"
            )
        for tier_id in sorted(set(expected_profiles) & set(measured_profiles)):
            if measured_profiles[tier_id] != expected_profiles[tier_id]:
                device_profile_reasons.append(
                    f"device tier profile differs from approved identity: {tier_id}"
                )
        device_profile_status = "pass" if not device_profile_reasons else "fail"
    gates.append(
        _gate(
            "approved_device_tier_profiles",
            device_profile_status,
            {
                "profiles": [
                    {
                        **measured_profiles[tier["tier_id"]],
                        "benchmark_run_id": tier["benchmark_run_id"],
                        "device_instance_id": tier["device_instance_id"],
                    }
                    for tier in sorted(
                        mobile["device_tiers"], key=lambda value: value["tier_id"]
                    )
                ],
                "supported_device_tier_ids": sorted(supported_profile_ids),
            },
            {
                "profiles": [
                    expected_profiles[tier_id] for tier_id in sorted(expected_profiles)
                ]
                if approved_device_profiles is not None
                else None,
            },
            device_profile_reasons,
        )
    )

    case_inventory = holdout["case_inventory"]
    holdout_reasons: list[str] = []
    if holdout["kind"] != "real_route_held_out":
        holdout_reasons.append("holdout is not real route-held-out data")
    if not holdout["frozen"]:
        holdout_reasons.append("holdout is not frozen")
    if holdout["threshold_fitted_on_holdout"]:
        holdout_reasons.append("a threshold was fitted on the scorecard holdout")
    if holdout["sample_count"] <= 0 or holdout["real_case_count"] <= 0:
        holdout_reasons.append("real holdout denominator is zero")
    if holdout["synthetic_case_count"] != 0:
        holdout_reasons.append("synthetic cases are present in scorecard evidence")
    if (
        holdout["sample_count"]
        != holdout["real_case_count"] + holdout["synthetic_case_count"]
    ):
        holdout_reasons.append("holdout raw case counts do not sum to sample_count")
    if holdout["independent_route_count"] <= 0:
        holdout_reasons.append("independent route denominator is zero")
    if case_inventory["dataset_id"] != holdout["dataset_id"]:
        holdout_reasons.append("case-inventory dataset id differs from holdout")
    if case_inventory["sample_count"] != holdout["sample_count"]:
        holdout_reasons.append("case-inventory sample count differs from holdout")
    gates.append(
        _gate(
            "real_route_holdout",
            "pass" if not holdout_reasons else "fail",
            {
                "dataset_id": holdout["dataset_id"],
                "case_inventory_sha256": holdout["case_inventory_file"]["sha256"],
                "group_split_sha256": holdout["group_split_file"]["sha256"],
                "independent_route_count": holdout["independent_route_count"],
                "kind": holdout["kind"],
                "real_case_count": holdout["real_case_count"],
                "sample_count": holdout["sample_count"],
                "synthetic_case_count": holdout["synthetic_case_count"],
            },
            {
                "frozen": True,
                "kind": "real_route_held_out",
                "minimum_independent_route_count": 1,
                "minimum_real_case_count": 1,
                "synthetic_case_count": 0,
                "threshold_fitted_on_holdout": False,
            },
            holdout_reasons,
        )
    )

    strata_by_name = {item["name"]: item for item in holdout["strata"]}
    inventory_strata_by_name = {item["name"]: item for item in case_inventory["strata"]}
    strata_reasons: list[str] = []
    missing_inventory_strata = sorted(
        set(inventory_strata_by_name) - set(strata_by_name)
    )
    unexpected_strata = sorted(set(strata_by_name) - set(inventory_strata_by_name))
    if missing_inventory_strata:
        strata_reasons.append(
            "holdout is missing case-inventory strata: "
            + ", ".join(missing_inventory_strata)
        )
    if unexpected_strata:
        strata_reasons.append(
            "holdout has strata outside case inventory: " + ", ".join(unexpected_strata)
        )
    missing_required_inventory = sorted(
        set(policy["required_real_route_strata"]) - set(inventory_strata_by_name)
    )
    if missing_required_inventory:
        strata_reasons.append(
            "case inventory lacks required strata: "
            + ", ".join(missing_required_inventory)
        )
    for name in sorted(inventory_strata_by_name):
        stratum = strata_by_name.get(name)
        if stratum is None:
            continue
        if stratum["case_count"] != inventory_strata_by_name[name]["case_count"]:
            strata_reasons.append(
                f"holdout stratum case count differs from case inventory: {name}"
            )
        if stratum["case_count"] <= 0:
            strata_reasons.append(f"zero denominator for required stratum: {name}")
        if stratum["failure_count"] > stratum["case_count"]:
            strata_reasons.append(
                f"failure_count exceeds case_count for stratum: {name}"
            )
        elif stratum["failure_count"] != 0:
            strata_reasons.append(f"field regression failures in stratum: {name}")
    gates.append(
        _gate(
            "field_regression_strata",
            "pass" if not strata_reasons else "fail",
            {
                "strata": [
                    {
                        "case_count": item["case_count"],
                        "failure_count": item["failure_count"],
                        "name": item["name"],
                    }
                    for item in sorted(
                        holdout["strata"], key=lambda value: value["name"]
                    )
                ]
            },
            {
                "required_strata": sorted(policy["required_real_route_strata"]),
                "required_inventory_strata": sorted(inventory_strata_by_name),
                "minimum_cases_per_stratum": 1,
                "maximum_failures_per_stratum": 0,
            },
            strata_reasons,
        )
    )

    leakage = report["leakage_audit"]
    leakage_fields = (
        "capture_group_overlap_count",
        "physical_sign_cluster_overlap_count",
        "near_duplicate_overlap_count",
    )
    leakage_reasons = [
        f"{field} is nonzero" for field in leakage_fields if leakage[field] != 0
    ]
    gates.append(
        _gate(
            "leakage",
            "pass" if not leakage_reasons else "fail",
            {field: leakage[field] for field in leakage_fields},
            {field: 0 for field in leakage_fields},
            leakage_reasons,
        )
    )

    primary = report["primary_semantics"]
    primary_denominator = (
        primary["true_positive_count"] + primary["false_positive_count"]
    )
    primary_lower: float | None = None
    primary_reasons: list[str] = []
    if primary_denominator <= 0:
        primary_reasons.append("confirmed numeric precision denominator is zero")
    else:
        primary_lower = wilson_lower_bound(
            primary["true_positive_count"],
            primary_denominator,
            policy["wilson_confidence_level"],
        )
        if primary_lower < policy["minimum_confirmed_numeric_precision_lower_bound"]:
            primary_reasons.append("Wilson precision lower bound is below threshold")
    if primary["confirmed_numeric_prediction_count"] != primary_denominator:
        primary_reasons.append("confirmed numeric raw count differs from TP + FP")
    gates.append(
        _gate(
            "confirmed_numeric_precision",
            "pass" if not primary_reasons else "fail",
            {
                "denominator": primary_denominator,
                "false_positive_count": primary["false_positive_count"],
                "true_positive_count": primary["true_positive_count"],
                "wilson_lower_bound": _rounded(primary_lower),
            },
            {
                "confidence_level": policy["wilson_confidence_level"],
                "minimum_wilson_lower_bound": policy[
                    "minimum_confirmed_numeric_precision_lower_bound"
                ],
            },
            primary_reasons,
        )
    )
    gates.append(
        _recall_coverage_gate(
            "confirmed_numeric_recall_coverage",
            primary,
            holdout,
            "primary",
            policy["required_real_route_strata"],
            policy["minimum_confirmed_numeric_recall_lower_bound"],
            policy["wilson_confidence_level"],
        )
    )

    dangerous_denominator = primary["confirmed_numeric_prediction_count"]
    dangerous_rate: float | None = None
    dangerous_reasons: list[str] = []
    if dangerous_denominator <= 0:
        dangerous_reasons.append("dangerous-substitution denominator is zero")
    else:
        dangerous_rate = primary["dangerous_substitution_count"] / dangerous_denominator
        if dangerous_rate > policy["maximum_dangerous_substitution_rate"]:
            dangerous_reasons.append("dangerous-substitution rate exceeds threshold")
    if primary["dangerous_substitution_count"] > primary["false_positive_count"]:
        dangerous_reasons.append("dangerous substitutions exceed all false positives")
    gates.append(
        _gate(
            "dangerous_substitutions",
            "pass" if not dangerous_reasons else "fail",
            {
                "dangerous_substitution_count": primary["dangerous_substitution_count"],
                "denominator": dangerous_denominator,
                "rate": _rounded(dangerous_rate),
            },
            {"maximum_rate": policy["maximum_dangerous_substitution_rate"]},
            dangerous_reasons,
        )
    )

    restrictions = report["restrictions"]
    restriction_denominator = (
        restrictions["true_positive_count"] + restrictions["false_positive_count"]
    )
    restriction_lower: float | None = None
    restriction_reasons: list[str] = []
    if restriction_denominator <= 0:
        restriction_reasons.append("resolved restriction precision denominator is zero")
    else:
        restriction_lower = wilson_lower_bound(
            restrictions["true_positive_count"],
            restriction_denominator,
            policy["wilson_confidence_level"],
        )
        if (
            restriction_lower
            < policy["minimum_resolved_restriction_precision_lower_bound"]
        ):
            restriction_reasons.append(
                "Wilson restriction precision lower bound is below threshold"
            )
    if restrictions["resolved_prediction_count"] != restriction_denominator:
        restriction_reasons.append(
            "resolved restriction raw count differs from TP + FP"
        )
    gates.append(
        _gate(
            "resolved_restriction_precision",
            "pass" if not restriction_reasons else "fail",
            {
                "denominator": restriction_denominator,
                "false_positive_count": restrictions["false_positive_count"],
                "true_positive_count": restrictions["true_positive_count"],
                "wilson_lower_bound": _rounded(restriction_lower),
            },
            {
                "confidence_level": policy["wilson_confidence_level"],
                "minimum_wilson_lower_bound": policy[
                    "minimum_resolved_restriction_precision_lower_bound"
                ],
            },
            restriction_reasons,
        )
    )
    gates.append(
        _recall_coverage_gate(
            "resolved_restriction_recall_coverage",
            restrictions,
            holdout,
            "restriction",
            policy["required_real_route_strata"],
            policy["minimum_resolved_restriction_recall_lower_bound"],
            policy["wilson_confidence_level"],
        )
    )

    unresolved_count = restrictions["unresolved_promoted_unconditional_count"]
    gates.append(
        _gate(
            "unresolved_restriction_safety",
            "pass" if unresolved_count == 0 else "fail",
            {"unresolved_promoted_unconditional_count": unresolved_count},
            {"maximum_count": 0},
            []
            if unresolved_count == 0
            else ["an unresolved plate became an unconditional limit"],
        )
    )

    calibration = report["calibration"]
    calibration_total = sum(item["sample_count"] for item in calibration["bins"])
    ece: float | None = None
    calibration_reasons: list[str] = []
    if calibration["sample_count"] <= 0 or calibration_total <= 0:
        calibration_reasons.append("calibration denominator is zero")
    if calibration_total != calibration["sample_count"]:
        calibration_reasons.append("calibration bin counts do not sum to sample_count")
    indexes = sorted(item["index"] for item in calibration["bins"])
    if indexes != list(range(len(indexes))):
        calibration_reasons.append(
            "calibration bin indexes are not contiguous from zero"
        )
    for item in calibration["bins"]:
        if item["sample_count"] <= 0:
            calibration_reasons.append(
                f"calibration bin {item['index']} has a zero denominator"
            )
        if item["correct_count"] > item["sample_count"]:
            calibration_reasons.append(
                f"calibration bin {item['index']} correct_count exceeds sample_count"
            )
        if item["confidence_sum"] > item["sample_count"]:
            calibration_reasons.append(
                f"calibration bin {item['index']} confidence_sum exceeds sample_count"
            )
    if calibration["sample_count"] > 0:
        ece = (
            sum(
                abs(item["confidence_sum"] - item["correct_count"])
                for item in calibration["bins"]
            )
            / calibration["sample_count"]
        )
        if ece > policy["maximum_expected_calibration_error"]:
            calibration_reasons.append("expected calibration error exceeds threshold")
    gates.append(
        _gate(
            "calibration",
            "pass" if not calibration_reasons else "fail",
            {
                "bin_count": len(calibration["bins"]),
                "expected_calibration_error": _rounded(ece),
                "sample_count": calibration["sample_count"],
            },
            {
                "maximum_expected_calibration_error": policy[
                    "maximum_expected_calibration_error"
                ]
            },
            calibration_reasons,
        )
    )

    parity_evidence = report["parity"]
    parity = report.get("_verified_parity_metrics")
    _require(
        isinstance(parity, dict),
        "normalized parity artifacts must be verified before evaluation",
    )
    parity_reasons: list[str] = []
    if parity["case_count"] < policy["minimum_parity_case_count"]:
        parity_reasons.append("parity case count is below threshold")
    if (
        parity["reference_output_count"]
        < policy["minimum_parity_reference_output_count"]
    ):
        parity_reasons.append("parity reference-output count is below threshold")
    if parity["reference_evaluated_case_count"] != parity["case_count"]:
        parity_reasons.append("reference outputs did not evaluate every parity case")
    if parity["reference_missing_case_count"] != 0:
        parity_reasons.append("reference outputs are missing parity cases")
    if parity["reference_unexpected_case_count"] != 0:
        parity_reasons.append("reference outputs contain unexpected parity cases")
    runtime_counts = {item["runtime"]: item for item in parity["runtime_counts"]}
    if set(runtime_counts) != {"coreml", "litert", "onnx"}:
        parity_reasons.append(
            "parity evidence does not cover ONNX, Core ML, and LiteRT"
        )
    for runtime_name, runtime in sorted(runtime_counts.items()):
        if runtime["evaluated_case_count"] != parity["case_count"]:
            parity_reasons.append(f"{runtime_name} did not evaluate every parity case")
        if runtime["missing_case_count"] != 0:
            parity_reasons.append(f"{runtime_name} is missing parity cases")
        if runtime["unexpected_case_count"] != 0:
            parity_reasons.append(f"{runtime_name} evaluated unexpected parity cases")
        if (
            runtime["matched_reference_output_count"]
            + runtime["missing_reference_output_count"]
            != parity["reference_output_count"]
        ):
            parity_reasons.append(
                f"{runtime_name} reference output counts are inconsistent"
            )
        if (
            runtime["matched_reference_output_count"]
            + runtime["unexpected_output_count"]
            != runtime["output_count"]
        ):
            parity_reasons.append(
                f"{runtime_name} emitted output counts are inconsistent"
            )
        if runtime["missing_reference_output_count"] != 0:
            parity_reasons.append(f"{runtime_name} is missing reference outputs")
        if runtime["unexpected_output_count"] != 0:
            parity_reasons.append(f"{runtime_name} emitted unexpected outputs")
    if parity["semantic_mismatch_count"] > policy["maximum_semantic_mismatch_count"]:
        parity_reasons.append("semantic mismatch count exceeds threshold")
    if parity["assembly_mismatch_count"] > policy["maximum_assembly_mismatch_count"]:
        parity_reasons.append("assembly mismatch count exceeds threshold")
    if parity["semantic_mismatch_count"] > parity["case_count"]:
        parity_reasons.append("semantic mismatch count exceeds parity case count")
    if parity["assembly_mismatch_count"] > parity["case_count"]:
        parity_reasons.append("assembly mismatch count exceeds parity case count")
    if parity["minimum_matched_box_iou"] is None:
        parity_reasons.append("no matched outputs exist for box-IoU parity")
    elif parity["minimum_matched_box_iou"] < policy["minimum_matched_box_iou"]:
        parity_reasons.append("minimum matched-box IoU is below threshold")
    if parity["maximum_calibrated_confidence_delta"] is None:
        parity_reasons.append("no matched outputs exist for confidence parity")
    elif (
        parity["maximum_calibrated_confidence_delta"]
        > policy["maximum_calibrated_confidence_delta"]
    ):
        parity_reasons.append("maximum calibrated-confidence delta exceeds threshold")
    gates.append(
        _gate(
            "cross_runtime_parity",
            "pass" if not parity_reasons else "fail",
            {
                "assembly_mismatch_count": parity["assembly_mismatch_count"],
                "case_count": parity["case_count"],
                "case_inventory_sha256": parity_evidence["case_inventory_file"][
                    "sha256"
                ],
                "maximum_calibrated_confidence_delta": parity[
                    "maximum_calibrated_confidence_delta"
                ],
                "minimum_matched_box_iou": parity["minimum_matched_box_iou"],
                "reference_output_count": parity["reference_output_count"],
                "reference_outputs_sha256": parity_evidence["reference_outputs_file"][
                    "sha256"
                ],
                "reference_evaluated_case_count": parity[
                    "reference_evaluated_case_count"
                ],
                "reference_missing_case_count": parity["reference_missing_case_count"],
                "reference_unexpected_case_count": parity[
                    "reference_unexpected_case_count"
                ],
                "runtime_counts": [
                    {
                        "assembly_mismatch_count": runtime["assembly_mismatch_count"],
                        "evaluated_case_count": runtime["evaluated_case_count"],
                        "matched_reference_output_count": runtime[
                            "matched_reference_output_count"
                        ],
                        "missing_reference_output_count": runtime[
                            "missing_reference_output_count"
                        ],
                        "missing_case_count": runtime["missing_case_count"],
                        "output_count": runtime["output_count"],
                        "runtime": runtime["runtime"],
                        "semantic_mismatch_count": runtime["semantic_mismatch_count"],
                        "unexpected_case_count": runtime["unexpected_case_count"],
                        "unexpected_output_count": runtime["unexpected_output_count"],
                    }
                    for runtime in sorted(
                        parity["runtime_counts"], key=lambda value: value["runtime"]
                    )
                ],
                "semantic_mismatch_count": parity["semantic_mismatch_count"],
            },
            {
                "maximum_assembly_mismatch_count": policy[
                    "maximum_assembly_mismatch_count"
                ],
                "maximum_calibrated_confidence_delta": policy[
                    "maximum_calibrated_confidence_delta"
                ],
                "maximum_semantic_mismatch_count": policy[
                    "maximum_semantic_mismatch_count"
                ],
                "minimum_case_count": policy["minimum_parity_case_count"],
                "minimum_matched_box_iou": policy["minimum_matched_box_iou"],
                "minimum_reference_output_count": policy[
                    "minimum_parity_reference_output_count"
                ],
                "required_runtimes": ["coreml", "litert", "onnx"],
            },
            parity_reasons,
        )
    )

    mobile = report["mobile"]
    artifact_total = sum(item["size_bytes"] for item in mobile["artifacts"])
    size_reasons: list[str] = []
    if mobile["pack_size_bytes"] <= 0:
        size_reasons.append("pack size is zero")
    if not mobile["artifacts"] or any(
        item["size_bytes"] <= 0 for item in mobile["artifacts"]
    ):
        size_reasons.append("mobile artifact evidence is empty or zero-sized")
    if mobile["pack_size_bytes"] > policy["maximum_pack_bytes"]:
        size_reasons.append("pack size exceeds threshold")
    if mobile["pack_size_bytes"] != artifact_total:
        size_reasons.append("pack size does not equal the verified artifact total")
    if artifact_total > policy["maximum_artifact_total_bytes"]:
        size_reasons.append("mobile artifact total size exceeds threshold")
    gates.append(
        _gate(
            "mobile_size",
            "pass" if not size_reasons else "fail",
            {
                "artifact_total_bytes": artifact_total,
                "pack_size_bytes": mobile["pack_size_bytes"],
            },
            {
                "maximum_artifact_total_bytes": policy["maximum_artifact_total_bytes"],
                "maximum_pack_bytes": policy["maximum_pack_bytes"],
            },
            size_reasons,
        )
    )

    supported_ids = set(mobile["supported_device_tier_ids"])
    tiers_by_id = {item["tier_id"]: item for item in mobile["device_tiers"]}
    measured_ids = set(tiers_by_id)
    latency_reasons: list[str] = []
    if not supported_ids:
        latency_reasons.append("no supported device tier is declared")
    missing_tiers = sorted(supported_ids - measured_ids)
    extra_tiers = sorted(measured_ids - supported_ids)
    if missing_tiers:
        latency_reasons.append(
            f"missing device-tier measurements: {', '.join(missing_tiers)}"
        )
    if extra_tiers:
        latency_reasons.append(
            f"undeclared device-tier measurements: {', '.join(extra_tiers)}"
        )
    measured_platforms = {tier["platform"] for tier in tiers_by_id.values()}
    required_platforms = set(candidate["supported_platforms"]) - {"offline"}
    missing_platforms = sorted(required_platforms - measured_platforms)
    if missing_platforms:
        latency_reasons.append(
            f"missing supported platform measurements: {', '.join(missing_platforms)}"
        )
    for tier_id in sorted(supported_ids & measured_ids):
        tier = tiers_by_id[tier_id]
        inference_rate = (
            tier["detector_inference_count"] / tier["drive_duration_seconds"]
        )
        if tier["detector_inference_count"] < policy["minimum_device_inference_count"]:
            latency_reasons.append(
                f"{tier_id} detector inference count is below threshold"
            )
        if (
            tier["end_to_end_inference_count"]
            < policy["minimum_device_inference_count"]
        ):
            latency_reasons.append(
                f"{tier_id} end-to-end inference count is below threshold"
            )
        if tier["detector_inference_count"] > tier["camera_frame_count"]:
            latency_reasons.append(
                f"{tier_id} detector inferences exceed captured camera frames"
            )
        if tier["end_to_end_inference_count"] != tier["detector_inference_count"]:
            latency_reasons.append(
                f"{tier_id} detector and end-to-end inference counts differ"
            )
        if inference_rate < policy["minimum_detector_inference_rate_hz"]:
            latency_reasons.append(
                f"{tier_id} sustained detector inference rate is below threshold"
            )
        if inference_rate > policy["maximum_detector_inference_rate_hz"]:
            latency_reasons.append(
                f"{tier_id} sustained detector inference rate exceeds threshold"
            )
        if tier["detector_p95_ms"] > policy["maximum_detector_p95_ms"]:
            latency_reasons.append(f"{tier_id} detector p95 exceeds threshold")
        if tier["end_to_end_p95_ms"] > policy["maximum_end_to_end_p95_ms"]:
            latency_reasons.append(f"{tier_id} end-to-end p95 exceeds threshold")
    gates.append(
        _gate(
            "device_latency",
            "pass" if not latency_reasons else "fail",
            {
                "device_tiers": [
                    {
                        "detector_inference_count": tier["detector_inference_count"],
                        "detector_p95_ms": tier["detector_p95_ms"],
                        "detector_inference_rate_hz": _rounded(
                            tier["detector_inference_count"]
                            / tier["drive_duration_seconds"]
                        ),
                        "end_to_end_inference_count": tier[
                            "end_to_end_inference_count"
                        ],
                        "end_to_end_p95_ms": tier["end_to_end_p95_ms"],
                        "platform": tier["platform"],
                        "tier_id": tier["tier_id"],
                    }
                    for tier in sorted(
                        mobile["device_tiers"], key=lambda value: value["tier_id"]
                    )
                ]
            },
            {
                "maximum_detector_p95_ms": policy["maximum_detector_p95_ms"],
                "maximum_end_to_end_p95_ms": policy["maximum_end_to_end_p95_ms"],
                "minimum_inference_count": policy["minimum_device_inference_count"],
                "minimum_detector_inference_rate_hz": policy[
                    "minimum_detector_inference_rate_hz"
                ],
                "maximum_detector_inference_rate_hz": policy[
                    "maximum_detector_inference_rate_hz"
                ],
                "required_platforms": sorted(required_platforms),
            },
            latency_reasons,
        )
    )

    runtime_reasons: list[str] = []
    for tier_id in sorted(supported_ids & measured_ids):
        tier = tiers_by_id[tier_id]
        camera_frame_rate = tier["camera_frame_count"] / tier["drive_duration_seconds"]
        dropped_rate = tier["dropped_frame_count"] / tier["camera_frame_count"]
        backpressure_rate = (
            tier["backpressure_event_count"] / tier["camera_frame_count"]
        )
        if (
            tier["drive_duration_seconds"]
            < policy["minimum_device_drive_duration_seconds"]
        ):
            runtime_reasons.append(f"{tier_id} drive duration is below threshold")
        if camera_frame_rate < policy["minimum_camera_frame_rate_hz"]:
            runtime_reasons.append(f"{tier_id} camera capture rate is below threshold")
        if tier["dropped_frame_count"] > tier["camera_frame_count"]:
            runtime_reasons.append(f"{tier_id} dropped frames exceed camera frames")
        if dropped_rate > policy["maximum_dropped_frame_rate"]:
            runtime_reasons.append(f"{tier_id} dropped-frame rate exceeds threshold")
        if tier["backpressure_event_count"] > tier["camera_frame_count"]:
            runtime_reasons.append(
                f"{tier_id} backpressure events exceed camera frames"
            )
        if backpressure_rate > policy["maximum_backpressure_event_rate"]:
            runtime_reasons.append(
                f"{tier_id} backpressure-event rate exceeds threshold"
            )
        if tier["peak_memory_bytes"] > policy["maximum_device_peak_memory_bytes"]:
            runtime_reasons.append(f"{tier_id} peak memory exceeds threshold")
        if tier["maximum_in_flight"] != 1:
            runtime_reasons.append(
                f"{tier_id} did not prove exactly one inference in flight"
            )
        if not tier["thermal_downshift_verified"]:
            runtime_reasons.append(f"{tier_id} lacks thermal-downshift evidence")
        if not tier["recording_unaffected"]:
            runtime_reasons.append(f"{tier_id} did not preserve recording")
    gates.append(
        _gate(
            "runtime_safety",
            "pass"
            if not runtime_reasons and bool(supported_ids) and not missing_tiers
            else "fail",
            {
                "device_tiers": [
                    {
                        "maximum_in_flight": tier["maximum_in_flight"],
                        "backpressure_event_count": tier["backpressure_event_count"],
                        "backpressure_event_rate": _rounded(
                            tier["backpressure_event_count"]
                            / tier["camera_frame_count"]
                        ),
                        "camera_frame_count": tier["camera_frame_count"],
                        "camera_frame_rate_hz": _rounded(
                            tier["camera_frame_count"] / tier["drive_duration_seconds"]
                        ),
                        "drive_duration_seconds": tier["drive_duration_seconds"],
                        "dropped_frame_count": tier["dropped_frame_count"],
                        "dropped_frame_rate": _rounded(
                            tier["dropped_frame_count"] / tier["camera_frame_count"]
                        ),
                        "peak_memory_bytes": tier["peak_memory_bytes"],
                        "recording_unaffected": tier["recording_unaffected"],
                        "thermal_downshift_verified": tier[
                            "thermal_downshift_verified"
                        ],
                        "tier_id": tier["tier_id"],
                    }
                    for tier in sorted(
                        mobile["device_tiers"], key=lambda value: value["tier_id"]
                    )
                ]
            },
            {
                "maximum_in_flight": 1,
                "maximum_backpressure_event_rate": policy[
                    "maximum_backpressure_event_rate"
                ],
                "maximum_dropped_frame_rate": policy["maximum_dropped_frame_rate"],
                "maximum_peak_memory_bytes": policy["maximum_device_peak_memory_bytes"],
                "minimum_drive_duration_seconds": policy[
                    "minimum_device_drive_duration_seconds"
                ],
                "minimum_camera_frame_rate_hz": policy["minimum_camera_frame_rate_hz"],
                "recording_unaffected": True,
                "thermal_downshift_verified": True,
            },
            runtime_reasons
            or (
                []
                if supported_ids and not missing_tiers
                else ["complete supported-tier runtime evidence is required"]
            ),
        )
    )

    temporal = report["temporal_behavior"]
    temporal_definitions = (
        (
            "temporal_duplicate_confirmations",
            temporal["duplicate_confirmation_count"],
            temporal["physical_assembly_count"],
            policy["maximum_duplicate_confirmation_rate"],
            "duplicate-confirmation",
        ),
        (
            "temporal_wrong_way_confirmations",
            temporal["wrong_way_confirmation_count"],
            temporal["direction_evaluable_confirmation_count"],
            policy["maximum_wrong_way_confirmation_rate"],
            "wrong-way-confirmation",
        ),
    )
    for gate_id, numerator, denominator, threshold, label in temporal_definitions:
        reasons: list[str] = []
        rate: float | None = None
        if denominator <= 0:
            reasons.append(f"{label} denominator is zero")
        elif numerator > denominator:
            reasons.append(f"{label} count exceeds denominator")
        else:
            rate = numerator / denominator
        if reasons:
            status = "fail"
        elif threshold is None:
            status = "pending_policy"
            reasons.append("a versioned acceptance threshold has not been approved")
        elif rate is not None and rate <= threshold:
            status = "pass"
        else:
            status = "fail"
            reasons.append(f"{label} rate exceeds threshold")
        gates.append(
            _gate(
                gate_id,
                status,
                {
                    "count": numerator,
                    "denominator": denominator,
                    "rate": _rounded(rate),
                },
                {"maximum_rate": threshold},
                reasons,
            )
        )

    model_scorecard_eligible = all(gate["status"] == "pass" for gate in gates)
    return {
        "candidate_id": candidate_id,
        "decision": (
            "model_scorecard_eligible"
            if model_scorecard_eligible
            else "model_scorecard_blocked"
        ),
        "evaluated_at": report["evaluated_at"],
        "gate_summary": {
            "fail": sum(gate["status"] == "fail" for gate in gates),
            "pass": sum(gate["status"] == "pass" for gate in gates),
            "pending_policy": sum(gate["status"] == "pending_policy" for gate in gates),
        },
        "gates": gates,
        "registry_id": registry.payload["registry_id"],
        "model_scorecard_eligible": model_scorecard_eligible,
        "report_id": report["report_id"],
        "selected_candidate_id": registry.payload["selected_candidate_id"],
        "selection_mutated": False,
    }


def registry_status(
    registry: ValidatedSelectionRegistry,
    sources: ValidatedSourceManifest,
) -> dict[str, Any]:
    license_defaults = sources.payload["release_policy"]["license_gates"]
    candidates: list[dict[str, Any]] = []
    for candidate_id in sorted(registry.candidates_by_id):
        candidate = registry.candidates_by_id[candidate_id]
        unpinned = sorted(
            component["family"]
            for component in candidate["components"]
            if component["pin_status"] == "unpinned"
        )
        candidates.append(
            {
                "blocking_reasons": list(candidate["blocking_reasons"]),
                "candidate_id": candidate_id,
                "eligible_for_selection": candidate["eligible_for_selection"],
                "lane": candidate["lane"],
                "pipeline": candidate["pipeline"],
                "required_license_gates": [
                    {
                        "default_decision": license_defaults[gate_id][
                            "default_decision"
                        ],
                        "gate_id": gate_id,
                    }
                    for gate_id in sorted(candidate["required_license_gate_ids"])
                ],
                "runtime_status": {
                    platform: {
                        "blockers": list(
                            candidate["runtime_status"][platform]["blockers"]
                        ),
                        "status": candidate["runtime_status"][platform]["status"],
                    }
                    for platform in sorted(candidate["runtime_status"])
                },
                "status": candidate["status"],
                "supported_platforms": list(candidate["supported_platforms"]),
                "unpinned_components": unpinned,
            }
        )
    return {
        "candidate_count": len(candidates),
        "candidates": candidates,
        "registry_id": registry.payload["registry_id"],
        "registry_sha256": registry.sha256,
        "scorecard_policy": dict(registry.payload["scorecard_policy"]),
        "selected_candidate_id": registry.payload["selected_candidate_id"],
        "selection_status": registry.payload["selection_status"],
        "source_manifest_id": sources.payload["manifest_id"],
        "source_manifest_sha256": _file_sha256(sources.path),
        "target_candidate_id": registry.payload["target_candidate_id"],
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--registry", default=str(DEFAULT_REGISTRY), help="model-selection registry"
    )
    parser.add_argument(
        "--sources",
        default=str(DEFAULT_SOURCE_MANIFEST),
        help="training-source manifest",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser(
        "status", help="validate and print deterministic candidate status"
    )
    evaluate_parser = subparsers.add_parser(
        "evaluate", help="evaluate one raw evidence report without changing selection"
    )
    evaluate_parser.add_argument(
        "report", help="evaluation report matching model-evaluation.schema.json"
    )
    evaluate_parser.add_argument(
        "--approve-license-gate",
        action="append",
        default=[],
        dest="approved_license_gates",
        help=(
            "explicit engineering review assertion for a release-policy gate; "
            "repeat for each required gate (does not grant legal approval)"
        ),
    )
    args = parser.parse_args(argv)
    try:
        sources = validate_manifest(args.sources)
        registry = validate_registry(args.registry, args.sources)
        if args.command == "status":
            print(
                json.dumps(registry_status(registry, sources), indent=2, sort_keys=True)
            )
            return 0
        _report_path, report = validate_evaluation_report(args.report)
        result = evaluate_candidate(
            registry,
            sources,
            report,
            approved_license_gates=args.approved_license_gates,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["model_scorecard_eligible"] else 1
    except (ModelSelectionError, SourceManifestError) as error:
        parser.exit(2, f"error: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
