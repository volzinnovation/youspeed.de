"""Refine private place-review poses using distinct mobile camera views."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import math

from fiona.transform import transform
from shapely import minimum_bounding_circle
from shapely.geometry import Polygon

from scripts.inspector.adjacent_sign_pose import _Frame, _ray_constraints
from scripts.tsr.collection.estimate_sign_poses import (
    MAX_RANGE_M, MAX_RAY_POSITION_ERROR_M, METRIC, MIN_RANGE_M, WGS84, Ray,
    cross, delta_angle, dot, fit_position, image_bearing_candidate, project, subtract,
)
from scripts.tsr.collection.triangulate_sign_position import MAX_RAYS, _clip


def timestamp(value):
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def measure(group, observation, source):
    captured = timestamp(observation["captured_at"]).isoformat().replace("+00:00", "Z")
    key = observation.get("annotation_id") or observation["evidence_id"]
    record = {
        "source": source, "observation_id": key,
        "image_id": observation.get("image_id") or key,
        "sequence_id": observation["sequence_id"], "fix_id": observation.get("fix_id"),
        "captured_at": captured, "pose_basis": "assumed", "sign_code": group["sign_code"],
        "bearing_degrees": observation["bearing_deg"],
        "bearing_error_deg": observation["bearing_error_deg"],
        "horizontal_error_m": observation["horizontal_error_m"],
    }
    if observation.get("fix_at"):
        record["fix_at"] = timestamp(observation["fix_at"]).isoformat().replace("+00:00", "Z")
    point, rotation = project([observation["longitude"]], [observation["latitude"]])[0]
    return Ray.parse(record, point, rotation)


def distinct_views(group):
    """Collapse shared frames/fixes and nearby captures from one linked drive."""
    observations = group["observations"] + group.get("follow_on_observations", [])
    views, matched = [], {}
    for observation in observations:
        try:
            ray = measure(group, observation, "panoramax")
        except (ValueError, TypeError, KeyError):
            continue
        views.append((ray, None))
        matched[observation["annotation_id"]] = ray
    parents = {}

    def find(sequence):
        while sequence in parents:
            sequence = parents[sequence]
        return sequence

    for observation in group.get("mobile_observations", []):
        if observation.get("gallery_only"):
            continue
        link = observation["association"]
        if link["candidate_group_ids"] != [group["id"]]:
            continue
        anchor = matched.get(link["matched_annotation_id"])
        if not anchor or not 0 < observation["horizontal_error_m"] <= MAX_RAY_POSITION_ERROR_M:
            continue
        try:
            ray = measure(group, observation, "mobile")
        except (ValueError, TypeError, KeyError):
            continue
        first, second = find(ray.sequence), find(anchor.sequence)
        if first != second and link["independence_status"] == "same_capture_or_drive_possible":
            parents[first] = second
        views.append((ray, observation["evidence_id"]))

    kept, duplicates = [], 0
    # Keep existing Panoramax constraints when a mobile record repeats that view.
    for ray, identifier in sorted(views, key=lambda entry: (
        entry[1] is not None, entry[0].position_error, entry[0].angular_error, entry[0].key
    )):
        ray = replace(ray, sequence=find(ray.sequence))
        if any(
            ray.image == other.image or ray.fix == other.fix
            or (ray.sequence == other.sequence and (
                abs((timestamp(ray.captured_at) - timestamp(other.captured_at)).total_seconds()) <= .25
                or math.dist(ray.position, other.position) < 3
            ))
            for other, _ in kept
        ):
            duplicates += identifier is not None
            continue
        kept.append((ray, identifier))
    return kept, duplicates


def supports_position(ray, point):
    offset = subtract(point, ray.position)
    forward = dot(ray.direction, offset)
    angle = math.radians(ray.angular_error)
    allowance = ray.position_error / math.cos(angle) + forward * math.tan(angle)
    return (
        forward >= MIN_RANGE_M and math.hypot(*offset) <= MAX_RANGE_M
        and abs(cross(ray.direction, offset)) <= allowance + .001
    )


def narrow_existing(point, radius, mobile):
    """Intersect the existing conditional envelope with new camera constraints."""
    if not radius:
        return None
    outer = radius / math.cos(math.pi / 64)
    region = [(outer * math.cos(i * math.tau / 64), outer * math.sin(i * math.tau / 64))
              for i in range(64)]
    original_area = Polygon(region).area
    for ray in mobile:
        center = tuple(value - origin for value, origin in zip(ray.position, point))
        for normal, offset in _ray_constraints(_Frame(ray, center, ray.direction, 1)):
            region = _clip(region, normal, offset)
            if len(region) < 3:
                return None
    polygon = Polygon(region)
    if polygon.area >= original_area * .99:
        return None
    center = tuple(minimum_bounding_circle(polygon).centroid.coords[0])
    updated = tuple(origin + offset for origin, offset in zip(point, center))
    if not all(supports_position(ray, updated) for ray in mobile):
        return None
    updated_radius = max(math.dist(center, vertex) for vertex in region)
    return (updated, updated_radius) if updated_radius < radius else None


def refine_group(group):
    if not group.get("mobile_observations"):
        return None
    before = group.get("proposal")
    views, duplicates = distinct_views(group)
    mobile = [ray for ray, identifier in views if identifier]
    info = {"status": "insufficient_distinct_views", "duplicate_mobile_count": duplicates,
            "mobile_evidence_ids": []}
    if not mobile or len({ray.sequence for ray, _ in views}) < 2:
        return info

    point, radius, original_point = None, None, None
    if before:
        original_point, _ = project([before["longitude"]], [before["latitude"]])[0]
        point, radius = original_point, before.get("position_radius_m")
    if point is not None and radius:
        compatible = [ray for ray in mobile if supports_position(ray, point)]
        result = narrow_existing(point, radius, compatible)
        if result:
            point, radius = result
    elif 3 <= len(views) <= MAX_RAYS:
        fit, _ = fit_position(tuple(ray for ray, _ in views), max_radius=40)
        if (fit and any(ray in fit.rays for ray in mobile)
                and len({ray.sequence for ray in fit.rays}) >= 2
                and (point is None or math.dist(point, fit.point) <= 30)):
            point, radius = fit.point, fit.radius
            views = [(ray, identifier) for ray, identifier in views if ray in fit.rays]
    if point is None:
        return info
    used = [(ray, identifier) for ray, identifier in views if supports_position(ray, point)]
    identifiers = sorted(identifier for _, identifier in used if identifier)
    if not identifiers or len({ray.sequence for ray, _ in used}) < 2:
        return info

    longitude, latitude = (axis[0] for axis in transform(METRIC, WGS84, [point[0]], [point[1]]))
    _, rotation = project([longitude], [latitude])[0]
    proxy = image_bearing_candidate([ray for ray, _ in used])
    old_heading = before.get("azimut_deg") if before else None
    heading = old_heading
    if proxy and proxy.spread <= 45:
        candidate = (proxy.heading - rotation) % 360
        if old_heading is None or delta_angle(old_heading, candidate) <= 30:
            heading = candidate
    movement = math.dist(original_point, point) if original_point else None
    turn = delta_angle(old_heading, heading) if old_heading is not None and heading is not None else None
    heading_changed = heading is not None and (turn is None or turn >= .05)
    old_radius = before.get("position_radius_m") if before else None
    radius_changed = radius is not None and (old_radius is None or radius < old_radius - .05)
    if before and movement < .05 and not heading_changed and not radius_changed:
        return {**info, "status": "no_material_change"}
    return {
        **info, "status": "refined", "mobile_evidence_ids": identifiers,
        "movement_m": movement, "azimut_change_deg": turn,
        "drive_count": len({ray.sequence for ray, _ in used}),
        "proposal": {
            "longitude": longitude, "latitude": latitude, "position_radius_m": radius,
            "position_status": "mobile_refinement", "azimut_deg": heading,
            "azimut_method": "sequence_balanced_image_proxy" if heading_changed else (
                before.get("azimut_method") if before else None
            ),
        },
    }


def attach_refinements(document):
    for group in document["groups"]:
        group.pop("mobile_refinement", None)
        result = refine_group(group)
        if result:
            group["mobile_refinement"] = result
    return document
