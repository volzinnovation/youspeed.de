#!/usr/bin/env python3
"""Build v3 spatial index database (SQLite + RTree, optional SpatiaLite extension).

Inputs:
- v1 dist artifacts: ways.meta, ways.geom, areas.idx

Output:
- speeds_v3.sqlite
"""

from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from pathlib import Path
from typing import Iterator, List, Optional, Tuple

FALSE_TAG_VALUES = {"", "0", "false", "no", "off", "none"}


def _iter_jsonl(path: Path) -> Iterator[dict]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


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
    parser = argparse.ArgumentParser(description="Build v3 SQLite/SpatiaLite-style speed map DB")
    parser.add_argument("--v1-dist", required=True, help="Path to mapdata/dist/<region>")
    parser.add_argument("--out-db", required=True, help="Output SQLite database path")
    parser.add_argument("--batch-size", type=int, default=20000, help="Insert batch size (default: 20000)")
    parser.add_argument("--progress-every", type=int, default=250000, help="Progress logging interval")
    return parser.parse_args()


def _tag_truthy(raw: object) -> bool:
    if raw is None:
        return False
    value = str(raw).strip().lower()
    if value in FALSE_TAG_VALUES:
        return False
    return True


def _parse_numeric_tag(raw: object) -> Optional[float]:
    if raw is None:
        return None
    try:
        return float(str(raw).strip())
    except (TypeError, ValueError):
        return None


def _is_tunnel_like_way(meta: dict) -> bool:
    if _tag_truthy(meta.get("tunnel")):
        return True
    location = str(meta.get("location") or "").strip().lower()
    if location in {"underground", "tunnel"}:
        return True
    layer = _parse_numeric_tag(meta.get("layer"))
    if layer is not None and layer < 0:
        return True
    level = _parse_numeric_tag(meta.get("level"))
    if level is not None and level < 0:
        return True
    return False


def main() -> int:
    args = parse_args()
    v1_dist = Path(args.v1_dist)
    out_db = Path(args.out_db)
    if args.batch_size < 100:
        print("--batch-size must be >= 100", file=sys.stderr)
        return 1

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
          way_id INTEGER NOT NULL UNIQUE,
          highway TEXT,
          street_name TEXT,
          ref TEXT,
          maxspeed TEXT,
          maxspeed_type TEXT,
          source_maxspeed TEXT,
          approx_heading_deg REAL,
          service TEXT,
          tunnel TEXT,
          bridge TEXT,
          covered TEXT,
          location TEXT,
          layer TEXT,
          level TEXT,
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

        CREATE TABLE tunnel_portal (
          row_id INTEGER PRIMARY KEY,
          way_row_id INTEGER NOT NULL,
          way_id INTEGER NOT NULL,
          portal_index INTEGER NOT NULL,
          lon REAL NOT NULL,
          lat REAL NOT NULL,
          tunnel TEXT,
          location TEXT,
          layer REAL,
          level REAL
        );

        CREATE VIRTUAL TABLE tunnel_portal_rtree USING rtree(
          row_id,
          min_lon, max_lon,
          min_lat, max_lat
        );

        CREATE TABLE way_geom (
          row_id INTEGER PRIMARY KEY,
          points_json TEXT NOT NULL
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
        ],
    )

    ways_batch: List[Tuple] = []
    ways_rtree_batch: List[Tuple] = []
    geom_batch: List[Tuple] = []
    tunnel_portal_batch: List[Tuple] = []
    tunnel_portal_rtree_batch: List[Tuple] = []
    row_id = 0
    tunnel_portal_row_id = 0

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
            way_id = int(meta["way_id"])
            points = geom.get("points")
            if not isinstance(points, list):
                points = []

            ways_batch.append(
                (
                    row_id,
                    way_id,
                    meta.get("highway"),
                    meta.get("street_name"),
                    meta.get("ref"),
                    meta.get("maxspeed"),
                    meta.get("maxspeed_type"),
                    meta.get("source_maxspeed"),
                    meta.get("approx_heading_deg"),
                    meta.get("service"),
                    meta.get("tunnel"),
                    meta.get("bridge"),
                    meta.get("covered"),
                    meta.get("location"),
                    meta.get("layer"),
                    meta.get("level"),
                    float(meta["min_lon"]),
                    float(meta["min_lat"]),
                    float(meta["max_lon"]),
                    float(meta["max_lat"]),
                )
            )
            ways_rtree_batch.append(
                (
                    row_id,
                    float(meta["min_lon"]),
                    float(meta["max_lon"]),
                    float(meta["min_lat"]),
                    float(meta["max_lat"]),
                )
            )
            geom_batch.append((row_id, json.dumps(points, separators=(",", ":"))))

            if _is_tunnel_like_way(meta) and len(points) >= 2:
                layer = _parse_numeric_tag(meta.get("layer"))
                level = _parse_numeric_tag(meta.get("level"))
                for portal_index, portal in enumerate((points[0], points[-1])):
                    try:
                        lat = float(portal[0])
                        lon = float(portal[1])
                    except (TypeError, ValueError, IndexError):
                        continue
                    tunnel_portal_row_id += 1
                    tunnel_portal_batch.append(
                        (
                            tunnel_portal_row_id,
                            row_id,
                            way_id,
                            portal_index,
                            lon,
                            lat,
                            meta.get("tunnel"),
                            meta.get("location"),
                            layer,
                            level,
                        )
                    )
                    tunnel_portal_rtree_batch.append(
                        (
                            tunnel_portal_row_id,
                            lon,
                            lon,
                            lat,
                            lat,
                        )
                    )

            if len(ways_batch) >= args.batch_size:
                conn.executemany(
                    """
                    INSERT INTO ways(
                      row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed,
                      approx_heading_deg, service, tunnel, bridge, covered, location, layer, level,
                      min_lon, min_lat, max_lon, max_lat
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ways_batch,
                )
                conn.executemany(
                    "INSERT INTO ways_rtree(row_id, min_lon, max_lon, min_lat, max_lat) VALUES(?, ?, ?, ?, ?)",
                    ways_rtree_batch,
                )
                conn.executemany(
                    "INSERT INTO way_geom(row_id, points_json) VALUES(?, ?)",
                    geom_batch,
                )
                conn.executemany(
                    """
                    INSERT INTO tunnel_portal(
                      row_id, way_row_id, way_id, portal_index, lon, lat, tunnel, location, layer, level
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    tunnel_portal_batch,
                )
                conn.executemany(
                    "INSERT INTO tunnel_portal_rtree(row_id, min_lon, max_lon, min_lat, max_lat) VALUES(?, ?, ?, ?, ?)",
                    tunnel_portal_rtree_batch,
                )
                conn.commit()
                ways_batch.clear()
                ways_rtree_batch.clear()
                geom_batch.clear()
                tunnel_portal_batch.clear()
                tunnel_portal_rtree_batch.clear()

            if row_id % args.progress_every == 0:
                print(f"  ways inserted: {row_id}", file=sys.stderr)

    if ways_batch:
        conn.executemany(
            """
            INSERT INTO ways(
              row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed,
              approx_heading_deg, service, tunnel, bridge, covered, location, layer, level,
              min_lon, min_lat, max_lon, max_lat
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ways_batch,
        )
        conn.executemany(
            "INSERT INTO ways_rtree(row_id, min_lon, max_lon, min_lat, max_lat) VALUES(?, ?, ?, ?, ?)",
            ways_rtree_batch,
        )
        conn.executemany(
            "INSERT INTO way_geom(row_id, points_json) VALUES(?, ?)",
            geom_batch,
        )
        conn.executemany(
            """
            INSERT INTO tunnel_portal(
              row_id, way_row_id, way_id, portal_index, lon, lat, tunnel, location, layer, level
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            tunnel_portal_batch,
        )
        conn.executemany(
            "INSERT INTO tunnel_portal_rtree(row_id, min_lon, max_lon, min_lat, max_lat) VALUES(?, ?, ?, ?, ?)",
            tunnel_portal_rtree_batch,
        )
        conn.commit()

    print(f"Ways done: {row_id}", file=sys.stderr)

    areas_payload = json.loads(areas_idx.read_text(encoding="utf-8"))
    areas = areas_payload.get("areas", [])
    if not isinstance(areas, list):
        print("areas.idx format invalid: areas must be array", file=sys.stderr)
        return 1

    area_rows = []
    area_rtree_rows = []
    for i, area in enumerate(areas, start=1):
        points = area.get("points")
        points_json = json.dumps(points, separators=(",", ":")) if isinstance(points, list) and points else None
        area_rows.append(
            (
                i,
                str(area.get("area_id", "")),
                area.get("geometry_type"),
                area.get("name"),
                area.get("place"),
                area.get("boundary"),
                area.get("admin_level"),
                area.get("residential"),
                points_json,
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
                  row_id, area_id, geometry_type, name, place, boundary, admin_level, residential, points_json,
                  min_lon, min_lat, max_lon, max_lat
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
              row_id, area_id, geometry_type, name, place, boundary, admin_level, residential, points_json,
              min_lon, min_lat, max_lon, max_lat
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            area_rows,
        )
        conn.executemany(
            "INSERT INTO areas_rtree(row_id, min_lon, max_lon, min_lat, max_lat) VALUES(?, ?, ?, ?, ?)",
            area_rtree_rows,
        )
        conn.commit()

    conn.execute("CREATE INDEX idx_ways_way_id ON ways(way_id)")
    conn.execute("CREATE INDEX idx_areas_place_admin ON areas(place, admin_level, boundary)")
    conn.execute("CREATE INDEX idx_tunnel_portal_way ON tunnel_portal(way_id, way_row_id, portal_index)")
    conn.executemany(
        "INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)",
        [
            ("tunnel_portal_count", str(tunnel_portal_row_id)),
        ],
    )
    conn.commit()
    conn.close()

    print(f"Wrote v3 DB: {out_db}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
