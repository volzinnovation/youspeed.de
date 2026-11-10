"""Direction evidence from independent camera geotags along a selected road."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
import math

MAX_FRAME_GAP_S = 12.0
MAX_TRAJECTORY_DURATION_S = 24.0
MAX_SPEED_MPS = 55.0
MIN_EFFECTIVE_BASELINE_M = 8.0
MAX_TRAJECTORY_ANGLE_DEG = 40.0
MAX_LOCAL_BEND_DEG = 20.0
MAX_FRONT_RAY_ANGLE_DEG = 85.0


@dataclass(frozen=True)
class ApproachEvidence:
    travel: str
    front_azimuth_grid_deg: float
    travel_bearing_grid_deg: float
    method: str
    sequence_count: int
    image_count: int
    trajectory_error_deg: float
    image_groups: tuple[tuple[str, ...], ...]


@dataclass(frozen=True)
class Segment:
    start: tuple[float, float]
    direction: tuple[float, float]
    length: float
    chainage: float


@dataclass(frozen=True)
class Projection:
    distance: float
    chainage: float
    tangent: float


def _subtract(a, b):
    return a[0] - b[0], a[1] - b[1]


def _dot(a, b):
    return a[0] * b[0] + a[1] * b[1]


def _bearing(direction):
    return math.degrees(math.atan2(*direction)) % 360


def _vector(bearing):
    radians = math.radians(bearing)
    return math.sin(radians), math.cos(radians)


def _delta(a, b):
    return abs((a - b + 180) % 360 - 180)


def _segments(points):
    chainage = 0.0
    result = []
    for start, end in zip(points, points[1:]):
        x, y = _subtract(end, start)
        length = math.hypot(x, y)
        if length > 0:
            result.append(Segment(start, (x / length, y / length), length, chainage))
            chainage += length
    return result


def _project(point, segments, map_error):
    candidates = []
    for segment in segments:
        east, north = _subtract(point, segment.start)
        distance_along = _dot((east, north), segment.direction)
        progress = min(segment.length, max(0.0, distance_along))
        dx, dy = segment.direction
        distance = math.hypot(east - dx * progress, north - dy * progress)
        candidates.append(
            Projection(
                distance, segment.chainage + progress, _bearing(segment.direction)
            )
        )
    best = min(candidates, key=lambda item: item.distance)
    # Reject distinct near-matches on a self-crossing/returning road or at a bend.
    # Adjacent collinear fragments of the same corridor remain usable.
    if any(
        candidate.distance <= best.distance + map_error
        and (
            abs(candidate.chainage - best.chainage) > max(8.0, 2 * map_error)
            or _delta(candidate.tangent, best.tangent) > MAX_LOCAL_BEND_DEG
        )
        for candidate in candidates
    ):
        return None
    return best


def _capture_time(ray):
    try:
        value = datetime.fromisoformat(ray.captured_at.replace("Z", "+00:00"))
        return value.timestamp() if value.tzinfo is not None else None
    except (AttributeError, OverflowError, ValueError):
        return None


def _tracks(rays):
    groups = defaultdict(list)
    for ray in rays:
        sequence = getattr(ray, "sequence", None)
        if sequence is None:
            continue
        timestamp = _capture_time(ray)
        if timestamp is not None:
            groups[ray.source, sequence].append((timestamp, ray))

    for rows in groups.values():
        # Exact repeat frame/fix cannot make a new trajectory sample.
        rows.sort(key=lambda row: (row[0], row[1].position_error, row[1].image))
        distinct = []
        images, fixes = set(), set()
        for timestamp, ray in rows:
            if ray.image in images or ray.fix in fixes:
                continue
            images.add(ray.image)
            fixes.add(ray.fix)
            distinct.append((timestamp, ray))
        if len(distinct) >= 2:
            yield distinct


def _track_direction(rows, fit, segments, tangent, corridor, map_error):
    times, rays = zip(*rows)
    duration = times[-1] - times[0]
    if not 0 < duration <= MAX_TRAJECTORY_DURATION_S or any(
        not 0 < b - a <= MAX_FRAME_GAP_S for a, b in zip(times, times[1:])
    ):
        return None
    projections = [_project(ray.position, segments, map_error) for ray in rays]
    if any(
        projection is None
        or projection.distance > corridor + map_error
        or _delta(projection.tangent, tangent) > MAX_LOCAL_BEND_DEG
        for projection in projections
    ):
        return None

    start, end = projections[0], projections[-1]
    minimum, maximum = sorted((start.chainage, end.chainage))
    if any(
        segment.chainage < maximum
        and segment.chainage + segment.length > minimum
        and _delta(_bearing(segment.direction), tangent) > MAX_LOCAL_BEND_DEG
        for segment in segments
    ):
        return None
    road_progress = end.chainage - start.chainage
    direction = 1 if road_progress > 0 else -1
    chord = _subtract(rays[-1].position, rays[0].position)
    distance = math.hypot(*chord)
    endpoint_error = rays[0].position_error + rays[-1].position_error
    if (
        abs(road_progress) < endpoint_error + MIN_EFFECTIVE_BASELINE_M
        or distance < endpoint_error + MIN_EFFECTIVE_BASELINE_M
        or distance - endpoint_error > MAX_SPEED_MPS * duration
    ):
        return None

    travel = (tangent + (180 if direction < 0 else 0)) % 360
    travel_vector = _vector(travel)
    trajectory_error = _delta(_bearing(chord), travel) + math.degrees(
        math.asin(endpoint_error / distance)
    )
    if trajectory_error > MAX_TRAJECTORY_ANGLE_DEG:
        return None
    for i, (before, after) in enumerate(zip(rays, rays[1:])):
        allowed_jitter = before.position_error + after.position_error
        progress = projections[i + 1].chainage - projections[i].chainage
        movement = _subtract(after.position, before.position)
        step = math.hypot(*movement)
        if (
            direction * progress < -allowed_jitter
            or step - allowed_jitter > MAX_SPEED_MPS * (times[i + 1] - times[i])
        ):
            return None
        if step > allowed_jitter + 4:
            uncertainty = math.degrees(math.asin(allowed_jitter / step))
            if (
                _delta(_bearing(movement), travel) - uncertainty
                > MAX_TRAJECTORY_ANGLE_DEG
            ):
                return None

    definitely_upstream = False
    for ray in rays:
        ahead = _dot(_subtract(fit.point, ray.position), travel_vector)
        point_error = fit.radius + ray.position_error + map_error
        sightline = _delta(_bearing(ray.direction), travel)
        # No camera can be clearly past the estimated face or looking back
        # while its sequence is claimed to be approaching it.
        if ahead < -point_error or sightline - ray.angular_error > 90:
            return None
        definitely_upstream |= (
            ahead > point_error
            and sightline + ray.angular_error <= MAX_FRONT_RAY_ANGLE_DEG
        )
    if not definitely_upstream:
        return None
    return (
        direction,
        len(rays),
        trajectory_error,
        _bearing(chord),
        tuple(ray.image for ray in rays),
    )


def image_approach(fit, road_points, tangent_deg, *, corridor_m=8.0, map_error_m=3.0):
    """Compare same-sequence camera displacement with a chosen road's tangent.

    Road points and fit use the same projected east/north frame. The tangent
    follows the original order of the supplied road vertices.
    This helper does not select the governing road, infer sign class, resolve
    access/oneway rules or assert a calibrated front-normal error interval.
    An image pair is weaker evidence than a track of three or more frames.
    """
    if not (
        math.isfinite(tangent_deg) and 0 < corridor_m <= 30 and 0 <= map_error_m <= 15
    ):
        raise ValueError("invalid image-approach road policy")
    segments = _segments(road_points)
    if not segments:
        return None
    at_sign = _project(fit.point, segments, map_error_m)
    if at_sign is None or _delta(at_sign.tangent, tangent_deg) > MAX_LOCAL_BEND_DEG:
        return None
    votes = [
        vote
        for track in _tracks(fit.rays)
        if (
            vote := _track_direction(
                track, fit, segments, tangent_deg, corridor_m, map_error_m
            )
        )
        is not None
    ]
    directions = {direction for direction, _, _, _, _ in votes}
    if len(directions) != 1:
        return None
    direction = next(iter(directions))
    image_count = sum(count for _, count, _, _, _ in votes)
    strong = len(votes) >= 2 or any(count >= 3 for _, count, _, _, _ in votes)
    best = min(votes, key=lambda vote: (vote[2], -vote[1], vote[3]))
    return ApproachEvidence(
        travel="forward" if direction > 0 else "backward",
        front_azimuth_grid_deg=(tangent_deg + (180 if direction > 0 else 0)) % 360,
        travel_bearing_grid_deg=best[3],
        method="image_sequence_approach" if strong else "image_pair_approach",
        sequence_count=len(votes),
        image_count=image_count,
        trajectory_error_deg=max(error for _, _, error, _, _ in votes),
        image_groups=tuple(images for _, _, _, _, images in votes),
    )
