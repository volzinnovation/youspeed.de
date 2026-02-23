#!/usr/bin/env python3
"""Build a v3 incremental SQL patch pack from a daily OSM diff."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import sqlite3
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence, Tuple


MAXSPEED_KEYS = {"maxspeed", "zone:maxspeed", "maxspeed:type", "source:maxspeed", "max:speed"}


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


def _build_sql_patch(
    delete_ids: Sequence[str],
    inserts: Sequence[dict],
    *,
    from_version: str,
    to_version: str,
    diff_file: Path,
) -> str:
    lines: List[str] = []
    lines.append("-- youspeed v3 delta patch")
    lines.append(f"-- from_version={from_version}")
    lines.append(f"-- to_version={to_version}")
    lines.append(f"-- source_diff={diff_file}")
    lines.append(f"-- generated_at_utc={_now_utc()}")
    lines.append("BEGIN IMMEDIATE;")
    lines.append("PRAGMA foreign_keys=OFF;")

    for way_id in sorted(set(delete_ids)):
        way_lit = _sql_literal(way_id)
        lines.append(f"DELETE FROM way_geom WHERE row_id IN (SELECT row_id FROM ways WHERE way_id={way_lit});")
        lines.append(f"DELETE FROM ways_rtree WHERE row_id IN (SELECT row_id FROM ways WHERE way_id={way_lit});")
        lines.append(f"DELETE FROM ways WHERE way_id={way_lit};")

    for ins in inserts:
        way_lit = _sql_literal(ins["way_id"])
        lines.append(
            "INSERT INTO ways("
            "way_id, highway, maxspeed, maxspeed_type, source_maxspeed, "
            "zone_maxspeed, traffic_sign, approx_heading_deg, "
            "min_lon, min_lat, max_lon, max_lat"
            ") VALUES("
            f"{way_lit}, "
            f"{_sql_literal(ins['highway'])}, "
            f"{_sql_literal(ins['maxspeed'])}, "
            f"{_sql_literal(ins['maxspeed_type'])}, "
            f"{_sql_literal(ins['source_maxspeed'])}, "
            f"{_sql_literal(ins['zone_maxspeed'])}, "
            f"{_sql_literal(ins['traffic_sign'])}, "
            f"{_sql_literal(ins['approx_heading_deg'])}, "
            f"{_sql_literal(ins['min_lon'])}, "
            f"{_sql_literal(ins['min_lat'])}, "
            f"{_sql_literal(ins['max_lon'])}, "
            f"{_sql_literal(ins['max_lat'])}"
            ");"
        )
        lines.append(
            "INSERT INTO ways_rtree(row_id, min_lon, max_lon, min_lat, max_lat) "
            "VALUES(("
            f"SELECT row_id FROM ways WHERE way_id={way_lit}"
            f"), {_sql_literal(ins['min_lon'])}, {_sql_literal(ins['max_lon'])}, "
            f"{_sql_literal(ins['min_lat'])}, {_sql_literal(ins['max_lat'])});"
        )
        lines.append(
            "INSERT INTO way_geom(row_id, way_id, points_json) "
            "VALUES(("
            f"SELECT row_id FROM ways WHERE way_id={way_lit}"
            f"), {way_lit}, {_sql_literal(ins['points_json'])});"
        )

    lines.append("COMMIT;")
    lines.append("")
    return "\n".join(lines)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build v3 SQL patch pack from daily OSM diff")
    parser.add_argument("--base-db", required=True, help="Path to v3 base DB (for existing-value fallback)")
    parser.add_argument("--diff-file", required=True, help="Path to daily diff (.osc or .osc.gz)")
    parser.add_argument("--region", default="germany")
    parser.add_argument("--from-version", required=True, help="Source bundle version")
    parser.add_argument("--to-version", required=True, help="Target bundle version")
    parser.add_argument("--out-dir", required=True, help="Output directory for delta manifest + SQL patch")
    parser.add_argument("--patch-file-name", default="v3_patch.sql")
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


def _validate_patch_sql(base_db: Path, patch_sql: str) -> None:
    import tempfile
    import shutil

    with tempfile.TemporaryDirectory() as tmp:
        sim = Path(tmp) / "sim.sqlite"
        shutil.copy2(base_db, sim)
        conn = sqlite3.connect(str(sim))
        try:
            conn.executescript(patch_sql)
            conn.execute("PRAGMA quick_check")
        finally:
            conn.close()


def main() -> int:
    args = parse_args()
    base_db = Path(args.base_db)
    diff_file = Path(args.diff_file)
    if not base_db.exists():
        raise SystemExit(f"Missing base DB: {base_db}")
    if not diff_file.exists():
        raise SystemExit(f"Missing diff file: {diff_file}")

    conn = sqlite3.connect(str(base_db))
    conn.row_factory = sqlite3.Row
    try:
        required = {"ways", "ways_rtree", "way_geom"}
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        present = {str(r[0]) for r in rows}
        missing = sorted(required - present)
        if missing:
            raise SystemExit(f"Invalid v3 DB schema. Missing table(s): {', '.join(missing)}")

        parsed = _parse_daily_diff(diff_file)
        changed_ids = sorted(parsed.ops_by_way.keys())
        existing_rows = _fetch_existing_rows(conn, changed_ids)
    finally:
        conn.close()

    delete_ids: List[str] = []
    inserts: List[dict] = []
    skipped_inserts = 0

    for way_id, op in parsed.ops_by_way.items():
        existing = existing_rows.get(way_id)
        if op.action in {"delete", "modify"}:
            delete_ids.append(way_id)
        if op.action in {"create", "modify"}:
            payload = _build_insert_payload(way_id, op, existing, parsed.node_coords)
            if payload is None:
                skipped_inserts += 1
            else:
                if op.action == "create" and existing is not None and way_id not in delete_ids:
                    skipped_inserts += 1
                else:
                    inserts.append(payload)

    patch_sql = _build_sql_patch(
        delete_ids=delete_ids,
        inserts=inserts,
        from_version=args.from_version,
        to_version=args.to_version,
        diff_file=diff_file,
    )

    if args.validate_on_copy:
        _validate_patch_sql(base_db, patch_sql)

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    patch_path = out_dir / args.patch_file_name
    patch_path.write_text(patch_sql, encoding="utf-8")

    patch_sha = _sha256_path(patch_path)
    use_github_urls = bool(args.github_owner and args.github_repo and args.github_release_tag)
    asset_prefix = args.github_asset_prefix.strip("/")

    patch_url: Optional[str] = None
    if use_github_urls:
        asset_name = f"{asset_prefix}/{args.patch_file_name}" if asset_prefix else args.patch_file_name
        patch_url = _github_release_asset_url(args.github_owner, args.github_repo, args.github_release_tag, asset_name)
    elif args.base_url:
        patch_url = "/".join([args.base_url.rstrip("/"), args.patch_file_name.lstrip("/")])

    manifest = {
        "format": "youspeed.v3.delta.manifest",
        "schema_version": 1,
        "region": args.region,
        "from_bundle_version": args.from_version,
        "to_bundle_version": args.to_version,
        "created_at_utc": _now_utc(),
        "source_diff_file": str(diff_file),
        "patch": {
            "file": args.patch_file_name,
            "bytes": patch_path.stat().st_size,
            "sha256": patch_sha,
            "url": patch_url,
        },
        "stats": {
            "changed_way_count": len(parsed.ops_by_way),
            "ways_added": parsed.ways_added,
            "ways_removed": parsed.ways_removed,
            "ways_modified": parsed.ways_modified,
            "maxspeed_tag_events": parsed.maxspeed_tag_events,
            "maxspeed_tag_changes": parsed.maxspeed_tag_changes,
            "delete_way_count": len(set(delete_ids)),
            "insert_way_count": len(inserts),
            "skipped_insert_way_count": skipped_inserts,
        },
    }
    manifest_path = out_dir / args.manifest_name
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"Wrote v3 delta pack: {out_dir}")
    print(f"Patch: {patch_path}")
    print(f"Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
