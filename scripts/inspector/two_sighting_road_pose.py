"""Two-view roadside placement, paired with StreetShots' SignPoseEstimator."""

from dataclasses import dataclass
from datetime import datetime
import math

from shapely.geometry import box

from scripts.tsr.collection.estimate_sign_poses import (
    MAX_RANGE_M,
    MIN_BASELINE_M,
    MIN_RANGE_M,
    dot,
    subtract,
)


OFFSET_M = 1.0
ROAD_SIDES = ("right", "left")
MIN_TRAVEL_ALIGNMENT = math.cos(math.radians(35))
MIN_BRANCH_ALIGNMENT = math.cos(math.radians(25))


def advance(point, direction, distance):
    return tuple(value + step * distance for value, step in zip(point, direction))


def unit(vector):
    return tuple(value / math.hypot(*vector) for value in vector)


@dataclass(frozen=True)
class Segment:
    way_id: str
    start: tuple[float, float]
    end: tuple[float, float]

    @property
    def direction(self):
        return unit(subtract(self.end, self.start))

    def distance(self, point):
        delta = subtract(self.end, self.start)
        fraction = max(
            0, min(1, dot(subtract(point, self.start), delta) / dot(delta, delta))
        )
        return math.dist(point, advance(self.start, delta, fraction))


@dataclass(frozen=True)
class Placement:
    point: tuple[float, float]
    way_id: str
    approach: tuple[float, float]
    score: float
    road_side: str
    junction: tuple[float, float] | None = None

    @property
    def method(self):
        anchor = "Junction" if self.junction is not None else "Way"
        return f"twoSighting{self.road_side.title()}Of{anchor}"


def offset_point(point, direction, road_side):
    signed_distance = OFFSET_M if road_side == "right" else -OFFSET_M
    return advance(point, (direction[1], -direction[0]), signed_distance)


def segment_candidates(roads, near):
    east, north = near
    hits = roads.index.query(box(east - 125, north - 125, east + 125, north + 125))
    if len(hits) > 512:
        return
    for index in hits:
        way = roads.ways[index]
        for start, end in zip(way.points, way.points[1:]):
            if math.dist(start, end) >= 0.25:
                segment = Segment(way.key, start, end)
                if segment.distance(near) <= 110:
                    yield segment


def residual(ray, point):
    offset = subtract(point, ray.position)
    forward = dot(offset, ray.direction)
    if forward < MIN_RANGE_M - 1e-6 or math.hypot(*offset) > MAX_RANGE_M + 1e-6:
        return None
    envelope = ray.position_error + forward * math.tan(math.radians(ray.angular_error))
    across = abs(dot(offset, (ray.direction[1], -ray.direction[0])))
    return (
        across / envelope
        if envelope > 0 and across <= min(3, 0.65 * envelope)
        else None
    )


def mean_camera_distance(rays, segments):
    return sum(
        min(segment.distance(ray.position) for segment in segments) for ray in rays
    ) / len(rays)


def travel_direction(segment, travel):
    direction = segment.direction
    if dot(direction, travel) < 0:
        direction = tuple(-value for value in direction)
    return direction


def best_placement(candidates):
    ranked = sorted(candidates, key=lambda candidate: candidate.score)
    if not ranked:
        return None
    best = ranked[0]
    if any(
        candidate.score - best.score < 2
        and (
            candidate.way_id != best.way_id
            or (
                math.dist(candidate.junction, best.junction) >= 1
                if best.junction is not None
                else math.dist(candidate.point, best.point) > 3
            )
        )
        for candidate in ranked[1:]
    ):
        return None
    return best


def along_way(rays, travel, routes, nominal, road_side):
    candidates = []
    for way_id, segments in routes.items():
        camera_distance = mean_camera_distance(rays, segments)
        if camera_distance > 18:
            continue
        for segment in segments:
            direction = travel_direction(segment, travel)
            alignment = dot(travel, direction)
            if alignment < MIN_TRAVEL_ALIGNMENT:
                continue
            start = offset_point(segment.start, direction, road_side)
            axis = segment.direction
            normals = [(ray.direction[1], -ray.direction[0]) for ray in rays]
            slopes = [dot(normal, axis) for normal in normals]
            if nominal is not None:
                station = dot(subtract(nominal, start), axis)
            else:
                leverage = sum(slope**2 for slope in slopes)
                if leverage < 0.008:
                    continue
                station = (
                    sum(
                        slope * dot(normal, subtract(ray.position, start))
                        for ray, normal, slope in zip(rays, normals, slopes)
                    )
                    / leverage
                )
            if not -1e-6 <= station <= math.dist(segment.start, segment.end) + 1e-6:
                continue
            point = advance(start, axis, station)
            if dot(subtract(point, rays[-1].position), direction) < 0 or (
                nominal is not None and math.dist(point, nominal) > 20
            ):
                continue
            errors = [residual(ray, point) for ray in rays]
            if None in errors:
                continue
            if nominal is None:
                bounds = [
                    (
                        ray.position_error
                        + dot(subtract(point, ray.position), ray.direction)
                        * math.tan(math.radians(ray.angular_error))
                    )
                    / abs(slope)
                    for ray, slope in zip(rays, slopes)
                    if abs(slope) > 1e-6
                ]
                if not bounds or min(bounds) > 20:
                    continue
            score = camera_distance + 10 * (1 - alignment) + 10 * sum(errors)
            if nominal is not None:
                score += math.dist(point, nominal)
            candidates.append(Placement(point, way_id, direction, score, road_side))
    return best_placement(candidates)


def at_junction(rays, travel, routes, nominal, road_side):
    vertices = {}
    for segments in routes.values():
        for segment in segments:
            for vertex in (segment.start, segment.end):
                vertices.setdefault(vertex, []).append(segment)
    candidates = []
    for vertex, approaches in vertices.items():
        if len(approaches) < 2 or (
            nominal is not None and math.dist(vertex, nominal) > 20
        ):
            continue
        for segment in approaches:
            direction = travel_direction(segment, travel)
            if dot(direction, travel) < MIN_TRAVEL_ALIGNMENT:
                continue
            other_end = segment.end if segment.start == vertex else segment.start
            if (
                dot(subtract(vertex, rays[-1].position), direction) < 0
                or dot(subtract(other_end, vertex), direction) >= 0
                or not any(
                    other.way_id != segment.way_id
                    and abs(dot(other.direction, direction)) < MIN_BRANCH_ALIGNMENT
                    for other in approaches
                )
            ):
                continue
            point = offset_point(vertex, direction, road_side)
            errors = [residual(ray, point) for ray in rays]
            if None in errors:
                continue
            camera_distance = mean_camera_distance(rays, routes[segment.way_id])
            if camera_distance > 18:
                continue
            optical_score = (
                math.dist(point, nominal) if nominal is not None else 10 * sum(errors)
            )
            candidates.append(
                Placement(
                    point,
                    segment.way_id,
                    direction,
                    camera_distance + optical_score,
                    road_side,
                    vertex,
                )
            )
    return best_placement(candidates)


def estimate(rays, roads, road_side="right"):
    """Apply the one-metre offset on the selected side of the approach."""
    if road_side not in ROAD_SIDES:
        raise ValueError("road side must be 'left' or 'right'")
    if (
        len(rays) != 2
        or not roads.ways
        or any(
            not (1 <= ray.angular_error <= 45 and 1 <= ray.position_error <= 50)
            for ray in rays
        )
    ):
        return None
    rays = sorted(
        rays,
        key=lambda ray: (
            datetime.fromisoformat(ray.captured_at.replace("Z", "+00:00")),
            ray.key,
        ),
    )
    displacement = subtract(rays[1].position, rays[0].position)
    if math.hypot(*displacement) < MIN_BASELINE_M:
        return None
    travel = unit(displacement)
    routes = {}
    for segment in segment_candidates(roads, rays[-1].position):
        routes.setdefault(segment.way_id, []).append(segment)
    nominal = rays[0].intersection(rays[1])
    way = along_way(rays, travel, routes, nominal, road_side)
    junction = at_junction(rays, travel, routes, nominal, road_side)
    if junction is not None and (
        way is None or (nominal is not None and math.dist(junction.point, nominal) <= 3)
    ):
        return junction
    return way
