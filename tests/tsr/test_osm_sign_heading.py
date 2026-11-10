from types import SimpleNamespace

import pytest
from fiona.transform import transform
from shapely.geometry import Point

from scripts.tsr.collection.estimate_sign_poses import (
    METRIC,
    WGS84,
    delta_angle,
    project,
)
from scripts.tsr.collection.image_approach import image_approach
from scripts.tsr.collection.osm_sign_heading import RoadHeadingIndex


CENTER, _ = project([8.43], [48.90])[0]


def build_way(key, offsets, **tags):
    xs = [CENTER[0] + offset[0] for offset in offsets]
    ys = [CENTER[1] + offset[1] for offset in offsets]
    lons, lats = transform(METRIC, WGS84, xs, ys)
    return {
        "way_id": key,
        "node_ids": [f"{key}-{i}" for i in range(len(offsets))],
        "points_lat_lon": list(zip(lats, lons)),
        "tags": {"highway": "residential", **tags},
    }


def index(*ways):
    return RoadHeadingIndex(
        {
            "schema_version": 1,
            "source": {"kind": "original_osm", "sha256": "a" * 64},
            "extraction": {
                "bounds_wgs84": [[8.4, 48.8, 8.5, 49]],
                "candidate_complete_within_source_bbox": True,
                "node_geometry_complete": True,
            },
            "roads": list(ways),
        }
    )


def fit(x=0, y=0, radius=0.5, rays=()):
    point = (CENTER[0] + x, CENTER[1] + y)
    return SimpleNamespace(
        point=point,
        region=tuple(Point(point).buffer(radius).exterior.coords[:-1]),
        radius=radius,
        rays=rays,
    )


@pytest.mark.parametrize(("y", "facing", "side"), [(-6, 270, "right"), (6, 90, "left")])
def test_freiburg_front_follows_approach_and_is_invariant_to_reversing_node_order(
    y, facing, side
):
    direct = index(build_way("1", [(-100, 0), (100, 0)]))
    result = direct.heading(fit(y=y), "DE:274-30", 8.43, 48.90)
    assert result.side == side and result.method == "osm_road_side"
    assert not result.corroborated
    assert delta_angle(result.facing, facing) < 0.1
    reverse = index(build_way("1", [(100, 0), (-100, 0)]))
    opposite = reverse.heading(fit(y=y), "DE:274-30", 8.43, 48.90)
    assert delta_angle(opposite.facing, facing) < 0.1


def test_unresolved_side_or_parallel_way_withholds_azimuth():
    road = build_way("1", [(-100, 0), (100, 0)])
    crossing_center = index(road).heading(fit(y=-3, radius=6), "DE:274-30", 8.43, 48.90)
    assert (
        crossing_center.facing is None
        and crossing_center.status == "road_side_ambiguous"
    )
    assert len(crossing_center.candidates) == 2
    parallel = build_way("2", [(-100, -12), (100, -12)])
    result = index(road, parallel).heading(
        fit(y=-4, radius=8), "DE:274-30", 8.43, 48.90
    )
    assert result.facing is None and result.status == "competing_roads"


def test_private_fallback_uses_associated_way_or_true_nearest_segment():
    west = build_way("1", [(-100, -20), (100, -20)], oneway="-1")
    east = build_way("2", [(-100, 0), (100, 0)])
    roads = index(west, east)
    nearest = roads.fallback(fit(y=5), 8.43, 48.90, None, None)
    assert nearest.way_id == "2" and nearest.method == "osm_nearest_road_fallback"
    assert nearest.direction_basis == "right_hand_road_side"
    assert delta_angle(nearest.approach, 270) < 0.1
    associated = roads.fallback(fit(), 8.43, 48.90, "1", None)
    assert (
        associated.way_id == "1" and associated.method == "osm_associated_way_fallback"
    )
    assert associated.direction_basis == "osm_oneway"
    assert delta_angle(associated.approach, 270) < 0.1
    center = roads.fallback(fit(), 8.43, 48.90, None, None)
    assert center.direction_basis == "osm_node_order"
    assert delta_angle(center.approach, 90) < 0.1


def test_oneway_reverse_and_observed_face_conflict():
    road = build_way("1", [(-100, 0), (100, 0)], oneway="-1")
    roads = index(road)
    centered = roads.heading(fit(radius=4), "DE:274-30", 8.43, 48.90)
    assert centered.method == "osm_oneway" and delta_angle(centered.facing, 90) < 0.1
    rejected = roads.heading(
        fit(radius=4), "DE:274-30", 8.43, 48.90, (270, 30, "front_visibility")
    )
    assert rejected.facing is None and rejected.status == "camera_heading_conflict"
    conditional = build_way(
        "1", [(-100, 0), (100, 0)], oneway="yes", **{"oneway:conditional": "no @ (...)"}
    )
    assert index(conditional).heading(fit(), "DE:274-30", 8.43, 48.90).facing is None


def test_independent_approach_direction_resolves_side_only_with_strong_evidence():
    def camera(i, x):
        return SimpleNamespace(
            position=(CENTER[0] + x, CENTER[1]),
            direction=(1, 0),
            angular_error=5,
            position_error=1,
            source="panoramax",
            sequence="sequence",
            fix=f"fix{i}",
            image=f"image{i}",
            captured_at=f"2026-11-10T12:00:{i * 2:02d}Z",
        )

    roads = index(build_way("1", [(-100, 0), (100, 0)]))
    cameras = [camera(0, -60), camera(1, -40), camera(2, -20)]
    strong = roads.heading(
        fit(radius=6, rays=cameras), "DE:274-30", 8.43, 48.90, approach=image_approach
    )
    assert (
        strong.method == "osm_image_approach" and delta_angle(strong.facing, 270) < 0.1
    )
    assert delta_angle(strong.image_travel, 90) < 0.1
    assert strong.corroborated
    weak = roads.heading(
        fit(radius=6, rays=cameras[:2]),
        "DE:274-30",
        8.43,
        48.90,
        approach=image_approach,
    )
    assert weak.facing is None and weak.image_method == "image_pair_approach"
    assert delta_angle(weak.image_travel, 90) < 0.1
    unrelated = roads.heading(
        fit(radius=6, rays=cameras), "DE:283", 8.43, 48.90, approach=image_approach
    )
    assert unrelated.facing is None and unrelated.status == "unsupported_sign_class"
    assert delta_angle(unrelated.image_travel, 90) < 0.1


def test_image_track_on_parallel_road_cannot_corroborate_sign_road():
    near_sign = build_way("1", [(-100, 0), (100, 0)])
    camera_road = build_way("2", [(-100, 10), (100, 10)])
    rays = [
        SimpleNamespace(
            position=(CENTER[0] + x, CENTER[1] + 10),
            direction=(1, 0),
            angular_error=5,
            position_error=1,
            source="panoramax",
            sequence="track",
            fix=f"fix-{i}",
            image=f"image-{i}",
            captured_at=f"2026-11-10T12:00:{i * 2:02d}Z",
        )
        for i, x in enumerate((-60, -40, -20))
    ]
    result = index(near_sign, camera_road).heading(
        fit(y=-6, rays=rays),
        "DE:274-30",
        8.43,
        48.90,
        approach=image_approach,
    )
    assert result.way_id == "1" and result.method == "osm_road_side"
    assert not result.corroborated and result.image_travel is None


def test_frame_matched_way_can_corroborate_exact_approach(tmp_path):
    import json
    import sqlite3

    from scripts.tsr.collection.sign_road_association import sha256
    from scripts.tsr.collection.travelled_way import PhoneMatch, TravelBundles

    raw_way = build_way("9007199254740999", [(-100, 0), (100, 0)])
    path = tmp_path / "original-phone.sqlite"
    with sqlite3.connect(path) as db:
        db.executescript("""
            CREATE TABLE metadata(key TEXT, value TEXT);
            INSERT INTO metadata VALUES ('road_geometry_policy','source_vertices_v1');
            CREATE TABLE way_geom(way_id INTEGER PRIMARY KEY, points_json TEXT);
        """)
        db.execute(
            "INSERT INTO way_geom VALUES (?,?)",
            (int(raw_way["way_id"]), json.dumps(raw_way["points_lat_lon"])),
        )
    bundles = TravelBundles([path])
    bundle_hash = sha256(path)
    match = PhoneMatch(raw_way["way_id"], bundle_hash, "forward")
    assert bundles.direction(match, raw_way["points_lat_lon"][::-1]) == "backward"
    assert bundles.direction(match, [[48.9, 8.43], [48.91, 8.43]]) is None
    rays = [
        SimpleNamespace(
            position=(CENTER[0] + x, CENTER[1]),
            direction=(1, 0),
            angular_error=5,
            position_error=1,
            phone_match=match,
            image=f"im{i}",
            fix=f"fix{i}",
        )
        for i, x in enumerate((-60, -35))
    ]
    roads = index(raw_way)
    candidate = fit(y=-6, rays=rays)
    result = roads.heading(candidate, "DE:274-30", 8.43, 48.90, travel_bundles=bundles)
    assert result.corroborated and result.method == "osm_recorded_approach"
    assert delta_angle(result.facing, 270) < 0.1
    assert delta_angle(result.recorded_travel, 90) < 0.1
    rays[1].phone_match = PhoneMatch(raw_way["way_id"], "b" * 64, "forward")
    result = roads.heading(candidate, "DE:274-30", 8.43, 48.90, travel_bundles=bundles)
    assert not result.corroborated and result.recorded_travel is None
    reverse_graph = index(
        build_way("1", [(-100, -6), (100, -6)]),
        build_way(raw_way["way_id"], [(100, 0), (-100, 0)]),
    )
    fallback = reverse_graph.fallback(candidate, 8.43, 48.90, "1", bundles)
    assert fallback.way_id == raw_way["way_id"]
    assert fallback.method == "osm_recorded_way_fallback"
    assert fallback.direction_basis == "recorded_travel"
    assert delta_angle(fallback.approach, 90) < 0.1


def test_phone_match_uses_original_frame_clock_and_stability():
    from scripts.tsr.collection.travelled_way import PhoneMatch

    capture = "2026-11-10T12:00:01Z"
    row = {
        "schema_version": 1,
        "source": "on_device_bundle_matcher",
        "matched_way_stable": True,
        "travel_direction": "reverse",
        "osm_way_id": "9007199254740999",
        "bundle_db_sha256": "a" * 64,
        "matched_fix_at": "2026-11-10T12:00:00Z",
        "frame_match_delta_ms": 1000,
    }
    assert PhoneMatch.from_frame(row, capture).way_id == row["osm_way_id"]
    assert PhoneMatch.from_frame(row, "2026-11-10T12:00:01.005Z") is None
    assert PhoneMatch.from_frame(row | {"matched_way_stable": False}, capture) is None
    assert PhoneMatch.from_frame(row | {"travel_direction": "unknown"}, capture) is None


def test_packed_phone_match_verifies_geometry_companion(tmp_path):
    import json
    import zlib

    import pytest

    from scripts.map.packed_runtime import GEOMETRY, pack_chunks
    from scripts.tsr.collection.sign_road_association import sha256
    from scripts.tsr.collection.travelled_way import PhoneMatch, TravelBundles

    way_id = "9007199254740999"
    points = [[48.9, 8.43], [48.91, 8.43]]
    geometry = json.dumps(points).encode()
    source = "a" * 64
    context = tmp_path / "context.yspc"
    roads = tmp_path / "ways.yspg"
    index_file = tmp_path / "geometry-index"
    index_file.write_bytes(
        GEOMETRY.pack(int(way_id), 0, len(geometry), zlib.crc32(geometry))
    )
    pack_chunks([b"context"], context, source, codec=1)
    pack_chunks(
        [geometry], roads, source, index_path=index_file, index_count=1, codec=1
    )
    context_hash = sha256(context)
    manifest = tmp_path / "manifest.json"
    data = {
        "format": "youspeed.v4.bundle.manifest",
        "db": {"file": context.name, "sha256": context_hash},
        "packed_base": {
            "roads": {"file": roads.name, "uncompressed_sha256": sha256(roads)}
        },
        "source": {"packed_storage": {"original_sqlite_sha256": source}},
    }
    manifest.write_text(json.dumps(data))
    bundle = TravelBundles([], [manifest])
    assert (
        bundle.direction(PhoneMatch(way_id, context_hash, "reverse"), points)
        == "backward"
    )
    data["source"]["packed_storage"]["original_sqlite_sha256"] = "b" * 64
    manifest.write_text(json.dumps(data))
    with pytest.raises(ValueError, match="original geometry revision"):
        TravelBundles([], [manifest])
    with roads.open("ab") as handle:
        handle.write(b"tampered")
    with pytest.raises(ValueError, match="SHA-256"):
        data["source"]["packed_storage"]["original_sqlite_sha256"] = source
        manifest.write_text(json.dumps(data))
        TravelBundles([], [manifest])
