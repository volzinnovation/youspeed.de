"""Characterize retained field failures without labelling predictions as truth.

These tests protect a reproducible baseline, not desired suppression behavior.
Run the actual native replay separately and set YOUSPEED_FR_EXIT_REPLAY_OUTPUT to
its output directory to compare it with the frozen historical baseline. Ordinary
pytest runs validate the retained corpus without compiling Swift/Kotlin again.
"""

from collections import Counter
from datetime import datetime
import hashlib
import importlib.util
import json
import os
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "shared/tsr/applicability/fixtures"
NAME = "fr-exit-failures-20260928-v1"
CORPUS_PATH = FIXTURES / f"{NAME}.json"
CORPUS = json.loads(CORPUS_PATH.read_text())
MANIFEST = json.loads((FIXTURES / f"{NAME}.manifest.json").read_text())
BASELINE = json.loads((FIXTURES / f"{NAME}.baseline.json").read_text())
SCENARIOS = {scenario["id"]: scenario for scenario in CORPUS["scenarios"]}
CLIPS = {clip["scenarioId"]: clip for clip in MANIFEST["clips"]}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


def millis(timestamp):
    return datetime.fromisoformat(timestamp.replace("Z", "+00:00")).timestamp() * 1000


def batches(scenario):
    return SCENARIOS[scenario]["batches"]


def candidate(candidate_id):
    matches = [
        (batch, item)
        for scenario in SCENARIOS.values()
        for batch in scenario["batches"]
        for item in batch["candidates"]
        if item["candidateId"] == candidate_id
    ]
    assert len(matches) == 1
    return matches[0]


def projected_frame(frame):
    return {
        "frameId": frame["batch"]["frameId"],
        "capturedAtMs": frame["batch"]["capturedAtMs"],
        "decisions": [
            {key: decision[key] for key in (
                "trackId", "classification", "reasons", "displayEligible",
                "immediateEligible", "passageEligible",
            )}
            for decision in frame["decisions"]
        ],
    }


def test_real_failure_corpus_remains_unreviewed_and_hash_bound():
    assert len(SCENARIOS) == 4
    assert sum(len(s["batches"]) for s in SCENARIOS.values()) == 263
    assert CORPUS["reviewStatus"] == "unreviewed"
    assert CORPUS["sourceSha256"] == MANIFEST["source"]["sha256"]
    assert digest(CORPUS_PATH.read_bytes()) == MANIFEST["fixtureSha256"]
    assert MANIFEST["verifiedApplicabilityGroundTruth"] is False
    for scenario in SCENARIOS.values():
        assert scenario["origin"] == "unreviewed_real"
        assert scenario["expectedFinalClass"] is None


def test_recorded_batches_validate_with_actual_replay_contract():
    spec = importlib.util.spec_from_file_location(
        "fr_exit_replay", ROOT / "scripts/tsr/applicability/replay.py"
    )
    replay = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(replay)
    replay.validate_vectors(CORPUS)


@pytest.mark.parametrize("scenario_id", SCENARIOS)
def test_original_frame_identity_timestamps_and_causal_order_are_preserved(scenario_id):
    clip = CLIPS[scenario_id]
    frames = batches(scenario_id)
    assert [
        {"frameId": frame["frameId"], "sha256": digest(canonical(frame))}
        for frame in frames
    ] == clip["batchSha256"]
    times = [frame["capturedAtMs"] for frame in frames]
    assert len({frame["frameId"] for frame in frames}) == len(frames)
    assert all(right > left for left, right in zip(times, times[1:]))
    assert times[0] == clip["firstCaptureMs"]
    assert times[-1] == clip["lastCaptureMs"]
    assert millis(clip["requestedStartUtc"]) - 5000 <= times[0]
    assert times[-1] <= millis(clip["requestedEndUtc"])
    assert max(right - left for left, right in zip(times, times[1:])) == clip["maximumCaptureGapMs"]
    for frame in frames:
        assert frame["road"]["capturedAtMs"] <= frame["capturedAtMs"]
        for item in frame["candidates"]:
            assert item["candidateId"].startswith(frame["frameId"] + ":")


def test_fresh_connected_exit_can_still_appear_left_of_old_image_boundary():
    frame, item = candidate("66a36d2e-dc4a-4641-a6b2-98c220883dc7:0")
    assert item["semanticKey"] == "maximum_speed:70:km/h"
    assert item["recognitionEligible"] is True
    assert item["box"]["x"] + item["box"]["width"] / 2 < 0.60
    assert frame["capturedAtMs"] - frame["road"]["capturedAtMs"] == 1381
    assert any(branch["roadClass"] == "motorway_link" and branch["endpointLinked"]
               for branch in frame["road"]["branches"])


def test_service_area_30_has_motorway_context_but_no_recorded_branch():
    frame, item = candidate("dabbb355-3d52-460b-a7bf-bff65be27d7d:0")
    assert item["semanticKey"] == "maximum_speed:30:km/h"
    assert item["recognitionEligible"] is True
    assert item["box"]["x"] + item["box"]["width"] / 2 > 0.70
    assert frame["road"]["roadClass"] == "motorway"
    assert frame["road"]["postedSpeedKmh"] == 130
    assert frame["road"]["branches"] == []
    assert frame["capturedAtMs"] - frame["road"]["capturedAtMs"] == 3294


def test_reduction_cascade_preserves_order_and_classifier_flicker():
    # Exact observed anchors establish a sequence, not four verified physical signs.
    anchors = [candidate(identity) for identity in (
        "97e3808c-a563-4d49-8732-6dda11e5e38a:0",
        "ba7fe13f-1ad1-484f-8abf-37f8b56451ea:0",
        "723ca3bc-2256-4756-baa9-4cff75620b2a:0",
        "dabbb355-3d52-460b-a7bf-bff65be27d7d:0",
    )]
    assert [item["semanticKey"] for _, item in anchors] == [
        f"maximum_speed:{speed}:km/h" for speed in (90, 70, 50, 30)
    ]
    times = [frame["capturedAtMs"] for frame, _ in anchors]
    assert times == sorted(times)
    assert times[-1] - times[0] == 8261
    assert all(item["recognitionEligible"] for _, item in anchors)
    # An earlier 30 proposal really occurred among 90 proposals; do not clean it away.
    early_frame, early_item = candidate("656a2e7f-fc1c-4ddf-b87d-b68a59cdc1f0:0")
    assert early_item["semanticKey"] == "maximum_speed:30:km/h"
    assert times[0] < early_frame["capturedAtMs"] < times[1]


def test_separate_ramp_70_retains_five_second_context_gap():
    frame, item = candidate("beeb67b4-7f5d-4bbb-a504-8b5f550059be:0")
    assert item["semanticKey"] == "maximum_speed:70:km/h"
    assert item["recognitionEligible"] is True
    assert frame["road"]["branches"] == []
    assert frame["capturedAtMs"] - frame["road"]["capturedAtMs"] == 5027


def test_dismissal_followed_by_new_camera_claim_is_preserved_as_observation():
    events = CLIPS["clip-160920"]["recordedAuthorityEvents"]
    references = [event for event in events if event["event"] == "speed_reference"]
    dismissed = next(event for event in references if event["reason"] == "camera_dismissed")
    before = [event for event in references
              if event["state"] == "CAMERA" and event["timestampUTC"] < dismissed["timestampUTC"]][-1]
    after = next(event for event in references
                 if event["state"] == "CAMERA" and event["timestampUTC"] > dismissed["timestampUTC"])
    assert dismissed["state"] == "BUNDLE" and dismissed["transition"] == "T16"
    assert before["evidenceId"] != after["evidenceId"]
    assert millis(after["timestampUTC"]) - millis(dismissed["timestampUTC"]) == pytest.approx(3074.869, abs=0.001)
    # A later high-limit candidate must survive in the corpus as a recovery control.
    assert any(item["semanticKey"] == "maximum_speed:110:km/h" and item["recognitionEligible"]
               for frame in batches("clip-160920") for item in frame["candidates"]
               if frame["capturedAtMs"] > millis(after["timestampUTC"]))


def test_photo_links_and_dismissals_remain_review_evidence_not_truth():
    for clip in CLIPS.values():
        assert clip["verifiedApplicabilityGroundTruth"] is False
        assert clip["reviewStatus"] == "log_and_nearby_still_review_only"
        photo = clip["photo"]
        assert len(photo["sha256"]) == 64
        assert photo["widthPixels"] == 4096 and photo["heightPixels"] == 3072
        assert clip["firstCaptureMs"] <= millis(photo["capturedAtUtc"]) <= clip["lastCaptureMs"]
        assert any(event["event"] == "vision_dismissed" and event["source"] == "user"
                   for event in clip["recordedAuthorityEvents"])
        times = [event["timestampUTC"] for event in clip["recordedAuthorityEvents"]]
        assert times == sorted(times)


def test_frozen_native_baseline_records_unknown_without_claiming_suppression():
    report = BASELINE["nativeReplayReport"]
    assert BASELINE["status"] == "historical_characterization_not_target_behavior"
    assert BASELINE["fieldQualified"] is False
    assert report["parity"] == "passed" and report["lane"] == "recorded_candidate"
    assert report["corpusSha256"] == digest(CORPUS_PATH.read_bytes())
    assert len(report["sourceHashes"]) == 3
    assert report["numericTolerance"] == 1e-9
    decisions = []
    for scenario in BASELINE["scenarios"]:
        assert [(frame["frameId"], frame["capturedAtMs"]) for frame in scenario["frames"]] == [
            (frame["frameId"], frame["capturedAtMs"]) for frame in batches(scenario["id"])
        ]
        decisions.extend(decision for frame in scenario["frames"] for decision in frame["decisions"])
    assert Counter(decision["classification"] for decision in decisions) == {"UNKNOWN": 311}
    assert Counter(reason for decision in decisions for reason in decision["reasons"]) == {
        "unqualified_observation": 236, "stale_road_context": 66,
        "camera_calibration_unavailable": 8, "unreliable_road_context": 1,
    }
    assert not any(decision[key] for decision in decisions
                   for key in ("displayEligible", "immediateEligible", "passageEligible"))
    assert sum(frame["capturedAtMs"] - frame["road"]["capturedAtMs"] > 1500
               for scenario in SCENARIOS.values() for frame in scenario["batches"]) == 229


@pytest.mark.skipif(not os.environ.get("YOUSPEED_FR_EXIT_REPLAY_OUTPUT"),
                    reason="Run native replay separately; ordinary corpus checks need no compilers.")
def test_supplied_actual_native_replay_matches_frozen_baseline():
    output = Path(os.environ["YOUSPEED_FR_EXIT_REPLAY_OUTPUT"])
    report = json.loads((output / "report.json").read_text())
    predictions = json.loads((output / "predictions.json").read_text())
    assert report["parity"] == "passed"
    assert report["corpusSha256"] == digest(CORPUS_PATH.read_bytes())
    assert report["sourceHashes"] == BASELINE["nativeReplayReport"]["sourceHashes"]
    assert [{"id": scenario["id"], "frames": [projected_frame(frame) for frame in scenario["frames"]]}
            for scenario in predictions] == BASELINE["scenarios"]
