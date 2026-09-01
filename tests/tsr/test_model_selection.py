import ast
import copy
import hashlib
import json
from pathlib import Path
from pathlib import PurePosixPath

import jsonschema
import pytest

from scripts.tsr.bootstrap_sources import DEFAULT_MANIFEST, validate_manifest
from scripts.tsr.model_selection import (
    DEFAULT_EVALUATION_SCHEMA,
    DEFAULT_REGISTRY,
    ModelSelectionError,
    _device_measurement_sha256,
    _validate_normalized_outputs,
    _validate_parity_case_inventory,
    evaluate_candidate,
    main,
    registry_status,
    validate_evaluation_report,
    validate_registry,
    wilson_lower_bound,
)


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "tsr" / "model_selection.py"
TARGET_ID = "de-yolox-nano-mnv3-large-proposal-classification"


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _hash(value: int) -> str:
    return f"{value:064x}"


def _json_bytes(value: object) -> bytes:
    return json.dumps(value, separators=(",", ":"), sort_keys=True).encode("utf-8")


def _opaque_bytes(path: str) -> bytes:
    return f"immutable test evidence for {path}\n".encode()


def _evidence_ref(path: str, payload: bytes) -> dict:
    return {"path": path, "sha256": hashlib.sha256(payload).hexdigest()}


def _opaque_ref(path: str) -> dict:
    return _evidence_ref(path, _opaque_bytes(path))


def _component_manifests(candidate: dict) -> list[dict]:
    result = []
    for component in candidate["components"]:
        role = component["role"]
        result.append(
            {
                "role": role,
                "family": component["family"],
                "source_refs": copy.deepcopy(component["source_refs"]),
                "artifact_formats": {
                    "trained_checkpoint": "safetensors",
                    "reference_onnx": "onnx",
                    "coreml": "coreml-compiled-model",
                    "litert": "litert-flatbuffer",
                },
                "trained_checkpoint": _opaque_ref(
                    f"models/{role}/trained-checkpoint.safetensors"
                ),
                "reference_onnx": _opaque_ref(f"models/{role}/reference.onnx"),
                "coreml": _opaque_ref(f"models/{role}/model.mlmodelc"),
                "litert": _opaque_ref(f"models/{role}/model.tflite"),
            }
        )
    return result


def _component_identities(components: list[dict]) -> list[dict]:
    return [
        {
            "role": component["role"],
            "trained_checkpoint_sha256": component["trained_checkpoint"]["sha256"],
            "reference_onnx_sha256": component["reference_onnx"]["sha256"],
            "coreml_sha256": component["coreml"]["sha256"],
            "litert_sha256": component["litert"]["sha256"],
        }
        for component in components
    ]


def _holdout_strata() -> list[dict]:
    return [
        {"name": "weather", "case_count": 100, "failure_count": 0},
        {"name": "day", "case_count": 700, "failure_count": 0},
        {"name": "construction", "case_count": 100, "failure_count": 0},
        {"name": "night", "case_count": 300, "failure_count": 0},
        {"name": "adjacent_road", "case_count": 100, "failure_count": 0},
    ]


def _recall_strata() -> list[dict]:
    return [
        {
            "name": item["name"],
            "case_count": item["case_count"],
            "ground_truth_count": item["case_count"],
            "true_positive_count": item["case_count"],
            "false_negative_count": 0,
        }
        for item in _holdout_strata()
    ]


def _case_inventory() -> dict:
    cases = []
    for index in range(1000):
        strata = ["day" if index < 700 else "night"]
        if index < 100:
            strata.append("weather")
        if 100 <= index < 200:
            strata.append("construction")
        if 200 <= index < 300:
            strata.append("adjacent_road")
        case_id = f"case-{index:04d}"
        cases.append(
            {
                "case_id": case_id,
                "annotation_sha256": hashlib.sha256(
                    f"annotations/{case_id}".encode()
                ).hexdigest(),
                "strata": strata,
                "primary_ground_truth_count": 1,
                "restriction_ground_truth_count": 1,
            }
        )
    inventory = {
        "schema_version": 1,
        "dataset_id": "de-real-route-holdout-001",
        "cases": cases,
    }
    _recompute_case_inventory(inventory)
    return inventory


def _parity_case_inventory(case_count: int = 1000) -> dict:
    return {
        "schema_version": 1,
        "inventory_id": "de-parity-corpus-001",
        "cases": [
            {
                "case_id": f"parity-case-{index:04d}",
                "input_sha256": hashlib.sha256(
                    f"parity/input/{index:04d}".encode()
                ).hexdigest(),
            }
            for index in range(case_count)
        ],
    }


def _normalized_parity_outputs(
    parity: dict,
    runtime: str,
    output_kind: str,
    *,
    case_count: int = 1000,
) -> dict:
    artifact_field = {
        "onnx": "reference_onnx_sha256",
        "coreml": "coreml_sha256",
        "litert": "litert_sha256",
    }[runtime]
    case_ids = [f"parity-case-{index:04d}" for index in range(case_count)]
    return {
        "schema_version": 1,
        "output_kind": output_kind,
        "runtime": runtime,
        "training_run_manifest_sha256": parity["training_run_manifest_sha256"],
        "case_inventory_sha256": parity["case_inventory_file"]["sha256"],
        "artifact_sha256s": sorted(
            component[artifact_field] for component in parity["components"]
        ),
        "evaluated_case_ids": case_ids,
        "outputs": [
            {
                "output_id": f"speed-sign-{index:04d}",
                "case_id": case_id,
                "semantic_label": "speed-limit-50",
                "assembly_label": "unconditional",
                "box_xyxy": [0.1, 0.1, 0.2, 0.2],
                "calibrated_confidence": 0.99,
            }
            for index, case_id in enumerate(case_ids)
        ],
    }


def _recompute_case_inventory(inventory: dict) -> None:
    cases = inventory["cases"]
    inventory["sample_count"] = len(cases)
    inventory["primary_ground_truth_count"] = sum(
        case["primary_ground_truth_count"] for case in cases
    )
    inventory["restriction_ground_truth_count"] = sum(
        case["restriction_ground_truth_count"] for case in cases
    )
    aggregates: dict[str, dict] = {}
    for case in cases:
        for name in case["strata"]:
            aggregate = aggregates.setdefault(
                name,
                {
                    "name": name,
                    "case_count": 0,
                    "primary_ground_truth_count": 0,
                    "restriction_ground_truth_count": 0,
                },
            )
            aggregate["case_count"] += 1
            aggregate["primary_ground_truth_count"] += case[
                "primary_ground_truth_count"
            ]
            aggregate["restriction_ground_truth_count"] += case[
                "restriction_ground_truth_count"
            ]
    inventory["strata"] = [aggregates[name] for name in sorted(aggregates)]


def _bind_json_file(section: dict, field: str, path: str) -> None:
    payload = {key: value for key, value in section.items() if key != field}
    section[field] = _evidence_ref(path, _json_bytes(payload))


def _device_attestation(tier: dict, claim: str) -> dict:
    return {
        "schema_version": 1,
        "tier_id": tier["tier_id"],
        "benchmark_run_id": tier["benchmark_run_id"],
        "device_instance_id": tier["device_instance_id"],
        "platform": tier["platform"],
        "hardware_model_id": tier["hardware_model_id"],
        "os_build_id": tier["os_build_id"],
        "app_build_sha256": tier["app_build_sha256"],
        "training_run_manifest_sha256": tier["training_run_manifest_sha256"],
        "artifact_sha256s": tier["artifact_sha256s"],
        "measurement_sha256": _device_measurement_sha256(tier),
        "claim": claim,
        "value": tier[claim],
        "log_file": _opaque_ref(f"device/{tier['tier_id']}/{claim}.log"),
    }


def _device_profile(tier: dict) -> dict:
    return {
        "tier_id": tier["tier_id"],
        "platform": tier["platform"],
        "hardware_model_id": tier["hardware_model_id"],
        "os_build_id": tier["os_build_id"],
        "app_build_sha256": tier["app_build_sha256"],
    }


def _seal_report(report: dict) -> None:
    training_run = report["lineage"]["training_run"]
    training_run["manifest_file"] = _evidence_ref(
        training_run["manifest_file"]["path"],
        _json_bytes(training_run["manifest"]),
    )
    holdout = report["holdout"]
    holdout["case_inventory_file"] = _evidence_ref(
        holdout["case_inventory_file"]["path"],
        _json_bytes(holdout["case_inventory"]),
    )
    parity = report["parity"]
    parity_inventory = _parity_case_inventory()
    parity["case_inventory_file"] = _evidence_ref(
        parity["case_inventory_file"]["path"],
        _json_bytes(parity_inventory),
    )
    parity["reference_outputs_file"] = _evidence_ref(
        parity["reference_outputs_file"]["path"],
        _json_bytes(_normalized_parity_outputs(parity, "onnx", "reference")),
    )
    for runtime in parity["runtime_outputs"]:
        runtime["output_file"] = _evidence_ref(
            runtime["output_file"]["path"],
            _json_bytes(
                _normalized_parity_outputs(parity, runtime["runtime"], "measured")
            ),
        )
    for tier in report["mobile"]["device_tiers"]:
        for evidence_field, claim in (
            ("thermal_evidence_file", "thermal_downshift_verified"),
            ("recording_evidence_file", "recording_unaffected"),
        ):
            tier[evidence_field] = _evidence_ref(
                tier[evidence_field]["path"],
                _json_bytes(_device_attestation(tier, claim)),
            )
    for section, field in (
        (holdout, "report_file"),
        (report["leakage_audit"], "audit_file"),
        (report["primary_semantics"], "metrics_file"),
        (report["restrictions"], "metrics_file"),
        (report["calibration"], "reliability_report_file"),
        (report["parity"], "report_file"),
        (report["temporal_behavior"], "report_file"),
        (report["mobile"], "pack_manifest_file"),
    ):
        _bind_json_file(section, field, section[field]["path"])


def _sync_training_manifest_references(report: dict) -> None:
    manifest_hash = report["lineage"]["training_run"]["manifest_file"]["sha256"]
    report["leakage_audit"]["training_run_manifest_sha256"] = manifest_hash
    report["calibration"]["training_run_manifest_sha256"] = manifest_hash
    report["parity"]["training_run_manifest_sha256"] = manifest_hash
    report["primary_semantics"]["training_run_manifest_sha256"] = manifest_hash
    report["restrictions"]["training_run_manifest_sha256"] = manifest_hash
    report["temporal_behavior"]["training_run_manifest_sha256"] = manifest_hash
    report["mobile"]["training_run_manifest_sha256"] = manifest_hash
    for tier in report["mobile"]["device_tiers"]:
        tier["training_run_manifest_sha256"] = manifest_hash


def _sync_holdout_inventory_references(report: dict) -> None:
    inventory_hash = report["holdout"]["case_inventory_file"]["sha256"]
    report["leakage_audit"]["holdout_case_inventory_sha256"] = inventory_hash
    report["primary_semantics"]["holdout_case_inventory_sha256"] = inventory_hash
    report["restrictions"]["holdout_case_inventory_sha256"] = inventory_hash


def _sync_perfect_recall_metrics(report: dict) -> None:
    inventory = report["holdout"]["case_inventory"]
    for section_name, task_prefix, prediction_field in (
        (
            "primary_semantics",
            "primary",
            "confirmed_numeric_prediction_count",
        ),
        ("restrictions", "restriction", "resolved_prediction_count"),
    ):
        section = report[section_name]
        ground_truth_count = inventory[f"{task_prefix}_ground_truth_count"]
        section.update(
            {
                "evaluated_case_count": inventory["sample_count"],
                "ground_truth_count": ground_truth_count,
                "true_positive_count": ground_truth_count,
                "false_positive_count": 0,
                "false_negative_count": 0,
                prediction_field: ground_truth_count,
                "strata": [
                    {
                        "name": stratum["name"],
                        "case_count": stratum["case_count"],
                        "ground_truth_count": stratum[
                            f"{task_prefix}_ground_truth_count"
                        ],
                        "true_positive_count": stratum[
                            f"{task_prefix}_ground_truth_count"
                        ],
                        "false_negative_count": 0,
                    }
                    for stratum in inventory["strata"]
                ],
            }
        )


def _passing_report() -> dict:
    registry = validate_registry()
    candidate = registry.candidates_by_id[TARGET_ID]
    bootstrap_ids = sorted(
        reference["artifact_id"]
        for component in candidate["components"]
        for reference in component["source_refs"]
    )
    component_manifests = _component_manifests(candidate)
    components = _component_identities(component_manifests)
    training_manifest = {
        "schema_version": 1,
        "training_run_id": "de-target-training-001",
        "candidate_id": TARGET_ID,
        "source_manifest_id": "youspeed-tsr-training-sources-v1",
        "source_manifest_sha256": _sha256(DEFAULT_MANIFEST),
        "training_dataset_bundle": {
            "bundle_id": "de-training-bundle-001",
            "source_ids": [
                "gtsign-220-e235536",
                "panoramax-de-crops-b485694",
                "synset-signset-germany-dcc1znjxu7apx8rn",
                "zod-frames-2.0.0",
            ],
            "artifact_refs": [
                {
                    "source_id": "panoramax-de-crops-b485694",
                    "artifact_id": "panoramax-de-train-b485694",
                },
                {
                    "source_id": "synset-signset-germany-dcc1znjxu7apx8rn",
                    "artifact_id": "synset-signset-germany-archive",
                },
            ],
            "inventory_file": _opaque_ref("datasets/training-inventory.json"),
            "group_split_file": _opaque_ref("datasets/training-group-split.json"),
        },
        "calibration_dataset_bundle": {
            "bundle_id": "de-calibration-bundle-001",
            "source_ids": ["panoramax-de-crops-b485694"],
            "artifact_refs": [
                {
                    "source_id": "panoramax-de-crops-b485694",
                    "artifact_id": "panoramax-de-validation-b485694",
                }
            ],
            "inventory_file": _opaque_ref("datasets/calibration-inventory.json"),
            "group_split_file": _opaque_ref("datasets/calibration-group-split.json"),
        },
        "components": component_manifests,
    }
    manifest_ref = _evidence_ref(
        "manifests/training-run.json", _json_bytes(training_manifest)
    )
    case_inventory = _case_inventory()
    inventory_ref = _evidence_ref(
        "datasets/holdout-case-inventory.json", _json_bytes(case_inventory)
    )
    report = {
        "schema_version": 1,
        "report_id": "target-evaluation-001",
        "candidate_id": TARGET_ID,
        "evaluated_at": "2026-09-01T12:00:00Z",
        "lineage": {
            "source_manifest_id": "youspeed-tsr-training-sources-v1",
            "source_manifest_sha256": _sha256(DEFAULT_MANIFEST),
            "selection_registry_sha256": _sha256(DEFAULT_REGISTRY),
            "bootstrap_artifact_ids": bootstrap_ids,
            "training_run": {
                "manifest_file": manifest_ref,
                "manifest": training_manifest,
            },
        },
        "holdout": {
            "dataset_id": "de-real-route-holdout-001",
            "case_inventory_file": inventory_ref,
            "case_inventory": case_inventory,
            "group_split_file": _opaque_ref("datasets/holdout-group-split.json"),
            "kind": "real_route_held_out",
            "frozen": True,
            "threshold_fitted_on_holdout": False,
            "sample_count": 1000,
            "real_case_count": 1000,
            "synthetic_case_count": 0,
            "independent_route_count": 20,
            "strata": _holdout_strata(),
            "report_file": _opaque_ref("reports/holdout.json"),
        },
        "leakage_audit": {
            "audit_file": _opaque_ref("reports/leakage-audit.json"),
            "training_run_manifest_sha256": manifest_ref["sha256"],
            "training_dataset_inventory_sha256": training_manifest[
                "training_dataset_bundle"
            ]["inventory_file"]["sha256"],
            "training_group_split_sha256": training_manifest["training_dataset_bundle"][
                "group_split_file"
            ]["sha256"],
            "calibration_dataset_inventory_sha256": training_manifest[
                "calibration_dataset_bundle"
            ]["inventory_file"]["sha256"],
            "calibration_group_split_sha256": training_manifest[
                "calibration_dataset_bundle"
            ]["group_split_file"]["sha256"],
            "holdout_case_inventory_sha256": inventory_ref["sha256"],
            "holdout_group_split_sha256": _opaque_ref(
                "datasets/holdout-group-split.json"
            )["sha256"],
            "capture_group_overlap_count": 0,
            "physical_sign_cluster_overlap_count": 0,
            "near_duplicate_overlap_count": 0,
        },
        "primary_semantics": {
            "training_run_manifest_sha256": manifest_ref["sha256"],
            "components": copy.deepcopy(components),
            "holdout_case_inventory_sha256": inventory_ref["sha256"],
            "evaluated_case_count": 1000,
            "ground_truth_count": 1000,
            "true_positive_count": 1000,
            "false_positive_count": 0,
            "false_negative_count": 0,
            "confirmed_numeric_prediction_count": 1000,
            "dangerous_substitution_count": 0,
            "strata": _recall_strata(),
            "metrics_file": _opaque_ref("reports/primary-metrics.json"),
        },
        "restrictions": {
            "training_run_manifest_sha256": manifest_ref["sha256"],
            "components": copy.deepcopy(components),
            "holdout_case_inventory_sha256": inventory_ref["sha256"],
            "evaluated_case_count": 1000,
            "ground_truth_count": 1000,
            "true_positive_count": 1000,
            "false_positive_count": 0,
            "false_negative_count": 0,
            "resolved_prediction_count": 1000,
            "unresolved_promoted_unconditional_count": 0,
            "strata": _recall_strata(),
            "metrics_file": _opaque_ref("reports/restriction-metrics.json"),
        },
        "calibration": {
            "training_run_manifest_sha256": manifest_ref["sha256"],
            "dataset_inventory_sha256": training_manifest["calibration_dataset_bundle"][
                "inventory_file"
            ]["sha256"],
            "group_split_sha256": training_manifest["calibration_dataset_bundle"][
                "group_split_file"
            ]["sha256"],
            "sample_count": 1000,
            "bins": [
                {
                    "index": 0,
                    "sample_count": 1000,
                    "confidence_sum": 990.0,
                    "correct_count": 990,
                }
            ],
            "reliability_report_file": _opaque_ref(
                "reports/calibration-reliability.json"
            ),
        },
        "parity": {
            "training_run_manifest_sha256": manifest_ref["sha256"],
            "components": copy.deepcopy(components),
            "case_inventory_file": _opaque_ref("parity/case-inventory.json"),
            "reference_outputs_file": _opaque_ref("parity/reference-onnx-outputs.json"),
            "runtime_outputs": [
                {
                    "runtime": runtime,
                    "output_file": _opaque_ref(f"parity/{runtime}-outputs.json"),
                }
                for runtime in ("onnx", "coreml", "litert")
            ],
            "report_file": _opaque_ref("reports/parity.json"),
        },
        "temporal_behavior": {
            "training_run_manifest_sha256": manifest_ref["sha256"],
            "components": copy.deepcopy(components),
            "physical_assembly_count": 1000,
            "duplicate_confirmation_count": 0,
            "direction_evaluable_confirmation_count": 1000,
            "wrong_way_confirmation_count": 0,
            "report_file": _opaque_ref("reports/temporal.json"),
        },
        "mobile": {
            "training_run_manifest_sha256": manifest_ref["sha256"],
            "pack_manifest_file": _opaque_ref("reports/mobile-pack.json"),
            "artifacts": [
                {
                    "role": "proposal_detector",
                    "platform": "ios",
                    "artifact_id": "proposal-detector-coreml",
                    "file": copy.deepcopy(component_manifests[0]["coreml"]),
                },
                {
                    "role": "proposal_detector",
                    "platform": "android",
                    "artifact_id": "proposal-detector-litert",
                    "file": copy.deepcopy(component_manifests[0]["litert"]),
                },
                {
                    "role": "classifier",
                    "platform": "ios",
                    "artifact_id": "classifier-coreml",
                    "file": copy.deepcopy(component_manifests[1]["coreml"]),
                },
                {
                    "role": "classifier",
                    "platform": "android",
                    "artifact_id": "classifier-litert",
                    "file": copy.deepcopy(component_manifests[1]["litert"]),
                },
            ],
            "supported_device_tier_ids": ["ios-baseline", "android-baseline"],
            "device_tiers": [
                {
                    "tier_id": "ios-baseline",
                    "benchmark_run_id": "ios-baseline-run-001",
                    "device_instance_id": "test-ios-device-001",
                    "platform": "ios",
                    "hardware_model_id": "test-ios-hardware",
                    "os_build_id": "test-ios-os-build",
                    "app_build_sha256": _hash(70),
                    "training_run_manifest_sha256": manifest_ref["sha256"],
                    "artifact_sha256s": [
                        components[0]["coreml_sha256"],
                        components[1]["coreml_sha256"],
                    ],
                    "drive_duration_seconds": 1800,
                    "camera_frame_count": 54_000,
                    "dropped_frame_count": 0,
                    "backpressure_event_count": 0,
                    "peak_memory_bytes": 128_000_000,
                    "detector_inference_count": 3600,
                    "detector_p95_ms": 100,
                    "end_to_end_inference_count": 3600,
                    "end_to_end_p95_ms": 180,
                    "maximum_in_flight": 1,
                    "thermal_downshift_verified": True,
                    "thermal_evidence_file": _opaque_ref(
                        "device/ios-baseline/thermal-attestation.json"
                    ),
                    "recording_unaffected": True,
                    "recording_evidence_file": _opaque_ref(
                        "device/ios-baseline/recording-attestation.json"
                    ),
                },
                {
                    "tier_id": "android-baseline",
                    "benchmark_run_id": "android-baseline-run-001",
                    "device_instance_id": "test-android-device-001",
                    "platform": "android",
                    "hardware_model_id": "test-android-hardware",
                    "os_build_id": "test-android-os-build",
                    "app_build_sha256": _hash(70),
                    "training_run_manifest_sha256": manifest_ref["sha256"],
                    "artifact_sha256s": [
                        components[0]["litert_sha256"],
                        components[1]["litert_sha256"],
                    ],
                    "drive_duration_seconds": 1800,
                    "camera_frame_count": 54_000,
                    "dropped_frame_count": 0,
                    "backpressure_event_count": 0,
                    "peak_memory_bytes": 128_000_000,
                    "detector_inference_count": 3600,
                    "detector_p95_ms": 110,
                    "end_to_end_inference_count": 3600,
                    "end_to_end_p95_ms": 190,
                    "maximum_in_flight": 1,
                    "thermal_downshift_verified": True,
                    "thermal_evidence_file": _opaque_ref(
                        "device/android-baseline/thermal-attestation.json"
                    ),
                    "recording_unaffected": True,
                    "recording_evidence_file": _opaque_ref(
                        "device/android-baseline/recording-attestation.json"
                    ),
                },
            ],
        },
    }
    for artifact in report["mobile"]["artifacts"]:
        artifact["size_bytes"] = len(_opaque_bytes(artifact["file"]["path"]))
    report["mobile"]["pack_size_bytes"] = sum(
        artifact["size_bytes"] for artifact in report["mobile"]["artifacts"]
    )
    _seal_report(report)
    return report


def _evidence_bytes(report: dict, path: str) -> bytes:
    training_run = report["lineage"]["training_run"]
    if path == training_run["manifest_file"]["path"]:
        return _json_bytes(training_run["manifest"])
    holdout = report["holdout"]
    if path == holdout["case_inventory_file"]["path"]:
        return _json_bytes(holdout["case_inventory"])
    parity = report["parity"]
    if path == parity["case_inventory_file"]["path"]:
        return _json_bytes(_parity_case_inventory())
    if path == parity["reference_outputs_file"]["path"]:
        return _json_bytes(_normalized_parity_outputs(parity, "onnx", "reference"))
    for runtime in parity["runtime_outputs"]:
        if path == runtime["output_file"]["path"]:
            return _json_bytes(
                _normalized_parity_outputs(parity, runtime["runtime"], "measured")
            )
    for section, field in (
        (holdout, "report_file"),
        (report["leakage_audit"], "audit_file"),
        (report["primary_semantics"], "metrics_file"),
        (report["restrictions"], "metrics_file"),
        (report["calibration"], "reliability_report_file"),
        (report["parity"], "report_file"),
        (report["temporal_behavior"], "report_file"),
        (report["mobile"], "pack_manifest_file"),
    ):
        if path == section[field]["path"]:
            return _json_bytes(
                {key: value for key, value in section.items() if key != field}
            )
    for tier in report["mobile"]["device_tiers"]:
        for evidence_field, claim in (
            ("thermal_evidence_file", "thermal_downshift_verified"),
            ("recording_evidence_file", "recording_unaffected"),
        ):
            if path == tier[evidence_field]["path"]:
                return _json_bytes(_device_attestation(tier, claim))
    return _opaque_bytes(path)


def _all_evidence_refs(value: object) -> list[dict]:
    if isinstance(value, dict):
        if set(value) == {"path", "sha256"}:
            return [value]
        return [ref for child in value.values() for ref in _all_evidence_refs(child)]
    if isinstance(value, list):
        return [ref for child in value for ref in _all_evidence_refs(child)]
    return []


def _is_safe_test_path(path: str) -> bool:
    pure = PurePosixPath(path)
    return (
        bool(path)
        and not pure.is_absolute()
        and "\\" not in path
        and "//" not in path
        and all(part not in {"", ".", ".."} for part in pure.parts)
    )


def _write_bundle(tmp_path: Path, report: dict) -> Path:
    refs = _all_evidence_refs(report)
    for tier in report["mobile"]["device_tiers"]:
        refs.extend(
            _device_attestation(tier, claim)["log_file"]
            for claim in ("thermal_downshift_verified", "recording_unaffected")
        )
    for reference in refs:
        relative_path = reference["path"]
        if not _is_safe_test_path(relative_path):
            continue
        evidence_path = tmp_path.joinpath(*PurePosixPath(relative_path).parts)
        evidence_path.parent.mkdir(parents=True, exist_ok=True)
        payload = _evidence_bytes(report, relative_path)
        if not evidence_path.is_symlink():
            evidence_path.write_bytes(payload)
    report_path = tmp_path / "evaluation.json"
    report_path.write_text(json.dumps(report), encoding="utf-8")
    return report_path


def _write_referenced_payload(
    tmp_path: Path,
    reference: dict,
    payload: dict,
) -> None:
    raw = _json_bytes(payload)
    reference["sha256"] = hashlib.sha256(raw).hexdigest()
    evidence_path = tmp_path.joinpath(*PurePosixPath(reference["path"]).parts)
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    evidence_path.write_bytes(raw)


def _replace_parity_evidence(
    tmp_path: Path,
    report_path: Path,
    report: dict,
    *,
    case_count: int = 1000,
    mutate_reference=None,
    mutate_runtime=None,
) -> None:
    parity = report["parity"]
    inventory = _parity_case_inventory(case_count)
    _write_referenced_payload(tmp_path, parity["case_inventory_file"], inventory)
    reference_payload = _normalized_parity_outputs(
        parity, "onnx", "reference", case_count=case_count
    )
    if mutate_reference is not None:
        mutate_reference(reference_payload)
    _write_referenced_payload(
        tmp_path, parity["reference_outputs_file"], reference_payload
    )
    for runtime in parity["runtime_outputs"]:
        runtime_payload = _normalized_parity_outputs(
            parity, runtime["runtime"], "measured", case_count=case_count
        )
        if mutate_runtime is not None:
            mutate_runtime(runtime["runtime"], runtime_payload)
        _write_referenced_payload(tmp_path, runtime["output_file"], runtime_payload)
    parity_report_path = parity["report_file"]["path"]
    _bind_json_file(parity, "report_file", parity_report_path)
    _write_referenced_payload(
        tmp_path,
        parity["report_file"],
        {key: value for key, value in parity.items() if key != "report_file"},
    )
    report_path.write_text(json.dumps(report), encoding="utf-8")


def _rewrite_bound_section(
    tmp_path: Path,
    section: dict,
    reference_field: str,
) -> None:
    path = section[reference_field]["path"]
    _bind_json_file(section, reference_field, path)
    _write_referenced_payload(
        tmp_path,
        section[reference_field],
        {key: value for key, value in section.items() if key != reference_field},
    )


def _validated_report(tmp_path: Path, payload: dict) -> dict:
    path = _write_bundle(tmp_path, payload)
    _path, report = validate_evaluation_report(path)
    return report


def _schema_validator() -> jsonschema.Draft202012Validator:
    schema = json.loads(DEFAULT_EVALUATION_SCHEMA.read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(
        schema, format_checker=jsonschema.FormatChecker()
    )


def _schema_def_validator(name: str) -> jsonschema.Draft202012Validator:
    schema = json.loads(DEFAULT_EVALUATION_SCHEMA.read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(
        {"$ref": f"#/$defs/{name}", "$defs": schema["$defs"]}
    )


def _gates(result: dict) -> dict[str, dict]:
    return {gate["gate_id"]: gate for gate in result["gates"]}


def _replace_mobile_artifact_identity(report: dict) -> None:
    replacement = copy.deepcopy(
        report["lineage"]["training_run"]["manifest"]["components"][1]["coreml"]
    )
    artifact = report["mobile"]["artifacts"][0]
    artifact["file"] = replacement
    artifact["size_bytes"] = len(_opaque_bytes(replacement["path"]))
    report["mobile"]["pack_size_bytes"] = sum(
        item["size_bytes"] for item in report["mobile"]["artifacts"]
    )


def _evaluate(tmp_path: Path, payload: dict, *, approve: bool = True) -> dict:
    payload = copy.deepcopy(payload)
    _seal_report(payload)
    report = _validated_report(tmp_path, payload)
    return evaluate_candidate(
        validate_registry(),
        validate_manifest(DEFAULT_MANIFEST),
        report,
        approved_license_gates=(
            [
                "apache_notice_review",
                "attribution_review",
                "attribution_share_alike_review",
            ]
            if approve
            else []
        ),
    )


def _evaluate_report_path(report_path: Path) -> dict:
    _path, report = validate_evaluation_report(report_path)
    return evaluate_candidate(
        validate_registry(),
        validate_manifest(DEFAULT_MANIFEST),
        report,
        approved_license_gates=[
            "apache_notice_review",
            "attribution_review",
            "attribution_share_alike_review",
        ],
    )


def test_registry_is_unselected_scoped_and_cross_checks_pinned_references() -> None:
    registry = validate_registry()
    sources = validate_manifest(DEFAULT_MANIFEST)

    assert registry.payload["selected_candidate_id"] is None
    assert registry.payload["selection_status"] == "not_evaluated"
    assert registry.payload["source_manifest_sha256"] == _sha256(DEFAULT_MANIFEST)
    assert registry.payload["source_manifest_sha256"] == (
        "4985ebb8a146918c113700d312e6becb893acfed1d07f2bfa16263fadf0c1cbc"
    )
    assert (
        registry.payload["scorecard_policy"]["scope"] == "internal_candidate_comparison"
    )
    assert (
        registry.payload["scorecard_gates"][
            "minimum_confirmed_numeric_recall_lower_bound"
        ]
        == 0.9
    )
    assert (
        registry.payload["scorecard_gates"][
            "minimum_resolved_restriction_recall_lower_bound"
        ]
        == 0.8
    )
    assert registry.payload["scorecard_gates"]["minimum_camera_frame_rate_hz"] == 15
    assert (
        registry.payload["scorecard_gates"]["approved_holdout_case_inventory_sha256"]
        is None
    )
    assert registry.payload["scorecard_gates"]["approved_device_tier_profiles"] is None
    assert registry.payload["target_candidate_id"] == TARGET_ID
    assert registry.candidates_by_id[TARGET_ID]["pipeline"] == "proposal_classification"
    assert registry.candidates_by_id[TARGET_ID]["status"] == "blocked"
    assert any(
        "full-scene supplementary_plate detector-label coverage" in reason
        for reason in registry.candidates_by_id[TARGET_ID]["blocking_reasons"]
    )
    small = registry.candidates_by_id[
        "de-yolox-nano-mnv3-small-proposal-classification"
    ]
    assert small["status"] == "blocked"
    assert any(
        "full-scene supplementary_plate detector-label coverage" in reason
        for reason in small["blocking_reasons"]
    )
    assert (
        registry.candidates_by_id["de-yolox-nano-direct-ios-shadow"]["status"]
        == "blocked"
    )
    assert (
        registry.candidates_by_id["de-rf-detr-nano-mnv3-large-proposal-classification"][
            "components"
        ][0]["pin_status"]
        == "unpinned"
    )
    gtsign = registry.candidates_by_id["gtsign-220-vit-all-classes-external"]
    assert gtsign["status"] == "blocked"
    assert gtsign["eligible_for_selection"] is False
    assert gtsign["supported_platforms"] == ["offline"]
    assert gtsign["components"][0]["source_refs"] == [
        {
            "source_id": "gtsign-220-e235536",
            "artifact_id": "gtsign-220-vit-all-classes",
        }
    ]

    status = registry_status(registry, sources)
    assert [candidate["candidate_id"] for candidate in status["candidates"]] == sorted(
        candidate["candidate_id"] for candidate in status["candidates"]
    )
    assert status["selected_candidate_id"] is None
    assert status["scorecard_policy"]["authority"] == "engineering_evidence_only"


def test_registry_rejects_source_manifest_byte_drift(tmp_path: Path) -> None:
    source_payload = json.loads(DEFAULT_MANIFEST.read_text(encoding="utf-8"))
    source_payload["as_of_date"] = "2026-09-02"
    changed_sources = tmp_path / "sources.json"
    changed_sources.write_text(json.dumps(source_payload), encoding="utf-8")

    with pytest.raises(ModelSelectionError, match="source_manifest_sha256"):
        validate_registry(DEFAULT_REGISTRY, changed_sources)


def test_registry_rejects_making_gtsign_external_teacher_selectable(
    tmp_path: Path,
) -> None:
    payload = json.loads(DEFAULT_REGISTRY.read_text(encoding="utf-8"))
    candidate = next(
        item
        for item in payload["candidates"]
        if item["candidate_id"] == "gtsign-220-vit-all-classes-external"
    )
    candidate["eligible_for_selection"] = True
    changed_registry = tmp_path / "registry.json"
    changed_registry.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ModelSelectionError, match="blocked offline-only"):
        validate_registry(changed_registry)


def test_registry_rejects_partially_configured_corpus_pins(tmp_path: Path) -> None:
    payload = json.loads(DEFAULT_REGISTRY.read_text(encoding="utf-8"))
    payload["scorecard_gates"]["approved_holdout_dataset_id"] = "holdout-001"
    changed_registry = tmp_path / "registry.json"
    changed_registry.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ModelSelectionError, match="configured atomically"):
        validate_registry(changed_registry)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda report: report["primary_semantics"].update({"reported_precision": 1.0}),
        lambda report: report["parity"]["runtime_outputs"].pop(),
        lambda report: report["mobile"]["artifacts"][0].update({"size_bytes": 0}),
        lambda report: report["lineage"]["training_run"]["manifest"][
            "training_dataset_bundle"
        ]["source_ids"].clear(),
        lambda report: report["mobile"]["device_tiers"][0].update(
            {"hardware_model_id": True}
        ),
    ],
)
def test_schema_and_manual_validator_reject_the_same_structural_gaps(
    tmp_path: Path,
    mutate,
) -> None:
    report = _passing_report()
    _schema_validator().validate(report)
    _validated_report(tmp_path, copy.deepcopy(report))

    mutate(report)
    with pytest.raises(jsonschema.ValidationError):
        _schema_validator().validate(report)
    with pytest.raises(ModelSelectionError):
        _validated_report(tmp_path, report)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda report: report.update({"schema_version": True}),
        lambda report: report["lineage"]["training_run"]["manifest"].update(
            {"schema_version": True}
        ),
        lambda report: report["holdout"]["case_inventory"].update(
            {"schema_version": True}
        ),
    ],
)
def test_schema_versions_must_be_real_integers_for_both_validators(
    tmp_path: Path,
    mutate,
) -> None:
    report = _passing_report()
    mutate(report)
    with pytest.raises(jsonschema.ValidationError):
        _schema_validator().validate(report)
    with pytest.raises(ModelSelectionError, match="schema_version"):
        _validated_report(tmp_path, report)


def test_evidence_paths_are_safe_relative_paths_in_both_validators(
    tmp_path: Path,
) -> None:
    report = _passing_report()
    report["parity"]["report_file"]["path"] = "../outside.json"
    with pytest.raises(jsonschema.ValidationError):
        _schema_validator().validate(report)
    with pytest.raises(ModelSelectionError, match="safe relative POSIX path"):
        _validated_report(tmp_path, report)


def test_datetime_syntax_is_identical_for_both_validators(tmp_path: Path) -> None:
    report = _passing_report()
    report["evaluated_at"] = "2026-09-01 12:00:00+00:00"
    with pytest.raises(jsonschema.ValidationError):
        _schema_validator().validate(report)
    with pytest.raises(ModelSelectionError, match="RFC 3339"):
        _validated_report(tmp_path, report)


def test_normalized_parity_payloads_are_checked_by_schema_and_manual_validator() -> (
    None
):
    report = _passing_report()
    parity = report["parity"]
    inventory = _parity_case_inventory()
    outputs = _normalized_parity_outputs(parity, "onnx", "reference")

    _schema_def_validator("parityCaseInventory").validate(inventory)
    _validate_parity_case_inventory(inventory, "parity inventory")
    _schema_def_validator("normalizedParityOutputs").validate(outputs)
    _validate_normalized_outputs(outputs, "normalized outputs")

    outputs["outputs"][0]["calibrated_confidence"] = True
    with pytest.raises(jsonschema.ValidationError):
        _schema_def_validator("normalizedParityOutputs").validate(outputs)
    with pytest.raises(ModelSelectionError, match="finite number"):
        _validate_normalized_outputs(outputs, "normalized outputs")


def test_case_inventory_strata_upper_bound_matches_schema_and_manual(
    tmp_path: Path,
) -> None:
    report = _passing_report()
    report["holdout"]["case_inventory"]["cases"][0]["strata"] = [
        f"extra-{index:04d}" for index in range(1001)
    ]
    _recompute_case_inventory(report["holdout"]["case_inventory"])

    with pytest.raises(jsonschema.ValidationError):
        _schema_validator().validate(report)
    with pytest.raises(ModelSelectionError, match="exceeds 1000 items"):
        _validated_report(tmp_path, report)


@pytest.mark.parametrize("symlink_kind", ["target", "component"])
def test_evidence_bundle_rejects_symlink_targets_and_path_components(
    tmp_path: Path,
    symlink_kind: str,
) -> None:
    report = _passing_report()
    if symlink_kind == "component":
        report["parity"]["report_file"]["path"] = "links/reports/parity.json"
        _seal_report(report)
    report_path = _write_bundle(tmp_path, report)
    parity_path = tmp_path.joinpath(
        *PurePosixPath(report["parity"]["report_file"]["path"]).parts
    )
    if symlink_kind == "target":
        external = tmp_path / "external-parity.json"
        external.write_bytes(parity_path.read_bytes())
        parity_path.unlink()
        parity_path.symlink_to(external)
    else:
        external_dir = tmp_path / "external-reports"
        external_dir.mkdir()
        external = external_dir / "parity.json"
        external.write_bytes(parity_path.read_bytes())
        parity_path.unlink()
        parity_path.parent.rmdir()
        parity_path.parent.symlink_to(external_dir, target_is_directory=True)

    with pytest.raises(ModelSelectionError, match="must not traverse symlinks"):
        validate_evaluation_report(report_path)


def test_tampered_evidence_bytes_are_rejected(tmp_path: Path) -> None:
    report = _passing_report()
    report_path = _write_bundle(tmp_path, report)
    parity_path = tmp_path.joinpath(
        *PurePosixPath(report["parity"]["report_file"]["path"]).parts
    )
    parity_path.write_bytes(b"tampered parity evidence")

    with pytest.raises(ModelSelectionError, match="evidence SHA-256 mismatch"):
        validate_evaluation_report(report_path)


def test_embedded_training_manifest_cannot_change_without_its_file(
    tmp_path: Path,
) -> None:
    report = _passing_report()
    report_path = _write_bundle(tmp_path, report)
    changed_report = copy.deepcopy(report)
    changed_report["lineage"]["training_run"]["manifest"]["components"][0]["family"] = (
        "Changed Without Evidence"
    )
    report_path.write_text(json.dumps(changed_report), encoding="utf-8")

    with pytest.raises(ModelSelectionError, match="differs from embedded manifest"):
        validate_evaluation_report(report_path)


def test_device_attestation_requires_the_hashed_opaque_log(tmp_path: Path) -> None:
    report = _passing_report()
    report_path = _write_bundle(tmp_path, report)
    tier = report["mobile"]["device_tiers"][0]
    log_ref = _device_attestation(tier, "recording_unaffected")["log_file"]
    log_path = tmp_path.joinpath(*PurePosixPath(log_ref["path"]).parts)
    log_path.write_bytes(b"changed device log")

    with pytest.raises(ModelSelectionError, match="evidence SHA-256 mismatch"):
        validate_evaluation_report(report_path)


def test_device_attestation_log_cannot_alias_a_model_artifact(tmp_path: Path) -> None:
    report = _passing_report()
    report_path = _write_bundle(tmp_path, report)
    tier = report["mobile"]["device_tiers"][0]
    attestation = _device_attestation(tier, "thermal_downshift_verified")
    attestation["log_file"] = copy.deepcopy(
        report["lineage"]["training_run"]["manifest"]["components"][0]["coreml"]
    )
    _write_referenced_payload(tmp_path, tier["thermal_evidence_file"], attestation)
    _rewrite_bound_section(tmp_path, report["mobile"], "pack_manifest_file")
    report_path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(ModelSelectionError, match="globally distinct opaque log"):
        validate_evaluation_report(report_path)


def test_device_attestation_cannot_reuse_stale_measurements(tmp_path: Path) -> None:
    report = _passing_report()
    report_path = _write_bundle(tmp_path, report)
    report["mobile"]["device_tiers"][0]["camera_frame_count"] += 1
    _rewrite_bound_section(tmp_path, report["mobile"], "pack_manifest_file")
    report_path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(ModelSelectionError, match="other benchmark measurements"):
        validate_evaluation_report(report_path)


@pytest.mark.parametrize(
    ("field", "replacement", "reason"),
    [
        ("benchmark_run_id", "other-run-002", "another benchmark run"),
        ("device_instance_id", "other-device-002", "another device instance"),
        ("hardware_model_id", "other-hardware-model", "another hardware_model_id"),
        ("os_build_id", "other-os-build", "another os_build_id"),
        ("app_build_sha256", _hash(71), "another app_build_sha256"),
    ],
)
def test_device_attestations_bind_profile_run_and_device_identity(
    tmp_path: Path,
    field: str,
    replacement: str,
    reason: str,
) -> None:
    report = _passing_report()
    report_path = _write_bundle(tmp_path, report)
    report["mobile"]["device_tiers"][0][field] = replacement
    _rewrite_bound_section(tmp_path, report["mobile"], "pack_manifest_file")
    report_path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(ModelSelectionError, match=reason):
        validate_evaluation_report(report_path)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda report: report["primary_semantics"].update(
            {"dangerous_substitution_count": 1}
        ),
        lambda report: report["temporal_behavior"].update(
            {"duplicate_confirmation_count": 1}
        ),
        lambda report: report["mobile"]["device_tiers"][0].update(
            {"recording_unaffected": False}
        ),
    ],
)
def test_report_only_score_or_boolean_mutation_cannot_reuse_unchanged_evidence(
    tmp_path: Path,
    mutate,
) -> None:
    report = _passing_report()
    report_path = _write_bundle(tmp_path, report)
    changed_report = copy.deepcopy(report)
    mutate(changed_report)
    report_path.write_text(json.dumps(changed_report), encoding="utf-8")

    with pytest.raises(ModelSelectionError, match="differs from scored report fields"):
        validate_evaluation_report(report_path)


def test_scored_json_payload_comparison_does_not_coerce_boolean_to_integer(
    tmp_path: Path,
) -> None:
    report = _passing_report()
    report_path = _write_bundle(tmp_path, report)
    primary = report["primary_semantics"]
    payload = {key: value for key, value in primary.items() if key != "metrics_file"}
    payload["dangerous_substitution_count"] = False
    _write_referenced_payload(tmp_path, primary["metrics_file"], payload)
    report_path.write_text(json.dumps(report), encoding="utf-8")

    with pytest.raises(ModelSelectionError, match="differs from scored report fields"):
        validate_evaluation_report(report_path)


def test_manual_semantic_validation_rejects_duplicate_component_role(
    tmp_path: Path,
) -> None:
    report = _passing_report()
    report["lineage"]["training_run"]["manifest"]["components"][1]["role"] = (
        "proposal_detector"
    )
    _seal_report(report)
    with pytest.raises(ModelSelectionError, match="duplicate role"):
        _validated_report(tmp_path, report)


@pytest.mark.parametrize("alias_kind", ["path", "hash"])
def test_training_manifest_rejects_artifact_aliases_across_roles_and_components(
    tmp_path: Path,
    alias_kind: str,
) -> None:
    report = _passing_report()
    components = report["lineage"]["training_run"]["manifest"]["components"]
    if alias_kind == "path":
        components[1]["reference_onnx"] = copy.deepcopy(
            components[0]["trained_checkpoint"]
        )
    else:
        components[1]["reference_onnx"]["sha256"] = components[0]["trained_checkpoint"][
            "sha256"
        ]
    _seal_report(report)

    with pytest.raises(
        ModelSelectionError, match="artifact path aliases|SHA-256 aliases"
    ):
        _validated_report(tmp_path, report)


def test_training_manifest_artifact_format_attestation_matches_schema_and_manual(
    tmp_path: Path,
) -> None:
    report = _passing_report()
    report["lineage"]["training_run"]["manifest"]["components"][0]["artifact_formats"][
        "coreml"
    ] = "onnx"
    _seal_report(report)

    with pytest.raises(jsonschema.ValidationError):
        _schema_validator().validate(report)
    with pytest.raises(ModelSelectionError, match="role/format mapping"):
        _validated_report(tmp_path, report)


def test_wilson_lower_bound_uses_raw_counts_and_rejects_zero_denominator() -> None:
    assert wilson_lower_bound(1000, 1000) == pytest.approx(0.9961732415)
    assert wilson_lower_bound(990, 1000) < 0.99
    with pytest.raises(ModelSelectionError, match="positive"):
        wilson_lower_bound(0, 0)


def test_evaluator_computes_all_numeric_gates_but_remains_fail_closed(
    tmp_path: Path,
) -> None:
    result = _evaluate(tmp_path, _passing_report())
    gates = _gates(result)

    assert gates["confirmed_numeric_precision"]["status"] == "pass"
    assert gates["confirmed_numeric_recall_coverage"]["status"] == "pass"
    assert gates["resolved_restriction_precision"]["status"] == "pass"
    assert gates["resolved_restriction_recall_coverage"]["status"] == "pass"
    assert gates["cross_runtime_parity"]["status"] == "pass"
    assert gates["approved_evaluation_corpora"]["status"] == "pending_policy"
    assert gates["approved_device_tier_profiles"]["status"] == "pending_policy"
    assert gates["device_latency"]["status"] == "pass"
    assert gates["runtime_safety"]["status"] == "pass"
    assert gates["candidate_readiness"]["status"] == "fail"
    assert gates["licensing"]["status"] == "pass"
    assert gates["licensing"]["threshold"]["required_license_gate_ids"] == [
        "apache_notice_review",
        "attribution_review",
        "attribution_share_alike_review",
    ]
    assert gates["temporal_duplicate_confirmations"]["status"] == "pending_policy"
    assert gates["temporal_wrong_way_confirmations"]["status"] == "pending_policy"
    assert result["decision"] == "model_scorecard_blocked"
    assert result["model_scorecard_eligible"] is False
    assert "release_eligible" not in result
    assert result["selected_candidate_id"] is None
    assert result["selection_mutated"] is False


@pytest.mark.parametrize(
    ("pins_match", "expected_status"), [(True, "pass"), (False, "fail")]
)
def test_approved_corpus_gate_uses_exact_versioned_pins(
    tmp_path: Path,
    pins_match: bool,
    expected_status: str,
) -> None:
    report = _passing_report()
    registry_payload = json.loads(DEFAULT_REGISTRY.read_text(encoding="utf-8"))
    registry_gates = registry_payload["scorecard_gates"]
    registry_gates.update(
        {
            "approved_holdout_dataset_id": report["holdout"]["dataset_id"],
            "approved_holdout_case_inventory_sha256": report["holdout"][
                "case_inventory_file"
            ]["sha256"],
            "approved_holdout_group_split_sha256": report["holdout"][
                "group_split_file"
            ]["sha256"],
            "approved_parity_case_inventory_sha256": report["parity"][
                "case_inventory_file"
            ]["sha256"],
            "approved_parity_reference_outputs_sha256": report["parity"][
                "reference_outputs_file"
            ]["sha256"],
        }
    )
    if not pins_match:
        registry_gates["approved_parity_reference_outputs_sha256"] = _hash(55)
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(registry_payload), encoding="utf-8")
    registry = validate_registry(registry_path)
    report["lineage"]["selection_registry_sha256"] = registry.sha256
    _seal_report(report)
    validated = _validated_report(tmp_path / "bundle", report)

    result = evaluate_candidate(
        registry,
        validate_manifest(DEFAULT_MANIFEST),
        validated,
        approved_license_gates=["apache_notice_review"],
    )
    assert _gates(result)["approved_evaluation_corpora"]["status"] == expected_status


def test_rehashed_unapproved_corpora_remain_pending_policy(tmp_path: Path) -> None:
    report = _passing_report()
    report["holdout"]["case_inventory"]["cases"][0]["annotation_sha256"] = _hash(56)
    _seal_report(report)
    _sync_holdout_inventory_references(report)
    _seal_report(report)
    report_path = _write_bundle(tmp_path, report)

    def mutate_reference(outputs: dict) -> None:
        outputs["outputs"][0]["semantic_label"] = "speed-limit-60"

    _replace_parity_evidence(
        tmp_path,
        report_path,
        report,
        mutate_reference=mutate_reference,
    )
    gate = _gates(_evaluate_report_path(report_path))["approved_evaluation_corpora"]
    assert gate["status"] == "pending_policy"
    assert all(value is None for value in gate["threshold"].values())


@pytest.mark.parametrize(
    ("mutation", "expected_status"),
    [("exact", "pass"), ("substituted_hardware", "fail"), ("missing_tier", "fail")],
)
def test_device_tiers_must_match_registry_pinned_profiles_exactly(
    tmp_path: Path,
    mutation: str,
    expected_status: str,
) -> None:
    report = _passing_report()
    approved_profiles = sorted(
        (_device_profile(tier) for tier in report["mobile"]["device_tiers"]),
        key=lambda profile: profile["tier_id"],
    )
    registry_payload = json.loads(DEFAULT_REGISTRY.read_text(encoding="utf-8"))
    registry_payload["scorecard_gates"]["approved_device_tier_profiles"] = (
        approved_profiles
    )
    registry_path = tmp_path / "registry.json"
    registry_path.write_text(json.dumps(registry_payload), encoding="utf-8")
    registry = validate_registry(registry_path)
    report["lineage"]["selection_registry_sha256"] = registry.sha256
    if mutation == "substituted_hardware":
        report["mobile"]["device_tiers"][0]["hardware_model_id"] = (
            "unapproved-flagship-model"
        )
    elif mutation == "missing_tier":
        removed = report["mobile"]["device_tiers"].pop()
        report["mobile"]["supported_device_tier_ids"].remove(removed["tier_id"])
    _seal_report(report)
    validated = _validated_report(tmp_path / "bundle", report)

    result = evaluate_candidate(
        registry,
        validate_manifest(DEFAULT_MANIFEST),
        validated,
        approved_license_gates=[
            "apache_notice_review",
            "attribution_review",
            "attribution_share_alike_review",
        ],
    )
    assert _gates(result)["approved_device_tier_profiles"]["status"] == expected_status


@pytest.mark.parametrize(
    ("mutate", "gate_id", "reason_fragment"),
    [
        (
            lambda report: report["primary_semantics"].update(
                {
                    "true_positive_count": 900,
                    "false_negative_count": 100,
                    "confirmed_numeric_prediction_count": 900,
                }
            ),
            "confirmed_numeric_recall_coverage",
            "overall Wilson recall",
        ),
        (
            lambda report: report["restrictions"].update(
                {
                    "true_positive_count": 800,
                    "false_negative_count": 200,
                    "resolved_prediction_count": 800,
                }
            ),
            "resolved_restriction_recall_coverage",
            "overall Wilson recall",
        ),
        (
            lambda report: report["primary_semantics"].update(
                {"ground_truth_count": 999}
            ),
            "confirmed_numeric_recall_coverage",
            "ground truth does not equal TP + FN",
        ),
        (
            lambda report: report["primary_semantics"].update(
                {"evaluated_case_count": 999}
            ),
            "confirmed_numeric_recall_coverage",
            "holdout inventory",
        ),
        (
            lambda report: report["primary_semantics"]["strata"][0].update(
                {"case_count": 99}
            ),
            "confirmed_numeric_recall_coverage",
            "stratum case count differs",
        ),
    ],
)
def test_recall_coverage_is_fail_closed(
    tmp_path: Path,
    mutate,
    gate_id: str,
    reason_fragment: str,
) -> None:
    payload = _passing_report()
    mutate(payload)
    gate = _gates(_evaluate(tmp_path, payload))[gate_id]
    assert gate["status"] == "fail"
    assert any(reason_fragment in reason for reason in gate["reasons"])


def test_recall_denominators_are_anchored_to_verified_inventory(
    tmp_path: Path,
) -> None:
    report = _passing_report()
    inventory = report["holdout"]["case_inventory"]
    inventory["cases"][0]["primary_ground_truth_count"] = 0
    _recompute_case_inventory(inventory)
    _seal_report(report)
    _sync_holdout_inventory_references(report)
    _seal_report(report)

    gate = _gates(_evaluate(tmp_path, report))["confirmed_numeric_recall_coverage"]
    assert gate["status"] == "fail"
    assert any(
        "ground-truth count differs from the holdout inventory" in reason
        for reason in gate["reasons"]
    )


def test_every_frozen_inventory_stratum_must_be_reported_even_if_not_policy_named(
    tmp_path: Path,
) -> None:
    report = _passing_report()
    inventory = report["holdout"]["case_inventory"]
    for case in inventory["cases"][:100]:
        case["strata"].append("tunnel")
    _recompute_case_inventory(inventory)
    _seal_report(report)
    _sync_holdout_inventory_references(report)
    _seal_report(report)
    gates = _gates(_evaluate(tmp_path, report))

    assert gates["field_regression_strata"]["status"] == "fail"
    assert gates["confirmed_numeric_recall_coverage"]["status"] == "fail"
    assert gates["resolved_restriction_recall_coverage"]["status"] == "fail"
    assert any(
        "missing holdout-inventory recall strata: tunnel" in reason
        for reason in gates["confirmed_numeric_recall_coverage"]["reasons"]
    )


def test_zero_recall_denominator_fails_for_policy_required_stratum(
    tmp_path: Path,
) -> None:
    report = _passing_report()
    inventory = report["holdout"]["case_inventory"]
    for case in inventory["cases"]:
        if "weather" in case["strata"]:
            case["primary_ground_truth_count"] = 0
    _recompute_case_inventory(inventory)
    _sync_perfect_recall_metrics(report)
    _seal_report(report)
    _sync_holdout_inventory_references(report)
    _seal_report(report)
    _schema_validator().validate(report)
    gate = _gates(_evaluate(tmp_path, report))["confirmed_numeric_recall_coverage"]
    assert gate["status"] == "fail"
    assert any(
        "zero for required stratum: weather" in reason for reason in gate["reasons"]
    )


def test_optional_stratum_can_have_zero_denominator_for_one_task(
    tmp_path: Path,
) -> None:
    report = _passing_report()
    inventory = report["holdout"]["case_inventory"]
    for case in inventory["cases"][300:400]:
        case["strata"].append("tunnel")
        case["restriction_ground_truth_count"] = 0
    _recompute_case_inventory(inventory)
    report["holdout"]["strata"].append(
        {"name": "tunnel", "case_count": 100, "failure_count": 0}
    )
    _sync_perfect_recall_metrics(report)
    _seal_report(report)
    _sync_holdout_inventory_references(report)
    _seal_report(report)
    _schema_validator().validate(report)
    gates = _gates(_evaluate(tmp_path, report))
    assert gates["field_regression_strata"]["status"] == "pass"
    assert gates["confirmed_numeric_recall_coverage"]["status"] == "pass"
    assert gates["resolved_restriction_recall_coverage"]["status"] == "pass"


def test_overall_recall_denominator_must_be_positive_in_both_validators(
    tmp_path: Path,
) -> None:
    report = _passing_report()
    report["primary_semantics"]["ground_truth_count"] = 0
    with pytest.raises(jsonschema.ValidationError):
        _schema_validator().validate(report)
    with pytest.raises(ModelSelectionError, match="positive"):
        _validated_report(tmp_path, report)


@pytest.mark.parametrize(
    "mutate",
    [
        lambda report: report["lineage"]["training_run"]["manifest"]["components"][
            0
        ].update({"family": "Other Detector"}),
        lambda report: report["parity"]["components"][0].update(
            {"coreml_sha256": _hash(40)}
        ),
        _replace_mobile_artifact_identity,
        lambda report: report["calibration"].update(
            {"dataset_inventory_sha256": _hash(42)}
        ),
        lambda report: report["lineage"]["training_run"]["manifest"][
            "training_dataset_bundle"
        ].update({"inventory_file": _opaque_ref("datasets/other-inventory.json")}),
        lambda report: report["primary_semantics"].update(
            {"holdout_case_inventory_sha256": _hash(43)}
        ),
        lambda report: report["mobile"]["device_tiers"][0].update(
            {"artifact_sha256s": [_hash(44), _hash(45)]}
        ),
        lambda report: report["parity"].update(
            {"training_run_manifest_sha256": _hash(46)}
        ),
        lambda report: report["primary_semantics"].update(
            {"training_run_manifest_sha256": _hash(47)}
        ),
        lambda report: report["restrictions"]["components"][0].update(
            {"reference_onnx_sha256": _hash(48)}
        ),
        lambda report: report["temporal_behavior"]["components"][0].update(
            {"litert_sha256": _hash(49)}
        ),
    ],
)
def test_lineage_binds_candidate_datasets_components_parity_mobile_and_device_evidence(
    tmp_path: Path,
    mutate,
) -> None:
    payload = _passing_report()
    mutate(payload)
    lineage = _gates(_evaluate(tmp_path, payload))["lineage"]
    assert lineage["status"] == "fail"
    assert lineage["reasons"]


@pytest.mark.parametrize(
    "mutate_manifest",
    [
        lambda manifest: manifest.update(
            {"candidate_id": "de-yolox-nano-direct-ios-shadow"}
        ),
        lambda manifest: manifest["components"][0].update(
            {"family": "Different Detector Family"}
        ),
        lambda manifest: manifest["components"][0].update(
            {
                "source_refs": [
                    {
                        "source_id": "gtsign-220-e235536",
                        "artifact_id": "gtsign-220-vit-all-classes",
                    }
                ]
            }
        ),
    ],
)
def test_resigned_training_manifest_still_must_match_candidate_identity(
    tmp_path: Path,
    mutate_manifest,
) -> None:
    report = _passing_report()
    mutate_manifest(report["lineage"]["training_run"]["manifest"])
    _seal_report(report)
    _sync_training_manifest_references(report)
    _seal_report(report)

    lineage = _gates(_evaluate(tmp_path, report))["lineage"]
    assert lineage["status"] == "fail"
    assert lineage["reasons"]


def test_training_dataset_source_lineage_must_resolve_to_known_dataset_sources(
    tmp_path: Path,
) -> None:
    report = _passing_report()
    bundle = report["lineage"]["training_run"]["manifest"]["training_dataset_bundle"]
    bundle["source_ids"][-1] = "unknown-dataset-source"
    bundle["source_ids"].sort()
    _seal_report(report)
    _sync_training_manifest_references(report)
    _seal_report(report)
    validated = _validated_report(tmp_path, report)

    with pytest.raises(ModelSelectionError, match="unknown source_id"):
        evaluate_candidate(
            validate_registry(),
            validate_manifest(DEFAULT_MANIFEST),
            validated,
            approved_license_gates=["apache_notice_review"],
        )


@pytest.mark.parametrize("mutation", ["missing_case", "missing_output", "extra_output"])
def test_parity_requires_every_case_and_output_without_missing_or_extra_results(
    tmp_path: Path,
    mutation: str,
) -> None:
    report = _passing_report()
    report_path = _write_bundle(tmp_path, report)

    def mutate_runtime(runtime: str, payload: dict) -> None:
        if runtime != "coreml":
            return
        if mutation == "missing_case":
            payload["evaluated_case_ids"].pop()
            payload["outputs"].pop()
        elif mutation == "missing_output":
            payload["outputs"].pop()
        else:
            payload["outputs"].append(
                {
                    "output_id": "unexpected-output",
                    "case_id": payload["evaluated_case_ids"][0],
                    "semantic_label": "speed-limit-50",
                    "assembly_label": "unconditional",
                    "box_xyxy": [0.1, 0.1, 0.2, 0.2],
                    "calibrated_confidence": 0.99,
                }
            )

    _replace_parity_evidence(
        tmp_path, report_path, report, mutate_runtime=mutate_runtime
    )
    _path, validated = validate_evaluation_report(report_path)
    parity = _gates(
        evaluate_candidate(
            validate_registry(),
            validate_manifest(DEFAULT_MANIFEST),
            validated,
            approved_license_gates=["apache_notice_review"],
        )
    )["cross_runtime_parity"]
    assert parity["status"] == "fail"


def test_parity_observations_are_derived_from_complete_normalized_outputs(
    tmp_path: Path,
) -> None:
    gate = _gates(_evaluate(tmp_path, _passing_report()))["cross_runtime_parity"]

    assert gate["observed"]["case_count"] == 1000
    assert gate["observed"]["reference_output_count"] == 1000
    assert gate["observed"]["reference_missing_case_count"] == 0
    assert gate["observed"]["semantic_mismatch_count"] == 0
    assert all(
        runtime["matched_reference_output_count"] == 1000
        and runtime["missing_reference_output_count"] == 0
        and runtime["unexpected_output_count"] == 0
        for runtime in gate["observed"]["runtime_counts"]
    )


def test_parity_one_case_bundle_fails_versioned_inventory_floors(
    tmp_path: Path,
) -> None:
    report = _passing_report()
    report_path = _write_bundle(tmp_path, report)
    _replace_parity_evidence(tmp_path, report_path, report, case_count=1)

    gate = _gates(_evaluate_report_path(report_path))["cross_runtime_parity"]
    assert gate["status"] == "fail"
    assert any("case count is below" in reason for reason in gate["reasons"])
    assert any(
        "reference-output count is below" in reason for reason in gate["reasons"]
    )


def test_parity_same_count_case_substitution_is_detected(tmp_path: Path) -> None:
    report = _passing_report()
    report_path = _write_bundle(tmp_path, report)

    def mutate_runtime(runtime: str, payload: dict) -> None:
        if runtime == "coreml":
            payload["evaluated_case_ids"][-1] = "unrelated-case"
            payload["outputs"][-1]["case_id"] = "unrelated-case"

    _replace_parity_evidence(
        tmp_path, report_path, report, mutate_runtime=mutate_runtime
    )
    gate = _gates(_evaluate_report_path(report_path))["cross_runtime_parity"]
    coreml = next(
        item
        for item in gate["observed"]["runtime_counts"]
        if item["runtime"] == "coreml"
    )

    assert gate["status"] == "fail"
    assert coreml["evaluated_case_count"] == 1000
    assert coreml["missing_case_count"] == 1
    assert coreml["unexpected_case_count"] == 1


@pytest.mark.parametrize(
    "mutation",
    ["semantic", "assembly", "box", "confidence"],
)
def test_parity_scores_are_derived_from_rehashed_runtime_outputs(
    tmp_path: Path,
    mutation: str,
) -> None:
    report = _passing_report()
    report_path = _write_bundle(tmp_path, report)

    def mutate_runtime(runtime: str, payload: dict) -> None:
        if runtime != "coreml":
            return
        output = payload["outputs"][0]
        if mutation == "semantic":
            output["semantic_label"] = "speed-limit-60"
        elif mutation == "assembly":
            output["assembly_label"] = "restricted"
        elif mutation == "box":
            output["box_xyxy"] = [0.1, 0.1, 0.21, 0.2]
        else:
            output["calibrated_confidence"] = 0.9

    _replace_parity_evidence(
        tmp_path, report_path, report, mutate_runtime=mutate_runtime
    )
    assert (
        _gates(_evaluate_report_path(report_path))["cross_runtime_parity"]["status"]
        == "fail"
    )


@pytest.mark.parametrize("identity", ["manifest", "artifact"])
def test_parity_output_files_bind_exact_training_and_runtime_artifact_identity(
    tmp_path: Path,
    identity: str,
) -> None:
    report = _passing_report()
    report_path = _write_bundle(tmp_path, report)

    def mutate_runtime(runtime: str, payload: dict) -> None:
        if runtime == "coreml":
            if identity == "manifest":
                payload["training_run_manifest_sha256"] = _hash(98)
            else:
                payload["artifact_sha256s"][0] = _hash(99)

    _replace_parity_evidence(
        tmp_path, report_path, report, mutate_runtime=mutate_runtime
    )
    with pytest.raises(
        ModelSelectionError, match="another training run|other runtime artifacts"
    ):
        validate_evaluation_report(report_path)


@pytest.mark.parametrize(
    ("mutate", "gate_id", "reason_fragment"),
    [
        (
            lambda report: report["mobile"]["device_tiers"][0].update(
                {"detector_inference_count": 999}
            ),
            "device_latency",
            "inference count",
        ),
        (
            lambda report: report["mobile"]["device_tiers"][0].update(
                {"drive_duration_seconds": 1799}
            ),
            "runtime_safety",
            "drive duration",
        ),
        (
            lambda report: report["mobile"]["device_tiers"][0].update(
                {"peak_memory_bytes": 256_000_001}
            ),
            "runtime_safety",
            "peak memory",
        ),
        (
            lambda report: report["mobile"]["device_tiers"][0].update(
                {"dropped_frame_count": 541}
            ),
            "runtime_safety",
            "dropped-frame rate",
        ),
        (
            lambda report: report["mobile"]["device_tiers"][0].update(
                {"backpressure_event_count": 55}
            ),
            "runtime_safety",
            "backpressure-event rate",
        ),
        (
            lambda report: report["mobile"]["device_tiers"][0].update(
                {"thermal_downshift_verified": False}
            ),
            "runtime_safety",
            "thermal-downshift",
        ),
        (
            lambda report: report["mobile"]["device_tiers"][0].update(
                {"recording_unaffected": False}
            ),
            "runtime_safety",
            "preserve recording",
        ),
        (
            lambda report: report["mobile"]["device_tiers"][0].update(
                {"camera_frame_count": 3600}
            ),
            "runtime_safety",
            "camera capture rate",
        ),
    ],
)
def test_device_evidence_enforces_versioned_duration_load_memory_and_camera_impact(
    tmp_path: Path,
    mutate,
    gate_id: str,
    reason_fragment: str,
) -> None:
    payload = _passing_report()
    mutate(payload)
    gate = _gates(_evaluate(tmp_path, payload))[gate_id]
    assert gate["status"] == "fail"
    assert any(reason_fragment in reason for reason in gate["reasons"])


@pytest.mark.parametrize(
    ("mutate", "reason_fragment"),
    [
        (
            lambda tier: tier.update({"camera_frame_count": 3599}),
            "inferences exceed captured camera frames",
        ),
        (
            lambda tier: tier.update({"end_to_end_inference_count": 3601}),
            "inference counts differ",
        ),
        (
            lambda tier: tier.update(
                {
                    "detector_inference_count": 18_001,
                    "end_to_end_inference_count": 18_001,
                }
            ),
            "inference rate exceeds threshold",
        ),
    ],
)
def test_device_inference_coverage_is_coherent_with_frames_and_duration(
    tmp_path: Path,
    mutate,
    reason_fragment: str,
) -> None:
    report = _passing_report()
    mutate(report["mobile"]["device_tiers"][0])
    gate = _gates(_evaluate(tmp_path, report))["device_latency"]
    assert gate["status"] == "fail"
    assert any(reason_fragment in reason for reason in gate["reasons"])


def test_pack_size_must_equal_verified_artifact_sizes(tmp_path: Path) -> None:
    report = _passing_report()
    report["mobile"]["pack_size_bytes"] += 1
    gate = _gates(_evaluate(tmp_path, report))["mobile_size"]
    assert gate["status"] == "fail"
    assert any("verified artifact total" in reason for reason in gate["reasons"])


def test_mobile_artifact_size_is_recomputed_from_verified_bytes(tmp_path: Path) -> None:
    report = _passing_report()
    report["mobile"]["artifacts"][0]["size_bytes"] += 1
    report["mobile"]["pack_size_bytes"] += 1
    _seal_report(report)
    with pytest.raises(ModelSelectionError, match="size_bytes differs"):
        _validated_report(tmp_path, report)


def test_evaluator_rejects_unapproved_license_and_dangerous_substitution(
    tmp_path: Path,
) -> None:
    payload = _passing_report()
    payload["primary_semantics"]["true_positive_count"] = 999
    payload["primary_semantics"]["false_positive_count"] = 1
    payload["primary_semantics"]["false_negative_count"] = 1
    payload["primary_semantics"]["dangerous_substitution_count"] = 1
    result = _evaluate(tmp_path, payload, approve=False)
    gates = _gates(result)
    assert gates["licensing"]["status"] == "fail"
    assert gates["dangerous_substitutions"]["status"] == "pass"
    assert gates["dangerous_substitutions"]["observed"]["rate"] == 0.001


def test_evaluator_computes_ece_and_enforces_parity_size_latency(
    tmp_path: Path,
) -> None:
    payload = _passing_report()
    payload["calibration"]["bins"][0]["confidence_sum"] = 900
    payload["mobile"]["pack_size_bytes"] = 25_000_001
    payload["mobile"]["device_tiers"][0]["detector_p95_ms"] = 251
    _seal_report(payload)
    report_path = _write_bundle(tmp_path, payload)

    def mutate_runtime(runtime: str, outputs: dict) -> None:
        if runtime == "coreml":
            outputs["outputs"][0]["semantic_label"] = "speed-limit-60"

    _replace_parity_evidence(
        tmp_path, report_path, payload, mutate_runtime=mutate_runtime
    )
    _path, report = validate_evaluation_report(report_path)
    result = evaluate_candidate(
        validate_registry(),
        validate_manifest(DEFAULT_MANIFEST),
        report,
        approved_license_gates=["apache_notice_review"],
    )
    gates = _gates(result)

    assert gates["calibration"]["observed"]["expected_calibration_error"] == 0.09
    assert gates["calibration"]["status"] == "fail"
    assert gates["cross_runtime_parity"]["status"] == "fail"
    assert gates["mobile_size"]["status"] == "fail"
    assert gates["device_latency"]["status"] == "fail"


def test_evaluation_output_order_is_deterministic(tmp_path: Path) -> None:
    report = _validated_report(tmp_path, _passing_report())
    registry = validate_registry()
    sources = validate_manifest(DEFAULT_MANIFEST)
    first = evaluate_candidate(
        registry, sources, report, approved_license_gates=["apache_notice_review"]
    )
    second = evaluate_candidate(
        registry,
        sources,
        copy.deepcopy(report),
        approved_license_gates=["apache_notice_review"],
    )

    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert [gate["gate_id"] for gate in first["gates"]] == [
        "candidate_readiness",
        "lineage",
        "licensing",
        "approved_evaluation_corpora",
        "approved_device_tier_profiles",
        "real_route_holdout",
        "field_regression_strata",
        "leakage",
        "confirmed_numeric_precision",
        "confirmed_numeric_recall_coverage",
        "dangerous_substitutions",
        "resolved_restriction_precision",
        "resolved_restriction_recall_coverage",
        "unresolved_restriction_safety",
        "calibration",
        "cross_runtime_parity",
        "mobile_size",
        "device_latency",
        "runtime_safety",
        "temporal_duplicate_confirmations",
        "temporal_wrong_way_confirmations",
    ]


def test_evaluate_cli_prints_scorecard_block_without_mutating_selection(
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
) -> None:
    report_path = _write_bundle(tmp_path, _passing_report())

    exit_code = main(
        [
            "--registry",
            str(DEFAULT_REGISTRY),
            "--sources",
            str(DEFAULT_MANIFEST),
            "evaluate",
            str(report_path),
            "--approve-license-gate",
            "apache_notice_review",
        ]
    )
    output = json.loads(capsys.readouterr().out)

    assert exit_code == 1
    assert output["decision"] == "model_scorecard_blocked"
    assert output["model_scorecard_eligible"] is False
    assert (
        json.loads(DEFAULT_REGISTRY.read_text(encoding="utf-8"))[
            "selected_candidate_id"
        ]
        is None
    )


def test_selector_never_imports_model_frameworks_pickle_or_jsonschema() -> None:
    tree = ast.parse(SCRIPT.read_text(encoding="utf-8"))
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])

    assert imported_roots.isdisjoint(
        {
            "coremltools",
            "jsonschema",
            "onnx",
            "pickle",
            "tensorflow",
            "torch",
            "ultralytics",
        }
    )
