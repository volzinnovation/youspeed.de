#!/usr/bin/env python3
"""Validate the TSR M0 v2 training/export/evidence plan without executing it.

This is a control-plane tool only.  It never downloads data, invokes a model
framework, deserializes checkpoint bytes, starts training, exports a model, or
creates evidence.  ``validate`` checks the checked-in plan and its pinned
repository contracts.  ``status`` additionally hashes already-present local
inputs and outputs and reports every missing or unattested prerequisite.

Exit codes are 0 for a valid/complete request, 1 for a valid but blocked M0
status, and 2 for an invalid or unsafe plan/evidence layout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Mapping, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PLAN = REPOSITORY_ROOT / "shared" / "tsr" / "m0-workflow-v1.json"
DEFAULT_PLAN_SCHEMA = REPOSITORY_ROOT / "shared" / "tsr" / "m0-workflow-v1.schema.json"
DEFAULT_BUNDLE_ROOT = REPOSITORY_ROOT / "artifacts" / "tsr" / "m0-v2"
DEFAULT_SOURCE_ROOT = REPOSITORY_ROOT / "artifacts" / "tsr" / "bootstrap"

if __package__:
    from .bootstrap_sources import (  # type: ignore[import-not-found]
        SourceManifestError,
        ValidatedSourceManifest,
        validate_manifest,
    )
    from .group_splits_v2 import (  # type: ignore[import-not-found]
        GroupSplitError,
        validate_group_split,
    )
    from .model_selection import (  # type: ignore[import-not-found]
        ModelSelectionError,
        ValidatedSelectionRegistry,
        evaluate_candidate,
        validate_evaluation_report,
        validate_registry,
    )
else:
    sys.path.insert(0, str(REPOSITORY_ROOT))
    from scripts.tsr.bootstrap_sources import (  # noqa: E402
        SourceManifestError,
        ValidatedSourceManifest,
        validate_manifest,
    )
    from scripts.tsr.group_splits_v2 import (  # noqa: E402
        GroupSplitError,
        validate_group_split,
    )
    from scripts.tsr.model_selection import (  # noqa: E402
        ModelSelectionError,
        ValidatedSelectionRegistry,
        evaluate_candidate,
        validate_evaluation_report,
        validate_registry,
    )


SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
SHA256 = re.compile(r"^[a-f0-9]{64}$")
ZERO_SHA256 = "0" * 64

TARGET_CANDIDATE_ID = "de-yolox-nano-mnv3-large-proposal-classification"
CHALLENGER_CANDIDATE_ID = "de-yolox-nano-mnv3-small-proposal-classification"
DETECTOR_COMPONENT_ID = "m0-yolox-nano-two-role-detector-v2"
LARGE_COMPONENT_ID = "m0-mobilenetv3-large-union-classifier-v2"
SMALL_COMPONENT_ID = "m0-mobilenetv3-small-union-classifier-v2"

EXPECTED_CONTRACTS = {
    "taxonomy-v2": (
        "shared/tsr/taxonomy-v2.json",
        None,
    ),
    "zod-supplementary-plate-audit-v1": (
        "shared/tsr/zod-supplementary-plate-audit-v1.json",
        None,
    ),
    "full-scene-annotation-v2-schema": (
        "shared/tsr/full-scene-annotation-v2.schema.json",
        "https://youspeed.de/schemas/tsr/full-scene-annotation-v2.json",
    ),
    "group-split-v2-schema": (
        "shared/tsr/group-split-v2.schema.json",
        "https://youspeed.de/schemas/tsr/group-split-v2.json",
    ),
    "model-pack-v2-schema": (
        "shared/tsr/model-pack-v2.schema.json",
        "https://youspeed.de/schemas/tsr/model-pack-v2.json",
    ),
    "model-evaluation-v1-schema": (
        "shared/tsr/model-evaluation.schema.json",
        "https://youspeed.de/schemas/tsr/model-evaluation-v1.json",
    ),
    "recognition-event-v2-schema": (
        "shared/tsr/recognition-event-v2.schema.json",
        "https://youspeed.de/schemas/tsr/recognition-event-v2.json",
    ),
}

EXPECTED_SOURCE_REQUIREMENTS = {
    "yolox-initialization": (
        "training",
        "yolox-0.1.1rc0",
        "yolox-nano-coco-0.1.1rc0",
    ),
    "mnv3-large-initialization": (
        "training",
        "timm-mobilenetv3-large-ra-in1k-96f46a1",
        "mobilenetv3-large-ra-in1k-96f46a1",
    ),
    "mnv3-small-initialization": (
        "training",
        "timm-mobilenetv3-small-lamb-in1k-1824797",
        "mobilenetv3-small-lamb-in1k-1824797",
    ),
    "gtsign-offline-teacher": (
        "training",
        "gtsign-220-e235536",
        "gtsign-220-vit-all-classes",
    ),
    "panoramax-training-crops": (
        "training",
        "panoramax-de-crops-b485694",
        "panoramax-de-train-b485694",
    ),
    "synset-training-archive": (
        "training",
        "synset-signset-germany-dcc1znjxu7apx8rn",
        "synset-signset-germany-archive",
    ),
    "panoramax-offline-benchmark": (
        "evidence",
        "panoramax-de-classifier-5360aa6",
        "panoramax-de-yolo26-classifier-5360aa6",
    ),
}

EXPECTED_DATA_REQUIREMENTS = {
    "reviewed-full-scene-annotations": (
        "full_scene_annotation_manifest_v2",
        "training",
    ),
    "grouped-train-calibration-holdout-split": (
        "group_split_manifest_v2",
        "training",
    ),
    "zod-byte-inventory": ("sha256_inventory", "training"),
    "gtsign-byte-inventory": ("sha256_inventory", "training"),
    "panoramax-regrouped-byte-inventory": ("sha256_inventory", "training"),
    "synset-byte-inventory": ("sha256_inventory", "training"),
    "gtsign-taxonomy-adapter": ("taxonomy_adapter", "training"),
    "panoramax-taxonomy-adapter": ("taxonomy_adapter", "evidence"),
    "training-environment-lock": ("environment_lock", "training"),
    "export-environment-lock": ("environment_lock", "export"),
    "detector-training-recipe": ("training_recipe", "training"),
    "large-classifier-training-recipe": ("training_recipe", "training"),
    "small-classifier-training-recipe": ("training_recipe", "training"),
    "mobile-export-recipe": ("export_recipe", "export"),
    "parity-corpus-inventory": ("parity_corpus_inventory", "evidence"),
}

EXPECTED_COMPONENTS = {
    DETECTOR_COMPONENT_ID: {
        "registry_role": "proposal_detector",
        "pack_role": "proposal_detector",
        "architecture": "YOLOX-Nano",
        "source_ref": ("yolox-0.1.1rc0", "yolox-nano-coco-0.1.1rc0"),
        "family": "m0-yolox-nano-detector-v2",
        "requirements": {
            "reviewed-full-scene-annotations",
            "grouped-train-calibration-holdout-split",
            "zod-byte-inventory",
            "training-environment-lock",
            "detector-training-recipe",
        },
    },
    LARGE_COMPONENT_ID: {
        "registry_role": "classifier",
        "pack_role": "semantic_classifier",
        "architecture": "MobileNetV3-Large",
        "source_ref": (
            "timm-mobilenetv3-large-ra-in1k-96f46a1",
            "mobilenetv3-large-ra-in1k-96f46a1",
        ),
        "family": "m0-mnv3-large-classifier-v2",
        "requirements": {
            "grouped-train-calibration-holdout-split",
            "gtsign-byte-inventory",
            "panoramax-regrouped-byte-inventory",
            "synset-byte-inventory",
            "gtsign-taxonomy-adapter",
            "training-environment-lock",
            "large-classifier-training-recipe",
        },
    },
    SMALL_COMPONENT_ID: {
        "registry_role": "classifier",
        "pack_role": "semantic_classifier",
        "architecture": "MobileNetV3-Small",
        "source_ref": (
            "timm-mobilenetv3-small-lamb-in1k-1824797",
            "mobilenetv3-small-lamb-in1k-1824797",
        ),
        "family": "m0-mnv3-small-classifier-v2",
        "requirements": {
            "grouped-train-calibration-holdout-split",
            "gtsign-byte-inventory",
            "panoramax-regrouped-byte-inventory",
            "synset-byte-inventory",
            "gtsign-taxonomy-adapter",
            "training-environment-lock",
            "small-classifier-training-recipe",
        },
    },
}

ARTIFACT_CONVENTIONS = {
    "checkpoint": ("checkpoint", "safetensors", "training", ".safetensors"),
    "onnx": ("onnx", "onnx", "reference", ".onnx"),
    "coreml": ("coreml", "coreml_mlpackage_zip", "ios", ".mlpackage.zip"),
    "litert": ("litert", "tflite_flatbuffer", "android", ".tflite"),
}


class M0WorkflowError(ValueError):
    """Raised when an M0 plan or local evidence layout is unsafe."""


@dataclass(frozen=True)
class ValidatedWorkflow:
    plan_path: Path
    plan_sha256: str
    payload: dict[str, Any]
    repository_root: Path
    source_manifest: ValidatedSourceManifest
    registry: ValidatedSelectionRegistry
    contracts_by_id: Mapping[str, tuple[Path, dict[str, Any]]]
    components_by_id: Mapping[str, dict[str, Any]]
    candidates_by_id: Mapping[str, dict[str, Any]]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise M0WorkflowError(message)


def _reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise M0WorkflowError(f"duplicate JSON key: {key}")
        result[key] = value
    return result


def _reject_nonfinite(value: str) -> None:
    raise M0WorkflowError(f"non-finite JSON number is not allowed: {value}")


def _load_json(path: Path | str, label: str) -> tuple[Path, bytes, dict[str, Any]]:
    candidate = Path(path).expanduser()
    _require(not candidate.is_symlink(), f"{label} cannot be a symlink")
    resolved = candidate.resolve()
    _require(resolved.is_file(), f"missing {label}: {resolved}")
    try:
        raw = resolved.read_bytes()
        payload = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=_reject_duplicate_keys,
            parse_constant=_reject_nonfinite,
        )
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise M0WorkflowError(f"cannot read {label} {resolved}: {error}") from error
    _require(isinstance(payload, dict), f"{label} must be a JSON object")
    return resolved, raw, payload


def _exact_keys(value: Any, expected: Sequence[str], field: str) -> dict[str, Any]:
    _require(isinstance(value, dict), f"{field} must be an object")
    expected_set = set(expected)
    actual = set(value)
    missing = sorted(expected_set - actual)
    extra = sorted(actual - expected_set)
    _require(not missing, f"{field} is missing fields: {', '.join(missing)}")
    _require(not extra, f"{field} has unexpected fields: {', '.join(extra)}")
    return value


def _id(value: Any, field: str) -> str:
    _require(
        isinstance(value, str) and SAFE_ID.fullmatch(value) is not None,
        f"{field} must be a safe lowercase identifier",
    )
    return value


def _sha256(value: Any, field: str) -> str:
    _require(
        isinstance(value, str)
        and SHA256.fullmatch(value) is not None
        and value != ZERO_SHA256,
        f"{field} must be a non-placeholder lowercase SHA-256",
    )
    return value


def _safe_relative_path(value: Any, field: str) -> str:
    _require(isinstance(value, str) and value, f"{field} must be a path")
    _require("\\" not in value, f"{field} must use POSIX separators")
    pure = PurePosixPath(value)
    _require(not pure.is_absolute(), f"{field} must be relative")
    _require(
        pure.parts and all(part not in {"", ".", ".."} for part in pure.parts),
        f"{field} must be normalized and cannot traverse",
    )
    _require(str(pure) == value, f"{field} must be normalized")
    return value


def _resolve_safe(root: Path | str, relative_path: str, field: str) -> Path:
    root_path = Path(root).expanduser().resolve()
    relative = PurePosixPath(_safe_relative_path(relative_path, field))
    candidate = root_path
    for part in relative.parts:
        candidate = candidate / part
        _require(not candidate.is_symlink(), f"{field} must not traverse symlinks")
    resolved = candidate.resolve(strict=False)
    try:
        resolved.relative_to(root_path)
    except ValueError as error:
        raise M0WorkflowError(f"{field} escapes its root") from error
    return resolved


def _file_digest(path: Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _file_state(value: Any, field: str) -> dict[str, Any]:
    state = _exact_keys(
        value,
        ("state", "sha256", "byte_length", "blocking_reason"),
        field,
    )
    _require(state["state"] in {"pending", "available"}, f"{field}.state is invalid")
    if state["state"] == "pending":
        _require(state["sha256"] is None, f"{field}.sha256 must be null while pending")
        _require(
            state["byte_length"] is None,
            f"{field}.byte_length must be null while pending",
        )
        _require(
            isinstance(state["blocking_reason"], str)
            and bool(state["blocking_reason"].strip()),
            f"{field}.blocking_reason is required while pending",
        )
    else:
        _sha256(state["sha256"], f"{field}.sha256")
        _require(
            type(state["byte_length"]) is int and state["byte_length"] > 0,
            f"{field}.byte_length must be a positive integer when available",
        )
        _require(
            state["blocking_reason"] is None,
            f"{field}.blocking_reason must be null when available",
        )
    return state


def _source_ref(value: Any, field: str) -> tuple[str, str]:
    ref = _exact_keys(value, ("source_id", "artifact_id"), field)
    return _id(ref["source_id"], f"{field}.source_id"), _id(
        ref["artifact_id"], f"{field}.artifact_id"
    )


def _pinned_document(
    value: Any,
    field: str,
    *,
    registry: bool = False,
) -> tuple[str, str, str]:
    expected = ["document_id", "path", "sha256"]
    if registry:
        expected.append("selected_candidate_id")
    document = _exact_keys(value, expected, field)
    if registry:
        _require(
            document["selected_candidate_id"] is None,
            f"{field}.selected_candidate_id must remain null",
        )
    return (
        _id(document["document_id"], f"{field}.document_id"),
        _safe_relative_path(document["path"], f"{field}.path"),
        _sha256(document["sha256"], f"{field}.sha256"),
    )


def _verify_pinned_repository_document(
    repository_root: Path,
    path: str,
    expected_sha256: str,
    field: str,
) -> tuple[Path, dict[str, Any]]:
    resolved = _resolve_safe(repository_root, path, f"{field}.path")
    _require(resolved.is_file(), f"missing pinned {field}: {path}")
    actual = _file_digest(resolved)
    _require(actual == expected_sha256, f"{field}.sha256 does not match {path}")
    loaded_path, _raw, payload = _load_json(resolved, field)
    return loaded_path, payload


def _register_path(paths: dict[str, str], path: str, owner: str) -> None:
    prior = paths.get(path)
    _require(prior is None, f"bundle path {path} aliases {prior} and {owner}")
    paths[path] = owner


def _validate_contract_payloads(
    contracts: Mapping[str, tuple[Path, dict[str, Any]]],
) -> None:
    taxonomy = contracts["taxonomy-v2"][1]
    _require(taxonomy.get("schema_version") == 2, "taxonomy-v2 schema changed")
    _require(
        taxonomy.get("taxonomy_id") == "youspeed-tsr-semantic-v2"
        and taxonomy.get("taxonomy_version") == "tsr-semantic-v2"
        and taxonomy.get("status") == "frozen",
        "taxonomy-v2 identity or frozen status changed",
    )
    detector_classes = taxonomy.get("detector_classes")
    _require(
        isinstance(detector_classes, list), "taxonomy detector_classes are missing"
    )
    _require(
        [(item.get("class_id"), item.get("output_index")) for item in detector_classes]
        == [("primary_sign", 0), ("supplementary_plate", 1)],
        "M0 needs the exact two-role detector taxonomy",
    )
    constraints = {
        item.get("reference_id"): item
        for item in taxonomy.get("model_role_constraints", [])
        if isinstance(item, dict)
    }
    _require(
        constraints.get("gtsign-220-vit")
        == {
            "reference_id": "gtsign-220-vit",
            "role": "offline_teacher",
            "runtime_included": False,
            "acceptance_gate_eligible": False,
        },
        "GTSIGN role constraint changed",
    )
    _require(
        constraints.get("panoramax-classify-de-road-signs")
        == {
            "reference_id": "panoramax-classify-de-road-signs",
            "role": "offline_crop_benchmark",
            "runtime_included": False,
            "acceptance_gate_eligible": False,
        },
        "Panoramax role constraint changed",
    )

    audit = contracts["zod-supplementary-plate-audit-v1"][1]
    _require(
        audit.get("audit_id") == "zod-supplementary-plate-audit-v1"
        and audit.get("conclusion")
        == "no_auditable_separate_supplementary_plate_labels"
        and audit.get("eligibility", {}).get("supplementary_plate_proposal_training")
        == "ineligible",
        "ZOD supplementary-plate audit no longer matches the blocked M0 premise",
    )

    for contract_id, (_path, expected_schema_id) in EXPECTED_CONTRACTS.items():
        if expected_schema_id is not None:
            _require(
                contracts[contract_id][1].get("$id") == expected_schema_id,
                f"{contract_id} schema id changed",
            )


def _registry_component_projection(
    candidate: Mapping[str, Any],
) -> dict[str, tuple[str, set[tuple[str, str]]]]:
    projection: dict[str, tuple[str, set[tuple[str, str]]]] = {}
    for component in candidate["components"]:
        projection[component["role"]] = (
            component["family"],
            {
                (ref["source_id"], ref["artifact_id"])
                for ref in component["source_refs"]
            },
        )
    return projection


def validate_workflow_plan(
    path: Path | str = DEFAULT_PLAN,
    *,
    repository_root: Path | str = REPOSITORY_ROOT,
) -> ValidatedWorkflow:
    """Validate the static offline plan and every pinned repository contract."""

    root = Path(repository_root).expanduser().resolve()
    plan_path, raw, plan = _load_json(path, "M0 workflow plan")
    plan_schema_path = _resolve_safe(
        root,
        "shared/tsr/m0-workflow-v1.schema.json",
        "M0 workflow schema",
    )
    _require(plan_schema_path.is_file(), "missing M0 workflow JSON Schema")
    _schema_path, _schema_raw, plan_schema = _load_json(
        plan_schema_path, "M0 workflow JSON Schema"
    )
    _exact_keys(
        plan,
        (
            "schema_version",
            "workflow_id",
            "mode",
            "safety_policy",
            "source_manifest",
            "selection_registry",
            "contracts",
            "contract_mappings",
            "source_artifact_requirements",
            "data_requirements",
            "components",
            "candidate_compositions",
            "controlled_comparison",
            "external_references",
        ),
        "plan",
    )
    _require(
        type(plan["schema_version"]) is int and plan["schema_version"] == 1,
        "plan.schema_version must be integer 1",
    )
    _require(
        plan["workflow_id"] == "youspeed-tsr-m0-v2-offline",
        "unexpected M0 workflow id",
    )
    _require(plan["mode"] == "offline_readiness_only", "M0 mode must be read-only")
    safety = _exact_keys(
        plan["safety_policy"],
        (
            "network_allowed",
            "paid_compute_allowed",
            "executes_training",
            "executes_export",
            "deserializes_models",
            "generates_model_artifacts",
        ),
        "plan.safety_policy",
    )
    _require(
        all(value is False for value in safety.values()),
        "every M0 control-plane safety flag must be false",
    )

    source_id, source_path, source_sha = _pinned_document(
        plan["source_manifest"], "plan.source_manifest"
    )
    _require(
        source_id == "youspeed-tsr-training-sources-v1",
        "unexpected source manifest id",
    )
    source_file, _source_payload = _verify_pinned_repository_document(
        root, source_path, source_sha, "plan.source_manifest"
    )
    try:
        sources = validate_manifest(source_file)
    except SourceManifestError as error:
        raise M0WorkflowError(str(error)) from error

    registry_id, registry_path, registry_sha = _pinned_document(
        plan["selection_registry"], "plan.selection_registry", registry=True
    )
    _require(
        registry_id == "youspeed-tsr-model-selection-v1",
        "unexpected model-selection registry id",
    )
    registry_file, _registry_payload = _verify_pinned_repository_document(
        root, registry_path, registry_sha, "plan.selection_registry"
    )
    try:
        registry = validate_registry(registry_file, source_file)
    except (ModelSelectionError, SourceManifestError) as error:
        raise M0WorkflowError(str(error)) from error
    _require(
        registry.payload["selected_candidate_id"] is None,
        "selection registry must remain unselected",
    )

    contract_values = plan["contracts"]
    _require(isinstance(contract_values, list), "plan.contracts must be an array")
    contracts: dict[str, tuple[Path, dict[str, Any]]] = {}
    for index, value in enumerate(contract_values):
        contract_id, contract_path, contract_sha = _pinned_document(
            value, f"plan.contracts[{index}]"
        )
        _require(contract_id not in contracts, f"duplicate contract {contract_id}")
        expected = EXPECTED_CONTRACTS.get(contract_id)
        _require(expected is not None, f"unexpected contract {contract_id}")
        _require(contract_path == expected[0], f"{contract_id} path changed")
        contracts[contract_id] = _verify_pinned_repository_document(
            root, contract_path, contract_sha, f"plan.contracts[{index}]"
        )
    _require(
        set(contracts) == set(EXPECTED_CONTRACTS),
        "plan must pin every required v2/evaluation contract exactly once",
    )
    _validate_contract_payloads(contracts)

    mappings = _exact_keys(
        plan["contract_mappings"],
        (
            "registry_to_pack_roles",
            "pack_to_evaluation_artifacts",
            "serialization_to_evaluation_formats",
        ),
        "plan.contract_mappings",
    )
    _require(
        mappings["registry_to_pack_roles"]
        == {
            "proposal_detector": "proposal_detector",
            "classifier": "semantic_classifier",
        },
        "registry-to-pack role mapping changed",
    )
    _require(
        mappings["pack_to_evaluation_artifacts"]
        == {
            "checkpoint": "trained_checkpoint",
            "onnx": "reference_onnx",
            "coreml": "coreml",
            "litert": "litert",
        },
        "pack-to-evaluation artifact mapping changed",
    )
    _require(
        mappings["serialization_to_evaluation_formats"]
        == {
            "safetensors": "safetensors",
            "onnx": "onnx",
            "coreml_mlpackage_zip": "coreml-compiled-model",
            "tflite_flatbuffer": "litert-flatbuffer",
        },
        "artifact serialization mapping changed",
    )

    source_requirements = plan["source_artifact_requirements"]
    _require(
        isinstance(source_requirements, list), "source requirements must be an array"
    )
    seen_source_requirements: set[str] = set()
    for index, raw_requirement in enumerate(source_requirements):
        field = f"plan.source_artifact_requirements[{index}]"
        requirement = _exact_keys(
            raw_requirement, ("requirement_id", "phase", "source_ref"), field
        )
        requirement_id = _id(requirement["requirement_id"], f"{field}.requirement_id")
        _require(
            requirement_id not in seen_source_requirements,
            f"duplicate source requirement {requirement_id}",
        )
        seen_source_requirements.add(requirement_id)
        expected = EXPECTED_SOURCE_REQUIREMENTS.get(requirement_id)
        _require(
            expected is not None, f"unexpected source requirement {requirement_id}"
        )
        source_ref = _source_ref(requirement["source_ref"], f"{field}.source_ref")
        _require(
            (requirement["phase"], *source_ref) == expected,
            f"source requirement {requirement_id} changed",
        )
        artifact = sources.artifacts_by_id.get(source_ref[1])
        _require(artifact is not None, f"unknown source artifact {source_ref[1]}")
        _require(
            artifact["source_id"] == source_ref[0],
            f"source/artifact mismatch for {requirement_id}",
        )
    _require(
        seen_source_requirements == set(EXPECTED_SOURCE_REQUIREMENTS),
        "source artifact requirement set is incomplete",
    )

    bundle_paths: dict[str, str] = {}
    data_requirements = plan["data_requirements"]
    _require(isinstance(data_requirements, list), "data requirements must be an array")
    data_by_id: dict[str, dict[str, Any]] = {}
    for index, raw_requirement in enumerate(data_requirements):
        field = f"plan.data_requirements[{index}]"
        requirement = _exact_keys(
            raw_requirement,
            (
                "requirement_id",
                "kind",
                "phase",
                "path",
                "source_ids",
                "materialization",
            ),
            field,
        )
        requirement_id = _id(requirement["requirement_id"], f"{field}.requirement_id")
        _require(
            requirement_id not in data_by_id,
            f"duplicate data requirement {requirement_id}",
        )
        expected = EXPECTED_DATA_REQUIREMENTS.get(requirement_id)
        _require(expected is not None, f"unexpected data requirement {requirement_id}")
        _require(
            (requirement["kind"], requirement["phase"]) == expected,
            f"data requirement {requirement_id} kind/phase changed",
        )
        path_value = _safe_relative_path(requirement["path"], f"{field}.path")
        _register_path(bundle_paths, path_value, requirement_id)
        source_ids = requirement["source_ids"]
        _require(isinstance(source_ids, list), f"{field}.source_ids must be an array")
        normalized_source_ids = [
            _id(item, f"{field}.source_ids[{source_index}]")
            for source_index, item in enumerate(source_ids)
        ]
        _require(
            len(normalized_source_ids) == len(set(normalized_source_ids)),
            f"{field}.source_ids contains duplicates",
        )
        _require(
            all(
                source_id_value in sources.sources_by_id
                for source_id_value in normalized_source_ids
            ),
            f"{field}.source_ids contains an unknown source",
        )
        _file_state(requirement["materialization"], f"{field}.materialization")
        data_by_id[requirement_id] = requirement
    _require(
        set(data_by_id) == set(EXPECTED_DATA_REQUIREMENTS),
        "data requirement set is incomplete",
    )

    component_values = plan["components"]
    _require(isinstance(component_values, list), "plan.components must be an array")
    components: dict[str, dict[str, Any]] = {}
    artifact_ids: set[str] = set()
    available_artifact_hashes: set[str] = set()
    for index, raw_component in enumerate(component_values):
        field = f"plan.components[{index}]"
        component = _exact_keys(
            raw_component,
            (
                "component_id",
                "registry_role",
                "pack_role",
                "architecture",
                "initialization",
                "training_requirement_ids",
                "artifact_family_id",
                "artifacts",
            ),
            field,
        )
        component_id = _id(component["component_id"], f"{field}.component_id")
        _require(component_id not in components, f"duplicate component {component_id}")
        expected_component = EXPECTED_COMPONENTS.get(component_id)
        _require(expected_component is not None, f"unexpected component {component_id}")
        _require(
            component["registry_role"] == expected_component["registry_role"]
            and component["pack_role"] == expected_component["pack_role"]
            and component["architecture"] == expected_component["architecture"]
            and component["artifact_family_id"] == expected_component["family"],
            f"component identity changed for {component_id}",
        )
        _require(
            _source_ref(component["initialization"], f"{field}.initialization")
            == expected_component["source_ref"],
            f"component initialization changed for {component_id}",
        )
        requirement_ids = component["training_requirement_ids"]
        _require(
            isinstance(requirement_ids, list)
            and len(requirement_ids) == len(set(requirement_ids)),
            f"{field}.training_requirement_ids must be unique",
        )
        normalized_requirements = {
            _id(value, f"{field}.training_requirement_ids[]")
            for value in requirement_ids
        }
        _require(
            normalized_requirements == expected_component["requirements"],
            f"training requirements changed for {component_id}",
        )
        artifacts = _exact_keys(
            component["artifacts"], tuple(ARTIFACT_CONVENTIONS), f"{field}.artifacts"
        )
        component_artifact_ids: dict[str, str] = {}
        for role, convention in ARTIFACT_CONVENTIONS.items():
            artifact_field = f"{field}.artifacts.{role}"
            artifact = _exact_keys(
                artifacts[role],
                (
                    "artifact_id",
                    "artifact_family_id",
                    "role",
                    "format",
                    "serialization_format",
                    "platform",
                    "path",
                    "derived_from_artifact_id",
                    "materialization",
                ),
                artifact_field,
            )
            artifact_id = _id(artifact["artifact_id"], f"{artifact_field}.artifact_id")
            _require(
                artifact_id not in artifact_ids, f"duplicate artifact id {artifact_id}"
            )
            artifact_ids.add(artifact_id)
            component_artifact_ids[role] = artifact_id
            expected_format, serialization, platform, suffix = convention
            _require(
                artifact["artifact_family_id"] == component["artifact_family_id"],
                f"{artifact_field} has the wrong artifact family",
            )
            _require(
                artifact["role"] == role
                and artifact["format"] == expected_format
                and artifact["serialization_format"] == serialization
                and artifact["platform"] == platform,
                f"{artifact_field} role/format/platform attestation is invalid",
            )
            artifact_path = _safe_relative_path(
                artifact["path"], f"{artifact_field}.path"
            )
            _require(
                artifact_path.endswith(suffix),
                f"{artifact_field}.path must end in {suffix}",
            )
            _register_path(bundle_paths, artifact_path, artifact_id)
            state = _file_state(
                artifact["materialization"], f"{artifact_field}.materialization"
            )
            if state["state"] == "available":
                _require(
                    state["sha256"] not in available_artifact_hashes,
                    "materialized component artifacts must have globally distinct SHA-256 values",
                )
                available_artifact_hashes.add(state["sha256"])
        _require(
            artifacts["checkpoint"]["derived_from_artifact_id"] is None,
            f"{field} checkpoint must be the lineage root",
        )
        _require(
            artifacts["onnx"]["derived_from_artifact_id"]
            == component_artifact_ids["checkpoint"],
            f"{field} ONNX must derive from its checkpoint",
        )
        for mobile_role in ("coreml", "litert"):
            _require(
                artifacts[mobile_role]["derived_from_artifact_id"]
                == component_artifact_ids["onnx"],
                f"{field} {mobile_role} must derive from its reference ONNX",
            )
        components[component_id] = component
    _require(set(components) == set(EXPECTED_COMPONENTS), "component set changed")

    candidate_values = plan["candidate_compositions"]
    _require(
        isinstance(candidate_values, list), "candidate compositions must be an array"
    )
    candidates: dict[str, dict[str, Any]] = {}
    expected_candidates = {
        TARGET_CANDIDATE_ID: (
            f"{TARGET_CANDIDATE_ID}-m0-v2",
            "target",
            DETECTOR_COMPONENT_ID,
            LARGE_COMPONENT_ID,
        ),
        CHALLENGER_CANDIDATE_ID: (
            f"{CHALLENGER_CANDIDATE_ID}-m0-v2",
            "controlled_challenger",
            DETECTOR_COMPONENT_ID,
            SMALL_COMPONENT_ID,
        ),
    }
    for index, raw_candidate in enumerate(candidate_values):
        field = f"plan.candidate_compositions[{index}]"
        candidate = _exact_keys(
            raw_candidate,
            (
                "candidate_id",
                "expected_pack_id",
                "lane",
                "detector_component_id",
                "classifier_component_id",
                "training_manifest",
                "model_pack",
                "evaluation_report",
            ),
            field,
        )
        candidate_id = _id(candidate["candidate_id"], f"{field}.candidate_id")
        _require(candidate_id not in candidates, f"duplicate candidate {candidate_id}")
        expected = expected_candidates.get(candidate_id)
        _require(
            expected is not None, f"unexpected candidate composition {candidate_id}"
        )
        _require(
            (
                candidate["expected_pack_id"],
                candidate["lane"],
                candidate["detector_component_id"],
                candidate["classifier_component_id"],
            )
            == expected,
            f"candidate composition changed for {candidate_id}",
        )
        for output_name in ("training_manifest", "model_pack", "evaluation_report"):
            output_field = f"{field}.{output_name}"
            output = _exact_keys(
                candidate[output_name], ("path", "materialization"), output_field
            )
            output_path = _safe_relative_path(output["path"], f"{output_field}.path")
            _register_path(bundle_paths, output_path, f"{candidate_id}:{output_name}")
            _file_state(output["materialization"], f"{output_field}.materialization")
        candidates[candidate_id] = candidate
    _require(
        set(candidates) == set(expected_candidates), "candidate composition set changed"
    )

    comparison = _exact_keys(
        plan["controlled_comparison"],
        (
            "target_candidate_id",
            "challenger_candidate_id",
            "shared_detector_component_id",
            "only_controlled_variable",
        ),
        "plan.controlled_comparison",
    )
    _require(
        comparison
        == {
            "target_candidate_id": TARGET_CANDIDATE_ID,
            "challenger_candidate_id": CHALLENGER_CANDIDATE_ID,
            "shared_detector_component_id": DETECTOR_COMPONENT_ID,
            "only_controlled_variable": "semantic_classifier_architecture_initialization_and_exports",
        },
        "controlled comparison contract changed",
    )

    external_values = plan["external_references"]
    _require(isinstance(external_values, list), "external references must be an array")
    external: dict[str, dict[str, Any]] = {}
    expected_external = {
        "gtsign-220-vit": (
            "offline_teacher",
            ("gtsign-220-e235536", "gtsign-220-vit-all-classes"),
            "training",
            "gtsign-taxonomy-adapter",
        ),
        "panoramax-classify-de-road-signs": (
            "offline_crop_benchmark",
            (
                "panoramax-de-classifier-5360aa6",
                "panoramax-de-yolo26-classifier-5360aa6",
            ),
            "evidence",
            "panoramax-taxonomy-adapter",
        ),
    }
    for index, raw_reference in enumerate(external_values):
        field = f"plan.external_references[{index}]"
        reference = _exact_keys(
            raw_reference,
            (
                "reference_id",
                "role",
                "source_ref",
                "runtime_included",
                "acceptance_gate_eligible",
                "required_phase",
                "taxonomy_adapter_requirement_id",
            ),
            field,
        )
        reference_id = _id(reference["reference_id"], f"{field}.reference_id")
        _require(
            reference_id not in external, f"duplicate external reference {reference_id}"
        )
        expected = expected_external.get(reference_id)
        _require(expected is not None, f"unexpected external reference {reference_id}")
        _require(
            (
                reference["role"],
                _source_ref(reference["source_ref"], f"{field}.source_ref"),
                reference["required_phase"],
                reference["taxonomy_adapter_requirement_id"],
            )
            == expected,
            f"external reference {reference_id} changed",
        )
        _require(
            reference["runtime_included"] is False
            and reference["acceptance_gate_eligible"] is False,
            f"external reference {reference_id} must remain offline and scorecard-ineligible",
        )
        external[reference_id] = reference
    _require(set(external) == set(expected_external), "external reference set changed")

    component_source_refs = {
        _source_ref(component["initialization"], "component.initialization")
        for component in components.values()
    }
    external_source_refs = {
        _source_ref(reference["source_ref"], "external_reference.source_ref")
        for reference in external.values()
    }
    _require(
        component_source_refs.isdisjoint(external_source_refs),
        "offline references cannot initialize a mobile runtime component",
    )

    for candidate_id, candidate in candidates.items():
        registered = registry.candidates_by_id.get(candidate_id)
        _require(
            registered is not None, f"candidate {candidate_id} is absent from registry"
        )
        _require(
            registered["pipeline"] == "proposal_classification"
            and registered["eligible_for_selection"] is True,
            f"registry candidate {candidate_id} is not the selectable proposal pipeline",
        )
        if registered["status"] == "blocked":
            _require(
                bool(registered["blocking_reasons"]),
                f"blocked registry candidate {candidate_id} needs explicit reasons",
            )
        projection = _registry_component_projection(registered)
        detector = components[candidate["detector_component_id"]]
        classifier = components[candidate["classifier_component_id"]]
        _require(
            projection.get("proposal_detector")
            == (
                detector["architecture"],
                {_source_ref(detector["initialization"], "detector.initialization")},
            ),
            f"detector identity for {candidate_id} drifts from the registry",
        )
        _require(
            projection.get("classifier")
            == (
                classifier["architecture"],
                {
                    _source_ref(
                        classifier["initialization"], "classifier.initialization"
                    )
                },
            ),
            f"classifier identity for {candidate_id} drifts from the registry",
        )

    _schema_validate(plan, plan_schema, "M0 workflow plan")
    return ValidatedWorkflow(
        plan_path=plan_path,
        plan_sha256=hashlib.sha256(raw).hexdigest(),
        payload=plan,
        repository_root=root,
        source_manifest=sources,
        registry=registry,
        contracts_by_id=contracts,
        components_by_id=components,
        candidates_by_id=candidates,
    )


def _schema_validate(
    instance: Mapping[str, Any], schema: Mapping[str, Any], label: str
) -> None:
    try:
        import jsonschema
    except ImportError as error:  # pragma: no cover - environment-dependent
        raise M0WorkflowError(
            f"cannot validate {label}: jsonschema is unavailable; refusing to proceed"
        ) from error
    try:
        jsonschema.Draft202012Validator.check_schema(schema)
        jsonschema.Draft202012Validator(
            schema,
            format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
        ).validate(instance)
    except jsonschema.ValidationError as error:
        location = ".".join(str(item) for item in error.absolute_path)
        suffix = f" at {location}" if location else ""
        raise M0WorkflowError(
            f"{label} violates its schema{suffix}: {error.message}"
        ) from error
    except jsonschema.SchemaError as error:
        raise M0WorkflowError(
            f"invalid schema while checking {label}: {error.message}"
        ) from error


def _validate_inventory(
    payload: Mapping[str, Any],
    requirement: Mapping[str, Any],
    label: str,
    *,
    content_root: Path,
) -> None:
    inventory = _exact_keys(
        payload,
        ("schema_version", "inventory_id", "frozen", "source_ids", "files"),
        label,
    )
    _require(
        type(inventory["schema_version"]) is int and inventory["schema_version"] == 1,
        f"{label}.schema_version must be integer 1",
    )
    _id(inventory["inventory_id"], f"{label}.inventory_id")
    _require(inventory["frozen"] is True, f"{label} must be frozen")
    _require(
        inventory["source_ids"] == requirement["source_ids"],
        f"{label}.source_ids must match the workflow requirement exactly",
    )
    files = inventory["files"]
    _require(isinstance(files, list) and files, f"{label}.files must be non-empty")
    seen_paths: set[str] = set()
    for index, raw_file in enumerate(files):
        field = f"{label}.files[{index}]"
        file_record = _exact_keys(raw_file, ("path", "byte_length", "sha256"), field)
        path = _safe_relative_path(file_record["path"], f"{field}.path")
        _require(path not in seen_paths, f"duplicate inventory path {path}")
        seen_paths.add(path)
        _require(
            type(file_record["byte_length"]) is int and file_record["byte_length"] > 0,
            f"{field}.byte_length must be positive",
        )
        expected_sha = _sha256(file_record["sha256"], f"{field}.sha256")
        content_path = _resolve_safe(content_root, path, f"{field}.path")
        _require(content_path.is_file(), f"missing inventoried byte: {path}")
        _require(
            content_path.stat().st_size == file_record["byte_length"],
            f"inventoried byte length mismatch: {path}",
        )
        _require(
            _file_digest(content_path) == expected_sha,
            f"inventoried byte SHA-256 mismatch: {path}",
        )


def _validate_generic_attestation(
    payload: Mapping[str, Any], requirement: Mapping[str, Any], label: str
) -> None:
    kind = requirement["kind"]
    if kind == "taxonomy_adapter":
        attestation = _exact_keys(
            payload,
            (
                "schema_version",
                "adapter_id",
                "frozen",
                "source_ids",
                "target_taxonomy_version",
                "review_status",
                "mapping",
            ),
            label,
        )
        _id(attestation["adapter_id"], f"{label}.adapter_id")
    elif kind == "environment_lock":
        attestation = _exact_keys(
            payload,
            (
                "schema_version",
                "lock_id",
                "frozen",
                "source_ids",
                "network_allowed",
                "paid_compute_allowed",
                "container_image_digest",
                "dependencies_lock_sha256",
            ),
            label,
        )
        _id(attestation["lock_id"], f"{label}.lock_id")
    else:
        attestation = _exact_keys(
            payload,
            (
                "schema_version",
                "recipe_id",
                "frozen",
                "source_ids",
                "seed",
                "configuration_sha256",
                "network_allowed",
                "paid_compute_allowed",
            ),
            label,
        )
    _require(
        type(attestation["schema_version"]) is int
        and attestation["schema_version"] == 1,
        f"{label}.schema_version must be integer 1",
    )
    _require(attestation["frozen"] is True, f"{label} must be frozen")
    _require(
        attestation["source_ids"] == requirement["source_ids"],
        f"{label}.source_ids must match the workflow requirement exactly",
    )
    if kind == "taxonomy_adapter":
        _require(
            attestation["target_taxonomy_version"] == "tsr-semantic-v2",
            f"{label} targets the wrong taxonomy",
        )
        _require(
            attestation["review_status"] == "accepted",
            f"{label} must have accepted review status",
        )
        _require(
            isinstance(attestation["mapping"], list) and attestation["mapping"],
            f"{label}.mapping must be non-empty",
        )
    elif kind == "environment_lock":
        _require(
            attestation["network_allowed"] is False,
            f"{label} must disable network",
        )
        _require(
            attestation["paid_compute_allowed"] is False,
            f"{label} must disable paid compute",
        )
        digest = attestation["container_image_digest"]
        _require(
            isinstance(digest, str)
            and digest.startswith("sha256:")
            and SHA256.fullmatch(digest[7:]) is not None
            and digest[7:] != ZERO_SHA256,
            f"{label}.container_image_digest must be immutable",
        )
        _sha256(
            attestation["dependencies_lock_sha256"],
            f"{label}.dependencies_lock_sha256",
        )
    else:
        _require(
            type(attestation["seed"]) is int and attestation["seed"] >= 0,
            f"{label}.seed must be a non-negative integer",
        )
        _sha256(
            attestation["configuration_sha256"],
            f"{label}.configuration_sha256",
        )
        _require(
            attestation["network_allowed"] is False,
            f"{label} must disable network",
        )
        _require(
            attestation["paid_compute_allowed"] is False,
            f"{label} must disable paid compute",
        )


def _blocker(
    blockers: list[dict[str, str]],
    *,
    phase: str,
    code: str,
    subject: str,
    path: str,
    detail: str,
) -> None:
    blockers.append(
        {
            "phase": phase,
            "code": code,
            "subject": subject,
            "path": path,
            "detail": detail,
        }
    )


def _check_materialized_file(
    *,
    root: Path,
    relative_path: str,
    state: Mapping[str, Any],
    phase: str,
    subject: str,
    blockers: list[dict[str, str]],
) -> Path | None:
    path = _resolve_safe(root, relative_path, f"{subject}.path")
    if state["state"] == "pending":
        code = "unattested_file_present" if path.exists() else "pending_materialization"
        detail = (
            "Bytes exist but the plan has no immutable size/hash attestation."
            if path.exists()
            else state["blocking_reason"]
        )
        _blocker(
            blockers,
            phase=phase,
            code=code,
            subject=subject,
            path=relative_path,
            detail=detail,
        )
        return None
    if not path.exists():
        _blocker(
            blockers,
            phase=phase,
            code="missing_attested_file",
            subject=subject,
            path=relative_path,
            detail="The plan claims available bytes, but the file is absent.",
        )
        return None
    _require(path.is_file(), f"{subject} must resolve to a regular file")
    actual_size = path.stat().st_size
    if actual_size != state["byte_length"]:
        _blocker(
            blockers,
            phase=phase,
            code="byte_length_mismatch",
            subject=subject,
            path=relative_path,
            detail=f"Expected {state['byte_length']} bytes; found {actual_size}.",
        )
        return None
    actual_sha = _file_digest(path)
    if actual_sha != state["sha256"]:
        _blocker(
            blockers,
            phase=phase,
            code="sha256_mismatch",
            subject=subject,
            path=relative_path,
            detail="Local bytes do not match the plan SHA-256.",
        )
        return None
    return path


def _check_source_artifact(
    requirement: Mapping[str, Any],
    workflow: ValidatedWorkflow,
    source_root: Path,
    blockers: list[dict[str, str]],
) -> None:
    ref = requirement["source_ref"]
    artifact = workflow.source_manifest.artifacts_by_id[ref["artifact_id"]]
    relative_path = artifact["relative_path"]
    subject = requirement["requirement_id"]
    path = _resolve_safe(source_root, relative_path, f"source artifact {subject}")
    if not path.exists():
        _blocker(
            blockers,
            phase=requirement["phase"],
            code="missing_source_artifact",
            subject=subject,
            path=relative_path,
            detail="Pinned source bytes are not present; this tool will not download them.",
        )
        return
    _require(path.is_file(), f"source artifact {subject} must be a regular file")
    if (
        artifact["size_bytes"] is not None
        and path.stat().st_size != artifact["size_bytes"]
    ):
        _blocker(
            blockers,
            phase=requirement["phase"],
            code="source_byte_length_mismatch",
            subject=subject,
            path=relative_path,
            detail="Local source byte length differs from the pinned manifest.",
        )
        return
    for algorithm, expected in sorted(artifact["hashes"].items()):
        if _file_digest(path, algorithm) != expected:
            _blocker(
                blockers,
                phase=requirement["phase"],
                code=f"source_{algorithm}_mismatch",
                subject=subject,
                path=relative_path,
                detail=f"Local source bytes fail the pinned {algorithm} check.",
            )
            return


def _validate_data_file(
    path: Path,
    requirement: Mapping[str, Any],
    workflow: ValidatedWorkflow,
    *,
    bundle_root: Path,
    source_root: Path,
) -> None:
    _loaded_path, _raw, payload = _load_json(path, requirement["requirement_id"])
    kind = requirement["kind"]
    if kind == "full_scene_annotation_manifest_v2":
        _schema_validate(
            payload,
            workflow.contracts_by_id["full-scene-annotation-v2-schema"][1],
            requirement["requirement_id"],
        )
        accepted_plate_sources = {"youspeed_reviewed", "reviewed_synthetic"}
        accepted_plate_count = 0
        for frame in payload["frames"]:
            if any(item["role"] == "supplementary_plate" for item in frame["objects"]):
                _require(
                    frame["source"]["kind"] in accepted_plate_sources,
                    "supplementary-plate boxes must come from a reviewed YouSpeed or synthetic source",
                )
                accepted_plate_count += 1
        _require(
            accepted_plate_count > 0,
            "full-scene manifest contains no eligible supplementary-plate boxes",
        )
    elif kind == "group_split_manifest_v2":
        _schema_validate(
            payload,
            workflow.contracts_by_id["group-split-v2-schema"][1],
            requirement["requirement_id"],
        )
        try:
            validate_group_split(payload)
        except GroupSplitError as error:
            raise M0WorkflowError(str(error)) from error
        audit = payload["leakage_audit"]
        _require(
            audit["near_duplicate_analysis_status"] == "passed"
            and audit["near_duplicate_overlap_count"] == 0
            and audit["passed"] is True,
            "group split cannot be training-ready before the near-duplicate audit passes",
        )
    elif kind in {"sha256_inventory", "parity_corpus_inventory"}:
        _validate_inventory(
            payload,
            requirement,
            requirement["requirement_id"],
            content_root=(source_root if kind == "sha256_inventory" else bundle_root),
        )
    else:
        _validate_generic_attestation(
            payload, requirement, requirement["requirement_id"]
        )


def _validate_training_manifest_document(
    path: Path,
    candidate: Mapping[str, Any],
    workflow: ValidatedWorkflow,
) -> dict[str, Any]:
    _loaded, _raw, payload = _load_json(path, "training manifest")
    evaluation_schema = workflow.contracts_by_id["model-evaluation-v1-schema"][1]
    training_schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$defs": evaluation_schema["$defs"],
        "$ref": "#/$defs/trainingManifest",
    }
    _schema_validate(payload, training_schema, "training manifest")
    _require(
        payload["candidate_id"] == candidate["candidate_id"],
        "training manifest candidate_id does not match its lane",
    )
    _require(
        payload["source_manifest_id"] == workflow.source_manifest.payload["manifest_id"]
        and payload["source_manifest_sha256"]
        == workflow.payload["source_manifest"]["sha256"],
        "training manifest source lineage changed",
    )
    expected_components = {
        workflow.components_by_id[candidate["detector_component_id"]][
            "registry_role"
        ]: workflow.components_by_id[candidate["detector_component_id"]],
        workflow.components_by_id[candidate["classifier_component_id"]][
            "registry_role"
        ]: workflow.components_by_id[candidate["classifier_component_id"]],
    }
    _require(
        len(payload["components"]) == 2,
        "training manifest must bind exactly two components",
    )
    seen_roles: set[str] = set()
    mapping = workflow.payload["contract_mappings"]
    for trained in payload["components"]:
        role = trained["role"]
        _require(role not in seen_roles, f"duplicate training component role {role}")
        seen_roles.add(role)
        expected = expected_components.get(role)
        _require(expected is not None, f"unexpected training component role {role}")
        _require(
            trained["family"] == expected["architecture"], f"{role} family changed"
        )
        _require(
            {(ref["source_id"], ref["artifact_id"]) for ref in trained["source_refs"]}
            == {_source_ref(expected["initialization"], f"{role}.initialization")},
            f"{role} source lineage changed",
        )
        for pack_role, evaluation_field in mapping[
            "pack_to_evaluation_artifacts"
        ].items():
            planned = expected["artifacts"][pack_role]
            state = planned["materialization"]
            _require(
                state["state"] == "available",
                f"training manifest exists before {role}.{pack_role} is attested",
            )
            _require(
                trained[evaluation_field]["sha256"] == state["sha256"],
                f"training manifest {role}.{evaluation_field} hash changed",
            )
            expected_format = mapping["serialization_to_evaluation_formats"][
                planned["serialization_format"]
            ]
            _require(
                trained["artifact_formats"][evaluation_field] == expected_format,
                f"training manifest {role}.{evaluation_field} format changed",
            )
    return payload


def _expected_class_mapping(workflow: ValidatedWorkflow) -> list[dict[str, Any]]:
    taxonomy = workflow.contracts_by_id["taxonomy-v2"][1]
    expected: list[dict[str, Any]] = []
    for speed in taxonomy["primary_classifier_taxonomy"]["numeric_values_kmh"]:
        expected.append(
            {
                "class_id": f"speed_limit_{speed}",
                "output_index": len(expected),
                "sign_role": "primary_sign",
                "semantic": {
                    "kind": "maximum_speed",
                    "value": speed,
                    "unit": "km/h",
                    "restriction_kind": None,
                },
            }
        )
    for item in taxonomy["primary_classifier_taxonomy"]["non_numeric_classes"]:
        expected.append(
            {
                "class_id": item["class_id"],
                "output_index": len(expected),
                "sign_role": "primary_sign",
                "semantic": {
                    "kind": item["semantic_kind"],
                    "value": None,
                    "unit": None,
                    "restriction_kind": None,
                },
            }
        )
    for kind in taxonomy["supplementary_classifier_taxonomy"]["restriction_kinds"]:
        expected.append(
            {
                "class_id": f"supplementary_{kind}",
                "output_index": len(expected),
                "sign_role": "supplementary_plate",
                "semantic": {
                    "kind": "supplementary_restriction",
                    "value": None,
                    "unit": None,
                    "restriction_kind": kind,
                },
            }
        )
    return expected


def _validate_model_pack_document(
    path: Path,
    candidate: Mapping[str, Any],
    workflow: ValidatedWorkflow,
) -> dict[str, Any]:
    _loaded, _raw, payload = _load_json(path, "model pack")
    _schema_validate(
        payload,
        workflow.contracts_by_id["model-pack-v2-schema"][1],
        "model pack",
    )
    _require(
        payload["pack_id"] == candidate["expected_pack_id"], "model pack id changed"
    )
    _require(payload["countries"] == ["DE"], "M0 model pack must target Germany only")
    _require(
        payload["pipeline"] == "proposal_classification", "model pack pipeline changed"
    )
    _require(
        payload["taxonomy_version"] == "tsr-semantic-v2", "model pack taxonomy changed"
    )
    _require(
        payload["execution_policy"]["initial_mode"] == "shadow"
        and payload["execution_policy"]["override_eligible"] is False,
        "M0 model pack must remain shadow-only",
    )
    _require(
        payload["class_mapping"] == _expected_class_mapping(workflow),
        "model pack class mapping does not exactly implement taxonomy-v2",
    )
    for stage_name, component_key in (
        ("detector", "detector_component_id"),
        ("classifier", "classifier_component_id"),
    ):
        component = workflow.components_by_id[candidate[component_key]]
        stage = payload["stages"][stage_name]
        _require(
            stage["component_id"] == component["component_id"],
            f"{stage_name} id changed",
        )
        _require(
            stage["architecture"] == component["architecture"],
            f"{stage_name} family changed",
        )
        expected_preprocessing = (
            ("yolox-letterbox-rgb-640-v2", "full_frame", 640, 640)
            if stage_name == "detector"
            else ("mnv3-proposal-rgb-224-v2", "proposal_crop", 224, 224)
        )
        preprocessing = stage["preprocessing"]
        _require(
            (
                preprocessing["version"],
                preprocessing["source"],
                preprocessing["input_width"],
                preprocessing["input_height"],
            )
            == expected_preprocessing,
            f"{stage_name} preprocessing identity changed",
        )
        _require(
            preprocessing["input_dtype"] in {"float32", "float16"},
            f"{stage_name} M0 reference preprocessing must remain floating point",
        )
        calibration = stage["calibration"]
        _require(
            calibration["passed"] is True
            and calibration["runtime_output"] == "calibrated_confidence",
            f"{stage_name} calibration must be passed and used at runtime",
        )
        for role, artifact in stage["artifacts"].items():
            planned = component["artifacts"][role]
            state = planned["materialization"]
            _require(
                state["state"] == "available",
                f"model pack exists before {stage_name}.{role} is attested",
            )
            _require(
                artifact["artifact_id"] == planned["artifact_id"]
                and artifact["artifact_family_id"] == planned["artifact_family_id"]
                and artifact["sha256"] == state["sha256"]
                and artifact["byte_length"] == state["byte_length"],
                f"model pack {stage_name}.{role} identity changed",
            )
            _require(
                artifact["role"] == role
                and artifact["format"] == planned["format"]
                and artifact["platform"] == planned["platform"]
                and artifact["path"] == planned["path"]
                and artifact["derived_from_artifact_id"]
                == planned["derived_from_artifact_id"],
                f"model pack {stage_name}.{role} role/path/derivation changed",
            )
            expected_shape = (
                [1, 3, 640, 640] if stage_name == "detector" else [1, 3, 224, 224]
            )
            expected_output = (
                "yolox_role_proposals_v2"
                if stage_name == "detector"
                else "role_masked_union_logits_v2"
            )
            _require(
                artifact["input_shape"] == expected_shape
                and artifact["output_schema"] == expected_output,
                f"model pack {stage_name}.{role} tensor contract changed",
            )
            if role == "checkpoint":
                _require(
                    artifact["exporter"] is None and artifact["parity"] is None,
                    f"model pack {stage_name} checkpoint cannot claim export parity",
                )
            else:
                _require(
                    artifact["exporter"] is not None and artifact["parity"] is not None,
                    f"model pack {stage_name}.{role} needs exporter and parity evidence",
                )
                _require(
                    artifact["parity"]["reference_artifact_id"]
                    == planned["derived_from_artifact_id"]
                    and artifact["parity"]["passed"] is True,
                    f"model pack {stage_name}.{role} parity lineage did not pass",
                )
    external = {item["reference_id"]: item for item in payload["offline_references"]}
    _require(
        set(external)
        == {item["reference_id"] for item in workflow.payload["external_references"]},
        "model pack offline reference set changed",
    )
    for item in external.values():
        _require(
            item["runtime_included"] is False
            and item["acceptance_gate_eligible"] is False,
            "model pack external references must remain offline-only",
        )
        planned_reference = next(
            reference
            for reference in workflow.payload["external_references"]
            if reference["reference_id"] == item["reference_id"]
        )
        source_ref = planned_reference["source_ref"]
        source_artifact = workflow.source_manifest.artifacts_by_id[
            source_ref["artifact_id"]
        ]
        _require(
            item["role"] == planned_reference["role"]
            and item["revision"] == source_artifact["revision"]
            and item["artifact_sha256"] == source_artifact["hashes"]["sha256"],
            f"model pack offline reference {item['reference_id']} identity changed",
        )
    return payload


def _validate_candidate_document_bindings(
    candidate: Mapping[str, Any],
    documents: Mapping[str, dict[str, Any]],
    workflow: ValidatedWorkflow,
) -> None:
    training = documents["training_manifest"]
    pack = documents["model_pack"]
    report = documents["evaluation_report"]
    training_state = candidate["training_manifest"]["materialization"]
    report_state = candidate["evaluation_report"]["materialization"]

    _require(
        report["lineage"]["training_run"]["manifest"] == training
        and report["lineage"]["training_run"]["manifest_file"]["sha256"]
        == training_state["sha256"],
        "evaluation report is not bound to the planned training manifest bytes",
    )
    _require(
        report["lineage"]["selection_registry_sha256"]
        == workflow.payload["selection_registry"]["sha256"],
        "evaluation report selection-registry lineage changed",
    )
    lineage = pack["lineage"]
    full_scene_state = next(
        item["materialization"]
        for item in workflow.payload["data_requirements"]
        if item["requirement_id"] == "reviewed-full-scene-annotations"
    )
    group_split_state = next(
        item["materialization"]
        for item in workflow.payload["data_requirements"]
        if item["requirement_id"] == "grouped-train-calibration-holdout-split"
    )
    _require(
        full_scene_state["state"] == "available"
        and group_split_state["state"] == "available",
        "model pack exists before frozen annotations and group split are attested",
    )
    _require(
        lineage
        == {
            "taxonomy_sha256": next(
                item["sha256"]
                for item in workflow.payload["contracts"]
                if item["document_id"] == "taxonomy-v2"
            ),
            "source_manifest_sha256": workflow.payload["source_manifest"]["sha256"],
            "full_scene_annotation_manifest_sha256": full_scene_state["sha256"],
            "group_split_manifest_sha256": group_split_state["sha256"],
            "training_run_id": training["training_run_id"],
            "training_run_sha256": training_state["sha256"],
            "evaluation_report_sha256": report_state["sha256"],
            "parity_report_sha256": report["parity"]["report_file"]["sha256"],
        },
        "model pack lineage does not exactly bind the M0 run/evaluation documents",
    )
    _require(
        all(
            stage["calibration"]["dataset_sha256"]
            == report["calibration"]["dataset_inventory_sha256"]
            and stage["calibration"]["expected_calibration_error"]
            <= workflow.registry.payload["scorecard_gates"][
                "maximum_expected_calibration_error"
            ]
            for stage in pack["stages"].values()
        ),
        "model pack calibration is not bound to accepted evaluation evidence",
    )
    parity_corpus_sha = report["parity"]["case_inventory_file"]["sha256"]
    _require(
        all(
            artifact["parity"] is None
            or artifact["parity"]["corpus_sha256"] == parity_corpus_sha
            for stage in pack["stages"].values()
            for artifact in stage["artifacts"].values()
        ),
        "model pack artifact parity uses a different corpus",
    )
    expected_mobile_artifacts = {
        (
            component["registry_role"],
            component["artifacts"][role]["platform"],
            component["artifacts"][role]["artifact_id"],
            component["artifacts"][role]["materialization"]["sha256"],
            component["artifacts"][role]["materialization"]["byte_length"],
        )
        for component in (
            workflow.components_by_id[candidate["detector_component_id"]],
            workflow.components_by_id[candidate["classifier_component_id"]],
        )
        for role in ("coreml", "litert")
    }
    actual_mobile_artifacts = {
        (
            item["role"],
            item["platform"],
            item["artifact_id"],
            item["file"]["sha256"],
            item["size_bytes"],
        )
        for item in report["mobile"]["artifacts"]
    }
    _require(
        actual_mobile_artifacts == expected_mobile_artifacts,
        "evaluation mobile artifacts do not exactly match the planned model pack",
    )

    used_source_ids = set(training["training_dataset_bundle"]["source_ids"])
    used_source_ids.update(training["calibration_dataset_bundle"]["source_ids"])
    used_source_ids.update(
        ref["source_id"]
        for component in training["components"]
        for ref in component["source_refs"]
    )
    used_source_ids.update(
        reference["source_ref"]["source_id"]
        for reference in workflow.payload["external_references"]
    )
    expected_licenses = {
        (
            workflow.source_manifest.sources_by_id[source_id]["license"]["expression"],
            workflow.source_manifest.sources_by_id[source_id]["license"]["url"],
        )
        for source_id in used_source_ids
    }
    actual_licenses = {(item["spdx"], item["source"]) for item in pack["licenses"]}
    _require(
        actual_licenses == expected_licenses,
        "model pack licenses do not exactly cover the training and offline-reference lineage",
    )


def workflow_status(
    workflow: ValidatedWorkflow,
    *,
    bundle_root: Path | str = DEFAULT_BUNDLE_ROOT,
    source_root: Path | str = DEFAULT_SOURCE_ROOT,
    approved_license_gates: Sequence[str] = (),
) -> dict[str, Any]:
    """Return a deterministic, read-only readiness report for local bytes."""

    bundle = Path(bundle_root).expanduser().resolve()
    sources_root = Path(source_root).expanduser().resolve()
    blockers: list[dict[str, str]] = []
    approved_gates = list(approved_license_gates)
    _require(
        len(approved_gates) == len(set(approved_gates)),
        "approved license gate list contains duplicates",
    )
    known_license_gates = set(
        workflow.source_manifest.payload["release_policy"]["license_gates"]
    )
    unknown_gates = sorted(set(approved_gates) - known_license_gates)
    _require(
        not unknown_gates,
        f"unknown approved license gate: {', '.join(unknown_gates)}",
    )

    for requirement in workflow.payload["source_artifact_requirements"]:
        _check_source_artifact(requirement, workflow, sources_root, blockers)

    for requirement in workflow.payload["data_requirements"]:
        materialized = _check_materialized_file(
            root=bundle,
            relative_path=requirement["path"],
            state=requirement["materialization"],
            phase=requirement["phase"],
            subject=requirement["requirement_id"],
            blockers=blockers,
        )
        if materialized is not None:
            _validate_data_file(
                materialized,
                requirement,
                workflow,
                bundle_root=bundle,
                source_root=sources_root,
            )

    for component in workflow.payload["components"]:
        for role, artifact in component["artifacts"].items():
            phase = "training" if role == "checkpoint" else "export"
            _check_materialized_file(
                root=bundle,
                relative_path=artifact["path"],
                state=artifact["materialization"],
                phase=phase,
                subject=f"{component['component_id']}:{role}",
                blockers=blockers,
            )

    scorecard_results: dict[str, dict[str, Any]] = {}
    for candidate in workflow.payload["candidate_compositions"]:
        candidate_id = candidate["candidate_id"]
        documents: dict[str, dict[str, Any]] = {}
        for output_name, phase in (
            ("training_manifest", "export"),
            ("model_pack", "export"),
            ("evaluation_report", "evidence"),
        ):
            output = candidate[output_name]
            materialized = _check_materialized_file(
                root=bundle,
                relative_path=output["path"],
                state=output["materialization"],
                phase=phase,
                subject=f"{candidate_id}:{output_name}",
                blockers=blockers,
            )
            if materialized is None:
                continue
            if output_name == "training_manifest":
                documents[output_name] = _validate_training_manifest_document(
                    materialized, candidate, workflow
                )
            elif output_name == "model_pack":
                documents[output_name] = _validate_model_pack_document(
                    materialized, candidate, workflow
                )
            else:
                try:
                    _report_path, report = validate_evaluation_report(materialized)
                    _require(
                        report["candidate_id"] == candidate_id,
                        "evaluation report candidate_id does not match its lane",
                    )
                    documents[output_name] = report
                    scorecard_results[candidate_id] = evaluate_candidate(
                        workflow.registry,
                        workflow.source_manifest,
                        report,
                        approved_license_gates=approved_gates,
                    )
                except (ModelSelectionError, SourceManifestError) as error:
                    raise M0WorkflowError(str(error)) from error
        if set(documents) == {"training_manifest", "model_pack", "evaluation_report"}:
            _validate_candidate_document_bindings(candidate, documents, workflow)

    registry_gates = workflow.registry.payload["scorecard_gates"]
    corpus_pin_fields = (
        "approved_holdout_dataset_id",
        "approved_holdout_case_inventory_sha256",
        "approved_holdout_group_split_sha256",
        "approved_parity_case_inventory_sha256",
        "approved_parity_reference_outputs_sha256",
    )
    if any(registry_gates[field] is None for field in corpus_pin_fields):
        _blocker(
            blockers,
            phase="evidence",
            code="trusted_corpus_policy_pending",
            subject="model-selection-scorecard",
            path="shared/tsr/model-selection-v1.json",
            detail="Approved holdout/parity corpus pins are intentionally unconfigured.",
        )
    if registry_gates["approved_device_tier_profiles"] is None:
        _blocker(
            blockers,
            phase="evidence",
            code="device_tier_policy_pending",
            subject="model-selection-scorecard",
            path="shared/tsr/model-selection-v1.json",
            detail="Approved device tier profiles are intentionally unconfigured.",
        )
    for candidate_id in (TARGET_CANDIDATE_ID, CHALLENGER_CANDIDATE_ID):
        registered = workflow.registry.candidates_by_id[candidate_id]
        for index, reason in enumerate(registered["blocking_reasons"]):
            _blocker(
                blockers,
                phase="training" if "supplementary_plate" in reason else "evidence",
                code="registry_candidate_blocked",
                subject=candidate_id,
                path="shared/tsr/model-selection-v1.json",
                detail=f"registry blocker {index + 1}: {reason}",
            )

    used_source_ids = {
        requirement["source_ref"]["source_id"]
        for requirement in workflow.payload["source_artifact_requirements"]
    }
    required_license_gates = sorted(
        {
            workflow.source_manifest.sources_by_id[source_id]["license"]["release_gate"]
            for source_id in used_source_ids
        }
    )
    for gate_id in required_license_gates:
        if gate_id in approved_gates:
            continue
        _blocker(
            blockers,
            phase="evidence",
            code="license_review_required",
            subject=gate_id,
            path="shared/tsr/training-sources-v1.json",
            detail=(
                "An explicit engineering review assertion is missing; this workflow cannot grant legal or release approval."
            ),
        )

    blockers.sort(
        key=lambda item: (
            item["phase"],
            item["code"],
            item["subject"],
            item["path"],
            item["detail"],
        )
    )
    training_blocked = any(item["phase"] == "training" for item in blockers)
    export_blocked = training_blocked or any(
        item["phase"] == "export" for item in blockers
    )
    evidence_blocked = export_blocked or any(
        item["phase"] == "evidence" for item in blockers
    )
    model_scorecard_eligible = len(scorecard_results) == 2 and all(
        result["model_scorecard_eligible"] for result in scorecard_results.values()
    )
    workflow_complete = not evidence_blocked and model_scorecard_eligible
    return {
        "workflow_id": workflow.payload["workflow_id"],
        "plan_sha256": workflow.plan_sha256,
        "mode": workflow.payload["mode"],
        "valid": True,
        "training_inputs_ready": not training_blocked,
        "exports_complete": not export_blocked,
        "scorecard_evidence_complete": not evidence_blocked,
        "model_scorecard_eligible": model_scorecard_eligible,
        "workflow_complete": workflow_complete,
        "decision": "complete" if workflow_complete else "blocked",
        "selected_candidate_id": workflow.registry.payload["selected_candidate_id"],
        "scorecard_results": {
            candidate_id: scorecard_results[candidate_id]
            for candidate_id in sorted(scorecard_results)
        },
        "blocker_count": len(blockers),
        "blockers": blockers,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", default=str(DEFAULT_PLAN), help="M0 workflow plan")
    parser.add_argument(
        "--repository-root",
        default=str(REPOSITORY_ROOT),
        help="repository root containing pinned contracts",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("validate", help="validate the static offline workflow plan")
    status_parser = subparsers.add_parser(
        "status", help="hash local bytes and report all blockers without writing"
    )
    status_parser.add_argument("--bundle-root", default=str(DEFAULT_BUNDLE_ROOT))
    status_parser.add_argument("--source-root", default=str(DEFAULT_SOURCE_ROOT))
    status_parser.add_argument(
        "--approve-license-gate",
        action="append",
        default=[],
        dest="approved_license_gates",
        help=(
            "record an explicit engineering review assertion for a source gate; "
            "repeat per gate (does not grant legal or release approval)"
        ),
    )
    args = parser.parse_args(argv)
    try:
        workflow = validate_workflow_plan(
            args.plan,
            repository_root=args.repository_root,
        )
        if args.command == "validate":
            print(
                json.dumps(
                    {
                        "valid": True,
                        "workflow_id": workflow.payload["workflow_id"],
                        "mode": workflow.payload["mode"],
                        "plan_sha256": workflow.plan_sha256,
                        "selected_candidate_id": workflow.registry.payload[
                            "selected_candidate_id"
                        ],
                    },
                    indent=2,
                    sort_keys=True,
                )
            )
            return 0
        result = workflow_status(
            workflow,
            bundle_root=args.bundle_root,
            source_root=args.source_root,
            approved_license_gates=args.approved_license_gates,
        )
        print(json.dumps(result, indent=2, sort_keys=True))
        return 0 if result["workflow_complete"] else 1
    except (M0WorkflowError, SourceManifestError, ModelSelectionError) as error:
        parser.exit(2, f"error: {error}\n")


if __name__ == "__main__":
    raise SystemExit(main())
