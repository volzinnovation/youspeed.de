#!/usr/bin/env python3
"""Analyze daily OSM diffs and simulate patch impact for v1-v4 artifacts.

Outputs:
- CSV with per-day metrics (added/removed/tag changes, invalidated v1/v2 tiles,
  simulated v3/v4 SQL row counts and patch timing)
- JSON summary

The script copies v3/v4 DB files into a run-specific work directory and executes
simulated INSERT/DELETE patch transactions with rollback for each daily diff.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import math
import shutil
import sqlite3
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

EARTH_RADIUS_M = 6378137.0
MAX_MERCATOR_LAT = 85.05112878
MAXSPEED_KEYS = {"maxspeed", "zone:maxspeed", "maxspeed:type", "source:maxspeed", "max:speed"}
ADMIN_BOUNDARY_LEVELS = {"8", "9"}


@dataclass
class WayOp:
    action: str
    tags: Dict[str, str]
    node_refs: List[str]


@dataclass
class DiffParseResult:
    ways_added: int
    ways_removed: int
    ways_modified: int
    maxspeed_tag_events: int
    maxspeed_tag_changes: int
    boundary_admin_way_events: int
    boundary_admin_way_changes: int
    ops_by_way: Dict[str, WayOp]
    node_coords: Dict[str, Tuple[float, float]]  # node_id -> (lon, lat)


def _tag_name(raw: str) -> str:
    if "}" in raw:
        return raw.rsplit("}", 1)[-1]
    return raw


def _lon_lat_to_mercator_m(lon: float, lat: float) -> Tuple[float, float]:
    lat = min(max(lat, -MAX_MERCATOR_LAT), MAX_MERCATOR_LAT)
    x = EARTH_RADIUS_M * math.radians(lon)
    y = EARTH_RADIUS_M * math.log(math.tan(math.pi / 4.0 + math.radians(lat) / 2.0))
    return x, y


def _tile_range_for_bbox(
    min_lon: float, min_lat: float, max_lon: float, max_lat: float, tile_size_m: int
) -> Tuple[int, int, int, int]:
    x0, y0 = _lon_lat_to_mercator_m(min_lon, min_lat)
    x1, y1 = _lon_lat_to_mercator_m(max_lon, max_lat)
    tx0 = math.floor(min(x0, x1) / tile_size_m)
    tx1 = math.floor(max(x0, x1) / tile_size_m)
    ty0 = math.floor(min(y0, y1) / tile_size_m)
    ty1 = math.floor(max(y0, y1) / tile_size_m)
    return tx0, tx1, ty0, ty1


def _cell_range_for_bbox(
    min_lon: float, min_lat: float, max_lon: float, max_lat: float, grid_scale: int
) -> Tuple[int, int, int, int]:
    x0 = math.floor((min(min_lon, max_lon) + 180.0) * grid_scale)
    x1 = math.floor((max(min_lon, max_lon) + 180.0) * grid_scale)
    y0 = math.floor((min(min_lat, max_lat) + 90.0) * grid_scale)
    y1 = math.floor((max(min_lat, max_lat) + 90.0) * grid_scale)
    return x0, x1, y0, y1


def _parse_daily_diff(path: Path) -> DiffParseResult:
    ways_added = 0
    ways_removed = 0
    ways_modified = 0
    maxspeed_tag_events = 0
    maxspeed_tag_changes = 0
    boundary_admin_way_events = 0
    boundary_admin_way_changes = 0
    ops_by_way: Dict[str, WayOp] = {}
    node_coords: Dict[str, Tuple[float, float]] = {}

    open_fn = gzip.open if path.suffix == ".gz" else open
    current_action: Optional[str] = None

    with open_fn(path, "rt", encoding="utf-8", errors="replace") as fh:
        for event, elem in ET.iterparse(fh, events=("start", "end")):
            tag = _tag_name(elem.tag)

            if event == "start":
                if tag in {"create", "modify", "delete"}:
                    current_action = tag
                continue

            # end event
            if tag in {"create", "modify", "delete"}:
                current_action = None
                elem.clear()
                continue

            if tag == "node":
                node_id = elem.attrib.get("id")
                lat = elem.attrib.get("lat")
                lon = elem.attrib.get("lon")
                if node_id and lat is not None and lon is not None:
                    try:
                        node_coords[node_id] = (float(lon), float(lat))
                    except ValueError:
                        pass
                elem.clear()
                continue

            if tag == "way":
                way_id = elem.attrib.get("id")
                if not way_id:
                    elem.clear()
                    continue
                action = current_action or "modify"
                if action == "create":
                    ways_added += 1
                elif action == "delete":
                    ways_removed += 1
                else:
                    ways_modified += 1

                tags: Dict[str, str] = {}
                has_speed = False
                for child in elem:
                    ctag = _tag_name(child.tag)
                    if ctag == "tag":
                        k = child.attrib.get("k")
                        v = child.attrib.get("v")
                        if k:
                            tags[k] = v or ""
                            if k in MAXSPEED_KEYS:
                                has_speed = True
                if has_speed:
                    maxspeed_tag_events += 1
                    if action == "modify":
                        maxspeed_tag_changes += 1
                is_admin_boundary_way = (
                    tags.get("boundary") == "administrative"
                    and tags.get("admin_level") in ADMIN_BOUNDARY_LEVELS
                )
                if is_admin_boundary_way:
                    boundary_admin_way_events += 1
                    if action == "modify":
                        boundary_admin_way_changes += 1

                node_refs: List[str] = []
                for child in elem:
                    ctag = _tag_name(child.tag)
                    if ctag == "nd":
                        ref = child.attrib.get("ref")
                        if ref:
                            node_refs.append(ref)

                ops_by_way[way_id] = WayOp(action=action, tags=tags, node_refs=node_refs)
                elem.clear()
                continue

            # Do not clear generic child elements here (e.g. nd/tag), because
            # the parent <way> end-handler still needs their attributes.

    return DiffParseResult(
        ways_added=ways_added,
        ways_removed=ways_removed,
        ways_modified=ways_modified,
        maxspeed_tag_events=maxspeed_tag_events,
        maxspeed_tag_changes=maxspeed_tag_changes,
        boundary_admin_way_events=boundary_admin_way_events,
        boundary_admin_way_changes=boundary_admin_way_changes,
        ops_by_way=ops_by_way,
        node_coords=node_coords,
    )


def _chunked(seq: Sequence[str], n: int) -> Iterable[List[str]]:
    for i in range(0, len(seq), n):
        yield list(seq[i : i + n])


def _fetch_existing_rows(conn: sqlite3.Connection, way_ids: Sequence[str]) -> Dict[str, sqlite3.Row]:
    if not way_ids:
        return {}
    out: Dict[str, sqlite3.Row] = {}
    for chunk in _chunked(way_ids, 500):
        placeholders = ",".join(["?"] * len(chunk))
        sql = f"""
        SELECT
          w.row_id,
          w.way_id,
          w.highway,
          w.maxspeed,
          w.maxspeed_type,
          w.source_maxspeed,
          w.zone_maxspeed,
          w.traffic_sign,
          w.approx_heading_deg,
          w.min_lon,
          w.min_lat,
          w.max_lon,
          w.max_lat,
          g.points_json
        FROM ways w
        LEFT JOIN way_geom g ON g.row_id = w.row_id
        WHERE w.way_id IN ({placeholders})
        """
        for row in conn.execute(sql, chunk):
            out[str(row["way_id"])] = row
    return out


def _fetch_row_ids(conn: sqlite3.Connection, way_ids: Sequence[str]) -> Dict[str, int]:
    if not way_ids:
        return {}
    out: Dict[str, int] = {}
    for chunk in _chunked(way_ids, 500):
        placeholders = ",".join(["?"] * len(chunk))
        sql = f"SELECT way_id, row_id FROM ways WHERE way_id IN ({placeholders})"
        for row in conn.execute(sql, chunk):
            out[str(row["way_id"])] = int(row["row_id"])
    return out


def _fetch_existing_area_rows(conn: sqlite3.Connection, area_ids: Sequence[str]) -> Dict[str, sqlite3.Row]:
    if not area_ids:
        return {}
    out: Dict[str, sqlite3.Row] = {}
    for chunk in _chunked(list(area_ids), 500):
        placeholders = ",".join(["?"] * len(chunk))
        sql = f"""
        SELECT
          row_id,
          area_id,
          geometry_type,
          name,
          place,
          boundary,
          admin_level,
          min_lon,
          min_lat,
          max_lon,
          max_lat
        FROM areas
        WHERE area_id IN ({placeholders})
        """
        for row in conn.execute(sql, chunk):
            out[str(row["area_id"])] = row
    return out


def _fetch_way_tile_counts(conn: sqlite3.Connection, row_ids: Sequence[int]) -> Dict[int, int]:
    if not row_ids:
        return {}
    out: Dict[int, int] = {}
    row_id_str = [str(r) for r in row_ids]
    for chunk in _chunked(row_id_str, 500):
        placeholders = ",".join(["?"] * len(chunk))
        sql = f"SELECT row_id, COUNT(*) AS c FROM way_tile WHERE row_id IN ({placeholders}) GROUP BY row_id"
        for row in conn.execute(sql, chunk):
            out[int(row["row_id"])] = int(row["c"])
    return out


def _bbox_from_nodes(node_refs: Sequence[str], node_coords: Dict[str, Tuple[float, float]]) -> Optional[Tuple[float, float, float, float]]:
    points = []
    for ref in node_refs:
        pt = node_coords.get(ref)
        if pt is not None:
            points.append(pt)
    if len(points) < 2:
        return None
    lons = [p[0] for p in points]
    lats = [p[1] for p in points]
    return (min(lons), min(lats), max(lons), max(lats))


def _points_json_from_nodes(node_refs: Sequence[str], node_coords: Dict[str, Tuple[float, float]]) -> str:
    pts = []
    for ref in node_refs:
        pt = node_coords.get(ref)
        if pt is None:
            continue
        lon, lat = pt
        pts.append([lat, lon])
    return json.dumps(pts, separators=(",", ":"))


def _build_insert_payload(
    way_id: str,
    op: WayOp,
    existing: Optional[sqlite3.Row],
    node_coords: Dict[str, Tuple[float, float]],
) -> Optional[dict]:
    bbox = _bbox_from_nodes(op.node_refs, node_coords)
    if bbox is None and existing is not None:
        bbox = (
            float(existing["min_lon"]),
            float(existing["min_lat"]),
            float(existing["max_lon"]),
            float(existing["max_lat"]),
        )
    if bbox is None:
        return None

    min_lon, min_lat, max_lon, max_lat = bbox
    tags = op.tags
    payload = {
        "way_id": way_id,
        "highway": tags.get("highway", existing["highway"] if existing is not None else None),
        "maxspeed": tags.get("maxspeed", existing["maxspeed"] if existing is not None else None),
        "maxspeed_type": tags.get("maxspeed:type", existing["maxspeed_type"] if existing is not None else None),
        "source_maxspeed": tags.get("source:maxspeed", existing["source_maxspeed"] if existing is not None else None),
        "zone_maxspeed": tags.get("zone:maxspeed", existing["zone_maxspeed"] if existing is not None else None),
        "traffic_sign": tags.get("traffic_sign", existing["traffic_sign"] if existing is not None else None),
        "approx_heading_deg": existing["approx_heading_deg"] if existing is not None else None,
        "min_lon": float(min_lon),
        "min_lat": float(min_lat),
        "max_lon": float(max_lon),
        "max_lat": float(max_lat),
        "points_json": (
            existing["points_json"]
            if existing is not None and existing["points_json"] is not None
            else _points_json_from_nodes(op.node_refs, node_coords)
        ),
    }
    return payload


def _build_boundary_area_insert_payload(
    way_id: str,
    op: WayOp,
    existing_area: Optional[sqlite3.Row],
    node_coords: Dict[str, Tuple[float, float]],
) -> Optional[dict]:
    bbox = _bbox_from_nodes(op.node_refs, node_coords)
    if bbox is None and existing_area is not None:
        bbox = (
            float(existing_area["min_lon"]),
            float(existing_area["min_lat"]),
            float(existing_area["max_lon"]),
            float(existing_area["max_lat"]),
        )
    if bbox is None:
        return None

    min_lon, min_lat, max_lon, max_lat = bbox
    tags = op.tags
    payload = {
        "area_id": f"w:{way_id}",
        "geometry_type": "LineString",
        "name": tags.get("name", existing_area["name"] if existing_area is not None else None),
        "place": tags.get("place", existing_area["place"] if existing_area is not None else None),
        "boundary": tags.get("boundary", existing_area["boundary"] if existing_area is not None else None),
        "admin_level": tags.get("admin_level", existing_area["admin_level"] if existing_area is not None else None),
        "min_lon": float(min_lon),
        "min_lat": float(min_lat),
        "max_lon": float(max_lon),
        "max_lat": float(max_lat),
    }
    return payload


def _tile_rows_for_bbox(
    min_lon: float,
    min_lat: float,
    max_lon: float,
    max_lat: float,
    tile_size_m: int,
    max_way_tiles: int,
) -> List[Tuple[int, int]]:
    tx0, tx1, ty0, ty1 = _tile_range_for_bbox(min_lon, min_lat, max_lon, max_lat, tile_size_m)
    tile_count = (tx1 - tx0 + 1) * (ty1 - ty0 + 1)
    if tile_count > max_way_tiles:
        center_lon = (min_lon + max_lon) / 2.0
        center_lat = (min_lat + max_lat) / 2.0
        x, y = _lon_lat_to_mercator_m(center_lon, center_lat)
        return [(math.floor(x / tile_size_m), math.floor(y / tile_size_m))]
    out: List[Tuple[int, int]] = []
    for tx in range(tx0, tx1 + 1):
        for ty in range(ty0, ty1 + 1):
            out.append((tx, ty))
    return out


def _simulate_v3_patch(conn: sqlite3.Connection, delete_ids: Sequence[str], inserts: Sequence[dict]) -> Tuple[float, int, int, Optional[str]]:
    row_ids_by_way = _fetch_row_ids(conn, delete_ids)
    delete_row_ids = list(row_ids_by_way.values())
    delete_rows = len(delete_row_ids) * 3
    insert_rows = len(inserts) * 3

    t0 = time.perf_counter()
    try:
        conn.execute("BEGIN")
        if delete_row_ids:
            rows = [(rid,) for rid in delete_row_ids]
            conn.executemany("DELETE FROM way_geom WHERE row_id=?", rows)
            conn.executemany("DELETE FROM ways_rtree WHERE row_id=?", rows)
            conn.executemany("DELETE FROM ways WHERE row_id=?", rows)

        for ins in inserts:
            cur = conn.execute(
                """
                INSERT INTO ways(
                  way_id, highway, maxspeed, maxspeed_type, source_maxspeed,
                  zone_maxspeed, traffic_sign, approx_heading_deg,
                  min_lon, min_lat, max_lon, max_lat
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ins["way_id"],
                    ins["highway"],
                    ins["maxspeed"],
                    ins["maxspeed_type"],
                    ins["source_maxspeed"],
                    ins["zone_maxspeed"],
                    ins["traffic_sign"],
                    ins["approx_heading_deg"],
                    ins["min_lon"],
                    ins["min_lat"],
                    ins["max_lon"],
                    ins["max_lat"],
                ),
            )
            row_id = int(cur.lastrowid)
            conn.execute(
                "INSERT INTO ways_rtree(row_id, min_lon, max_lon, min_lat, max_lat) VALUES(?, ?, ?, ?, ?)",
                (row_id, ins["min_lon"], ins["max_lon"], ins["min_lat"], ins["max_lat"]),
            )
            conn.execute(
                "INSERT INTO way_geom(row_id, way_id, points_json) VALUES(?, ?, ?)",
                (row_id, ins["way_id"], ins["points_json"]),
            )
    except Exception as exc:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        return (round((time.perf_counter() - t0) * 1000.0, 3), delete_rows, insert_rows, str(exc))

    conn.execute("ROLLBACK")
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)
    return (elapsed_ms, delete_rows, insert_rows, None)


def _simulate_v4_patch(
    conn: sqlite3.Connection,
    delete_ids: Sequence[str],
    inserts: Sequence[dict],
    tile_size_m: int,
    max_way_tiles: int,
) -> Tuple[float, int, int, Optional[str]]:
    row_ids_by_way = _fetch_row_ids(conn, delete_ids)
    delete_row_ids = list(row_ids_by_way.values())
    tile_counts = _fetch_way_tile_counts(conn, delete_row_ids)
    delete_rows = 0
    for rid in delete_row_ids:
        delete_rows += 3  # ways + ways_rtree + way_geom
        delete_rows += int(tile_counts.get(rid, 0))  # way_tile rows

    insert_rows = 0
    for ins in inserts:
        tile_rows = _tile_rows_for_bbox(
            ins["min_lon"],
            ins["min_lat"],
            ins["max_lon"],
            ins["max_lat"],
            tile_size_m=tile_size_m,
            max_way_tiles=max_way_tiles,
        )
        insert_rows += 3 + len(tile_rows)

    t0 = time.perf_counter()
    try:
        conn.execute("BEGIN")
        if delete_row_ids:
            rows = [(rid,) for rid in delete_row_ids]
            conn.executemany("DELETE FROM way_tile WHERE row_id=?", rows)
            conn.executemany("DELETE FROM way_geom WHERE row_id=?", rows)
            conn.executemany("DELETE FROM ways_rtree WHERE row_id=?", rows)
            conn.executemany("DELETE FROM ways WHERE row_id=?", rows)

        for ins in inserts:
            cur = conn.execute(
                """
                INSERT INTO ways(
                  way_id, highway, maxspeed, maxspeed_type, source_maxspeed,
                  zone_maxspeed, traffic_sign, approx_heading_deg,
                  min_lon, min_lat, max_lon, max_lat
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ins["way_id"],
                    ins["highway"],
                    ins["maxspeed"],
                    ins["maxspeed_type"],
                    ins["source_maxspeed"],
                    ins["zone_maxspeed"],
                    ins["traffic_sign"],
                    ins["approx_heading_deg"],
                    ins["min_lon"],
                    ins["min_lat"],
                    ins["max_lon"],
                    ins["max_lat"],
                ),
            )
            row_id = int(cur.lastrowid)
            conn.execute(
                "INSERT INTO ways_rtree(row_id, min_lon, max_lon, min_lat, max_lat) VALUES(?, ?, ?, ?, ?)",
                (row_id, ins["min_lon"], ins["max_lon"], ins["min_lat"], ins["max_lat"]),
            )
            conn.execute(
                "INSERT INTO way_geom(row_id, way_id, points_json) VALUES(?, ?, ?)",
                (row_id, ins["way_id"], ins["points_json"]),
            )

            tile_rows = _tile_rows_for_bbox(
                ins["min_lon"],
                ins["min_lat"],
                ins["max_lon"],
                ins["max_lat"],
                tile_size_m=tile_size_m,
                max_way_tiles=max_way_tiles,
            )
            if tile_rows:
                conn.executemany(
                    "INSERT INTO way_tile(row_id, tile_x, tile_y) VALUES(?, ?, ?)",
                    [(row_id, tx, ty) for tx, ty in tile_rows],
                )
    except Exception as exc:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        return (round((time.perf_counter() - t0) * 1000.0, 3), delete_rows, insert_rows, str(exc))

    conn.execute("ROLLBACK")
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)
    return (elapsed_ms, delete_rows, insert_rows, None)


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table_name,),
    ).fetchone()
    return row is not None


def _simulate_v3_area_patch(
    conn: sqlite3.Connection,
    delete_area_ids: Sequence[str],
    inserts: Sequence[dict],
) -> Tuple[float, int, int, Optional[str]]:
    existing = _fetch_existing_area_rows(conn, delete_area_ids)
    delete_row_ids = [int(r["row_id"]) for r in existing.values()]
    delete_rows = len(delete_row_ids) * 2
    insert_rows = len(inserts) * 2

    t0 = time.perf_counter()
    try:
        conn.execute("BEGIN")
        if delete_row_ids:
            rows = [(rid,) for rid in delete_row_ids]
            conn.executemany("DELETE FROM areas_rtree WHERE row_id=?", rows)
            conn.executemany("DELETE FROM areas WHERE row_id=?", rows)

        for ins in inserts:
            cur = conn.execute(
                """
                INSERT INTO areas(
                  area_id, geometry_type, name, place, boundary, admin_level,
                  min_lon, min_lat, max_lon, max_lat
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ins["area_id"],
                    ins["geometry_type"],
                    ins["name"],
                    ins["place"],
                    ins["boundary"],
                    ins["admin_level"],
                    ins["min_lon"],
                    ins["min_lat"],
                    ins["max_lon"],
                    ins["max_lat"],
                ),
            )
            row_id = int(cur.lastrowid)
            conn.execute(
                "INSERT INTO areas_rtree(row_id, min_lon, max_lon, min_lat, max_lat) VALUES(?, ?, ?, ?, ?)",
                (row_id, ins["min_lon"], ins["max_lon"], ins["min_lat"], ins["max_lat"]),
            )
    except Exception as exc:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        return (round((time.perf_counter() - t0) * 1000.0, 3), delete_rows, insert_rows, str(exc))

    conn.execute("ROLLBACK")
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)
    return (elapsed_ms, delete_rows, insert_rows, None)


def _simulate_v4_area_patch(
    conn: sqlite3.Connection,
    delete_area_ids: Sequence[str],
    inserts: Sequence[dict],
    tile_size_m: int,
    max_city_tiles: int,
) -> Tuple[float, int, int, Optional[str]]:
    existing = _fetch_existing_area_rows(conn, delete_area_ids)
    delete_area_row_ids = [int(r["row_id"]) for r in existing.values()]

    has_city_boundary = _table_exists(conn, "city_boundary")
    has_city_boundary_rtree = _table_exists(conn, "city_boundary_rtree")
    has_city_tile = _table_exists(conn, "city_tile")
    has_city_ring = _table_exists(conn, "city_ring")

    delete_boundary_row_ids: List[int] = []
    if has_city_boundary:
        way_ids = [aid.split(":", 1)[1] for aid in delete_area_ids if aid.startswith("w:")]
        for chunk in _chunked(way_ids, 500):
            int_ids: List[int] = []
            for wid in chunk:
                try:
                    int_ids.append(int(wid))
                except ValueError:
                    continue
            if not int_ids:
                continue
            placeholders = ",".join(["?"] * len(int_ids))
            sql = f"SELECT row_id FROM city_boundary WHERE osm_type='w' AND osm_id IN ({placeholders})"
            for row in conn.execute(sql, int_ids):
                delete_boundary_row_ids.append(int(row["row_id"]))

    delete_rows = len(delete_area_row_ids) * 2
    if delete_boundary_row_ids:
        delete_rows += len(delete_boundary_row_ids) * 2  # city_boundary + city_boundary_rtree
        if has_city_tile:
            for chunk in _chunked([str(rid) for rid in delete_boundary_row_ids], 500):
                placeholders = ",".join(["?"] * len(chunk))
                sql = f"SELECT COUNT(*) AS c FROM city_tile WHERE boundary_row_id IN ({placeholders})"
                c_row = conn.execute(sql, chunk).fetchone()
                delete_rows += int(c_row["c"]) if c_row else 0
        if has_city_ring:
            for chunk in _chunked([str(rid) for rid in delete_boundary_row_ids], 500):
                placeholders = ",".join(["?"] * len(chunk))
                sql = f"SELECT COUNT(*) AS c FROM city_ring WHERE boundary_row_id IN ({placeholders})"
                c_row = conn.execute(sql, chunk).fetchone()
                delete_rows += int(c_row["c"]) if c_row else 0

    insert_rows = len(inserts) * 2  # areas + areas_rtree
    if has_city_boundary and has_city_boundary_rtree and has_city_tile:
        for ins in inserts:
            if not str(ins["area_id"]).startswith("w:"):
                continue
            tile_rows = _tile_rows_for_bbox(
                ins["min_lon"],
                ins["min_lat"],
                ins["max_lon"],
                ins["max_lat"],
                tile_size_m=tile_size_m,
                max_way_tiles=max_city_tiles,
            )
            insert_rows += 2 + len(tile_rows)  # city_boundary + rtree + city_tile rows

    t0 = time.perf_counter()
    try:
        conn.execute("BEGIN")

        if delete_area_row_ids:
            rows = [(rid,) for rid in delete_area_row_ids]
            conn.executemany("DELETE FROM areas_rtree WHERE row_id=?", rows)
            conn.executemany("DELETE FROM areas WHERE row_id=?", rows)

        if delete_boundary_row_ids and has_city_boundary:
            rows = [(rid,) for rid in delete_boundary_row_ids]
            if has_city_tile:
                conn.executemany("DELETE FROM city_tile WHERE boundary_row_id=?", rows)
            if has_city_ring:
                conn.executemany("DELETE FROM city_ring WHERE boundary_row_id=?", rows)
            if has_city_boundary_rtree:
                conn.executemany("DELETE FROM city_boundary_rtree WHERE row_id=?", rows)
            conn.executemany("DELETE FROM city_boundary WHERE row_id=?", rows)

        for ins in inserts:
            cur = conn.execute(
                """
                INSERT INTO areas(
                  area_id, geometry_type, name, place, boundary, admin_level,
                  min_lon, min_lat, max_lon, max_lat
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    ins["area_id"],
                    ins["geometry_type"],
                    ins["name"],
                    ins["place"],
                    ins["boundary"],
                    ins["admin_level"],
                    ins["min_lon"],
                    ins["min_lat"],
                    ins["max_lon"],
                    ins["max_lat"],
                ),
            )
            area_row_id = int(cur.lastrowid)
            conn.execute(
                "INSERT INTO areas_rtree(row_id, min_lon, max_lon, min_lat, max_lat) VALUES(?, ?, ?, ?, ?)",
                (area_row_id, ins["min_lon"], ins["max_lon"], ins["min_lat"], ins["max_lat"]),
            )

            if not (has_city_boundary and has_city_boundary_rtree and has_city_tile):
                continue
            area_id = str(ins["area_id"])
            if not area_id.startswith("w:"):
                continue
            osm_raw = area_id.split(":", 1)[1]
            try:
                osm_id = int(osm_raw)
            except ValueError:
                continue
            try:
                admin_level = int(ins["admin_level"]) if ins["admin_level"] is not None else 8
            except ValueError:
                admin_level = 8
            bcur = conn.execute(
                """
                INSERT INTO city_boundary(
                  osm_type, osm_id, admin_level, name,
                  min_lon, min_lat, max_lon, max_lat
                ) VALUES ('w', ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    osm_id,
                    admin_level,
                    ins["name"],
                    ins["min_lon"],
                    ins["min_lat"],
                    ins["max_lon"],
                    ins["max_lat"],
                ),
            )
            boundary_row_id = int(bcur.lastrowid)
            conn.execute(
                "INSERT INTO city_boundary_rtree(row_id, min_lon, max_lon, min_lat, max_lat) VALUES(?, ?, ?, ?, ?)",
                (boundary_row_id, ins["min_lon"], ins["max_lon"], ins["min_lat"], ins["max_lat"]),
            )
            tile_rows = _tile_rows_for_bbox(
                ins["min_lon"],
                ins["min_lat"],
                ins["max_lon"],
                ins["max_lat"],
                tile_size_m=tile_size_m,
                max_way_tiles=max_city_tiles,
            )
            if tile_rows:
                conn.executemany(
                    "INSERT INTO city_tile(boundary_row_id, tile_x, tile_y) VALUES(?, ?, ?)",
                    [(boundary_row_id, tx, ty) for tx, ty in tile_rows],
                )
    except Exception as exc:
        try:
            conn.execute("ROLLBACK")
        except Exception:
            pass
        return (round((time.perf_counter() - t0) * 1000.0, 3), delete_rows, insert_rows, str(exc))

    conn.execute("ROLLBACK")
    elapsed_ms = round((time.perf_counter() - t0) * 1000.0, 3)
    return (elapsed_ms, delete_rows, insert_rows, None)


def _date_key(path: Path) -> str:
    # Expected format: <region>-YYYY-MM-DD.osc.gz
    name = path.name
    for i in range(len(name) - 9):
        token = name[i : i + 10]
        if token[4] == "-" and token[7] == "-":
            return token
    return datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc).strftime("%Y-%m-%d")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Analyze daily OSM diffs and simulate v3/v4 SQL patch cost")
    parser.add_argument(
        "--diff-dir",
        default="mapdata/reports/deltas/daily",
        help="Directory containing one daily .osc.gz file per day",
    )
    parser.add_argument(
        "--v3-db",
        default="mapdata/dist-v3/germany/speeds_v3.sqlite",
        help="Path to source v3 SQLite DB",
    )
    parser.add_argument(
        "--v4-db",
        default="mapdata/dist-v4/germany/speeds_v4.sqlite",
        help="Path to source v4 SQLite DB",
    )
    parser.add_argument(
        "--work-dir-base",
        default="mapdata/build/germany/delta_analysis",
        help="Base work directory for per-run DB copies and temporary artifacts",
    )
    parser.add_argument(
        "--csv-out",
        default="mapdata/reports/deltas/daily_diff_analysis.csv",
        help="Output CSV path",
    )
    parser.add_argument(
        "--json-out",
        default="mapdata/reports/deltas/daily_diff_analysis.json",
        help="Output summary JSON path",
    )
    parser.add_argument(
        "--v1-grid-scale",
        type=int,
        default=100,
        help="v1 grid scale used for ways.idx (default: 100)",
    )
    parser.add_argument("--v2-tile-size-m", type=int, default=4096, help="v2 tile size in meters (default: 4096)")
    parser.add_argument(
        "--v4-max-way-tiles",
        type=int,
        default=1024,
        help="v4 per-way tile cap before center fallback (default: 1024)",
    )
    parser.add_argument(
        "--v4-max-city-tiles",
        type=int,
        default=50000,
        help="v4 per-boundary tile cap before center fallback (default: 50000)",
    )
    parser.add_argument(
        "--copy-dbs",
        action="store_true",
        default=True,
        help="Copy v3/v4 DBs into run workdir before simulation (default: on)",
    )
    parser.add_argument(
        "--no-copy-dbs",
        action="store_false",
        dest="copy_dbs",
        help="Disable DB copies and operate directly on the provided DB paths",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    diff_dir = Path(args.diff_dir)
    if not diff_dir.exists():
        print(f"Diff directory not found: {diff_dir}", file=sys.stderr)
        return 1
    diff_files = sorted([p for p in diff_dir.iterdir() if p.is_file() and p.name.endswith((".osc", ".osc.gz"))], key=_date_key)
    if not diff_files:
        print(f"No daily diff files found in: {diff_dir}", file=sys.stderr)
        return 1

    src_v3 = Path(args.v3_db)
    src_v4 = Path(args.v4_db)
    if not src_v3.exists() or not src_v4.exists():
        print(f"Missing DB(s): v3={src_v3.exists()} v4={src_v4.exists()}", file=sys.stderr)
        return 1

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(args.work_dir_base) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    if args.copy_dbs:
        sim_v3 = run_dir / "speeds_v3.sim.sqlite"
        sim_v4 = run_dir / "speeds_v4.sim.sqlite"
        print(f"Copying v3 DB -> {sim_v3}", file=sys.stderr)
        shutil.copy2(src_v3, sim_v3)
        print(f"Copying v4 DB -> {sim_v4}", file=sys.stderr)
        shutil.copy2(src_v4, sim_v4)
    else:
        sim_v3 = src_v3
        sim_v4 = src_v4

    conn_v3 = sqlite3.connect(str(sim_v3), isolation_level=None)
    conn_v4 = sqlite3.connect(str(sim_v4), isolation_level=None)
    conn_v3.row_factory = sqlite3.Row
    conn_v4.row_factory = sqlite3.Row

    # Keep write behavior similar to normal patching while preserving speed.
    conn_v3.execute("PRAGMA journal_mode=WAL")
    conn_v4.execute("PRAGMA journal_mode=WAL")
    conn_v3.execute("PRAGMA synchronous=NORMAL")
    conn_v4.execute("PRAGMA synchronous=NORMAL")

    # Prefer DB metadata if available.
    v4_tile_size_row = conn_v4.execute("SELECT value FROM metadata WHERE key='tile_size_m' LIMIT 1").fetchone()
    v4_max_way_tiles_row = conn_v4.execute("SELECT value FROM metadata WHERE key='max_way_tiles' LIMIT 1").fetchone()
    v4_max_city_tiles_row = conn_v4.execute("SELECT value FROM metadata WHERE key='max_city_tiles' LIMIT 1").fetchone()
    v4_tile_size_m = int(v4_tile_size_row["value"]) if v4_tile_size_row else int(args.v2_tile_size_m)
    v4_max_way_tiles = int(v4_max_way_tiles_row["value"]) if v4_max_way_tiles_row else int(args.v4_max_way_tiles)
    v4_max_city_tiles = int(v4_max_city_tiles_row["value"]) if v4_max_city_tiles_row else int(args.v4_max_city_tiles)

    rows: List[dict] = []
    totals = {
        "ways_added": 0,
        "ways_removed": 0,
        "ways_modified": 0,
        "maxspeed_tag_events": 0,
        "maxspeed_tag_changes": 0,
        "boundary_admin_way_events": 0,
        "boundary_admin_way_changes": 0,
        "invalidated_v1_tiles": 0,
        "invalidated_v2_tiles": 0,
        "boundary_invalidated_v1_tiles": 0,
        "boundary_invalidated_v2_tiles": 0,
        "v3_patch_ms": 0.0,
        "v4_patch_ms": 0.0,
        "boundary_v3_patch_ms": 0.0,
        "boundary_v4_patch_ms": 0.0,
    }

    for i, diff_path in enumerate(diff_files, start=1):
        day_key = _date_key(diff_path)
        print(f"[{i}/{len(diff_files)}] parsing {diff_path.name}", file=sys.stderr)
        parsed = _parse_daily_diff(diff_path)

        changed_way_ids = sorted(parsed.ops_by_way.keys())
        existing = _fetch_existing_rows(conn_v3, changed_way_ids)

        invalid_v1 = set()
        invalid_v2 = set()
        unresolved_bbox = 0

        inserts: List[dict] = []
        skipped_inserts = 0
        delete_ids: List[str] = []

        for way_id, op in parsed.ops_by_way.items():
            ex = existing.get(way_id)
            bbox: Optional[Tuple[float, float, float, float]] = None
            if ex is not None:
                bbox = (
                    float(ex["min_lon"]),
                    float(ex["min_lat"]),
                    float(ex["max_lon"]),
                    float(ex["max_lat"]),
                )
            else:
                bbox = _bbox_from_nodes(op.node_refs, parsed.node_coords)

            if bbox is None:
                unresolved_bbox += 1
            else:
                min_lon, min_lat, max_lon, max_lat = bbox
                x0, x1, y0, y1 = _cell_range_for_bbox(min_lon, min_lat, max_lon, max_lat, args.v1_grid_scale)
                for x in range(x0, x1 + 1):
                    for y in range(y0, y1 + 1):
                        invalid_v1.add(f"{x}:{y}")
                tx0, tx1, ty0, ty1 = _tile_range_for_bbox(min_lon, min_lat, max_lon, max_lat, args.v2_tile_size_m)
                for tx in range(tx0, tx1 + 1):
                    for ty in range(ty0, ty1 + 1):
                        invalid_v2.add(f"{tx}/{ty}")

            if op.action in {"delete", "modify"}:
                delete_ids.append(way_id)
            if op.action in {"create", "modify"}:
                payload = _build_insert_payload(way_id, op, ex, parsed.node_coords)
                if payload is None:
                    skipped_inserts += 1
                else:
                    # Avoid unique key errors for create events where way already exists.
                    if op.action == "create" and ex is not None and way_id not in delete_ids:
                        skipped_inserts += 1
                    else:
                        inserts.append(payload)

        v3_ms, v3_delete_rows, v3_insert_rows, v3_error = _simulate_v3_patch(conn_v3, delete_ids, inserts)
        v4_ms, v4_delete_rows, v4_insert_rows, v4_error = _simulate_v4_patch(
            conn_v4,
            delete_ids,
            inserts,
            tile_size_m=v4_tile_size_m,
            max_way_tiles=v4_max_way_tiles,
        )

        boundary_ops = {
            way_id: op
            for way_id, op in parsed.ops_by_way.items()
            if op.tags.get("boundary") == "administrative" and op.tags.get("admin_level") in ADMIN_BOUNDARY_LEVELS
        }
        boundary_existing = _fetch_existing_area_rows(
            conn_v3,
            [f"w:{way_id}" for way_id in boundary_ops.keys()],
        )
        boundary_invalid_v1 = set()
        boundary_invalid_v2 = set()
        boundary_delete_ids: List[str] = []
        boundary_inserts: List[dict] = []
        boundary_unresolved_bbox = 0
        boundary_skipped_inserts = 0

        for way_id, op in boundary_ops.items():
            area_id = f"w:{way_id}"
            existing_area = boundary_existing.get(area_id)

            bbox: Optional[Tuple[float, float, float, float]] = None
            if existing_area is not None:
                bbox = (
                    float(existing_area["min_lon"]),
                    float(existing_area["min_lat"]),
                    float(existing_area["max_lon"]),
                    float(existing_area["max_lat"]),
                )
            else:
                bbox = _bbox_from_nodes(op.node_refs, parsed.node_coords)

            if bbox is None:
                boundary_unresolved_bbox += 1
            else:
                min_lon, min_lat, max_lon, max_lat = bbox
                x0, x1, y0, y1 = _cell_range_for_bbox(min_lon, min_lat, max_lon, max_lat, args.v1_grid_scale)
                for x in range(x0, x1 + 1):
                    for y in range(y0, y1 + 1):
                        boundary_invalid_v1.add(f"{x}:{y}")
                tx0, tx1, ty0, ty1 = _tile_range_for_bbox(min_lon, min_lat, max_lon, max_lat, args.v2_tile_size_m)
                for tx in range(tx0, tx1 + 1):
                    for ty in range(ty0, ty1 + 1):
                        boundary_invalid_v2.add(f"{tx}/{ty}")

            if op.action in {"delete", "modify"}:
                boundary_delete_ids.append(area_id)
            if op.action in {"create", "modify"}:
                payload = _build_boundary_area_insert_payload(way_id, op, existing_area, parsed.node_coords)
                if payload is None:
                    boundary_skipped_inserts += 1
                else:
                    if op.action == "create" and existing_area is not None and area_id not in boundary_delete_ids:
                        boundary_skipped_inserts += 1
                    else:
                        boundary_inserts.append(payload)

        boundary_v3_ms, boundary_v3_delete_rows, boundary_v3_insert_rows, boundary_v3_error = _simulate_v3_area_patch(
            conn_v3, boundary_delete_ids, boundary_inserts
        )
        boundary_v4_ms, boundary_v4_delete_rows, boundary_v4_insert_rows, boundary_v4_error = _simulate_v4_area_patch(
            conn_v4,
            boundary_delete_ids,
            boundary_inserts,
            tile_size_m=v4_tile_size_m,
            max_city_tiles=v4_max_city_tiles,
        )

        row = {
            "date": day_key,
            "diff_file": str(diff_path),
            "ways_added": parsed.ways_added,
            "ways_removed": parsed.ways_removed,
            "ways_modified": parsed.ways_modified,
            "changed_way_count": len(parsed.ops_by_way),
            "maxspeed_tag_events": parsed.maxspeed_tag_events,
            "maxspeed_tag_changes": parsed.maxspeed_tag_changes,
            "boundary_admin_way_events": parsed.boundary_admin_way_events,
            "boundary_admin_way_changes": parsed.boundary_admin_way_changes,
            "invalidated_v1_tiles": len(invalid_v1),
            "invalidated_v2_tiles": len(invalid_v2),
            "boundary_invalidated_v1_tiles": len(boundary_invalid_v1),
            "boundary_invalidated_v2_tiles": len(boundary_invalid_v2),
            "unresolved_bbox_way_count": unresolved_bbox,
            "boundary_unresolved_bbox_way_count": boundary_unresolved_bbox,
            "sql_skipped_insert_way_count": skipped_inserts,
            "boundary_sql_skipped_insert_way_count": boundary_skipped_inserts,
            "v3_sql_delete_rows": v3_delete_rows,
            "v3_sql_insert_rows": v3_insert_rows,
            "v3_sql_total_rows": v3_delete_rows + v3_insert_rows,
            "v3_patch_ms": v3_ms,
            "v3_patch_error": v3_error or "",
            "v4_sql_delete_rows": v4_delete_rows,
            "v4_sql_insert_rows": v4_insert_rows,
            "v4_sql_total_rows": v4_delete_rows + v4_insert_rows,
            "v4_patch_ms": v4_ms,
            "v4_patch_error": v4_error or "",
            "boundary_v3_sql_delete_rows": boundary_v3_delete_rows,
            "boundary_v3_sql_insert_rows": boundary_v3_insert_rows,
            "boundary_v3_sql_total_rows": boundary_v3_delete_rows + boundary_v3_insert_rows,
            "boundary_v3_patch_ms": boundary_v3_ms,
            "boundary_v3_patch_error": boundary_v3_error or "",
            "boundary_v4_sql_delete_rows": boundary_v4_delete_rows,
            "boundary_v4_sql_insert_rows": boundary_v4_insert_rows,
            "boundary_v4_sql_total_rows": boundary_v4_delete_rows + boundary_v4_insert_rows,
            "boundary_v4_patch_ms": boundary_v4_ms,
            "boundary_v4_patch_error": boundary_v4_error or "",
        }
        rows.append(row)

        totals["ways_added"] += parsed.ways_added
        totals["ways_removed"] += parsed.ways_removed
        totals["ways_modified"] += parsed.ways_modified
        totals["maxspeed_tag_events"] += parsed.maxspeed_tag_events
        totals["maxspeed_tag_changes"] += parsed.maxspeed_tag_changes
        totals["boundary_admin_way_events"] += parsed.boundary_admin_way_events
        totals["boundary_admin_way_changes"] += parsed.boundary_admin_way_changes
        totals["invalidated_v1_tiles"] += len(invalid_v1)
        totals["invalidated_v2_tiles"] += len(invalid_v2)
        totals["boundary_invalidated_v1_tiles"] += len(boundary_invalid_v1)
        totals["boundary_invalidated_v2_tiles"] += len(boundary_invalid_v2)
        totals["v3_patch_ms"] += v3_ms
        totals["v4_patch_ms"] += v4_ms
        totals["boundary_v3_patch_ms"] += boundary_v3_ms
        totals["boundary_v4_patch_ms"] += boundary_v4_ms

    conn_v3.close()
    conn_v4.close()

    csv_out = Path(args.csv_out)
    csv_out.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "date",
        "diff_file",
        "ways_added",
        "ways_removed",
        "ways_modified",
        "changed_way_count",
        "maxspeed_tag_events",
        "maxspeed_tag_changes",
        "boundary_admin_way_events",
        "boundary_admin_way_changes",
        "invalidated_v1_tiles",
        "invalidated_v2_tiles",
        "boundary_invalidated_v1_tiles",
        "boundary_invalidated_v2_tiles",
        "unresolved_bbox_way_count",
        "boundary_unresolved_bbox_way_count",
        "sql_skipped_insert_way_count",
        "boundary_sql_skipped_insert_way_count",
        "v3_sql_delete_rows",
        "v3_sql_insert_rows",
        "v3_sql_total_rows",
        "v3_patch_ms",
        "v3_patch_error",
        "v4_sql_delete_rows",
        "v4_sql_insert_rows",
        "v4_sql_total_rows",
        "v4_patch_ms",
        "v4_patch_error",
        "boundary_v3_sql_delete_rows",
        "boundary_v3_sql_insert_rows",
        "boundary_v3_sql_total_rows",
        "boundary_v3_patch_ms",
        "boundary_v3_patch_error",
        "boundary_v4_sql_delete_rows",
        "boundary_v4_sql_insert_rows",
        "boundary_v4_sql_total_rows",
        "boundary_v4_patch_ms",
        "boundary_v4_patch_error",
    ]
    with csv_out.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow(row)

    json_out = Path(args.json_out)
    json_out.parent.mkdir(parents=True, exist_ok=True)
    summary = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_dir": str(run_dir),
        "source_inputs": {
            "diff_dir": str(diff_dir),
            "v3_db": str(src_v3),
            "v4_db": str(src_v4),
            "sim_v3_db": str(sim_v3),
            "sim_v4_db": str(sim_v4),
            "copy_dbs": bool(args.copy_dbs),
        },
        "parameters": {
            "v1_grid_scale": args.v1_grid_scale,
            "v2_tile_size_m": args.v2_tile_size_m,
            "v4_tile_size_m": v4_tile_size_m,
            "v4_max_way_tiles": v4_max_way_tiles,
            "v4_max_city_tiles": v4_max_city_tiles,
        },
        "totals": totals,
        "days": len(rows),
        "four_tradeoff_update_daily_mean": {
            "S1_v1": {
                "maxspeed_update_workload": round((totals["invalidated_v1_tiles"] / len(rows)) if rows else 0.0, 3),
                "boundary_update_workload": round((totals["boundary_invalidated_v1_tiles"] / len(rows)) if rows else 0.0, 3),
                "polygon_update_workload": round((totals["boundary_invalidated_v1_tiles"] / len(rows)) if rows else 0.0, 3),
                "unit": "invalidated_grid_cells_per_day",
            },
            "S2_v2": {
                "maxspeed_update_workload": round((totals["invalidated_v2_tiles"] / len(rows)) if rows else 0.0, 3),
                "boundary_update_workload": round((totals["boundary_invalidated_v2_tiles"] / len(rows)) if rows else 0.0, 3),
                "polygon_update_workload": round((totals["boundary_invalidated_v2_tiles"] / len(rows)) if rows else 0.0, 3),
                "unit": "invalidated_tiles_per_day",
            },
            "S3_v3": {
                "maxspeed_update_workload": round((totals["v3_patch_ms"] / len(rows)) if rows else 0.0, 3),
                "boundary_update_workload": round((totals["boundary_v3_patch_ms"] / len(rows)) if rows else 0.0, 3),
                "polygon_update_workload": round((totals["boundary_v3_patch_ms"] / len(rows)) if rows else 0.0, 3),
                "unit": "simulated_patch_ms_per_day",
            },
            "S4_v4": {
                "maxspeed_update_workload": round((totals["v4_patch_ms"] / len(rows)) if rows else 0.0, 3),
                "boundary_update_workload": round((totals["boundary_v4_patch_ms"] / len(rows)) if rows else 0.0, 3),
                "polygon_update_workload": round((totals["boundary_v4_patch_ms"] / len(rows)) if rows else 0.0, 3),
                "unit": "simulated_patch_ms_per_day",
            },
        },
        "csv_path": str(csv_out),
        "rows": rows,
    }
    json_out.write_text(json.dumps(summary, indent=2, sort_keys=True), encoding="utf-8")

    print(f"Wrote CSV: {csv_out}", file=sys.stderr)
    print(f"Wrote JSON summary: {json_out}", file=sys.stderr)
    print(f"Run work dir: {run_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
