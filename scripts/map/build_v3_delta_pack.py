#!/usr/bin/env python3
"""Build a v3 incremental SQL patch pack from a daily OSM diff.

Modes:
1) Heuristic OSC mode (default): infer row operations from .osc(.gz) and base DB.
2) Exact DB diff mode (--target-db): build a lossless patch by diffing base DB against
   a fully rebuilt target DB (recommended for release pipelines).
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import sqlite3
import tempfile
import zlib
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Set, Tuple


MAXSPEED_KEYS = {"maxspeed", "zone:maxspeed", "maxspeed:type", "source:maxspeed", "max:speed"}
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

WAY_COLS = [
    "way_id",
    "highway",
    "street_name",
    "ref",
    "maxspeed",
    "maxspeed_type",
    "source_maxspeed",
    "approx_heading_deg",
    "service",
    "tunnel",
    "min_lon",
    "min_lat",
    "max_lon",
    "max_lat",
]

AREA_COLS = [
    "area_id",
    "geometry_type",
    "name",
    "place",
    "boundary",
    "admin_level",
    "residential",
    "points_json",
    "min_lon",
    "min_lat",
    "max_lon",
    "max_lat",
]

WAY_LINK_COLS = [
    "way_id",
    "linked_way_id",
    "shared_ref",
    "link_kind",
]


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
    ops_by_way: Dict[str, WayOp]
    node_coords: Dict[str, Tuple[float, float]]  # node_id -> (lon, lat)


def _tag_name(raw: str) -> str:
    if "}" in raw:
        return raw.rsplit("}", 1)[-1]
    return raw


def _iter_chunks(seq: Sequence[str], n: int) -> Iterable[List[str]]:
    for i in range(0, len(seq), n):
        yield list(seq[i : i + n])


def _sha256_path(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _sql_escape(value: str) -> str:
    return value.replace("'", "''")


def _sql_literal(value: Optional[object]) -> str:
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        return format(value, ".17g")
    return f"'{_sql_escape(str(value))}'"


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _github_release_asset_url(owner: str, repo: str, tag: str, asset_name: str) -> str:
    return f"https://github.com/{owner}/{repo}/releases/download/{tag}/{asset_name}"


def _id_sort_key(raw_id: str) -> Tuple[int, int | str]:
    if raw_id.isdigit():
        return (0, int(raw_id))
    return (1, raw_id)


def _coerce_way_link_ids(way_ids: Sequence[str]) -> List[int]:
    out: List[int] = []
    for raw_id in way_ids:
        text = str(raw_id).strip()
        if not text:
            continue
        try:
            out.append(int(text))
        except ValueError as exc:
            raise SystemExit(f"way_links requires numeric OSM way IDs, got: {raw_id!r}") from exc
    return out


def _table_exists(conn: sqlite3.Connection, db_alias: str, table: str) -> bool:
    row = conn.execute(
        f"SELECT 1 FROM {db_alias}.sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (table,),
    ).fetchone()
    return row is not None


def _parse_daily_diff(path: Path) -> DiffParseResult:
    ways_added = 0
    ways_removed = 0
    ways_modified = 0
    maxspeed_tag_events = 0
    maxspeed_tag_changes = 0
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
                node_refs: List[str] = []
                for child in elem:
                    ctag = _tag_name(child.tag)
                    if ctag == "tag":
                        k = child.attrib.get("k")
                        v = child.attrib.get("v")
                        if k:
                            tags[k] = v or ""
                            if k in MAXSPEED_KEYS:
                                has_speed = True
                    elif ctag == "nd":
                        ref = child.attrib.get("ref")
                        if ref:
                            node_refs.append(ref)

                if has_speed:
                    maxspeed_tag_events += 1
                    if action == "modify":
                        maxspeed_tag_changes += 1

                ops_by_way[way_id] = WayOp(action=action, tags=tags, node_refs=node_refs)
                elem.clear()
                continue

    return DiffParseResult(
        ways_added=ways_added,
        ways_removed=ways_removed,
        ways_modified=ways_modified,
        maxspeed_tag_events=maxspeed_tag_events,
        maxspeed_tag_changes=maxspeed_tag_changes,
        ops_by_way=ops_by_way,
        node_coords=node_coords,
    )


def _fetch_existing_rows(conn: sqlite3.Connection, way_ids: Sequence[str]) -> Dict[str, sqlite3.Row]:
    out: Dict[str, sqlite3.Row] = {}
    if not way_ids:
        return out
    for chunk in _iter_chunks(list(way_ids), 500):
        placeholders = ",".join(["?"] * len(chunk))
        sql = f"""
        SELECT
          w.way_id,
          w.highway,
          w.street_name,
          w.ref,
          w.maxspeed,
          w.maxspeed_type,
          w.source_maxspeed,
          w.approx_heading_deg,
          w.service,
          w.tunnel,
          w.min_lon,
          w.min_lat,
          w.max_lon,
          w.max_lat,
          g.points_json
        FROM ways w
        LEFT JOIN way_geom g ON g.way_id = w.way_id
        WHERE w.way_id IN ({placeholders})
        """
        for row in conn.execute(sql, chunk):
            out[str(row["way_id"])] = row
    return out


def _fetch_way_payload_rows(conn: sqlite3.Connection, db_alias: str, way_ids: Sequence[str]) -> List[dict]:
    out: List[dict] = []
    if not way_ids:
        return out
    for chunk in _iter_chunks(list(way_ids), 500):
        placeholders = ",".join(["?"] * len(chunk))
        sql = f"""
        SELECT
          w.way_id,
          w.highway,
          w.street_name,
          w.ref,
          w.maxspeed,
          w.maxspeed_type,
          w.source_maxspeed,
          w.approx_heading_deg,
          w.service,
          w.tunnel,
          w.min_lon,
          w.min_lat,
          w.max_lon,
          w.max_lat,
          g.points_json
        FROM {db_alias}.ways w
        LEFT JOIN {db_alias}.way_geom g ON g.way_id = w.way_id
        WHERE w.way_id IN ({placeholders})
        """
        for row in conn.execute(sql, chunk):
            out.append(
                {
                    "way_id": str(row[0]),
                    "highway": row[1],
                    "street_name": row[2],
                    "ref": row[3],
                    "maxspeed": row[4],
                    "maxspeed_type": row[5],
                    "source_maxspeed": row[6],
                    "approx_heading_deg": row[7],
                    "service": row[8],
                    "tunnel": row[9],
                    "min_lon": float(row[10]),
                    "min_lat": float(row[11]),
                    "max_lon": float(row[12]),
                    "max_lat": float(row[13]),
                    "points_json": row[14] if row[14] is not None else "[]",
                }
            )
    return out


def _fetch_way_link_payload_rows(conn: sqlite3.Connection, db_alias: str, way_ids: Sequence[str]) -> List[dict]:
    out: List[dict] = []
    int_way_ids = _coerce_way_link_ids(way_ids)
    if not int_way_ids:
        return out
    for chunk in _iter_chunks(int_way_ids, 500):
        placeholders = ",".join(["?"] * len(chunk))
        sql = f"""
        SELECT
          way_id,
          linked_way_id,
          shared_ref,
          link_kind
        FROM {db_alias}.way_links
        WHERE way_id IN ({placeholders})
           OR linked_way_id IN ({placeholders})
        ORDER BY way_id, linked_way_id
        """
        params = list(chunk) + list(chunk)
        for row in conn.execute(sql, params):
            out.append(
                {
                    "way_id": int(row[0]),
                    "linked_way_id": int(row[1]),
                    "shared_ref": int(row[2]),
                    "link_kind": row[3],
                }
            )
    return out


def _count_way_link_rows(conn: sqlite3.Connection, db_alias: str, way_ids: Sequence[str]) -> int:
    int_way_ids = _coerce_way_link_ids(way_ids)
    if not int_way_ids:
        return 0
    total = 0
    for chunk in _iter_chunks(int_way_ids, 500):
        placeholders = ",".join(["?"] * len(chunk))
        sql = f"""
        SELECT COUNT(*)
        FROM {db_alias}.way_links
        WHERE way_id IN ({placeholders})
           OR linked_way_id IN ({placeholders})
        """
        params = list(chunk) + list(chunk)
        total += int(conn.execute(sql, params).fetchone()[0])
    return total


def _bbox_from_nodes(node_refs: Sequence[str], node_coords: Dict[str, Tuple[float, float]]) -> Optional[Tuple[float, float, float, float]]:
    points: List[Tuple[float, float]] = []
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
    pts: List[List[float]] = []
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
    return {
        "way_id": way_id,
        "highway": tags.get("highway", existing["highway"] if existing is not None else None),
        "street_name": tags.get("name", existing["street_name"] if existing is not None else None),
        "ref": tags.get("ref", existing["ref"] if existing is not None else None),
        "maxspeed": tags.get("maxspeed", existing["maxspeed"] if existing is not None else None),
        "maxspeed_type": tags.get("maxspeed:type", existing["maxspeed_type"] if existing is not None else None),
        "source_maxspeed": tags.get("source:maxspeed", existing["source_maxspeed"] if existing is not None else None),
        "approx_heading_deg": existing["approx_heading_deg"] if existing is not None else None,
        "service": tags.get("service", existing["service"] if existing is not None else None),
        "tunnel": tags.get("tunnel", existing["tunnel"] if existing is not None else None),
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


def _compute_heuristic_delta(
    base_conn: sqlite3.Connection,
    parsed: DiffParseResult,
) -> Tuple[List[str], List[dict], List[dict], List[dict], dict]:
    changed_ids = sorted(parsed.ops_by_way.keys(), key=_id_sort_key)
    existing_rows = _fetch_existing_rows(base_conn, changed_ids)

    delete_ids: List[str] = []
    inserts: List[dict] = []
    skipped_inserts = 0
    skipped_non_drivable = 0

    for way_id, op in parsed.ops_by_way.items():
        existing = existing_rows.get(way_id)
        if op.action in {"delete", "modify"}:
            delete_ids.append(way_id)
        if op.action in {"create", "modify"}:
            payload = _build_insert_payload(way_id, op, existing, parsed.node_coords)
            if payload is None:
                skipped_inserts += 1
                continue
            highway = str(payload.get("highway") or "").strip()
            if highway not in DRIVABLE_HIGHWAYS_CAR:
                skipped_non_drivable += 1
                continue
            if op.action == "create" and existing is not None and way_id not in delete_ids:
                skipped_inserts += 1
                continue
            inserts.append(payload)

    stats = {
        "mode": "heuristic_osc",
        "changed_way_count": len(parsed.ops_by_way),
        "ways_added": parsed.ways_added,
        "ways_removed": parsed.ways_removed,
        "ways_modified": parsed.ways_modified,
        "maxspeed_tag_events": parsed.maxspeed_tag_events,
        "maxspeed_tag_changes": parsed.maxspeed_tag_changes,
        "delete_way_count": len(set(delete_ids)),
        "insert_way_count": len(inserts),
        "skipped_insert_way_count": skipped_inserts,
        "skipped_non_drivable_way_count": skipped_non_drivable,
        "delete_area_count": 0,
        "insert_area_count": 0,
    }
    return delete_ids, inserts, [], [], stats


def _compute_exact_way_delta(base_conn: sqlite3.Connection, target_alias: str) -> Tuple[List[str], List[dict], dict]:
    base_only_ids = [
        str(r[0])
        for r in base_conn.execute(
            f"""
            SELECT b.way_id
            FROM main.ways b
            LEFT JOIN {target_alias}.ways t ON t.way_id = b.way_id
            WHERE t.way_id IS NULL
            """
        )
    ]

    changed_or_new_ids = [
        str(r[0])
        for r in base_conn.execute(
            f"""
            SELECT t.way_id
            FROM {target_alias}.ways t
            LEFT JOIN main.ways b ON b.way_id = t.way_id
            LEFT JOIN {target_alias}.way_geom tg ON tg.way_id = t.way_id
            LEFT JOIN main.way_geom bg ON bg.way_id = t.way_id
            WHERE
              b.way_id IS NULL OR
              COALESCE(b.highway,'') != COALESCE(t.highway,'') OR
              COALESCE(b.street_name,'') != COALESCE(t.street_name,'') OR
              COALESCE(b.ref,'') != COALESCE(t.ref,'') OR
              COALESCE(b.maxspeed,'') != COALESCE(t.maxspeed,'') OR
              COALESCE(b.maxspeed_type,'') != COALESCE(t.maxspeed_type,'') OR
              COALESCE(b.source_maxspeed,'') != COALESCE(t.source_maxspeed,'') OR
              ABS(COALESCE(b.approx_heading_deg,0.0) - COALESCE(t.approx_heading_deg,0.0)) > 1e-9 OR
              COALESCE(b.service,'') != COALESCE(t.service,'') OR
              COALESCE(b.tunnel,'') != COALESCE(t.tunnel,'') OR
              ABS(COALESCE(b.min_lon,0.0) - COALESCE(t.min_lon,0.0)) > 1e-12 OR
              ABS(COALESCE(b.min_lat,0.0) - COALESCE(t.min_lat,0.0)) > 1e-12 OR
              ABS(COALESCE(b.max_lon,0.0) - COALESCE(t.max_lon,0.0)) > 1e-12 OR
              ABS(COALESCE(b.max_lat,0.0) - COALESCE(t.max_lat,0.0)) > 1e-12 OR
              COALESCE(bg.points_json,'') != COALESCE(tg.points_json,'')
            """
        )
    ]

    deletes = sorted(set(base_only_ids + changed_or_new_ids), key=_id_sort_key)
    inserts = _fetch_way_payload_rows(base_conn, target_alias, sorted(set(changed_or_new_ids), key=_id_sort_key))

    stats = {
        "delete_way_count": len(deletes),
        "insert_way_count": len(inserts),
        "exact_way_removed_count": len(base_only_ids),
        "exact_way_upsert_count": len(set(changed_or_new_ids)),
    }
    return deletes, inserts, stats


def _compute_exact_area_delta(base_conn: sqlite3.Connection, target_alias: str) -> Tuple[List[dict], List[dict], dict]:
    has_base = _table_exists(base_conn, "main", "areas") and _table_exists(base_conn, "main", "areas_rtree")
    has_target = _table_exists(base_conn, target_alias, "areas") and _table_exists(base_conn, target_alias, "areas_rtree")
    if not (has_base and has_target):
        return [], [], {"delete_area_count": 0, "insert_area_count": 0, "exact_area_mode": "disabled_missing_tables"}

    base_row_id_by_area = {
        str(r[0]): int(r[1])
        for r in base_conn.execute("SELECT area_id, row_id FROM main.areas")
    }
    max_base_row_id = int(base_conn.execute("SELECT COALESCE(MAX(row_id), 0) FROM main.areas").fetchone()[0])
    next_row_id = max_base_row_id + 1

    base_only_rows = [
        {"area_id": str(r[0]), "row_id": int(r[1])}
        for r in base_conn.execute(
            f"""
            SELECT b.area_id, b.row_id
            FROM main.areas b
            LEFT JOIN {target_alias}.areas t ON t.area_id = b.area_id
            WHERE t.area_id IS NULL
            """
        )
    ]

    changed_or_new_rows = base_conn.execute(
        f"""
        SELECT
          t.area_id,
          t.geometry_type,
          t.name,
          t.place,
          t.boundary,
          t.admin_level,
          t.residential,
          t.points_json,
          t.min_lon,
          t.min_lat,
          t.max_lon,
          t.max_lat
        FROM {target_alias}.areas t
        LEFT JOIN main.areas b ON b.area_id = t.area_id
        WHERE
          b.area_id IS NULL OR
          COALESCE(b.geometry_type,'') != COALESCE(t.geometry_type,'') OR
          COALESCE(b.name,'') != COALESCE(t.name,'') OR
          COALESCE(b.place,'') != COALESCE(t.place,'') OR
          COALESCE(b.boundary,'') != COALESCE(t.boundary,'') OR
          COALESCE(b.admin_level,'') != COALESCE(t.admin_level,'') OR
          COALESCE(b.residential,'') != COALESCE(t.residential,'') OR
          COALESCE(b.points_json,'') != COALESCE(t.points_json,'') OR
          ABS(COALESCE(b.min_lon,0.0) - COALESCE(t.min_lon,0.0)) > 1e-12 OR
          ABS(COALESCE(b.min_lat,0.0) - COALESCE(t.min_lat,0.0)) > 1e-12 OR
          ABS(COALESCE(b.max_lon,0.0) - COALESCE(t.max_lon,0.0)) > 1e-12 OR
          ABS(COALESCE(b.max_lat,0.0) - COALESCE(t.max_lat,0.0)) > 1e-12
        """
    ).fetchall()

    area_deletes: Dict[str, dict] = {row["area_id"]: row for row in base_only_rows}
    area_inserts: List[dict] = []
    area_added_count = 0
    area_changed_count = 0
    reassigned_row_ids = 0

    for row in changed_or_new_rows:
        area_id = str(row[0])
        base_row_id = base_row_id_by_area.get(area_id)
        if base_row_id is not None:
            assigned_row_id = base_row_id
            area_changed_count += 1
            area_deletes[area_id] = {"area_id": area_id, "row_id": assigned_row_id}
        else:
            assigned_row_id = next_row_id
            next_row_id += 1
            area_added_count += 1
            reassigned_row_ids += 1

        area_inserts.append(
            {
                "row_id": int(assigned_row_id),
                "area_id": area_id,
                "geometry_type": row[1],
                "name": row[2],
                "place": row[3],
                "boundary": row[4],
                "admin_level": row[5],
                "residential": row[6],
                "points_json": row[7],
                "min_lon": float(row[8]),
                "min_lat": float(row[9]),
                "max_lon": float(row[10]),
                "max_lat": float(row[11]),
            }
        )

    stats = {
        "delete_area_count": len(area_deletes),
        "insert_area_count": len(area_inserts),
        "exact_area_added_count": area_added_count,
        "exact_area_removed_count": len(base_only_rows),
        "exact_area_changed_count": area_changed_count,
        "exact_area_reassigned_row_ids_for_new_count": reassigned_row_ids,
    }
    return list(area_deletes.values()), area_inserts, stats


def _compute_exact_way_link_delta(
    base_conn: sqlite3.Connection,
    target_alias: str,
    changed_way_ids: Sequence[str],
) -> Tuple[List[str], List[dict], dict]:
    has_base = _table_exists(base_conn, "main", "way_links")
    has_target = _table_exists(base_conn, target_alias, "way_links")
    if not has_base and not has_target:
        return [], [], {"delete_way_link_count": 0, "insert_way_link_count": 0, "way_links_mode": "disabled"}
    if has_base != has_target:
        raise SystemExit("Schema mismatch: way_links table must exist in both base and target DBs")
    if not changed_way_ids:
        return [], [], {"delete_way_link_count": 0, "insert_way_link_count": 0, "way_links_mode": "enabled"}

    change_ids = sorted(set(changed_way_ids), key=_id_sort_key)
    delete_count = _count_way_link_rows(base_conn, "main", change_ids)
    inserts = _fetch_way_link_payload_rows(base_conn, target_alias, change_ids)
    stats = {
        "delete_way_link_count": delete_count,
        "insert_way_link_count": len(inserts),
        "exact_way_link_touch_way_count": len(change_ids),
        "way_links_mode": "enabled",
    }
    return change_ids, inserts, stats


def _compute_exact_delta(
    base_db: Path,
    target_db: Path,
    parsed: DiffParseResult,
) -> Tuple[List[str], List[dict], List[str], List[dict], List[dict], List[dict], dict]:
    conn = sqlite3.connect(str(base_db))
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("ATTACH DATABASE ? AS targetdb", (str(target_db),))

        required = {"ways", "ways_rtree", "way_geom"}
        for alias in ("main", "targetdb"):
            rows = conn.execute(f"SELECT name FROM {alias}.sqlite_master WHERE type='table'").fetchall()
            present = {str(r[0]) for r in rows}
            missing = sorted(required - present)
            if missing:
                raise SystemExit(f"Invalid schema in {alias}. Missing table(s): {', '.join(missing)}")

        delete_ids, inserts, way_stats = _compute_exact_way_delta(conn, "targetdb")
        way_link_delete_ids, way_link_inserts, way_link_stats = _compute_exact_way_link_delta(conn, "targetdb", delete_ids)
        area_deletes, area_inserts, area_stats = _compute_exact_area_delta(conn, "targetdb")
    finally:
        conn.close()

    stats = {
        "mode": "exact_db_diff",
        "changed_way_count": len(parsed.ops_by_way),
        "ways_added": parsed.ways_added,
        "ways_removed": parsed.ways_removed,
        "ways_modified": parsed.ways_modified,
        "maxspeed_tag_events": parsed.maxspeed_tag_events,
        "maxspeed_tag_changes": parsed.maxspeed_tag_changes,
    }
    stats.update(way_stats)
    stats.update(way_link_stats)
    stats.update(area_stats)
    stats["skipped_insert_way_count"] = 0
    stats["skipped_non_drivable_way_count"] = 0
    stats["target_db"] = str(target_db)
    return delete_ids, inserts, way_link_delete_ids, way_link_inserts, area_deletes, area_inserts, stats


def _build_sql_patch(
    delete_ids: Sequence[str],
    inserts: Sequence[dict],
    way_link_delete_ids: Sequence[str],
    way_link_inserts: Sequence[dict],
    area_deletes: Sequence[dict],
    area_inserts: Sequence[dict],
    *,
    from_version: str,
    to_version: str,
    diff_file: Path,
    generation_mode: str,
) -> str:
    lines: List[str] = []
    lines.append("-- youspeed v3 delta patch")
    lines.append(f"-- from_version={from_version}")
    lines.append(f"-- to_version={to_version}")
    lines.append(f"-- source_diff={diff_file}")
    lines.append(f"-- generation_mode={generation_mode}")
    lines.append(f"-- generated_at_utc={_now_utc()}")
    lines.append("BEGIN IMMEDIATE;")
    lines.append("PRAGMA foreign_keys=OFF;")

    for chunk in _iter_chunks(sorted(set(way_link_delete_ids), key=_id_sort_key), 500):
        int_chunk = _coerce_way_link_ids(chunk)
        if not int_chunk:
            continue
        id_list = ",".join(str(v) for v in int_chunk)
        lines.append(f"DELETE FROM way_links WHERE way_id IN ({id_list});")
        lines.append(f"DELETE FROM way_links WHERE linked_way_id IN ({id_list});")

    for way_id in sorted(set(delete_ids), key=_id_sort_key):
        way_lit = _sql_literal(way_id)
        lines.append(f"DELETE FROM way_geom WHERE way_id={way_lit};")
        lines.append(f"DELETE FROM ways_rtree WHERE way_id={way_lit};")
        lines.append(f"DELETE FROM ways WHERE way_id={way_lit};")

    for ins in inserts:
        way_lit = _sql_literal(ins["way_id"])
        lines.append(
            "INSERT INTO ways("
            "way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, "
            "approx_heading_deg, service, tunnel, "
            "min_lon, min_lat, max_lon, max_lat"
            ") VALUES("
            f"{way_lit}, "
            f"{_sql_literal(ins['highway'])}, "
            f"{_sql_literal(ins['street_name'])}, "
            f"{_sql_literal(ins['ref'])}, "
            f"{_sql_literal(ins['maxspeed'])}, "
            f"{_sql_literal(ins['maxspeed_type'])}, "
            f"{_sql_literal(ins['source_maxspeed'])}, "
            f"{_sql_literal(ins['approx_heading_deg'])}, "
            f"{_sql_literal(ins['service'])}, "
            f"{_sql_literal(ins['tunnel'])}, "
            f"{_sql_literal(ins['min_lon'])}, "
            f"{_sql_literal(ins['min_lat'])}, "
            f"{_sql_literal(ins['max_lon'])}, "
            f"{_sql_literal(ins['max_lat'])}"
            ");"
        )
        lines.append(
            "INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat) "
            f"VALUES({way_lit}, {_sql_literal(ins['min_lon'])}, {_sql_literal(ins['max_lon'])}, "
            f"{_sql_literal(ins['min_lat'])}, {_sql_literal(ins['max_lat'])});"
        )
        lines.append(
            "INSERT INTO way_geom(way_id, points_json) "
            f"VALUES({way_lit}, {_sql_literal(ins['points_json'])});"
        )

    for ins in way_link_inserts:
        lines.append(
            "INSERT INTO way_links(way_id, linked_way_id, shared_ref, link_kind) "
            f"VALUES({int(ins['way_id'])}, {int(ins['linked_way_id'])}, "
            f"{_sql_literal(ins['shared_ref'])}, {_sql_literal(ins['link_kind'])});"
        )

    for item in area_deletes:
        row_id_lit = _sql_literal(int(item["row_id"]))
        area_id_lit = _sql_literal(str(item["area_id"]))
        lines.append(f"DELETE FROM areas_rtree WHERE row_id={row_id_lit};")
        lines.append(f"DELETE FROM areas WHERE area_id={area_id_lit};")

    for item in area_inserts:
        row_id_lit = _sql_literal(int(item["row_id"]))
        lines.append(
            "INSERT INTO areas("
            "row_id, area_id, geometry_type, name, place, boundary, admin_level, residential, "
            "points_json, min_lon, min_lat, max_lon, max_lat"
            ") VALUES("
            f"{row_id_lit}, "
            f"{_sql_literal(item['area_id'])}, "
            f"{_sql_literal(item['geometry_type'])}, "
            f"{_sql_literal(item['name'])}, "
            f"{_sql_literal(item['place'])}, "
            f"{_sql_literal(item['boundary'])}, "
            f"{_sql_literal(item['admin_level'])}, "
            f"{_sql_literal(item['residential'])}, "
            f"{_sql_literal(item['points_json'])}, "
            f"{_sql_literal(item['min_lon'])}, "
            f"{_sql_literal(item['min_lat'])}, "
            f"{_sql_literal(item['max_lon'])}, "
            f"{_sql_literal(item['max_lat'])}"
            ");"
        )
        lines.append(
            "INSERT INTO areas_rtree(row_id, min_lon, max_lon, min_lat, max_lat) "
            f"VALUES({row_id_lit}, {_sql_literal(item['min_lon'])}, {_sql_literal(item['max_lon'])}, "
            f"{_sql_literal(item['min_lat'])}, {_sql_literal(item['max_lat'])});"
        )

    lines.append("COMMIT;")
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build v3 SQL patch pack from daily OSM diff")
    parser.add_argument("--base-db", required=True, help="Path to v3 base DB")
    parser.add_argument("--target-db", default="", help="Optional path to rebuilt target DB for exact lossless patch mode")
    parser.add_argument("--diff-file", required=True, help="Path to daily diff (.osc or .osc.gz)")
    parser.add_argument("--region", default="germany")
    parser.add_argument("--from-version", required=True, help="Source bundle version")
    parser.add_argument("--to-version", required=True, help="Target bundle version")
    parser.add_argument("--out-dir", required=True, help="Output directory for delta manifest + SQL patch")
    parser.add_argument("--patch-file-name", default="v3_patch.sql")
    parser.add_argument(
        "--patch-compression",
        choices=["none", "zlib"],
        default="zlib",
        help="Compression for patch artifact payload (default: zlib)",
    )
    parser.add_argument("--manifest-name", default="v3_delta_manifest.json")
    parser.add_argument("--base-url", default="", help="Optional base URL prefix for patch URL")
    parser.add_argument("--github-owner", default="", help="GitHub owner/org for release asset URLs")
    parser.add_argument("--github-repo", default="", help="GitHub repo for release asset URLs")
    parser.add_argument("--github-release-tag", default="", help="GitHub release tag for asset URLs")
    parser.add_argument(
        "--github-asset-prefix",
        default="",
        help="Optional prefix for release asset names (for example: germany/2026-02-23/)",
    )
    parser.add_argument(
        "--validate-on-copy",
        action="store_true",
        help="Validate patch by applying it to a temporary copy of --base-db",
    )
    return parser.parse_args()


def _assert_target_equivalence(patched_db: Path, target_db: Path) -> None:
    conn = sqlite3.connect(":memory:")
    try:
        conn.execute("ATTACH DATABASE ? AS p", (str(patched_db),))
        conn.execute("ATTACH DATABASE ? AS t", (str(target_db),))

        way_extra = conn.execute(
            "SELECT COUNT(*) FROM p.ways pw LEFT JOIN t.ways tw USING(way_id) WHERE tw.way_id IS NULL"
        ).fetchone()[0]
        way_missing = conn.execute(
            "SELECT COUNT(*) FROM t.ways tw LEFT JOIN p.ways pw USING(way_id) WHERE pw.way_id IS NULL"
        ).fetchone()[0]
        way_attr_diff = conn.execute(
            """
            SELECT COUNT(*)
            FROM p.ways pw JOIN t.ways tw USING(way_id)
            WHERE
              COALESCE(pw.highway,'') != COALESCE(tw.highway,'') OR
              COALESCE(pw.street_name,'') != COALESCE(tw.street_name,'') OR
              COALESCE(pw.ref,'') != COALESCE(tw.ref,'') OR
              COALESCE(pw.maxspeed,'') != COALESCE(tw.maxspeed,'') OR
              COALESCE(pw.maxspeed_type,'') != COALESCE(tw.maxspeed_type,'') OR
              COALESCE(pw.source_maxspeed,'') != COALESCE(tw.source_maxspeed,'') OR
              ABS(COALESCE(pw.approx_heading_deg,0.0) - COALESCE(tw.approx_heading_deg,0.0)) > 1e-9 OR
              COALESCE(pw.service,'') != COALESCE(tw.service,'') OR
              COALESCE(pw.tunnel,'') != COALESCE(tw.tunnel,'') OR
              ABS(COALESCE(pw.min_lon,0.0) - COALESCE(tw.min_lon,0.0)) > 1e-12 OR
              ABS(COALESCE(pw.min_lat,0.0) - COALESCE(tw.min_lat,0.0)) > 1e-12 OR
              ABS(COALESCE(pw.max_lon,0.0) - COALESCE(tw.max_lon,0.0)) > 1e-12 OR
              ABS(COALESCE(pw.max_lat,0.0) - COALESCE(tw.max_lat,0.0)) > 1e-12
            """
        ).fetchone()[0]
        way_geom_diff = conn.execute(
            """
            SELECT COUNT(*)
            FROM p.way_geom pg JOIN t.way_geom tg USING(way_id)
            WHERE COALESCE(pg.points_json,'') != COALESCE(tg.points_json,'')
            """
        ).fetchone()[0]

        if any(v > 0 for v in (way_extra, way_missing, way_attr_diff, way_geom_diff)):
            raise SystemExit(
                "Patch drift against target DB "
                f"(ways extra={way_extra} missing={way_missing} attr_diff={way_attr_diff} geom_diff={way_geom_diff})"
            )

        has_way_links = _table_exists(conn, "p", "way_links") and _table_exists(conn, "t", "way_links")
        if has_way_links:
            way_link_extra = conn.execute(
                """
                SELECT COUNT(*)
                FROM p.way_links pl
                LEFT JOIN t.way_links tl
                  ON pl.way_id = tl.way_id
                 AND pl.linked_way_id = tl.linked_way_id
                WHERE tl.way_id IS NULL
                """
            ).fetchone()[0]
            way_link_missing = conn.execute(
                """
                SELECT COUNT(*)
                FROM t.way_links tl
                LEFT JOIN p.way_links pl
                  ON pl.way_id = tl.way_id
                 AND pl.linked_way_id = tl.linked_way_id
                WHERE pl.way_id IS NULL
                """
            ).fetchone()[0]
            way_link_attr_diff = conn.execute(
                """
                SELECT COUNT(*)
                FROM p.way_links pl
                JOIN t.way_links tl
                  ON pl.way_id = tl.way_id
                 AND pl.linked_way_id = tl.linked_way_id
                WHERE
                  COALESCE(pl.shared_ref,0) != COALESCE(tl.shared_ref,0) OR
                  COALESCE(pl.link_kind,'') != COALESCE(tl.link_kind,'')
                """
            ).fetchone()[0]
            if any(v > 0 for v in (way_link_extra, way_link_missing, way_link_attr_diff)):
                raise SystemExit(
                    "Patch drift against target DB "
                    f"(way_links extra={way_link_extra} missing={way_link_missing} attr_diff={way_link_attr_diff})"
                )

        has_areas = (
            _table_exists(conn, "p", "areas")
            and _table_exists(conn, "p", "areas_rtree")
            and _table_exists(conn, "t", "areas")
            and _table_exists(conn, "t", "areas_rtree")
        )
        if has_areas:
            area_extra = conn.execute(
                "SELECT COUNT(*) FROM p.areas pa LEFT JOIN t.areas ta ON pa.area_id = ta.area_id WHERE ta.area_id IS NULL"
            ).fetchone()[0]
            area_missing = conn.execute(
                "SELECT COUNT(*) FROM t.areas ta LEFT JOIN p.areas pa ON ta.area_id = pa.area_id WHERE pa.area_id IS NULL"
            ).fetchone()[0]
            area_attr_diff = conn.execute(
                """
                SELECT COUNT(*)
                FROM p.areas pa JOIN t.areas ta ON pa.area_id = ta.area_id
                WHERE
                  COALESCE(pa.geometry_type,'') != COALESCE(ta.geometry_type,'') OR
                  COALESCE(pa.name,'') != COALESCE(ta.name,'') OR
                  COALESCE(pa.place,'') != COALESCE(ta.place,'') OR
                  COALESCE(pa.boundary,'') != COALESCE(ta.boundary,'') OR
                  COALESCE(pa.admin_level,'') != COALESCE(ta.admin_level,'') OR
                  COALESCE(pa.residential,'') != COALESCE(ta.residential,'') OR
                  COALESCE(pa.points_json,'') != COALESCE(ta.points_json,'') OR
                  ABS(COALESCE(pa.min_lon,0.0) - COALESCE(ta.min_lon,0.0)) > 1e-12 OR
                  ABS(COALESCE(pa.min_lat,0.0) - COALESCE(ta.min_lat,0.0)) > 1e-12 OR
                  ABS(COALESCE(pa.max_lon,0.0) - COALESCE(ta.max_lon,0.0)) > 1e-12 OR
                  ABS(COALESCE(pa.max_lat,0.0) - COALESCE(ta.max_lat,0.0)) > 1e-12
                """
            ).fetchone()[0]

            if any(v > 0 for v in (area_extra, area_missing, area_attr_diff)):
                raise SystemExit(
                    "Patch drift against target DB "
                    f"(areas extra={area_extra} missing={area_missing} attr_diff={area_attr_diff})"
                )
    finally:
        conn.close()


def _validate_patch_sql(base_db: Path, patch_sql: str, *, target_db: Optional[Path]) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        sim = Path(tmp) / "sim.sqlite"
        shutil.copy2(base_db, sim)
        conn = sqlite3.connect(str(sim))
        try:
            conn.executescript(patch_sql)
            conn.execute("PRAGMA quick_check")
        finally:
            conn.close()

        if target_db is not None:
            _assert_target_equivalence(sim, target_db)


def main() -> int:
    args = parse_args()
    base_db = Path(args.base_db)
    diff_file = Path(args.diff_file)
    target_db = Path(args.target_db) if args.target_db.strip() else None

    if not base_db.exists():
        raise SystemExit(f"Missing base DB: {base_db}")
    if target_db is not None and not target_db.exists():
        raise SystemExit(f"Missing target DB: {target_db}")
    if not diff_file.exists():
        raise SystemExit(f"Missing diff file: {diff_file}")

    parsed = _parse_daily_diff(diff_file)

    if target_db is not None:
        delete_ids, inserts, way_link_delete_ids, way_link_inserts, area_deletes, area_inserts, stats = _compute_exact_delta(base_db, target_db, parsed)
        generation_mode = "exact_db_diff"
    else:
        conn = sqlite3.connect(str(base_db))
        conn.row_factory = sqlite3.Row
        try:
            required = {"ways", "ways_rtree", "way_geom"}
            rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
            present = {str(r[0]) for r in rows}
            missing = sorted(required - present)
            if missing:
                raise SystemExit(f"Invalid v3 DB schema. Missing table(s): {', '.join(missing)}")
            if _table_exists(conn, "main", "way_links"):
                raise SystemExit("Heuristic OSC mode does not support way_links; rebuild target DB and use --target-db")
            delete_ids, inserts, area_deletes, area_inserts, stats = _compute_heuristic_delta(conn, parsed)
        finally:
            conn.close()
        generation_mode = "heuristic_osc"
        way_link_delete_ids = []
        way_link_inserts = []

    patch_sql = _build_sql_patch(
        delete_ids=delete_ids,
        inserts=inserts,
        way_link_delete_ids=way_link_delete_ids,
        way_link_inserts=way_link_inserts,
        area_deletes=area_deletes,
        area_inserts=area_inserts,
        from_version=args.from_version,
        to_version=args.to_version,
        diff_file=diff_file,
        generation_mode=generation_mode,
    )

    if args.validate_on_copy:
        _validate_patch_sql(base_db, patch_sql, target_db=target_db)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    patch_file_name = args.patch_file_name
    if args.patch_compression == "zlib" and patch_file_name == "v3_patch.sql":
        patch_file_name = "v3_patch.sql.zlib"

    patch_path = out_dir / patch_file_name
    patch_payload = patch_sql.encode("utf-8")
    if args.patch_compression == "zlib":
        patch_payload = zlib.compress(patch_payload, level=9)
    patch_path.write_bytes(patch_payload)

    patch_sha = _sha256_path(patch_path)
    use_github_urls = bool(args.github_owner and args.github_repo and args.github_release_tag)
    asset_prefix = args.github_asset_prefix.strip("/")

    patch_url: Optional[str] = None
    if use_github_urls:
        asset_name = f"{asset_prefix}/{patch_file_name}" if asset_prefix else patch_file_name
        patch_url = _github_release_asset_url(args.github_owner, args.github_repo, args.github_release_tag, asset_name)
    elif args.base_url:
        patch_url = "/".join([args.base_url.rstrip("/"), patch_file_name.lstrip("/")])

    manifest = {
        "format": "youspeed.v3.delta.manifest",
        "schema_version": 1,
        "region": args.region,
        "from_bundle_version": args.from_version,
        "to_bundle_version": args.to_version,
        "created_at_utc": _now_utc(),
        "source_diff_file": str(diff_file),
        "generation_mode": generation_mode,
        "patch": {
            "file": patch_file_name,
            "bytes": patch_path.stat().st_size,
            "sha256": patch_sha,
            "url": patch_url,
            "compression": args.patch_compression,
        },
        "stats": stats,
    }
    manifest_path = out_dir / args.manifest_name
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"Wrote v3 delta pack: {out_dir}")
    print(f"Patch: {patch_path}")
    print(f"Patch compression: {args.patch_compression}")
    print(f"Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
