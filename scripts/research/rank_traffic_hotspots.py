#!/usr/bin/env python3
"""Rank snapshot traffic-speed candidates against explicitly mapped OSM limits.

This research tool never changes the mobile speed-reference policy. It defaults
to the provider's historical Durchschnitt speed and samples the full traffic
geometry. Mixed limits, unknown rules, uncertain alignment and disconnected
paths fail closed. The output screens candidates; it cannot count violations.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import csv
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re
import sqlite3
import xml.etree.ElementTree as ET

RADIUS = 6371008.8
DRIVABLE = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified",
            "residential", "service", "living_street", "road", "motorway_link", "trunk_link",
            "primary_link", "secondary_link", "tertiary_link"}
SPEED_METADATA = {"reason", "type", "source", "note", "check_date", "signed", "advisory", "advised", "practical"}
OTHER_VEHICLES = {"hgv", "bus", "motorcycle", "hazmat", "bicycle", "agricultural", "emergency", "taxi", "psv", "foot", "train", "tilting"}


def number(value):
    try:
        n = float(value)
        return n if math.isfinite(n) else None
    except (ValueError, TypeError, OverflowError):
        return None


def angle_error(a, b):
    return abs((a - b + 180) % 360 - 180)


def heading(a, b):
    return math.degrees(math.atan2(b[0] - a[0], b[1] - a[1])) % 360


def quantile(values, q):
    if not values:
        return None
    v = sorted(values)
    return v[min(len(v) - 1, math.ceil(q * len(v)) - 1)]


def coord_key(point):
    return f"{point[0]:.7f}:{point[1]:.7f}"


class Projection:
    def __init__(self, lon, lat):
        self.lon, self.lat = lon, lat
        self.scale = math.cos(math.radians(lat))

    def xy(self, point):
        return (RADIUS * math.radians(point[0] - self.lon) * self.scale,
                RADIUS * math.radians(point[1] - self.lat))


def line_parts(geometry):
    if not isinstance(geometry, dict):
        return []
    if geometry.get("type") == "LineString":
        parts = [geometry.get("coordinates")]
    elif geometry.get("type") == "MultiLineString":
        parts = geometry.get("coordinates")
    else:
        return []
    if not isinstance(parts, list) or not parts:
        return []
    for part in parts:
        if not isinstance(part, list) or len(part) < 2:
            return []
        for point in part:
            if (not isinstance(point, (list, tuple)) or len(point) < 2
                    or any(not isinstance(v, (int, float)) or isinstance(v, bool) or not math.isfinite(v) for v in point[:2])
                    or not -180 <= point[0] <= 180 or not -85 < point[1] < 85):
                return []
    return parts


def validate_bbox(bbox):
    if (len(bbox) != 4 or any(number(v) is None for v in bbox)
            or not (-180 <= bbox[0] < bbox[2] <= 180 and -85 < bbox[1] < bbox[3] < 85)):
        raise ValueError("bbox must be valid west,south,east,north bounds")


def geometry_points(geometry):
    return [point for part in line_parts(geometry) for point in part]


def load_gpx(path):
    """Keep track/route order and GPX segment breaks; never connect separate tracks."""
    root = ET.parse(path).getroot()
    parts = []
    for container in root.iter():
        if container.tag.rsplit("}", 1)[-1] not in ("trkseg", "rte"):
            continue
        points = []
        for element in container:
            if element.tag.rsplit("}", 1)[-1] not in ("trkpt", "rtept"):
                continue
            lat, lon = number(element.attrib.get("lat")), number(element.attrib.get("lon"))
            if lat is None or lon is None or not -85 < lat < 85 or not -180 <= lon <= 180:
                raise ValueError("GPX contains invalid coordinates")
            if not points or points[-1] != [lon, lat]:
                points.append([lon, lat])
        if len(points) >= 2:
            parts.append(points)
    if not parts:
        raise ValueError("GPX contains no usable track/route segments")
    return dict(type="MultiLineString", coordinates=parts)


def sample_geometry(geometry, projection, spacing=5):
    """Length-weighted midpoints; every source vertex boundary is retained."""
    samples = []
    chainage = 0.0
    for part_index, part in enumerate(line_parts(geometry)):
        for original_a, original_b in zip(part, part[1:]):
            a, b = projection.xy(original_a), projection.xy(original_b)
            length = math.dist(a, b)
            if length < 1e-5:
                continue
            steps = max(1, math.ceil(length / spacing))
            for i in range(steps):
                fraction = (i + .5) / steps
                point = (a[0] + fraction * (b[0] - a[0]), a[1] + fraction * (b[1] - a[1]))
                samples.append(dict(xy=point, heading=heading(a, b), weight=length / steps,
                                    chainage=chainage + fraction * length, part=part_index))
            chainage += length
    return samples


def parse_limit(raw):
    """Only explicit scalar numeric limits; missing/implicit/none are unresolved."""
    if raw is None:
        return None
    match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)\s*(km/h|kmh|kph|mph)?\s*", str(raw))
    if not match:
        return None
    value = float(match[1]) * (1.609344 if match[2] == "mph" else 1)
    return value if 0 < value <= 300 else None


def resolve_limit(tags, direction):
    """Reject relevant conditional/lane/variable rules; preserve tag provenance.

    Vehicle-specific rules are excluded because this traffic feed is an
    all-vehicle aggregate, not a passenger-car-only observation distribution.
    Opposite-direction conditions and advisory/source metadata do not mask a
    current scalar rule. Unknown speed-key suffixes always block admission.
    """
    direction_name = "forward" if direction == 1 else "backward"
    opposite = "backward" if direction == 1 else "forward"
    issues = []
    for key, value in tags.items():
        if not key.startswith("maxspeed"):
            continue
        parts = key.split(":")[1:]
        if SPEED_METADATA.intersection(parts) or opposite in parts:
            continue
        if parts and parts[0] == "variable":
            if str(value).strip().lower() not in ("no", "false", "0"):
                issues.append("variable_limit")
            continue
        if "conditional" in parts or "@" in str(value):
            issues.append("conditional_limit")
        if "lanes" in parts:
            issues.append("lane_specific_limit")
        if OTHER_VEHICLES.intersection(parts) or {"motorcar", "motor_vehicle", "vehicle"}.intersection(parts):
            issues.append("vehicle_specific_limit")
        if any(p not in {"forward", "backward", "conditional", "lanes", "variable"} | OTHER_VEHICLES | {"motorcar", "motor_vehicle", "vehicle"} for p in parts):
            issues.append("unsupported_limit_scope")
    if issues:
        return None, None, sorted(set(issues))
    key = f"maxspeed:{direction_name}" if tags.get(f"maxspeed:{direction_name}") not in (None, "") else "maxspeed"
    raw = tags.get(key)
    value = parse_limit(raw)
    return value, key if raw is not None else None, [] if value is not None else ["unknown_or_unlimited_limit"]


@dataclass
class Road:
    way_id: int
    properties: dict
    coordinates: list
    tags: dict
    forward_allowed: bool
    backward_allowed: bool
    start_node: str
    end_node: str

    def limit(self, direction):
        return resolve_limit(self.tags, direction)

    def nodes(self, direction):
        return (self.start_node, self.end_node) if direction == 1 else (self.end_node, self.start_node)


def load_roads(db_path, bbox):
    """Load full source-vertex geometries from a read-only v3/fresh-extract DB."""
    db = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master")}
    if "road_speed_source_tag" not in tables:
        raise ValueError("Database lacks raw speed tags: conditional/variable completeness cannot be checked")
    west, south, east, north = bbox
    rows = list(db.execute("""SELECT w.*,g.points_json FROM ways_rtree r JOIN ways w USING(way_id)
        JOIN way_geom g USING(way_id) WHERE r.max_lon>=? AND r.min_lon<=? AND r.max_lat>=? AND r.min_lat<=?""",
                           (west, east, south, north)))
    roads = []
    for row in rows:
        p = dict(row)
        if p.get("highway") not in DRIVABLE:
            continue
        way_id = p["way_id"]
        tags = {t[0]: t[1] for t in db.execute("SELECT key,raw_value FROM road_speed_source_tag WHERE way_id=?", (way_id,))}
        # Scalar columns are exact source tags in the repository v3 format.
        for column, key in (("maxspeed", "maxspeed"), ("maxspeed_forward", "maxspeed:forward"), ("maxspeed_backward", "maxspeed:backward")):
            if p.get(column) not in (None, ""):
                tags.setdefault(key, p[column])
        coordinates = [[point[1], point[0]] for point in json.loads(p.pop("points_json"))]
        if len(coordinates) < 2:
            continue
        topology = None
        if "traffic_sign_way_direction" in tables:
            topology = db.execute("SELECT * FROM traffic_sign_way_direction WHERE way_id=?", (way_id,)).fetchone()
        topology = dict(topology) if topology is not None else p
        oneway = str(topology.get("oneway", "0")).lower()
        forward = bool(topology.get("forward_allowed", oneway not in ("-1", "reverse")))
        backward = bool(topology.get("backward_allowed", oneway not in ("1", "yes", "true")))
        roads.append(Road(way_id, p, coordinates, tags, forward, backward,
                          str(topology.get("start_node_key") or coord_key(coordinates[0])),
                          str(topology.get("end_node_key") or coord_key(coordinates[-1]))))
    metadata = dict(db.execute("SELECT key,value FROM metadata")) if "metadata" in tables else {}
    db.close()
    return roads, metadata


class RoadIndex:
    def __init__(self, roads, projection, cell_size=50):
        self.roads = {road.way_id: road for road in roads}
        self.cell_size = cell_size
        self.grid = defaultdict(list)
        self.segments = []
        for road in roads:
            points = [projection.xy(point) for point in road.coordinates]
            for a, b in zip(points, points[1:]):
                if math.dist(a, b) < 1e-5:
                    continue
                sid = len(self.segments)
                self.segments.append((road, a, b, heading(a, b)))
                for ix in range(math.floor(min(a[0], b[0]) / cell_size), math.floor(max(a[0], b[0]) / cell_size) + 1):
                    for iy in range(math.floor(min(a[1], b[1]) / cell_size), math.floor(max(a[1], b[1]) / cell_size) + 1):
                        self.grid[ix, iy].append(sid)

    def nearest(self, point, travel_heading, max_distance=15, max_heading=35):
        ix, iy = (math.floor(c / self.cell_size) for c in point)
        segment_ids = {sid for dx in (-1, 0, 1) for dy in (-1, 0, 1) for sid in self.grid.get((ix + dx, iy + dy), [])}
        candidates = {}
        for sid in segment_ids:
            road, a, b, forward_heading = self.segments[sid]
            dx, dy = b[0] - a[0], b[1] - a[1]
            fraction = max(0, min(1, ((point[0] - a[0]) * dx + (point[1] - a[1]) * dy) / (dx * dx + dy * dy)))
            distance = math.dist(point, (a[0] + fraction * dx, a[1] + fraction * dy))
            if distance > max_distance:
                continue
            for direction, allowed in ((1, road.forward_allowed), (-1, road.backward_allowed)):
                error = angle_error(travel_heading, forward_heading if direction == 1 else (forward_heading + 180) % 360)
                if not allowed or error > max_heading:
                    continue
                match = dict(road=road, direction=direction, distance=distance, heading_error=error,
                             cost=distance + .05 * error, fraction=fraction)
                key = (road.way_id, direction)
                if key not in candidates or match["cost"] < candidates[key]["cost"]:
                    candidates[key] = match
        return sorted(candidates.values(), key=lambda m: (m["cost"], m["road"].way_id, m["direction"]))


class RouteGate:
    """Directed route geometry and unambiguous OSM overlap, separate from limits."""
    def __init__(self, geometry, projection, road_index):
        self.projection = projection
        self.index = road_index
        fake_roads = []
        for i, part in enumerate(line_parts(geometry)):
            fake_roads.append(Road(-(i + 1), {}, part, {}, True, False, str(i) + "a", str(i) + "b"))
        self.geometry_index = RoadIndex(fake_roads, projection)
        self.directed_ways = set()
        self.route_samples = sample_geometry(geometry, projection)
        for sample in self.route_samples:
            sample["osm_step"] = None
            choices = road_index.nearest(sample["xy"], sample["heading"], max_distance=30, max_heading=35)
            if not choices:
                continue
            best = choices[0]
            nodes = {best["road"].start_node, best["road"].end_node}
            if any(other["cost"] - best["cost"] <= 3 and other["road"].way_id != best["road"].way_id
                   and not nodes.intersection({other["road"].start_node, other["road"].end_node})
                   for other in choices[1:]):
                continue
            step = (best["road"].way_id, best["direction"])
            self.directed_ways.add(step)
            sample["osm_step"] = step

    def evaluate(self, result):
        samples = sample_geometry(result["geometry"], self.projection)
        total = sum(sample["weight"] for sample in samples)
        aligned = sum(sample["weight"] for sample in samples if self.geometry_index.nearest(
            sample["xy"], sample["heading"], max_distance=30, max_heading=35))
        overlap = 100 * aligned / total if total else 0
        path = [(step["way_id"], step["direction"]) for step in result["match"]["directed_path"]]
        on_route_ways = [step for step in path if step in self.directed_ways]
        reasons = []
        if overlap < 99.5:
            reasons.append("outside_directed_gpx_corridor")
        if not on_route_ways:
            reasons.append("no_directed_osm_route_overlap")
        elif len(on_route_ways) != len(path):
            reasons.append("partial_directed_osm_route_overlap")
        result["route_overlap_pct"] = round(overlap, 2)
        result["route_osm_overlap_ways"] = [dict(way_id=way, direction=direction) for way, direction in on_route_ways]
        result["on_route"] = not reasons
        result["reasons"] = sorted(set(result["reasons"] + reasons))
        result["eligible"] = not result["reasons"]

    def coverage(self, results, *, speed_field="average_speed"):
        """Length-weighted union along GPX, never sum overlapping traffic links.

        Coverage uses only local, direction-aligned traffic projections whose
        matched OSM path contains the route's local directed way. Samples whose
        OSM route match is ambiguous remain unknown. A clamped traffic endpoint
        does not extend coverage along the road beyond that link's geometry.
        """
        traffic_roads, source_rows = [], {}
        for row in results:
            for part in line_parts(row["geometry"]):
                identity = -len(traffic_roads) - 1
                traffic_roads.append(Road(identity, {}, part, {}, True, False, str(identity) + "a", str(identity) + "b"))
                source_rows[identity] = row
        traffic_index = RoadIndex(traffic_roads, self.projection)
        covered, eligible, mapped, total = [], [], 0.0, 0.0
        for sample in self.route_samples:
            total += sample["weight"]
            step = sample["osm_step"]
            if step is None:
                continue
            mapped += sample["weight"]
            available_here, eligible_here = False, False
            for match in traffic_index.nearest(sample["xy"], sample["heading"], max_distance=30, max_heading=35):
                if not 0 < match["fraction"] < 1:
                    continue
                row = source_rows[match["road"].way_id]
                source_failures = {"duplicate_or_missing_segment_id"}
                if speed_field == "speed":
                    source_failures.update({"not_measured_source_score30", "invalid_or_zero_speed", "closed_segment",
                                           "missing_observation_time", "invalid_observation_time"})
                else:
                    source_failures.add("missing_or_invalid_average_speed")
                if source_failures.intersection(row["reasons"]):
                    continue
                path = {(item["way_id"], item["direction"]) for item in row["match"]["directed_path"]}
                if step not in path:
                    continue
                available_here = True
                eligible_here = eligible_here or row["eligible"]
            if available_here:
                covered.append(sample)
            if eligible_here:
                eligible.append(sample)
        available_m = sum(sample["weight"] for sample in covered)
        eligible_m = sum(sample["weight"] for sample in eligible)
        def intervals(samples):
            result = []
            for sample in samples:
                start, end = sample["chainage"] - sample["weight"] / 2, sample["chainage"] + sample["weight"] / 2
                if result and result[-1]["part"] == sample["part"] and abs(result[-1]["end_m"] - start) < .01:
                    result[-1]["end_m"] = round(end, 3)
                else:
                    result.append(dict(part=sample["part"], start_m=round(start, 3), end_m=round(end, 3)))
            return result
        result = dict(route_length_m=round(total, 2), osm_mapped_length_m=round(mapped, 2),
                      selected_traffic_length_m=round(available_m, 2), eligible_traffic_length_m=round(eligible_m, 2),
                      selected_traffic_coverage_pct=round(100 * available_m / total, 2) if total else 0,
                      eligible_traffic_coverage_pct=round(100 * eligible_m / total, 2) if total else 0,
                      selected_intervals_m=intervals(covered), eligible_intervals_m=intervals(eligible),
                      coverage_basis="historical_average_availability" if speed_field == "average_speed" else "current_measured_availability",
                      method="Length-weighted union of at-most-5m GPX midpoint samples; distance <=30m, local heading <=35 degrees, same local directed OSM way, and interior traffic-segment projection. Selected-source coverage requires a unique valid selected-field value; current mode additionally requires open score-30 data and a valid current timestamp. Historical-average availability never uses current score, c-value or closure gates. Eligible coverage additionally requires all ranking admission gates. Ambiguous/unmatched GPX samples count as unknown uncovered length, not compliance.")
        if speed_field == "average_speed":
            result.update(average_source_length_m=result["selected_traffic_length_m"],
                          average_source_coverage_pct=result["selected_traffic_coverage_pct"])
        else:
            result.update(measured_traffic_length_m=result["selected_traffic_length_m"],
                          measured_traffic_coverage_pct=result["selected_traffic_coverage_pct"],
                          measured_intervals_m=result["selected_intervals_m"])
        return result


def direction_label(geometry, properties):
    raw = properties.get("Bearing")
    if raw and str(raw).upper() in {"N", "NE", "E", "SE", "S", "SW", "W", "NW"}:
        return str(raw).upper()
    points = geometry_points(geometry)
    if len(points) < 2:
        return "unknown"
    p = Projection(*points[0])
    value = heading(p.xy(points[0]), p.xy(points[-1]))
    return ("N", "NE", "E", "SE", "S", "SW", "W", "NW")[int((value + 22.5) // 45) % 8]


def match_feature(feature, index, projection, *, speed_field="average_speed", min_c_value=70, spacing=5, max_distance=15, max_heading=35):
    if speed_field not in ("speed", "average_speed"):
        raise ValueError("speed_field must be speed or average_speed")
    p, geometry = feature.get("properties") or {}, feature.get("geometry") or {}
    source_speed = number(p.get(speed_field))
    current_c_value = number(p.get("c_value"))
    c_value = current_c_value if speed_field == "speed" else None
    reasons = []
    provenance_warnings = []
    if speed_field == "speed":
        if number(p.get("score")) != 30:
            reasons.append("not_measured_source_score30")
        if c_value is None or not 0 <= c_value <= 100 or c_value < min_c_value:
            reasons.append("insufficient_provider_c_value")
        if source_speed is None or not 0 < source_speed <= 300:
            reasons.append("invalid_or_zero_speed")
        if p.get("segment_closed") in (True, 1, "true", "1"):
            reasons.append("closed_segment")
    elif source_speed is None or not 0 < source_speed <= 300:
        reasons.append("missing_or_invalid_average_speed")
    timestamp_issues = []
    if not p.get("observed_at"):
        timestamp_issues.append("missing_observation_time")
    else:
        try:
            datetime.fromisoformat(str(p["observed_at"]).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            timestamp_issues.append("invalid_observation_time")
    if speed_field == "speed":
        reasons.extend(timestamp_issues)
    else:
        provenance_warnings.extend(issue.replace("observation_time", "export_timestamp") for issue in timestamp_issues)
    samples = sample_geometry(geometry, projection, spacing)
    if not samples:
        reasons.append("invalid_geometry")
    total_length = sum(s["weight"] for s in samples)
    matches, distance_values, heading_values = [], [], []
    breakdown = defaultdict(lambda: dict(length_m=0.0, way_ids=set(), source_keys=set(), issues=set()))
    ambiguity_length = 0.0
    unmatched_length = 0.0
    for sample in samples:
        alternatives = index.nearest(sample["xy"], sample["heading"], max_distance, max_heading)
        if not alternatives:
            unmatched_length += sample["weight"]
            matches.append(None)
            continue
        best = alternatives[0]
        first_road = best["road"]
        # Adjacent source ways can legitimately meet at a split. Comparable,
        # disconnected parallel ways must not be resolved by nearest distance.
        for other in alternatives[1:]:
            if other["cost"] - best["cost"] > 3:
                break
            r = other["road"]
            if r.way_id != first_road.way_id and not ({r.start_node, r.end_node} & {first_road.start_node, first_road.end_node}):
                ambiguity_length += sample["weight"]
                break
        matches.append(best)
        distance_values.append(best["distance"])
        heading_values.append(best["heading_error"])
        limit, source_key, issues = first_road.limit(best["direction"])
        bucket = breakdown[limit]
        bucket["length_m"] += sample["weight"]
        bucket["way_ids"].add(first_road.way_id)
        if source_key:
            bucket["source_keys"].add(source_key)
        bucket["issues"].update(issues)
    if unmatched_length > 1e-6:
        reasons.append("road_alignment_gap")
    if ambiguity_length > 1e-6:
        reasons.append("ambiguous_parallel_road")
    if None in breakdown:
        reasons.append("unresolved_osm_limit")
    numeric_limits = [limit for limit in breakdown if limit is not None]
    if len(numeric_limits) > 1:
        reasons.append("mixed_osm_limits")
    path = []
    for sample, match in zip(samples, matches):
        if match is None:
            continue
        step = (match["road"].way_id, match["direction"])
        if not path or path[-1] != step:
            if path and sample["part"] == previous_part:
                previous_road, previous_direction = index.roads[path[-1][0]], path[-1][1]
                if previous_road.nodes(previous_direction)[1] != match["road"].nodes(match["direction"])[0]:
                    reasons.append("disconnected_osm_path")
            path.append(step)
        previous_part = sample["part"]
    limit_breakdown = [dict(osm_limit_kmh=limit, length_m=round(v["length_m"], 2),
                            share_pct=round(100 * v["length_m"] / total_length, 2) if total_length else 0,
                            osm_way_ids=sorted(v["way_ids"]), source_keys=sorted(v["source_keys"]), issues=sorted(v["issues"]))
                       for limit, v in sorted(breakdown.items(), key=lambda item: -item[1]["length_m"])]
    matched_ways = sorted({m["road"].way_id for m in matches if m})
    source_tags = {str(wid): index.roads[wid].tags for wid in matched_ways}
    osm_limit = numeric_limits[0] if len(numeric_limits) == 1 and None not in breakdown else None
    excess = source_speed - osm_limit if source_speed is not None and osm_limit is not None else None
    result = dict(id=str(p.get("XDSegID") or feature.get("id", "")),
                  feature_id=str(feature.get("id", "")),
                  road_name=str(p.get("RoadName") or p.get("RoadList") or p.get("RoadNumber") or "Unnamed road"),
                  direction=direction_label(geometry, p), speed_kmh=source_speed,
                  osm_limit_kmh=osm_limit, excess_kmh=round(excess, 3) if excess is not None else None,
                  excess_pct=round(100 * excess / osm_limit, 2) if excess is not None else None,
                  speed_field=speed_field, speed_basis_label="Durchschnitt" if speed_field == "average_speed" else "Aktuell",
                  source_score=p.get("score") if speed_field == "speed" else None, c_value=c_value,
                  confidence_basis="not_supplied_for_average_speed" if speed_field == "average_speed" else "current_source_score_and_c_value",
                  current_speed_kmh=number(p.get("speed")), current_source_score=p.get("score"), current_c_value=current_c_value,
                  observed_at_raw=p.get("observed_at"), average_speed_kmh=number(p.get("average_speed")),
                  observed_at_role="snapshot_export_timestamp" if speed_field == "average_speed" else "reported_current_speed_timestamp",
                  reference_speed_kmh=number(p.get("reference_speed")),
                  segment_length_m=round(total_length, 2),
                  match=dict(coverage_pct=round(100 * (1 - unmatched_length / total_length), 2) if total_length else 0,
                             distance_p95_m=round(quantile(distance_values, .95), 2) if distance_values else None,
                             heading_error_p95_deg=round(quantile(heading_values, .95), 2) if heading_values else None,
                             ambiguous_length_m=round(ambiguity_length, 2), unmatched_length_m=round(unmatched_length, 2),
                             osm_way_ids=matched_ways, directed_path=[dict(way_id=w, direction=d) for w, d in path]),
                  match_limit_breakdown=limit_breakdown, osm_source_tags=source_tags,
                  reasons=sorted(set(reasons)), provenance_warnings=provenance_warnings, geometry=geometry)
    result["eligible"] = not result["reasons"]
    result["substantial"] = excess is not None and excess >= max(10, .2 * osm_limit)
    return result


def ranking_key(candidate):
    """Historical ranking never depends on unrelated current confidence."""
    confidence = number(candidate.get("c_value")) if candidate.get("speed_field", "speed") == "speed" else None
    return (-candidate["excess_kmh"], -candidate["excess_pct"], -(confidence or 0), candidate["id"])


def cluster_candidates(candidates, projection):
    """Represent directly adjacent same-road/direction/limit links once.

    The displayed speed remains the strongest member's exact source value;
    no averages across traffic segments are invented.
    """
    candidates = sorted(candidates, key=ranking_key)
    groups = []
    for candidate in candidates:
        touching = [group for group in groups if any(_adjacent(candidate, member, projection) for member in group)]
        if not touching:
            groups.append([candidate])
        else:
            merged = [candidate] + [member for group in touching for member in group]
            groups = [group for group in groups if not any(group is item for item in touching)]
            groups.append(sorted(merged, key=ranking_key))
    groups.sort(key=lambda group: ranking_key(group[0]))
    result = []
    for rank, group in enumerate(groups, 1):
        representative = dict(group[0])
        representative["rank"] = rank
        representative["cluster_member_ids"] = [row["id"] for row in group]
        representative["cluster_member_count"] = len(group)
        representative["cluster_total_length_m"] = round(sum(row["segment_length_m"] for row in group), 2)
        result.append(representative)
    return result


def _adjacent(a, b, projection):
    if (a["road_name"].casefold(), a["direction"], a["osm_limit_kmh"]) != (b["road_name"].casefold(), b["direction"], b["osm_limit_kmh"]):
        return False
    ap, bp = geometry_points(a["geometry"]), geometry_points(b["geometry"])
    if not ap or not bp:
        return False
    return min(math.dist(projection.xy(ap[-1]), projection.xy(bp[0])), math.dist(projection.xy(bp[-1]), projection.xy(ap[0]))) <= 10


def analyze(db_path, traffic, bbox, metadata=None, route_geometry=None, **options):
    validate_bbox(bbox)
    if traffic.get("type") != "FeatureCollection" or not isinstance(traffic.get("features"), list):
        raise ValueError("Traffic input must be a GeoJSON FeatureCollection")
    if any(not isinstance(feature, dict) or feature.get("type") != "Feature" for feature in traffic["features"]):
        raise ValueError("Traffic input contains a malformed feature")
    speed_field = options.get("speed_field", "average_speed")
    if speed_field not in ("speed", "average_speed"):
        raise ValueError("speed_field must be speed or average_speed")
    if speed_field == "speed" and (number(options.get("min_c_value", 70)) is None or not 0 <= options.get("min_c_value", 70) <= 100):
        raise ValueError("min_c_value must be between 0 and 100")
    metadata = metadata or {}
    scope = dict(metadata.get("scope", {}))
    scope["bbox"] = list(bbox)
    scope.setdefault("center", [(bbox[0] + bbox[2]) / 2, (bbox[1] + bbox[3]) / 2])
    gate = None
    if route_geometry is not None:
        scope.update(kind="gpx", route=route_geometry)
    projection = Projection(*scope["center"])
    points = [p for feature in traffic.get("features", []) for p in geometry_points(feature.get("geometry", {}))]
    full_bbox = (min([bbox[0]] + [p[0] for p in points]) - .0007,
                 min([bbox[1]] + [p[1] for p in points]) - .0005,
                 max([bbox[2]] + [p[0] for p in points]) + .0007,
                 max([bbox[3]] + [p[1] for p in points]) + .0005)
    roads, db_metadata = load_roads(db_path, full_bbox)
    index = RoadIndex(roads, projection)
    results = [match_feature(feature, index, projection, **options) for feature in traffic.get("features", [])]
    if route_geometry is not None:
        gate = RouteGate(route_geometry, projection, index)
        for result in results:
            gate.evaluate(result)
    counts = Counter(row["id"] for row in results)
    for row in results:
        if not row["id"] or counts[row["id"]] > 1:
            row["reasons"] = sorted(set(row["reasons"] + ["duplicate_or_missing_segment_id"]))
            row["eligible"] = False
    eligible = [row for row in results if row["eligible"]]
    positive = [row for row in eligible if row["excess_kmh"] > 0]
    candidates = cluster_candidates(positive, projection)
    top5_eligible = [dict(row, rank=rank) for rank, row in enumerate(sorted(eligible, key=ranking_key)[:5], 1)]
    exclusions = Counter(reason for row in results if not row["eligible"] for reason in row["reasons"])
    observation_times = sorted({str(row["observed_at_raw"]) for row in results if row["observed_at_raw"]})
    speed_basis = (dict(field="average_speed", label="Durchschnitt",
        description="Provider historical typical segment speed for the source snapshot's day and time; its historical observation window is not supplied.",
        confidence_note="Historical-average confidence and sample size are not supplied. Current score/c-value and current closure status do not describe this average. The raw source timestamp identifies the export/snapshot, not the historical observation window.")
        if speed_field == "average_speed" else dict(field="speed", label="Aktuell",
        description="Provider current estimated segment speed from measured-source score-30 data.",
        confidence_note="Provider c-value is a confidence index, not a probability or a speeding rate; the source timestamp's timezone remains as supplied."))
    roads_geojson = dict(type="FeatureCollection", features=[dict(type="Feature", id=str(road.way_id),
        geometry=dict(type="LineString", coordinates=road.coordinates),
        properties=dict(osm_id=road.way_id, name=road.properties.get("street_name"), ref=road.properties.get("ref"),
                        highway=road.properties.get("highway"), maxspeed=road.tags.get("maxspeed"))) for road in roads])
    report = dict(format="youspeed.traffic-hotspots.snapshot.v1", scope=scope,
                  fetched_at=metadata.get("fetched_at"), generated_at=datetime.now(timezone.utc).isoformat(),
                  observation_time=observation_times[0] if len(observation_times) == 1 else None,
                  observation_times=observation_times,
                  observation_time_role="snapshot_export_timestamp" if speed_field == "average_speed" else "reported_current_speed_timestamp",
                  speed_basis=speed_basis,
                  summary=dict(traffic_segments=len(results), eligible_segments=len(eligible),
                               positive_excess_segments=len(positive), candidate_segments=len(candidates),
                               excluded_segments=len(results) - len(eligible), top_count=min(10, len(candidates)),
                               substantial_candidates=sum(row["substantial"] for row in candidates),
                               eligible_comparison_count=len(eligible), top5_count=len(top5_eligible)),
                  sources=metadata.get("sources", []), metadata=metadata, osm_metadata=db_metadata,
                  methodology=["Snapshot candidate screening, not individual-vehicle speeding rates.",
                    ("Rank only the provider's Durchschnitt (average_speed); no fallback to Aktuell. Current score, c-value, current speed, closure and current-time validity gates are not applied to the historical average. Average-specific confidence is not supplied."
                     if speed_field == "average_speed" else "Measured-source score 30 and provider c-value at least " + str(options.get("min_c_value", 70)) + "; the c-value is not a probability."),
                    "Full traffic geometry sampled at most every 5 metres in a local metric projection; direction and source one-way access retained.",
                    "Every sample must match within 15 metres and 35 degrees; comparable disconnected parallel alignments are excluded.",
                    "One explicit numeric OSM limit must cover the complete matched path. Conditional, vehicle, lane and variable uncertainty fails closed.",
                    ("Rank by average excess km/h, then percent excess, then stable source ID. Positive excess is a candidate; substantial means at least max(10 km/h, 20% of limit). The five strongest eligible comparisons also include values at/below the mapped limit."
                     if speed_field == "average_speed" else "Rank by aggregate excess km/h, then percent excess, then provider c-value. Positive excess is a candidate; substantial means at least max(10 km/h, 20% of limit)."),
                    "Adjacent same-road/direction/limit positive links are represented once by their strongest member; displayed speed is that member's source value.",
                    "Observation timestamps, source timezone assumptions, freshness and OSM source dates are retained; no claim of live or legally current limits."],
                  exclusions=dict(exclusions), roads=roads_geojson, traffic=traffic,
                  candidates=candidates, top10=candidates[:10], top5_eligible=top5_eligible, diagnostics=results)
    if route_geometry is not None:
        report["methodology"].insert(1, "GPX scope: at least 99.5% of the traffic segment must align within 30 metres and 35 degrees of the route, and every matched directed OSM way must occur on the unambiguous GPX match. The 30m corridor includes a small endpoint tolerance; partial-overlap, opposite-direction and merely nearby sections are excluded.")
        on_route = [row for row in results if row["on_route"]]
        off_route = [row for row in results if not row["on_route"]]
        report["route_exclusions"] = dict(Counter(reason for row in on_route if not row["eligible"] for reason in row["reasons"]))
        report["scope_exclusions"] = dict(Counter(reason for row in off_route for reason in row["reasons"]
                if reason in {"outside_directed_gpx_corridor", "no_directed_osm_route_overlap", "partial_directed_osm_route_overlap"}))
        report["route_coverage"] = gate.coverage(results, speed_field=speed_field)
        report["summary"].update(fetched_traffic_segments=len(results), on_route_segments=len(on_route),
            off_route_segments=len(off_route), route_excluded_segments=sum(not row["eligible"] for row in on_route),
            route_intersecting_segments=sum(row["route_overlap_pct"] > 0 and bool(row["route_osm_overlap_ways"]) for row in results),
            route_length_m=report["route_coverage"]["route_length_m"],
            route_selected_coverage_pct=report["route_coverage"]["selected_traffic_coverage_pct"],
            route_eligible_coverage_pct=report["route_coverage"]["eligible_traffic_coverage_pct"])
        if speed_field == "average_speed":
            average_available = lambda row: row["speed_kmh"] is not None and 0 < row["speed_kmh"] <= 300
            report["summary"].update(average_source_segments=sum(average_available(row) for row in results),
                on_route_average_source_segments=sum(average_available(row) for row in on_route),
                route_average_source_coverage_pct=report["route_coverage"]["average_source_coverage_pct"])
        else:
            report["summary"].update(on_route_measured_segments=sum(number(row["source_score"]) == 30 for row in on_route),
                route_measured_coverage_pct=report["route_coverage"]["measured_traffic_coverage_pct"])
    return report


def write_outputs(report, output_dir):
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    serialized = json.dumps(report, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    (output_dir / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    (output_dir / "data.js").write_text("window.HOTSPOT_REPORT=" + serialized.replace("</", "<\\/") + ";\n")
    geojson = dict(type="FeatureCollection", features=[dict(type="Feature", geometry=row["geometry"],
                    properties={key: value for key, value in row.items() if key != "geometry"}) for row in report["candidates"]])
    (output_dir / "candidates.geojson").write_text(json.dumps(geojson, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    columns = ["rank", "id", "road_name", "direction", "speed_field", "speed_basis_label", "speed_kmh", "osm_limit_kmh", "excess_kmh", "excess_pct", "source_score", "c_value", "confidence_basis", "current_speed_kmh", "current_source_score", "current_c_value", "observed_at_raw", "observed_at_role", "substantial"]
    with (output_dir / "candidates.csv").open("w", newline="") as out:
        writer = csv.DictWriter(out, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(report["candidates"])


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--traffic", required=True, type=Path)
    parser.add_argument("--bbox", required=True, help="west,south,east,north")
    parser.add_argument("--metadata", type=Path)
    parser.add_argument("--gpx", type=Path, help="Restrict traffic to the directed GPX route")
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--min-c-value", type=float, default=70)
    parser.add_argument("--speed-field", choices=("speed", "average_speed"), default="average_speed",
                        help="Rank Durchschnitt by default; current Aktuell requires explicit speed")
    args = parser.parse_args()
    try:
        bbox = tuple(float(value) for value in args.bbox.split(","))
        validate_bbox(bbox)
    except ValueError as error:
        parser.error(str(error))
    metadata = json.loads(args.metadata.read_text()) if args.metadata else {}
    metadata["traffic_sha256"] = hashlib.sha256(args.traffic.read_bytes()).hexdigest()
    metadata["osm_db"] = str(args.db.resolve())
    if args.gpx:
        metadata["gpx_sha256"] = hashlib.sha256(args.gpx.read_bytes()).hexdigest()
        metadata["gpx_file"] = str(args.gpx.resolve())
    report = analyze(args.db, json.loads(args.traffic.read_text()), bbox, metadata,
                     route_geometry=load_gpx(args.gpx) if args.gpx else None,
                     speed_field=args.speed_field, min_c_value=args.min_c_value)
    write_outputs(report, args.output_dir)
    print(json.dumps(dict(summary=report["summary"], exclusions=report["exclusions"],
                          top10=[{key: row[key] for key in ("rank", "id", "road_name", "direction", "speed_kmh", "osm_limit_kmh", "excess_kmh", "c_value")} for row in report["top10"]]), indent=2))


if __name__ == "__main__":
    main()
