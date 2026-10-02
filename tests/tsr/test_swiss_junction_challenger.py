"""Real Swiss still provenance and separate oracle decision-wiring regressions.

No lane model runs here. Manual geometry and user labels are distinct; hypothetical
pose/association inputs below are deliberately an oracle, never live measurements.
"""
from copy import deepcopy
from dataclasses import replace
import hashlib
import json

import pytest

from scripts.tsr.applicability.exit_hypothesis_simulation import (
    Encounter, ExitHypothesisSimulation, GeometryHint, Observation, Pose,
)
from scripts.tsr.applicability.image_geometry_replay import ROOT, predict, run, timestamp, validate


BASE = ROOT / "shared/tsr/applicability/fixtures/panoramax-swiss-junction-v1"
CORPUS = BASE / "corpus.json"


def corpus():
    return json.loads(CORPUS.read_text())


def oracle_observations():
    """Correct association + perfectly current pose counterfactual, behavior off.

    Keep actual still time/boxes/numbers; do not manufacture a video sequence.
    Synthetic physical IDs distinguish the two candidates in ONE frame only.
    """
    frame = corpus()["frames"][0]
    at = timestamp(frame["captured_at"]) // 1000
    main = "oracle-current-road"
    branch = "oracle-left-street"
    encounter = Encounter("swiss-junction-oracle", "one-still", branch,
                          bundle_id="oracle-no-real-bundle", camera_geometry_id="oracle-no-calibration")
    output = []
    # These explicit reviewed-relation oracle inputs are not prediction targets
    # fed to the image geometry algorithm. Their accuracy is NOT being measured.
    for sign, relation in zip(frame["signs"], ("branch", "mainline")):
        x, _, width, _ = sign["box"]
        output.append(Observation(
            encounter, frame["frame_id"], at, f"oracle-{sign['sign_id']}",
            sign["value_kmh"], Pose(at, main),
            GeometryHint(relation, source="reviewed_geometry", branch_kind="junction",
                         mainline_way_ids=(main,), branch_way_ids=(branch,),
                         topology_built_at_ms=at), image_center_x=x + width / 2))
    return output


def test_real_still_metadata_and_user_labels_remain_separate_from_recognition():
    data = corpus()
    assert validate(data, verify_images=False)["frames"] == 1
    frame = data["frames"][0]
    source = frame["source"]
    metadata_bytes = (ROOT / source["metadata_path"]).read_bytes()
    assert hashlib.sha256(metadata_bytes).hexdigest() == source["metadata_sha256"]
    metadata = json.loads(metadata_bytes)
    assert frame["captured_at"] == metadata["properties"]["datetime"]
    assert frame["frame_id"] == metadata["id"]
    assert frame["sequence_id"] == metadata["collection"]
    assert source["coordinates"] == metadata["geometry"]["coordinates"]
    assert frame["temporal_tracking_eligible"] is False
    assert frame["legacy_evaluation_eligible"] is False
    assert frame["topology"]["motorway"] is False
    assert frame["visual_cues"]["continuous_painted_ego_lane_boundaries"] == "not_visible"
    assert {s["value_kmh"]: s["expected_applicability"] for s in frame["signs"]} == {30: "other", 50: "ego"}
    assert all(s["track_id"] is None and not s["track_verified"] for s in frame["signs"])
    assert source["historical_app_annotation"]["applicability_status"] == "UNKNOWN"


def test_manual_geometry_replay_preserves_the_unresolved_legitimate_fifty():
    data = corpus()
    rows = predict(data)
    assert [r["reviewed_geometry"] for r in rows] == ["other", "unknown"]
    assert rows[1]["geometry_reason"] == "missing_reliable_ground_anchor"
    assert all(r["legacy_fixed_x_approximation"] == "not_evaluated" for r in rows)
    # Labels are only score inputs; they cannot force the missing main-road result.
    changed = deepcopy(data)
    for sign in changed["frames"][0]["signs"]:
        sign.update(expected_applicability="unknown", expected_road_id=None)
    assert predict(changed) == rows
    changed["frames"][0]["geometry"]["reviewed"] = False
    assert all(r["reviewed_geometry"] == "unknown" for r in predict(changed))


def test_frozen_swiss_geometry_report_matches_pinned_inputs():
    frozen = json.loads((BASE / "image-geometry.report.json").read_text())
    fresh = run([CORPUS], verify_images=False)
    for key in ("predictions", "stages", "coverage", "runner_sha256", "corpus_schema_sha256"):
        assert fresh[key] == frozen[key]
    assert fresh["corpora"][0]["sha256"] == frozen["corpora"][0]["sha256"]
    assert fresh["coverage"]["track_reuses"] == 0


@pytest.mark.parametrize("reverse_order", [False, True])
def test_two_signs_in_one_frame_get_independent_decisions_with_oracle_geometry(reverse_order):
    observations = oracle_observations()
    if reverse_order:
        observations.reverse()
    simulation = ExitHypothesisSimulation()
    decisions = {o.speed_limit_kmh: simulation.observe(o) for o in observations}
    assert {value: d.outcome for value, d in decisions.items()} == {30: "reject", 50: "ego"}
    # Two objects do not become two confirmations of either physical sign.
    assert all(d.distinct_observations_in_burst == 1 for d in decisions.values())
    assert all(not d.corroboration for d in decisions.values())


@pytest.mark.parametrize("left,right", [(0.1, 0.9), (0.9, 0.1), (0.5, 0.5)])
def test_counterfactual_image_position_never_becomes_a_left_or_right_side_veto(left, right):
    thirty, fifty = oracle_observations()
    simulation = ExitHypothesisSimulation()
    assert simulation.observe(replace(thirty, image_center_x=left)).outcome == "reject"
    assert simulation.observe(replace(fifty, image_center_x=right)).outcome == "ego"


@pytest.mark.parametrize("missing", ["pose", "geometry", "corridor"])
def test_missing_path_or_pose_evidence_abstains_for_both_numbers(missing):
    simulation = ExitHypothesisSimulation()
    for observation in oracle_observations():
        if missing == "pose":
            observation = replace(observation, pose=None)
        elif missing == "geometry":
            observation = replace(observation, geometry=None)
        else:
            observation = replace(observation, geometry=replace(observation.geometry, sign_corridor="unknown"))
        assert simulation.observe(observation).outcome == "hold"


def test_counterfactual_turn_into_side_street_makes_thirty_current():
    # Separate counterfactual pose at this still, not a fabricated later drive frame.
    thirty, fifty = oracle_observations()
    simulation = ExitHypothesisSimulation()
    on_branch = Pose(thirty.captured_at_ms, "oracle-left-street")
    assert simulation.observe(replace(thirty, pose=on_branch)).outcome == "ego"
    assert simulation.observe(replace(fifty, pose=on_branch)).outcome == "hold"
