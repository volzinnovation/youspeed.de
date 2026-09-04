import copy
import hashlib
from pathlib import Path

import numpy as np
import pytest
from PIL import Image

from scripts.tsr.m0_shadow_round_trip import (
    RoundTripV2Error,
    build_report,
    load_json,
)


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "shared" / "tsr" / "fixtures"


def _fixtures():
    return (
        load_json(FIXTURES / "de-yolox-mnv3-shadow-pack-v2.json"),
        load_json(FIXTURES / "panoramax-m0-round-trip-v2.json"),
        load_json(FIXTURES / "recognition-events-v2.json"),
    )


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_committed_reviewed_round_trip_is_shadow_only_and_not_model_inference() -> None:
    pack, fixture, events = _fixtures()
    report = build_report(pack, fixture, events)

    assert report["contract_status"] == "passed"
    assert report["source_asset_status"] == "not_run"
    assert report["preprocessing_status"] == "not_run"
    assert report["shadow_event_status"] == "passed"
    assert report["model_inference_status"] == "not_run_missing_trained_artifacts"
    assert report["model_inference_claimed"] is False
    assert report["override_gate_status"] == "blocked_shadow_only"
    assert report["temporal_association"] == {
        "frame_gap_ms": 1737.0,
        "cross_frame_image_iou": 0.0,
        "association_basis": "reviewed_stable_physical_sign_hint",
    }


def test_hard_event_cannot_inherit_later_restriction_or_override() -> None:
    pack, fixture, events = _fixtures()
    inherited = copy.deepcopy(events)
    inherited[0]["assemblies"][0]["supplementary_plates"][0]["restriction"] = {
        "kind": "extent",
        "normalized_value": "2000 m",
        "extent_m": 2000,
        "raw_text": None,
        "country_sign_code": None,
    }
    with pytest.raises(RoundTripV2Error, match="fails schema"):
        build_report(pack, fixture, inherited)

    override = copy.deepcopy(events)
    override[1]["override_eligible"] = True
    with pytest.raises(RoundTripV2Error, match="fails schema"):
        build_report(pack, fixture, override)


def test_event_stage_identity_must_match_the_pack() -> None:
    pack, fixture, events = _fixtures()
    mismatched = copy.deepcopy(events)
    mismatched[0]["stage_runs"]["classifier"]["artifact_sha256"] = "a" * 64
    with pytest.raises(RoundTripV2Error, match="artifact hash does not match pack"):
        build_report(pack, fixture, mismatched)


def test_reviewed_event_boxes_must_match_full_scene_annotations() -> None:
    pack, fixture, events = _fixtures()
    moved = copy.deepcopy(events)
    moved[0]["assemblies"][0]["primary"]["bounding_box"]["x"] += 0.01
    with pytest.raises(RoundTripV2Error, match="does not match the reviewed"):
        build_report(pack, fixture, moved)


def test_runtime_inference_cannot_be_relabelled_as_reviewed_oracle_evidence() -> None:
    pack, fixture, events = _fixtures()
    runtime = copy.deepcopy(events)
    score = {"raw_score": 0.9, "calibrated_confidence": 0.8}
    for event in runtime:
        event["evidence_origin"] = "runtime_inference"
        for run in event["stage_runs"].values():
            run["invoked"] = True
            run["latency_ms"] = 1
        for assembly in event["assemblies"]:
            assembly["primary"]["detector_score"] = score
            assembly["primary"]["classifier_score"] = score
            for plate in assembly["supplementary_plates"]:
                plate["detector_score"] = score
                if plate["readability"] == "readable":
                    plate["classifier_score"] = score

    with pytest.raises(RoundTripV2Error, match="must be reviewed expectations"):
        build_report(pack, fixture, runtime)


def test_exact_assets_generate_independent_detector_primary_and_plate_evidence(
    tmp_path: Path,
) -> None:
    pack, fixture, events = _fixtures()
    fixture = copy.deepcopy(fixture)
    events = copy.deepcopy(events)
    images: dict[str, Path] = {}
    boxes = [
        (
            {"x": 2, "y": 2, "width": 8, "height": 8},
            {"x": 2, "y": 12, "width": 8, "height": 6},
        ),
        (
            {"x": 22, "y": 20, "width": 8, "height": 8},
            {"x": 22, "y": 30, "width": 8, "height": 6},
        ),
    ]
    for index, observation in enumerate(fixture["observations"]):
        pixels = np.zeros((48, 40, 3), dtype=np.uint8)
        pixels[:, :] = [10 + index, 20 + index, 30 + index]
        primary_box, plate_box = boxes[index]
        pixels[
            primary_box["y"] : primary_box["y"] + primary_box["height"],
            primary_box["x"] : primary_box["x"] + primary_box["width"],
        ] = [240, 20 + index, 20]
        pixels[
            plate_box["y"] : plate_box["y"] + plate_box["height"],
            plate_box["x"] : plate_box["x"] + plate_box["width"],
        ] = [20, 240, 20 + index]
        path = tmp_path / f"{observation['observation_id']}.png"
        Image.fromarray(pixels).save(path)
        observation["hd_asset"].update(
            {"width": 40, "height": 48, "sha256": _sha256(path)}
        )
        observation["review"]["primary"]["bounding_box"] = primary_box
        observation["review"]["supplementary_plate"]["bounding_box"] = plate_box
        event = next(
            item for item in events if item["frame"]["frame_id"] == observation["picture_id"]
        )
        event["frame"]["width"] = 40
        event["frame"]["height"] = 48
        event["assemblies"][0]["primary"]["bounding_box"] = {
            field: primary_box[field] / (40 if field in {"x", "width"} else 48)
            for field in ("x", "y", "width", "height")
        }
        event["assemblies"][0]["supplementary_plates"][0]["bounding_box"] = {
            field: plate_box[field] / (40 if field in {"x", "width"} else 48)
            for field in ("x", "y", "width", "height")
        }
        images[observation["observation_id"]] = path

    report = build_report(
        pack,
        fixture,
        events,
        images,
        capture_dir=tmp_path / "captures",
    )

    assert report["source_asset_status"] == "passed"
    assert report["preprocessing_status"] == "passed"
    assert len(report["preprocessing"]) == 2
    for observation in report["preprocessing"]:
        detector = observation["detector"]
        primary = observation["classifier"]["primary_sign"]
        plate = observation["classifier"]["supplementary_plate"]
        assert detector["tensor_shape"] == [1, 3, 640, 640]
        assert primary["tensor_shape"] == [1, 3, 224, 224]
        assert plate["tensor_shape"] == [1, 3, 224, 224]
        assert primary["tensor_sha256"] != plate["tensor_sha256"]
        assert primary["metadata"]["role_hint"] == "primary_sign"
        assert plate["metadata"]["role_hint"] == "supplementary_plate"
        assert set(observation["diagnostic_captures"]) == {
            "detector",
            "primary",
            "supplementary",
        }


def test_asset_hash_mismatch_fails_before_preprocessing(tmp_path: Path) -> None:
    pack, fixture, events = _fixtures()
    bad = tmp_path / "bad.png"
    Image.new("RGB", (10, 10)).save(bad)
    with pytest.raises(RoundTripV2Error, match="hash mismatch"):
        build_report(
            pack,
            fixture,
            events,
            {"hard-preceding-frame": bad},
        )
