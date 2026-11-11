import math
from dataclasses import replace

from scripts.inspector.refine_place_sign_pose import distinct_views, narrow_existing
from scripts.tsr.collection.estimate_sign_poses import Ray


def test_close_mobile_capture_counts_once_and_another_day_stays_independent():
    pano = {
        "annotation_id": "pano", "image_id": "photo", "sequence_id": "drive",
        "captured_at": "2026-10-24T12:00:00Z", "longitude": 8.44, "latitude": 48.8,
        "bearing_deg": 0, "bearing_error_deg": 10, "horizontal_error_m": 5,
    }
    group = {"id": "group", "sign_code": "DE:205", "observations": [pano]}
    mobile = {k: v for k, v in pano.items() if k not in ("annotation_id", "image_id")}
    mobile.update(evidence_id="mobile-a", sequence_id="mobile-drive",
                  captured_at="2026-10-24T12:00:00.100Z", latitude=48.80004)
    mobile["association"] = {"candidate_group_ids": ["group"], "matched_annotation_id": "pano",
                             "independence_status": "same_capture_or_drive_possible"}
    other_day = {**mobile, "evidence_id": "mobile-b", "sequence_id": "other-drive",
                 "captured_at": "2026-10-25T12:00:00Z",
                 "association": {**mobile["association"], "independence_status": "different_capture_day"}}
    group["mobile_observations"] = [mobile, other_day]
    views, duplicates = distinct_views(group)
    assert duplicates == 1
    assert {identifier for _, identifier in views} == {None, "mobile-b"}
    assert len({ray.sequence for ray, _ in views}) == 2


def test_position_refinement_respects_direction_and_rejects_conflict():
    record = {
        "source": "mobile", "observation_id": "o", "image_id": "i", "sequence_id": "s",
        "captured_at": "2026-10-24T12:00:00Z", "sign_code": "DE:205", "pose_basis": "assumed",
        "bearing_degrees": 0, "bearing_error_deg": 6, "horizontal_error_m": 1,
    }
    view = Ray.parse(record, (5, -20), 0)
    point, radius = narrow_existing((0, 0), 10, [view])
    assert point[0] > 1
    assert math.dist(point, (0, 0)) < 10
    assert radius < 10
    conflicting = replace(view, position=(50, -20))
    assert narrow_existing((0, 0), 10, [conflicting]) is None
