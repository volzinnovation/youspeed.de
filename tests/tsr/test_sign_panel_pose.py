import math

from scripts.tsr.collection.estimate_sign_poses import delta_angle
from scripts.tsr.collection.sign_panel_pose import panel_heading, quad_heading


def observation(image_id, heading, yaw, lateral):
    width, height, fov = 4096, 3072, 70
    focal = width / (2 * math.tan(math.radians(fov / 2)))
    turn = math.radians(heading - yaw - 180)
    corners = []
    for x, y in ((-0.5, -0.5), (0.5, -0.5), (0.5, 0.5), (-0.5, 0.5)):
        z = 8 - x * math.sin(turn)
        corners.append(
            [
                width / 2 + focal * (lateral + x * math.cos(turn)) / z,
                height / 2 + focal * y / z,
            ]
        )
    return {
        "image_id": image_id,
        "image_width": width,
        "image_height": height,
        "horizontal_fov_deg": fov,
        "camera_yaw_deg": yaw,
        "corners_xy": corners,
        "corner_allowance_px": 0.2,
        "fov_allowance_deg": 1,
        "yaw_allowance_deg": 8,
        "tilt_allowance_deg": 2,
    }


def test_two_panel_views_recover_front_normal_with_retained_yaw_allowance():
    a = observation("a", 212, 10, 0.5)
    b = observation("b", 212, 20, -0.3)
    assert delta_angle(quad_heading(a)[0], 212) < 0.001
    result = panel_heading([a, b])
    assert delta_angle(result["azimut_deg"], 212) < 2
    assert 8 <= result["sensitivity_half_width_deg"] < 30
    assert result["views"] == 2


def test_panel_fit_abstains_on_clipping_and_conflicting_normal_intervals():
    a = observation("a", 212, 10, 0)
    clipped = observation("b", 212, 20, 0)
    clipped["corners_xy"][0][0] = 0
    assert quad_heading(clipped) is None
    assert panel_heading([a, clipped]) is None
    conflict = observation("c", 40, 210, 0)
    assert panel_heading([a, conflict]) is None


def test_reviewed_heading_links_only_to_unique_current_fit():
    from types import SimpleNamespace

    from scripts.tsr.collection.estimate_sign_poses import digest
    from scripts.tsr.collection.run_sign_pose_batch import panel_candidates

    records = [
        {
            "source": "panoramax",
            "observation_id": image_id,
            "image_id": image_id,
            "sign_code": "DE:350",
        }
        for image_id in ("a", "b", "c")
    ]
    evidence = [
        observation(row["image_id"], 212, 10, 0.1)
        | row
        | {"review_group_id": "one panel"}
        for row in records
    ]

    def fit(*ids):
        return SimpleNamespace(
            keys=ids,
            rays=[
                SimpleNamespace(key=f"panoramax:{key}", image=f"panoramax:{key}")
                for key in ids
            ],
        )

    primary = ("DE:350", fit("a", "b"), None)
    current = {digest(row) for row in records}
    linked = panel_candidates(records, [primary], evidence, current)
    assert linked[("a", "b")]["views"] == 3
    assert not panel_candidates(
        records, [primary], evidence, current - {digest(records[2])}
    )
    assert not panel_candidates(
        records, [primary, ("DE:350", fit("c"), None)], evidence, current
    )
