#!/usr/bin/env python3
"""Build v4 spatial DB (SQLite + RTree + tile mapping).

v4 combines:
- spatial indexing (RTree) like v3
- virtual tile partition metadata for fast local prefiltering
- optional city-context index (admin polygons + place points)
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import sys
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

try:
    import osmium
except Exception:
    osmium = None

EARTH_RADIUS_M = 6378137.0
MAX_MERCATOR_LAT = 85.05112878
PLACE_VALUES = {"city", "town", "village", "hamlet"}
FALSE_TAG_VALUES = {"", "0", "false", "no", "off", "none"}


def _lon_lat_to_mercator_m(lon: float, lat: float) -> Tuple[float, float]:
    lat = min(max(lat, -MAX_MERCATOR_LAT), MAX_MERCATOR_LAT)
    x = EARTH_RADIUS_M * math.radians(lon)
    y = EARTH_RADIUS_M * math.log(math.tan(math.pi / 4.0 + math.radians(lat) / 2.0))
    return x, y


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


def _downsample_closed_ring(points: List[Tuple[float, float]], max_points: int) -> List[Tuple[float, float]]:
    if len(points) < 4:
        return points
    if max_points < 4:
        max_points = 4
    if len(points) <= max_points:
        return points

    if points[0] != points[-1]:
        points = points + [points[0]]

    body = points[:-1]
    if len(body) < 3:
        return points

    target_body = max_points - 1
    if len(body) <= target_body:
        sampled = body
    else:
        step = (len(body) - 1) / max(target_body - 1, 1)
        sampled = []
        last_idx = -1
        for i in range(target_body):
            idx = int(round(i * step))
            idx = min(max(idx, 0), len(body) - 1)
            if idx == last_idx:
                continue
            sampled.append(body[idx])
            last_idx = idx
        if sampled[-1] != body[-1]:
            sampled[-1] = body[-1]

    if sampled[0] != sampled[-1]:
        sampled.append(sampled[0])
    return sampled


class _CityContextExtractor(osmium.SimpleHandler):
    def __init__(
        self,
        tile_size_m: int,
        max_ring_points: int,
        max_boundary_tiles: int,
        batch_size: int,
        progress_every: int,
    ) -> None:
        super().__init__()
        self.tile_size_m = tile_size_m
        self.max_ring_points = max_ring_points
        self.max_boundary_tiles = max_boundary_tiles
        self.batch_size = batch_size
        self.progress_every = progress_every

        self.boundary_rows: List[Tuple] = []
        self.boundary_rtree_rows: List[Tuple] = []
        self.ring_rows: List[Tuple] = []
        self.tile_rows: List[Tuple] = []
        self.place_rows: List[Tuple] = []
        self.place_rtree_rows: List[Tuple] = []

        self.boundary_row_id = 0
        self.place_row_id = 0

        self.stats = {
            "city_boundaries": 0,
            "city_rings": 0,
            "city_tiles": 0,
            "city_tile_fallback_boundaries": 0,
            "city_places": 0,
            "area_events_seen": 0,
        }

    def area(self, area: "osmium.osm.Area") -> None:
        self.stats["area_events_seen"] += 1
        tags = area.tags
        if tags.get("boundary") != "administrative":
            return
        admin_level_raw = tags.get("admin_level")
        if admin_level_raw not in {"8", "9"}:
            return

        ring_rows_local: List[Tuple[int, int, int, str]] = []
        min_lon = float("inf")
        min_lat = float("inf")
        max_lon = float("-inf")
        max_lat = float("-inf")

        outer_index = 0
        ring_index = 0

        for outer in area.outer_rings():
            outer_pts: List[Tuple[float, float]] = []
            for n in outer:
                outer_pts.append((float(n.lon), float(n.lat)))
            if len(outer_pts) < 4:
                continue
            outer_pts = _downsample_closed_ring(outer_pts, self.max_ring_points)

            for lon, lat in outer_pts:
                min_lon = min(min_lon, lon)
                min_lat = min(min_lat, lat)
                max_lon = max(max_lon, lon)
                max_lat = max(max_lat, lat)

            ring_rows_local.append(
                (
                    ring_index,
                    outer_index,
                    0,
                    json.dumps([[lon, lat] for lon, lat in outer_pts], separators=(",", ":")),
                )
            )
            ring_index += 1

            for inner in area.inner_rings(outer):
                hole_pts: List[Tuple[float, float]] = []
                for n in inner:
                    hole_pts.append((float(n.lon), float(n.lat)))
                if len(hole_pts) < 4:
                    continue
                hole_pts = _downsample_closed_ring(hole_pts, self.max_ring_points)
                ring_rows_local.append(
                    (
                        ring_index,
                        outer_index,
                        1,
                        json.dumps([[lon, lat] for lon, lat in hole_pts], separators=(",", ":")),
                    )
                )
                ring_index += 1

            outer_index += 1

        if not ring_rows_local or not math.isfinite(min_lon) or not math.isfinite(min_lat):
            return

        self.boundary_row_id += 1
        row_id = self.boundary_row_id

        osm_type = "way" if area.from_way() else "relation"
        osm_id = int(area.orig_id())
        admin_level = int(admin_level_raw)
        name = tags.get("name")

        self.boundary_rows.append((row_id, osm_type, osm_id, admin_level, name, min_lon, min_lat, max_lon, max_lat))
        self.boundary_rtree_rows.append((row_id, min_lon, max_lon, min_lat, max_lat))

        for ring_idx, outer_idx, is_hole, points_json in ring_rows_local:
            self.ring_rows.append((row_id, ring_idx, outer_idx, is_hole, points_json))

        tx0, tx1, ty0, ty1 = _tile_range_for_bbox(min_lon, min_lat, max_lon, max_lat, self.tile_size_m)
        tile_count = (tx1 - tx0 + 1) * (ty1 - ty0 + 1)
        if tile_count > self.max_boundary_tiles:
            tx, ty = _tile_for_lon_lat((min_lon + max_lon) / 2.0, (min_lat + max_lat) / 2.0, self.tile_size_m)
            self.tile_rows.append((row_id, tx, ty))
            self.stats["city_tile_fallback_boundaries"] += 1
        else:
            for tx in range(tx0, tx1 + 1):
                for ty in range(ty0, ty1 + 1):
                    self.tile_rows.append((row_id, tx, ty))

        self.stats["city_boundaries"] += 1
        self.stats["city_rings"] += len(ring_rows_local)
        self.stats["city_tiles"] += 1 if tile_count > self.max_boundary_tiles else tile_count

        if self.stats["city_boundaries"] % self.progress_every == 0:
            print(f"  city boundaries captured: {self.stats['city_boundaries']}", file=sys.stderr)

    def node(self, node: "osmium.osm.Node") -> None:
        place = node.tags.get("place")
        if place not in PLACE_VALUES:
            return
        if not node.location.valid():
            return
        name = node.tags.get("name")
        if not name:
            return

        self.place_row_id += 1
        lon = float(node.location.lon)
        lat = float(node.location.lat)
        self.place_rows.append((self.place_row_id, place, name, lon, lat))
        self.place_rtree_rows.append((self.place_row_id, lon, lon, lat, lat))
        self.stats["city_places"] += 1


def _insert_city_rows(conn: sqlite3.Connection, extractor: _CityContextExtractor, batch_size: int) -> None:
    def _flush(rows: List[Tuple], sql: str) -> None:
        if not rows:
            return
        conn.executemany(sql, rows)
        rows.clear()

    # Boundaries
    for i in range(0, len(extractor.boundary_rows), batch_size):
        conn.executemany(
            """
            INSERT INTO city_boundary(
              row_id, osm_type, osm_id, admin_level, name,
              min_lon, min_lat, max_lon, max_lat
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            extractor.boundary_rows[i : i + batch_size],
        )
    for i in range(0, len(extractor.boundary_rtree_rows), batch_size):
        conn.executemany(
            "INSERT INTO city_boundary_rtree(row_id, min_lon, max_lon, min_lat, max_lat) VALUES(?, ?, ?, ?, ?)",
            extractor.boundary_rtree_rows[i : i + batch_size],
        )
    for i in range(0, len(extractor.ring_rows), batch_size):
        conn.executemany(
            """
            INSERT INTO city_ring(boundary_row_id, ring_index, outer_index, is_hole, points_json)
            VALUES (?, ?, ?, ?, ?)
            """,
            extractor.ring_rows[i : i + batch_size],
        )
    for i in range(0, len(extractor.tile_rows), batch_size):
        conn.executemany(
            "INSERT INTO city_tile(boundary_row_id, tile_x, tile_y) VALUES(?, ?, ?)",
            extractor.tile_rows[i : i + batch_size],
        )

    # Places from PBF nodes.
    for i in range(0, len(extractor.place_rows), batch_size):
        conn.executemany(
            "INSERT INTO city_place(row_id, place, name, lon, lat) VALUES (?, ?, ?, ?, ?)",
            extractor.place_rows[i : i + batch_size],
        )
    for i in range(0, len(extractor.place_rtree_rows), batch_size):
        conn.executemany(
            "INSERT INTO city_place_rtree(row_id, min_lon, max_lon, min_lat, max_lat) VALUES(?, ?, ?, ?, ?)",
            extractor.place_rtree_rows[i : i + batch_size],
        )


def _populate_city_context_from_areas(conn: sqlite3.Connection, batch_size: int) -> int:
    cur = conn.execute(
        """
        SELECT place, name, min_lon, min_lat
        FROM areas
        WHERE geometry_type='Point'
          AND place IN ('city','town','village','hamlet')
          AND name IS NOT NULL
        """
    )
    rows = cur.fetchall()
    out = []
    out_rtree = []
    row_id = 0
    for place, name, lon, lat in rows:
        row_id += 1
        lon_f = float(lon)
        lat_f = float(lat)
        out.append((row_id, place, name, lon_f, lat_f))
        out_rtree.append((row_id, lon_f, lon_f, lat_f, lat_f))

    for i in range(0, len(out), batch_size):
        conn.executemany(
            "INSERT INTO city_place(row_id, place, name, lon, lat) VALUES (?, ?, ?, ?, ?)",
            out[i : i + batch_size],
        )
    for i in range(0, len(out_rtree), batch_size):
        conn.executemany(
            "INSERT INTO city_place_rtree(row_id, min_lon, max_lon, min_lat, max_lat) VALUES(?, ?, ?, ?, ?)",
            out_rtree[i : i + batch_size],
        )
    return len(out)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build v4 SQLite/SpatiaLite DB with tile prefilter table")
    parser.add_argument("--v1-dist", required=True, help="Path to mapdata/dist/<region>")
    parser.add_argument("--out-db", required=True, help="Output SQLite database path")
    parser.add_argument("--input-pbf", help="Optional source PBF to build exact city polygon index")
    parser.add_argument("--tile-size-m", type=int, default=4096, help="Tile size in EPSG:3857 meters")
    parser.add_argument("--max-way-tiles", type=int, default=1024, help="Per-way tile fan-out cap before center fallback")
    parser.add_argument("--max-city-tiles", type=int, default=50000, help="Per-city bbox tile cap before center fallback")
    parser.add_argument("--max-city-ring-points", type=int, default=256, help="Max points per city ring after downsampling")
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
    if args.max_city_tiles < 1:
        print("--max-city-tiles must be >= 1", file=sys.stderr)
        return 1
    if args.max_city_ring_points < 4:
        print("--max-city-ring-points must be >= 4", file=sys.stderr)
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

    input_pbf = Path(args.input_pbf) if args.input_pbf else None
    if input_pbf and not input_pbf.exists():
        print(f"Missing --input-pbf: {input_pbf}", file=sys.stderr)
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
          street_name TEXT,
          ref TEXT,
          maxspeed TEXT,
          maxspeed_type TEXT,
          source_maxspeed TEXT,
          zone_maxspeed TEXT,
          traffic_sign TEXT,
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

        CREATE TABLE way_geom (
          row_id INTEGER PRIMARY KEY,
          way_id TEXT NOT NULL UNIQUE,
          points_json TEXT NOT NULL
        );

        CREATE TABLE tunnel_portal (
          row_id INTEGER PRIMARY KEY,
          way_row_id INTEGER NOT NULL,
          way_id TEXT NOT NULL,
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
          residential TEXT,
          parking TEXT,
          traffic_sign TEXT,
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

        CREATE TABLE city_boundary (
          row_id INTEGER PRIMARY KEY,
          osm_type TEXT NOT NULL,
          osm_id INTEGER NOT NULL,
          admin_level INTEGER NOT NULL,
          name TEXT,
          min_lon REAL NOT NULL,
          min_lat REAL NOT NULL,
          max_lon REAL NOT NULL,
          max_lat REAL NOT NULL
        );

        CREATE VIRTUAL TABLE city_boundary_rtree USING rtree(
          row_id,
          min_lon, max_lon,
          min_lat, max_lat
        );

        CREATE TABLE city_ring (
          boundary_row_id INTEGER NOT NULL,
          ring_index INTEGER NOT NULL,
          outer_index INTEGER NOT NULL,
          is_hole INTEGER NOT NULL,
          points_json TEXT NOT NULL
        );

        CREATE TABLE city_tile (
          boundary_row_id INTEGER NOT NULL,
          tile_x INTEGER NOT NULL,
          tile_y INTEGER NOT NULL
        );

        CREATE TABLE city_place (
          row_id INTEGER PRIMARY KEY,
          place TEXT NOT NULL,
          name TEXT NOT NULL,
          lon REAL NOT NULL,
          lat REAL NOT NULL
        );

        CREATE VIRTUAL TABLE city_place_rtree USING rtree(
          row_id,
          min_lon, max_lon,
          min_lat, max_lat
        );
        """
    )

    conn.executemany(
        "INSERT INTO metadata(key, value) VALUES(?, ?)",
        [
            ("schema_version", "2"),
            ("backend", backend),
            ("source_v1_dist", str(v1_dist)),
            ("tile_size_m", str(args.tile_size_m)),
            ("max_way_tiles", str(args.max_way_tiles)),
            ("max_city_tiles", str(args.max_city_tiles)),
            ("max_city_ring_points", str(args.max_city_ring_points)),
            ("city_context_mode", "disabled"),
        ],
    )

    ways_batch: List[Tuple] = []
    ways_rtree_batch: List[Tuple] = []
    geom_batch: List[Tuple] = []
    tunnel_portal_batch: List[Tuple] = []
    tunnel_portal_rtree_batch: List[Tuple] = []
    way_tile_batch: List[Tuple] = []
    row_id = 0
    tunnel_portal_row_id = 0
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
                    meta.get("street_name"),
                    meta.get("ref"),
                    meta.get("maxspeed"),
                    meta.get("maxspeed_type"),
                    meta.get("source_maxspeed"),
                    meta.get("zone_maxspeed"),
                    meta.get("traffic_sign"),
                    meta.get("approx_heading_deg"),
                    meta.get("service"),
                    meta.get("tunnel"),
                    meta.get("bridge"),
                    meta.get("covered"),
                    meta.get("location"),
                    meta.get("layer"),
                    meta.get("level"),
                    min_lon,
                    min_lat,
                    max_lon,
                    max_lat,
                )
            )
            ways_rtree_batch.append((row_id, min_lon, max_lon, min_lat, max_lat))
            geom_batch.append((row_id, way_id, json.dumps(points, separators=(",", ":"))))

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
                      row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed,
                      zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level,
                      min_lon, min_lat, max_lon, max_lat
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                conn.executemany(
                    "INSERT INTO way_tile(row_id, tile_x, tile_y) VALUES(?, ?, ?)",
                    way_tile_batch,
                )
                conn.commit()
                ways_batch.clear()
                ways_rtree_batch.clear()
                geom_batch.clear()
                tunnel_portal_batch.clear()
                tunnel_portal_rtree_batch.clear()
                way_tile_batch.clear()

            if row_id % args.progress_every == 0:
                print(f"  ways inserted: {row_id}", file=sys.stderr)

    if ways_batch:
        conn.executemany(
            """
            INSERT INTO ways(
              row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed,
              zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, bridge, covered, location, layer, level,
              min_lon, min_lat, max_lon, max_lat
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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

    area_rows: List[Tuple] = []
    area_rtree_rows: List[Tuple] = []
    city_sign_marker_count = 0
    for i, area in enumerate(areas, start=1):
        points = area.get("points")
        points_json = json.dumps(points, separators=(",", ":")) if isinstance(points, list) and points else None
        traffic_sign = area.get("traffic_sign")
        if traffic_sign:
            city_sign_marker_count += 1
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
                area.get("parking"),
                traffic_sign,
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
                  row_id, area_id, geometry_type, name, place, boundary, admin_level, residential, parking, traffic_sign, points_json,
                  min_lon, min_lat, max_lon, max_lat
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
              row_id, area_id, geometry_type, name, place, boundary, admin_level, residential, parking, traffic_sign, points_json,
              min_lon, min_lat, max_lon, max_lat
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            area_rows,
        )
        conn.executemany(
            "INSERT INTO areas_rtree(row_id, min_lon, max_lon, min_lat, max_lat) VALUES(?, ?, ?, ?, ?)",
            area_rtree_rows,
        )
        conn.commit()

    city_mode = "areas_place_points"
    city_stats: Dict[str, int] = {
        "city_boundaries": 0,
        "city_rings": 0,
        "city_tiles": 0,
        "city_tile_fallback_boundaries": 0,
        "city_places": 0,
    }

    if input_pbf:
        if osmium is None:
            print("pyosmium unavailable; skipping exact city polygon extraction", file=sys.stderr)
        else:
            print(f"Extracting city polygons from PBF: {input_pbf}", file=sys.stderr)
            extractor = _CityContextExtractor(
                tile_size_m=args.tile_size_m,
                max_ring_points=args.max_city_ring_points,
                max_boundary_tiles=args.max_city_tiles,
                batch_size=args.batch_size,
                progress_every=max(1, args.progress_every // 100),
            )
            extractor.apply_file(str(input_pbf), locations=True)
            _insert_city_rows(conn, extractor, args.batch_size)
            city_stats = {
                "city_boundaries": int(extractor.stats["city_boundaries"]),
                "city_rings": int(extractor.stats["city_rings"]),
                "city_tiles": int(extractor.stats["city_tiles"]),
                "city_tile_fallback_boundaries": int(extractor.stats["city_tile_fallback_boundaries"]),
                "city_places": int(extractor.stats["city_places"]),
            }
            city_mode = "admin_polygons_plus_places"

    if city_stats["city_places"] == 0:
        # Fallback from areas.idx point rows if PBF extraction is disabled or unavailable.
        city_stats["city_places"] = _populate_city_context_from_areas(conn, args.batch_size)

    conn.execute("CREATE INDEX idx_ways_way_id ON ways(way_id)")
    conn.execute("CREATE INDEX idx_way_tile_xy ON way_tile(tile_x, tile_y, row_id)")
    conn.execute("CREATE INDEX idx_way_tile_row ON way_tile(row_id)")
    conn.execute("CREATE INDEX idx_tunnel_portal_way ON tunnel_portal(way_id, way_row_id, portal_index)")
    conn.execute("CREATE INDEX idx_areas_place_admin ON areas(place, admin_level, boundary)")
    conn.execute("CREATE INDEX idx_areas_traffic_sign ON areas(traffic_sign, geometry_type)")

    conn.execute("CREATE INDEX idx_city_boundary_osm ON city_boundary(osm_type, osm_id)")
    conn.execute("CREATE INDEX idx_city_ring_boundary ON city_ring(boundary_row_id, outer_index, is_hole, ring_index)")
    conn.execute("CREATE INDEX idx_city_tile_xy ON city_tile(tile_x, tile_y, boundary_row_id)")
    conn.execute("CREATE INDEX idx_city_tile_boundary ON city_tile(boundary_row_id)")
    conn.execute("CREATE INDEX idx_city_place_place_name ON city_place(place, name)")

    conn.executemany(
        "INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)",
        [
            ("city_context_mode", city_mode),
            ("city_boundaries", str(city_stats["city_boundaries"])),
            ("city_rings", str(city_stats["city_rings"])),
            ("city_tiles", str(city_stats["city_tiles"])),
            ("city_tile_fallback_boundaries", str(city_stats["city_tile_fallback_boundaries"])),
            ("city_places", str(city_stats["city_places"])),
            ("city_sign_marker_count", str(city_sign_marker_count)),
            ("tunnel_portal_count", str(tunnel_portal_row_id)),
            ("source_input_pbf", str(input_pbf) if input_pbf else ""),
        ],
    )
    conn.commit()
    conn.close()

    print(f"City context mode: {city_mode}", file=sys.stderr)
    print(
        "City context stats: boundaries={city_boundaries}, rings={city_rings}, tiles={city_tiles}, places={city_places}, tile_fallback={city_tile_fallback_boundaries}".format(
            **city_stats
        ),
        file=sys.stderr,
    )
    print(f"Wrote v4 DB: {out_db}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
