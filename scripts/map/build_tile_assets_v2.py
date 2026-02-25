#!/usr/bin/env python3
"""Build per-tile v2 map assets from existing v1 dist artifacts.

Input (v1):
- ways.meta (JSONL)
- ways.geom (JSONL)
- areas.idx (JSON)

Output (v2):
- catalog.v2.json
- tiles/<tile_id>/tile_manifest.v2.json
- tiles/<tile_id>/<content_sha256>.tilepack

Each tilepack stores raw JSON chunk payloads concatenated in this fixed order:
- segment_index
- segment_geom
- speed_rules
- adjacency
- area_index
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import shutil
import sys
import tempfile
from collections import OrderedDict
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Tuple

EARTH_RADIUS_M = 6378137.0
MAX_MERCATOR_LAT = 85.05112878
PLACE_VALUES = {"city", "town", "village", "hamlet"}

CHUNK_ORDER = ["segment_index", "segment_geom", "speed_rules", "adjacency", "area_index"]


def _sha256_path(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _lon_lat_to_mercator_m(lon: float, lat: float) -> Tuple[float, float]:
    lat = min(max(lat, -MAX_MERCATOR_LAT), MAX_MERCATOR_LAT)
    x = EARTH_RADIUS_M * math.radians(lon)
    y = EARTH_RADIUS_M * math.log(math.tan(math.pi / 4.0 + math.radians(lat) / 2.0))
    return x, y


def _mercator_m_to_lon_lat(x: float, y: float) -> Tuple[float, float]:
    lon = math.degrees(x / EARTH_RADIUS_M)
    lat = math.degrees(2.0 * math.atan(math.exp(y / EARTH_RADIUS_M)) - math.pi / 2.0)
    return lon, lat


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


def _tile_id(tx: int, ty: int) -> str:
    return f"{tx}/{ty}"


def _tile_bbox_wgs84(tx: int, ty: int, tile_size_m: int) -> dict:
    min_x = tx * tile_size_m
    max_x = (tx + 1) * tile_size_m
    min_y = ty * tile_size_m
    max_y = (ty + 1) * tile_size_m

    min_lon, min_lat = _mercator_m_to_lon_lat(min_x, min_y)
    max_lon, max_lat = _mercator_m_to_lon_lat(max_x, max_y)

    return {
        "min_lat": min(min_lat, max_lat),
        "min_lon": min(min_lon, max_lon),
        "max_lat": max(min_lat, max_lat),
        "max_lon": max(min_lon, max_lon),
    }


def _local_cell_key(
    min_lon: float,
    min_lat: float,
    max_lon: float,
    max_lat: float,
    tx: int,
    ty: int,
    tile_size_m: int,
    subgrid: int,
) -> Iterator[str]:
    tile_x0 = tx * tile_size_m
    tile_y0 = ty * tile_size_m
    x0, y0 = _lon_lat_to_mercator_m(min_lon, min_lat)
    x1, y1 = _lon_lat_to_mercator_m(max_lon, max_lat)

    lx0 = min(max(min(x0, x1) - tile_x0, 0.0), float(tile_size_m))
    lx1 = min(max(max(x0, x1) - tile_x0, 0.0), float(tile_size_m))
    ly0 = min(max(min(y0, y1) - tile_y0, 0.0), float(tile_size_m))
    ly1 = min(max(max(y0, y1) - tile_y0, 0.0), float(tile_size_m))

    def to_idx(v: float) -> int:
        idx = int(math.floor((v / tile_size_m) * subgrid))
        return min(max(idx, 0), subgrid - 1)

    ix0 = to_idx(lx0)
    ix1 = to_idx(lx1)
    iy0 = to_idx(ly0)
    iy1 = to_idx(ly1)
    for ix in range(ix0, ix1 + 1):
        for iy in range(iy0, iy1 + 1):
            yield f"{ix}:{iy}"


class _JsonlHandleCache:
    def __init__(self, root: Path, max_open: int = 128) -> None:
        self.root = root
        self.max_open = max_open
        self._handles: OrderedDict[str, object] = OrderedDict()
        self.root.mkdir(parents=True, exist_ok=True)

    def write(self, rel_name: str, row: dict) -> None:
        h = self._handles.get(rel_name)
        if h is None:
            if len(self._handles) >= self.max_open:
                old_name, old_handle = self._handles.popitem(last=False)
                old_handle.close()
            path = self.root / rel_name
            path.parent.mkdir(parents=True, exist_ok=True)
            h = path.open("a", encoding="utf-8")
            self._handles[rel_name] = h
        else:
            self._handles.move_to_end(rel_name)
        h.write(json.dumps(row, sort_keys=True, separators=(",", ":")))
        h.write("\n")

    def close(self) -> None:
        for h in self._handles.values():
            h.close()
        self._handles.clear()


def _load_areas_idx(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError("areas.idx must be a JSON object")
    return payload


def _load_jsonl(path: Path) -> Iterator[dict]:
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


def _build_chunks_for_tile(tile_ways: List[dict], tile_areas: List[dict], tx: int, ty: int, tile_size_m: int, subgrid: int) -> Dict[str, bytes]:
    segment_index_cells: Dict[str, List[str]] = {}
    segment_geom: Dict[str, dict] = {}
    speed_rules: Dict[str, dict] = {}
    adjacency = {"edges": {}}

    for row in tile_ways:
        seg_id = row["way_id"]
        segment_geom[seg_id] = {
            "way_id": row["way_id"],
            "points": row["points"],
            "min_lon": row["min_lon"],
            "min_lat": row["min_lat"],
            "max_lon": row["max_lon"],
            "max_lat": row["max_lat"],
            "approx_heading_deg": row.get("approx_heading_deg"),
            "highway": row.get("highway"),
        }
        speed_rules[seg_id] = {
            "highway": row.get("highway"),
            "street_name": row.get("street_name"),
            "maxspeed": row.get("maxspeed"),
            "maxspeed_type": row.get("maxspeed_type"),
            "source_maxspeed": row.get("source_maxspeed"),
            "zone_maxspeed": row.get("zone_maxspeed"),
            "traffic_sign": row.get("traffic_sign"),
        }

        for cell in _local_cell_key(
            row["min_lon"],
            row["min_lat"],
            row["max_lon"],
            row["max_lat"],
            tx,
            ty,
            tile_size_m,
            subgrid,
        ):
            segment_index_cells.setdefault(cell, []).append(seg_id)

    for cell in segment_index_cells:
        segment_index_cells[cell] = sorted(set(segment_index_cells[cell]))

    segment_index = {
        "grid_size": subgrid,
        "cells": dict(sorted(segment_index_cells.items())),
    }

    area_index = {"areas": tile_areas}
    chunk_map: Dict[str, object] = {
        "segment_index": segment_index,
        "segment_geom": segment_geom,
        "speed_rules": speed_rules,
        "adjacency": adjacency,
        "area_index": area_index,
    }
    return {
        name: json.dumps(chunk_map[name], sort_keys=True, separators=(",", ":")).encode("utf-8") for name in CHUNK_ORDER
    }


def _parse_tile_id(tile_id: str) -> Tuple[int, int]:
    x_part, y_part = tile_id.split("/", 1)
    return int(x_part), int(y_part)


def _tile_sort_key(tile_id: str) -> Tuple[int, int]:
    tx, ty = _parse_tile_id(tile_id)
    return (tx, ty)


def _tile_file_map(root: Path) -> Dict[str, Path]:
    out: Dict[str, Path] = {}
    for p in root.rglob("*.jsonl"):
        rel = p.relative_to(root).as_posix()
        tile_id = rel.removesuffix(".jsonl")
        out[tile_id] = p
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build v2 tile assets from v1 region dist")
    parser.add_argument("--v1-dist", required=True, help="Path to mapdata/dist/<region> (v1 artifacts)")
    parser.add_argument("--out-dir", required=True, help="Output directory for v2 assets")
    parser.add_argument("--region", required=True, help="Region name (e.g. germany)")
    parser.add_argument("--tile-size-m", type=int, default=1024, help="Tile size in meters (default: 1024)")
    parser.add_argument("--subgrid", type=int, default=32, help="Per-tile index subdivisions per axis (default: 32)")
    parser.add_argument("--content-version", type=int, default=1, help="Content version integer for generated tiles")
    parser.add_argument(
        "--base-url",
        default="https://cdn.youspeed.de/map/v2/stable",
        help="Base CDN URL for catalog/manifests (default: https://cdn.youspeed.de/map/v2/stable)",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=250000,
        help="Log progress every N processed ways (default: 250000)",
    )
    parser.add_argument(
        "--max-ways",
        type=int,
        default=0,
        help="Optional safety limit for ways processed (0 means no limit)",
    )
    parser.add_argument(
        "--max-area-tiles",
        type=int,
        default=4096,
        help="Cap of tiles per area before fallback to center tile only (default: 4096)",
    )
    parser.add_argument(
        "--include-area-only-tiles",
        action="store_true",
        help="Emit tiles that contain only area context and no drivable ways",
    )
    parser.add_argument("--keep-temp", action="store_true", help="Keep temporary bucket files")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.tile_size_m < 256:
        print("--tile-size-m must be >= 256", file=sys.stderr)
        return 1
    if args.subgrid < 4:
        print("--subgrid must be >= 4", file=sys.stderr)
        return 1
    if args.content_version < 1:
        print("--content-version must be >= 1", file=sys.stderr)
        return 1
    if args.max_area_tiles < 1:
        print("--max-area-tiles must be >= 1", file=sys.stderr)
        return 1

    v1_dist = Path(args.v1_dist)
    out_dir = Path(args.out_dir)

    ways_meta_path = v1_dist / "ways.meta"
    ways_geom_path = v1_dist / "ways.geom"
    areas_idx_path = v1_dist / "areas.idx"
    for path in (ways_meta_path, ways_geom_path, areas_idx_path):
        if not path.exists():
            print(f"Missing required v1 artifact: {path}", file=sys.stderr)
            return 1

    if out_dir.exists():
        shutil.rmtree(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    tiles_dir = out_dir / "tiles"
    tiles_dir.mkdir(parents=True, exist_ok=True)

    temp_root = Path(tempfile.mkdtemp(prefix="tilev2_", dir=str(out_dir)))
    ways_bucket_dir = temp_root / "ways"
    areas_bucket_dir = temp_root / "areas"
    ways_writer = _JsonlHandleCache(ways_bucket_dir)
    areas_writer = _JsonlHandleCache(areas_bucket_dir)

    print("Bucketing ways into tiles...", file=sys.stderr)
    ways_processed = 0
    with ways_meta_path.open("r", encoding="utf-8") as fm, ways_geom_path.open("r", encoding="utf-8") as fg:
        while True:
            lm = fm.readline()
            lg = fg.readline()
            if not lm and not lg:
                break
            if not lm or not lg:
                print("ways.meta / ways.geom line count mismatch", file=sys.stderr)
                return 1
            if not lm.strip() or not lg.strip():
                continue
            row = json.loads(lm)
            geom = json.loads(lg)
            way_id = row.get("way_id")
            if way_id != geom.get("way_id"):
                print(f"way_id mismatch in ways.meta and ways.geom: {way_id} vs {geom.get('way_id')}", file=sys.stderr)
                return 1
            points = geom.get("points")
            if not isinstance(points, list) or len(points) < 2:
                continue

            min_lon = float(row["min_lon"])
            min_lat = float(row["min_lat"])
            max_lon = float(row["max_lon"])
            max_lat = float(row["max_lat"])

            tx0, tx1, ty0, ty1 = _tile_range_for_bbox(min_lon, min_lat, max_lon, max_lat, args.tile_size_m)
            row_out = {
                "way_id": str(way_id),
                "highway": row.get("highway"),
                "street_name": row.get("street_name"),
                "maxspeed": row.get("maxspeed"),
                "maxspeed_type": row.get("maxspeed_type"),
                "source_maxspeed": row.get("source_maxspeed"),
                "zone_maxspeed": row.get("zone_maxspeed"),
                "traffic_sign": row.get("traffic_sign"),
                "approx_heading_deg": row.get("approx_heading_deg"),
                "min_lon": min_lon,
                "min_lat": min_lat,
                "max_lon": max_lon,
                "max_lat": max_lat,
                "points": points,
            }
            for tx in range(tx0, tx1 + 1):
                for ty in range(ty0, ty1 + 1):
                    ways_writer.write(f"{_tile_id(tx, ty)}.jsonl", row_out)

            ways_processed += 1
            if args.max_ways > 0 and ways_processed >= args.max_ways:
                break
            if ways_processed % args.progress_every == 0:
                print(f"  ways processed: {ways_processed}", file=sys.stderr)

    ways_writer.close()
    print(f"Ways bucketed: {ways_processed}", file=sys.stderr)
    way_tile_ids = set(_tile_file_map(ways_bucket_dir).keys())

    print("Bucketing areas into tiles...", file=sys.stderr)
    areas_idx = _load_areas_idx(areas_idx_path)
    area_rows = areas_idx.get("areas", [])
    if not isinstance(area_rows, list):
        print("areas.idx areas must be an array", file=sys.stderr)
        return 1
    areas_processed = 0
    area_assignments = 0
    area_center_fallback = 0
    for area in area_rows:
        min_lon = float(area["min_lon"])
        min_lat = float(area["min_lat"])
        max_lon = float(area["max_lon"])
        max_lat = float(area["max_lat"])
        tx0, tx1, ty0, ty1 = _tile_range_for_bbox(min_lon, min_lat, max_lon, max_lat, args.tile_size_m)
        total_tiles = (tx1 - tx0 + 1) * (ty1 - ty0 + 1)
        tile_ids: List[str] = []
        if total_tiles > args.max_area_tiles:
            center_lon = (min_lon + max_lon) / 2.0
            center_lat = (min_lat + max_lat) / 2.0
            ctx, cty = _tile_for_lon_lat(center_lon, center_lat, args.tile_size_m)
            tile_ids = [_tile_id(ctx, cty)]
            area_center_fallback += 1
        else:
            for tx in range(tx0, tx1 + 1):
                for ty in range(ty0, ty1 + 1):
                    tile_ids.append(_tile_id(tx, ty))

        for tid in tile_ids:
            if not args.include_area_only_tiles and tid not in way_tile_ids:
                continue
            areas_writer.write(f"{tid}.jsonl", area)
            area_assignments += 1
        areas_processed += 1
    areas_writer.close()
    print(
        f"Areas bucketed: {areas_processed} (assignments={area_assignments}, center_fallback={area_center_fallback})",
        file=sys.stderr,
    )

    way_tile_files = _tile_file_map(ways_bucket_dir)
    area_tile_files = _tile_file_map(areas_bucket_dir)
    if args.include_area_only_tiles:
        all_tile_ids = sorted(set(way_tile_files.keys()) | set(area_tile_files.keys()), key=_tile_sort_key)
    else:
        all_tile_ids = sorted(set(way_tile_files.keys()), key=_tile_sort_key)
    print(f"Building tile packs: {len(all_tile_ids)} tiles", file=sys.stderr)

    generated_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    catalog_tiles = []

    for idx, tile_id in enumerate(all_tile_ids, start=1):
        tx, ty = _parse_tile_id(tile_id)
        tile_dir = tiles_dir / tile_id
        tile_dir.mkdir(parents=True, exist_ok=True)

        tile_ways = list(_load_jsonl(way_tile_files[tile_id])) if tile_id in way_tile_files else []
        tile_areas = list(_load_jsonl(area_tile_files[tile_id])) if tile_id in area_tile_files else []
        chunks = _build_chunks_for_tile(tile_ways, tile_areas, tx, ty, args.tile_size_m, args.subgrid)

        tilepack_tmp = tile_dir / "tilepack.tmp"
        chunk_entries = []
        offset = 0
        with tilepack_tmp.open("wb") as tf:
            for name in CHUNK_ORDER:
                blob = chunks[name]
                tf.write(blob)
                chunk_entries.append(
                    {
                        "name": name,
                        "offset": offset,
                        "length": len(blob),
                        "codec": "raw",
                    }
                )
                offset += len(blob)

        tile_pack_sha = _sha256_path(tilepack_tmp)
        tile_pack_name = f"{tile_pack_sha}.tilepack"
        tile_pack_path = tile_dir / tile_pack_name
        os.replace(tilepack_tmp, tile_pack_path)
        tile_pack_bytes = tile_pack_path.stat().st_size

        bbox = _tile_bbox_wgs84(tx, ty, args.tile_size_m)
        manifest_payload = {
            "schema_version": 2,
            "tile_id": tile_id,
            "content_version": args.content_version,
            "generated_at_utc": generated_at,
            "tile_pack_url": f"{args.base_url}/{args.region}/tiles/{tile_id}/{tile_pack_name}",
            "tile_pack_bytes": tile_pack_bytes,
            "tile_pack_sha256": tile_pack_sha,
            "bbox_wgs84": bbox,
            "stats": {
                "segment_count": len(tile_ways),
                "node_count": sum(len(w.get("points", [])) for w in tile_ways),
                "area_count": len(tile_areas),
            },
            "chunks": chunk_entries,
        }
        manifest_path = tile_dir / "tile_manifest.v2.json"
        manifest_path.write_text(
            json.dumps(manifest_payload, sort_keys=True, separators=(",", ":"), indent=2) + "\n",
            encoding="utf-8",
        )
        manifest_sha = _sha256_path(manifest_path)
        manifest_rel_url = f"{args.base_url}/{args.region}/tiles/{tile_id}/tile_manifest.v2.json"

        catalog_tiles.append(
            {
                "tile_id": tile_id,
                "tile_manifest_url": manifest_rel_url,
                "tile_manifest_sha256": manifest_sha,
                "content_version": args.content_version,
                "content_bytes": tile_pack_bytes,
                "content_sha256": tile_pack_sha,
                "bbox_wgs84": bbox,
            }
        )

        if idx % 500 == 0:
            print(f"  tiles built: {idx}/{len(all_tile_ids)}", file=sys.stderr)

    catalog_payload = {
        "schema_version": 2,
        "region": args.region,
        "generated_at_utc": generated_at,
        "app_compat": {
            "min_data_runtime_version": 2,
            "max_data_runtime_version": 2,
        },
        "tile_grid": {
            "crs": "EPSG:3857",
            "tile_size_m": args.tile_size_m,
        },
        "channels": ["stable", "canary"],
        "tiles": sorted(catalog_tiles, key=lambda t: _tile_sort_key(t["tile_id"])),
    }
    catalog_path = out_dir / "catalog.v2.json"
    catalog_path.write_text(
        json.dumps(catalog_payload, sort_keys=True, separators=(",", ":"), indent=2) + "\n",
        encoding="utf-8",
    )

    if not args.keep_temp:
        shutil.rmtree(temp_root)
    print(f"Wrote v2 catalog: {catalog_path}", file=sys.stderr)
    print(f"Wrote tile assets: {tiles_dir}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
