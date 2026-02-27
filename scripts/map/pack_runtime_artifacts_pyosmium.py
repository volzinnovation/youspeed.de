#!/usr/bin/env python3
"""Build runtime map artifacts directly from OSM PBF using pyosmium.

Outputs:
- ways.meta: JSONL (one object per way)
- ways.idx: JSON object with coarse grid-cell -> way ID mapping
- areas.idx: JSON object with coarse grid-cell -> area ID mapping + area metadata
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
from collections import defaultdict
from typing import Dict, Iterable, List, TextIO, Tuple

try:
    import osmium
except ImportError as exc:
    print(
        "Missing dependency: Python package 'osmium' (pyosmium). "
        "Install it and rerun.",
        file=sys.stderr,
    )
    raise SystemExit(1) from exc

GRID_SCALE_DEFAULT = 100  # 0.01 degree cells
MAX_GEOM_POINTS_DEFAULT = 24
PLACE_VALUES = {"city", "town", "village", "hamlet"}
SPEED_TAG_KEYS = (
    "maxspeed",
    "maxspeed:type",
    "source:maxspeed",
    "maxspeed:conditional",
    "zone:maxspeed",
    "traffic_sign",
)
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


def _cell_index(value: float, offset: float, scale: int) -> int:
    return math.floor((value + offset) * scale)


def _bbox_from_coords(coords: List[Tuple[float, float]]) -> Tuple[float, float, float, float] | None:
    if not coords:
        return None
    lons = [c[0] for c in coords]
    lats = [c[1] for c in coords]
    return (min(lons), min(lats), max(lons), max(lats))


def _downsample_coords(coords: List[Tuple[float, float]], max_points: int) -> List[Tuple[float, float]]:
    if max_points < 2:
        max_points = 2
    n = len(coords)
    if n <= max_points:
        return coords

    step = (n - 1) / (max_points - 1)
    selected: List[Tuple[float, float]] = []
    last_idx = -1
    for i in range(max_points):
        idx = int(round(i * step))
        idx = min(max(idx, 0), n - 1)
        if idx == last_idx:
            continue
        selected.append(coords[idx])
        last_idx = idx
    if selected[-1] != coords[-1]:
        selected[-1] = coords[-1]
    return selected


def _bearing_deg(from_lon: float, from_lat: float, to_lon: float, to_lat: float) -> float:
    lat1 = math.radians(from_lat)
    lat2 = math.radians(to_lat)
    dlon = math.radians(to_lon - from_lon)
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    bearing = math.degrees(math.atan2(y, x))
    return (bearing + 360.0) % 360.0


def _extract_way_coords(way: osmium.osm.Way) -> List[Tuple[float, float]]:
    coords: List[Tuple[float, float]] = []
    for node_ref in way.nodes:
        loc = node_ref.location
        if not loc.valid():
            continue
        coords.append((loc.lon, loc.lat))
    return coords


def _is_closed_ring(coords: List[Tuple[float, float]]) -> bool:
    return len(coords) >= 4 and coords[0] == coords[-1]


class ArtifactHandler(osmium.SimpleHandler):
    def __init__(
        self,
        max_geom_points: int,
        grid_scale: int,
        ways_meta_file: TextIO,
        ways_geom_file: TextIO,
    ) -> None:
        super().__init__()
        self.max_geom_points = max_geom_points
        self.grid_scale = grid_scale
        self.ways_meta_file = ways_meta_file
        self.ways_geom_file = ways_geom_file
        self.ways_count = 0
        self.ways_lookup: Dict[str, int] = {}
        self.ways_geom_lookup: Dict[str, int] = {}
        self.ways_cells: Dict[str, List[str]] = defaultdict(list)
        self.areas: List[dict] = []

    def way(self, way: osmium.osm.Way) -> None:
        tags = way.tags
        highway = tags.get("highway")
        is_car_drivable = highway in DRIVABLE_HIGHWAYS_CAR
        has_speed_tags = any(k in tags for k in SPEED_TAG_KEYS)
        residential_value = tags.get("residential")
        if residential_value is None and tags.get("landuse") == "residential":
            residential_value = "landuse"
        is_residential_polygon = residential_value is not None

        coords: List[Tuple[float, float]] = []
        bbox: Tuple[float, float, float, float] | None = None

        if is_car_drivable or has_speed_tags or tags.get("boundary") == "administrative" or is_residential_polygon:
            coords = _extract_way_coords(way)
            bbox = _bbox_from_coords(coords)

        if is_car_drivable and bbox is not None and len(coords) > 1:
            min_lon, min_lat, max_lon, max_lat = bbox
            first_lon, first_lat = coords[0]
            last_lon, last_lat = coords[-1]
            way_id = str(way.id)
            way_row = {
                "way_id": way_id,
                "highway": highway,
                "street_name": tags.get("name"),
                "ref": tags.get("ref"),
                "maxspeed": tags.get("maxspeed"),
                "maxspeed_type": tags.get("maxspeed:type"),
                "source_maxspeed": tags.get("source:maxspeed"),
                "maxspeed_conditional": tags.get("maxspeed:conditional"),
                "zone_maxspeed": tags.get("zone:maxspeed"),
                "traffic_sign": tags.get("traffic_sign"),
                "min_lon": min_lon,
                "min_lat": min_lat,
                "max_lon": max_lon,
                "max_lat": max_lat,
                "center_lon": (min_lon + max_lon) / 2,
                "center_lat": (min_lat + max_lat) / 2,
                "first_lon": first_lon,
                "first_lat": first_lat,
                "last_lon": last_lon,
                "last_lat": last_lat,
                "approx_heading_deg": _bearing_deg(first_lon, first_lat, last_lon, last_lat),
            }
            self.ways_lookup[way_id] = self.ways_meta_file.tell()
            self.ways_meta_file.write(json.dumps(way_row, sort_keys=True, separators=(",", ":")))
            self.ways_meta_file.write("\n")

            x0 = _cell_index(min_lon, 180.0, self.grid_scale)
            x1 = _cell_index(max_lon, 180.0, self.grid_scale)
            y0 = _cell_index(min_lat, 90.0, self.grid_scale)
            y1 = _cell_index(max_lat, 90.0, self.grid_scale)
            for x in range(x0, x1 + 1):
                for y in range(y0, y1 + 1):
                    self.ways_cells[f"{x}:{y}"].append(way_id)

            sampled = _downsample_coords(coords, self.max_geom_points)
            geom_row = {"way_id": way_id, "points": [[lat, lon] for lon, lat in sampled]}
            self.ways_geom_lookup[way_id] = self.ways_geom_file.tell()
            self.ways_geom_file.write(json.dumps(geom_row, sort_keys=True, separators=(",", ":")))
            self.ways_geom_file.write("\n")
            self.ways_count += 1

        if tags.get("boundary") == "administrative" and tags.get("admin_level") in {"8", "9"} and bbox is not None:
            min_lon, min_lat, max_lon, max_lat = bbox
            area_points = None
            if _is_closed_ring(coords):
                sampled_area = _downsample_coords(coords, self.max_geom_points)
                area_points = [[lon, lat] for lon, lat in sampled_area]
            self.areas.append(
                {
                    "area_id": f"w:{way.id}",
                    "geometry_type": "LineString",
                    "name": tags.get("name"),
                    "place": tags.get("place"),
                    "boundary": tags.get("boundary"),
                    "admin_level": tags.get("admin_level"),
                    "residential": residential_value,
                    "points": area_points,
                    "min_lon": min_lon,
                    "min_lat": min_lat,
                    "max_lon": max_lon,
                    "max_lat": max_lat,
                }
            )

        if is_residential_polygon and bbox is not None and _is_closed_ring(coords):
            min_lon, min_lat, max_lon, max_lat = bbox
            sampled_area = _downsample_coords(coords, self.max_geom_points)
            self.areas.append(
                {
                    "area_id": f"w:{way.id}",
                    "geometry_type": "Polygon",
                    "name": tags.get("name"),
                    "place": tags.get("place"),
                    "boundary": tags.get("boundary"),
                    "admin_level": tags.get("admin_level"),
                    "residential": residential_value,
                    "points": [[lon, lat] for lon, lat in sampled_area],
                    "min_lon": min_lon,
                    "min_lat": min_lat,
                    "max_lon": max_lon,
                    "max_lat": max_lat,
                }
            )

    def node(self, node: osmium.osm.Node) -> None:
        place = node.tags.get("place")
        if place not in PLACE_VALUES:
            return
        if not node.location.valid():
            return

        lon = node.location.lon
        lat = node.location.lat
        self.areas.append(
            {
                "area_id": f"n:{node.id}",
                "geometry_type": "Point",
                "name": node.tags.get("name"),
                "place": place,
                "boundary": node.tags.get("boundary"),
                "admin_level": node.tags.get("admin_level"),
                "residential": node.tags.get("residential"),
                "points": None,
                "min_lon": lon,
                "min_lat": lat,
                "max_lon": lon,
                "max_lat": lat,
            }
        )


def _build_cells(rows: Iterable[dict], id_key: str, scale: int) -> Dict[str, List[str]]:
    cells: Dict[str, set] = defaultdict(set)

    for row in rows:
        row_id = row[id_key]
        x0 = _cell_index(row["min_lon"], 180.0, scale)
        x1 = _cell_index(row["max_lon"], 180.0, scale)
        y0 = _cell_index(row["min_lat"], 90.0, scale)
        y1 = _cell_index(row["max_lat"], 90.0, scale)

        for x in range(x0, x1 + 1):
            for y in range(y0, y1 + 1):
                cells[f"{x}:{y}"].add(row_id)

    out: Dict[str, List[str]] = {}
    for cell in sorted(cells.keys()):
        out[cell] = sorted(cells[cell], key=_id_sort_key)
    return out


def _write_json(path: str, payload: dict) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, sort_keys=True, separators=(",", ":"))


def main() -> int:
    parser = argparse.ArgumentParser(description="Pack runtime artifacts directly from PBF using pyosmium")
    parser.add_argument("input_pbf", help="Source OSM PBF file")
    parser.add_argument("ways_idx_out", help="Output path for ways.idx")
    parser.add_argument("ways_meta_out", help="Output path for ways.meta")
    parser.add_argument("areas_idx_out", help="Output path for areas.idx")
    parser.add_argument("ways_lookup_out", help="Output path for ways.lookup")
    parser.add_argument("ways_geom_out", help="Output path for ways.geom")
    parser.add_argument("ways_geom_lookup_out", help="Output path for ways.geom.lookup")
    parser.add_argument("--grid-scale", type=int, default=GRID_SCALE_DEFAULT, help="Grid scale (default: 100)")
    parser.add_argument(
        "--max-geom-points",
        type=int,
        default=MAX_GEOM_POINTS_DEFAULT,
        help="Max sampled points per way geometry (default: 24)",
    )
    args = parser.parse_args()

    if args.grid_scale <= 0:
        print("grid-scale must be > 0", file=sys.stderr)
        return 1

    if not os.path.isfile(args.input_pbf):
        print(f"Input file not found: {args.input_pbf}", file=sys.stderr)
        return 1

    os.makedirs(os.path.dirname(args.ways_idx_out), exist_ok=True)
    os.makedirs(os.path.dirname(args.ways_meta_out), exist_ok=True)
    os.makedirs(os.path.dirname(args.areas_idx_out), exist_ok=True)
    os.makedirs(os.path.dirname(args.ways_lookup_out), exist_ok=True)
    os.makedirs(os.path.dirname(args.ways_geom_out), exist_ok=True)
    os.makedirs(os.path.dirname(args.ways_geom_lookup_out), exist_ok=True)

    with open(args.ways_meta_out, "w", encoding="utf-8") as ways_meta_file, open(
        args.ways_geom_out, "w", encoding="utf-8"
    ) as ways_geom_file:
        handler = ArtifactHandler(
            max_geom_points=args.max_geom_points,
            grid_scale=args.grid_scale,
            ways_meta_file=ways_meta_file,
            ways_geom_file=ways_geom_file,
        )
        handler.apply_file(args.input_pbf, locations=True)

    areas_by_id = {row["area_id"]: row for row in handler.areas}
    areas = list(areas_by_id.values())

    ways_cells = {cell: ids for cell, ids in sorted(handler.ways_cells.items(), key=lambda kv: kv[0])}
    areas_cells = _build_cells(areas, "area_id", args.grid_scale)

    ways_idx_payload = {
        "schema_version": 1,
        "grid_scale": args.grid_scale,
        "ways_count": handler.ways_count,
        "cells": ways_cells,
    }

    areas_sorted = sorted(areas, key=lambda r: _id_sort_key(r["area_id"]))
    areas_idx_payload = {
        "schema_version": 1,
        "grid_scale": args.grid_scale,
        "areas_count": len(areas),
        "cells": areas_cells,
        "areas": areas_sorted,
    }

    _write_json(args.ways_idx_out, ways_idx_payload)
    _write_json(args.areas_idx_out, areas_idx_payload)
    _write_json(
        args.ways_lookup_out,
        {
            "schema_version": 1,
            "index": handler.ways_lookup,
        },
    )
    _write_json(
        args.ways_geom_lookup_out,
        {
            "schema_version": 1,
            "index": handler.ways_geom_lookup,
        },
    )

    print(f"Packed runtime artifacts from {args.input_pbf}")
    print(f"- {args.ways_meta_out} ({handler.ways_count} ways)")
    print(f"- {args.ways_idx_out} ({len(ways_cells)} grid cells)")
    print(f"- {args.areas_idx_out} ({len(areas)} areas, {len(areas_cells)} grid cells)")
    print(f"- {args.ways_lookup_out} ({len(handler.ways_lookup)} offsets)")
    print(f"- {args.ways_geom_out} ({handler.ways_count} ways, max_points={args.max_geom_points})")
    print(f"- {args.ways_geom_lookup_out} ({len(handler.ways_geom_lookup)} offsets)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
