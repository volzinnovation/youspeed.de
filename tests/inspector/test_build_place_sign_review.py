import json
from types import SimpleNamespace

from fiona.transform import transform
import pytest
from shapely.geometry import LineString
from shapely.strtree import STRtree

from scripts.inspector import build_place_sign_review as review
from scripts.tsr.collection.estimate_sign_poses import Fit, Ray, angle, subtract


def test_metric_window_and_clipped_road_background():
    place = review.place_window()
    west, south, east, north = place["bounds_en_m"]
    assert east - west == north - south == 2000
    assert place["bounds_ring_wgs84"][0] == place["bounds_ring_wgs84"][-1]
    way = SimpleNamespace(
        key="demo",
        geometry=LineString([(west - 300, south + 300), (east + 300, south + 300)]),
        tags={"highway": "residential", "name": "Demo street"},
    )
    roads = SimpleNamespace(ways=[way], index=STRtree([way.geometry]))
    [road] = review.local_roads(roads, place["bounds_en_m"])
    xs, ys = transform(review.WGS84, review.METRIC, *zip(*road["coordinates"]))
    assert xs == pytest.approx([west, east], abs=0.00001)
    assert ys == pytest.approx([south + 300, south + 300], abs=0.00001)
    assert road["name"] == "Demo street"


def test_nominal_crossing_does_not_claim_position_uncertainty():
    bounds = review.place_window()["bounds_en_m"]
    west, south, east, north = bounds
    target = ((west + east) / 2, (south + north) / 2)

    def ray(index, point, bearing):
        return Ray.parse(
            {
                "source": "panoramax",
                "observation_id": str(index),
                "image_id": str(index),
                "sequence_id": str(index),
                "sign_code": "DE:222",
                "pose_basis": "assumed",
                "captured_at": f"2026-11-10T12:00:0{index}Z",
                "bearing_degrees": bearing,
                "bearing_error_deg": 20,
                "horizontal_error_m": 5,
            },
            point,
            0,
        )

    cameras = [(target[0] - 20, target[1] + offset) for offset in (-5, 5)]
    rays = [
        ray(i, point, angle(subtract(target, point))) for i, point in enumerate(cameras)
    ]
    no_road = SimpleNamespace(ways=[], fallback=lambda *_: None)
    point = review.nominal_intersection(rays, bounds)
    assert point == pytest.approx(target, abs=1e-8)
    assert (
        review.propose([SimpleNamespace(ray=r) for r in rays], bounds, no_road) is None
    )
    result = review.render_proposal(
        Fit(point, 0, rays, ()),
        "nominal_review",
        "nominal_optical_ray_crossing",
        no_road,
    )
    assert result["position_status"] == "nominal_review"
    assert result["position_radius_m"] is None
    assert result["support_count"] == 2
    assert result["azimut_method"] == "reverse_image_ray_proxy"
    assert result["longitude"] == pytest.approx(review.CENTER[0], abs=1e-8)
    assert result["latitude"] == pytest.approx(review.CENTER[1], abs=1e-8)

    contradictory = ray(2, (target[0] - 10, target[1] - 8), 270)
    assert review.nominal_intersection([*rays, contradictory], bounds) is None


@pytest.mark.parametrize("road_side", ["right", "left"])
@pytest.mark.parametrize(
    ("cameras", "target", "roads", "expected"),
    [
        (
            (14, 28),
            (2, 33),
            [("20", [(0, -20), (0, 60)])],
            (1, 33, "twoSightingRightOfWay", 180),
        ),
        (
            (52, 38),
            (-2, 33),
            [("20", [(0, -20), (0, 60)])],
            (-1, 33, "twoSightingRightOfWay", 0),
        ),
        (
            (14, 28),
            (2, 33),
            [("20", [(0, 0), (0, 33)]), ("31", [(0, 33), (18, 33)])],
            (1, 33, "twoSightingRightOfJunction", 180),
        ),
        (
            (0, 5),
            (1, 33),
            [("20", [(0, -5), (0, 33)]), ("31", [(0, 33), (20, 33)])],
            (1, 33, "twoSightingRightOfJunction", 180),
        ),
        (
            (14, 28),
            (1, 33),
            [("20", [(0, -20), (0, 60)]), ("21", [(0, -20), (0, 60)])],
            None,
        ),
    ],
)
def test_two_sighting_road_fallback_matches_streetshots_cases(
    cameras, target, roads, expected, road_side
):
    # Same metre-based geometry as the iPhone SignPoseTests, translated to
    # the Inspector's projected review window.
    bounds = review.place_window()["bounds_en_m"]
    west, south, east, north = bounds
    origin = ((west + east) / 2, (south + north) / 2)

    def absolute(point):
        return tuple(a + b for a, b in zip(point, origin))

    mirror = 1 if road_side == "right" else -1
    target = (mirror * target[0], target[1])
    views = []
    for index, camera in enumerate(cameras):
        position = (0, camera)
        record = {
            "source": "panoramax",
            "observation_id": str(index),
            "image_id": str(index),
            "sequence_id": str(index),
            "sign_code": "DE:274-30",
            "pose_basis": "assumed",
            "captured_at": f"2026-11-10T12:00:0{index}Z",
            "bearing_degrees": angle(subtract(target, position)),
            "bearing_error_deg": 3,
            "horizontal_error_m": 1.5,
        }
        views.append(SimpleNamespace(ray=Ray.parse(record, absolute(position), 0)))

    ways = []
    for way_id, coords in roads:
        points = [absolute((mirror * x, y)) for x, y in coords]
        ways.append(
            SimpleNamespace(key=way_id, points=points, geometry=LineString(points))
        )
    index = SimpleNamespace(ways=ways, index=STRtree([way.geometry for way in ways]))
    result = review.propose(list(reversed(views)), bounds, index, road_side=road_side)
    if expected is None:
        assert result is None
        return

    expected_east, expected_north, expected_method, grid_azimuth = expected
    longitude, latitude = result["longitude"], result["latitude"]
    xs, ys = transform(review.WGS84, review.METRIC, [longitude], [latitude])
    _, rotation = review.project([longitude], [latitude])[0]
    assert (xs[0], ys[0]) == pytest.approx(
        absolute((mirror * expected_east, expected_north)), abs=1e-6
    )
    assert (result["azimut_deg"] + rotation) % 360 == pytest.approx(
        grid_azimuth, abs=1e-6
    )
    assert result["azimut_method"] == "road_tangent_two_sighting"
    assert result["position_method"] == expected_method.replace(
        "Right", road_side.title()
    )
    assert result["road_side"] == road_side
    assert result["position_status"] == "two_sighting_road_review"
    assert result["position_radius_m"] is None
    assert result["osm_way_id"] == "20"
    assert result["osm_distance_m"] == 1
    assert result["support_count"] == 2


def test_frozen_rays_must_match_the_private_report_snapshot(tmp_path):
    rays_file = tmp_path / "rays.json"
    report_file = tmp_path / "report.jsonl"
    meta = {"record_type": "corpus_metadata", "corpus_read_at": "2026-11-10T12:00:00Z"}
    document = {
        "private_panoramax_review": True,
        "origin_rechecked": False,
        "corpus_metadata": meta,
        "rays": [{"source": "panoramax"}],
    }
    rays_file.write_text(json.dumps(document))
    report_file.write_text(json.dumps(meta) + "\n")
    rays_file.chmod(0o600)
    report_file.chmod(0o600)
    assert review.frozen_sources(rays_file, report_file) == (document["rays"], [meta])

    report_file.write_text(json.dumps({**meta, "corpus_read_at": "other"}) + "\n")
    with pytest.raises(ValueError, match="same private corpus snapshot"):
        review.frozen_sources(rays_file, report_file)


def track_view(
    image, second, north, height, *, sequence="pass-1", code="DE:222", east=0
):
    return SimpleNamespace(
        ray=SimpleNamespace(
            image=image,
            key=image,
            fix=image,
            sequence=sequence,
            code=code,
            captured_at=f"2026-11-10T12:00:{second:02}Z",
            position=(east, north),
            direction=(0, 1),
            bearing=0,
            angular_error=20,
            position_error=5,
        ),
        coordinates=review.CENTER,
        camera_heading=0,
        angular_height=height,
    )


def test_adjacent_rank_never_skips_an_unqualified_or_competing_photo():
    anchor = track_view("anchor", 0, 0, 1)
    next_view = track_view("next", 3, 30, 2)
    later = track_view("later", 6, 50, 6)
    ranks = {("pass-1", 12): "next", ("pass-1", 13): "later"}
    qualified = {("next", "DE:222"): [next_view], ("later", "DE:222"): [later]}
    assert list(review.next_frames(anchor, "pass-1", 11, ranks, qualified)) == [
        (1, next_view),
        (2, later),
    ]
    assert (
        list(
            review.next_frames(
                anchor, "pass-1", 11, ranks, {("later", "DE:222"): [later]}
            )
        )
        == []
    )
    qualified["next", "DE:222"].append(track_view("next", 3, 31, 2.2))
    assert list(review.next_frames(anchor, "pass-1", 11, ranks, qualified)) == []


def test_follow_on_needs_closing_compatible_geometry_on_same_pass():
    anchor = track_view("anchor", 0, 0, 1)
    assert review.compatible_next_frame(anchor, track_view("next", 3, 30, 2))
    assert not review.compatible_next_frame(anchor, track_view("next", 3, 30, 0.8))
    assert not review.compatible_next_frame(anchor, track_view("next", 3, -30, 2))
    assert not review.compatible_next_frame(anchor, track_view("next", 9, 30, 2))
    assert not review.compatible_next_frame(
        anchor, track_view("next", 3, 30, 2, sequence="pass-2")
    )


def test_duplicate_source_rank_fails_closed(tmp_path):
    ranks = tmp_path / "ranks.json"
    ranks.write_text(
        json.dumps(
            {
                "source_id": "panoramax.woladen.de",
                "frames": [
                    {"sequence_id": "pass-1", "image_id": "a", "rank": 12},
                    {"sequence_id": "pass-1", "image_id": "b", "rank": 12},
                ],
            }
        )
    )
    ranks.chmod(0o600)
    with pytest.raises(ValueError, match="duplicate Panoramax sequence rank"):
        review.read_sequence_ranks(ranks)


def test_follow_on_diagnostic_counts_independent_passes_and_flags_behind_point():
    bounds = review.place_window()["bounds_en_m"]
    east, north = (bounds[0] + bounds[2]) / 2, (bounds[1] + bounds[3]) / 2
    first = track_view("first", 0, north - 10, 1, east=east)
    second = track_view("second", 0, north - 10, 1, east=east + 5, sequence="pass-2")
    next_view = track_view("next", 3, north + 20, 2, east=east)
    later = track_view("later", 6, north + 40, 6, east=east)
    proposal = {
        "longitude": review.CENTER[0],
        "latitude": review.CENTER[1],
        "position_radius_m": None,
    }
    diagnostic = review.follow_on_diagnostic(
        [first, second], [(None, 1, next_view), (None, 2, later)], proposal
    )
    assert diagnostic["independent_sequence_count"] == 2
    assert diagnostic["position_fit_status"] == "insufficient_independent_sequences"
    assert diagnostic["conflicting_observation_count"] == 2
    assert (
        diagnostic["proposal_consistency"] == "nominal_point_conflicts_with_follow_ons"
    )
