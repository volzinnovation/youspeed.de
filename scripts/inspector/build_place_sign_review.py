"""Build a private 2 km place review from frozen Panoramax evidence."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
from itertools import combinations
import json
import math
from pathlib import Path

from fiona.transform import transform
from shapely.geometry import Point, box

from scripts.tsr.collection.estimate_sign_poses import (
    METRIC,
    MAX_RANGE_M,
    MIN_RANGE_M,
    MIN_VIEWS,
    WGS84,
    Fit,
    angle,
    delta_angle,
    dot,
    fit_position,
    image_bearing_candidate,
    independent,
    project,
    subtract,
)
from scripts.tsr.collection.osm_sign_heading import ROAD_OFFSET_M, RoadHeadingIndex
from scripts.tsr.collection.panoramax_sequence_bridge import (
    MAX_COARSE_RADIUS_M,
    group_bridges,
    load_views,
    stable_across_sequences,
)
from scripts.tsr.collection.run_sign_pose_batch import (
    read_private,
    write_private_json,
)
from scripts.tsr.collection.sign_identities import sign_token


CENTER = (8.4364, 48.7978)
HALF_SIZE_M = 1000
MAX_PRIVATE_INPUT_BYTES = 64 * 1024**2
REVIEW_PRIORITY = {"bounded_review": 0, "coarse_review": 1, "nominal_review": 2}
MAX_FOLLOW_ON_FRAMES = 2
FOLLOW_ON_CONTEXT_M = 100


def place_window(name="Bad Herrenalb", center=CENTER):
    longitude, latitude = center
    if not (
        math.isfinite(longitude)
        and math.isfinite(latitude)
        and 5 <= longitude <= 16
        and 47 <= latitude <= 56
    ):
        raise ValueError("the center must be a longitude and latitude in Germany")
    (east, north), _ = project([longitude], [latitude])[0]
    west, south, east, north = (
        east - HALF_SIZE_M,
        north - HALF_SIZE_M,
        east + HALF_SIZE_M,
        north + HALF_SIZE_M,
    )
    lon, lat = transform(
        METRIC,
        WGS84,
        [west, east, east, west, west],
        [south, south, north, north, south],
    )
    return {
        "name": name,
        "longitude": longitude,
        "latitude": latitude,
        "center_basis": "provisional_town_center"
        if center == CENTER
        else "configured_town_center",
        "crs": METRIC,
        "bounds_en_m": [west, south, east, north],
        "bounds_ring_wgs84": list(zip(lon, lat)),
        "bbox_wgs84": [min(lon), min(lat), max(lon), max(lat)],
    }


def inside(point, bounds):
    east, north = point
    west, south, east_limit, north_limit = bounds
    return west <= east <= east_limit and south <= north <= north_limit


def local_roads(roads, bounds):
    window = box(*bounds)
    result = []
    indices = roads.index.query(window, predicate="intersects")
    for index in sorted(indices, key=lambda value: roads.ways[value].key):
        way = roads.ways[index]
        clipped = way.geometry.intersection(window)
        parts = getattr(clipped, "geoms", (clipped,))
        for part in parts:
            if part.geom_type != "LineString" or not part.length:
                continue
            lon, lat = transform(METRIC, WGS84, *zip(*part.coords))
            result.append(
                {
                    "coordinates": list(zip(lon, lat)),
                    "highway": way.tags.get("highway"),
                    "name": way.tags.get("name"),
                }
            )
    return result


def nominal_intersection(rays, bounds):
    candidates = []
    for first, second in combinations(rays, 2):
        point = first.intersection(second)
        if point is None or not inside(point, bounds):
            continue
        residuals = [ray.association_distance(point) for ray in rays]
        if all(value is not None for value in residuals):
            candidates.append((sum(residuals), point))
    return min(candidates)[1] if candidates else None


def propose(group, bounds, roads):
    rays = independent([view.ray for view in group])
    if len(rays) < 2:
        return None
    fit, status, method = None, "bounded_review", "optical_ray_intersection"
    if len(rays) >= MIN_VIEWS:
        fit, _ = fit_position(rays)
        if fit is None:
            coarse, _ = fit_position(rays, max_radius=MAX_COARSE_RADIUS_M)
            if coarse is not None and stable_across_sequences(coarse):
                fit, status = coarse, "coarse_review"
    if fit is not None and not inside(fit.point, bounds):
        return None
    if fit is None:
        point = nominal_intersection(rays, bounds)
        if point is None:
            return None
        fit = Fit(point, 0, rays, ())
        status, method = "nominal_review", "nominal_optical_ray_crossing"
    return render_proposal(fit, status, method, roads)


def render_proposal(fit, status, method, roads):
    east, north = fit.point
    longitude, latitude = (v[0] for v in transform(METRIC, WGS84, [east], [north]))
    _, rotation = project([longitude], [latitude])[0]
    proxy = image_bearing_candidate(fit.rays)
    heading = (proxy.heading - rotation) % 360 if proxy else None
    heading_method = "reverse_image_ray_proxy" if proxy else None
    way_id, road_distance, road_basis = None, None, None
    road = roads.fallback(fit, longitude, latitude, None, None)
    if (
        road is not None
        and proxy is not None
        and road.distance <= ROAD_OFFSET_M
        and not road.tangent_ambiguous
        and road.direction_basis != "osm_node_order"
        and delta_angle(road.approach + 180, proxy.heading)
        <= proxy.spread + proxy.bearing_allowance
    ):
        heading = (road.approach + 180 - rotation) % 360
        heading_method = "road_tangent_with_image_proxy"
        way_id, road_distance, road_basis = (
            road.way_id,
            road.distance,
            road.direction_basis,
        )
    return {
        "longitude": longitude,
        "latitude": latitude,
        "position_method": method,
        "position_status": status,
        "position_radius_m": fit.radius if status != "nominal_review" else None,
        "support_count": len(fit.rays),
        "azimut_deg": heading,
        "azimut_method": heading_method,
        "azimut_image_spread_deg": proxy.spread if proxy else None,
        "osm_way_id": way_id,
        "osm_distance_m": road_distance,
        "osm_direction_basis": road_basis,
    }


def observation(view, record, native):
    from scripts.youspeed.panoramax_rays import numeric

    width, height = native["geometry"]["registered_dimensions"]
    projection = native["geometry"]["projection"]
    return {
        "image_id": record["image_id"],
        "annotation_id": native["annotation_id"],
        "source_id": native["source_id"],
        "sequence_id": record["sequence_id"],
        "captured_at": record["captured_at"],
        "longitude": view.coordinates[0],
        "latitude": view.coordinates[1],
        "camera_heading_deg": view.camera_heading,
        "bearing_deg": record["bearing_degrees"],
        "bearing_error_deg": view.ray.angular_error,
        "horizontal_error_m": view.ray.position_error,
        "box_xyxy": native["geometry"]["original_box"],
        "image_width": width,
        "image_height": height,
        "projection": projection,
        "box_wrap": native["geometry"]["wrap"] is True,
        "pose_method": record["pose_method"],
        "angular_height_deg": view.angular_height,
        "camera_fov_deg": 360
        if projection == "equirectangular"
        else numeric(native["picture"]["metadata"].get("field_of_view")),
        "item_visibility": record["item_visibility"],
        "picture_visibility": record["picture_visibility"],
        "sequence_visibility": record["sequence_visibility"],
    }


def group_priority(group):
    proposal = group["proposal"]
    public_views = sum(
        all(
            view[key] == "anyone"
            for key in ("item_visibility", "picture_visibility", "sequence_visibility")
        )
        for view in group["observations"]
    )
    status = proposal["position_status"] if proposal else "unresolved"
    support = proposal["support_count"] if proposal else 0
    radius = proposal["position_radius_m"] if proposal else None
    return (
        REVIEW_PRIORITY.get(status, 3),
        -public_views,
        -support,
        radius or MAX_COARSE_RADIUS_M,
        group["id"],
    )


def frozen_sources(rays_file, report_file):
    document = json.loads(read_private(rays_file, MAX_PRIVATE_INPUT_BYTES))
    report = [
        json.loads(line)
        for line in read_private(report_file, MAX_PRIVATE_INPUT_BYTES).splitlines()
        if line.strip()
    ]
    if (
        not report
        or not isinstance(document, dict)
        or document.get("private_panoramax_review") is not True
        or document.get("origin_rechecked") is not False
        or document.get("corpus_metadata") != report[0]
    ):
        raise ValueError(
            "review rays must be bound to the same private corpus snapshot"
        )
    records = document.get("rays")
    if not isinstance(records, list) or any(
        not isinstance(row, dict) or row.get("source") != "panoramax" for row in records
    ):
        raise ValueError("expected an array of private Panoramax rays")
    return records, report


def read_sequence_ranks(path):
    document = json.loads(read_private(path, MAX_PRIVATE_INPUT_BYTES))
    if (
        not isinstance(document, dict)
        or document.get("source_id") != "panoramax.woladen.de"
        or not isinstance(document.get("frames"), list)
    ):
        raise ValueError("expected authoritative Panoramax sequence ranks")
    ranks = {}
    used = set()
    for frame in document["frames"]:
        sequence, image, rank = frame["sequence_id"], frame["image_id"], frame["rank"]
        if (
            not isinstance(sequence, str)
            or not sequence
            or not isinstance(image, str)
            or not image
            or type(rank) is not int
            or rank < 0
            or (sequence, image) in ranks
            or (sequence, rank) in used
        ):
            raise ValueError("invalid or duplicate Panoramax sequence rank")
        ranks[sequence, image] = rank
        used.add((sequence, rank))
    return ranks


def compatible_next_frame(first, second):
    """Require a closing, same-direction view with consistent panel growth."""
    if first.ray.code != second.ray.code or first.ray.sequence != second.ray.sequence:
        return False
    elapsed = (
        datetime.fromisoformat(second.ray.captured_at.replace("Z", "+00:00"))
        - datetime.fromisoformat(first.ray.captured_at.replace("Z", "+00:00"))
    ).total_seconds()
    movement = subtract(second.ray.position, first.ray.position)
    step = math.hypot(*movement)
    if not 0 < elapsed <= 8 or not 2 <= step <= 50:
        return False
    course = angle(movement)
    if (
        delta_angle(first.camera_heading, second.camera_heading) > 20
        or max(delta_angle(course, view.ray.bearing) for view in (first, second)) > 40
    ):
        return False

    # Relative apparent height constrains the change in range without choosing
    # a physical sign size. Keep the fit provisional because the box can vary.
    first_height, second_height = (
        math.tan(math.radians(view.angular_height / 2)) for view in (first, second)
    )
    ratio = first_height / second_height
    if not 0.2 <= ratio <= 1 / 1.15:
        return False
    scaled_direction = tuple(ratio * value for value in second.ray.direction)
    difference = subtract(first.ray.direction, scaled_direction)
    first_range = dot(movement, difference) / dot(difference, difference)
    residual = subtract(movement, tuple(first_range * value for value in difference))
    return (
        MIN_RANGE_M <= ratio * first_range <= first_range <= MAX_RANGE_M
        and math.hypot(*residual) <= 8
    )


def next_frames(anchor, sequence, rank, photos_by_rank, views_by_photo):
    previous = anchor
    for offset in range(1, MAX_FOLLOW_ON_FRAMES + 1):
        image = photos_by_rank.get((sequence, rank + offset))
        candidates = views_by_photo.get((image, anchor.ray.code), ())
        if len(candidates) != 1:
            return
        candidate = candidates[0]
        if not compatible_next_frame(previous, candidate):
            return
        yield offset, candidate
        previous = candidate


def follow_on_diagnostic(group, continuations, proposal):
    latest = {view.ray.sequence: view.ray for view in group}
    for _, _, view in continuations:
        latest[view.ray.sequence] = view.ray
    rays = tuple(latest.values())
    _, fit_status = (
        fit_position(rays, max_radius=MAX_COARSE_RADIUS_M)
        if len(rays) >= MIN_VIEWS
        else (None, "insufficient_independent_sequences")
    )
    proxy = image_bearing_candidate(rays)
    lon, lat = group[0].coordinates
    conflicts = 0
    if proposal:
        lon, lat = proposal["longitude"], proposal["latitude"]
        point, _ = project([lon], [lat])[0]
        for _, _, view in continuations:
            displacement = subtract(point, view.ray.position)
            if (
                dot(displacement, view.ray.direction)
                < -(view.ray.position_error + (proposal["position_radius_m"] or 0))
                and delta_angle(angle(displacement), view.ray.bearing)
                > 90 + view.ray.angular_error
            ):
                conflicts += 1
    _, rotation = project([lon], [lat])[0]
    return {
        "independent_sequence_count": len(rays),
        "position_fit_status": fit_status,
        "proposal_consistency": "nominal_point_conflicts_with_follow_ons"
        if conflicts
        else None,
        "conflicting_observation_count": conflicts,
        "azimut_deg": (proxy.heading - rotation) % 360 if proxy else None,
        "azimut_method": "latest_per_sequence_reverse_image_ray_proxy"
        if proxy
        else None,
    }


def adjacent_proposal(group, continuations, window, bounds, roads):
    from scripts.inspector.adjacent_sign_pose import estimate_adjacent_pose

    following = defaultdict(list)
    for anchor, _, view in continuations:
        following[anchor["image_id"]].append(view)
    tracks = [
        (view, tuple(following[image]))
        for view in group
        if (image := view.ray.image.removeprefix("panoramax:")) in following
    ]
    result = estimate_adjacent_pose(tracks)
    if result.fit is None:
        return None, result.status, result.diagnostics
    if window.distance(Point(result.fit.point)) > FOLLOW_ON_CONTEXT_M:
        return None, "outside_follow_on_context", result.diagnostics
    proposal = render_proposal(
        result.fit,
        "adjacent_track_review",
        "adjacent_frame_scale_and_optical_rays",
        roads,
    )
    proposal["in_review_window"] = inside(result.fit.point, bounds)
    proposal["independent_sequence_count"] = len(
        {ray.sequence for ray in result.fit.rays}
    )
    return proposal, result.status, result.diagnostics


def build_document(
    records,
    report,
    roads,
    secret,
    *,
    name="Bad Herrenalb",
    center=CENTER,
    sequence_ranks=None,
):
    if len(secret) < 32:
        raise ValueError("review ID key must contain at least 32 private bytes")
    place = place_window(name, center)
    bounds = place["bounds_en_m"]
    place["roads"] = local_roads(roads, bounds)
    place["road_attribution"] = roads.source.get("attribution")
    all_views = load_views(records, report)
    views = [view for view in all_views if inside(view.ray.position, bounds)]
    records_by_key = {"panoramax:" + row["observation_id"]: row for row in records}
    native_by_id = {row["annotation_id"]: row for row in report[1:-1]}
    if len(records_by_key) != len(records) or len(native_by_id) != len(report) - 2:
        raise ValueError("frozen report or rays contain duplicate annotation IDs")

    def serialize(view):
        row = records_by_key[view.ray.key]
        native = native_by_id[row["observation_id"].removeprefix("panoramax:")]
        return observation(view, row, native)

    sequence_ranks = sequence_ranks or {}
    photos_by_rank = {
        (sequence, rank): image for (sequence, image), rank in sequence_ranks.items()
    }
    views_by_photo = defaultdict(list)
    window = box(*bounds)
    if photos_by_rank:
        for view in all_views:
            if window.distance(Point(view.ray.position)) <= FOLLOW_ON_CONTEXT_M:
                views_by_photo[
                    view.ray.image.removeprefix("panoramax:"), view.ray.code
                ].append(view)
    groups, pairs = group_bridges(views)
    output = []
    priorities = {}
    for group in groups:
        observations = []
        continuations = []
        used_photos = {view.ray.image for view in group}
        for view in group:
            row = serialize(view)
            observations.append(row)
            rank = sequence_ranks.get((row["sequence_id"], row["image_id"]))
            if rank is not None:
                row["sequence_rank"] = rank
                for offset, candidate in next_frames(
                    view, row["sequence_id"], rank, photos_by_rank, views_by_photo
                ):
                    if candidate.ray.image in used_photos:
                        break
                    used_photos.add(candidate.ray.image)
                    continuations.append((row, offset, candidate))
        proposal = propose(group, bounds, roads)
        result = {
            "id": sign_token(secret, "place-sign-review-v1", group[0].ray.key),
            "sign_code": group[0].ray.code,
            "observations": observations,
            "proposal": proposal,
        }
        priorities[result["id"]] = group_priority(result)
        if continuations:
            result["follow_on_observations"] = [
                dict(
                    serialize(view),
                    anchor_image_id=anchor["image_id"],
                    sequence_rank=anchor["sequence_rank"] + offset,
                    frame_offset=offset,
                    in_review_window=inside(view.ray.position, bounds),
                )
                for anchor, offset, view in continuations
            ]
            diagnostic = follow_on_diagnostic(group, continuations, proposal)
            adjacent, status, details = adjacent_proposal(
                group, continuations, window, bounds, roads
            )
            diagnostic["adjacent_track_status"] = status
            diagnostic["adjacent_track_diagnostics"] = details
            result["follow_on_diagnostic"] = diagnostic
            if diagnostic["conflicting_observation_count"]:
                result["challenged_proposal"] = proposal
                result["proposal"] = None
            if adjacent is not None:
                result["proposal"] = adjacent
        output.append(result)
    output.sort(key=lambda group: priorities[group["id"]])
    positions = Counter(
        group["proposal"]["position_status"] if group["proposal"] else "unresolved"
        for group in output
    )
    return {
        "schema_version": 1,
        "place": place,
        "default_group_id": output[0]["id"] if output else None,
        "groups": output,
        "summary": {
            "source_snapshot_at": report[0]["corpus_crop_snapshot_at"],
            "camera_views_in_window": len(views),
            "camera_images_in_window": len({view.ray.image for view in views}),
            "groups": len(output),
            "groups_with_proposal": len(output) - positions["unresolved"],
            "position_status_counts": dict(sorted(positions.items())),
            **(
                {
                    "groups_with_follow_ons": sum(
                        bool(group.get("follow_on_observations")) for group in output
                    ),
                    "follow_on_observations": sum(
                        len(group.get("follow_on_observations", ())) for group in output
                    ),
                }
                if sequence_ranks
                else {}
            ),
            **pairs,
        },
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rays", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--road-graph", type=Path, required=True)
    parser.add_argument(
        "--sequence-ranks",
        type=Path,
        help="Private authoritative Panoramax picture ranks",
    )
    parser.add_argument("--id-key-file", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--mobile-rays", type=Path, action="append", default=[],
                        help="Optional private mobile JSON Lines for proposed close-time evidence links")
    parser.add_argument("--mobile-bindings", type=Path,
                        help="Private current source bindings keyed by mobile observation ID")
    parser.add_argument("--mobile-collection", type=Path,
                        help="Complete private place collection with rays and source bindings")
    parser.add_argument(
        "--mobidata-inventory", type=Path,
        help="Optional SQLite inventory for same-class MobiData reference candidates within 30 m",
    )
    parser.add_argument("--place-name", help="Place name for a custom center")
    parser.add_argument("--center", nargs=2, type=float, metavar=("LON", "LAT"))
    args = parser.parse_args()
    if bool(args.place_name) != (args.center is not None):
        parser.error("--place-name and --center must be supplied together")
    records, report = frozen_sources(args.rays, args.report)
    document = build_document(
        records,
        report,
        RoadHeadingIndex.load(args.road_graph),
        read_private(args.id_key_file, 4096),
        name=args.place_name or "Bad Herrenalb",
        center=tuple(args.center) if args.center else CENTER,
        sequence_ranks=read_sequence_ranks(args.sequence_ranks)
        if args.sequence_ranks
        else None,
    )
    if args.mobidata_inventory:
        from scripts.inspector.match_place_sign_inventory import attach_inventory_matches

        attach_inventory_matches(document, args.mobidata_inventory)
    if args.mobile_rays or args.mobile_collection:
        from scripts.inspector.link_place_mobile_evidence import attach_collection_context, attach_mobile_evidence
        from scripts.inspector.refine_place_sign_pose import attach_refinements

        if args.mobile_collection:
            collection = json.loads(read_private(args.mobile_collection, MAX_PRIVATE_INPUT_BYTES))
            rows, bindings = collection["rays"], collection["bindings"]
        else:
            collection = {}
            rows = [json.loads(line) for path in args.mobile_rays
                    for line in read_private(path, MAX_PRIVATE_INPUT_BYTES).splitlines() if line.strip()]
            bindings = json.loads(read_private(args.mobile_bindings, MAX_PRIVATE_INPUT_BYTES)) if args.mobile_bindings else None
        attach_mobile_evidence(document, rows, bindings)
        attach_refinements(document)
        if collection:
            attach_collection_context(document, collection)
    write_private_json(args.output, document)
    print(json.dumps(document["summary"], sort_keys=True))


if __name__ == "__main__":
    main()
