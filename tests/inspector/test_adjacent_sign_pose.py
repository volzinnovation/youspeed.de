import math

import pytest

from scripts.inspector.adjacent_sign_pose import estimate_adjacent_pose
from scripts.tsr.collection.estimate_sign_poses import Ray, angle, subtract
from scripts.tsr.collection.panoramax_sequence_bridge import BridgeView


def chain(sequence, cameras, target, scale=0.6):
    views = []
    for index, camera in enumerate(cameras):
        east, depth = subtract(target, camera)
        ray = Ray.parse(
            {
                "source": "panoramax",
                "observation_id": f"{sequence}-{index}",
                "image_id": f"{sequence}-{index}",
                "sequence_id": sequence,
                "sign_code": "DE:222",
                "pose_basis": "assumed",
                "captured_at": f"2026-11-10T12:00:0{3 * index}Z",
                "bearing_degrees": angle((east, depth)),
                "bearing_error_deg": 12,
                "horizontal_error_m": 1.5,
            },
            camera,
            0,
        )
        height = math.degrees(2 * math.atan(scale / (2 * depth)))
        views.append(BridgeView(ray, 0, height, (9, 48.8)))
    return views[0], tuple(views[1:])


def test_scale_change_localizes_without_choosing_a_physical_panel_height():
    target = (3, 54)
    evidence = [
        chain("a", [(0, 0), (0, 27)], target, scale=0.4),
        chain("b", [(6, 2), (6, 25), (6, 44)], target, scale=0.8),
        chain("c", [(3, 4), (3, 29)], target, scale=0.7),
    ]
    result = estimate_adjacent_pose(evidence)
    assert result.status == "estimated"
    assert result.fit.point == pytest.approx(target, abs=1e-6)
    assert len(result.fit.rays) == 7
    assert result.diagnostics["support_sequence_count"] == 3
    assert result.diagnostics["support_pair_count"] == 4
    assert 0 < result.fit.radius < 40
    assert result.fit.radius == result.diagnostics["conditional_position_radius_m"]
    outside = estimate_adjacent_pose(evidence, bounds=(-10, -10, 10, 50))
    assert outside.fit is None
    assert outside.status == "adjacent_position_outside_bounds"


def test_repeated_frames_do_not_outvote_independent_sequences():
    target = (3, 54)
    long_track = chain("a", [(0, 0), (0, 25), (0, 42)], target)
    inconsistent = chain("b", [(6, 0), (6, 25)], (3, 90))
    assert (
        estimate_adjacent_pose([long_track]).status == "insufficient_adjacent_sequences"
    )
    result = estimate_adjacent_pose([long_track, inconsistent])
    assert result.status == "inconsistent_adjacent_tracks"
    assert result.fit is None
    corroborated = estimate_adjacent_pose(
        [long_track, inconsistent, chain("c", [(3, 2), (3, 28)], target)]
    )
    assert corroborated.status == "estimated"
    assert corroborated.fit.point == pytest.approx(target, abs=1e-6)
    assert corroborated.diagnostics["support_sequence_count"] == 2


def test_small_scale_change_leaves_the_position_unbounded():
    target = (3, 80)
    result = estimate_adjacent_pose(
        [
            chain("a", [(3, 0), (3, 10)], target),
            chain("b", [(3, 1), (3, 11)], target),
        ]
    )
    assert result.fit is None
    assert result.status == "adjacent_position_unbounded"
    assert result.diagnostics["support_sequence_count"] == 2
