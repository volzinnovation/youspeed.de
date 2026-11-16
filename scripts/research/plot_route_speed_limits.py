#!/usr/bin/env python3
"""Compare bundled OSM way limits with MobiData and Mapillary sign locations.

Use --gpx track.gpx --output chart.html to chart the supplied track or route.
An exact geometry match loads the registered route's local Mapillary overlay.
Supply --mapillary for other GPXs to add Mapillary speed-sign observations.
Use --route for a registered route by ID (default ss-r03) and --bundle-db
for a different materialized BW bundle SQLite database. Inputs are read-only.
"""

from __future__ import annotations

import argparse
from bisect import bisect_right
from collections import defaultdict
from contextlib import closing
from dataclasses import dataclass
from hashlib import sha256
from html import escape
from itertools import groupby, permutations
import json
import math
from pathlib import Path
import re
import sqlite3
from xml.etree import ElementTree

from profile_bw_sign_route import distance

ROOT = Path(__file__).resolve().parents[2]
ROUTES = ROOT / "shared/survey/reference-routes/v4/routes.geojson"
BUNDLE = (
    ROOT
    / "mapdata/build/packed-v4-2026-10-27/rollout-final/baden-wuerttemberg/work/source.sqlite"
)
MAPILLARY = ROOT / "output/mapillary"
TEMPLATE = Path(__file__).with_name("route_speed_limits.html")
MAPILLARY_RADIUS_M = 15
MAX_HEADING_ERROR = 30
GRID_M = 36
SEARCH_RADIUS_M = 30


@dataclass(frozen=True)
class Edge:
    x: float
    y: float
    east: float
    north: float
    planar_length: float
    station: float
    length: float

    def at(self, station):
        offset = (station - self.station) / self.length * self.planar_length
        return self.x + offset * self.east, self.y + offset * self.north

    def project(self, x, y):
        offset = (x - self.x) * self.east + (y - self.y) * self.north
        offset = max(0, min(self.planar_length, offset))
        error = math.hypot(
            x - self.x - offset * self.east, y - self.y - offset * self.north
        )
        return error, self.station + offset / self.planar_length * self.length


class Polyline:
    def __init__(self, points, origin):
        lat0, lon0 = origin
        self.origin = origin
        self.longitude_scale = 111195 * math.cos(math.radians(lat0))
        self.vertices = [self.xy(lat, lon) for lat, lon in points]
        self.edges = []
        self.stations = [0.0]
        for a, b, (x, y), (x2, y2) in zip(
            points, points[1:], self.vertices, self.vertices[1:]
        ):
            planar_length = math.hypot(x2 - x, y2 - y)
            if planar_length == 0:
                continue
            length = distance(*a, *b)
            self.edges.append(
                Edge(
                    x,
                    y,
                    (x2 - x) / planar_length,
                    (y2 - y) / planar_length,
                    planar_length,
                    self.length,
                    length,
                )
            )
            self.stations.append(self.length + length)

    @property
    def length(self):
        return self.stations[-1]

    def xy(self, lat, lon):
        return (lon - self.origin[1]) * self.longitude_scale, (
            lat - self.origin[0]
        ) * 111195

    def edge_index(self, station):
        return min(len(self.edges) - 1, bisect_right(self.stations, station) - 1)

    def at(self, station):
        edge = self.edges[self.edge_index(station)]
        return *edge.at(station), edge.east, edge.north

    def project(self, x, y, start=0, end=None):
        last = len(self.edges) if end is None else self.edge_index(end) + 1
        first = self.edge_index(start)
        best = (math.inf, 0.0, 0.0, 0.0)
        for edge in self.edges[first:last]:
            error, station = edge.project(x, y)
            station = (
                max(start, station) if end is None else max(start, min(end, station))
            )
            near_x, near_y = edge.at(station)
            candidate = (
                math.hypot(x - near_x, y - near_y),
                station,
                edge.east,
                edge.north,
            )
            best = min(best, candidate)
        return best


@dataclass(frozen=True)
class WaySpan:
    start: float
    end: float
    way_id: int | None
    direction: int


def cell(position):
    return math.floor(position / GRID_M)


def load_roads(db, points):
    """Index the bundle's unmodified geometry and its shared OSM vertices."""
    lats, lons = zip(*points)
    roads, grid, vertices = {}, defaultdict(list), defaultdict(set)
    query = """
        SELECT w.*, g.points_json, d.forward_allowed, d.backward_allowed
        FROM ways_rtree r CROSS JOIN ways w USING (way_id)
        CROSS JOIN way_geom g USING (way_id)
        JOIN traffic_sign_way_direction d USING (way_id)
        WHERE r.min_lon <= ? AND r.max_lon >= ? AND r.min_lat <= ? AND r.max_lat >= ?
    """
    for row in db.execute(
        query,
        (max(lons) + 0.001, min(lons) - 0.001, max(lats) + 0.001, min(lats) - 0.001),
    ):
        way_id = row["way_id"]
        geometry = Polyline(json.loads(row["points_json"]), points[0])
        roads[way_id] = (row, geometry)
        for vertex in geometry.vertices:
            vertices[vertex].add(way_id)
        for edge in geometry.edges:
            x2, y2 = edge.at(edge.station + edge.length)
            for i in range(
                cell(min(edge.x, x2) - SEARCH_RADIUS_M),
                cell(max(edge.x, x2) + SEARCH_RADIUS_M) + 1,
            ):
                for j in range(
                    cell(min(edge.y, y2) - SEARCH_RADIUS_M),
                    cell(max(edge.y, y2) + SEARCH_RADIUS_M) + 1,
                ):
                    grid[i, j].append((way_id, edge))
    connections = defaultdict(list)
    for vertex, way_ids in vertices.items():
        for pair in permutations(sorted(way_ids), 2):
            connections[pair].append(vertex)
    return roads, grid, connections


def candidates_at(route, station, roads, grid):
    x, y, east, north = route.at(station)
    candidates = {}
    for way_id, edge in grid[cell(x), cell(y)]:
        row, _ = roads[way_id]
        error, on_way = edge.project(x, y)
        if error > SEARCH_RADIUS_M:
            continue
        alignment = east * edge.east + north * edge.north
        for direction, permission in ((1, "forward_allowed"), (-1, "backward_allowed")):
            if row[permission]:
                key = way_id, direction
                candidate = (
                    error**2 / 9 + 12 * (1 - direction * alignment) ** 2,
                    error,
                    on_way,
                )
                candidates[key] = min(candidates.get(key, candidate), candidate)
    return x, y, sorted(candidates.items(), key=lambda entry: (entry[1], entry[0]))[:18]


def transition_cost(previous, current, on_way, x, y, step, connections):
    (old_way, old_direction), (cost, old_station) = previous
    way, direction = current
    if way == old_way:
        if direction != old_direction:
            return cost + 55
        return cost + (18 if (on_way - old_station) * direction < -step else 0)
    shared = connections.get((old_way, way), ())
    gap = min((math.hypot(x - u, y - v) for u, v in shared), default=math.inf)
    return cost + (2 + (max(0, gap - step) / 3) ** 2 if gap < 19 else 110)


def match_route(route, roads, grid, connections, sample_spacing=3):
    """Match directed road geometry as a sequence before locating way boundaries."""
    count = math.ceil(route.length / sample_spacing)
    step = route.length / count
    stations = [(i + 0.5) * step for i in range(count)]
    states, history = {}, []
    for station in stations:
        x, y, emissions = candidates_at(route, station, roads, grid)
        current = {}
        for key, (emission, _, on_way) in emissions:
            parent, cost = None, 0
            if states:

                def transition(entry):
                    return transition_cost(entry, key, on_way, x, y, step, connections)

                previous = min(states.items(), key=transition)
                parent, cost = previous[0], transition(previous)
            current[key] = (cost + emission, parent, on_way)
        if not current:
            current[None] = (0, min(states, key=states.get) if states else None, 0)
        best = min(state[0] for state in current.values())
        history.append(current)
        states = {
            key: (cost - best, on_way)
            for key, (cost, _, on_way) in current.items()
            if key is not None and cost - best < 120
        }

    path, key = [], min(history[-1], key=lambda key: history[-1][key][0])
    for station, back in zip(reversed(stations), reversed(history)):
        if key is None and None not in back:
            key = min(back, key=lambda candidate: back[candidate][0])
        path.append((station, key))
        key = back[key][1]
    path.reverse()

    runs = []
    for key, items in groupby(path, key=lambda entry: entry[1]):
        samples = list(items)
        runs.append((key, samples[0][0], samples[-1][0]))
    bounds = [0.0]
    for (old, _, previous), (new, following, _) in zip(runs, runs[1:]):
        midpoint = (previous + following) / 2
        shared = connections.get((old[0], new[0]), ()) if old and new else ()
        options = []
        for vertex in shared:
            error, station, _, _ = route.project(
                *vertex,
                start=max(0, midpoint - 16),
                end=min(route.length, midpoint + 16),
            )
            if error < 12:
                options.append((abs(station - midpoint) + error, station))
        boundary = min(options)[1] if options else midpoint
        bounds.append(max(bounds[-1], boundary))
    bounds.append(route.length)
    return [
        WaySpan(start, end, *(key or (None, 0)))
        for start, end, (key, _, _) in zip(bounds, bounds[1:], runs)
        if round(end, 2) > round(start, 2)
    ]


def base_limit(road, direction):
    """Return the unconditional OSM road value in the bundle."""
    directional = road["maxspeed_forward" if direction == 1 else "maxspeed_backward"]
    raw = (directional or road["maxspeed"] or "").strip().lower()
    if raw in {"none", "unlimited"}:
        return "∞", "OSM unlimited"
    match = re.fullmatch(r"(\d{1,3})(?:\s*(km/h|kmh|kph|mph))?", raw)
    if match and int(match[1]) > 0:
        return str(round(int(match[1]) * (1.609344 if match[2] == "mph" else 1))), (
            "Directional OSM maxspeed" if directional else "OSM maxspeed"
        )
    tags = (
        [raw] if directional else [raw, road["maxspeed_type"], road["source_maxspeed"]]
    )
    for value in tags:
        if value and (
            speed := {"urban": "50", "rural": "100"}.get(value.lower().split(":")[-1])
        ):
            return speed, "Typed OSM speed"
    return "?", "No base OSM limit"


def related_rows(db, query, way_ids):
    # Keep older SQLite versions below their bind-parameter limit.
    for start in range(0, len(way_ids), 800):
        batch = way_ids[start : start + 800]
        yield from db.execute(query.format(ids=",".join("?" for _ in batch)), batch)


def road_sections(db, roads, spans, way_ids):
    states = related_rows(
        db, "SELECT * FROM road_speed_rule_set WHERE way_id IN ({ids})", way_ids
    )
    conditions = {
        row["way_id"]: "; ".join(
            tag["raw"]
            for tag in json.loads(row["rules_json"]).get("tags", [])
            if tag.get("conditional")
            or tag.get("lane")
            or tag.get("vehicle") not in (None, "all")
        )
        for row in states
    }
    sections = []
    for span in spans:
        if span.way_id is None:
            value, road, source = "?", "Unmatched track", "No matched way"
        else:
            row, _ = roads[span.way_id]
            value, source = base_limit(row, span.direction)
            road = row["street_name"] or row["ref"] or row["highway"]
        sections.append(
            [
                round(span.start, 2),
                round(span.end, 2),
                value,
                span.way_id,
                span.direction,
                road,
                source,
                conditions.get(span.way_id, ""),
            ]
        )
    return sections


def road_bearing(east, north, direction):
    return math.degrees(math.atan2(east * direction, north * direction)) % 360


def heading_error(a, b):
    return abs((a - b + 180) % 360 - 180)


def valid_bearing(value):
    return (
        not isinstance(value, bool)
        and isinstance(value, (float, int))
        and 0 <= value < 360
    )


def mobidata_signs(db, route, roads, spans, way_ids):
    passages = defaultdict(list)
    for index, span in enumerate(spans):
        passages[span.way_id, span.direction].append((index, span))
    query = """
        SELECT a.way_id, a.direction, a.station_chainage_m, t.record_key,
               a.local_heading_deg, t.orientation_deg, t.normalized_code, t.kind, t.numeric_value
        FROM traffic_sign_association a JOIN traffic_sign_runtime t USING (sign_id)
        WHERE a.way_id IN ({ids}) AND a.status = 'accepted'
          AND t.source_id = 'mobidata-bw-vzk' AND t.numeric_value > 0
          AND t.kind IN ('speed_limit', 'speed_limit_end', 'speed_zone_start', 'speed_zone_end')
    """
    for row in related_rows(db, query, way_ids):
        if not valid_bearing(row["orientation_deg"]) or not valid_bearing(
            row["local_heading_deg"]
        ):
            continue
        way_id = row["way_id"]
        direction = row["direction"]
        road_heading = (
            row["local_heading_deg"] + (180 if direction == -1 else 0)
        ) % 360
        difference = heading_error(row["orientation_deg"], road_heading)
        if difference > MAX_HEADING_ERROR:
            continue
        geometry = roads[way_id][1]
        station = row["station_chainage_m"] * (6371008.8 / 6371000.0)
        x, y, _, _ = geometry.at(max(0, min(geometry.length, station)))
        for index, span in passages.get((way_id, direction), ()):
            error, at, east, north = route.project(x, y, span.start, span.end)
            if (
                error <= 8
                and heading_error(road_heading, road_bearing(east, north, 1))
                <= MAX_HEADING_ERROR
            ):
                detail = f"{row['normalized_code']} · Directed OSM way {way_id} · {difference:.1f}° from road heading"
                yield sign(
                    at,
                    row["numeric_value"],
                    row["kind"],
                    row["record_key"],
                    detail,
                    index,
                )


def sign(at, value, kind, key, detail, index):
    return [round(at, 2), f"{value:g}", kind, str(key), detail, index]


def mapillary_signs(overlay, route, roads, spans, cache):
    starts = [span.start for span in spans]
    xs, ys = zip(*route.vertices)
    left, right = min(xs) - MAPILLARY_RADIUS_M, max(xs) + MAPILLARY_RADIUS_M
    bottom, top = min(ys) - MAPILLARY_RADIUS_M, max(ys) + MAPILLARY_RADIUS_M
    for feature in overlay["features"]:
        if feature["geometry"]["type"] != "Point":
            continue
        props = feature["properties"]
        raw = props["value"]
        review = props.get("image_review", {})
        if review.get("duplicate_of_feature_id"):
            continue
        match = re.fullmatch(
            r"regulatory--(end-of-)?maximum-speed-limit-(\d+)--g1", raw
        )
        if match:
            value = int(match[2])
            kind = "speed_limit_end" if match[1] else "speed_limit"
        elif (
            raw
            in {
                "regulatory--speed-limit-zone--g1",
                "regulatory--end-of-speed-limit-zone--g1",
            }
            and review.get("german_sign_code") in {"DE:274.1", "DE:274.2"}
            and review.get("visible_speed_kmh")
        ):
            value = review["visible_speed_kmh"]
            kind = (
                "speed_zone_end"
                if review["german_sign_code"] == "DE:274.2"
                else "speed_zone_start"
            )
        else:
            continue

        x, y = route.xy(*reversed(feature["geometry"]["coordinates"]))
        if not left <= x <= right or not bottom <= y <= top:
            continue
        error, at, east, north = route.project(x, y)
        if error > MAPILLARY_RADIUS_M:
            continue
        key = str(feature["id"])
        angle = props.get("aligned_direction")
        if angle is None and cache is not None:
            record = cache.execute(
                "SELECT aligned_direction FROM mapillary_azimuth WHERE feature_id = ? AND feature_class = ?",
                (key, raw),
            ).fetchone()
            angle = record[0] if record else None
        if not valid_bearing(angle):
            continue
        index = bisect_right(starts, at) - 1
        span = spans[index]
        if span.way_id is None:
            continue
        x_on_route, y_on_route, _, _ = route.at(at)
        _, _, road_east, road_north = roads[span.way_id][1].project(
            x_on_route, y_on_route
        )
        course = road_bearing(road_east, road_north, span.direction)
        if heading_error(course, road_bearing(east, north, 1)) > MAX_HEADING_ERROR:
            continue
        # Mapillary reports the sign-face azimuth, opposite its reader's course.
        difference = heading_error((angle + 180) % 360, course)
        if difference > MAX_HEADING_ERROR:
            continue
        detail = f"{error:.1f} m from track · {difference:.1f}° from road heading"
        if review.get("evidence_image_id"):
            detail += f" · Image {review['evidence_image_id']}"
        last_seen = props.get("last_seen_at")
        if type(last_seen) is not int or not 0 < last_seen <= 8_640_000_000_000_000:
            last_seen = None
        yield [*sign(at, value, kind, key, detail, index), last_seen]


def find_conflicts(sections, sources):
    for provider, events in sources.items():
        for at, value, kind, key, _, index, *_ in events:
            start, end, base, *_ = sections[index]
            if kind.endswith("_end") or base == "?" or base == value:
                continue
            # A projected sign can land just before the boundary it introduces.
            adjacent_match = any(
                0 <= neighbor < len(sections)
                and sections[neighbor][2] == value
                and abs(at - boundary) <= MAPILLARY_RADIUS_M
                for neighbor, boundary in ((index - 1, start), (index + 1, end))
            )
            yield [at, provider, base, value, index, key, adjacent_match]


def connect_readonly(path):
    db = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    return db


def gpx_geometry(path):
    root = ElementTree.parse(path).getroot()
    if root.tag.rsplit("}", 1)[-1] != "gpx":
        raise ValueError("Expected a GPX document")
    tracks = root.findall("./{*}trk")
    if len(tracks) > 1:
        raise ValueError("Supply a GPX with one track or one route")
    if tracks:
        groups = [
            segment.findall("./{*}trkpt")
            for segment in tracks[0].findall("./{*}trkseg")
        ]
    else:
        routes = root.findall("./{*}rte")
        if len(routes) != 1:
            raise ValueError("GPX needs one track or one route")
        groups = [routes[0].findall("./{*}rtept")]

    coordinates = []
    for group in groups:
        segment = []
        for point in group:
            try:
                lon, lat = float(point.get("lon", "")), float(point.get("lat", ""))
            except ValueError:
                raise ValueError(
                    "GPX point needs numeric latitude and longitude"
                ) from None
            if not -180 <= lon <= 180 or not -90 <= lat <= 90:
                raise ValueError(
                    "GPX point is outside valid latitude or longitude bounds"
                )
            segment.append([lon, lat])
        if not segment:
            continue
        if coordinates:
            if coordinates[-1] != segment[0]:
                raise ValueError(
                    "GPX track has a gap between segments. Supply one continuous track."
                )
            coordinates.extend(segment[1:])
        else:
            coordinates.extend(segment)
    if len(coordinates) < 2:
        raise ValueError("GPX needs at least two points")
    return {"type": "LineString", "coordinates": coordinates}


def load_route(args):
    route_set = args.route_set or ROUTES
    if args.gpx is None or args.route_set or route_set.is_file():
        features = json.loads(route_set.read_text(encoding="utf-8"))["features"]
    else:
        features = []
    if args.gpx is None:
        route_id = args.route or "ss-r03"
        feature = next(
            (f for f in features if f["properties"]["route_id"] == route_id), None
        )
        if feature is None:
            raise ValueError(f"Unknown reference route {route_id}")
        return feature["geometry"], feature["properties"]

    geometry = gpx_geometry(args.gpx)
    canonical = json.dumps(
        geometry, sort_keys=True, separators=(",", ":"), allow_nan=False
    )
    digest = sha256(canonical.encode("utf-8")).hexdigest()
    registered = next(
        (
            f["properties"]
            for f in features
            if f["properties"]["geometry_sha256"] == digest
        ),
        None,
    )
    return geometry, registered or {"name": args.gpx.stem, "geometry_sha256": digest}


def load_mapillary(path, props):
    if path is None and (route_id := props.get("route_id")):
        candidate = MAPILLARY / "evaluation" / f"{route_id}.geojson"
        if candidate.is_file():
            path = candidate
    if path is None:
        return None
    overlay = json.loads(path.read_text(encoding="utf-8"))
    if overlay.get("type") != "FeatureCollection" or not isinstance(
        overlay.get("features"), list
    ):
        raise ValueError("Mapillary input must be a GeoJSON FeatureCollection")
    if (digest := overlay.get("route_geometry_sha256")) and digest != props[
        "geometry_sha256"
    ]:
        raise ValueError("Mapillary overlay belongs to a different route geometry")
    if props.get("route_id") and overlay.get("route_id") not in (
        None,
        props["route_id"],
    ):
        raise ValueError("Mapillary overlay belongs to a different registered route")
    return overlay


def build_chart(args):
    geometry, props = load_route(args)
    points = [(lat, lon) for lon, lat in geometry["coordinates"]]
    route = Polyline(points, points[0])
    if round(route.length, 2) <= 0:
        raise ValueError("The route needs two distinct positions")
    if "polyline_length_m" in props and not math.isclose(
        route.length, props["polyline_length_m"], abs_tol=0.02
    ):
        raise ValueError("Route geometry length differs from its registered length")
    overlay = load_mapillary(args.mapillary, props)

    with closing(connect_readonly(args.bundle_db)) as db:
        roads, grid, connections = load_roads(db, points)
        spans = match_route(route, roads, grid, connections)
        way_ids = sorted({span.way_id for span in spans if span.way_id is not None})
        if not way_ids:
            raise ValueError("No bundle roads matched the route")
        sections = road_sections(db, roads, spans, way_ids)
        mobi = sorted(mobidata_signs(db, route, roads, spans, way_ids))
    mapillary = []
    if overlay is not None:
        if args.azimuth_cache:
            with closing(connect_readonly(args.azimuth_cache)) as db:
                mapillary = sorted(mapillary_signs(overlay, route, roads, spans, db))
        else:
            mapillary = sorted(mapillary_signs(overlay, route, roads, spans, None))
    conflicts = sorted(
        find_conflicts(sections, {"MobiData": mobi, "Mapillary": mapillary})
    )
    title = args.title or props["name"]
    return {
        "title": title,
        "length": round(route.length, 2),
        "segments": sections,
        "mobi": mobi,
        "mapillary": mapillary,
        "mapillary_loaded": overlay is not None,
        "conflicts": conflicts,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group()
    source.add_argument(
        "--gpx", type=Path, help="GPX track or route in the direction of travel"
    )
    source.add_argument("--route", help="reference route ID (default ss-r03)")
    parser.add_argument(
        "--route-set",
        type=Path,
        help="reference routes GeoJSON (defaults to the local v4 route set)",
    )
    parser.add_argument(
        "--bundle-db", type=Path, default=BUNDLE, help="materialized BW bundle SQLite"
    )
    parser.add_argument(
        "--mapillary",
        type=Path,
        help="Mapillary point GeoJSON with sign classes and headings",
    )
    parser.add_argument(
        "--azimuth-cache", type=Path, help="optional Mapillary heading SQLite cache"
    )
    parser.add_argument("--title", help="optional display title")
    parser.add_argument(
        "--output", type=Path, required=True, help="destination HTML file"
    )
    parser.add_argument(
        "--fragment", action="store_true", help="write an embeddable HTML fragment"
    )
    args = parser.parse_args()
    try:
        data = build_chart(args)
        payload = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace(
            "<", "\\u003c"
        )
        template = TEMPLATE.read_text(encoding="utf-8")
        document = (
            template.split("<!-- Chart fragment -->")[1] if args.fragment else template
        )
        document = document.replace("<!-- Chart fragment -->", "")
        document = document.replace("__ROUTE_TITLE__", escape(data["title"])).replace(
            "__ROUTE_DATA__", payload
        )
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(document, encoding="utf-8")
    except (OSError, ValueError, sqlite3.Error, ElementTree.ParseError) as error:
        parser.exit(1, f"{error}\n")

    conflict_ways = {data["segments"][entry[4]][3] for entry in data["conflicts"]}
    print(
        f"{data['title']}: {len(data['conflicts'])} conflicting observations on "
        f"{len(conflict_ways)} OSM ways. Wrote {args.output}"
    )


if __name__ == "__main__":
    main()
