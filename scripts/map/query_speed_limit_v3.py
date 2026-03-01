#!/usr/bin/env python3
"""Query speed-limit candidates from v3 SQLite/SpatiaLite artifacts."""

from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

from city_polygon_resolver import resolve_city_context

DEFAULT_DE_URBAN = 50
DEFAULT_DE_RURAL_CAR = 100
PLACE_VALUES = {"city", "town", "village", "hamlet"}
PLACE_RANK = {"city": 0, "town": 1, "village": 2, "hamlet": 3}
NUMERIC_SPEED_RE = re.compile(r"^(\d{1,3})")
DRIVABLE_HIGHWAYS_CAR = {
    "motorway",
    "trunk",
    "primary",
    "secondary",
    "tertiary",
    "unclassified",
    "residential",
    "service",
    "living_street",
    "motorway_link",
    "trunk_link",
    "primary_link",
    "secondary_link",
    "tertiary_link",
    "road",
}


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371008.8
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def distance_to_bbox_m(lat: float, lon: float, row: dict) -> float:
    clamped_lon = min(max(lon, row["min_lon"]), row["max_lon"])
    clamped_lat = min(max(lat, row["min_lat"]), row["max_lat"])
    return haversine_m(lat, lon, clamped_lat, clamped_lon)


def _xy_m(lat: float, lon: float, lat0: float, lon0: float) -> Tuple[float, float]:
    meters_per_deg_lat = 111132.0
    meters_per_deg_lon = 111320.0 * math.cos(math.radians(lat0))
    x = (lon - lon0) * meters_per_deg_lon
    y = (lat - lat0) * meters_per_deg_lat
    return x, y


def point_to_segment_distance_m(
    lat: float, lon: float, lat1: float, lon1: float, lat2: float, lon2: float
) -> float:
    px, py = _xy_m(lat, lon, lat, lon)
    x1, y1 = _xy_m(lat1, lon1, lat, lon)
    x2, y2 = _xy_m(lat2, lon2, lat, lon)
    dx = x2 - x1
    dy = y2 - y1
    if dx == 0.0 and dy == 0.0:
        return math.hypot(px - x1, py - y1)
    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    proj_x = x1 + t * dx
    proj_y = y1 + t * dy
    return math.hypot(px - proj_x, py - proj_y)


def polyline_distance_m(lat: float, lon: float, points: List[List[float]]) -> float:
    if not points:
        return float("inf")
    if len(points) == 1:
        return haversine_m(lat, lon, points[0][0], points[0][1])
    best = float("inf")
    for i in range(len(points) - 1):
        lat1, lon1 = points[i]
        lat2, lon2 = points[i + 1]
        d = point_to_segment_distance_m(lat, lon, lat1, lon1, lat2, lon2)
        if d < best:
            best = d
    return best


def heading_mismatch_deg(heading: float, approx_heading: Optional[float]) -> Optional[float]:
    if approx_heading is None:
        return None
    raw = abs((heading - approx_heading) % 360.0)
    raw = min(raw, 360.0 - raw)
    return min(raw, abs(180.0 - raw))


def parse_explicit_speed_kmh(row: dict) -> Optional[int]:
    for key in ("maxspeed",):
        value = row.get(key)
        if isinstance(value, str):
            m = NUMERIC_SPEED_RE.match(value.strip())
            if m:
                return int(m.group(1))
    for key in ("maxspeed_type", "source_maxspeed"):
        value = row.get(key)
        if value == "DE:urban":
            return 50
        if value == "DE:rural":
            return 100
    return None


def point_in_bbox(lat: float, lon: float, row: dict) -> bool:
    return row["min_lat"] <= lat <= row["max_lat"] and row["min_lon"] <= lon <= row["max_lon"]


def _point_on_segment(lon: float, lat: float, x1: float, y1: float, x2: float, y2: float, eps: float = 1e-12) -> bool:
    cross = (lon - x1) * (y2 - y1) - (lat - y1) * (x2 - x1)
    if abs(cross) > eps:
        return False
    dot = (lon - x1) * (x2 - x1) + (lat - y1) * (y2 - y1)
    if dot < -eps:
        return False
    sq_len = (x2 - x1) ** 2 + (y2 - y1) ** 2
    if dot - sq_len > eps:
        return False
    return True


def _point_in_ring(lon: float, lat: float, ring: List[List[float]]) -> bool:
    if len(ring) < 4:
        return False
    inside = False
    for i in range(len(ring) - 1):
        x1, y1 = float(ring[i][0]), float(ring[i][1])
        x2, y2 = float(ring[i + 1][0]), float(ring[i + 1][1])
        if _point_on_segment(lon, lat, x1, y1, x2, y2):
            return True
        intersects = ((y1 > lat) != (y2 > lat)) and (
            lon < (x2 - x1) * (lat - y1) / ((y2 - y1) if (y2 - y1) != 0 else 1e-30) + x1
        )
        if intersects:
            inside = not inside
    return inside


def _resolve_residential_context(lat: float, lon: float, area_candidates: Iterable[dict], enabled: bool) -> Dict[str, object]:
    if not enabled:
        return {
            "inside_city": False,
            "candidate_polygons": 0,
            "containing_polygons": 0,
            "residential_mode": "unavailable",
        }

    candidate_polygons = 0
    containing_polygons = 0
    for area in area_candidates:
        residential = area.get("residential")
        if not isinstance(residential, str) or not residential.strip():
            continue
        points = area.get("points")
        if not isinstance(points, list) or len(points) < 4:
            continue
        candidate_polygons += 1
        if _point_in_ring(lon, lat, points):
            containing_polygons += 1

    return {
        "inside_city": containing_polygons > 0,
        "candidate_polygons": candidate_polygons,
        "containing_polygons": containing_polygons,
        "residential_mode": "polygon_containment",
    }


def _column_exists(conn: sqlite3.Connection, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    for row in rows:
        if len(row) >= 2 and row[1] == column:
            return True
    return False


def _bbox_area(area: dict) -> float:
    return max(float(area["max_lon"]) - float(area["min_lon"]), 0.0) * max(float(area["max_lat"]) - float(area["min_lat"]), 0.0)


def _resolve_city_context_from_areas(lat: float, lon: float, area_candidates: Iterable[dict]) -> dict:
    containing_admin: List[Tuple[int, float, str]] = []
    containing_places: List[Tuple[int, float, str]] = []
    nearby_places: List[Tuple[int, float, str]] = []

    for area in area_candidates:
        name = area.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        place = area.get("place")
        area_is_admin = area.get("boundary") == "administrative" and area.get("admin_level") in {"8", "9"}
        inside_bbox = point_in_bbox(lat, lon, area)
        area_size = _bbox_area(area)

        if area_is_admin and inside_bbox:
            containing_admin.append((int(area["admin_level"]), area_size, name))

        if place in PLACE_VALUES:
            center_lat = (float(area["min_lat"]) + float(area["max_lat"])) / 2.0
            center_lon = (float(area["min_lon"]) + float(area["max_lon"])) / 2.0
            d = haversine_m(lat, lon, center_lat, center_lon)
            rank = int(PLACE_RANK.get(place, 99))
            nearby_places.append((rank, d, name))
            if inside_bbox:
                containing_places.append((rank, d, name))

    if containing_admin:
        containing_admin.sort(key=lambda x: (x[0], x[1], x[2]))
        best = containing_admin[0]
        return {
            "inside_city": True,
            "city_name": best[2],
            "city_admin_level": best[0],
            "city_source": "admin_bbox",
            "city_candidate_boundaries": len(containing_admin),
            "city_place_candidates": len(nearby_places),
        }

    if containing_places:
        containing_places.sort(key=lambda x: (x[0], x[1], x[2]))
        best = containing_places[0]
        return {
            "inside_city": True,
            "city_name": best[2],
            "city_admin_level": None,
            "city_source": "place_bbox",
            "city_candidate_boundaries": 0,
            "city_place_candidates": len(nearby_places),
        }

    if nearby_places:
        nearby_places.sort(key=lambda x: (x[0], x[1], x[2]))
        best = nearby_places[0]
        return {
            "inside_city": False,
            "city_name": best[2],
            "city_admin_level": None,
            "city_source": "place_nearest",
            "city_candidate_boundaries": 0,
            "city_place_candidates": len(nearby_places),
        }

    return {
        "inside_city": False,
        "city_name": None,
        "city_admin_level": None,
        "city_source": None,
        "city_candidate_boundaries": 0,
        "city_place_candidates": 0,
    }


def _query_way_rows(
    conn: sqlite3.Connection,
    lat: float,
    lon: float,
    radius_m: float,
    limit_rows: int,
    has_street_name: bool,
    has_ref: bool,
    has_service: bool,
    has_tunnel: bool,
    has_bridge: bool,
    has_covered: bool,
    has_location: bool,
    has_layer: bool,
    has_level: bool,
) -> List[dict]:
    deg_lat = radius_m / 111132.0
    cos_lat = max(0.173648, abs(math.cos(math.radians(lat))))
    deg_lon = radius_m / (111320.0 * cos_lat)
    min_lat = lat - deg_lat
    max_lat = lat + deg_lat
    min_lon = lon - deg_lon
    max_lon = lon + deg_lon

    street_name_select = "w.street_name" if has_street_name else "NULL"
    ref_select = "w.ref" if has_ref else "NULL"
    service_select = "w.service" if has_service else "NULL"
    tunnel_select = "w.tunnel" if has_tunnel else "NULL"
    bridge_select = "w.bridge" if has_bridge else "NULL"
    covered_select = "w.covered" if has_covered else "NULL"
    location_select = "w.location" if has_location else "NULL"
    layer_select = "w.layer" if has_layer else "NULL"
    level_select = "w.level" if has_level else "NULL"
    sql = f"""
    SELECT
      w.way_id,
      w.highway,
      {street_name_select} AS street_name,
      {ref_select} AS ref,
      w.maxspeed,
      w.maxspeed_type,
      w.source_maxspeed,
      w.approx_heading_deg,
      {service_select} AS service,
      {tunnel_select} AS tunnel,
      {bridge_select} AS bridge,
      {covered_select} AS covered,
      {location_select} AS location,
      {layer_select} AS layer,
      {level_select} AS level,
      w.min_lon,
      w.min_lat,
      w.max_lon,
      w.max_lat,
      g.points_json
    FROM ways_rtree r
    JOIN ways w ON w.row_id = r.row_id
    LEFT JOIN way_geom g ON g.row_id = w.row_id
    WHERE r.min_lon <= ? AND r.max_lon >= ?
      AND r.min_lat <= ? AND r.max_lat >= ?
    ORDER BY
      (
        CASE
          WHEN ? < w.min_lon THEN (w.min_lon - ?)
          WHEN ? > w.max_lon THEN (? - w.max_lon)
          ELSE 0
        END
      ) * (
        CASE
          WHEN ? < w.min_lon THEN (w.min_lon - ?)
          WHEN ? > w.max_lon THEN (? - w.max_lon)
          ELSE 0
        END
      ) +
      (
        CASE
          WHEN ? < w.min_lat THEN (w.min_lat - ?)
          WHEN ? > w.max_lat THEN (? - w.max_lat)
          ELSE 0
        END
      ) * (
        CASE
          WHEN ? < w.min_lat THEN (w.min_lat - ?)
          WHEN ? > w.max_lat THEN (? - w.max_lat)
          ELSE 0
        END
      )
    LIMIT ?
    """
    params = (
        max_lon,
        min_lon,
        max_lat,
        min_lat,
        lon,
        lon,
        lon,
        lon,
        lon,
        lon,
        lon,
        lon,
        lat,
        lat,
        lat,
        lat,
        lat,
        lat,
        lat,
        lat,
        limit_rows,
    )
    rows = []
    cur = conn.execute(sql, params)
    for r in cur.fetchall():
        points: List[List[float]] = []
        if isinstance(r[19], str) and r[19]:
            try:
                parsed = json.loads(r[19])
                if isinstance(parsed, list):
                    points = parsed
            except json.JSONDecodeError:
                points = []
        rows.append(
            {
                "way_id": str(r[0]),
                "highway": r[1],
                "street_name": r[2],
                "ref": r[3],
                "maxspeed": r[4],
                "maxspeed_type": r[5],
                "source_maxspeed": r[6],
                "approx_heading_deg": r[7],
                "service": r[8],
                "tunnel": r[9],
                "bridge": r[10],
                "covered": r[11],
                "location": r[12],
                "layer": r[13],
                "level": r[14],
                "min_lon": float(r[15]),
                "min_lat": float(r[16]),
                "max_lon": float(r[17]),
                "max_lat": float(r[18]),
                "points": points,
            }
        )
    return rows


def _query_area_rows(
    conn: sqlite3.Connection,
    lat: float,
    lon: float,
    limit_rows: int = 512,
    has_residential: bool = False,
    has_points_json: bool = False,
) -> List[dict]:
    place_window_deg = 0.3
    residential_select = "a.residential" if has_residential else "NULL"
    points_select = "a.points_json" if has_points_json else "NULL"
    sql = """
    SELECT
      a.area_id, a.geometry_type, a.name, a.place, a.boundary, a.admin_level,
      a.min_lon, a.min_lat, a.max_lon, a.max_lat,
      {residential_select} AS residential,
      {points_select} AS points_json
    FROM areas_rtree r
    JOIN areas a ON a.row_id = r.row_id
    WHERE
      (
        r.min_lon <= ? AND r.max_lon >= ?
        AND r.min_lat <= ? AND r.max_lat >= ?
      )
      OR
      (
        a.place IN ('city','town','village','hamlet')
        AND r.min_lon <= ? AND r.max_lon >= ?
        AND r.min_lat <= ? AND r.max_lat >= ?
      )
    LIMIT ?
    """.format(residential_select=residential_select, points_select=points_select)
    cur = conn.execute(
        sql,
        (
            lon,
            lon,
            lat,
            lat,
            lon + place_window_deg,
            lon - place_window_deg,
            lat + place_window_deg,
            lat - place_window_deg,
            limit_rows,
        ),
    )
    out = []
    for r in cur.fetchall():
        points: List[List[float]] = []
        if isinstance(r[11], str) and r[11]:
            try:
                parsed = json.loads(r[11])
                if isinstance(parsed, list):
                    points = parsed
            except json.JSONDecodeError:
                points = []
        out.append(
            {
                "area_id": str(r[0]),
                "geometry_type": r[1],
                "name": r[2],
                "place": r[3],
                "boundary": r[4],
                "admin_level": r[5],
                "min_lon": float(r[6]),
                "min_lat": float(r[7]),
                "max_lon": float(r[8]),
                "max_lat": float(r[9]),
                "residential": r[10],
                "points": points,
            }
        )
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Query speed candidates from v3 SQLite/SpatiaLite DB")
    parser.add_argument("--db", required=True, help="Path to speeds_v3.sqlite")
    parser.add_argument("--lat", required=True, type=float, help="Latitude in degrees")
    parser.add_argument("--lon", required=True, type=float, help="Longitude in degrees")
    parser.add_argument("--heading", type=float, default=None, help="Heading in degrees (0-360)")
    parser.add_argument("--search-radius-m", type=float, default=1200.0, help="RTree search radius in meters")
    parser.add_argument("--max-candidates", type=int, default=5000, help="SQL prefilter candidate cap")
    parser.add_argument("--top-k", type=int, default=5, help="Number of candidates to return")
    parser.add_argument("--heading-weight", type=float, default=2.0, help="Meters per degree heading penalty")
    parser.add_argument(
        "--distance-mode",
        choices=("bbox", "polyline", "hybrid"),
        default="hybrid",
        help="Distance scoring mode",
    )
    parser.add_argument("--polyline-top-n", type=int, default=250, help="Hybrid refinement top-N rows")
    parser.add_argument(
        "--vehicle-profile",
        choices=("car", "any"),
        default="car",
        help="Candidate filtering profile",
    )
    parser.add_argument("--unknown-highway-penalty", type=float, default=30.0)
    parser.add_argument(
        "--city-db",
        help="Optional SQLite DB with city_boundary/city_ring tables (defaults to sibling dist-v4 DB)",
    )
    return parser.parse_args()


def _default_city_db_path(db_path: Path) -> Path:
    # mapdata/dist-v3/<region>/speeds_v3.sqlite -> mapdata/dist-v4/<region>/speeds_v4.sqlite
    return db_path.parent.parent.parent / "dist-v4" / db_path.parent.name / "speeds_v4.sqlite"


def main() -> int:
    args = parse_args()
    started = time.perf_counter()

    if not (-90.0 <= args.lat <= 90.0 and -180.0 <= args.lon <= 180.0):
        print("Invalid coordinate range", file=sys.stderr)
        return 1
    if args.heading is not None and not (0.0 <= args.heading <= 360.0):
        print("Heading must be in range [0, 360]", file=sys.stderr)
        return 1
    if args.search_radius_m <= 0.0:
        print("search-radius-m must be > 0", file=sys.stderr)
        return 1
    if args.max_candidates <= 0:
        print("max-candidates must be > 0", file=sys.stderr)
        return 1
    if args.top_k <= 0:
        print("top-k must be > 0", file=sys.stderr)
        return 1
    if args.polyline_top_n <= 0:
        print("polyline-top-n must be > 0", file=sys.stderr)
        return 1

    db_path = Path(args.db)
    if not db_path.exists():
        print(f"Missing artifact: {db_path}", file=sys.stderr)
        return 1

    t0 = time.perf_counter()
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    schema_ok = bool(
        conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name IN ('ways','ways_rtree','areas','areas_rtree') LIMIT 1"
        ).fetchone()
    )
    if not schema_ok:
        print("Invalid v3 DB schema", file=sys.stderr)
        return 1
    has_street_name = _column_exists(conn, "ways", "street_name")
    has_ref = _column_exists(conn, "ways", "ref")
    has_service = _column_exists(conn, "ways", "service")
    has_tunnel = _column_exists(conn, "ways", "tunnel")
    has_bridge = _column_exists(conn, "ways", "bridge")
    has_covered = _column_exists(conn, "ways", "covered")
    has_location = _column_exists(conn, "ways", "location")
    has_layer = _column_exists(conn, "ways", "layer")
    has_level = _column_exists(conn, "ways", "level")
    has_area_residential = _column_exists(conn, "areas", "residential")
    has_area_points_json = _column_exists(conn, "areas", "points_json")
    index_load_ms = (time.perf_counter() - t0) * 1000.0

    t1 = time.perf_counter()
    ways = _query_way_rows(
        conn=conn,
        lat=args.lat,
        lon=args.lon,
        radius_m=args.search_radius_m,
        limit_rows=args.max_candidates,
        has_street_name=has_street_name,
        has_ref=has_ref,
        has_service=has_service,
        has_tunnel=has_tunnel,
        has_bridge=has_bridge,
        has_covered=has_covered,
        has_location=has_location,
        has_layer=has_layer,
        has_level=has_level,
    )
    area_candidates = _query_area_rows(
        conn=conn,
        lat=args.lat,
        lon=args.lon,
        has_residential=has_area_residential,
        has_points_json=has_area_points_json,
    )
    candidate_load_ms = (time.perf_counter() - t1) * 1000.0

    city_db_path = Path(args.city_db) if args.city_db else _default_city_db_path(db_path)

    t_city = time.perf_counter()
    city_context = None
    if city_db_path.exists():
        try:
            if str(city_db_path) == str(db_path):
                city_context = resolve_city_context(conn, args.lat, args.lon)
            else:
                city_conn = sqlite3.connect(str(city_db_path))
                city_context = resolve_city_context(city_conn, args.lat, args.lon)
                city_conn.close()
        except sqlite3.Error:
            city_context = None
    if not isinstance(city_context, dict) or city_context.get("city_mode") == "unavailable":
        city_context = _resolve_city_context_from_areas(args.lat, args.lon, area_candidates)
        city_context["city_mode"] = "bbox_fallback"
    residential_context = _resolve_residential_context(
        args.lat,
        args.lon,
        area_candidates,
        enabled=bool(has_area_residential and has_area_points_json),
    )
    city_resolve_ms = (time.perf_counter() - t_city) * 1000.0

    t2 = time.perf_counter()
    scored: List[dict] = []
    filtered_non_drivable = 0
    for row in ways:
        parsed_speed = parse_explicit_speed_kmh(row)
        highway = row.get("highway")
        if args.vehicle_profile == "car":
            if highway is not None and highway not in DRIVABLE_HIGHWAYS_CAR:
                filtered_non_drivable += 1
                continue

        distance_m = distance_to_bbox_m(args.lat, args.lon, row)
        heading_diff = None
        heading_penalty = 0.0
        if args.heading is not None:
            heading_diff = heading_mismatch_deg(args.heading, row.get("approx_heading_deg"))
            if heading_diff is not None:
                heading_penalty = heading_diff * args.heading_weight

        unknown_highway_penalty = 0.0
        if args.vehicle_profile == "car" and highway is None:
            unknown_highway_penalty = args.unknown_highway_penalty

        score = distance_m + heading_penalty + unknown_highway_penalty
        scored.append(
            {
                "way_id": row["way_id"],
                "highway": highway,
                "street_name": row.get("street_name"),
                "ref": row.get("ref"),
                "distance_m": round(distance_m, 2),
                "heading_diff_deg": None if heading_diff is None else round(heading_diff, 2),
                "score": round(score, 2),
                "maxspeed": row.get("maxspeed"),
                "maxspeed_type": row.get("maxspeed_type"),
                "source_maxspeed": row.get("source_maxspeed"),
                "service": row.get("service"),
                "tunnel": row.get("tunnel"),
                "bridge": row.get("bridge"),
                "covered": row.get("covered"),
                "location": row.get("location"),
                "layer": row.get("layer"),
                "level": row.get("level"),
                "parsed_speed_kmh": parsed_speed,
                "points": row.get("points", []),
                "_heading_penalty": heading_penalty,
                "_unknown_highway_penalty": unknown_highway_penalty,
            }
        )

    polyline_refine_mode = "disabled"
    refined_polyline_rows = 0
    polyline_missing_rows = 0
    t_poly = time.perf_counter()
    if args.distance_mode != "bbox":
        sorted_scored = sorted(scored, key=lambda r: (r["score"], r["distance_m"], r["way_id"]))
        refine_rows = sorted_scored[: args.polyline_top_n] if args.distance_mode == "hybrid" else sorted_scored
        polyline_refine_mode = "active"
        for row in refine_rows:
            pts = row.get("points")
            if not isinstance(pts, list) or not pts:
                polyline_missing_rows += 1
                continue
            dpoly = polyline_distance_m(args.lat, args.lon, pts)
            score = dpoly + row["_heading_penalty"] + row["_unknown_highway_penalty"]
            row["distance_m"] = round(dpoly, 2)
            row["score"] = round(score, 2)
            refined_polyline_rows += 1
    polyline_refine_ms = (time.perf_counter() - t_poly) * 1000.0

    scored.sort(key=lambda r: (r["score"], r["distance_m"], r["way_id"]))
    for row in scored:
        row.pop("_heading_penalty", None)
        row.pop("_unknown_highway_penalty", None)
        row.pop("points", None)
    top = scored[: args.top_k]
    scoring_ms = (time.perf_counter() - t2) * 1000.0

    built_up = bool(residential_context.get("inside_city", False))
    default_speed = DEFAULT_DE_URBAN if built_up else DEFAULT_DE_RURAL_CAR
    best = top[0] if top else None
    if best and best.get("parsed_speed_kmh") is not None:
        effective_speed = best["parsed_speed_kmh"]
        effective_source = "map_explicit"
    else:
        effective_speed = default_speed
        effective_source = "default_rule"

    result = {
        "input": {
            "lat": args.lat,
            "lon": args.lon,
            "heading": args.heading,
            "search_radius_m": args.search_radius_m,
            "max_candidates": args.max_candidates,
            "db": str(db_path),
        },
        "summary": {
            "candidate_way_ids": len({r["way_id"] for r in ways}),
            "matched_way_rows": len(ways),
            "filtered_non_drivable_rows": filtered_non_drivable,
            "scored_rows": len(scored),
            "distance_mode_requested": args.distance_mode,
            "distance_mode_effective": "polyline" if polyline_refine_mode == "active" else "bbox",
            "polyline_refine_mode": polyline_refine_mode,
            "polyline_refined_rows": refined_polyline_rows,
            "polyline_missing_rows": polyline_missing_rows,
            "candidate_areas": len(area_candidates),
            "inside_built_up_guess": built_up,
            "residential_candidate_polygons": residential_context.get("candidate_polygons", 0),
            "residential_containing_polygons": residential_context.get("containing_polygons", 0),
            "residential_mode": residential_context.get("residential_mode"),
            "default_speed_kmh": default_speed,
            "effective_speed_kmh": effective_speed,
            "effective_speed_source": effective_source,
            "city_name": city_context.get("city_name"),
            "city_admin_level": city_context.get("city_admin_level"),
            "city_source": city_context.get("city_source"),
            "city_candidate_boundaries": city_context.get("city_candidate_boundaries", 0),
            "city_containing_boundaries": city_context.get("city_containing_boundaries", 0),
            "city_place_candidates": city_context.get("city_place_candidates", 0),
            "city_mode": city_context.get("city_mode"),
            "has_street_name_column": has_street_name,
            "has_ref_column": has_ref,
            "has_service_column": has_service,
            "has_tunnel_column": has_tunnel,
            "has_bridge_column": has_bridge,
            "has_covered_column": has_covered,
            "has_location_column": has_location,
            "has_layer_column": has_layer,
            "has_level_column": has_level,
        },
        "timing_ms": {
            "load_index": round(index_load_ms, 2),
            "load_candidates": round(candidate_load_ms, 2),
            "city_resolve": round(city_resolve_ms, 2),
            "polyline_refine": round(polyline_refine_ms, 2),
            "score_and_rank": round(scoring_ms, 2),
            "total": round((time.perf_counter() - started) * 1000.0, 2),
        },
        "top_candidates": top,
        "notes": [
            "v3 query uses SQLite RTree candidate prefilter.",
            "Built-up inference uses residential=* polygon containment from areas table.",
            "Use camera-detected signs to override map/default limits in final fusion.",
        ],
    }

    conn.close()
    print(f"query_time_ms={result['timing_ms']['total']}", file=sys.stderr)
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
