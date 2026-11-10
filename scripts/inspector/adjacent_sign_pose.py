"""Private localization from adjacent-frame scale change and forward sightlines."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import math

from scripts.tsr.collection.estimate_sign_poses import (
    MAX_RANGE_M,
    MIN_RANGE_M,
    Fit,
    Ray,
    dot,
    project,
    subtract,
    vector,
)
from scripts.tsr.collection.triangulate_sign_position import _clip


SCALE_RATIO_ALLOWANCE = 0.25
MAX_TRACK_CENTER_OFFSET_M = 18
MAX_ADJACENT_RADIUS_M = 40
MAX_SEQUENCES = 64
MAX_FRAMES_PER_SEQUENCE = 3


@dataclass(frozen=True)
class AdjacentPose:
    fit: Fit | None
    status: str
    diagnostics: dict


@dataclass(frozen=True)
class _Frame:
    ray: Ray
    center: tuple[float, float]
    axis: tuple[float, float]
    scale: float


@dataclass(frozen=True)
class _Pair:
    point: tuple[float, float]
    residual: float
    sensitivity: float
    constraints: tuple


@dataclass(frozen=True)
class _Track:
    frames: tuple[_Frame, ...]
    pairs: tuple[_Pair, ...]
    point: tuple[float, float]
    constraints: tuple


def _scaled(components, factor):
    return tuple(factor * value for value in components)


def _along(center, direction, distance):
    return tuple(
        origin + component * distance for origin, component in zip(center, direction)
    )


def _ray_constraints(frame):
    theta = math.radians(frame.ray.bearing)
    allowance = math.radians(frame.ray.angular_error)
    left, right = theta - allowance, theta + allowance
    normals = (
        (-math.cos(left), math.sin(left)),
        (math.cos(right), -math.sin(right)),
        _scaled(frame.ray.direction, -1),
    )
    return tuple(
        (normal, dot(normal, frame.center) + frame.ray.position_error)
        for normal in normals
    )


def _pair(first, second):
    a, b = first.ray, second.ray
    if (
        a.sequence != b.sequence
        or a.code != b.code
        or a.image == b.image
        or a.fix == b.fix
    ):
        return None
    earlier = datetime.fromisoformat(a.captured_at.replace("Z", "+00:00"))
    later = datetime.fromisoformat(b.captured_at.replace("Z", "+00:00"))
    elapsed = (later - earlier).total_seconds()
    movement = subtract(second.center, first.center)
    if not 0 < elapsed <= 8 or not 2 <= math.hypot(*movement) <= 50:
        return None
    if not second.scale > first.scale > 0:
        return None
    ratio = first.scale / second.scale
    cosine_a = dot(a.direction, first.axis)
    cosine_b = dot(b.direction, second.axis)
    if not 0.15 <= ratio <= 0.9 or min(cosine_a, cosine_b) < 0.5:
        return None

    # A fixed panel's normalized apparent height is proportional to 1/z,
    # where z is its axial depth. Convert the depth ratio to a ray-range ratio.
    range_ratio = ratio * cosine_a / cosine_b
    difference = subtract(a.direction, _scaled(b.direction, range_ratio))
    leverage = math.hypot(*difference)
    if leverage < 0.1:
        return None
    first_range = dot(movement, difference) / leverage**2
    second_range = range_ratio * first_range
    if not MIN_RANGE_M <= second_range <= first_range <= MAX_RANGE_M:
        return None
    position_a = _along(first.center, a.direction, first_range)
    position_b = _along(second.center, b.direction, second_range)
    residual = math.dist(position_a, position_b)
    if residual > 8:
        return None
    point = tuple((x + y) / 2 for x, y in zip(position_a, position_b))
    sensitivity = (
        a.position_error + b.position_error + SCALE_RATIO_ALLOWANCE * second_range
    ) / leverage

    # Bound z1/z0 using an explicit scale allowance and outward expansion for
    # the camera GPS disks. The result remains conditional on the nominal axes.
    low = ratio * (1 - SCALE_RATIO_ALLOWANCE)
    high = ratio * (1 + SCALE_RATIO_ALLOWANCE)
    constraints = (
        (
            subtract(second.axis, _scaled(first.axis, high)),
            dot(second.axis, second.center)
            - high * dot(first.axis, first.center)
            + b.position_error
            + high * a.position_error,
        ),
        (
            subtract(_scaled(first.axis, low), second.axis),
            low * dot(first.axis, first.center)
            - dot(second.axis, second.center)
            + low * a.position_error
            + b.position_error,
        ),
    )
    return _Pair(point, residual, sensitivity, constraints)


def _track(frames):
    pairs = []
    for first, second in zip(frames, frames[1:]):
        pair = _pair(first, second)
        if pair is None:
            break
        pairs.append(pair)
    if not pairs:
        return None
    frames = frames[: len(pairs) + 1]
    best = min(pairs, key=lambda pair: (pair.sensitivity, pair.residual))
    constraints = tuple(
        [constraint for frame in frames for constraint in _ray_constraints(frame)]
        + [constraint for pair in pairs for constraint in pair.constraints]
    )
    return _Track(frames, tuple(pairs), best.point, constraints)


def _supports(track, point):
    if math.dist(track.point, point) > MAX_TRACK_CENTER_OFFSET_M:
        return False
    if any(dot(normal, point) > offset + 1e-8 for normal, offset in track.constraints):
        return False
    return all(
        dot(subtract(point, frame.center), frame.ray.direction) >= MIN_RANGE_M
        and math.dist(point, frame.center) <= MAX_RANGE_M
        for frame in track.frames
    )


def _region(tracks):
    x, y = zip(*(frame.center for track in tracks for frame in track.frames))
    west, south = min(x) - MAX_RANGE_M, min(y) - MAX_RANGE_M
    east, north = max(x) + MAX_RANGE_M, max(y) + MAX_RANGE_M
    polygon = [(west, south), (east, south), (east, north), (west, north)]
    for track in tracks:
        for normal, offset in track.constraints:
            polygon = _clip(polygon, normal, offset)
    clipped = any(
        min(abs(x - west), abs(x - east), abs(y - south), abs(y - north)) < 1e-6
        for x, y in polygon
    )
    return polygon, clipped


def estimate_adjacent_pose(continuations, bounds=None):
    """Fit verified rank-adjacent BridgeView chains, with one vote per sequence.

    Each entry is (anchor_view, tuple(follow_on_views)). The caller establishes
    consecutive ranks and disambiguates same-class boxes in each image. Radius
    is an envelope conditional on the nominal axes and the scale allowance,
    not a statistical confidence interval.
    """
    chains = [(anchor, *tail) for anchor, tail in continuations if tail]
    if len(chains) > MAX_SEQUENCES or any(
        len(chain) > MAX_FRAMES_PER_SEQUENCE for chain in chains
    ):
        raise ValueError("too many adjacent frames for one sign group")
    if (
        len({chain[0].ray.sequence for chain in chains}) != len(chains)
        or len({chain[0].ray.code for chain in chains}) > 1
    ):
        raise ValueError(
            "adjacent pose requires one chain per sequence for one sign class"
        )
    diagnostics = {
        "input_sequence_count": len(chains),
        "input_pair_count": sum(len(chain) - 1 for chain in chains),
        "eligible_sequence_count": 0,
        "support_sequence_count": 0,
        "support_pair_count": 0,
        "relative_scale_ratio_allowance": SCALE_RATIO_ALLOWANCE,
        "radius_basis": "conditional_on_nominal_camera_axes_and_declared_bounds",
    }
    if len(chains) < 2:
        return AdjacentPose(None, "insufficient_adjacent_sequences", diagnostics)
    chains.sort(key=lambda chain: chain[0].ray.sequence)
    coordinates = [view.coordinates for chain in chains for view in chain]
    rotations = iter(rotation for _, rotation in project(*map(list, zip(*coordinates))))
    origin = chains[0][0].ray.position
    tracks = []
    for chain in chains:
        frames = tuple(
            _Frame(
                view.ray,
                subtract(view.ray.position, origin),
                vector(view.camera_heading + next(rotations)),
                math.tan(math.radians(view.angular_height / 2)),
            )
            for view in chain
        )
        track = _track(frames)
        if track is not None:
            tracks.append(track)
    diagnostics["eligible_sequence_count"] = len(tracks)
    if len(tracks) < 2:
        return AdjacentPose(None, "insufficient_adjacent_sequences", diagnostics)

    minimum_support = max(2, len(chains) // 2 + 1)
    candidates = {}
    for track in tracks:
        support = tuple(
            i for i, other in enumerate(tracks) if _supports(other, track.point)
        )
        if len(support) >= minimum_support:
            candidates.setdefault(support, []).append(track.point)
    if not candidates:
        return AdjacentPose(None, "inconsistent_adjacent_tracks", diagnostics)
    largest = max(map(len, candidates))
    winners = [support for support in candidates if len(support) == largest]
    if len(winners) != 1:
        return AdjacentPose(None, "inconsistent_adjacent_tracks", diagnostics)

    support = winners[0]
    selected = [tracks[i] for i in support]
    center = tuple(
        math.fsum(axis) / len(selected)
        for axis in zip(*(track.point for track in selected))
    )
    if not all(_supports(track, center) for track in selected):
        center = min(
            candidates[support],
            key=lambda point: sum(math.dist(track.point, point) for track in selected),
        )
    absolute = _along(origin, center, 1)
    diagnostics.update(
        support_sequence_count=len(selected),
        support_pair_count=sum(len(track.pairs) for track in selected),
        nominal_point_en_m=list(absolute),
        max_sequence_offset_m=max(math.dist(center, track.point) for track in selected),
        max_pair_ray_mismatch_m=max(
            pair.residual for track in selected for pair in track.pairs
        ),
    )
    if bounds is not None and not (
        bounds[0] <= absolute[0] <= bounds[2] and bounds[1] <= absolute[1] <= bounds[3]
    ):
        return AdjacentPose(None, "adjacent_position_outside_bounds", diagnostics)
    polygon, clipped = _region(selected)
    if not polygon or clipped:
        return AdjacentPose(None, "adjacent_position_unbounded", diagnostics)
    radius = max(math.dist(center, vertex) for vertex in polygon)
    diagnostics["conditional_position_radius_m"] = radius
    if radius > MAX_ADJACENT_RADIUS_M:
        return AdjacentPose(None, "adjacent_position_too_wide", diagnostics)
    rays = tuple(frame.ray for track in selected for frame in track.frames)
    region = tuple(_along(origin, vertex, 1) for vertex in polygon)
    return AdjacentPose(Fit(absolute, radius, rays, region), "estimated", diagnostics)
