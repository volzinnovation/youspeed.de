#!/usr/bin/env python3
"""Query speed-limit candidates from generated runtime artifacts.

Heuristic matcher:
- Uses `ways.idx` grid cells to obtain candidate way IDs.
- Streams `ways.meta` to fetch metadata for candidate IDs.
- Scores by point-to-bbox distance, plus optional heading penalty.
- Infers effective limit from best candidate, with fallback to DE defaults.
"""

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
CITY_BOUNDARY_PRIORITY = {9: 0, 8: 1, 6: 2}
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


def _id_sort_key(raw_id: str) -> Tuple[int, int | str]:
    if raw_id.isdigit():
        return (0, int(raw_id))
    return (1, raw_id)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Query map speed candidates from built artifacts")
    parser.add_argument("--dist-dir", required=True, help="Path to mapdata/dist/<region>")
    parser.add_argument("--lat", required=True, type=float, help="Latitude in degrees")
    parser.add_argument("--lon", required=True, type=float, help="Longitude in degrees")
    parser.add_argument("--heading", type=float, default=None, help="Heading in degrees (0-360)")
    parser.add_argument("--radius-cells", type=int, default=1, help="Search radius in grid cells")
    parser.add_argument("--top-k", type=int, default=5, help="Number of candidate ways to return")
    parser.add_argument(
        "--heading-weight",
        type=float,
        default=2.0,
        help="Meters per degree heading mismatch penalty",
    )
    parser.add_argument(
        "--vehicle-profile",
        choices=("car", "any"),
        default="car",
        help="Candidate filtering profile (default: car)",
    )
    parser.add_argument(
        "--unknown-highway-penalty",
        type=float,
        default=30.0,
        help="Extra score penalty for highway=null rows in car profile",
    )
    parser.add_argument(
        "--distance-mode",
        choices=("bbox", "polyline", "hybrid"),
        default="hybrid",
        help="Distance scoring mode: bbox only, full polyline, or hybrid refinement",
    )
    parser.add_argument(
        "--polyline-top-n",
        type=int,
        default=250,
        help="In hybrid mode, refine this many best bbox candidates using polyline distance",
    )
    parser.add_argument(
        "--city-db",
        help="Optional SQLite DB with city_boundary/city_ring tables (defaults to sibling dist-v4 DB)",
    )
    return parser.parse_args()


def cell_for(lat: float, lon: float, scale: int) -> str:
    x = math.floor((lon + 180.0) * scale)
    y = math.floor((lat + 90.0) * scale)
    return f"{x}:{y}"


def neighboring_cells(lat: float, lon: float, scale: int, radius: int) -> List[str]:
    x = math.floor((lon + 180.0) * scale)
    y = math.floor((lat + 90.0) * scale)
    out: List[str] = []
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            out.append(f"{x + dx}:{y + dy}")
    return out


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
    # Road can be matched in either direction.
    return min(raw, abs(180.0 - raw))


def parse_explicit_speed_kmh(row: dict) -> Optional[int]:
    for key in ("maxspeed", "zone_maxspeed"):
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


def _city_boundary_priority(admin_level: object) -> Optional[int]:
    try:
        return CITY_BOUNDARY_PRIORITY.get(int(admin_level))
    except (TypeError, ValueError):
        return None


def _same_admin_name(lhs: str, rhs: str) -> bool:
    return lhs.strip().casefold() == rhs.strip().casefold()


def _format_admin_city_name(boundaries: List[Tuple[int, float, str]]) -> Tuple[Optional[str], Optional[int]]:
    normalized = [(admin_level, bbox_area, name.strip()) for admin_level, bbox_area, name in boundaries if name.strip()]
    if not normalized:
        return None, None
    normalized.sort(key=lambda record: ((_city_boundary_priority(record[0]) or 99), record[1], record[2]))
    best_level, _, best_name = normalized[0]
    if best_level == 9:
        parents = [
            candidate
            for candidate in normalized
            if candidate[0] == 8 and not _same_admin_name(candidate[2], best_name)
        ]
        if parents:
            parents.sort(key=lambda record: (record[1], record[2]))
            return f"{best_name} ({parents[0][2]})", best_level
    return best_name, best_level


def inside_built_up_guess(lat: float, lon: float, area_candidates: Iterable[dict]) -> bool:
    for area in area_candidates:
        if not point_in_bbox(lat, lon, area):
            continue
        place = area.get("place")
        if place in PLACE_VALUES:
            return True
        if area.get("boundary") == "administrative" and _city_boundary_priority(area.get("admin_level")) is not None:
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
        admin_level = area.get("admin_level")
        admin_priority = _city_boundary_priority(admin_level)
        area_is_admin = area.get("boundary") == "administrative" and admin_priority is not None
        inside_bbox = point_in_bbox(lat, lon, area)
        area_size = _bbox_area(area)

        if area_is_admin and inside_bbox:
            containing_admin.append((int(admin_level), area_size, name))

        if place in PLACE_VALUES:
            center_lat = (float(area["min_lat"]) + float(area["max_lat"])) / 2.0
            center_lon = (float(area["min_lon"]) + float(area["max_lon"])) / 2.0
            d = haversine_m(lat, lon, center_lat, center_lon)
            rank = int(PLACE_RANK.get(place, 99))
            nearby_places.append((rank, d, name))
            if inside_bbox:
                containing_places.append((rank, d, name))

    if containing_admin:
        containing_admin.sort(key=lambda x: ((_city_boundary_priority(x[0]) or 99), x[1], x[2]))
        city_name, city_admin_level = _format_admin_city_name(containing_admin)
        return {
            "inside_city": True,
            "city_name": city_name,
            "city_admin_level": city_admin_level,
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


def load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        return json.load(f)


def load_candidate_ways_scan(ways_meta_path: Path, way_ids: set[str]) -> List[dict]:
    out: List[dict] = []
    if not way_ids:
        return out

    found = 0
    with ways_meta_path.open("r", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            if row.get("way_id") in way_ids:
                out.append(row)
                found += 1
                if found == len(way_ids):
                    break
    return out


def load_candidate_ways_lookup(ways_meta_path: Path, way_ids: set[str], lookup_index: Dict[str, int]) -> List[dict]:
    out: List[dict] = []
    if not way_ids:
        return out

    with ways_meta_path.open("r", encoding="utf-8") as f:
        for way_id in sorted(way_ids, key=_id_sort_key):
            offset = lookup_index.get(way_id)
            if offset is None:
                continue
            f.seek(offset)
            line = f.readline()
            if not line:
                continue
            out.append(json.loads(line))
    return out


def load_candidate_geoms_lookup(
    ways_geom_path: Path, way_ids: set[str], lookup_index: Dict[str, int]
) -> Dict[str, List[List[float]]]:
    out: Dict[str, List[List[float]]] = {}
    if not way_ids:
        return out

    with ways_geom_path.open("r", encoding="utf-8") as f:
        for way_id in sorted(way_ids, key=_id_sort_key):
            offset = lookup_index.get(way_id)
            if offset is None:
                continue
            f.seek(offset)
            line = f.readline()
            if not line:
                continue
            row = json.loads(line)
            pts = row.get("points")
            if isinstance(pts, list):
                out[way_id] = pts
    return out


def _default_city_db_path(dist_dir: Path) -> Path:
    # mapdata/dist/<region> -> mapdata/dist-v4/<region>/speeds_v4.sqlite
    return dist_dir.parent.parent / "dist-v4" / dist_dir.name / "speeds_v4.sqlite"


def main() -> int:
    args = parse_args()
    started = time.perf_counter()

    if not (-90.0 <= args.lat <= 90.0 and -180.0 <= args.lon <= 180.0):
        print("Invalid coordinate range", file=sys.stderr)
        return 1
    if args.heading is not None and not (0.0 <= args.heading <= 360.0):
        print("Heading must be in range [0, 360]", file=sys.stderr)
        return 1
    if args.radius_cells < 0:
        print("radius-cells must be >= 0", file=sys.stderr)
        return 1
    if args.top_k <= 0:
        print("top-k must be > 0", file=sys.stderr)
        return 1
    if args.polyline_top_n <= 0:
        print("polyline-top-n must be > 0", file=sys.stderr)
        return 1

    dist_dir = Path(args.dist_dir)
    ways_idx_path = dist_dir / "ways.idx"
    ways_meta_path = dist_dir / "ways.meta"
    areas_idx_path = dist_dir / "areas.idx"
    ways_lookup_path = dist_dir / "ways.lookup"
    ways_geom_path = dist_dir / "ways.geom"
    ways_geom_lookup_path = dist_dir / "ways.geom.lookup"

    for path in (ways_idx_path, ways_meta_path, areas_idx_path):
        if not path.exists():
            print(f"Missing artifact: {path}", file=sys.stderr)
            return 1

    t0 = time.perf_counter()
    ways_idx = load_json(ways_idx_path)
    areas_idx = load_json(areas_idx_path)
    index_load_ms = (time.perf_counter() - t0) * 1000.0

    scale = int(ways_idx["grid_scale"])
    if int(areas_idx["grid_scale"]) != scale:
        print("ways.idx and areas.idx grid_scale mismatch", file=sys.stderr)
        return 1

    query_cells = neighboring_cells(args.lat, args.lon, scale, args.radius_cells)

    way_ids: set[str] = set()
    for cell in query_cells:
        for way_id in ways_idx.get("cells", {}).get(cell, []):
            way_ids.add(way_id)

    area_ids: set[str] = set()
    for cell in query_cells:
        for area_id in areas_idx.get("cells", {}).get(cell, []):
            area_ids.add(area_id)

    areas_by_id = {a["area_id"]: a for a in areas_idx.get("areas", [])}
    area_candidates = [areas_by_id[aid] for aid in sorted(area_ids) if aid in areas_by_id]

    lookup_index = None
    load_mode = "scan"
    if ways_lookup_path.exists():
        lookup_payload = load_json(ways_lookup_path)
        if isinstance(lookup_payload.get("index"), dict):
            lookup_index = {str(k): int(v) for k, v in lookup_payload["index"].items()}
            load_mode = "lookup"

    t1 = time.perf_counter()
    if lookup_index is not None:
        ways = load_candidate_ways_lookup(ways_meta_path, way_ids, lookup_index)
    else:
        ways = load_candidate_ways_scan(ways_meta_path, way_ids)
    candidate_load_ms = (time.perf_counter() - t1) * 1000.0

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
                "distance_m": round(distance_m, 2),
                "heading_diff_deg": None if heading_diff is None else round(heading_diff, 2),
                "score": round(score, 2),
                "maxspeed": row.get("maxspeed"),
                "maxspeed_type": row.get("maxspeed_type"),
                "source_maxspeed": row.get("source_maxspeed"),
                "zone_maxspeed": row.get("zone_maxspeed"),
                "parsed_speed_kmh": parsed_speed,
                "center_lat": row.get("center_lat"),
                "center_lon": row.get("center_lon"),
                "_heading_penalty": heading_penalty,
                "_unknown_highway_penalty": unknown_highway_penalty,
            }
        )

    polyline_refine_mode = "disabled"
    refined_polyline_rows = 0
    polyline_missing_rows = 0
    t_poly = time.perf_counter()
    if args.distance_mode != "bbox":
        if ways_geom_path.exists() and ways_geom_lookup_path.exists():
            geom_lookup_payload = load_json(ways_geom_lookup_path)
            geom_lookup_index: Dict[str, int] = {}
            if isinstance(geom_lookup_payload.get("index"), dict):
                geom_lookup_index = {str(k): int(v) for k, v in geom_lookup_payload["index"].items()}
            if geom_lookup_index:
                sorted_scored = sorted(scored, key=lambda r: (r["score"], r["distance_m"], r["way_id"]))
                if args.distance_mode == "hybrid":
                    refine_ids = {r["way_id"] for r in sorted_scored[: args.polyline_top_n]}
                else:
                    refine_ids = {r["way_id"] for r in sorted_scored}

                geoms = load_candidate_geoms_lookup(ways_geom_path, refine_ids, geom_lookup_index)
                polyline_refine_mode = "active"
                for row in scored:
                    way_id = row["way_id"]
                    if way_id not in refine_ids:
                        continue
                    pts = geoms.get(way_id)
                    if not pts:
                        polyline_missing_rows += 1
                        continue
                    dpoly = polyline_distance_m(args.lat, args.lon, pts)
                    score = dpoly + row["_heading_penalty"] + row["_unknown_highway_penalty"]
                    row["distance_m"] = round(dpoly, 2)
                    row["score"] = round(score, 2)
                    refined_polyline_rows += 1
            else:
                polyline_refine_mode = "missing_lookup_index"
        else:
            polyline_refine_mode = "missing_geom_artifacts"
    polyline_refine_ms = (time.perf_counter() - t_poly) * 1000.0

    scored.sort(key=lambda r: (r["score"], r["distance_m"], r["way_id"]))
    for row in scored:
        row.pop("_heading_penalty", None)
        row.pop("_unknown_highway_penalty", None)
    top = scored[: args.top_k]
    scoring_ms = (time.perf_counter() - t2) * 1000.0

    city_db_path = Path(args.city_db) if args.city_db else _default_city_db_path(dist_dir)

    t_city = time.perf_counter()
    city_context = None
    if city_db_path.exists():
        try:
            city_conn = sqlite3.connect(str(city_db_path))
            city_context = resolve_city_context(city_conn, args.lat, args.lon)
            city_conn.close()
        except sqlite3.Error:
            city_context = None
    if not isinstance(city_context, dict) or city_context.get("city_mode") == "unavailable":
        city_context = _resolve_city_context_from_areas(args.lat, args.lon, area_candidates)
        city_context["city_mode"] = "bbox_fallback"
    city_resolve_ms = (time.perf_counter() - t_city) * 1000.0

    built_up = bool(city_context.get("inside_city", False))
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
            "radius_cells": args.radius_cells,
            "query_cell": cell_for(args.lat, args.lon, scale),
        },
        "summary": {
            "candidate_way_ids": len(way_ids),
            "matched_way_rows": len(ways),
            "filtered_non_drivable_rows": filtered_non_drivable,
            "scored_rows": len(scored),
            "candidate_load_mode": load_mode,
            "distance_mode_requested": args.distance_mode,
            "distance_mode_effective": "polyline" if polyline_refine_mode == "active" else "bbox",
            "polyline_refine_mode": polyline_refine_mode,
            "polyline_refined_rows": refined_polyline_rows,
            "polyline_missing_rows": polyline_missing_rows,
            "candidate_areas": len(area_candidates),
            "inside_built_up_guess": built_up,
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
            "Distance mode can use bbox, polyline, or hybrid refinement depending on artifact availability.",
            "Built-up inference prefers exact admin polygon containment when city tables are available.",
            "Use camera-detected signs to override map/default limits in final fusion.",
        ],
    }

    print(f"query_time_ms={result['timing_ms']['total']}", file=sys.stderr)
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
