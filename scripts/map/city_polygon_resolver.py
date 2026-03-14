#!/usr/bin/env python3
"""Shared city polygon containment resolver for query benchmarks."""

from __future__ import annotations

import json
import math
import sqlite3
from typing import Dict, List, Optional, Tuple

CITY_BOUNDARY_PRIORITY = {9: 0, 8: 1, 6: 2}
PLACE_RANK = {"city": 0, "town": 1, "village": 2, "hamlet": 3}
PRIMARY_PLACE_MAX_RANK = 1
NEAREST_PLACE_FALLBACK_MAX_DISTANCE_M = 5000.0


def table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def _point_on_segment(px: float, py: float, x1: float, y1: float, x2: float, y2: float) -> bool:
    eps = 1e-12
    cross = (px - x1) * (y2 - y1) - (py - y1) * (x2 - x1)
    if abs(cross) > eps:
        return False
    dot = (px - x1) * (x2 - x1) + (py - y1) * (y2 - y1)
    if dot < -eps:
        return False
    sq_len = (x2 - x1) * (x2 - x1) + (y2 - y1) * (y2 - y1)
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


def boundary_contains_point(conn: sqlite3.Connection, boundary_row_id: int, lon: float, lat: float) -> bool:
    cur = conn.execute(
        """
        SELECT outer_index, is_hole, points_json
        FROM city_ring
        WHERE boundary_row_id=?
        ORDER BY outer_index, is_hole, ring_index
        """,
        (boundary_row_id,),
    )
    grouped: Dict[int, Dict[str, object]] = {}
    for outer_index, is_hole, points_json in cur.fetchall():
        try:
            points = json.loads(points_json)
        except Exception:
            continue
        if not isinstance(points, list):
            continue
        outer_key = int(outer_index)
        group = grouped.setdefault(outer_key, {"outer": None, "holes": []})
        if int(is_hole) == 0:
            group["outer"] = points
        else:
            cast_holes = group["holes"]
            if isinstance(cast_holes, list):
                cast_holes.append(points)

    for group in grouped.values():
        outer = group.get("outer")
        if not isinstance(outer, list):
            continue
        if not _point_in_ring(lon, lat, outer):
            continue
        holes = group.get("holes")
        in_hole = False
        if isinstance(holes, list):
            in_hole = any(isinstance(hole, list) and _point_in_ring(lon, lat, hole) for hole in holes)
        if not in_hole:
            return True
    return False


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_m = 6371008.8
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    return 2.0 * radius_m * math.asin(math.sqrt(a))


def _primary_place_candidates(
    candidates: List[Tuple[int, float, str]],
) -> List[Tuple[int, float, str]]:
    return [candidate for candidate in candidates if candidate[0] <= PRIMARY_PLACE_MAX_RANK]


def _select_nearest_place_fallback(
    candidates: List[Tuple[int, float, str]],
) -> Optional[Tuple[int, float, str]]:
    within_threshold = [candidate for candidate in candidates if candidate[1] <= NEAREST_PLACE_FALLBACK_MAX_DISTANCE_M]
    if not within_threshold:
        return None
    primary = _primary_place_candidates(within_threshold)
    if primary:
        return sorted(primary, key=lambda record: (record[1], record[0], record[2]))[0]
    return sorted(within_threshold, key=lambda record: (record[0], record[1], record[2]))[0]


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


def resolve_city_context(conn: sqlite3.Connection, lat: float, lon: float, limit_rows: int = 2048) -> Dict[str, object]:
    has_boundary_tables = all(
        table_exists(conn, table_name)
        for table_name in ("city_boundary", "city_boundary_rtree", "city_ring")
    )
    has_place_tables = all(
        table_exists(conn, table_name)
        for table_name in ("city_place", "city_place_rtree")
    )

    if not has_boundary_tables:
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

    candidates = conn.execute(
        """
        SELECT
          b.row_id,
          b.admin_level,
          b.name,
          b.min_lon,
          b.min_lat,
          b.max_lon,
          b.max_lat
        FROM city_boundary_rtree r
        JOIN city_boundary b ON b.row_id = r.row_id
        WHERE r.min_lon <= ? AND r.max_lon >= ?
          AND r.min_lat <= ? AND r.max_lat >= ?
          AND b.admin_level IN (6, 8, 9)
        LIMIT ?
        """,
        (lon, lon, lat, lat, limit_rows),
    ).fetchall()

    containing: List[Tuple[int, Optional[str], float]] = []
    for row in candidates:
        row_id = int(row[0])
        admin_level = int(row[1])
        name = row[2]
        bbox_area = max(float(row[5]) - float(row[3]), 0.0) * max(float(row[6]) - float(row[4]), 0.0)
        if boundary_contains_point(conn, row_id, lon, lat):
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
            "city_mode": "admin_polygons_plus_places" if has_place_tables else "admin_polygons",
        }

    if has_place_tables:
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
            ranked_candidates.append((rank, _haversine_m(lat, lon, float(place_lat), float(place_lon)), str(name)))
        best_place = _select_nearest_place_fallback(ranked_candidates)
        if best_place:
            return {
                "inside_city": False,
                "city_name": best_place[2],
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
        "city_mode": "admin_polygons_plus_places" if has_place_tables else "admin_polygons",
    }
