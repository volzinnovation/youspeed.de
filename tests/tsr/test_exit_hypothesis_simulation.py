"""Synthetic decision-wiring tests, not a detector or field-accuracy benchmark."""
from dataclasses import replace

import pytest

from scripts.tsr.applicability.exit_hypothesis_simulation import (
    Encounter, ExitHypothesisSimulation, GeometryHint, Observation, Pose, SpeedSample,
)


SCOPE = Encounter("synthetic-drive", "eastbound-pass-1", "exit-1")


def observation(at=10_000, track="sign-1", speed=70, corridor="branch", **changes):
    o = Observation(SCOPE, f"frame-{at}", at, track, speed, Pose(at - 100, "motorway-1"),
                    GeometryHint(corridor))
    return replace(o, **changes)


def steady(at):
    return tuple(SpeedSample(at - gap, 120) for gap in (3_000, 2_000, 1_000, 0))


def test_genuine_mainline_70_is_ego_even_when_driver_does_not_brake_near_exit():
    d = ExitHypothesisSimulation().observe(observation(corridor="mainline"), steady(10_000))
    assert (d.outcome, d.reason) == ("ego", "sign_on_current_mainline")
    assert d.corroboration == ("steady_speed",)


def test_descending_roadworks_signs_with_steady_driver_remain_ego():
    sim = ExitHypothesisSimulation()
    for index, limit in enumerate((90, 70, 50, 30)):
        at = 10_000 + index * 2_000
        d = sim.observe(observation(at, f"roadworks-{index}", limit, "mainline"), steady(at))
        assert d.outcome == "ego"
    assert "descending_distinct_signs" in d.corroboration


def test_behavior_and_descending_sequence_cannot_reject_without_geometry_assignment():
    sim = ExitHypothesisSimulation()
    for index, limit in enumerate((90, 70, 50, 30)):
        at = 10_000 + index * 2_000
        d = sim.observe(observation(at, f"sign-{index}", limit, "unknown"), steady(at))
        assert d.outcome == "hold"
    assert set(d.corroboration) == {"steady_speed", "descending_distinct_signs"}


def test_service_area_sign_near_image_centre_is_rejected_by_corridor_not_x():
    o = observation(speed=30, image_center_x=0.55,
                    geometry=GeometryHint("branch", branch_kind="service_area"))
    assert ExitHypothesisSimulation().observe(o).outcome == "reject"


def test_branch_context_rejects_new_physical_sign_after_dismissal_and_way_split():
    sim = ExitHypothesisSimulation()
    assert sim.observe(observation(speed=90)).outcome == "reject"
    sim.dismiss(SCOPE, 10_100)
    later = observation(13_170, "new-exit-sign", 50, pose=Pose(13_100, "motorway-2"))
    d = sim.observe(later)
    assert d.outcome == "reject"
    assert "dismissed_in_encounter" in d.corroboration


def test_dismissal_does_not_turn_unresolved_geometry_into_a_veto():
    sim = ExitHypothesisSimulation()
    sim.dismiss(SCOPE, 9_900)
    d = sim.observe(observation(geometry=None))
    assert (d.outcome, d.reason) == ("hold", "missing_geometry")


def test_actual_ramp_entry_releases_suppression_even_without_braking():
    sim = ExitHypothesisSimulation()
    assert sim.observe(observation()).outcome == "reject"
    sim.dismiss(SCOPE, 10_100)
    entered = observation(11_000, "next-sign", 50, pose=Pose(10_900, "ramp-1"))
    d = sim.observe(entered, steady(11_000))
    assert (d.outcome, d.reason) == ("ego", "sign_on_entered_branch")
    assert "dismissed_in_encounter" not in d.corroboration
    assert sim.observe(observation(12_000, "sign-3", 30)).reason == "mainline_encounter_ended"


@pytest.mark.parametrize("change", [
    {"session_id": "another-drive"}, {"traversal_id": "westbound-pass"},
    {"branch_id": "next-exit"}, {"bundle_id": "another-bundle"},
    {"camera_geometry_id": "rotated-mount"},
])
def test_dismissal_and_physical_track_history_do_not_cross_encounter_scope(change):
    sim = ExitHypothesisSimulation()
    sim.observe(observation())
    sim.dismiss(SCOPE, 10_100)
    d = sim.observe(observation(11_000, encounter=replace(SCOPE, **change)))
    assert "dismissed_in_encounter" not in d.corroboration
    assert d.distinct_observations_in_burst == 1


def test_old_static_topology_does_not_make_a_fresh_pose_stale():
    o = observation(at=1_800_000_000_000, geometry=GeometryHint("branch", topology_built_at_ms=0))
    assert ExitHypothesisSimulation().observe(o).outcome == "reject"
    stale = replace(o, pose=replace(o.pose, captured_at_ms=o.captured_at_ms - 3_000))
    d = ExitHypothesisSimulation().observe(stale)
    assert (d.outcome, d.reason) == ("hold", "stale_pose")


@pytest.mark.parametrize("changes,reason", [
    ({"pose": None}, "missing_pose"),
    ({"pose": Pose(9_900, "motorway-1", horizontal_accuracy_m=80)}, "unreliable_pose"),
    ({"pose": Pose(9_900, "motorway-1", course_accuracy_deg=50)}, "unreliable_pose"),
    ({"pose": Pose(9_900, "motorway-1", stable=False)}, "unreliable_pose"),
    ({"geometry": None}, "missing_geometry"),
    ({"geometry": GeometryHint("branch", topology_usable=False)}, "missing_geometry"),
    ({"geometry": GeometryHint("branch", inside_directed_interval=False)}, "outside_mainline_encounter"),
    ({"pose": Pose(9_900, "parallel-road")}, "outside_mainline_encounter"),
])
def test_unreliable_or_absent_context_holds(changes, reason):
    d = ExitHypothesisSimulation().observe(observation(**changes), steady(10_000))
    assert (d.outcome, d.reason) == ("hold", reason)


def test_future_driver_speed_is_rejected_and_does_not_contaminate_state():
    sim = ExitHypothesisSimulation()
    with pytest.raises(ValueError, match="Future speed"):
        sim.observe(observation(), steady(10_001))
    assert sim.observe(observation()).distinct_observations_in_burst == 1


@pytest.mark.parametrize("changes,error", [
    ({"pose": Pose(10_001, "motorway-1")}, "Future pose"),
    ({"geometry": GeometryHint("branch", topology_built_at_ms=10_001)}, "Future topology"),
])
def test_future_pose_or_topology_is_rejected(changes, error):
    with pytest.raises(ValueError, match=error):
        ExitHypothesisSimulation().observe(observation(**changes))


def test_same_physical_sign_class_flicker_is_not_a_descending_sign_sequence():
    sim = ExitHypothesisSimulation()
    for index, value in enumerate((90, 70, 50, 30)):
        d = sim.observe(observation(10_000 + index * 400, "same-sign", value))
        assert "descending_distinct_signs" not in d.corroboration
    assert d.distinct_observations_in_burst == 4


def test_descending_sequence_is_bounded_in_time():
    sim = ExitHypothesisSimulation()
    for index, value in enumerate((90, 70, 50, 30)):
        d = sim.observe(observation(10_000 + index * 20_000, f"sign-{index}", value))
        assert "descending_distinct_signs" not in d.corroboration


def test_sparse_panoramax_frames_never_manufacture_confirmation():
    sim = ExitHypothesisSimulation()
    for at in (10_000, 22_000, 34_000):
        d = sim.observe(observation(at))
        assert d.distinct_observations_in_burst == 1
        # A candidate-level geometric rejection is not a claim of recognition confirmation.
        assert d.outcome == "reject"


def test_duplicate_frame_and_duplicate_capture_time_add_no_observation():
    sim = ExitHypothesisSimulation()
    original = observation()
    assert sim.observe(original).distinct_observations_in_burst == 1
    assert sim.observe(original).reason == "duplicate_frame"
    assert sim.observe(replace(original, frame_id="duplicate-time")).reason == "non_increasing_capture_time"
    assert sim.observe(observation(10_400)).distinct_observations_in_burst == 2


@pytest.mark.parametrize("branch_first", [True, False])
def test_same_frame_can_contain_both_valid_mainline_and_unrelated_branch_signs(branch_first):
    sim = ExitHypothesisSimulation()
    candidates = [(observation(track="mainline-70", corridor="mainline"), "ego"),
                  (observation(track="branch-30", speed=30), "reject")]
    for candidate, expected in candidates[::(-1 if branch_first else 1)]:
        d = sim.observe(candidate)
        assert d.outcome == expected
        assert d.distinct_observations_in_burst == 1


def test_simultaneously_visible_descending_values_are_not_a_temporal_sequence():
    sim = ExitHypothesisSimulation()
    for index, value in enumerate((90, 70, 50, 30)):
        d = sim.observe(observation(track=f"simultaneous-{index}", speed=value))
        assert "descending_distinct_signs" not in d.corroboration


def test_reusing_frame_identity_with_changed_capture_time_is_invalid():
    sim = ExitHypothesisSimulation()
    sim.observe(observation())
    with pytest.raises(ValueError, match="immutable frame"):
        sim.observe(observation(10_200, frame_id="frame-10000"))


@pytest.mark.parametrize("status", ["skipped", "failed", "interrupted"])
def test_unanalyzed_frames_do_not_count_as_observations_or_visual_loss(status):
    sim = ExitHypothesisSimulation()
    assert sim.observe(observation()).distinct_observations_in_burst == 1
    assert sim.observe(observation(10_200, status=status)).reason == "frame_not_analyzed"
    assert sim.observe(observation(10_400)).distinct_observations_in_burst == 2


@pytest.mark.parametrize("pose", [None, Pose(1_000, "motorway-1"),
                                  Pose(10_900, "motorway-1", horizontal_accuracy_m=80)])
def test_invalid_pose_discards_prior_dismissal_support(pose):
    sim = ExitHypothesisSimulation()
    sim.observe(observation())
    sim.dismiss(SCOPE, 10_100)
    d = sim.observe(observation(11_000, pose=pose))
    assert d.outcome == "hold"
    assert "dismissed_in_encounter" not in d.corroboration
    assert "dismissed_in_encounter" not in sim.observe(observation(11_500)).corroboration


def test_long_gap_ends_old_encounter_until_a_new_traversal_is_supplied():
    sim = ExitHypothesisSimulation()
    sim.observe(observation())
    sim.dismiss(SCOPE, 10_100)
    assert sim.observe(observation(30_000)).reason == "encounter_expired"
    assert sim.observe(observation(30_400)).reason == "encounter_expired"
    fresh = replace(SCOPE, traversal_id="next-pass")
    assert sim.observe(observation(30_800, encounter=fresh)).outcome == "reject"


def test_continuous_observations_cannot_keep_dismissal_or_encounter_alive_forever():
    sim = ExitHypothesisSimulation()
    sim.observe(observation())
    sim.dismiss(SCOPE, 10_100)
    for at in range(11_000, 70_001, 1_000):
        d = sim.observe(observation(at))
        if at > 25_100:
            assert "dismissed_in_encounter" not in d.corroboration
    assert sim.observe(observation(71_000)).reason == "encounter_expired"


@pytest.mark.parametrize("value", [float("nan"), float("inf"), -1, True, 1.5])
def test_invalid_timestamp_cannot_bypass_freshness_or_causality(value):
    sim = ExitHypothesisSimulation()
    for o in (observation(captured_at_ms=value),
              observation(pose=Pose(value, "motorway-1")),
              observation(geometry=GeometryHint("branch", topology_built_at_ms=value))):
        with pytest.raises(ValueError, match="Timestamps"):
            sim.observe(o)
    with pytest.raises(ValueError, match="Timestamps"):
        sim.observe(observation(), (SpeedSample(value, 120),))


@pytest.mark.parametrize("field", ["session_id", "traversal_id", "branch_id",
                                   "bundle_id", "camera_geometry_id"])
def test_blank_encounter_identity_cannot_collapse_scope(field):
    with pytest.raises(ValueError, match="identity"):
        ExitHypothesisSimulation().observe(observation(encounter=replace(SCOPE, **{field: " "})))


@pytest.mark.parametrize("value", [0, -1, float("nan"), True, 60_001])
def test_experimental_time_windows_must_be_positive_and_bounded(value):
    with pytest.raises(ValueError, match="windows"):
        ExitHypothesisSimulation(max_pose_age_ms=value)


def test_dismissal_events_cannot_move_backwards_in_time():
    sim = ExitHypothesisSimulation()
    sim.observe(observation())
    sim.dismiss(SCOPE, 12_000)
    with pytest.raises(ValueError, match="Dismissal"):
        sim.dismiss(SCOPE, 11_000)


@pytest.mark.parametrize("changes", [
    {"pose": Pose(9_900, "ramp-1")},
    {"geometry": GeometryHint("branch", mainline_way_ids=("another-motorway",))},
])
def test_same_frame_cannot_have_contradictory_shared_road_context(changes):
    sim = ExitHypothesisSimulation()
    sim.observe(observation())
    with pytest.raises(ValueError, match="contradictory road context"):
        sim.observe(observation(track="another-sign", **changes))
    assert sim.observe(observation(track="mainline-sign", corridor="mainline")).outcome == "ego"
