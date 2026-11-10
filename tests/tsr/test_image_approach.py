from datetime import datetime, timedelta, timezone
import math
from types import SimpleNamespace

import pytest

from scripts.tsr.collection.image_approach import image_approach

EAST_WAY = ((-100.0, 0.0), (100.0, 0.0))
SIGN = (0.0, -4.0)


def ray(
    position, second, *, sequence="seq", image=None, fix=None, bearing=None, error=3.0
):
    camera_to_sign = (SIGN[0] - position[0], SIGN[1] - position[1])
    if bearing is None:
        bearing = math.degrees(math.atan2(*camera_to_sign))
    angle = math.radians(bearing)
    time = datetime(2026, 11, 9, tzinfo=timezone.utc) + timedelta(seconds=second)
    return SimpleNamespace(
        source="panoramax",
        sequence=sequence,
        image=image or f"{sequence}-photo-{second}",
        fix=fix or f"{sequence}-fix-{second}",
        captured_at=time.isoformat().replace("+00:00", "Z"),
        position=position,
        position_error=error,
        direction=(math.sin(angle), math.cos(angle)),
        angular_error=15.0,
    )


def fit(*rays, radius=17.0):
    return SimpleNamespace(point=SIGN, radius=radius, rays=rays)


def forward_rays(sequence="seq"):
    return [
        ray((x, -2), time, sequence=sequence)
        for x, time in ((-55, 0), (-40, 2), (-25, 4))
    ]


def backward_rays(sequence="back"):
    return [
        ray((x, 2), time, sequence=sequence) for x, time in ((55, 0), (40, 2), (25, 4))
    ]


def test_uses_camera_progress_not_reported_bearing_to_choose_way_direction():
    rays = forward_rays()
    for observation in rays:
        observation.bearing = 270  # an unrelated EXIF field must not select travel
    result = image_approach(fit(*reversed(rays)), EAST_WAY, 90)
    assert result.travel == "forward"
    assert result.front_azimuth_grid_deg == 270
    assert result.method == "image_sequence_approach"
    assert result.image_count == 3
    assert result.sequence_count == 1


def test_reversing_way_order_keeps_front_azimuth():
    result = image_approach(fit(*forward_rays()), EAST_WAY[::-1], 270)
    assert result.travel == "backward"
    assert result.front_azimuth_grid_deg == 270


def test_westbound_sequence_sees_east_facing_front():
    result = image_approach(fit(*backward_rays()), EAST_WAY, 90)
    assert result.travel == "backward"
    assert result.front_azimuth_grid_deg == 90


def test_unpaired_or_shared_fix_frames_cannot_make_a_track():
    a, b, c = forward_rays()
    b.sequence = None
    c.fix = a.fix
    assert image_approach(fit(a, b, c), EAST_WAY, 90) is None


def test_two_fix_pair_is_explicitly_lower_support():
    a, _, c = forward_rays()
    result = image_approach(fit(a, c), EAST_WAY, 90)
    assert result.method == "image_pair_approach"
    assert result.image_count == 2


def test_conflicting_separately_supported_approaches_withhold_direction():
    assert image_approach(fit(*forward_rays(), *backward_rays()), EAST_WAY, 90) is None


@pytest.mark.parametrize(
    "points",
    [
        ((-45, -10), (-44, 0), (-43, 10)),  # crossing the corridor
        ((-55, -2), (-29, 2), (-46, -2), (-25, -2)),  # clear reversal
        (
            (-12, -2),
            (-8, -2),
            (-3, -2),
        ),  # noise-scale motion and no clear upstream camera
        ((15, -2), (35, -2), (55, -2)),  # moving away and looking back
        ((-55, -2), (-43, 14), (-25, -2)),  # leaves corridor mid-sequence
    ],
)
def test_crossings_reversals_uncertainty_and_looking_back_withhold(points):
    rays = [ray(point, i * 2) for i, point in enumerate(points)]
    assert image_approach(fit(*rays), EAST_WAY, 90) is None


def test_mismatched_time_gap_and_directionless_bend_withhold():
    a, b, c = forward_rays()
    c.captured_at = "2026-11-09T00:00:30Z"
    assert image_approach(fit(a, b, c), EAST_WAY, 90) is None
    bent_way = ((-100.0, 0.0), (-25.0, 0.0), (-25.0, 25.0), (0.0, 0.0), (100.0, 0.0))
    assert image_approach(fit(*forward_rays()), bent_way, 90) is None


def test_large_uncertainty_keeps_nominal_approach_unresolved():
    rays = [ray((x, -2), i * 2, error=15) for i, x in enumerate((-55, -40, -25))]
    assert image_approach(fit(*rays), EAST_WAY, 90) is None
