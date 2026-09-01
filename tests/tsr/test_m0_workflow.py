import ast
import copy
import hashlib
import json
from pathlib import Path

import jsonschema
import pytest

import scripts.tsr.m0_workflow as m0_workflow
from scripts.tsr.m0_workflow import (
    CHALLENGER_CANDIDATE_ID,
    DEFAULT_PLAN,
    DEFAULT_PLAN_SCHEMA,
    DETECTOR_COMPONENT_ID,
    LARGE_COMPONENT_ID,
    M0WorkflowError,
    SMALL_COMPONENT_ID,
    TARGET_CANDIDATE_ID,
    main,
    validate_workflow_plan,
    workflow_status,
)


ROOT = Path(__file__).resolve().parents[2]


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_plan(tmp_path: Path, payload) -> Path:
    path = tmp_path / "m0-workflow.json"
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def schema_validator():
    schema = load_json(DEFAULT_PLAN_SCHEMA)
    jsonschema.Draft202012Validator.check_schema(schema)
    return jsonschema.Draft202012Validator(schema)


def find_by_id(values, key, value):
    return next(item for item in values if item[key] == value)


def test_checked_in_plan_passes_schema_and_manual_contract_validation() -> None:
    plan = load_json(DEFAULT_PLAN)
    schema_validator().validate(plan)

    workflow = validate_workflow_plan(DEFAULT_PLAN)

    assert workflow.payload == plan
    assert workflow.payload["mode"] == "offline_readiness_only"
    assert workflow.registry.payload["selected_candidate_id"] is None
    assert set(workflow.components_by_id) == {
        DETECTOR_COMPONENT_ID,
        LARGE_COMPONENT_ID,
        SMALL_COMPONENT_ID,
    }
    assert set(workflow.candidates_by_id) == {
        TARGET_CANDIDATE_ID,
        CHALLENGER_CANDIDATE_ID,
    }


def test_runtime_validator_also_executes_the_json_schema(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    original = m0_workflow._schema_validate

    def recording_validator(instance, schema, label):
        calls.append(label)
        return original(instance, schema, label)

    monkeypatch.setattr(m0_workflow, "_schema_validate", recording_validator)
    validate_workflow_plan(DEFAULT_PLAN)

    assert calls == ["M0 workflow plan"]


def test_default_status_is_deterministic_read_only_and_fail_closed(
    tmp_path: Path,
) -> None:
    workflow = validate_workflow_plan(DEFAULT_PLAN)
    bundle_root = tmp_path / "bundle-does-not-exist"
    source_root = tmp_path / "sources-do-not-exist"

    first = workflow_status(
        workflow,
        bundle_root=bundle_root,
        source_root=source_root,
    )
    second = workflow_status(
        workflow,
        bundle_root=bundle_root,
        source_root=source_root,
    )

    assert first == second
    assert not bundle_root.exists()
    assert not source_root.exists()
    assert first["decision"] == "blocked"
    assert first["training_inputs_ready"] is False
    assert first["exports_complete"] is False
    assert first["scorecard_evidence_complete"] is False
    assert first["model_scorecard_eligible"] is False
    assert first["workflow_complete"] is False
    assert first["selected_candidate_id"] is None
    codes = {item["code"] for item in first["blockers"]}
    assert {
        "missing_source_artifact",
        "pending_materialization",
        "registry_candidate_blocked",
        "trusted_corpus_policy_pending",
        "device_tier_policy_pending",
        "license_review_required",
    }.issubset(codes)
    assert any(
        item["subject"] == "reviewed-full-scene-annotations"
        and "supplementary-plate" in item["detail"]
        for item in first["blockers"]
    )


def test_candidate_and_challenger_share_detector_and_only_change_classifier() -> None:
    workflow = validate_workflow_plan(DEFAULT_PLAN)
    target = workflow.candidates_by_id[TARGET_CANDIDATE_ID]
    challenger = workflow.candidates_by_id[CHALLENGER_CANDIDATE_ID]

    assert target["detector_component_id"] == DETECTOR_COMPONENT_ID
    assert challenger["detector_component_id"] == DETECTOR_COMPONENT_ID
    assert target["classifier_component_id"] == LARGE_COMPONENT_ID
    assert challenger["classifier_component_id"] == SMALL_COMPONENT_ID
    assert (
        workflow.components_by_id[DETECTOR_COMPONENT_ID]["architecture"] == "YOLOX-Nano"
    )
    assert (
        workflow.components_by_id[LARGE_COMPONENT_ID]["architecture"]
        == "MobileNetV3-Large"
    )
    assert (
        workflow.components_by_id[SMALL_COMPONENT_ID]["architecture"]
        == "MobileNetV3-Small"
    )


def test_external_models_are_offline_only_and_never_mobile_components() -> None:
    workflow = validate_workflow_plan(DEFAULT_PLAN)
    references = {
        item["reference_id"]: item for item in workflow.payload["external_references"]
    }

    assert references["gtsign-220-vit"]["role"] == "offline_teacher"
    assert (
        references["panoramax-classify-de-road-signs"]["role"]
        == "offline_crop_benchmark"
    )
    assert all(item["runtime_included"] is False for item in references.values())
    assert all(
        item["acceptance_gate_eligible"] is False for item in references.values()
    )
    component_artifact_ids = {
        component["initialization"]["artifact_id"]
        for component in workflow.payload["components"]
    }
    assert "gtsign-220-vit-all-classes" not in component_artifact_ids
    assert "panoramax-de-yolo26-classifier-5360aa6" not in component_artifact_ids


def test_schema_version_boolean_is_rejected_by_both_validators(tmp_path: Path) -> None:
    plan = load_json(DEFAULT_PLAN)
    plan["schema_version"] = True

    with pytest.raises(jsonschema.ValidationError):
        schema_validator().validate(plan)
    with pytest.raises(M0WorkflowError, match="integer 1"):
        validate_workflow_plan(write_plan(tmp_path, plan))


def test_online_or_executing_control_plane_is_rejected_by_both_validators(
    tmp_path: Path,
) -> None:
    plan = load_json(DEFAULT_PLAN)
    plan["safety_policy"]["network_allowed"] = True

    with pytest.raises(jsonschema.ValidationError):
        schema_validator().validate(plan)
    with pytest.raises(M0WorkflowError, match="safety flag"):
        validate_workflow_plan(write_plan(tmp_path, plan))


def test_runtime_inclusion_of_teacher_is_rejected_by_both_validators(
    tmp_path: Path,
) -> None:
    plan = load_json(DEFAULT_PLAN)
    teacher = find_by_id(plan["external_references"], "reference_id", "gtsign-220-vit")
    teacher["runtime_included"] = True

    with pytest.raises(jsonschema.ValidationError):
        schema_validator().validate(plan)
    with pytest.raises(M0WorkflowError, match="offline and scorecard-ineligible"):
        validate_workflow_plan(write_plan(tmp_path, plan))


def test_controlled_challenger_cannot_substitute_target_classifier(
    tmp_path: Path,
) -> None:
    plan = load_json(DEFAULT_PLAN)
    challenger = find_by_id(
        plan["candidate_compositions"], "candidate_id", CHALLENGER_CANDIDATE_ID
    )
    challenger["classifier_component_id"] = LARGE_COMPONENT_ID

    schema_validator().validate(plan)
    with pytest.raises(M0WorkflowError, match="composition changed"):
        validate_workflow_plan(write_plan(tmp_path, plan))


def test_published_panoramax_validation_cannot_replace_training_archive(
    tmp_path: Path,
) -> None:
    plan = load_json(DEFAULT_PLAN)
    requirement = find_by_id(
        plan["source_artifact_requirements"],
        "requirement_id",
        "panoramax-training-crops",
    )
    requirement["source_ref"]["artifact_id"] = "panoramax-de-validation-b485694"

    schema_validator().validate(plan)
    with pytest.raises(M0WorkflowError, match="source requirement .* changed"):
        validate_workflow_plan(write_plan(tmp_path, plan))


def test_pending_materialization_cannot_claim_hash_or_size(tmp_path: Path) -> None:
    plan = load_json(DEFAULT_PLAN)
    materialization = plan["components"][0]["artifacts"]["checkpoint"][
        "materialization"
    ]
    materialization["sha256"] = "1" * 64
    materialization["byte_length"] = 1

    with pytest.raises(jsonschema.ValidationError):
        schema_validator().validate(plan)
    with pytest.raises(M0WorkflowError, match="must be null while pending"):
        validate_workflow_plan(write_plan(tmp_path, plan))


def test_component_artifact_paths_are_globally_disjoint(tmp_path: Path) -> None:
    plan = load_json(DEFAULT_PLAN)
    detector = find_by_id(plan["components"], "component_id", DETECTOR_COMPONENT_ID)
    small = find_by_id(plan["components"], "component_id", SMALL_COMPONENT_ID)
    small["artifacts"]["onnx"]["path"] = detector["artifacts"]["onnx"]["path"]

    schema_validator().validate(plan)
    with pytest.raises(M0WorkflowError, match="bundle path .* aliases"):
        validate_workflow_plan(write_plan(tmp_path, plan))


def test_component_artifact_hashes_are_globally_disjoint(tmp_path: Path) -> None:
    plan = load_json(DEFAULT_PLAN)
    detector = find_by_id(plan["components"], "component_id", DETECTOR_COMPONENT_ID)
    repeated_hash = "1" * 64
    for role in ("checkpoint", "onnx"):
        detector["artifacts"][role]["materialization"] = {
            "state": "available",
            "sha256": repeated_hash,
            "byte_length": 10,
            "blocking_reason": None,
        }

    schema_validator().validate(plan)
    with pytest.raises(M0WorkflowError, match="globally distinct SHA-256"):
        validate_workflow_plan(write_plan(tmp_path, plan))


def test_artifact_role_format_and_safe_suffix_are_bound(tmp_path: Path) -> None:
    plan = load_json(DEFAULT_PLAN)
    detector = find_by_id(plan["components"], "component_id", DETECTOR_COMPONENT_ID)
    detector["artifacts"]["coreml"]["path"] = "runs/detector/model.bin"

    schema_validator().validate(plan)
    with pytest.raises(M0WorkflowError, match=r"must end in \.mlpackage\.zip"):
        validate_workflow_plan(write_plan(tmp_path, plan))


def test_mobile_exports_must_derive_from_the_reference_onnx(tmp_path: Path) -> None:
    plan = load_json(DEFAULT_PLAN)
    detector = find_by_id(plan["components"], "component_id", DETECTOR_COMPONENT_ID)
    detector["artifacts"]["litert"]["derived_from_artifact_id"] = detector["artifacts"][
        "checkpoint"
    ]["artifact_id"]

    schema_validator().validate(plan)
    with pytest.raises(
        M0WorkflowError, match="litert must derive from its reference ONNX"
    ):
        validate_workflow_plan(write_plan(tmp_path, plan))


def test_pinned_contract_byte_drift_is_rejected(tmp_path: Path) -> None:
    plan = load_json(DEFAULT_PLAN)
    taxonomy = find_by_id(plan["contracts"], "document_id", "taxonomy-v2")
    taxonomy["sha256"] = "1" * 64

    schema_validator().validate(plan)
    with pytest.raises(M0WorkflowError, match="sha256 does not match"):
        validate_workflow_plan(write_plan(tmp_path, plan))


def test_source_manifest_pin_is_the_reviewed_immutable_identity() -> None:
    plan = load_json(DEFAULT_PLAN)
    assert (
        plan["source_manifest"]["sha256"]
        == "4985ebb8a146918c113700d312e6becb893acfed1d07f2bfa16263fadf0c1cbc"
    )
    assert (
        hashlib.sha256(
            (ROOT / plan["source_manifest"]["path"]).read_bytes()
        ).hexdigest()
        == plan["source_manifest"]["sha256"]
    )


def test_unattested_bytes_do_not_satisfy_a_pending_requirement(tmp_path: Path) -> None:
    workflow = validate_workflow_plan(DEFAULT_PLAN)
    relative = Path("inputs/reviewed-full-scene-annotations-v2.json")
    bundle_root = tmp_path / "bundle"
    target = bundle_root / relative
    target.parent.mkdir(parents=True)
    target.write_text("{}\n", encoding="utf-8")

    result = workflow_status(
        workflow,
        bundle_root=bundle_root,
        source_root=tmp_path / "source-root",
    )

    blocker = next(
        item
        for item in result["blockers"]
        if item["subject"] == "reviewed-full-scene-annotations"
    )
    assert blocker["code"] == "unattested_file_present"
    assert result["training_inputs_ready"] is False


def test_attested_offline_environment_is_checked_without_execution(
    tmp_path: Path,
) -> None:
    plan = copy.deepcopy(load_json(DEFAULT_PLAN))
    requirement = find_by_id(
        plan["data_requirements"], "requirement_id", "training-environment-lock"
    )
    payload = {
        "schema_version": 1,
        "lock_id": "offline-training-lock-v1",
        "frozen": True,
        "source_ids": [],
        "network_allowed": False,
        "paid_compute_allowed": False,
        "container_image_digest": "sha256:" + "2" * 64,
        "dependencies_lock_sha256": "3" * 64,
    }
    raw = (json.dumps(payload, sort_keys=True) + "\n").encode()
    requirement["materialization"] = {
        "state": "available",
        "sha256": hashlib.sha256(raw).hexdigest(),
        "byte_length": len(raw),
        "blocking_reason": None,
    }
    plan_path = write_plan(tmp_path, plan)
    bundle_root = tmp_path / "bundle"
    output = bundle_root / requirement["path"]
    output.parent.mkdir(parents=True)
    output.write_bytes(raw)

    workflow = validate_workflow_plan(plan_path)
    result = workflow_status(
        workflow,
        bundle_root=bundle_root,
        source_root=tmp_path / "source-root",
    )

    assert not any(
        item["subject"] == "training-environment-lock" for item in result["blockers"]
    )
    assert result["decision"] == "blocked"


@pytest.mark.parametrize("content_state", ["missing", "wrong_hash"])
def test_dataset_inventory_rehashes_every_listed_source_byte(
    tmp_path: Path, content_state: str
) -> None:
    plan = copy.deepcopy(load_json(DEFAULT_PLAN))
    requirement = find_by_id(
        plan["data_requirements"], "requirement_id", "zod-byte-inventory"
    )
    expected_bytes = b"reviewed zod frame bytes\n"
    inventory = {
        "schema_version": 1,
        "inventory_id": "zod-byte-inventory-test",
        "frozen": True,
        "source_ids": ["zod-frames-2.0.0"],
        "files": [
            {
                "path": "datasets/zod/reviewed-frame.jpg",
                "byte_length": len(expected_bytes),
                "sha256": hashlib.sha256(expected_bytes).hexdigest(),
            }
        ],
    }
    inventory_bytes = (json.dumps(inventory, sort_keys=True) + "\n").encode()
    requirement["materialization"] = {
        "state": "available",
        "sha256": hashlib.sha256(inventory_bytes).hexdigest(),
        "byte_length": len(inventory_bytes),
        "blocking_reason": None,
    }
    plan_path = write_plan(tmp_path, plan)
    bundle_root = tmp_path / "bundle"
    inventory_path = bundle_root / requirement["path"]
    inventory_path.parent.mkdir(parents=True)
    inventory_path.write_bytes(inventory_bytes)
    source_root = tmp_path / "source-root"
    if content_state == "wrong_hash":
        content_path = source_root / inventory["files"][0]["path"]
        content_path.parent.mkdir(parents=True)
        content_path.write_bytes(b"x" * len(expected_bytes))

    workflow = validate_workflow_plan(plan_path)
    expected_error = (
        "missing inventoried byte" if content_state == "missing" else "SHA-256 mismatch"
    )
    with pytest.raises(M0WorkflowError, match=expected_error):
        workflow_status(
            workflow,
            bundle_root=bundle_root,
            source_root=source_root,
        )


def test_model_pack_must_implement_the_complete_frozen_taxonomy(
    tmp_path: Path,
) -> None:
    workflow = validate_workflow_plan(DEFAULT_PLAN)
    candidate = workflow.candidates_by_id[TARGET_CANDIDATE_ID]
    pack = load_json(ROOT / "shared/tsr/fixtures/de-yolox-mnv3-shadow-pack-v2.json")
    pack["pack_id"] = candidate["expected_pack_id"]
    path = tmp_path / "pack.json"
    path.write_text(json.dumps(pack), encoding="utf-8")

    with pytest.raises(M0WorkflowError, match="class mapping"):
        m0_workflow._validate_model_pack_document(path, candidate, workflow)


def test_model_pack_artifact_path_and_derivation_are_bound(tmp_path: Path) -> None:
    workflow = validate_workflow_plan(DEFAULT_PLAN)
    candidate = workflow.candidates_by_id[TARGET_CANDIDATE_ID]
    pack = load_json(ROOT / "shared/tsr/fixtures/de-yolox-mnv3-shadow-pack-v2.json")
    pack["pack_id"] = candidate["expected_pack_id"]
    pack["class_mapping"] = m0_workflow._expected_class_mapping(workflow)
    for stage_name, component_id in (
        ("detector", DETECTOR_COMPONENT_ID),
        ("classifier", LARGE_COMPONENT_ID),
    ):
        component = workflow.components_by_id[component_id]
        stage = pack["stages"][stage_name]
        stage["component_id"] = component_id
        stage["architecture"] = component["architecture"]
        stage["calibration"]["passed"] = True
        stage["calibration"]["runtime_output"] = "calibrated_confidence"
        for role, planned in component["artifacts"].items():
            digest = hashlib.sha256(planned["artifact_id"].encode()).hexdigest()
            planned["materialization"] = {
                "state": "available",
                "sha256": digest,
                "byte_length": 10,
                "blocking_reason": None,
            }
            artifact = stage["artifacts"][role]
            artifact.update(
                {
                    "artifact_id": planned["artifact_id"],
                    "artifact_family_id": planned["artifact_family_id"],
                    "path": planned["path"],
                    "sha256": digest,
                    "byte_length": 10,
                    "derived_from_artifact_id": planned["derived_from_artifact_id"],
                }
            )
            if role != "checkpoint":
                artifact["parity"]["reference_artifact_id"] = planned[
                    "derived_from_artifact_id"
                ]
                artifact["parity"]["passed"] = True
    pack["stages"]["detector"]["artifacts"]["coreml"]["path"] = (
        "runs/unrelated/model.mlpackage.zip"
    )
    path = tmp_path / "pack.json"
    path.write_text(json.dumps(pack), encoding="utf-8")

    with pytest.raises(M0WorkflowError, match="role/path/derivation"):
        m0_workflow._validate_model_pack_document(path, candidate, workflow)


def test_cross_document_binding_rejects_a_different_embedded_training_run() -> None:
    workflow = validate_workflow_plan(DEFAULT_PLAN)
    candidate = copy.deepcopy(workflow.candidates_by_id[TARGET_CANDIDATE_ID])
    candidate["training_manifest"]["materialization"] = {
        "state": "available",
        "sha256": "1" * 64,
        "byte_length": 1,
        "blocking_reason": None,
    }
    candidate["model_pack"]["materialization"] = {
        "state": "available",
        "sha256": "2" * 64,
        "byte_length": 1,
        "blocking_reason": None,
    }
    candidate["evaluation_report"]["materialization"] = {
        "state": "available",
        "sha256": "3" * 64,
        "byte_length": 1,
        "blocking_reason": None,
    }
    documents = {
        "training_manifest": {"training_run_id": "run-a"},
        "model_pack": {},
        "evaluation_report": {
            "lineage": {
                "training_run": {
                    "manifest": {"training_run_id": "run-b"},
                    "manifest_file": {"sha256": "1" * 64},
                }
            }
        },
    }

    with pytest.raises(M0WorkflowError, match="planned training manifest bytes"):
        m0_workflow._validate_candidate_document_bindings(
            candidate, documents, workflow
        )


def test_license_review_assertions_are_explicit_and_unknown_ids_fail(
    tmp_path: Path,
) -> None:
    workflow = validate_workflow_plan(DEFAULT_PLAN)
    with pytest.raises(M0WorkflowError, match="unknown approved license gate"):
        workflow_status(
            workflow,
            bundle_root=tmp_path / "bundle",
            source_root=tmp_path / "sources",
            approved_license_gates=["invented-approval"],
        )

    known = sorted(
        {
            workflow.source_manifest.sources_by_id[
                requirement["source_ref"]["source_id"]
            ]["license"]["release_gate"]
            for requirement in workflow.payload["source_artifact_requirements"]
        }
    )
    result = workflow_status(
        workflow,
        bundle_root=tmp_path / "bundle",
        source_root=tmp_path / "sources",
        approved_license_gates=known,
    )
    assert not any(
        blocker["code"] == "license_review_required" for blocker in result["blockers"]
    )
    assert result["model_scorecard_eligible"] is False


def test_symlinked_bundle_evidence_is_rejected(tmp_path: Path) -> None:
    workflow = validate_workflow_plan(DEFAULT_PLAN)
    bundle_root = tmp_path / "bundle"
    outside = tmp_path / "outside.json"
    outside.write_text("{}\n", encoding="utf-8")
    path = bundle_root / "inputs/reviewed-full-scene-annotations-v2.json"
    path.parent.mkdir(parents=True)
    path.symlink_to(outside)

    with pytest.raises(M0WorkflowError, match="must not traverse symlinks"):
        workflow_status(
            workflow,
            bundle_root=bundle_root,
            source_root=tmp_path / "source-root",
        )


def test_cli_validate_succeeds_and_status_returns_blocked(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    assert main(["validate"]) == 0
    validated = json.loads(capsys.readouterr().out)
    assert validated["valid"] is True
    assert validated["selected_candidate_id"] is None

    assert (
        main(
            [
                "status",
                "--bundle-root",
                str(tmp_path / "bundle"),
                "--source-root",
                str(tmp_path / "sources"),
            ]
        )
        == 1
    )
    status = json.loads(capsys.readouterr().out)
    assert status["decision"] == "blocked"
    assert status["model_scorecard_eligible"] is False


def test_control_plane_has_no_network_or_model_framework_imports() -> None:
    source_path = ROOT / "scripts/tsr/m0_workflow.py"
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    imported_roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported_roots.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported_roots.add(node.module.split(".", 1)[0])

    assert imported_roots.isdisjoint(
        {
            "urllib",
            "requests",
            "httpx",
            "socket",
            "torch",
            "tensorflow",
            "tflite_runtime",
            "coremltools",
            "onnx",
            "onnxruntime",
            "transformers",
            "huggingface_hub",
        }
    )
    assert "subprocess" not in imported_roots
    assert "os" not in imported_roots


def test_no_checked_in_artifact_or_evidence_uses_placeholder_bytes() -> None:
    plan = load_json(DEFAULT_PLAN)
    states = []
    for requirement in plan["data_requirements"]:
        states.append(requirement["materialization"])
    for component in plan["components"]:
        states.extend(
            item["materialization"] for item in component["artifacts"].values()
        )
    for candidate in plan["candidate_compositions"]:
        states.extend(
            candidate[name]["materialization"]
            for name in ("training_manifest", "model_pack", "evaluation_report")
        )

    assert states
    assert all(state["state"] == "pending" for state in states)
    assert all(state["sha256"] is None for state in states)
    assert all(state["byte_length"] is None for state in states)
