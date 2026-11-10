"""Road-aligned heading hypotheses for private traffic-sign review drafts."""

from __future__ import annotations

from dataclasses import dataclass
import json
import math
from pathlib import Path
import re

from fiona.transform import transform
from shapely.geometry import LineString, Point, Polygon, box
from shapely.strtree import STRtree

from scripts.tsr.collection.estimate_sign_poses import METRIC, WGS84, delta_angle
from scripts.tsr.collection.sign_road_association import (
    closest_segment,
    direction_from_tags,
    segment_projection,
    validate_bounds,
)
from scripts.tsr.collection.travelled_way import recorded_approach


ROAD_OFFSET_M = 15
MAP_MARGIN_M = 2
TANGENT_LIMIT_DEG = 15
# Conventional approach signs that normally face the traffic they govern.
# Crossings can have bilateral panels, so use image evidence for them.
SIDE_CLASSES = frozenset(
    "205 206 208 250 251 253 254 255 260 261 262 263 264 265 266 "
    "274 274.1 274.2 275 276 277 277.1 278 279 280 281 281.1 282 310 311".split()
)
IMAGE_CLASSES = SIDE_CLASSES | {"350"}


@dataclass
class Way:
    key: str
    points: list[tuple[float, float]]
    source_points: list[list[float]]
    nodes: frozenset[str]
    tags: dict
    geometry: LineString

    def direction(self):
        direction = direction_from_tags(self.tags)
        if direction != "unknown" or "oneway" in self.tags:
            return direction
        if self.tags.get("highway") not in ("motorway", "trunk") and not any(
            key.startswith("oneway:") for key in self.tags
        ):
            return "both"
        return "unknown"

    def ordinary(self):
        tags = self.tags
        return (
            tags.get("highway") not in {"motorway", "trunk", "road", "service"}
            and not tags.get("highway", "").endswith("_link")
            and tags.get("junction") not in {"roundabout", "circular"}
            and tags.get("bridge", "no") == "no"
            and tags.get("tunnel", "no") == "no"
            and tags.get("layer", "0") == "0"
        )


@dataclass(frozen=True)
class RoadHeading:
    status: str
    way_id: str | None = None
    side: str | None = None
    facing: float | None = None
    candidates: tuple[float, ...] = ()
    method: str | None = None
    image_travel: float | None = None
    image_method: str | None = None
    corroborated: bool = False
    recorded_travel: float | None = None


@dataclass(frozen=True)
class RoadFallback:
    way_id: str
    method: str
    direction_basis: str
    approach: float
    distance: float
    tangent_ambiguous: bool


def same_continuation(first, other, tangent, other_tangent):
    if not (first.nodes & other.nodes) or not (first.ordinary() and other.ordinary()):
        return False
    if not any(
        first.tags.get(key) and first.tags[key] == other.tags.get(key)
        for key in ("name", "ref")
    ):
        return False
    difference = delta_angle(tangent, other_tangent)
    if min(difference, 180 - difference) > TANGENT_LIMIT_DEG:
        return False
    direction = other.direction()
    if difference > 90:
        direction = {"forward": "reverse", "reverse": "forward"}.get(
            direction, direction
        )
    return first.direction() == direction


def side_from_segments(vertices, segments):
    offsets = [
        segment_projection(vertex, start, end)["signed_left_offset_m"]
        for start, end in segments
        for vertex in vertices
    ]
    if min(offsets) > MAP_MARGIN_M:
        return "left"
    if max(offsets) < -MAP_MARGIN_M:
        return "right"
    return None


class RoadHeadingIndex:
    def __init__(self, graph):
        source = graph["source"]
        extraction = graph["extraction"]
        if (
            graph.get("schema_version") != 1
            or source.get("kind") != "original_osm"
            or not re.fullmatch(r"[0-9a-f]{64}", source.get("sha256", ""))
            or not extraction.get("candidate_complete_within_source_bbox")
            or not extraction.get("node_geometry_complete")
        ):
            raise ValueError("heading requires the pinned original OSM graph")
        self.source = source
        self.bounds = [validate_bounds(bounds) for bounds in extraction["bounds_wgs84"]]
        lats, lons = [], []
        for road in graph["roads"]:
            for lat, lon in road["points_lat_lon"]:
                lats.append(lat)
                lons.append(lon)
        xs, ys = transform(WGS84, METRIC, lons, lats) if lons else ([], [])
        coordinates = iter(zip(xs, ys))
        self.ways = []
        for raw in graph["roads"]:
            points = [next(coordinates) for _ in raw["points_lat_lon"]]
            if len(set(points)) < 2:
                continue
            ends = raw["node_ids"]
            self.ways.append(
                Way(
                    raw["way_id"],
                    points,
                    raw["points_lat_lon"],
                    frozenset((ends[0], ends[-1])),
                    raw["tags"],
                    LineString(points),
                )
            )
        self.index = STRtree([way.geometry for way in self.ways])
        self.ways_by_id = {way.key: way for way in self.ways}

    @classmethod
    def load(cls, path):
        return cls(json.loads(Path(path).read_bytes()))

    def covered(self, lon, lat, radius):
        margin = radius + ROAD_OFFSET_M + 2 * MAP_MARGIN_M
        dy = margin / 110_000
        dx = dy / math.cos(math.radians(lat))
        return any(
            w + dx <= lon <= e - dx and s + dy <= lat <= n - dy
            for w, s, e, n in self.bounds
        )

    def fallback(self, fit, lon, lat, associated_way_id, travel_bundles):
        """Use a local OSM tangent as a labeled private draft azimuth."""
        if not self.ways or not self.covered(lon, lat, fit.radius):
            return None
        point = Point(fit.point)
        matches = [
            ray.phone_match
            for ray in fit.rays
            if getattr(ray, "phone_match", None) is not None
        ]
        recorded_ids = {match.way_id for match in matches} & self.ways_by_id.keys()

        def nearest(ways):
            return min(ways, key=lambda way: (way.geometry.distance(point), way.key))

        if recorded_ids:
            way = nearest(self.ways_by_id[key] for key in recorded_ids)
            method = "osm_recorded_way_fallback"
        elif associated_way_id in self.ways_by_id:
            way = self.ways_by_id[associated_way_id]
            method = "osm_associated_way_fallback"
        else:
            way = nearest(self.ways[i] for i in self.index.query_nearest(point))
            method = "osm_nearest_road_fallback"

        votes = set()
        if travel_bundles is not None:
            votes = {
                travel_bundles.direction(match, way.source_points)
                for match in matches
                if match.way_id == way.key
            } - {None}
        projection = closest_segment(fit.point, way.points)
        travel = way.direction()
        side = projection["signed_left_offset_m"]
        if len(votes) == 1:
            direction, basis = next(iter(votes)), "recorded_travel"
        elif travel in ("forward", "reverse"):
            direction, basis = travel, "osm_oneway"
        elif travel == "both" and abs(side) > MAP_MARGIN_M:
            direction = "reverse" if side > 0 else "forward"
            basis = "right_hand_road_side"
        else:
            direction, basis = "forward", "osm_node_order"
        approach = projection["tangent_degrees"]
        if direction != "forward":
            approach = (approach + 180) % 360
        return RoadFallback(
            way.key,
            method,
            basis,
            approach,
            projection["distance_m"],
            projection["tangent_ambiguous"],
        )

    def image_way_unique(self, first, tangent, fit, evidence):
        """Check camera-track roads independently of plausible sign locations."""
        rays = {ray.image: ray for ray in fit.rays}
        for group in evidence.image_groups:
            xy = [rays[image].position for image in group]
            lons, lats = transform(METRIC, WGS84, *zip(*xy))
            if any(not self.covered(lon, lat, 11) for lon, lat in zip(lons, lats)):
                return False
            points = [Point(point) for point in xy]
            x, y = xy[0]
            for idx in self.index.query(box(x - 11, y - 11, x + 11, y + 11)):
                other = self.ways[idx]
                if other is first or any(
                    other.geometry.distance(point) > 11 for point in points
                ):
                    continue
                other_tangent = closest_segment(xy[0], other.points)["tangent_degrees"]
                if not same_continuation(first, other, tangent, other_tangent):
                    return False
        return True

    def heading(
        self,
        fit,
        code,
        lon,
        lat,
        camera_heading=None,
        *,
        approach=None,
        travel_bundles=None,
    ):
        base = code.removeprefix("DE:").split("-", 1)[0]
        if base not in IMAGE_CLASSES and (approach is None or not fit.rays):
            return RoadHeading("unsupported_sign_class")
        if not self.covered(lon, lat, fit.radius):
            return RoadHeading("road_graph_outside_coverage")
        if not fit.region:
            return RoadHeading("missing_position_region")
        region = Polygon(fit.region)
        if (
            not region.is_valid
            or region.is_empty
            or not region.covers(Point(fit.point))
        ):
            return RoadHeading("invalid_position_region")
        point = Point(fit.point)
        radius = ROAD_OFFSET_M + MAP_MARGIN_M
        west, south, east, north = region.bounds
        search = box(west - radius, south - radius, east + radius, north + radius)
        roads = [self.ways[i] for i in self.index.query(search)]
        roads = [road for road in roads if road.geometry.distance(region) <= radius]
        if not roads:
            return RoadHeading("no_nearby_road")
        first = min(roads, key=lambda way: (way.geometry.distance(point), way.key))
        recorded = None
        matched_ids = {
            ray.phone_match.way_id
            for ray in fit.rays
            if getattr(ray, "phone_match", None) is not None
        }
        if travel_bundles is not None and len(matched_ids) == 1:
            matched = next((way for way in roads if way.key in matched_ids), None)
            if (
                matched is not None
                and matched.geometry.distance(point) <= ROAD_OFFSET_M
            ):
                match_projection = closest_segment(fit.point, matched.points)
                recorded = recorded_approach(
                    fit, matched, match_projection, travel_bundles
                )
                if recorded is not None:
                    first = matched
        if first.geometry.distance(point) > ROAD_OFFSET_M:
            return RoadHeading("no_nearby_road")
        projection = closest_segment(fit.point, first.points)
        tangent = projection["tangent_degrees"]
        if projection["tangent_ambiguous"]:
            return RoadHeading("unstable_road_tangent", first.key)
        images = (
            approach(fit, first.points, tangent)
            if approach is not None and fit.rays
            else None
        )
        if (
            images is not None
            and recorded is None
            and not self.image_way_unique(first, tangent, fit, images)
        ):
            images = None
        image_direction = images.travel_bearing_grid_deg if images is not None else None
        image_method = images.method if images is not None else None
        recorded_direction = (
            (tangent + (180 if recorded == "backward" else 0)) % 360
            if recorded is not None
            else None
        )

        def withheld(reason, side=None, candidates=()):
            return RoadHeading(
                reason,
                first.key,
                side,
                candidates=candidates,
                image_travel=image_direction,
                image_method=image_method,
                recorded_travel=recorded_direction,
            )

        if base not in IMAGE_CLASSES:
            return withheld("unsupported_sign_class")
        if not first.ordinary():
            return withheld("complex_road")
        direction = first.direction()
        if direction == "unknown":
            return withheld("unknown_traffic_direction")
        index = projection["segment_index"]
        primary = LineString(first.points[index : index + 2])
        # Distance to a single segment is convex. Its maximum over the feasible
        # polygon is at a vertex, giving an upper bound for the chosen way.
        plausible = min(
            radius,
            max(primary.distance(Point(v)) for v in fit.region) + 2 * MAP_MARGIN_M,
        )
        continuation = [first]
        for other in roads:
            if other is first or other.geometry.distance(region) > plausible:
                continue
            other_tangent = closest_segment(fit.point, other.points)["tangent_degrees"]
            if not same_continuation(first, other, tangent, other_tangent):
                return withheld("competing_roads")
            continuation.append(other)

        segments = []
        for way in continuation:
            for start, end in zip(way.points, way.points[1:]):
                if (
                    start == end
                    or LineString((start, end)).distance(region) > plausible
                ):
                    continue
                segment = segment_projection(fit.point, start, end)
                difference = delta_angle(segment["tangent_degrees"], tangent)
                if min(difference, 180 - difference) > TANGENT_LIMIT_DEG:
                    return withheld("unstable_road_tangent")
                segments.append((end, start) if difference > 90 else (start, end))
        if not segments:
            return withheld("no_nearby_segment")
        side = side_from_segments(fit.region, segments)

        allowed = {"forward", "backward"}
        if direction in ("forward", "reverse"):
            allowed = {"forward" if direction == "forward" else "backward"}
        facing = {"forward": (tangent + 180) % 360, "backward": tangent}
        if camera_heading is not None:
            center, error, _ = camera_heading
            allowed = {
                travel
                for travel in allowed
                if delta_angle(facing[travel], center) <= error
            }
        candidates = tuple(sorted(facing[travel] for travel in allowed))
        if not allowed:
            return withheld("camera_heading_conflict", side)

        side_travel = (
            {"right": "forward", "left": "backward"}.get(side)
            if base in SIDE_CLASSES
            else None
        )
        image_travel = images.travel if images is not None else None

        def result(travel, method):
            front = facing[travel]
            camera_corroborates = camera_heading is not None and (
                delta_angle((front + 180) % 360, camera_heading[0]) > camera_heading[1]
            )
            return RoadHeading(
                "estimated",
                first.key,
                side,
                front,
                candidates,
                method,
                image_direction,
                image_method,
                recorded == travel or image_travel == travel or camera_corroborates,
                recorded_direction,
            )

        if recorded is not None and (
            recorded not in allowed
            or side_travel not in (None, recorded)
            or image_travel not in (None, recorded)
        ):
            return withheld("recorded_travel_direction_conflict", side, candidates)
        if recorded is not None:
            return result(recorded, "osm_recorded_approach")
        if image_travel is not None and (
            image_travel not in allowed or side_travel and side_travel != image_travel
        ):
            return withheld("image_direction_conflict", side, candidates)
        if images is not None and images.method == "image_sequence_approach":
            return result(image_travel, "osm_image_approach")
        if side_travel is not None:
            if side_travel in allowed:
                return result(side_travel, "osm_road_side")
            return withheld("road_side_direction_conflict", side, candidates)
        if base in SIDE_CLASSES and len(allowed) == 1:
            return result(
                next(iter(allowed)),
                "osm_oneway" if direction != "both" else "osm_front_visibility",
            )
        return withheld("road_side_ambiguous", side, candidates)
