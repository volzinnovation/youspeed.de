"""Match detections from nearby Panoramax passes for private sign review."""

from __future__ import annotations

from collections import Counter, defaultdict
from dataclasses import dataclass
import math

from shapely.geometry import Point
from shapely.strtree import STRtree

from scripts.tsr.collection.estimate_sign_poses import (
    MAX_PAIRS_PER_CLASS,
    MAX_POSITION_RADIUS_M,
    MIN_VIEWS,
    Ray,
    delta_angle,
    estimate,
    fit_position,
    heading_interval,
    image_bearing_candidate,
    independent,
    project,
)
from scripts.tsr.collection.sign_identities import sign_token


MAX_CAMERA_DISTANCE_M = 20
MAX_CAMERA_HEADING_DELTA_DEG = 30
MAX_COARSE_RADIUS_M = 40
MAX_HOLDOUT_SHIFT_M = 5


@dataclass(frozen=True)
class BridgeView:
    ray: Ray
    camera_heading: float
    angular_height: float
    coordinates: tuple[float, float]


def load_views(records, report):
    from scripts.youspeed.panoramax_rays import numeric, registered_box

    if not report or report[0].get("record_type") != "corpus_metadata":
        raise ValueError("sequence bridges require an authoritative Panoramax report")
    if report[-1] != {"record_type": "corpus_complete", "source_rows": len(report) - 2}:
        raise ValueError("Panoramax report is incomplete")
    annotation_rows = {
        "panoramax:" + row["annotation_id"]: row
        for row in report[1:-1]
        if row.get("source_id") == "panoramax.woladen.de"
    }
    records = sorted(
        (row for row in records if row["source"] == "panoramax"),
        key=lambda row: row["observation_id"],
    )
    if not records:
        return []
    points = project(
        [row["longitude"] for row in records], [row["latitude"] for row in records]
    )
    views = []
    for row, (point, rotation) in zip(records, points):
        native = annotation_rows.get(row["observation_id"])
        if native is None or native["picture_id"] != row["image_id"]:
            raise ValueError(
                "bridge report must match the qualified annotation and image IDs"
            )
        if row["sequence_id"] not in {item["id"] for item in native["collections"]}:
            raise ValueError("bridge report sequence differs from the qualified ray")
        picture = native["picture"]
        coordinates = tuple(picture["geometry"]["coordinates"][:2])
        if math.dist(coordinates, (row["longitude"], row["latitude"])) > 1e-7:
            raise ValueError(
                "bridge report camera point differs from the qualified ray"
            )
        metadata = picture["metadata"]
        width, height, _, top, _, bottom = registered_box(native, metadata)
        if row.get("pose_method") == "gpano_full_sphere_pose":
            heading = numeric(picture["exif"].get("Xmp.GPano.PoseHeadingDegrees"))
            angular_height = (bottom - top) * 180 / height
        else:
            heading = numeric(picture.get("heading"))
            fov = numeric(metadata.get("field_of_view"))
            if fov is None or not 45 <= fov <= 100:
                raise ValueError(
                    "bridge report is missing the qualified horizontal FOV"
                )
            focal_px = width / (2 * math.tan(math.radians(fov / 2)))
            angular_height = math.degrees(
                2 * math.atan((bottom - top) / (2 * focal_px))
            )
        if heading is None or not 0 <= heading <= 360:
            raise ValueError("bridge report is missing the qualified camera heading")
        views.append(
            BridgeView(
                Ray.parse(row, point, rotation),
                heading % 360,
                angular_height,
                coordinates,
            )
        )
    return views


def group_bridges(views):
    """Build complete-link groups, with no repeated sequence or competing image."""
    classes = defaultdict(list)
    for view in views:
        classes[view.ray.code].append(view)
    stats = Counter()
    groups = []
    for class_views in classes.values():
        class_views.sort(key=lambda view: view.ray.key)
        points = [Point(view.ray.position) for view in class_views]
        index = STRtree(points)
        candidates = []
        frame_counts = Counter()
        tested_pairs = 0
        for i, first in enumerate(class_views):
            for j in index.query(
                points[i], predicate="dwithin", distance=MAX_CAMERA_DISTANCE_M
            ):
                second = class_views[j]
                if j <= i:
                    continue
                tested_pairs += 1
                if tested_pairs > MAX_PAIRS_PER_CLASS:
                    raise ValueError(
                        "too many nearby same-class images; use a smaller survey area"
                    )
                if (
                    first.ray.sequence == second.ray.sequence
                    or first.ray.image == second.ray.image
                ):
                    continue
                distance = math.dist(first.ray.position, second.ray.position)
                yaw_delta = delta_angle(first.camera_heading, second.camera_heading)
                if (
                    distance >= MAX_CAMERA_DISTANCE_M
                    or yaw_delta > MAX_CAMERA_HEADING_DELTA_DEG
                ):
                    continue
                stats["camera_rule_pairs"] += 1
                bearing_delta = delta_angle(first.ray.bearing, second.ray.bearing)
                scale_ratio = max(first.angular_height, second.angular_height) / min(
                    first.angular_height, second.angular_height
                )
                if bearing_delta > 30 or scale_ratio > 2.5:
                    continue
                frame_counts[i, second.ray.image] += 1
                frame_counts[j, first.ray.image] += 1
                candidates.append(
                    (distance, yaw_delta, bearing_delta, scale_ratio, i, j)
                )

        unique = [
            candidate
            for candidate in candidates
            if frame_counts[candidate[-2], class_views[candidate[-1]].ray.image] == 1
            and frame_counts[candidate[-1], class_views[candidate[-2]].ray.image] == 1
        ]
        edges = {(i, j) for *_, i, j in unique}
        stats["unambiguous_box_pairs"] += len(edges)
        partitions = {i: {i} for i in range(len(class_views))}
        owners = list(partitions)
        for *_, i, j in sorted(unique):
            first, second = owners[i], owners[j]
            if first == second or not all(
                (min(a, b), max(a, b)) in edges
                for a in partitions[first]
                for b in partitions[second]
            ):
                continue
            for member in partitions[second]:
                owners[member] = first
            partitions[first].update(partitions.pop(second))
        groups.extend(
            tuple(class_views[i] for i in sorted(group))
            for group in partitions.values()
            if len(group) >= 2
        )
    return groups, dict(stats)


def stable_across_sequences(fit):
    """Check usable leave-one-sequence-out fits without shrinking input errors."""
    tested = False
    for sequence in {ray.sequence for ray in fit.rays}:
        retained = tuple(ray for ray in fit.rays if ray.sequence != sequence)
        if len(retained) < MIN_VIEWS:
            continue
        alternate, _ = fit_position(retained, max_radius=MAX_COARSE_RADIUS_M)
        if alternate is not None:
            tested = True
            if math.dist(fit.point, alternate.point) > MAX_HOLDOUT_SHIFT_M:
                return False
    return tested


def bridge_positions(groups):
    for group in groups:
        rays = independent([view.ray for view in group])
        if len(rays) < MIN_VIEWS:
            continue
        fit, _ = fit_position(rays, max_radius=MAX_COARSE_RADIUS_M)
        if fit is None or (
            fit.radius > MAX_POSITION_RADIUS_M and not stable_across_sequences(fit)
        ):
            continue
        yield fit.rays[0].code, fit, heading_interval(fit)


def add_distinct_positions(estimates, proposed):
    """Preserve bounded positions and avoid double-counting nearby same-facing fits."""
    added = []
    for code, fit, heading in sorted(
        proposed,
        key=lambda item: (
            item[1].radius > MAX_POSITION_RADIUS_M,
            -len(item[1].rays),
            item[1].radius,
            item[1].keys,
        ),
    ):
        facing = image_bearing_candidate(fit.rays)
        if any(
            other_code == code
            and (
                set(fit.keys).intersection(other.keys)
                or (
                    math.dist(fit.point, other.point) < 20
                    and facing is not None
                    and (other_facing := image_bearing_candidate(other.rays))
                    is not None
                    and delta_angle(facing.heading, other_facing.heading) <= 30
                )
            )
            for other_code, other, _ in (*estimates, *added)
        ):
            continue
        added.append((code, fit, heading))
    return added


def rebuild_positions(records, report, strict):
    groups, diagnostics = group_bridges(load_views(records, report))
    coherent = [item for item in strict if image_bearing_candidate(item[1].rays)]
    wider, _ = estimate(records, max_radius=MAX_COARSE_RADIUS_M)
    coarse = (
        item
        for item in wider
        if item[1].radius > MAX_POSITION_RADIUS_M
        and image_bearing_candidate(item[1].rays)
        and stable_across_sequences(item[1])
    )
    proposed = [*bridge_positions(groups), *coarse]
    added = add_distinct_positions(coherent, proposed)
    diagnostics.update(
        strict_positions_withheld_for_viewing_conflict=len(strict) - len(coherent),
        additional_position_candidates=len(added),
    )
    return coherent + added, groups, diagnostics


def bridge_features(groups, boundaries, municipality, sign_by_ray, secret):
    features = []
    for group in groups:
        if not any(
            municipality
            in boundaries.memberships(*view.coordinates).get("gemeinde_ags", ())
            for view in group
        ):
            continue
        first = group[0]
        identifier = sign_token(secret, "panoramax-sequence-bridge-v1", first.ray.key)
        possible_signs = Counter(
            sign_by_ray[view.ray.key] for view in group if view.ray.key in sign_by_ray
        )
        sign_id = None
        if len(possible_signs) == 1:
            candidate, support = possible_signs.most_common(1)[0]
            if support >= 2:
                sign_id = candidate
        features.append(
            {
                "type": "Feature",
                "id": f"sequence-bridge.{identifier}",
                "geometry": {
                    "type": "MultiPoint",
                    "coordinates": [view.coordinates for view in group],
                },
                "properties": {
                    "id": identifier,
                    "stvo_nr": first.ray.code[3:],
                    "position_status": "linked_sign_estimate"
                    if sign_id
                    else "unresolved",
                    "geometry_role": "camera_positions",
                    "sequence_count": len(group),
                    "sign_id": sign_id,
                },
            }
        )
    return sorted(features, key=lambda feature: feature["id"])
