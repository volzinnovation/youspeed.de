#!/usr/bin/env python3
"""Query speed-limit candidates from v2 tile assets."""

from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

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
EARTH_RADIUS_M = 6378137.0
MAX_MERCATOR_LAT = 85.05112878


def _id_sort_key(raw_id: str) -> Tuple[int, int | str]:
    if raw_id.isdigit():
        return (0, int(raw_id))
    return (1, raw_id)


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must be a JSON object")
    return payload


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


def _parse_tile_id(tile_id: str) -> Tuple[int, int]:
    x_part, y_part = tile_id.split("/", 1)
    return int(x_part), int(y_part)


def _neighboring_tile_ids(tx: int, ty: int, radius: int) -> List[str]:
    out = []
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            out.append(_tile_id(tx + dx, ty + dy))
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


def inside_built_up_guess(lat: float, lon: float, area_candidates: Iterable[dict]) -> bool:
    for area in area_candidates:
        if not point_in_bbox(lat, lon, area):
            continue
        place = area.get("place")
        if place in PLACE_VALUES:
            return True
        if area.get("boundary") == "administrative" and area.get("admin_level") in {"8", "9"}:
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


def _read_manifest_chunks(manifest: dict, tilepack_path: Path) -> Dict[str, object]:
    chunks = manifest.get("chunks", [])
    if not isinstance(chunks, list):
        return {}
    raw = tilepack_path.read_bytes()
    out: Dict[str, object] = {}
    for chunk in chunks:
        name = chunk.get("name")
        offset = chunk.get("offset")
        length = chunk.get("length")
        if not isinstance(name, str) or not isinstance(offset, int) or not isinstance(length, int):
            continue
        blob = raw[offset : offset + length]
        try:
            out[name] = json.loads(blob.decode("utf-8"))
        except Exception:
            continue
    return out


def _tile_local_subcells(
    lat: float, lon: float, tx: int, ty: int, tile_size_m: int, grid_size: int, radius: int
) -> List[str]:
    x, y = _lon_lat_to_mercator_m(lon, lat)
    local_x = x - tx * tile_size_m
    local_y = y - ty * tile_size_m
    local_x = min(max(local_x, 0.0), float(tile_size_m))
    local_y = min(max(local_y, 0.0), float(tile_size_m))

    def to_idx(v: float) -> int:
        idx = int(math.floor((v / tile_size_m) * grid_size))
        return min(max(idx, 0), grid_size - 1)

    ix = to_idx(local_x)
    iy = to_idx(local_y)
    out = []
    for dx in range(-radius, radius + 1):
        for dy in range(-radius, radius + 1):
            sx = min(max(ix + dx, 0), grid_size - 1)
            sy = min(max(iy + dy, 0), grid_size - 1)
            out.append(f"{sx}:{sy}")
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Query speed candidates from v2 tile assets")
    parser.add_argument("--dist-dir", required=True, help="Path to v2 region dir (contains catalog.v2.json)")
    parser.add_argument("--lat", required=True, type=float, help="Latitude in degrees")
    parser.add_argument("--lon", required=True, type=float, help="Longitude in degrees")
    parser.add_argument("--heading", type=float, default=None, help="Heading in degrees (0-360)")
    parser.add_argument("--tile-radius", type=int, default=1, help="Tile window radius (default: 1 => 3x3)")
    parser.add_argument("--subcell-radius", type=int, default=1, help="Local subcell radius within each tile")
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


def _default_city_db_path(dist_dir: Path) -> Path:
    # mapdata/dist-v2/<region> -> mapdata/dist-v4/<region>/speeds_v4.sqlite
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
    if args.tile_radius < 0:
        print("tile-radius must be >= 0", file=sys.stderr)
        return 1
    if args.subcell_radius < 0:
        print("subcell-radius must be >= 0", file=sys.stderr)
        return 1
    if args.top_k <= 0:
        print("top-k must be > 0", file=sys.stderr)
        return 1
    if args.polyline_top_n <= 0:
        print("polyline-top-n must be > 0", file=sys.stderr)
        return 1

    dist_dir = Path(args.dist_dir)
    catalog_path = dist_dir / "catalog.v2.json"
    if not catalog_path.exists():
        print(f"Missing artifact: {catalog_path}", file=sys.stderr)
        return 1

    t0 = time.perf_counter()
    catalog = _load_json(catalog_path)
    tile_size_m = int(catalog.get("tile_grid", {}).get("tile_size_m", 0))
    if tile_size_m <= 0:
        print("Invalid tile grid in catalog", file=sys.stderr)
        return 1
    catalog_tiles = catalog.get("tiles", [])
    tile_entries: Dict[str, dict] = {}
    if isinstance(catalog_tiles, list):
        for row in catalog_tiles:
            if isinstance(row, dict) and isinstance(row.get("tile_id"), str):
                tile_entries[row["tile_id"]] = row
    index_load_ms = (time.perf_counter() - t0) * 1000.0

    qtx, qty = _tile_for_lon_lat(args.lon, args.lat, tile_size_m)
    window_tile_ids = _neighboring_tile_ids(qtx, qty, args.tile_radius)

    t1 = time.perf_counter()
    candidates: List[dict] = []
    area_candidates: List[dict] = []
    loaded_tiles = 0

    for tile_id in window_tile_ids:
        entry = tile_entries.get(tile_id)
        if entry is None:
            continue

        tile_dir = dist_dir / "tiles" / tile_id
        manifest_path = tile_dir / "tile_manifest.v2.json"
        if not manifest_path.exists():
            continue
        manifest = _load_json(manifest_path)
        tile_sha = manifest.get("tile_pack_sha256")
        if not isinstance(tile_sha, str):
            continue
        tilepack_path = tile_dir / f"{tile_sha}.tilepack"
        if not tilepack_path.exists():
            continue

        chunk_payloads = _read_manifest_chunks(manifest, tilepack_path)
        segment_index = chunk_payloads.get("segment_index")
        segment_geom = chunk_payloads.get("segment_geom")
        speed_rules = chunk_payloads.get("speed_rules")
        area_index = chunk_payloads.get("area_index")

        if not isinstance(segment_index, dict) or not isinstance(segment_geom, dict) or not isinstance(speed_rules, dict):
            continue
        grid_size = int(segment_index.get("grid_size", 0))
        cells = segment_index.get("cells", {})
        if grid_size <= 0 or not isinstance(cells, dict):
            continue

        tx, ty = _parse_tile_id(tile_id)
        subcells = _tile_local_subcells(args.lat, args.lon, tx, ty, tile_size_m, grid_size, args.subcell_radius)
        seg_ids = set()
        for cell in subcells:
            ids = cells.get(cell, [])
            if isinstance(ids, list):
                for sid in ids:
                    if isinstance(sid, str):
                        seg_ids.add(sid)

        for seg_id in sorted(seg_ids, key=_id_sort_key):
            geom = segment_geom.get(seg_id)
            if not isinstance(geom, dict):
                continue
            rules = speed_rules.get(seg_id, {})
            if not isinstance(rules, dict):
                rules = {}
            row = {
                "tile_id": tile_id,
                "segment_id": seg_id,
                "way_id": geom.get("way_id", seg_id),
                "highway": rules.get("highway", geom.get("highway")),
                "street_name": rules.get("street_name"),
                "maxspeed": rules.get("maxspeed"),
                "maxspeed_type": rules.get("maxspeed_type"),
                "source_maxspeed": rules.get("source_maxspeed"),
                "zone_maxspeed": rules.get("zone_maxspeed"),
                "traffic_sign": rules.get("traffic_sign"),
                "min_lon": geom.get("min_lon"),
                "min_lat": geom.get("min_lat"),
                "max_lon": geom.get("max_lon"),
                "max_lat": geom.get("max_lat"),
                "approx_heading_deg": geom.get("approx_heading_deg"),
                "points": geom.get("points", []),
            }
            if not all(isinstance(row[k], (int, float)) for k in ("min_lon", "min_lat", "max_lon", "max_lat")):
                continue
            candidates.append(row)

        if isinstance(area_index, dict):
            areas = area_index.get("areas", [])
            if isinstance(areas, list):
                for area in areas:
                    if isinstance(area, dict):
                        area_candidates.append(area)

        loaded_tiles += 1

    candidate_load_ms = (time.perf_counter() - t1) * 1000.0

    t2 = time.perf_counter()
    scored: List[dict] = []
    filtered_non_drivable = 0
    for row in candidates:
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
                "tile_id": row["tile_id"],
                "segment_id": row["segment_id"],
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
        if args.distance_mode == "hybrid":
            refine_rows = sorted_scored[: args.polyline_top_n]
        else:
            refine_rows = sorted_scored
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
            "tile_radius": args.tile_radius,
            "subcell_radius": args.subcell_radius,
            "query_tile": _tile_id(qtx, qty),
        },
        "summary": {
            "candidate_way_ids": len({r["way_id"] for r in candidates}),
            "matched_way_rows": len(candidates),
            "filtered_non_drivable_rows": filtered_non_drivable,
            "scored_rows": len(scored),
            "candidate_tile_rows": len(window_tile_ids),
            "loaded_tiles": loaded_tiles,
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
            "v2 query reads nearby physical tile packs only.",
            "Built-up inference prefers exact admin polygon containment when city tables are available.",
            "Use camera-detected signs to override map/default limits in final fusion.",
        ],
    }

    print(f"query_time_ms={result['timing_ms']['total']}", file=sys.stderr)
    print(json.dumps(result, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
