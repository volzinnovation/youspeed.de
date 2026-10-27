from copy import deepcopy
from itertools import permutations
import math

import pytest

from scripts.tsr.collection.sign_identity_proposals import EARTH_RADIUS_M, propose_identities


def descriptor(identity, north_m=0, *, way="9007199254740993", code="274", value=80):
    return {"group_id": identity, "classification_key": {"country": "DE", "code": code, "value": value},
            "candidate_lat_lon": [math.degrees(north_m / EARTH_RADIUS_M), 0],
            "uncertainty_diameter_m": 10, "all_camera_scenarios_estimated": True,
            "all_regions_bounded": True, "nominal_way_id": way,
            "way_proposal_stable_across_scenarios": True, "source_frame_ids": ["frame-" + identity]}


def test_conditional_proposal_hash_binds_contents_and_does_not_promote_truth():
    rows = [descriptor("a"), descriptor("b", 10)]
    before = deepcopy(rows)
    result = propose_identities(rows)
    proposal = result["proposals"][0]
    assert proposal["member_group_ids"] == ["a", "b"]
    assert proposal["status"] == "conditional_inferred"
    assert len(proposal["proposal_id"]) == 64
    assert proposal["nominal_way_id"] == "9007199254740993"
    assert proposal["max_pair_distance_m"] == pytest.approx(10)
    assert not proposal["reviewed"] and not proposal["proves_physical_identity"]
    assert not proposal["publish_eligible"] and not result["training_eligible"]
    assert rows == before
    rows[1]["candidate_lat_lon"][0] += 1e-7
    assert propose_identities(rows)["proposals"][0]["proposal_id"] != proposal["proposal_id"]


def test_complete_link_never_chains_close_neighbours_into_wide_cluster():
    rows = [descriptor("a", 0), descriptor("b", 15), descriptor("c", 30)]
    result = propose_identities(rows)
    assert [p["member_group_ids"] for p in result["proposals"]] == [["a", "b"]]
    assert result["unmerged_groups"] == [{"group_id": "c", "reason": "complete_link_partition_prevents_merge"}]
    assert result["blocked_pairs"][0]["member_group_ids"] == ["a", "c"]
    assert result["blocked_pairs"][0]["reasons"] == ["pair_distance_exceeds_limit"]
    for order in permutations(rows):
        assert propose_identities(list(order)) == result


def test_all_cross_member_pairs_checked_when_merging_clusters():
    result = propose_identities([descriptor("a", 0), descriptor("b", 4), descriptor("c", 18), descriptor("d", 22)])
    assert [p["member_group_ids"] for p in result["proposals"]] == [["a", "b"], ["c", "d"]]
    assert not any(len(p["member_group_ids"]) == 4 for p in result["proposals"])


def test_shared_frame_blocks_merge_even_for_identical_class_road_and_position():
    rows = [descriptor("a"), descriptor("b")]
    rows[1]["source_frame_ids"].append("frame-a")
    result = propose_identities(rows)
    assert result["proposals"] == []
    assert result["blocked_pairs"][0]["reasons"] == ["shared_source_frame_possible_co_visible_signs"]
    assert len(result["unmerged_groups"]) == 2


@pytest.mark.parametrize("change,reason", [
    ({"classification_key": None}, "classification_unavailable"),
    ({"classification_key": {"country": "de", "code": "274", "value": 80}}, "classification_invalid"),
    ({"classification_key": {"country": "DE", "code": "274", "value": True}}, "classification_invalid"),
    ({"classification_key": {"country": "DE", "code": "274", "value": 10 ** 400}}, "classification_invalid"),
    ({"candidate_lat_lon": None}, "candidate_position_unavailable"),
    ({"candidate_lat_lon": [float("nan"), 0]}, "candidate_position_invalid"),
    ({"candidate_lat_lon": [91, 0]}, "candidate_position_invalid"),
    ({"uncertainty_diameter_m": None}, "uncertainty_diameter_unavailable"),
    ({"uncertainty_diameter_m": 30.001}, "uncertainty_region_too_large"),
    ({"uncertainty_diameter_m": -1}, "uncertainty_diameter_invalid"),
    ({"all_camera_scenarios_estimated": False}, "not_all_camera_scenarios_estimated"),
    ({"all_camera_scenarios_estimated": 1}, "not_all_camera_scenarios_estimated"),
    ({"all_regions_bounded": False}, "not_all_regions_bounded"),
    ({"way_proposal_stable_across_scenarios": False}, "road_hypothesis_not_stable"),
    ({"nominal_way_id": "9223372036854775808"}, "road_hypothesis_unavailable_or_invalid"),
    ({"nominal_way_id": "01"}, "road_hypothesis_unavailable_or_invalid"),
    ({"nominal_way_id": 123}, "road_hypothesis_unavailable_or_invalid"),
    ({"source_frame_ids": []}, "source_frame_identity_unavailable_or_invalid"),
    ({"source_frame_ids": ["x", "x"]}, "source_frame_identity_unavailable_or_invalid"),
])
def test_uncertain_or_invalid_descriptor_never_forced_into_merge(change, reason):
    bad = descriptor("bad") | change
    result = propose_identities([bad, descriptor("good")])
    assert result["proposals"] == []
    assert result["excluded_groups"] == [{"group_id": "bad", "reasons": [reason]}]
    assert result["unmerged_groups"][0]["group_id"] == "good"


@pytest.mark.parametrize("field,value,reason", [
    ("classification_key", {"country": "FR", "code": "274", "value": 80}, "classification_mismatch"),
    ("classification_key", {"country": "DE", "code": "275", "value": 80}, "classification_mismatch"),
    ("classification_key", {"country": "DE", "code": "274", "value": 60}, "classification_mismatch"),
    ("nominal_way_id", "9007199254740994", "road_hypothesis_mismatch"),
])
def test_class_and_exact_large_way_identity_are_independent_pair_gates(field, value, reason):
    rows = [descriptor("a"), descriptor("b", 1)]
    rows[1][field] = value
    result = propose_identities(rows)
    assert result["proposals"] == []
    assert result["blocked_pairs"][0]["reasons"] == [reason]


def test_frame_order_and_integral_numeric_class_values_do_not_change_identity_hash():
    rows = [descriptor("a"), descriptor("b", 1)]
    rows[0]["source_frame_ids"] += ["later-a", "earlier-a"]
    expected = propose_identities(rows)
    rows[0]["source_frame_ids"].reverse()
    rows[1]["classification_key"]["value"] = 80.0
    assert propose_identities(rows) == expected


def test_null_value_class_and_diameter_boundary_are_eligible_but_far_pair_is_not():
    a, b, c = descriptor("a", value=None), descriptor("b", 19.999, value=None), descriptor("c", 40, value=None)
    a["uncertainty_diameter_m"] = 30
    result = propose_identities([a, b, c])
    assert result["counts"]["eligible_groups"] == 3
    assert result["proposals"][0]["member_group_ids"] == ["a", "b"]


def test_numeric_signed_zero_is_the_same_normalized_class_value():
    rows = [descriptor("a", value=0), descriptor("b", 1, value=0)]
    expected = propose_identities(rows)
    rows[0]["classification_key"]["value"] = -0.0
    assert propose_identities(rows) == expected


def test_empty_population_singleton_duplicates_and_caps():
    assert propose_identities([])["counts"]["input_groups"] == 0
    assert propose_identities([descriptor("one")])["proposals"] == []
    with pytest.raises(ValueError, match="duplicate_group"):
        propose_identities([descriptor("x"), descriptor("x")])
    with pytest.raises(ValueError, match="eligible_population_cap"):
        propose_identities([descriptor(str(i)) for i in range(513)])
    with pytest.raises(ValueError, match="descriptor_population_cap"):
        propose_identities([{}] * 4097)


def test_settings_cannot_silently_disable_required_compatibility():
    defaults = propose_identities([])["settings"]
    for key in ("requires_compatible_classification", "requires_consistent_road_hypothesis"):
        with pytest.raises(ValueError, match="cannot_be_disabled"):
            propose_identities([], defaults | {key: False})
    with pytest.raises(ValueError, match="exact_identity_settings"):
        propose_identities([], {"max_pair_distance_m": 20})
    with pytest.raises(ValueError, match="invalid_identity_distance"):
        propose_identities([], defaults | {"max_pair_distance_m": float("nan")})
