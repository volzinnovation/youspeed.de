#!/usr/bin/env python3
"""Query speed-limit candidates from v4 SQLite/SpatiaLite + tile prefilter DB."""

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

DEFAULT_DE_URBAN = 50
DEFAULT_DE_RURAL_CAR = 100
PLACE_VALUES = {"city", "town", "village", "hamlet"}
PLACE_RANK = {"city": 0, "town": 1, "village": 2, "hamlet": 3}
CITY_BOUNDARY_PRIORITY = {9: 0, 8: 1, 6: 2}
PRIMARY_PLACE_MAX_RANK = 1
NEAREST_PLACE_FALLBACK_MAX_DISTANCE_M = 5000.0
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
EARTH_RADIUS_M = 6378137.0
MAX_MERCATOR_LAT = 85.05112878


def _lon_lat_to_mercator_m(lon: float, lat: float) -> Tuple[float, float]:
    lat = min(max(lat, -MAX_MERCATOR_LAT), MAX_MERCATOR_LAT)
    x = EARTH_RADIUS_M * math.radians(lon)
    y = EARTH_RADIUS_M * math.log(math.tan(math.pi / 4.0 + math.radians(lat) / 2.0))
    return x, y


def _tile_for_lon_lat(lon: float, lat: float, tile_size_m: int) -> Tuple[int, int]:
    x, y = _lon_lat_to_mercator_m(lon, lat)
    return (math.floor(x / tile_size_m), math.floor(y / tile_size_m))


def _tile_id(tx: int, ty: int) -> str:
    return f"{tx}/{ty}"


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1", (table_name,)
    ).fetchone()
    return row is not None


def _column_exists(conn: sqlite3.Connection, table_name: str, column_name: str) -> bool:
    for row in conn.execute(f"PRAGMA table_info({table_name})"):
        if str(row[1]) == column_name:
            return True
    return False


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    r = 6371008.8
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _select_nearest_place_fallback(candidates: List[Tuple[int, float, str]]) -> Optional[Tuple[int, float, str]]:
    within_threshold = [candidate for candidate in candidates if candidate[1] <= NEAREST_PLACE_FALLBACK_MAX_DISTANCE_M]
    if not within_threshold:
        return None
    primary = [candidate for candidate in within_threshold if candidate[0] <= PRIMARY_PLACE_MAX_RANK]
    if primary:
        return sorted(primary, key=lambda row: (row[1], row[0], row[2]))[0]
    return sorted(within_threshold, key=lambda row: (row[0], row[1], row[2]))[0]


def _same_admin_name(lhs: str, rhs: str) -> bool:
    return lhs.strip().casefold() == rhs.strip().casefold()


def _format_admin_city_name(
    boundaries: List[Tuple[int, Optional[str], float]],
) -> Tuple[Optional[str], Optional[int]]:
    normalized: List[Tuple[int, str, float]] = []
    for admin_level, name, bbox_area in boundaries:
        if name is None:
            continue
        trimmed = name.strip()
        if not trimmed:
            continue
        normalized.append((admin_level, trimmed, bbox_area))
    if not normalized:
        return None, None
    normalized.sort(key=lambda record: (CITY_BOUNDARY_PRIORITY.get(record[0], 99), record[2], record[1]))
    best_level, best_name, _ = normalized[0]
    if best_level == 9:
        parents = [
            candidate
            for candidate in normalized
            if candidate[0] == 8 and not _same_admin_name(candidate[1], best_name)
        ]
        if parents:
            parents.sort(key=lambda record: (record[2], record[1]))
            return f"{best_name} ({parents[0][1]})", best_level
    return best_name, best_level


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


def _query_way_rows(
    conn: sqlite3.Connection,
    lat: float,
    lon: float,
    radius_m: float,
    tile_x_min: int,
    tile_x_max: int,
    tile_y_min: int,
    tile_y_max: int,
    limit_rows: int,
    has_street_name: bool,
    has_ref: bool,
    has_service: bool,
    has_tunnel: bool,
) -> Tuple[List[dict], int]:
    deg_lat = radius_m / 111132.0
    cos_lat = max(0.173648, abs(math.cos(math.radians(lat))))
    deg_lon = radius_m / (111320.0 * cos_lat)
    min_lat = lat - deg_lat
    max_lat = lat + deg_lat
    min_lon = lon - deg_lon
    max_lon = lon + deg_lon

    tile_row_count = int(
        conn.execute(
            """
            SELECT COUNT(DISTINCT way_id)
            FROM way_tile
            WHERE tile_x BETWEEN ? AND ?
              AND tile_y BETWEEN ? AND ?
            """,
            (tile_x_min, tile_x_max, tile_y_min, tile_y_max),
        ).fetchone()[0]
    )

    street_name_select = "w.street_name" if has_street_name else "NULL"
    ref_select = "w.ref" if has_ref else "NULL"
    service_select = "w.service" if has_service else "NULL"
    tunnel_select = "w.tunnel" if has_tunnel else "NULL"
    sql = f"""
    WITH tile_rows AS (
      SELECT DISTINCT way_id
      FROM way_tile
      WHERE tile_x BETWEEN ? AND ?
        AND tile_y BETWEEN ? AND ?
    )
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
      w.min_lon,
      w.min_lat,
      w.max_lon,
      w.max_lat,
      g.points_json
    FROM tile_rows t
    JOIN ways_rtree r ON r.way_id = t.way_id
    JOIN ways w ON w.way_id = t.way_id
    LEFT JOIN way_geom g ON g.way_id = t.way_id
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
        tile_x_min,
        tile_x_max,
        tile_y_min,
        tile_y_max,
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
    rows: List[dict] = []
    cur = conn.execute(sql, params)
    for r in cur.fetchall():
        points: List[List[float]] = []
        if isinstance(r[14], str) and r[14]:
            try:
                parsed = json.loads(r[14])
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
                "min_lon": float(r[10]),
                "min_lat": float(r[11]),
                "max_lon": float(r[12]),
                "max_lat": float(r[13]),
                "points": points,
            }
        )
    return rows, tile_row_count


def _query_area_rows(
    conn: sqlite3.Connection,
    lat: float,
    lon: float,
    limit_rows: int = 512,
    has_residential: bool = False,
    has_points_json: bool = False,
) -> List[dict]:
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
    WHERE r.min_lon <= ? AND r.max_lon >= ?
      AND r.min_lat <= ? AND r.max_lat >= ?
    LIMIT ?
    """.format(residential_select=residential_select, points_select=points_select)
    cur = conn.execute(sql, (lon, lon, lat, lat, limit_rows))
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
    n = len(ring)
    for i in range(n - 1):
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


def _boundary_contains_point(conn: sqlite3.Connection, boundary_row_id: int, lon: float, lat: float) -> bool:
    cur = conn.execute(
        """
        SELECT outer_index, is_hole, points_json
        FROM city_ring
        WHERE boundary_row_id=?
        ORDER BY outer_index, is_hole, ring_index
        """,
        (boundary_row_id,),
    )

    grouped: Dict[int, Dict[str, List[List[List[float]]]]] = {}
    for outer_index, is_hole, points_json in cur.fetchall():
        try:
            points = json.loads(points_json)
        except Exception:
            continue
        if not isinstance(points, list):
            continue
        g = grouped.setdefault(int(outer_index), {"outer": [], "holes": []})
        if int(is_hole) == 0:
            g["outer"] = points
        else:
            g["holes"].append(points)

    for group in grouped.values():
        outer = group.get("outer")
        if not outer:
            continue
        if not _point_in_ring(lon, lat, outer):
            continue
        in_hole = any(_point_in_ring(lon, lat, hole) for hole in group.get("holes", []))
        if not in_hole:
            return True
    return False


def _resolve_city_context(
    conn: sqlite3.Connection,
    lat: float,
    lon: float,
    query_tx: int,
    query_ty: int,
    tile_radius: int,
) -> Dict[str, object]:
    has_city_tables = all(
        _table_exists(conn, t)
        for t in ("city_boundary", "city_boundary_rtree", "city_ring", "city_tile", "city_place", "city_place_rtree")
    )

    if not has_city_tables:
        return {
            "inside_city": False,
            "city_name": None,
            "city_admin_level": None,
            "city_source": None,
            "city_candidate_boundaries": 0,
            "city_containing_boundaries": 0,
            "city_place_candidates": 0,
            "city_mode": "unavailable",
        }

    tile_x_min = query_tx - tile_radius
    tile_x_max = query_tx + tile_radius
    tile_y_min = query_ty - tile_radius
    tile_y_max = query_ty + tile_radius

    candidates = conn.execute(
        """
        WITH t AS (
          SELECT DISTINCT boundary_row_id
          FROM city_tile
          WHERE tile_x BETWEEN ? AND ?
            AND tile_y BETWEEN ? AND ?
        )
        SELECT
          b.row_id,
          b.admin_level,
          b.name,
          b.min_lon,
          b.min_lat,
          b.max_lon,
          b.max_lat
        FROM t
        JOIN city_boundary_rtree r ON r.row_id = t.boundary_row_id
        JOIN city_boundary b ON b.row_id = t.boundary_row_id
        WHERE r.min_lon <= ? AND r.max_lon >= ?
          AND r.min_lat <= ? AND r.max_lat >= ?
          AND b.admin_level IN (6, 8, 9)
        LIMIT 2048
        """,
        (
            tile_x_min,
            tile_x_max,
            tile_y_min,
            tile_y_max,
            lon,
            lon,
            lat,
            lat,
        ),
    ).fetchall()

    containing: List[Tuple[int, Optional[str], float]] = []
    for row in candidates:
        row_id = int(row[0])
        admin_level = int(row[1])
        name = row[2]
        bbox_area = max(float(row[5]) - float(row[3]), 0.0) * max(float(row[6]) - float(row[4]), 0.0)
        if _boundary_contains_point(conn, row_id, lon, lat):
            containing.append((admin_level, name, bbox_area))

    if containing:
        city_name, best_level = _format_admin_city_name(containing)
        return {
            "inside_city": True,
            "city_name": city_name,
            "city_admin_level": best_level,
            "city_source": "admin_polygon",
            "city_candidate_boundaries": len(candidates),
            "city_containing_boundaries": len(containing),
            "city_place_candidates": 0,
            "city_mode": "admin_polygons_plus_places",
        }

    # Fallback locality label for outside-city positions.
    place_candidates = conn.execute(
        """
        SELECT p.place, p.name, p.lon, p.lat
        FROM city_place_rtree r
        JOIN city_place p ON p.row_id = r.row_id
        WHERE r.min_lon <= ? AND r.max_lon >= ?
          AND r.min_lat <= ? AND r.max_lat >= ?
        ORDER BY ((p.lon - ?) * (p.lon - ?) + (p.lat - ?) * (p.lat - ?)) ASC
        LIMIT 16
        """,
        (lon + 0.3, lon - 0.3, lat + 0.3, lat - 0.3, lon, lon, lat, lat),
    ).fetchall()

    ranked_candidates = []
    for place, name, place_lon, place_lat in place_candidates:
        rank = PLACE_RANK.get(place)
        if rank is None or not name:
            continue
        ranked_candidates.append((rank, haversine_m(lat, lon, float(place_lat), float(place_lon)), str(name)))

    best = _select_nearest_place_fallback(ranked_candidates)
    if best:
        return {
            "inside_city": False,
            "city_name": best[2],
            "city_admin_level": None,
            "city_source": "place_fallback",
            "city_candidate_boundaries": len(candidates),
            "city_containing_boundaries": 0,
            "city_place_candidates": len(ranked_candidates),
            "city_mode": "admin_polygons_plus_places",
        }

    return {
        "inside_city": False,
        "city_name": None,
        "city_admin_level": None,
        "city_source": None,
        "city_candidate_boundaries": len(candidates),
        "city_containing_boundaries": 0,
        "city_place_candidates": 0,
        "city_mode": "admin_polygons_plus_places",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Query speed candidates from v4 SQLite/SpatiaLite tile DB")
    parser.add_argument("--db", required=True, help="Path to speeds_v4.sqlite")
    parser.add_argument("--lat", required=True, type=float, help="Latitude in degrees")
    parser.add_argument("--lon", required=True, type=float, help="Longitude in degrees")
    parser.add_argument("--heading", type=float, default=None, help="Heading in degrees (0-360)")
    parser.add_argument("--tile-radius", type=int, default=1, help="Tile window radius")
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
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    started = time.perf_counter()

    if not (-90.0 <= args.lat <= 90.0 and -180.0 <= args.lon <= 180.0):
        print("Invalid coordinate range", file=sys.stderr)
        return 1
    if args.heading is not None and not (0.0 <= args.heading <= 360.0):
        print("Heading must be in range [0, 360]", file=sys.stderr)
        return 1
    if args.tile_radius < 0:
        print("tile-radius must be >= 0", file=sys.stderr)
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
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name IN ('ways','ways_rtree','way_tile','areas','areas_rtree') LIMIT 1"
        ).fetchone()
    )
    if not schema_ok:
        print("Invalid v4 DB schema", file=sys.stderr)
        return 1

    has_street_name = _column_exists(conn, "ways", "street_name")
    has_ref = _column_exists(conn, "ways", "ref")
    has_service = _column_exists(conn, "ways", "service")
    has_tunnel = _column_exists(conn, "ways", "tunnel")
    has_area_residential = _column_exists(conn, "areas", "residential")
    has_area_points_json = _column_exists(conn, "areas", "points_json")

    tile_size_row = conn.execute("SELECT value FROM metadata WHERE key='tile_size_m' LIMIT 1").fetchone()
    if not tile_size_row:
        print("v4 metadata missing tile_size_m", file=sys.stderr)
        return 1
    tile_size_m = int(tile_size_row[0])
    if tile_size_m <= 0:
        print("v4 metadata tile_size_m must be > 0", file=sys.stderr)
        return 1
    index_load_ms = (time.perf_counter() - t0) * 1000.0

    tx, ty = _tile_for_lon_lat(args.lon, args.lat, tile_size_m)
    tile_x_min = tx - args.tile_radius
    tile_x_max = tx + args.tile_radius
    tile_y_min = ty - args.tile_radius
    tile_y_max = ty + args.tile_radius

    t1 = time.perf_counter()
    ways, tile_prefilter_rows = _query_way_rows(
        conn=conn,
        lat=args.lat,
        lon=args.lon,
        radius_m=args.search_radius_m,
        tile_x_min=tile_x_min,
        tile_x_max=tile_x_max,
        tile_y_min=tile_y_min,
        tile_y_max=tile_y_max,
        limit_rows=args.max_candidates,
        has_street_name=has_street_name,
        has_ref=has_ref,
        has_service=has_service,
        has_tunnel=has_tunnel,
    )
    area_candidates = _query_area_rows(
        conn=conn,
        lat=args.lat,
        lon=args.lon,
        has_residential=has_area_residential,
        has_points_json=has_area_points_json,
    )
    candidate_load_ms = (time.perf_counter() - t1) * 1000.0

    t_city = time.perf_counter()
    city_context = _resolve_city_context(conn, args.lat, args.lon, tx, ty, args.tile_radius)
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
            "tile_radius": args.tile_radius,
            "query_tile": _tile_id(tx, ty),
            "db": str(db_path),
        },
        "summary": {
            "candidate_way_ids": len({r["way_id"] for r in ways}),
            "matched_way_rows": len(ways),
            "tile_prefilter_way_rows": tile_prefilter_rows,
            "candidate_tile_rows": (2 * args.tile_radius + 1) ** 2,
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
            "v4 query combines tile prefilter (way_tile) with SQLite RTree.",
            "Built-up inference uses residential=* polygon containment from areas table.",
            "Top candidates include street_name/ref when present in the runtime artifact.",
        ],
    }

    conn.close()
    print(f"query_time_ms={result['timing_ms']['total']}", file=sys.stderr)
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
