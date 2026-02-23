#!/usr/bin/env python3
"""Build v4 spatial DB (SQLite + RTree + tile mapping).

v4 combines:
- spatial indexing (RTree) like v3
- virtual tile partition metadata for fast local prefiltering
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from pathlib import Path
from typing import List, Tuple

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


def _try_load_spatialite(conn: sqlite3.Connection) -> str:
    backend = "sqlite_rtree"
    try:
        conn.enable_load_extension(True)
        for ext in ("mod_spatialite", "libspatialite", "spatialite"):
            try:
                conn.load_extension(ext)
                backend = f"mod_spatialite:{ext}"
                break
            except sqlite3.OperationalError:
                continue
    except Exception:
        pass
    finally:
        try:
            conn.enable_load_extension(False)
        except Exception:
            pass
    return backend


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build v4 SQLite/SpatiaLite DB with tile prefilter table")
    parser.add_argument("--v1-dist", required=True, help="Path to mapdata/dist/<region>")
    parser.add_argument("--out-db", required=True, help="Output SQLite database path")
    parser.add_argument("--tile-size-m", type=int, default=4096, help="Tile size in EPSG:3857 meters")
    parser.add_argument("--max-way-tiles", type=int, default=1024, help="Per-way tile fan-out cap before center fallback")
    parser.add_argument("--batch-size", type=int, default=20000, help="Insert batch size")
    parser.add_argument("--progress-every", type=int, default=250000, help="Progress logging interval")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.tile_size_m < 256:
        print("--tile-size-m must be >= 256", file=sys.stderr)
        return 1
    if args.max_way_tiles < 1:
        print("--max-way-tiles must be >= 1", file=sys.stderr)
        return 1
    if args.batch_size < 100:
        print("--batch-size must be >= 100", file=sys.stderr)
        return 1

    v1_dist = Path(args.v1_dist)
    out_db = Path(args.out_db)

    ways_meta = v1_dist / "ways.meta"
    ways_geom = v1_dist / "ways.geom"
    areas_idx = v1_dist / "areas.idx"
    for p in (ways_meta, ways_geom, areas_idx):
        if not p.exists():
            print(f"Missing required input: {p}", file=sys.stderr)
            return 1

    out_db.parent.mkdir(parents=True, exist_ok=True)
    if out_db.exists():
        out_db.unlink()

    conn = sqlite3.connect(str(out_db))
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("PRAGMA cache_size=-200000")

    backend = _try_load_spatialite(conn)
    print(f"Spatial backend: {backend}", file=sys.stderr)

    conn.executescript(
        """
        CREATE TABLE metadata (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL
        );

        CREATE TABLE ways (
          row_id INTEGER PRIMARY KEY,
          way_id TEXT NOT NULL UNIQUE,
          highway TEXT,
          maxspeed TEXT,
          maxspeed_type TEXT,
          source_maxspeed TEXT,
          zone_maxspeed TEXT,
          traffic_sign TEXT,
          approx_heading_deg REAL,
          min_lon REAL NOT NULL,
          min_lat REAL NOT NULL,
          max_lon REAL NOT NULL,
          max_lat REAL NOT NULL
        );

        CREATE VIRTUAL TABLE ways_rtree USING rtree(
          row_id,
          min_lon, max_lon,
          min_lat, max_lat
        );

        CREATE TABLE way_geom (
          row_id INTEGER PRIMARY KEY,
          way_id TEXT NOT NULL UNIQUE,
          points_json TEXT NOT NULL
        );

        CREATE TABLE way_tile (
          row_id INTEGER NOT NULL,
          tile_x INTEGER NOT NULL,
          tile_y INTEGER NOT NULL
        );

        CREATE TABLE areas (
          row_id INTEGER PRIMARY KEY,
          area_id TEXT NOT NULL UNIQUE,
          geometry_type TEXT,
          name TEXT,
          place TEXT,
          boundary TEXT,
          admin_level TEXT,
          min_lon REAL NOT NULL,
          min_lat REAL NOT NULL,
          max_lon REAL NOT NULL,
          max_lat REAL NOT NULL
        );

        CREATE VIRTUAL TABLE areas_rtree USING rtree(
          row_id,
          min_lon, max_lon,
          min_lat, max_lat
        );
        """
    )

    conn.executemany(
        "INSERT INTO metadata(key, value) VALUES(?, ?)",
        [
            ("schema_version", "1"),
            ("backend", backend),
            ("source_v1_dist", str(v1_dist)),
            ("tile_size_m", str(args.tile_size_m)),
            ("max_way_tiles", str(args.max_way_tiles)),
        ],
    )

    ways_batch: List[Tuple] = []
    ways_rtree_batch: List[Tuple] = []
    geom_batch: List[Tuple] = []
    way_tile_batch: List[Tuple] = []
    row_id = 0
    way_tile_rows = 0
    way_tile_fallback_rows = 0

    with ways_meta.open("r", encoding="utf-8") as fm, ways_geom.open("r", encoding="utf-8") as fg:
        while True:
            lm = fm.readline()
            lg = fg.readline()
            if not lm and not lg:
                break
            if not lm or not lg:
                print("ways.meta / ways.geom line count mismatch", file=sys.stderr)
                return 1
            lm = lm.strip()
            lg = lg.strip()
            if not lm or not lg:
                continue

            meta = json.loads(lm)
            geom = json.loads(lg)
            if meta.get("way_id") != geom.get("way_id"):
                print(
                    f"way_id mismatch: meta={meta.get('way_id')} geom={geom.get('way_id')}",
                    file=sys.stderr,
                )
                return 1

            row_id += 1
            way_id = str(meta["way_id"])
            points = geom.get("points")
            if not isinstance(points, list):
                points = []

            min_lon = float(meta["min_lon"])
            min_lat = float(meta["min_lat"])
            max_lon = float(meta["max_lon"])
            max_lat = float(meta["max_lat"])

            ways_batch.append(
                (
                    row_id,
                    way_id,
                    meta.get("highway"),
                    meta.get("maxspeed"),
                    meta.get("maxspeed_type"),
                    meta.get("source_maxspeed"),
                    meta.get("zone_maxspeed"),
                    meta.get("traffic_sign"),
                    meta.get("approx_heading_deg"),
                    min_lon,
                    min_lat,
                    max_lon,
                    max_lat,
                )
            )
            ways_rtree_batch.append((row_id, min_lon, max_lon, min_lat, max_lat))
            geom_batch.append((row_id, way_id, json.dumps(points, separators=(",", ":"))))

            tx0, tx1, ty0, ty1 = _tile_range_for_bbox(min_lon, min_lat, max_lon, max_lat, args.tile_size_m)
            tile_count = (tx1 - tx0 + 1) * (ty1 - ty0 + 1)
            if tile_count > args.max_way_tiles:
                center_lon = (min_lon + max_lon) / 2.0
                center_lat = (min_lat + max_lat) / 2.0
                tx, ty = _tile_for_lon_lat(center_lon, center_lat, args.tile_size_m)
                way_tile_batch.append((row_id, tx, ty))
                way_tile_rows += 1
                way_tile_fallback_rows += 1
            else:
                for tx in range(tx0, tx1 + 1):
                    for ty in range(ty0, ty1 + 1):
                        way_tile_batch.append((row_id, tx, ty))
                        way_tile_rows += 1

            if len(ways_batch) >= args.batch_size:
                conn.executemany(
                    """
                    INSERT INTO ways(
                      row_id, way_id, highway, maxspeed, maxspeed_type, source_maxspeed,
                      zone_maxspeed, traffic_sign, approx_heading_deg,
                      min_lon, min_lat, max_lon, max_lat
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ways_batch,
                )
                conn.executemany(
                    "INSERT INTO ways_rtree(row_id, min_lon, max_lon, min_lat, max_lat) VALUES(?, ?, ?, ?, ?)",
                    ways_rtree_batch,
                )
                conn.executemany(
                    "INSERT INTO way_geom(row_id, way_id, points_json) VALUES(?, ?, ?)",
                    geom_batch,
                )
                conn.executemany(
                    "INSERT INTO way_tile(row_id, tile_x, tile_y) VALUES(?, ?, ?)",
                    way_tile_batch,
                )
                conn.commit()
                ways_batch.clear()
                ways_rtree_batch.clear()
                geom_batch.clear()
                way_tile_batch.clear()

            if row_id % args.progress_every == 0:
                print(f"  ways inserted: {row_id}", file=sys.stderr)

    if ways_batch:
        conn.executemany(
            """
            INSERT INTO ways(
              row_id, way_id, highway, maxspeed, maxspeed_type, source_maxspeed,
              zone_maxspeed, traffic_sign, approx_heading_deg,
              min_lon, min_lat, max_lon, max_lat
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ways_batch,
        )
        conn.executemany(
            "INSERT INTO ways_rtree(row_id, min_lon, max_lon, min_lat, max_lat) VALUES(?, ?, ?, ?, ?)",
            ways_rtree_batch,
        )
        conn.executemany(
            "INSERT INTO way_geom(row_id, way_id, points_json) VALUES(?, ?, ?)",
            geom_batch,
        )
        conn.executemany(
            "INSERT INTO way_tile(row_id, tile_x, tile_y) VALUES(?, ?, ?)",
            way_tile_batch,
        )
        conn.commit()

    print(f"Ways done: {row_id}", file=sys.stderr)
    print(f"Way-tile rows: {way_tile_rows} (center fallback={way_tile_fallback_rows})", file=sys.stderr)

    areas_payload = json.loads(areas_idx.read_text(encoding="utf-8"))
    areas = areas_payload.get("areas", [])
    if not isinstance(areas, list):
        print("areas.idx format invalid: areas must be array", file=sys.stderr)
        return 1

    area_rows = []
    area_rtree_rows = []
    for i, area in enumerate(areas, start=1):
        area_rows.append(
            (
                i,
                str(area.get("area_id", "")),
                area.get("geometry_type"),
                area.get("name"),
                area.get("place"),
                area.get("boundary"),
                area.get("admin_level"),
                float(area["min_lon"]),
                float(area["min_lat"]),
                float(area["max_lon"]),
                float(area["max_lat"]),
            )
        )
        area_rtree_rows.append(
            (
                i,
                float(area["min_lon"]),
                float(area["max_lon"]),
                float(area["min_lat"]),
                float(area["max_lat"]),
            )
        )
        if len(area_rows) >= args.batch_size:
            conn.executemany(
                """
                INSERT INTO areas(
                  row_id, area_id, geometry_type, name, place, boundary, admin_level,
                  min_lon, min_lat, max_lon, max_lat
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                area_rows,
            )
            conn.executemany(
                "INSERT INTO areas_rtree(row_id, min_lon, max_lon, min_lat, max_lat) VALUES(?, ?, ?, ?, ?)",
                area_rtree_rows,
            )
            conn.commit()
            area_rows.clear()
            area_rtree_rows.clear()

    if area_rows:
        conn.executemany(
            """
            INSERT INTO areas(
              row_id, area_id, geometry_type, name, place, boundary, admin_level,
              min_lon, min_lat, max_lon, max_lat
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            area_rows,
        )
        conn.executemany(
            "INSERT INTO areas_rtree(row_id, min_lon, max_lon, min_lat, max_lat) VALUES(?, ?, ?, ?, ?)",
            area_rtree_rows,
        )
        conn.commit()

    conn.execute("CREATE INDEX idx_ways_way_id ON ways(way_id)")
    conn.execute("CREATE INDEX idx_way_tile_xy ON way_tile(tile_x, tile_y, row_id)")
    conn.execute("CREATE INDEX idx_way_tile_row ON way_tile(row_id)")
    conn.execute("CREATE INDEX idx_areas_place_admin ON areas(place, admin_level, boundary)")
    conn.commit()
    conn.close()

    print(f"Wrote v4 DB: {out_db}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
