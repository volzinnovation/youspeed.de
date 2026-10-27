from copy import deepcopy
import hashlib
import json
import math

import pytest

from scripts.tsr.collection.localized_sign_identities import build_identity_report, canonical_classification
from scripts.tsr.collection.sign_identity_proposals import DEFAULT_SETTINGS


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def policy():
    return {"source_policy": "live-crops-only-v1", "acceptance_eligible": False, "training_eligible": False,
            "camera_assumptions": {"horizontal_fov_scenarios_degrees": [45, 60, 75, 90],
                                   "mount_yaw_scenarios_degrees": [-15, 0, 15],
                                   "nominal_scenario": {"horizontal_fov_degrees": 60, "mount_yaw_degrees": 0}},
            "physical_identity": dict(DEFAULT_SETTINGS)}


def group(identity="a", lat=48):
    frame = {"frame_id": identity, "axes": "east_north", "units": "metres",
             "provenance": {"reference": "synthetic-origin", "sha256": "a" * 64}}
    result = {"group_id": identity, "classification": {"country": "DE", "canonical_code": "274", "value": 80,
                                                        "model_label": "ignored", "family": "ignored"},
              "source_frame_ids": ["frame-" + identity], "local_frame": frame, "origin_lat_lon": [lat, 8],
              "nominal_position_lat_lon": [lat, 8], "status": "estimated", "scenarios": []}
    for fov in [45, 60, 75, 90]:
        for yaw in [-15, 0, 15]:
            result["scenarios"].append({
                "camera": {"horizontal_fov_degrees": fov, "mount_yaw_degrees": yaw},
                "position": {"status": "estimated", "local_frame": deepcopy(frame), "estimate_en_m": [0, 0],
                             "feasible_region": {"bounds_known": True, "range_clipped": False,
                                                 "vertices_en_m": [[-2, -2], [2, -2], [2, 2], [-2, 2]]}},
                "road_association": {"local_frame": deepcopy(frame), "map_source": {"sha256": "b" * 64},
                                     "candidate_population_complete_for_region": False,
                                     "roads": [{"way_id": "9007199254740993", "candidate": True,
                                                "nominal_projection": {"distance_m": 3}}]}})
    return result


def report(*groups, configuration=None):
    configuration = configuration or policy()
    return {"schema_version": 1, "protocol_sha256": digest(configuration), "groups": list(groups)}


def test_all_twelve_regions_feed_union_diameter_and_conditional_identity_core():
    a, b = group(), group("b", lat=48.00005)
    result = build_identity_report(report(a, b), policy())
    assert result["expected_camera_scenarios"] == 12
    descriptor = result["descriptors"][0]
    assert descriptor["uncertainty_diameter_m"] == pytest.approx(math.sqrt(32))
    assert descriptor["candidate_lat_lon"] == [48, 8]
    assert descriptor["all_camera_scenarios_estimated"] and descriptor["all_regions_bounded"]
    assert descriptor["way_proposal_stable_across_scenarios"]
    assert result["identity_result"]["proposals"][0]["member_group_ids"] == ["a", "b"]
    assert not result["proves_physical_identity"] and not result["publish_eligible"]
    assert result["map_source_sha256"] == "b" * 64


def test_wide_feasible_region_cannot_hide_behind_identical_fitted_points():
    g = group()
    g["scenarios"][0]["position"]["feasible_region"]["vertices_en_m"] = [[-50, -2], [50, -2], [50, 2], [-50, 2]]
    result = build_identity_report(report(g), policy())
    assert result["descriptors"][0]["uncertainty_diameter_m"] > 100
    assert result["exclusion_reason_counts"] == {"uncertainty_region_too_large": 1}


def test_displaced_regions_expand_union_even_when_individual_polygons_are_small():
    g = group()
    g["scenarios"][0]["position"]["feasible_region"]["vertices_en_m"] = [[30, -2], [34, -2], [34, 2], [30, 2]]
    result = build_identity_report(report(g), policy())
    assert result["descriptors"][0]["uncertainty_diameter_m"] == pytest.approx(math.sqrt(36**2 + 4**2))


@pytest.mark.parametrize("mode", ["missing", "duplicate", "extra", "wrong_camera"])
def test_exact_scenario_population_required(mode):
    g = group()
    if mode == "missing":
        g["scenarios"].pop()
    elif mode == "duplicate":
        g["scenarios"][-1] = deepcopy(g["scenarios"][0])
    elif mode == "extra":
        g["scenarios"].append(deepcopy(g["scenarios"][0]))
    else:
        g["scenarios"][0]["camera"]["horizontal_fov_degrees"] = 46
    result = build_identity_report(report(g), policy())
    assert not result["descriptors"][0]["all_camera_scenarios_estimated"]
    assert result["adapter_reason_counts"]["camera_scenario_population_incomplete_or_duplicated"] == 1
    assert result["identity_result"]["proposals"] == []


def test_one_failed_or_wrong_frame_scenario_cannot_borrow_other_scenarios():
    g = group()
    g["scenarios"][0]["position"]["status"] = "ambiguous"
    a = build_identity_report(report(g), policy())
    assert not a["descriptors"][0]["all_camera_scenarios_estimated"]
    assert a["descriptors"][0]["uncertainty_diameter_m"] is None
    g = group()
    g["scenarios"][0]["position"]["local_frame"]["frame_id"] = "another-origin"
    b = build_identity_report(report(g), policy())
    assert b["adapter_reason_counts"]["scenario_estimate_frame_or_point_invalid"] == 1


@pytest.mark.parametrize("change", [
    {"bounds_known": False}, {"range_clipped": True}, {"vertices_en_m": []},
    {"vertices_en_m": [[0, 0], [1, 0], [2, 0]]},
    {"vertices_en_m": [[-1, -1], [1, 1], [-1, 1], [1, -1]]},
])
def test_unbounded_or_bad_region_blocks_identity_uncertainty_claim(change):
    g = group()
    g["scenarios"][0]["position"]["feasible_region"].update(change)
    result = build_identity_report(report(g), policy())
    assert not result["descriptors"][0]["all_regions_bounded"]
    assert result["descriptors"][0]["uncertainty_diameter_m"] is None


def test_nearest_road_is_computed_from_distance_not_input_order_and_ties_stay_uncertain():
    g = group()
    for s in g["scenarios"]:
        s["road_association"]["roads"].insert(0, {"way_id": "2", "candidate": True,
                                                 "nominal_projection": {"distance_m": 10}})
    a = build_identity_report(report(g), policy())
    assert a["descriptors"][0]["nominal_way_id"] == "9007199254740993"
    g["scenarios"][0]["road_association"]["roads"][0]["nominal_projection"]["distance_m"] = 3
    b = build_identity_report(report(g), policy())
    assert not b["descriptors"][0]["way_proposal_stable_across_scenarios"]
    assert b["adapter_reason_counts"]["nearest_enumerated_road_tied"] == 1


def test_different_way_across_scenarios_and_map_hashes_across_groups_block_merge():
    g = group()
    g["scenarios"][0]["road_association"]["roads"][0]["way_id"] = "2"
    a = build_identity_report(report(g), policy())
    assert not a["descriptors"][0]["way_proposal_stable_across_scenarios"]
    x, y = group("x"), group("y")
    for s in y["scenarios"]:
        s["road_association"]["map_source"]["sha256"] = "c" * 64
    b = build_identity_report(report(x, y), policy())
    assert b["map_source_sha256"] is None
    assert b["adapter_reason_counts"]["report_contains_multiple_map_sources"] == 2
    assert b["identity_result"]["proposals"] == []


def test_map_hash_must_be_same_inside_each_group():
    g = group()
    g["scenarios"][0]["road_association"]["map_source"]["sha256"] = "c" * 64
    result = build_identity_report(report(g), policy())
    assert not result["descriptors"][0]["way_proposal_stable_across_scenarios"]
    assert result["adapter_reason_counts"]["camera_scenario_map_sources_missing_or_mismatched"] == 1


def test_report_map_hash_and_truncated_nearest_summary_are_explicitly_bound():
    g = group()
    for s in g["scenarios"]:
        s["road_association"].update(omitted_road_records=100,
            summary_scope="nearest_five_nominal_projections_full_supplied_graph_results_in_group_evidence")
        s["road_association"]["roads"][0]["candidate"] = False
    source = report(g)
    source["map_source_sha256"] = "b" * 64
    assert build_identity_report(source, policy())["descriptors"][0]["way_proposal_stable_across_scenarios"]
    source["map_source_sha256"] = "c" * 64
    assert not build_identity_report(source, policy())["descriptors"][0]["way_proposal_stable_across_scenarios"]
    source["map_source_sha256"] = "b" * 64
    g["scenarios"][0]["road_association"]["summary_scope"] = "arbitrary_first_five"
    assert not build_identity_report(source, policy())["descriptors"][0]["way_proposal_stable_across_scenarios"]


def test_legacy_live_classification_null_canonical_is_not_replaced_with_model_label():
    g = group()
    g["classification"].update(canonical_code=None, model_label="274", family="maximum_speed",
                               alternatives=[{"canonical_code": "274"}])
    result = build_identity_report(report(g), policy())
    assert result["descriptors"][0]["classification_key"] is None
    assert result["exclusion_reason_counts"] == {"classification_unavailable": 1}
    assert result["adapter_reason_counts"] == {"explicit_canonical_classification_unavailable": 1}


@pytest.mark.parametrize("classification", [None, {}, {"country": "unknown", "canonical_code": "274", "value": 80},
                                           {"country": "DE", "model_label": "274", "value": 80},
                                           {"country": "DE", "canonical_code": "274", "value": True},
                                           {"country": "DE", "canonical_code": "274"}])
def test_only_explicit_canonical_classification_is_accepted(classification):
    assert canonical_classification(classification) is None


def test_nominal_position_must_bind_nominal_en_point_and_projection_origin():
    g = group()
    g["nominal_position_lat_lon"] = [48.001, 8]
    result = build_identity_report(report(g), policy())
    assert result["descriptors"][0]["candidate_lat_lon"] is None
    assert result["adapter_reason_counts"]["nominal_position_missing_or_projection_mismatched"] == 1


def test_underconstrained_group_is_retained_with_explicit_exclusion_counts():
    g = {"group_id": "a", "source_frame_ids": ["frame-a"], "scenarios": [], "classification": None,
         "status": "underconstrained"}
    result = build_identity_report(report(g), policy())
    assert len(result["descriptors"]) == 1
    assert result["identity_result"]["counts"]["excluded_groups"] == 1
    assert result["exclusion_reason_counts"]["classification_unavailable"] == 1
    assert result["exclusion_reason_counts"]["not_all_camera_scenarios_estimated"] == 1


def test_protocol_binding_duplicate_group_and_input_immutability():
    source = report(group())
    before = deepcopy(source)
    build_identity_report(source, policy())
    assert source == before
    source["protocol_sha256"] = "0" * 64
    with pytest.raises(ValueError, match="protocol_mismatch"):
        build_identity_report(source, policy())
    with pytest.raises(ValueError, match="duplicate_localized"):
        build_identity_report(report(group(), group()), policy())
    wrong = policy()
    wrong["camera_assumptions"]["horizontal_fov_scenarios_degrees"] = [45, 60]
    with pytest.raises(ValueError, match="twelve"):
        build_identity_report(report(group(), configuration=wrong), wrong)
