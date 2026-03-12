#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sqlite3
import tempfile
import zlib
from pathlib import Path

FIXTURE_WINDOWS = (
    {
        "name": "three_way_gate",
        "min_lat": 48.7640,
        "max_lat": 48.7725,
        "min_lon": 8.3310,
        "max_lon": 8.3405,
    },
    {
        "name": "loffenau_hop",
        "min_lat": 48.7655,
        "max_lat": 48.7735,
        "min_lon": 8.3690,
        "max_lon": 8.3785,
    },
)

REQUIRED_WAY_IDS = {
    "1037006038",
    "16634524",
    "209270485",
    "16654539",
    "206811642",
    "723188219",
}

SQL_VAR_LIMIT = 900


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build plain-table replay DB for Android instrumented matcher regressions.")
    parser.add_argument("--source-zlib", required=True, help="Path to compressed Karlsruhe seed SQLite asset.")
    parser.add_argument("--output", required=True, help="Path to output replay SQLite DB.")
    parser.add_argument("--logs-root", help="Optional inspector/logs root to derive longer replay windows from.")
    parser.add_argument(
        "--window-padding-m",
        type=float,
        default=200.0,
        help="Padding around each derived log bbox in meters (default: 200).",
    )
    return parser.parse_args()


def inflate_zlib_sqlite(source_zlib: Path, destination_sqlite: Path) -> None:
    decompressor = zlib.decompressobj()
    with source_zlib.open("rb") as source, destination_sqlite.open("wb") as destination:
        while True:
            chunk = source.read(1024 * 1024)
            if not chunk:
                break
            destination.write(decompressor.decompress(chunk))
        destination.write(decompressor.flush())


def create_output_schema(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE ways (
          way_id TEXT PRIMARY KEY,
          highway TEXT,
          street_name TEXT,
          ref TEXT,
          maxspeed TEXT,
          maxspeed_type TEXT,
          source_maxspeed TEXT,
          approx_heading_deg REAL,
          service TEXT,
          tunnel TEXT,
          min_lon REAL NOT NULL,
          min_lat REAL NOT NULL,
          max_lon REAL NOT NULL,
          max_lat REAL NOT NULL
        );
        CREATE TABLE ways_rtree (
          way_id TEXT NOT NULL,
          min_lon REAL NOT NULL,
          max_lon REAL NOT NULL,
          min_lat REAL NOT NULL,
          max_lat REAL NOT NULL
        );
        CREATE TABLE way_geom (
          way_id TEXT PRIMARY KEY,
          points_json TEXT NOT NULL
        );
        CREATE TABLE way_links (
          way_id TEXT NOT NULL,
          linked_way_id TEXT NOT NULL,
          shared_ref INTEGER NOT NULL DEFAULT 0,
          shared_node_key TEXT,
          PRIMARY KEY(way_id, linked_way_id, shared_node_key)
        );
        CREATE TABLE corridor_progress (
          corridor_kind TEXT NOT NULL,
          corridor_id INTEGER NOT NULL,
          side_node_key TEXT NOT NULL,
          way_id TEXT NOT NULL,
          start_depth_m REAL NOT NULL,
          end_depth_m REAL NOT NULL,
          start_depth_nodes INTEGER NOT NULL,
          end_depth_nodes INTEGER NOT NULL,
          corridor_span_m REAL NOT NULL,
          corridor_span_nodes INTEGER NOT NULL,
          PRIMARY KEY(corridor_kind, corridor_id, side_node_key, way_id)
        );
        CREATE TABLE areas (
          row_id INTEGER PRIMARY KEY,
          area_id TEXT NOT NULL UNIQUE,
          geometry_type TEXT,
          name TEXT,
          place TEXT,
          boundary TEXT,
          admin_level TEXT,
          residential TEXT,
          points_json TEXT,
          min_lon REAL NOT NULL,
          min_lat REAL NOT NULL,
          max_lon REAL NOT NULL,
          max_lat REAL NOT NULL
        );
        CREATE TABLE areas_rtree (
          row_id INTEGER NOT NULL,
          min_lon REAL NOT NULL,
          max_lon REAL NOT NULL,
          min_lat REAL NOT NULL,
          max_lat REAL NOT NULL
        );
        """
    )


def iter_drive_match_logs(logs_root: Path) -> list[Path]:
    return sorted(
        path
        for path in logs_root.rglob("*.ndjson")
        if path.is_file() and "drive_match_log" in path.name
    )


def load_windows_from_logs(logs_root: Path, padding_m: float) -> list[dict[str, float | str]]:
    files = iter_drive_match_logs(logs_root)
    if not files:
        raise SystemExit(f"No drive_match_log ndjson files found under {logs_root}")
    windows: list[dict[str, float | str]] = []
    for path in files:
        bbox = compute_log_bbox(path)
        if bbox is None:
            continue
        min_lat, max_lat, min_lon, max_lon = bbox
        center_lat = (min_lat + max_lat) / 2.0
        lat_pad = padding_m / 111_132.0
        cos_lat = max(0.173648, abs(math.cos(math.radians(center_lat))))
        lon_pad = padding_m / (111_320.0 * cos_lat)
        windows.append(
            {
                "name": path.relative_to(logs_root).as_posix(),
                "min_lat": min_lat - lat_pad,
                "max_lat": max_lat + lat_pad,
                "min_lon": min_lon - lon_pad,
                "max_lon": max_lon + lon_pad,
            }
        )
    return windows


def compute_log_bbox(path: Path) -> tuple[float, float, float, float] | None:
    min_lat = math.inf
    max_lat = -math.inf
    min_lon = math.inf
    max_lon = -math.inf
    with path.open() as handle:
        for raw_line in handle:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            payload = json.loads(raw_line)
            lat = float(payload["lat"])
            lon = float(payload["lon"])
            min_lat = min(min_lat, lat)
            max_lat = max(max_lat, lat)
            min_lon = min(min_lon, lon)
            max_lon = max(max_lon, lon)
    if not math.isfinite(min_lat):
        return None
    return min_lat, max_lat, min_lon, max_lon


def resolve_windows(logs_root: Path | None, padding_m: float) -> list[dict[str, float | str]]:
    windows = [dict(window) for window in FIXTURE_WINDOWS]
    if logs_root is not None:
        windows.extend(load_windows_from_logs(logs_root, padding_m))
    return windows


def chunked(values: set[str] | list[str], chunk_size: int) -> list[list[str]]:
    ordered = sorted(values)
    return [ordered[index : index + chunk_size] for index in range(0, len(ordered), chunk_size)]


def fetch_initial_way_ids(source: sqlite3.Connection, windows: list[dict[str, float | str]]) -> set[str]:
    selected: set[str] = set(REQUIRED_WAY_IDS)
    query = """
        SELECT DISTINCT CAST(way_id AS TEXT)
        FROM ways
        WHERE min_lon <= ? AND max_lon >= ?
          AND min_lat <= ? AND max_lat >= ?
    """
    for window in windows:
        rows = source.execute(
            query,
            (window["max_lon"], window["min_lon"], window["max_lat"], window["min_lat"]),
        ).fetchall()
        selected.update(row[0] for row in rows if row[0])
    return selected


def expand_way_ids_with_links(source: sqlite3.Connection, way_ids: set[str]) -> set[str]:
    if not way_ids:
        return set()
    expanded = set(way_ids)
    for chunk in chunked(way_ids, SQL_VAR_LIMIT // 2):
        placeholders = ",".join("?" for _ in chunk)
        rows = source.execute(
            f"""
            SELECT CAST(way_id AS TEXT), CAST(linked_way_id AS TEXT)
            FROM way_links
            WHERE CAST(way_id AS TEXT) IN ({placeholders})
               OR CAST(linked_way_id AS TEXT) IN ({placeholders})
            """,
            tuple(chunk) + tuple(chunk),
        ).fetchall()
        for way_id, linked_way_id in rows:
            if way_id:
                expanded.add(way_id)
            if linked_way_id:
                expanded.add(linked_way_id)
    return expanded


def copy_way_rows(source: sqlite3.Connection, target: sqlite3.Connection, way_ids: set[str]) -> int:
    total = 0
    for chunk in chunked(way_ids, SQL_VAR_LIMIT):
        placeholders = ",".join("?" for _ in chunk)
        rows = source.execute(
            f"""
            SELECT
              CAST(way_id AS TEXT),
              highway,
              street_name,
              ref,
              maxspeed,
              maxspeed_type,
              source_maxspeed,
              approx_heading_deg,
              service,
              tunnel,
              min_lon,
              min_lat,
              max_lon,
              max_lat
            FROM ways
            WHERE CAST(way_id AS TEXT) IN ({placeholders})
            """,
            tuple(chunk),
        ).fetchall()
        target.executemany(
            """
            INSERT INTO ways (
              way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed,
              approx_heading_deg, service, tunnel, min_lon, min_lat, max_lon, max_lat
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        target.executemany(
            """
            INSERT INTO ways_rtree (way_id, min_lon, max_lon, min_lat, max_lat)
            VALUES (?, ?, ?, ?, ?)
            """,
            [(row[0], row[10], row[12], row[11], row[13]) for row in rows],
        )
        total += len(rows)
    return total


def copy_way_geom_rows(source: sqlite3.Connection, target: sqlite3.Connection, way_ids: set[str]) -> int:
    if not way_ids:
        return 0
    total = 0
    for chunk in chunked(way_ids, SQL_VAR_LIMIT):
        placeholders = ",".join("?" for _ in chunk)
        rows = source.execute(
            f"""
            SELECT CAST(way_id AS TEXT), points_json
            FROM way_geom
            WHERE CAST(way_id AS TEXT) IN ({placeholders})
            """,
            tuple(chunk),
        ).fetchall()
        target.executemany("INSERT INTO way_geom (way_id, points_json) VALUES (?, ?)", rows)
        total += len(rows)
    return total


def copy_way_links_rows(source: sqlite3.Connection, target: sqlite3.Connection, way_ids: set[str]) -> int:
    if not way_ids:
        return 0
    total = 0
    seen: set[tuple[str, str, int, str | None]] = set()
    way_id_lookup = set(way_ids)
    for chunk in chunked(way_ids, SQL_VAR_LIMIT // 2):
        placeholders = ",".join("?" for _ in chunk)
        rows = source.execute(
            f"""
            SELECT
              CAST(way_id AS TEXT),
              CAST(linked_way_id AS TEXT),
              shared_ref,
              shared_node_key
            FROM way_links
            WHERE CAST(way_id AS TEXT) IN ({placeholders})
               OR CAST(linked_way_id AS TEXT) IN ({placeholders})
            """,
            tuple(chunk) + tuple(chunk),
        ).fetchall()
        filtered_rows = []
        for row in rows:
            way_id = row[0]
            linked_way_id = row[1]
            if way_id not in way_id_lookup or linked_way_id not in way_id_lookup:
                continue
            dedupe_key = (way_id, linked_way_id, row[2], row[3])
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            filtered_rows.append(row)
        target.executemany(
            "INSERT OR IGNORE INTO way_links (way_id, linked_way_id, shared_ref, shared_node_key) VALUES (?, ?, ?, ?)",
            filtered_rows,
        )
        total += len(filtered_rows)
    return total


def copy_corridor_progress_rows(source: sqlite3.Connection, target: sqlite3.Connection, way_ids: set[str]) -> int:
    if not way_ids:
        return 0
    total = 0
    for chunk in chunked(way_ids, SQL_VAR_LIMIT):
        placeholders = ",".join("?" for _ in chunk)
        rows = source.execute(
            f"""
            SELECT
              corridor_kind,
              corridor_id,
              side_node_key,
              CAST(way_id AS TEXT),
              start_depth_m,
              end_depth_m,
              start_depth_nodes,
              end_depth_nodes,
              corridor_span_m,
              corridor_span_nodes
            FROM corridor_progress
            WHERE CAST(way_id AS TEXT) IN ({placeholders})
            """,
            tuple(chunk),
        ).fetchall()
        target.executemany(
            """
            INSERT INTO corridor_progress (
              corridor_kind, corridor_id, side_node_key, way_id, start_depth_m, end_depth_m,
              start_depth_nodes, end_depth_nodes, corridor_span_m, corridor_span_nodes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            rows,
        )
        total += len(rows)
    return total


def copy_area_rows(source: sqlite3.Connection, target: sqlite3.Connection, windows: list[dict[str, float | str]]) -> int:
    seen: dict[int, tuple] = {}
    query = """
        SELECT
          row_id,
          area_id,
          geometry_type,
          name,
          place,
          boundary,
          admin_level,
          residential,
          points_json,
          min_lon,
          min_lat,
          max_lon,
          max_lat
        FROM areas
        WHERE min_lon <= ? AND max_lon >= ?
          AND min_lat <= ? AND max_lat >= ?
    """
    for window in windows:
        rows = source.execute(
            query,
            (window["max_lon"], window["min_lon"], window["max_lat"], window["min_lat"]),
        ).fetchall()
        for row in rows:
            seen[int(row[0])] = row
    ordered_rows = list(seen.values())
    target.executemany(
        """
        INSERT INTO areas (
          row_id, area_id, geometry_type, name, place, boundary, admin_level,
          residential, points_json, min_lon, min_lat, max_lon, max_lat
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        ordered_rows,
    )
    target.executemany(
        "INSERT INTO areas_rtree (row_id, min_lon, max_lon, min_lat, max_lat) VALUES (?, ?, ?, ?, ?)",
        [(row[0], row[9], row[11], row[10], row[12]) for row in ordered_rows],
    )
    return len(ordered_rows)


def main() -> None:
    args = parse_args()
    source_zlib = Path(args.source_zlib).resolve()
    output_path = Path(args.output).resolve()
    logs_root = Path(args.logs_root).resolve() if args.logs_root else None
    windows = resolve_windows(logs_root, args.window_padding_m)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if output_path.exists():
        output_path.unlink()

    with tempfile.TemporaryDirectory(prefix="youspeed-replay-db-") as temp_dir:
        inflated_source = Path(temp_dir) / "source.sqlite"
        inflate_zlib_sqlite(source_zlib, inflated_source)

        source_conn = sqlite3.connect(str(inflated_source))
        target_conn = sqlite3.connect(str(output_path))
        try:
            create_output_schema(target_conn)
            way_ids = fetch_initial_way_ids(source_conn, windows)
            way_ids = expand_way_ids_with_links(source_conn, way_ids)
            way_count = copy_way_rows(source_conn, target_conn, way_ids)
            geom_count = copy_way_geom_rows(source_conn, target_conn, way_ids)
            link_count = copy_way_links_rows(source_conn, target_conn, way_ids)
            corridor_count = copy_corridor_progress_rows(source_conn, target_conn, way_ids)
            area_count = copy_area_rows(source_conn, target_conn, windows)
            target_conn.commit()
        finally:
            source_conn.close()
            target_conn.close()

    print(
        "built replay db",
        f"output={output_path}",
        f"windows={len(windows)}",
        f"ways={way_count}",
        f"way_geom={geom_count}",
        f"way_links={link_count}",
        f"corridor_progress={corridor_count}",
        f"areas={area_count}",
    )


if __name__ == "__main__":
    main()
