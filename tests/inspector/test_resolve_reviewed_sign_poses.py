from copy import deepcopy
import math

from fiona.transform import transform, transform_geom
import pytest
from shapely.geometry import box, mapping

from scripts.inspector import resolve_reviewed_sign_poses as resolver
from scripts.tsr.collection.estimate_sign_poses import METRIC, WGS84, angle, project, subtract


ORIGIN = (458000, 5405000)


def observation(sequence, index, camera, target=(3, 54), *, scale=.6):
    point = tuple(origin + offset for origin, offset in zip(ORIGIN, camera))
    longitude, latitude = (axis[0] for axis in transform(METRIC, WGS84, [point[0]], [point[1]]))
    _, rotation = project([longitude], [latitude])[0]
    return {
        "annotation_id": f"{sequence}-{index}", "image_id": f"photo-{sequence}-{index}",
        "sequence_id": sequence, "sequence_rank": index,
        "captured_at": f"2026-11-10T12:00:0{3 * index}Z",
        "longitude": longitude, "latitude": latitude,
        "bearing_deg": (angle(subtract(target, camera)) - rotation) % 360,
        "bearing_error_deg": 12, "horizontal_error_m": 1.5,
        "camera_heading_deg": -rotation % 360,
        "angular_height_deg": math.degrees(2 * math.atan(scale / (2 * (target[1] - camera[1])))),
    }


def group():
    return {
        "id": "canonical", "sign_code": "DE:222", "proposal": None,
        "observations": [
            observation("a", 1, (0, 27)), observation("b", 0, (6, 2)),
            observation("a", 0, (0, 0)), observation("b", 1, (6, 25)),
        ],
        "benchmark_review": {
            "object_ground_truth_eligible": True, "identity_status": "reviewed_group",
            "pose_is_ground_truth": False, "position_note": "Old hypothesis withheld.",
        },
        "position_ground_truth": None, "azimuth_ground_truth_deg": None,
    }


def document(*groups):
    return {"groups": list(groups), "place": {
        "bounds_en_m": [ORIGIN[0] - 100, ORIGIN[1] - 100, ORIGIN[0] + 100, ORIGIN[1] + 100],
    }, "summary": {"source_snapshot_at": "2026-11-12T12:00:00Z"}}


def test_recovers_merged_primary_frames_without_mutation_or_claiming_truth():
    source = document(group())
    before = deepcopy(source)
    output, report = resolver.resolve_document(source)
    assert source == before
    assert report["resolved_group_ids"] == ["canonical"]
    result = output["groups"][0]
    proposal = result["proposal"]
    point, _ = project([proposal["longitude"]], [proposal["latitude"]])[0]
    assert point == pytest.approx((ORIGIN[0] + 3, ORIGIN[1] + 54), abs=.001)
    assert 0 < proposal["position_radius_m"] <= 40
    assert proposal["position_status"] == "adjacent_track_review"
    assert proposal["independent_sequence_count"] == 2
    assert result["position_ground_truth"] is None
    assert result["azimuth_ground_truth_deg"] is None
    assert result["benchmark_review"]["pose_is_ground_truth"] is False
    assert result["pose_resolution"]["previous_position_note"] == "Old hypothesis withheld."
    assert report["source_refresh_performed"] is False
    assert output["summary"]["position_status_counts"] == {"adjacent_track_review": 1}


def test_primary_and_follow_on_duplicates_have_one_vote_per_sequence():
    source = group()
    second = source["observations"].pop(0)
    source["follow_on_observations"] = [second, deepcopy(second)]
    anchors, continuation, details = resolver.rebuild_tracks(source)
    assert len(anchors) == len(continuation) == 2
    assert details["observation_count"] == 4
    assert [row["sequence_ranks"] for row in details["selected_tracks"]] == [[0, 1], [0, 1]]
    output, report = resolver.resolve_document(document(source))
    assert report["resolved_group_count"] == 1
    assert output["groups"][0]["proposal"]["support_count"] == 4


def test_conflicting_duplicate_measurements_are_not_selected_by_input_order():
    source = group()
    other = deepcopy(source["observations"][0])
    other["bearing_deg"] += 1
    source["follow_on_observations"] = [other]
    output, report = resolver.resolve_document(document(source))
    assert output["groups"][0]["proposal"] is None
    assert report["groups"][0]["rejected_observation_counts"]["conflicting_annotation_measurements"] == 1


@pytest.mark.parametrize("change", ["rank_gap", "missing_rank", "non_growing", "same_fix"])
def test_does_not_relax_existing_track_gates(change):
    source = group()
    first = next(row for row in source["observations"] if row["annotation_id"] == "a-0")
    second = next(row for row in source["observations"] if row["annotation_id"] == "a-1")
    if change == "rank_gap":
        second["sequence_rank"] = 3
    elif change == "missing_rank":
        second.pop("sequence_rank")
    elif change == "non_growing":
        second["angular_height_deg"] = first["angular_height_deg"]
    else:
        first["fix_id"] = second["fix_id"] = "shared-fix"
    output, report = resolver.resolve_document(document(source))
    assert output["groups"][0]["proposal"] is None
    assert report["unresolved_group_count"] == 1
    assert report["groups"][0]["adjacent_status"] == "insufficient_adjacent_sequences"


def test_other_same_class_box_prevents_ambiguous_follow_on_association():
    source = group()
    competing = deepcopy(source["observations"][0])
    competing["annotation_id"] = "other-sign-same-frame"
    other = {"id": "other", "sign_code": source["sign_code"], "proposal": None,
             "observations": [competing]}
    output, report = resolver.resolve_document(document(source, other))
    assert output["groups"][0]["proposal"] is None
    assert report["groups"][0]["rejected_observation_counts"]["ambiguous_next_frame"] == 1


def test_existing_estimates_and_excluded_mixed_identities_are_untouched():
    existing = group()
    existing["id"] = "existing"
    existing["proposal"] = {"position_status": "nominal_review", "longitude": 8.44,
                            "latitude": 48.8, "position_radius_m": None}
    excluded = group()
    excluded["id"] = "mixed"
    excluded["benchmark_review"].update(identity_status="mixed_group_excluded",
                                        object_ground_truth_eligible=False)
    source = document(existing, excluded)
    output, report = resolver.resolve_document(source)
    assert output["groups"] == source["groups"]
    assert report["attempted_group_count"] == 0
    assert report["excluded_group_ids"] == ["mixed"]
    assert report["retained_existing_pose_group_ids"] == ["existing"]


def test_gallery_only_mobile_cannot_resurrect_a_withheld_proposal():
    source = group()
    source["observations"] = source["observations"][1:2]
    source["challenged_proposal"] = {"longitude": 8.44, "latitude": 48.8}
    source["mobile_observations"] = [{"gallery_only": True, "evidence_id": "gallery"}]
    source["mobile_refinement"] = {"status": "refined", "proposal": source["challenged_proposal"]}
    output, report = resolver.resolve_document(document(source))
    assert output["groups"][0]["proposal"] is None
    assert output["groups"][0]["challenged_proposal"] == source["challenged_proposal"]
    assert report["groups"][0]["mobile_evidence_ids"] == []
    assert output["groups"][0]["mobile_refinement"]["status"] == "insufficient_distinct_views"


def test_existing_radius_gate_rejects_wide_reconstructed_tracks():
    source = group()
    for row in source["observations"]:
        row["horizontal_error_m"] = 5
    output, report = resolver.resolve_document(document(source))
    assert output["groups"][0]["proposal"] is None
    assert report["groups"][0]["adjacent_status"] == "adjacent_position_too_wide"
    assert report["groups"][0]["adjacent_diagnostics"]["conditional_position_radius_m"] > 40


@pytest.mark.parametrize("candidate_ids", [["canonical"], ["canonical", "other"]])
def test_mobile_fit_requires_the_existing_unambiguous_association_gate(candidate_ids):
    source = group()
    source["observations"] = [observation("a", 0, (0, 0)), observation("b", 0, (30, 0))]
    for row in source["observations"]:
        row.update(bearing_error_deg=2, horizontal_error_m=.5)
    mobile = observation("mobile", 0, (-25, 5))
    mobile.pop("annotation_id")
    mobile.pop("image_id")
    mobile.update(
        evidence_id="mobile-third-drive", bearing_error_deg=2, horizontal_error_m=.5,
        association={"candidate_group_ids": candidate_ids, "matched_annotation_id": "a-0",
                     "independence_status": "different_capture_day"},
    )
    source["mobile_observations"] = [mobile]
    output, report = resolver.resolve_document(document(source))
    result = output["groups"][0]
    if len(candidate_ids) == 1:
        assert report["resolved_group_count"] == 1
        assert result["proposal"]["position_status"] == "mobile_refinement"
        assert result["proposal"]["independent_sequence_count"] == 3
        assert result["mobile_refinement"]["proposal"] == result["proposal"]
        assert result["pose_resolution"]["mobile_evidence_ids"] == ["mobile-third-drive"]
        point, _ = project([result["proposal"]["longitude"]], [result["proposal"]["latitude"]])[0]
        assert point == pytest.approx((ORIGIN[0] + 3, ORIGIN[1] + 54), abs=.001)
    else:
        assert report["resolved_group_count"] == 0
        assert result["proposal"] is None
        assert result["pose_resolution"]["mobile_evidence_ids"] == []


@pytest.mark.parametrize("hole_radius,accepted", [(50, True), (150, False)])
def test_generic_scope_shape_takes_precedence_and_preserves_100m_context(hole_radius, accepted):
    source = document(group())
    east, north = ORIGIN[0] + 3, ORIGIN[1] + 54
    outer = box(east - 500, north - 500, east + 500, north + 500)
    hole = box(east - hole_radius, north - hole_radius, east + hole_radius, north + hole_radius)
    source["place"].update(
        bounds_en_m=list(outer.bounds),
        boundary_wgs84=transform_geom(METRIC, WGS84, mapping(outer)),
        scope_geometry_wgs84=transform_geom(METRIC, WGS84, mapping(outer.difference(hole))),
    )
    output, report = resolver.resolve_document(source)
    proposal = output["groups"][0]["proposal"]
    assert bool(proposal) is accepted
    if accepted:
        assert proposal["in_review_window"] is False
        assert report["groups"][0]["adjacent_status"] == "estimated"
    else:
        assert report["groups"][0]["adjacent_status"] == "outside_follow_on_context"


def test_square_generic_scope_matches_existing_metric_window():
    source = document(group())
    original, original_report = resolver.resolve_document(source)
    square = box(*source["place"]["bounds_en_m"])
    source["place"]["scope_geometry_wgs84"] = transform_geom(METRIC, WGS84, mapping(square))
    scoped, scoped_report = resolver.resolve_document(source)
    assert scoped["groups"] == original["groups"]
    assert scoped_report == original_report
