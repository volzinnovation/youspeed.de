import copy

import pytest
from shapely.geometry import box, mapping

from scripts.inspector.link_place_mobile_evidence import attach_mobile_evidence


def document():
    return {"groups": [{
        "id": "group-a", "sign_code": "DE:205", "proposal": {"azimut_deg": 90},
        "observations": [{
            "annotation_id": "annotation-a", "image_id": "image-a",
            "longitude": 8.44, "latitude": 48.8, "bearing_deg": 359,
            "captured_at": "2026-10-24T12:00:00Z",
        }],
    }]}


def mobile(**changes):
    return {
        "source": "mobile", "observation_id": "mobile:crop:" + "a" * 64,
        "sequence_id": "pass-a", "sign_code": "DE:205",
        "longitude": 8.44001, "latitude": 48.8, "bearing_degrees": 1,
        "bearing_error_deg": 20, "horizontal_error_m": 15,
        "captured_at": "2026-10-24T12:00:01Z", **changes,
    }


def test_links_close_frames_and_preserves_pose_without_double_counting_input():
    review = document()
    original = copy.deepcopy(review)
    attach_mobile_evidence(review, [mobile(), mobile()])
    group = review["groups"][0]
    assert group["proposal"] == original["groups"][0]["proposal"]
    assert len(group["mobile_observations"]) == 1
    link = group["mobile_observations"][0]["association"]
    assert link["time_delta_s"] == 1
    assert link["bearing_delta_deg"] == 2
    assert link["status"] == "proposed"
    assert link["independence_status"] == "same_capture_or_drive_possible"


def test_rejects_other_days_classes_opposing_views_and_imprecise_fixes():
    review = document()
    bad = [
        mobile(captured_at="2026-10-25T12:00:00Z"),
        mobile(sign_code="DE:206"),
        mobile(bearing_degrees=180),
        mobile(horizontal_error_m=51),
        mobile(longitude=8.45),
    ]
    for row in bad:
        attach_mobile_evidence(review, [row])
        assert not review["groups"][0].get("mobile_observations")
        assert review["mobile_reference"]["unique_mobile_observations"] == 0


def test_shared_annotation_stays_explicit_and_rerun_clears_obsolete_links():
    review = document()
    review["groups"].append({**copy.deepcopy(review["groups"][0]), "id": "group-b"})
    attach_mobile_evidence(review, [mobile(evidence_kind="sighting")])
    assert review["mobile_reference"]["unique_mobile_observations"] == 1
    assert review["mobile_reference"]["groups_with_candidates"] == 2
    for group in review["groups"]:
        entry = group["mobile_observations"][0]
        assert entry["mobile_kind"] == "sighting"
        assert entry["association"]["candidate_group_ids"] == ["group-a", "group-b"]
        assert entry["association"]["shared_panoramax_group_ids"] == ["group-a", "group-b"]
    attach_mobile_evidence(review, [])
    assert all("mobile_observations" not in group for group in review["groups"])


@pytest.mark.parametrize("geometry_key", ["scope_geometry_wgs84", "boundary_wgs84"])
def test_mobile_window_uses_polygon_holes_without_dropping_context_links(geometry_key):
    review = document()
    outer = box(8.43, 48.79, 8.45, 48.81)
    hole = box(8.4399, 48.7999, 8.4401, 48.8001)
    review["place"] = {
        "bounds_ring_wgs84": list(outer.exterior.coords),
        "boundary_wgs84": mapping(outer),
        geometry_key: mapping(outer.difference(hole)),
    }
    attach_mobile_evidence(review, [mobile()])
    # Scope membership is a label. Nearby evidence stays linked even outside
    # the shape; source collection and the pose estimator own context gates.
    entries = review["groups"][0]["mobile_observations"]
    assert len(entries) == 1
    assert entries[0]["in_review_window"] is False


def test_square_generic_scope_preserves_mobile_window_membership():
    review = document()
    square = box(8.43, 48.79, 8.45, 48.81)
    review["place"] = {"bounds_ring_wgs84": list(square.exterior.coords)}
    original = copy.deepcopy(review)
    attach_mobile_evidence(original, [mobile()])
    review["place"]["scope_geometry_wgs84"] = mapping(square)
    attach_mobile_evidence(review, [mobile()])
    assert review["groups"] == original["groups"]
    assert review["mobile_reference"] == original["mobile_reference"]
