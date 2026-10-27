"""Synthetic qualification of explicit optical bearings, never GPS-course rays."""

from copy import deepcopy
from itertools import permutations
import math

import pytest

from scripts.tsr.collection.triangulate_sign_position import triangulate


PROVENANCE = {"reference": "synthetic-fixture-v1", "sha256": "a" * 64}


def ray(identity, position, target=(5, 30), *, bearing=None, angular=1.0, error=0.2):
    if bearing is None:
        bearing = math.degrees(math.atan2(target[0] - position[0], target[1] - position[1])) % 360
    return {
        "sighting_id": identity, "source_frame_id": "frame-" + identity,
        "position_fix_id": "fix-" + identity, "source_kind": "synthetic",
        "captured_at": "2026-10-09T12:00:00Z", "fix_at": "2026-10-09T12:00:00Z",
        "ray_at": "2026-10-09T12:00:00Z", "position_en_m": list(position),
        "horizontal_error_bound_m": error, "position_error_covers_capture_time": True,
        "optical_ray_bearing_degrees": bearing, "angular_error_bound_degrees": angular,
        "bearing_basis": "calibrated_optical_ray",
        "source_provenance": dict(PROVENANCE), "position_provenance": dict(PROVENANCE),
        "bearing_provenance": dict(PROVENANCE),
    }


def group(*rays):
    return {"schema_version": 1,
            "local_frame": {"frame_id": "synthetic-ENU", "axes": "east_north", "units": "metres",
                            "provenance": dict(PROVENANCE)},
            "association": {"group_id": "synthetic-sign", "basis": "hypothesis",
                            "provenance": dict(PROVENANCE)}, "rays": list(rays)}


def inside(point, polygon, epsilon=1e-7):
    """Independent convex containment by cross-product sign."""
    products = []
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        products.append((b[0] - a[0]) * (point[1] - a[1]) - (b[1] - a[1]) * (point[0] - a[0]))
    return all(v >= -epsilon for v in products) or all(v <= epsilon for v in products)


def test_exact_intersection_bound_region_and_no_truth_promotion():
    data = group(ray("a", (0, 0)), ray("b", (10, 0)))
    before = deepcopy(data)
    result = triangulate(data)
    assert result["status"] == "estimated"
    assert result["estimate_en_m"] == pytest.approx([5, 30], abs=1e-9)
    assert result["feasible_region"]["bounds_known"]
    assert not result["feasible_region"]["range_clipped"]
    assert inside([5, 30], result["feasible_region"]["vertices_en_m"])
    assert result["diagnostics"]["two_ray_outlier_check_unavailable"]
    assert result["statistical_confidence"] is None
    assert not result["proves_physical_sign_identity"]
    assert not result["proves_sign_to_road_applicability"]
    assert data == before


def test_explicit_forward_camera_hypothesis_is_useful_but_stays_conditional():
    data = group(ray("a", (0, 0)), ray("b", (10, 0)))
    for r in data["rays"]:
        r["bearing_basis"] = "explicit_camera_hypothesis"
        r["source_kind"] = "qualified_live_crop"
    result = triangulate(data)
    assert result["status"] == "estimated"
    assert result["conditional_on_camera_hypothesis"]
    assert result["conditional_on_association_hypothesis"]
    assert result["bearing_bases"] == ["explicit_camera_hypothesis"]


def test_noisy_multi_ray_fit_is_order_independent_and_local_translation_invariant():
    rays = [ray("a", (0, 0)), ray("b", (10, 0)), ray("c", (-10, 5))]
    rays[0]["optical_ray_bearing_degrees"] += 0.2
    expected = triangulate(group(*rays))
    assert expected["status"] == "estimated"
    assert math.dist(expected["estimate_en_m"], [5, 30]) < 0.5
    for permuted in permutations(rays):
        assert triangulate(group(*permuted)) == expected
    moved = deepcopy(rays)
    for r in moved:
        r["position_en_m"] = [v + 90000 for v in r["position_en_m"]]
    translated = triangulate(group(*moved))
    assert translated["status"] == "estimated"
    assert translated["estimate_en_m"] == pytest.approx([v + 90000 for v in expected["estimate_en_m"]])


def test_majority_discards_outlier_and_retains_its_diagnostics():
    data = group(ray("a", (0, 0)), ray("b", (10, 0)), ray("c", (-10, 5)), ray("d", (20, 0), bearing=90))
    result = triangulate(data)
    assert result["status"] == "estimated"
    assert result["estimate_en_m"] == pytest.approx([5, 30])
    assert result["diagnostics"]["outlier_count"] == 1
    assert result["feasible_region"]["conditional_on_inlier_ids"] == ["a", "b", "c"]
    assert result["diagnostics"]["residuals"][-1]["reason"] == "behind_camera"


def test_equal_consensus_populations_are_ambiguous_not_arbitrarily_chosen():
    result = triangulate(group(ray("a", (0, 0), bearing=0, angular=0.01, error=0.01),
                               ray("b", (10, 0), bearing=330, angular=0.01, error=0.01),
                               ray("c", (-10, 0), bearing=45, angular=0.01, error=0.01)))
    assert result["status"] == "ambiguous"
    assert result["estimate_en_m"] is None
    assert len(result["diagnostics"]["competing_consensus_sets"]) == 3


@pytest.mark.parametrize("rays,status", [
    ([], "underconstrained"),
    ([ray("a", (0, 0))], "underconstrained"),
    ([ray("a", (0, 0), bearing=0), ray("b", (10, 0), bearing=0)], "degenerate"),
    ([ray("a", (0, 0)), ray("b", (0.01, 0))], "degenerate"),
    ([ray("a", (0, 0), target=(5, 30), bearing=180 + math.degrees(math.atan2(5, 30))),
      ray("b", (10, 0), target=(5, 30), bearing=180 - math.degrees(math.atan2(5, 30)))], "behind_camera"),
    ([ray("a", (0, 0), target=(0, 1000)), ray("b", (100, 0), target=(0, 1000))], "underconstrained"),
])
def test_underconstrained_and_bad_geometry_never_emit_a_position(rays, status):
    result = triangulate(group(*rays))
    assert result["status"] == status
    assert result["estimate_en_m"] is None
    assert result["feasible_region"] is None


def test_wraparound_north_and_large_uncertainty_range_clipping():
    data = group(ray("a", (-5, 0), target=(0, 100), angular=10, error=10),
                 ray("b", (5, 0), target=(0, 100), angular=10, error=10))
    result = triangulate(data)
    assert result["status"] == "estimated"
    region = result["feasible_region"]
    assert region["range_clipped"] and not region["bounds_known"]
    assert inside([0, 100], region["vertices_en_m"])
    assert region["statistical_confidence"] is None


def test_declared_error_expansion_widens_region_without_confidence_interpretation():
    small = group(ray("a", (0, 0)), ray("b", (10, 0)))
    large = deepcopy(small)
    for r in large["rays"]:
        r["horizontal_error_bound_m"] = 1
        r["angular_error_bound_degrees"] = 2
    a, b = triangulate(small), triangulate(large)
    assert b["feasible_region"]["area_m2"] > a["feasible_region"]["area_m2"]
    assert all(inside(p, b["feasible_region"]["vertices_en_m"]) for p in a["feasible_region"]["vertices_en_m"])


def test_expanded_wedges_contain_true_point_for_bounded_origin_and_bearing_errors():
    target = (5, 30)
    # True origins lie on the declared one-metre disks; optical errors are 2°.
    for heading in range(0, 360, 30):
        offset = (math.cos(math.radians(heading)), math.sin(math.radians(heading)))
        rays = []
        for i, true_origin in enumerate(((0, 0), (10, 0), (-10, 5))):
            r = ray(str(i), true_origin, target=target, error=1, angular=2)
            r["position_en_m"] = [true_origin[k] + offset[k] for k in (0, 1)]
            r["optical_ray_bearing_degrees"] = (r["optical_ray_bearing_degrees"] + 2) % 360
            rays.append(r)
        result = triangulate(group(*rays))
        assert result["status"] == "estimated"
        assert inside(target, result["feasible_region"]["vertices_en_m"])


@pytest.mark.parametrize("key,value", [
    ("source_kind", "archive_replay"), ("bearing_basis", "gps_course"),
    ("position_error_covers_capture_time", False), ("position_error_covers_capture_time", 1),
    ("ray_at", "2026-10-09T12:00:01Z"), ("captured_at", "2026-10-09T12:00:00+00:00"),
    ("fix_at", "2026-10-07T12:00:00Z"), ("fix_at", "2026-99-09T12:00:00Z"),
    ("optical_ray_bearing_degrees", float("nan")), ("optical_ray_bearing_degrees", True),
    ("optical_ray_bearing_degrees", 360), ("angular_error_bound_degrees", -1),
    ("angular_error_bound_degrees", 90), ("horizontal_error_bound_m", float("inf")),
    ("horizontal_error_bound_m", -1), ("position_en_m", [0]),
    ("position_en_m", [0, float("nan")]), ("source_provenance", {"reference": "unbound"}),
    ("source_provenance", {"reference": "x", "sha256": "A" * 64}),
])
def test_malformed_or_unqualified_inputs_fail_closed(key, value):
    data = group(ray("a", (0, 0)), ray("b", (10, 0)))
    data["rays"][0][key] = value
    result = triangulate(data)
    assert result["status"] == "invalid_input"
    assert result["estimate_en_m"] is None


@pytest.mark.parametrize("key", ["sighting_id", "source_frame_id", "position_fix_id"])
def test_repeated_evidence_cannot_manufacture_support(key):
    data = group(ray("a", (0, 0)), ray("b", (10, 0)))
    data["rays"][1][key] = data["rays"][0][key]
    assert triangulate(data)["status"] == "invalid_input"


def test_relabelled_same_fix_is_rejected_and_synthetic_cannot_mix_with_live():
    assert triangulate(group(ray("a", (0, 0)), ray("b", (0, 0))))["status"] == "invalid_input"
    data = group(ray("a", (0, 0)), ray("b", (10, 0)))
    data["rays"][1]["source_kind"] = "qualified_live_crop"
    assert triangulate(data)["status"] == "invalid_input"


def test_fix_age_is_diagnostic_only_when_capture_time_bound_explicitly_covers_it():
    data = group(ray("a", (0, 0)), ray("b", (10, 0)))
    data["rays"][0]["fix_at"] = "2026-10-09T11:59:55Z"
    result = triangulate(data)
    assert result["status"] == "estimated"
    assert result["diagnostics"]["residuals"][0]["frame_fix_delta_ms"] == 5000


def test_strict_schema_and_work_bounds():
    data = group(ray("a", (0, 0)), ray("b", (10, 0)))
    with_course = deepcopy(data)
    with_course["rays"][0]["course_degrees"] = 30
    assert triangulate(with_course)["status"] == "invalid_input"
    assert triangulate(data, {"invented_threshold": 1})["status"] == "invalid_input"
    assert triangulate(data, {"max_refine_iterations": True})["status"] == "invalid_input"
    assert triangulate(data, {"max_range_m": float("nan")})["status"] == "invalid_input"
    assert triangulate(group(*[ray(str(i), (i * 3, 0)) for i in range(65)]))["status"] == "invalid_input"


def test_conditioning_and_iteration_caps_fail_closed():
    data = group(ray("a", (0, 0)), ray("b", (10, 0)), ray("c", (-10, 5)))
    data["rays"][0]["optical_ray_bearing_degrees"] += 0.5
    assert triangulate(data, {"max_condition_number": 1})["status"] == "inconsistent"
    assert triangulate(data, {"max_refine_iterations": 1})["status"] == "inconsistent"
