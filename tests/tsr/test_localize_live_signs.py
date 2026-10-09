"""Synthetic adapter qualification; no private crops or external fixtures."""
from copy import deepcopy
from itertools import permutations
import math

import pytest

from scripts.tsr.collection import localize_live_signs as m


ORIGIN = [48.0, 8.0]
T0 = m.seconds("2026-10-09T12:00:00Z")


def policy():
    # Self-contained copy of the predeclared engineering sensitivity settings.
    return {
        "source_policy": "live-crops-only-v1",
        "camera_assumptions": {
            "calibrated": False, "horizontal_fov_scenarios_degrees": [45, 60, 75, 90],
            "mount_yaw_scenarios_degrees": [-15, 0, 15],
            "nominal_scenario": {"horizontal_fov_degrees": 60, "mount_yaw_degrees": 0},
            "mount_residual_bound_degrees": 5, "pixel_center_assumed_error_pixels": 3,
            "pitch_roll_model": "level_pinhole_approximation_unverified",
        },
        "course": {"max_reported_accuracy_degrees": 30, "minimum_assumed_bound_degrees": 3},
        "position_model": {
            "max_interpolation_gap_seconds": 2, "max_original_frame_fix_delta_seconds": 2,
            "maximum_assumed_acceleration_mps2": 10, "minimum_horizontal_bound_m": 5,
            "reported_accuracy_multiplier": 2, "unbracketed_max_speed_bound_mps": 60,
        },
        "road_query_margin_m": 1000, "road_search_radius_m": 50,
        "solver": {"max_range_m": 500, "min_baseline_m": 2, "min_parallax_degrees": 2,
                   "min_forward_m": .01, "max_condition_number": 10000,
                   "max_refine_iterations": 8, "convergence_m": 1e-6},
    }


def row(identity, en=(0, 0), captured=0, fix=None, accuracy=2, course=None,
        observation="observation", session="session", course_accuracy=1):
    fix = captured if fix is None else fix
    lat, lon = m.frame_position(en, ORIGIN)
    course = math.degrees(math.atan2(-en[0], 30 - en[1])) % 360 if course is None else course
    position = {"latitude": lat, "longitude": lon, "fix_at": m.utc(T0 + fix),
                "frame_fix_delta_ms": (captured - fix) * 1000,
                "horizontal_accuracy_m": accuracy, "course_degrees": course,
                "course_accuracy_degrees": course_accuracy}
    return {"installation": "synthetic-installation", "epoch": 1, "crop_id": identity,
            "manifest": {"observation_id": observation, "source_frame_at": m.utc(T0 + captured),
                         "vehicle_position": position, "source_width": 1920, "source_height": 1080,
                         "supplied_box": {"x": .45, "y": .2, "width": .1, "height": .1},
                         "orientation_version": "upright-1", "local_frame_token": "frame-" + identity,
                         "source_upright_sha256": m.digest(["synthetic-frame", identity])},
            "observation": {"collection_session_id": session,
                            "vehicle_position": deepcopy(position),
                            "classification": {"country": "DE", "canonical_code": "274", "value": 50}}}


def graph():
    return {"schema_version": 1,
            "source": {"sha256": "b" * 64, "kind": "original_osm", "geometry_bounds_known": True,
                       "topology": "original_osm_node_ids", "is_as_driven": False},
            "extraction": {"bounds_wgs84": [[7.99, 47.99, 8.01, 48.01]], "legal_routing_complete": False},
            "roads": [{"way_id": "100", "points_lat_lon": [m.frame_position(p, ORIGIN) for p in [(-100, 0), (100, 0)]],
                       "direction": "both", "node_ids": ["1", "2"], "geometry_error_bound_m": 0,
                       "tags": {"highway": "primary"}}]}


def keys(rows):
    return {m.key(r) for r in rows}


def test_camera_pinhole_pixel_angle_yaw_wrap_and_bound_units():
    source = row("a", course=355)
    bearing, error = m.camera_bearing(source, 90, 15, policy())
    assert bearing == pytest.approx(10)
    expected_pixel = math.degrees(math.atan(2 * 3 / 1920))
    assert error == pytest.approx(3 + 5 + expected_pixel)
    source["manifest"]["supplied_box"]["x"] = .7  # center=.75 -> atan(.5), not linear22.5°
    bearing, _ = m.camera_bearing(source, 90, 15, policy())
    assert bearing == pytest.approx((10 + math.degrees(math.atan(.5))) % 360)
    source["manifest"]["source_width"] *= 2
    assert m.camera_bearing(source, 90, 15, policy())[1] < error


@pytest.mark.parametrize("fov", [0, 180, float("nan"), True])
def test_bad_camera_fov_rejected(fov):
    with pytest.raises(ValueError, match="camera_geometry"):
        m.camera_bearing(row("a"), fov, 0, policy())


def test_parent_observation_position_cannot_manufacture_crop_specific_origins():
    legacy, null = row("legacy"), row("null")
    del legacy["manifest"]["vehicle_position"]
    null["manifest"]["vehicle_position"] = None
    assert m.own_position(legacy) is None and m.own_position(null) is None
    selected, reasons = m.select_rays([legacy, null], policy())
    assert not selected and reasons == {"no_crop_specific_position": 2}
    assert not m.build_tracks([legacy, null])


@pytest.mark.parametrize("change,reason", [
    (("course_degrees", float("nan")), "course_uncertainty_or_missing"),
    (("course_degrees", True), "course_uncertainty_or_missing"),
    (("course_degrees", 360), "course_uncertainty_or_missing"),
    (("course_accuracy_degrees", 30.01), "course_uncertainty_or_missing"),
    (("course_accuracy_degrees", -1), "course_uncertainty_or_missing"),
])
def test_course_quality_gate(change, reason):
    source = row("a")
    source["manifest"]["vehicle_position"][change[0]] = change[1]
    selected, reasons = m.select_rays([source], policy())
    assert not selected and reasons == {reason: 1}


def test_timing_gate_uses_actual_timestamps_and_orientation_is_explicit():
    stale = row("stale", captured=2.001, fix=0)
    stale["manifest"]["vehicle_position"]["frame_fix_delta_ms"] = 0
    unsupported = row("orientation")
    unsupported["manifest"]["orientation_version"] = "rotated-or-unknown"
    boundary = row("inclusive", captured=2, fix=0, course_accuracy=30)
    selected, reasons = m.select_rays([stale, unsupported, boundary], policy())
    assert [r["crop_id"] for _, r in selected] == ["inclusive"]
    assert reasons == {"frame_fix_alignment": 1, "unsupported_orientation": 1}


def test_duplicate_fix_and_duplicate_source_frame_never_supply_extra_rays():
    a = row("a", captured=0)
    same_fix = row("same-fix", captured=.5, fix=0)
    same_frame = row("same-frame", en=(1, 0), captured=1)
    same_frame["manifest"]["source_upright_sha256"] = a["manifest"]["source_upright_sha256"]
    selected, reasons = m.select_rays([same_frame, same_fix, a], policy())
    assert [r["crop_id"] for _, r in selected] == ["a"]
    assert reasons == {"repeated_position_fix_or_source_frame": 2}


def test_frame_identity_is_global_within_session_but_not_between_sessions():
    a, b = row("a"), row("b")
    b["manifest"]["source_upright_sha256"] = a["manifest"]["source_upright_sha256"]
    assert m.source_frame_id(a) == m.source_frame_id(b)
    b["observation"]["collection_session_id"] = "another-session"
    assert m.source_frame_id(a) != m.source_frame_id(b)


def test_future_interpolation_accounts_for_acceleration_and_all_accuracy_sources():
    capture = row("capture", captured=1, fix=0, accuracy=2)
    left_duplicate = row("left-duplicate", captured=0, fix=0, accuracy=9, observation="support-left")
    future = row("future", en=(20, 0), captured=2, fix=2, accuracy=2, observation="support-right")
    future_duplicate = row("future-duplicate", en=(20, 0), captured=2, fix=2, accuracy=6, observation="support-right2")
    sources = [capture, left_duplicate, future, future_duplicate]
    en, error, provenance, support = m.capture_pose(capture, m.build_tracks(sources), ORIGIN, policy()["position_model"])
    assert en == pytest.approx([10, 0])
    assert error == pytest.approx(20)  # 2*(.5*9+.5*6) +10*2²/8
    assert provenance["method"] == "offline_bracketed_linear_interpolation"
    assert provenance["error_is_declared_sensitivity_bound_not_measured_accuracy"] is True
    assert keys(support) >= keys(sources)
    assert set(map(tuple, provenance["support_keys"])) >= keys(sources)


def test_exact_fix_time_retains_every_duplicate_accuracy_contributor():
    capture = row("a", accuracy=1)
    duplicate = row("z", accuracy=8, observation="support")
    _, error, provenance, support = m.capture_pose(capture, m.build_tracks([capture, duplicate]), ORIGIN, policy()["position_model"])
    assert error == 16
    assert provenance["method"] == "exact_recorded_fix_time"
    assert keys(support) == keys([capture, duplicate])


def test_conflicting_same_time_fixes_are_not_interpolated_or_hidden_dependencies():
    capture = row("capture", captured=1, fix=0)
    conflict = row("conflict", en=(100, 0), captured=0, fix=0, observation="conflicting-support")
    future = row("future", en=(20, 0), captured=2, fix=2, observation="support")
    en, error, provenance, support = m.capture_pose(capture, m.build_tracks([capture, conflict, future]), ORIGIN, policy()["position_model"])
    assert provenance["method"] == "recorded_fix_with_declared_capture_motion_envelope"
    assert en == pytest.approx([0, 0])
    assert error == 64
    assert m.key(conflict) in keys(support)  # its rejection changed the chosen reconstruction


def test_interpolation_does_not_cross_session_or_bridge_an_excessive_gap():
    capture = row("capture", captured=1, fix=0)
    other_session = row("other", en=(20, 0), captured=2, session="other")
    late = row("late", en=(40, 0), captured=4)
    en, error, provenance, support = m.capture_pose(capture, m.build_tracks([capture, other_session, late]), ORIGIN, policy()["position_model"])
    assert en == pytest.approx([0, 0]) and error == 64
    assert provenance["method"] == "recorded_fix_with_declared_capture_motion_envelope"
    assert m.key(other_session) not in keys(support)


@pytest.mark.parametrize("answer", [False, None, 1, {"eligible": False}, {"eligible": True}])
def test_source_boundary_requires_exact_affirmative_validator_result(answer):
    with pytest.raises(ValueError):
        m.run([row("a")], graph(), policy(), lambda _: answer)


def test_validator_exception_and_replay_policy_fail_before_computation(monkeypatch):
    def forbidden(*_args):
        raise AssertionError("computation after failed source qualification")
    monkeypatch.setattr(m, "build_tracks", forbidden)
    def reject(_row):
        raise ValueError("replay source rejected")
    with pytest.raises(ValueError, match="replay"):
        m.run([row("a")], graph(), policy(), reject)
    p = policy()
    p["source_policy"] = "archive-replay"
    with pytest.raises(ValueError, match="live_only"):
        m.run([row("a")], graph(), p, lambda _: True)


def test_duplicate_crop_identity_rejected_before_model_work():
    a = row("a")
    with pytest.raises(ValueError, match="duplicate_crop_identity"):
        m.run([a, deepcopy(a)], graph(), policy(), lambda _: True)


def test_singleton_has_explicit_fast_path_and_never_queries_geometry(monkeypatch):
    def forbidden(*_args):
        raise AssertionError("single ray cannot support geometry or triangulation")
    monkeypatch.setattr(m, "candidate_graph", forbidden)
    monkeypatch.setattr(m, "triangulate", forbidden)
    result = m.run([row("a")], graph(), policy(), lambda _: True)
    assert result["groups"][0]["status"] == "underconstrained"
    assert result["groups"][0]["scenarios"] == []


@pytest.mark.parametrize("points,course", [([[-10, 0], [0, 0], [0, 10]], 90), ([[-10, 0], [10, 0]], 0)])
def test_ambiguous_tangent_and_right_angle_course_tie_do_not_invent_direction(points, course):
    g = {"source": {"sha256": "a" * 64}, "roads": [{"way_id": "1", "points_en_m": points}]}
    result = m.travelled_path([(row("a", course=course), [0, 0], 5)], g)
    assert result["direction_by_way"] == {"1": "unknown"}
    assert result["captures"][0]["nearest"]["direction"] == "unknown"
    assert "hypothesis" in result["basis"]


def test_nearest_path_keeps_parallel_alternatives_without_phone_match_claim():
    g = {"source": {"sha256": "a" * 64}, "roads": [
        {"way_id": "1", "points_en_m": [[-10, 0], [10, 0]]},
        {"way_id": "2", "points_en_m": [[-10, 2], [10, 2]]}]}
    result = m.travelled_path([(row("a", course=90), [0, 0], 5)], g)
    assert result["captures"][0]["nearest"]["way_id"] == "1"
    assert len(result["captures"][0]["alternatives_within_nominal_position_envelope"]) == 2
    assert result["basis"] == "offline_nominal_nearest_segment_hypothesis_not_phone_match"


def test_run_is_order_independent_and_retains_all_twelve_camera_scenarios():
    rows = [row("a", (-5, 0), captured=0), row("b", (5, 0), captured=1),
            row("singleton", (0, 20), captured=4, observation="another")]
    before = deepcopy(rows)
    expected = m.run(rows, graph(), policy(), lambda _: True)
    for ordering in permutations(rows):
        assert m.run(list(ordering), graph(), policy(), lambda _: True) == expected
    multi = next(r for r in expected["groups"] if r["selected_rays"] == 2)
    assert len(multi["scenarios"]) == 12
    assert multi["status"] == "estimated"
    assert expected["training_eligible"] is False and expected["acceptance_eligible"] is False
    assert rows == before


def test_held_course_hypothesis_and_signed_age_are_visible_not_verified_heading():
    rows = [row("a", (-5, 0), captured=.25, fix=0), row("b", (5, 0), captured=1.25, fix=1)]
    result = m.run(rows, graph(), policy(), lambda _: True)
    heading = result["groups"][0]["capture_heading_hypothesis"]
    assert heading["method"] == "hold_recorded_fix_course_constant_until_capture"
    assert heading["capture_time_heading_error_bound_verified"] is False
    assert heading["turn_between_fix_and_capture_is_not_measured"] is True
    assert len(heading["rays"]) == 2
    assert {r["signed_frame_fix_delta_seconds"] for r in heading["rays"]} == {.25}


def test_frame_projection_round_trip_preserves_declared_local_coordinates():
    for en in [[0, 0], [100, -80], [-1000, 2000]]:
        assert m.local_en(m.frame_position(en, ORIGIN), ORIGIN) == pytest.approx(en, abs=1e-8)
