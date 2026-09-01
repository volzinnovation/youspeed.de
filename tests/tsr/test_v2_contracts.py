import copy
import hashlib
import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path

import jsonschema
import pytest


ROOT = Path(__file__).resolve().parents[2]
TSR_ROOT = ROOT / "shared" / "tsr"
FIXTURES = TSR_ROOT / "fixtures"


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def validate(schema_name: str, instance):
    schema = load_json(TSR_ROOT / schema_name)
    jsonschema.Draft202012Validator.check_schema(schema)
    jsonschema.Draft202012Validator(
        schema,
        format_checker=jsonschema.Draft202012Validator.FORMAT_CHECKER,
    ).validate(instance)


def normalized_box(observation, box):
    asset = observation["hd_asset"]
    return {
        "x": box["x"] / asset["width"],
        "y": box["y"] / asset["height"],
        "width": box["width"] / asset["width"],
        "height": box["height"] / asset["height"],
    }


def shadow_event(fixture, observation):
    pack = load_json(FIXTURES / "de-yolox-mnv3-shadow-pack-v2.json")
    review = observation["review"]
    expected = review["expected_shadow"]
    readable = review["supplementary_plate"]["readability"] == "readable"
    primary = review["primary"]
    plate = review["supplementary_plate"]

    detector = pack["stages"]["detector"]
    classifier = pack["stages"]["classifier"]
    detector_artifact = detector["artifacts"]["coreml"]
    classifier_artifact = classifier["artifacts"]["coreml"]

    return {
        "schema_version": 2,
        "event_id": f"contract-event-{observation['observation_id']}",
        "pack_id": pack["pack_id"],
        "taxonomy_version": "tsr-semantic-v2",
        "evidence_origin": "runtime_inference",
        "execution_mode": "shadow",
        "override_eligible": False,
        "override_disposition": "shadow_evidence_only",
        "qa_disposition": "emit",
        "source": "panoramax_replay",
        "frame": {
            "frame_id": observation["picture_id"],
            "timestamp_utc": observation["timestamp_utc"],
            "width": observation["hd_asset"]["width"],
            "height": observation["hd_asset"]["height"],
        },
        "stage_runs": {
            "detector": {
                "component_id": detector["component_id"],
                "artifact_id": detector_artifact["artifact_id"],
                "artifact_sha256": detector_artifact["sha256"],
                "artifact_format": detector_artifact["format"],
                "preprocessing_version": detector["preprocessing"]["version"],
                "calibration_id": detector["calibration"]["calibration_id"],
                "invoked": True,
                "latency_ms": 1.0,
            },
            "classifier": {
                "component_id": classifier["component_id"],
                "artifact_id": classifier_artifact["artifact_id"],
                "artifact_sha256": classifier_artifact["sha256"],
                "artifact_format": classifier_artifact["format"],
                "preprocessing_version": classifier["preprocessing"]["version"],
                "calibration_id": classifier["calibration"]["calibration_id"],
                "invoked": True,
                "latency_ms": 1.0,
            },
        },
        "state": expected["recognition_state"],
        "assemblies": [
            {
                "assembly_id": f"assembly-{observation['observation_id']}",
                "physical_sign_track_id": fixture["physical_sign_id"],
                "primary": {
                    "object_id": f"primary-{observation['observation_id']}",
                    "bounding_box": normalized_box(
                        observation, primary["bounding_box"]
                    ),
                    "detector_score": {
                        "raw_score": 0.9,
                        "calibrated_confidence": None,
                    },
                    "classifier_score": {
                        "raw_score": 0.9,
                        "calibrated_confidence": None,
                    },
                    "class_id": "speed_limit_70",
                    "semantic": {
                        "kind": "maximum_speed",
                        "value": 70,
                        "unit": "km/h",
                    },
                },
                "supplementary_plates": [
                    {
                        "object_id": f"plate-{observation['observation_id']}",
                        "bounding_box": normalized_box(
                            observation, plate["bounding_box"]
                        ),
                        "detector_score": {
                            "raw_score": 0.8,
                            "calibrated_confidence": None,
                        },
                        "classifier_score": (
                            {
                                "raw_score": 0.2 if not readable else 0.9,
                                "calibrated_confidence": None,
                            }
                        ),
                        "class_id": "supplementary_extent" if readable else None,
                        "readability": plate["readability"],
                        "restriction": plate["restriction"],
                    }
                ],
                "condition_state": expected["condition_state"],
                "temporal_evidence": {
                    "evidence_frame_count": 2 if readable else 1,
                    "prior_event_id": (
                        "contract-event-hard-preceding-frame" if readable else None
                    ),
                    "restriction_transition": (
                        "upgraded_from_later_readable_evidence"
                        if readable
                        else "none"
                    ),
                },
            }
        ],
        "road_context": expected["road_context"],
        "diagnostic_capture": {
            "status": "requested",
            "reasons": [expected["diagnostic_capture_reason"]],
            "capture_id": None,
        },
        "thermal_state": "nominal",
    }


def full_scene_manifest(fixture):
    frames = []
    for observation in fixture["observations"]:
        review = observation["review"]
        primary_id = f"primary-{observation['observation_id']}"
        plate_id = f"plate-{observation['observation_id']}"
        assembly_id = f"assembly-{observation['observation_id']}"
        plate = review["supplementary_plate"]
        frames.append(
            {
                "frame_id": observation["picture_id"],
                "drive_id": fixture["drive_id"],
                "source": {
                    "source_id": "panoramax-m0-public-fixture",
                    "kind": "panoramax_public_fixture",
                    "source_asset_id": observation["picture_id"],
                    "sequence_id": fixture["sequence"]["sequence_id"],
                    "source_page_uri": observation["source_page_uri"],
                    "source_asset_uri": observation["hd_asset"]["uri"],
                    "source_split_id": None,
                    "published_split_reuse": False,
                    "license": {
                        "spdx": fixture["sequence"]["license"]["spdx"],
                        "status": "verified",
                        "evidence_uri": observation["metadata_uri"],
                    },
                },
                "image": {
                    "sha256": observation["hd_asset"]["sha256"],
                    "width": observation["hd_asset"]["width"],
                    "height": observation["hd_asset"]["height"],
                },
                "review": {
                    "status": "accepted",
                    "method": "human",
                    "geometry_quality": review["geometry_quality"],
                    "reviewed_at": "2026-09-01T20:41:05Z",
                    "revision": "panoramax-m0-review-v2",
                },
                "objects": [
                    {
                        "object_id": primary_id,
                        "physical_sign_id": fixture["physical_sign_id"],
                        "assembly_id": assembly_id,
                        "role": "primary_sign",
                        "bounding_box": review["primary"]["bounding_box"],
                        "visibility": {
                            "occluded": False,
                            "truncated": False,
                            "difficult": observation["observation_id"]
                            == "hard-preceding-frame",
                        },
                        "readability": "readable",
                        "semantic": review["primary"]["semantic"],
                        "restriction_evidence": None,
                    },
                    {
                        "object_id": plate_id,
                        "physical_sign_id": fixture["physical_sign_id"],
                        "assembly_id": assembly_id,
                        "role": "supplementary_plate",
                        "bounding_box": plate["bounding_box"],
                        "visibility": {
                            "occluded": False,
                            "truncated": False,
                            "difficult": observation["observation_id"]
                            == "hard-preceding-frame",
                        },
                        "readability": plate["readability"],
                        "semantic": None,
                        "restriction_evidence": {
                            "state": plate["readability"],
                            "restriction": plate["restriction"],
                        },
                    },
                ],
                "assemblies": [
                    {
                        "assembly_id": assembly_id,
                        "physical_sign_id": fixture["physical_sign_id"],
                        "primary_object_id": primary_id,
                        "supplementary_object_ids": [plate_id],
                    }
                ],
            }
        )
    return {
        "schema_version": 2,
        "manifest_id": "panoramax-m0-full-scene-fixture-v2",
        "taxonomy_version": "tsr-semantic-v2",
        "frozen": True,
        "coordinate_system": "pixel_xywh_top_left_after_orientation_normalization",
        "frames": frames,
    }


def assert_group_invariants(manifest):
    weights = manifest["strategy"]["partitions"].values()
    assert sum(weights) == pytest.approx(1.0)

    component_by_id = {}
    component_sample_ids = set()
    for component in manifest["components"]:
        assert component["component_id"] not in component_by_id
        assert not component_sample_ids.intersection(component["sample_ids"])
        component_sample_ids.update(component["sample_ids"])
        component_by_id[component["component_id"]] = component
    manifest_digest = hashlib.sha256(
        "\0".join(
            component["assignment_digest"] for component in manifest["components"]
        ).encode("utf-8")
    ).hexdigest()
    assert manifest["manifest_id"] == (
        f"youspeed-tsr-group-split-v2-{manifest_digest[:16]}"
    )

    sample_ids = set()
    partitions_by_drive = defaultdict(set)
    partitions_by_sign = defaultdict(set)
    partitions_by_near_duplicate = defaultdict(set)
    prohibited = set()
    for source in manifest["prohibited_source_splits"]:
        prohibited.add(source["source_split_id"])
        prohibited.update(source["aliases"])

    for sample in manifest["samples"]:
        assert sample["sample_id"] not in sample_ids
        sample_ids.add(sample["sample_id"])
        component = component_by_id[sample["component_id"]]
        assert sample["partition"] == component["partition"]
        assert sample["sample_id"] in component["sample_ids"]
        assert sample["drive_id"] in component["drive_ids"]
        assert set(sample["physical_sign_ids"]).issubset(
            component["physical_sign_ids"]
        )
        assert set(sample["near_duplicate_cluster_ids"]).issubset(
            component["near_duplicate_cluster_ids"]
        )
        assert sample["source_split_id"] not in prohibited
        partitions_by_drive[sample["drive_id"]].add(sample["partition"])
        for physical_sign_id in sample["physical_sign_ids"]:
            partitions_by_sign[physical_sign_id].add(sample["partition"])
        for cluster_id in sample["near_duplicate_cluster_ids"]:
            partitions_by_near_duplicate[cluster_id].add(sample["partition"])

    for partition_sets in (
        partitions_by_drive,
        partitions_by_sign,
        partitions_by_near_duplicate,
    ):
        assert all(len(partitions) == 1 for partitions in partition_sets.values())
    assert component_sample_ids == sample_ids


def test_v2_schemas_are_well_formed():
    for schema_name in (
        "model-pack-v2.schema.json",
        "recognition-event-v2.schema.json",
        "full-scene-annotation-v2.schema.json",
        "group-split-v2.schema.json",
    ):
        jsonschema.Draft202012Validator.check_schema(load_json(TSR_ROOT / schema_name))


def test_two_stage_pack_has_independent_preprocessing_calibration_and_siblings():
    pack = load_json(FIXTURES / "de-yolox-mnv3-shadow-pack-v2.json")
    validate("model-pack-v2.schema.json", pack)

    detector = pack["stages"]["detector"]
    classifier = pack["stages"]["classifier"]
    assert detector["architecture"] == "YOLOX-Nano"
    assert classifier["architecture"] == "MobileNetV3-Large"
    assert detector["preprocessing"]["source"] == "full_frame"
    assert classifier["preprocessing"]["source"] == "proposal_crop"
    assert (
        detector["preprocessing"]["version"]
        != classifier["preprocessing"]["version"]
    )
    assert (
        detector["calibration"]["calibration_id"]
        != classifier["calibration"]["calibration_id"]
    )
    assert classifier["preprocessing"]["crop_policy"]["include_linked_objects"] is False
    assert classifier["preprocessing"]["crop_policy"]["role_hint_required"] is True

    artifact_ids = set()
    artifact_paths = set()
    artifact_hashes = set()
    for stage in (detector, classifier):
        assert set(stage["artifacts"]) == {"checkpoint", "onnx", "coreml", "litert"}
        family_ids = {
            artifact["artifact_family_id"] for artifact in stage["artifacts"].values()
        }
        assert len(family_ids) == 1
        for role, artifact in stage["artifacts"].items():
            assert artifact["role"] == role
            assert artifact["format"] == role
            assert artifact["artifact_id"] not in artifact_ids
            assert artifact["path"] not in artifact_paths
            assert artifact["sha256"] not in artifact_hashes
            artifact_ids.add(artifact["artifact_id"])
            artifact_paths.add(artifact["path"])
            artifact_hashes.add(artifact["sha256"])

    assert pack["execution_policy"]["override_eligible"] is False
    assert set(pack["execution_policy"]["required_gates"]) == {
        "holdout",
        "parity",
        "device",
        "temporal",
        "license",
    }


def test_model_pack_v2_rejects_runtime_override_and_linked_object_crops():
    pack = load_json(FIXTURES / "de-yolox-mnv3-shadow-pack-v2.json")
    pack["execution_policy"]["override_eligible"] = True
    with pytest.raises(jsonschema.ValidationError):
        validate("model-pack-v2.schema.json", pack)

    pack = load_json(FIXTURES / "de-yolox-mnv3-shadow-pack-v2.json")
    pack["stages"]["classifier"]["preprocessing"]["crop_policy"][
        "include_linked_objects"
    ] = True
    with pytest.raises(jsonschema.ValidationError):
        validate("model-pack-v2.schema.json", pack)


def test_offline_references_cannot_be_runtime_or_acceptance_models():
    pack = load_json(FIXTURES / "de-yolox-mnv3-shadow-pack-v2.json")
    roles = {
        reference["reference_id"]: reference
        for reference in pack["offline_references"]
    }
    assert roles["gtsign-220-vit"]["role"] == "offline_teacher"
    assert roles["panoramax-classify-de-road-signs"]["role"] == "offline_crop_benchmark"
    assert all(not reference["runtime_included"] for reference in roles.values())
    assert all(
        not reference["acceptance_gate_eligible"] for reference in roles.values()
    )


def test_panoramax_full_resolution_fixture_freezes_reviewed_temporal_evidence():
    fixture = load_json(FIXTURES / "panoramax-m0-round-trip-v2.json")
    pack = load_json(FIXTURES / "de-yolox-mnv3-shadow-pack-v2.json")
    hard, readable = fixture["observations"]

    assert [hard["sequence_rank"], readable["sequence_rank"]] == [10, 11]
    assert hard["neighbors"]["next_picture_id"] == readable["picture_id"]
    assert readable["neighbors"]["previous_picture_id"] == hard["picture_id"]
    hard_time = datetime.fromisoformat(hard["timestamp_utc"].replace("Z", "+00:00"))
    readable_time = datetime.fromisoformat(
        readable["timestamp_utc"].replace("Z", "+00:00")
    )
    gap_ms = (readable_time - hard_time).total_seconds() * 1000
    assert gap_ms <= pack["thresholds"]["confirmation_window_ms"]
    assert pack["thresholds"]["confirmation_frames"] == 2
    hard_primary_box = normalized_box(
        hard, hard["review"]["primary"]["bounding_box"]
    )
    readable_primary_box = normalized_box(
        readable, readable["review"]["primary"]["bounding_box"]
    )
    assert hard_primary_box["x"] + hard_primary_box["width"] < readable_primary_box["x"]
    assert pack["thresholds"]["stable_observation_hint_can_override_iou"] is True
    assert pack["thresholds"]["fallback_requires_unique_candidate"] is True
    assert hard["hd_asset"]["sha256"] == (
        "1d2c8a66c8eedf68c3028d8749c5916c597ba2b7feeb4e1ddb71a4bf219b3f76"
    )
    assert readable["hd_asset"]["sha256"] == (
        "3ad4c4349a121ab9695a8febaeb0bff4feadef4739672f434c63e98c8f0d3d0b"
    )

    hard_plate = hard["review"]["supplementary_plate"]
    readable_plate = readable["review"]["supplementary_plate"]
    assert hard["review"]["primary"]["semantic"]["value"] == 70
    assert hard_plate["present"] is True
    assert hard_plate["readability"] == "unreadable"
    assert hard_plate["restriction"] is None
    assert readable_plate["restriction"]["kind"] == "extent"
    assert readable_plate["restriction"]["extent_m"] == 2000
    assert fixture["temporal_contract"]["expected_final_track"]["restriction"] == {
        "kind": "extent",
        "normalized_value": "2000 m",
        "extent_m": 2000,
    }

    for observation in fixture["observations"]:
        expected = observation["review"]["expected_shadow"]
        assert expected["override_eligible"] is False
        assert expected["road_context"]["way_id"] == "52869774"
        assert expected["road_context"]["travel_direction"] == "reverse"
        assert (
            expected["road_context"]["latitude"]
            == observation["coordinate"]["latitude"]
        )
        assert (
            expected["road_context"]["longitude"]
            == observation["coordinate"]["longitude"]
        )


def test_full_scene_annotations_require_separate_plate_box_and_unreadable_null():
    fixture = load_json(FIXTURES / "panoramax-m0-round-trip-v2.json")
    manifest = load_json(FIXTURES / "panoramax-m0-full-scene-annotations-v2.json")
    assert manifest == full_scene_manifest(fixture)
    validate("full-scene-annotation-v2.schema.json", manifest)

    for frame in manifest["frames"]:
        width = frame["image"]["width"]
        height = frame["image"]["height"]
        assert {obj["role"] for obj in frame["objects"]} == {
            "primary_sign",
            "supplementary_plate",
        }
        boxes = []
        for obj in frame["objects"]:
            box = obj["bounding_box"]
            assert box["x"] + box["width"] <= width
            assert box["y"] + box["height"] <= height
            boxes.append(tuple(box.values()))
            assert obj["physical_sign_id"] == fixture["physical_sign_id"]
        assert len(set(boxes)) == 2

    invalid = copy.deepcopy(manifest)
    hard_plate = invalid["frames"][0]["objects"][1]
    hard_plate["restriction_evidence"]["restriction"] = {
        "kind": "extent",
        "normalized_value": "2000 m",
        "extent_m": 2000,
        "raw_text": "2 km",
        "country_sign_code": None,
    }
    with pytest.raises(jsonschema.ValidationError):
        validate("full-scene-annotation-v2.schema.json", invalid)


def test_shadow_events_bind_both_stage_identities_and_never_override():
    fixture = load_json(FIXTURES / "panoramax-m0-round-trip-v2.json")
    hard_event = shadow_event(fixture, fixture["observations"][0])
    readable_event = shadow_event(fixture, fixture["observations"][1])
    validate("recognition-event-v2.schema.json", hard_event)
    validate("recognition-event-v2.schema.json", readable_event)

    assert hard_event["state"] == "provisional"
    assert hard_event["assemblies"][0]["temporal_evidence"]["evidence_frame_count"] == 1
    assert readable_event["state"] == "confirmed"
    assert readable_event["assemblies"][0]["temporal_evidence"][
        "evidence_frame_count"
    ] == 2
    hard_plate = hard_event["assemblies"][0]["supplementary_plates"][0]
    assert hard_plate["classifier_score"] is not None
    assert hard_plate["class_id"] is None
    assert hard_plate["restriction"] is None
    assert readable_event["assemblies"][0]["supplementary_plates"][0]["restriction"][
        "kind"
    ] == "extent"
    assert readable_event["assemblies"][0]["temporal_evidence"][
        "restriction_transition"
    ] == "upgraded_from_later_readable_evidence"

    invalid = copy.deepcopy(hard_event)
    invalid["override_eligible"] = True
    with pytest.raises(jsonschema.ValidationError):
        validate("recognition-event-v2.schema.json", invalid)

    invalid = copy.deepcopy(hard_event)
    invalid["assemblies"][0]["primary"]["detector_score"]["raw_score"] = None
    with pytest.raises(jsonschema.ValidationError):
        validate("recognition-event-v2.schema.json", invalid)

    invalid = copy.deepcopy(hard_event)
    invalid["assemblies"][0]["supplementary_plates"][0]["restriction"] = {
        "kind": "extent",
        "normalized_value": "2000 m",
        "extent_m": 2000,
        "raw_text": None,
        "country_sign_code": None,
    }
    with pytest.raises(jsonschema.ValidationError):
        validate("recognition-event-v2.schema.json", invalid)


def test_committed_reviewed_expected_events_are_not_model_inference():
    events = load_json(FIXTURES / "recognition-events-v2.json")
    fixture = load_json(FIXTURES / "panoramax-m0-round-trip-v2.json")
    assert len(events) == 2
    for event in events:
        validate("recognition-event-v2.schema.json", event)
        assert event["evidence_origin"] == "reviewed_expectation"
        assert event["override_eligible"] is False
        assert event["stage_runs"]["detector"]["invoked"] is False
        assert event["stage_runs"]["classifier"]["invoked"] is False
        primary = event["assemblies"][0]["primary"]
        plate = event["assemblies"][0]["supplementary_plates"][0]
        assert primary["detector_score"] is None
        assert primary["classifier_score"] is None
        assert plate["detector_score"] is None
        assert plate["classifier_score"] is None

    hard, readable = events
    assert [event["frame"]["frame_id"] for event in events] == [
        observation["picture_id"] for observation in fixture["observations"]
    ]
    assert all(
        event["assemblies"][0]["physical_sign_track_id"]
        == fixture["physical_sign_id"]
        for event in events
    )
    assert hard["state"] == "provisional"
    assert hard["assemblies"][0]["supplementary_plates"][0]["restriction"] is None
    assert readable["state"] == "confirmed"
    restriction = readable["assemblies"][0]["supplementary_plates"][0][
        "restriction"
    ]
    assert restriction["kind"] == "extent"
    assert restriction["extent_m"] == 2000

    invalid = copy.deepcopy(events[0])
    invalid["stage_runs"]["detector"]["invoked"] = True
    with pytest.raises(jsonschema.ValidationError):
        validate("recognition-event-v2.schema.json", invalid)

    invalid = copy.deepcopy(events[0])
    invalid["assemblies"][0]["primary"]["detector_score"] = {
        "raw_score": 0.99,
        "calibrated_confidence": 0.99,
    }
    with pytest.raises(jsonschema.ValidationError):
        validate("recognition-event-v2.schema.json", invalid)


def test_taxonomy_is_frozen_and_rejects_published_panoramax_validation():
    taxonomy = load_json(TSR_ROOT / "taxonomy-v2.json")
    assert taxonomy["status"] == "frozen"
    assert taxonomy["detector_classes"] == [
        {
            "class_id": "primary_sign",
            "output_index": 0,
            "requires_separate_full_scene_box": True,
        },
        {
            "class_id": "supplementary_plate",
            "output_index": 1,
            "requires_separate_full_scene_box": True,
        },
    ]
    assert 70 in taxonomy["primary_classifier_taxonomy"]["numeric_values_kmh"]
    assert "extent" in taxonomy["supplementary_classifier_taxonomy"][
        "restriction_kinds"
    ]
    assert taxonomy["split_rules"]["published_panoramax_validation_allowed"] is False
    assert taxonomy["split_rules"]["prohibited_source_split_id"] == (
        "panoramax-classified-de-road-signs-b485694-validation"
    )


def test_zod_audit_fails_closed_for_supplementary_plate_training():
    audit = load_json(TSR_ROOT / "zod-supplementary-plate-audit-v1.json")
    assert audit["devkit"]["revision"] == (
        "601a3ef5cfccad9cc545230362077d299acbf898"
    )
    assert all(
        audit["devkit"]["revision"] in uri
        for uri in audit["devkit"]["evidence_uris"]
    )
    assert audit["reviewed_contract"]["class_count"] == 156
    assert audit["reviewed_contract"]["has_separate_supplementary_plate_class"] is False
    assert audit["reviewed_contract"]["has_parent_or_assembly_link"] is False
    assert audit["reviewed_contract"][
        "not_listed_class_can_map_to_supplementary_plate"
    ] is False
    assert audit["eligibility"]["supplementary_plate_proposal_training"] == "ineligible"


def test_group_split_fixture_is_schema_valid_and_leakage_safe():
    manifest = load_json(FIXTURES / "group-split-v2.json")
    validate("group-split-v2.schema.json", manifest)
    assert_group_invariants(manifest)
    assert manifest["leakage_audit"]["passed"] is True


def test_group_split_invariants_reject_sign_leakage_and_published_source_alias():
    manifest = load_json(FIXTURES / "group-split-v2.json")
    manifest["samples"][2]["physical_sign_ids"] = ["physical-sign-train-a"]
    manifest["components"][1]["physical_sign_ids"] = ["physical-sign-train-a"]
    with pytest.raises(AssertionError):
        assert_group_invariants(manifest)

    manifest = load_json(FIXTURES / "group-split-v2.json")
    manifest["samples"][0]["source_split_id"] = "panoramax-de-validation-b485694"
    with pytest.raises(AssertionError):
        assert_group_invariants(manifest)


def test_near_duplicate_audit_can_only_pass_with_zero_overlap():
    manifest = load_json(FIXTURES / "group-split-v2.json")
    pending = copy.deepcopy(manifest)
    pending["leakage_audit"]["near_duplicate_analysis_status"] = "pending"
    pending["leakage_audit"]["near_duplicate_overlap_count"] = None
    pending["leakage_audit"]["passed"] = False
    validate("group-split-v2.schema.json", pending)

    pending["leakage_audit"]["passed"] = True
    with pytest.raises(jsonschema.ValidationError):
        validate("group-split-v2.schema.json", pending)
