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
import math
import sqlite3
import sys
from collections import defaultdict, deque
from heapq import heappop, heappush
from pathlib import Path
from typing import Dict, Iterator, List, Set, Tuple

try:
    import osmium
except Exception:
    osmium = None


EARTH_RADIUS_M = 6378137.0
MAX_MERCATOR_LAT = 85.05112878
PLACE_VALUES = {"city", "town", "village", "hamlet"}


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
        sampled: List[Tuple[float, float]] = []
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


def _parse_admin_levels(raw: str) -> List[str]:
    raw_levels = {part.strip() for part in raw.split(",") if part.strip()}
    if not raw_levels or any(not level.isdigit() for level in raw_levels):
        raise ValueError("admin levels must be a comma-separated list of integers")
    return sorted(raw_levels, key=int)


def _is_truthy_osm_tag(value: str | None) -> bool:
    return (value or "").strip().lower() in {"yes", "true", "1"}


def _coord_key(lon: float, lat: float) -> str:
    return f"{round(lon * 10_000_000)}:{round(lat * 10_000_000)}"


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_m = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    return earth_radius_m * (2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a))))


def _points_length_m(points: list) -> float:
    total = 0.0
    for first, second in zip(points, points[1:]):
        if (
            not isinstance(first, list)
            or not isinstance(second, list)
            or len(first) < 2
            or len(second) < 2
        ):
            continue
        lat1, lon1 = first[0], first[1]
        lat2, lon2 = second[0], second[1]
        if not all(isinstance(value, (int, float)) for value in (lat1, lon1, lat2, lon2)):
            continue
        total += _haversine_m(float(lat1), float(lon1), float(lat2), float(lon2))
    return total


class _CityContextExtractor(osmium.SimpleHandler if osmium is not None else object):
    def __init__(
        self,
        tile_size_m: int,
        max_ring_points: int,
        max_boundary_tiles: int,
        progress_every: int,
        label_admin_levels: Set[str],
    ) -> None:
        if osmium is None:
            raise RuntimeError("pyosmium unavailable")
        super().__init__()
        self.tile_size_m = tile_size_m
        self.max_ring_points = max_ring_points
        self.max_boundary_tiles = max_boundary_tiles
        self.progress_every = progress_every
        self.label_admin_levels = set(label_admin_levels)

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
        if admin_level_raw not in self.label_admin_levels:
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
            for node in outer:
                outer_pts.append((float(node.lon), float(node.lat)))
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
                for node in inner:
                    hole_pts.append((float(node.lon), float(node.lat)))
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
    rows = conn.execute(
        """
        SELECT place, name, min_lon, min_lat
        FROM areas
        WHERE geometry_type='Point'
          AND place IN ('city','town','village','hamlet')
          AND name IS NOT NULL
        """
    ).fetchall()

    place_rows: List[Tuple] = []
    place_rtree_rows: List[Tuple] = []
    row_id = 0
    for place, name, lon, lat in rows:
        row_id += 1
        lon_f = float(lon)
        lat_f = float(lat)
        place_rows.append((row_id, place, name, lon_f, lat_f))
        place_rtree_rows.append((row_id, lon_f, lon_f, lat_f, lat_f))

    for i in range(0, len(place_rows), batch_size):
        conn.executemany(
            "INSERT INTO city_place(row_id, place, name, lon, lat) VALUES (?, ?, ?, ?, ?)",
            place_rows[i : i + batch_size],
        )
    for i in range(0, len(place_rtree_rows), batch_size):
        conn.executemany(
            "INSERT INTO city_place_rtree(row_id, min_lon, max_lon, min_lat, max_lat) VALUES(?, ?, ?, ?, ?)",
            place_rtree_rows[i : i + batch_size],
        )
    return len(place_rows)


def _build_corridor_progress(conn: sqlite3.Connection) -> tuple[int, int, int]:
    conn.executescript(
        """
        CREATE TABLE corridor_progress (
          corridor_kind TEXT NOT NULL,
          corridor_id INTEGER NOT NULL,
          side_node_key TEXT NOT NULL,
          way_id INTEGER NOT NULL,
          start_depth_m REAL NOT NULL,
          end_depth_m REAL NOT NULL,
          start_depth_nodes INTEGER NOT NULL,
          end_depth_nodes INTEGER NOT NULL,
          corridor_span_m REAL NOT NULL,
          corridor_span_nodes INTEGER NOT NULL,
          PRIMARY KEY(corridor_kind, corridor_id, side_node_key, way_id)
        );
        CREATE INDEX idx_corridor_progress_way_id ON corridor_progress(way_id);
        CREATE INDEX idx_corridor_progress_corridor ON corridor_progress(corridor_kind, corridor_id, side_node_key);

        CREATE TABLE corridor_pairs (
          corridor_kind TEXT NOT NULL,
          corridor_id INTEGER NOT NULL,
          side_node_key TEXT NOT NULL,
          paired_kind TEXT NOT NULL,
          paired_corridor_id INTEGER NOT NULL,
          PRIMARY KEY(corridor_kind, corridor_id, side_node_key, paired_kind, paired_corridor_id)
        );
        CREATE INDEX idx_corridor_pairs_main ON corridor_pairs(corridor_kind, corridor_id, side_node_key);
        CREATE INDEX idx_corridor_pairs_paired ON corridor_pairs(paired_kind, paired_corridor_id);
        """
    )

    way_rows = conn.execute(
        """
        SELECT
          way_id,
          ref_norm,
          highway,
          tunnel_flag,
          start_node_key,
          end_node_key,
          way_length_m
        FROM way_endpoints
        """
    ).fetchall()
    if not way_rows:
        return (0, 0, 0)

    way_info: Dict[int, dict] = {}
    node_to_way_ids: Dict[str, Set[int]] = defaultdict(set)
    for way_id, ref_norm, highway, tunnel_flag, start_node_key, end_node_key, way_length_m in way_rows:
        normalized_way_id = int(way_id)
        way_info[normalized_way_id] = {
            "ref_norm": ref_norm or "",
            "highway": (highway or "").strip().lower(),
            "tunnel_flag": int(tunnel_flag or 0),
            "start_node_key": start_node_key,
            "end_node_key": end_node_key,
            "length_m": float(way_length_m or 0.0),
        }
        node_to_way_ids[start_node_key].add(normalized_way_id)
        node_to_way_ids[end_node_key].add(normalized_way_id)

    link_rows = conn.execute(
        """
        SELECT
          wl.way_id,
          wl.linked_way_id,
          wl.shared_node_key
        FROM way_links wl
        """
    ).fetchall()

    neighbors_by_way: Dict[int, Set[int]] = defaultdict(set)
    linked_nodes_by_way: Dict[int, Dict[str, Set[int]]] = defaultdict(lambda: defaultdict(set))
    for source_way_id, linked_way_id, shared_node_key in link_rows:
        source_way_id = int(source_way_id)
        linked_way_id = int(linked_way_id)
        if source_way_id == linked_way_id:
            continue
        neighbors_by_way[source_way_id].add(linked_way_id)
        if shared_node_key:
            linked_nodes_by_way[source_way_id][shared_node_key].add(linked_way_id)

    def other_node_key(way_id: int, node_key: str) -> str:
        info = way_info[way_id]
        return info["end_node_key"] if info["start_node_key"] == node_key else info["start_node_key"]

    def way_node_keys(way_id: int) -> tuple[str, str]:
        info = way_info[way_id]
        return (info["start_node_key"], info["end_node_key"])

    def corridor_kind_for_way(way_id: int) -> str | None:
        info = way_info[way_id]
        if info["tunnel_flag"] == 1:
            return "tunnel"
        if info["highway"] == "motorway":
            return "motorway"
        return None

    def compatible_main_way(source_way_id: int, target_way_id: int, corridor_kind: str) -> bool:
        source = way_info[source_way_id]
        target = way_info[target_way_id]
        if corridor_kind == "tunnel":
            if source["tunnel_flag"] != 1 or target["tunnel_flag"] != 1:
                return False
        elif corridor_kind == "motorway":
            if source["highway"] != "motorway" or target["highway"] != "motorway":
                return False
        else:
            return False
        source_ref = source["ref_norm"]
        target_ref = target["ref_norm"]
        return not (source_ref and target_ref and source_ref != target_ref)

    def paired_kind_for_main_kind(main_kind: str) -> str:
        return "surface" if main_kind == "tunnel" else "motorway_link"

    def paired_way_allowed(main_kind: str, way_id: int, main_ref_norms: Set[str]) -> bool:
        info = way_info[way_id]
        if main_kind == "tunnel":
            if info["tunnel_flag"] == 1:
                return False
            if info["highway"] in {"motorway", "motorway_link"}:
                return False
            if main_ref_norms:
                return info["ref_norm"] in main_ref_norms
            return True
        if main_kind == "motorway":
            return info["highway"] == "motorway_link"
        return False

    def collect_component_way_ids(seed_way_id: int, corridor_kind: str, remaining_way_ids: Set[int]) -> Set[int]:
        component_way_ids = {seed_way_id}
        pending_way_ids = [seed_way_id]
        while pending_way_ids:
            current_way_id = pending_way_ids.pop()
            for neighbor_way_id in neighbors_by_way.get(current_way_id, set()):
                if neighbor_way_id not in remaining_way_ids:
                    continue
                if not compatible_main_way(current_way_id, neighbor_way_id, corridor_kind):
                    continue
                remaining_way_ids.remove(neighbor_way_id)
                component_way_ids.add(neighbor_way_id)
                pending_way_ids.append(neighbor_way_id)
        return component_way_ids

    def component_node_index(component_way_ids: Set[int]) -> Dict[str, Set[int]]:
        index: Dict[str, Set[int]] = defaultdict(set)
        for way_id in component_way_ids:
            start_node_key, end_node_key = way_node_keys(way_id)
            index[start_node_key].add(way_id)
            index[end_node_key].add(way_id)
        return index

    def component_portal_nodes(component_way_ids: Set[int], corridor_kind: str) -> Set[str]:
        portals: Set[str] = set()
        for way_id in component_way_ids:
            for shared_node_key, linked_way_ids in linked_nodes_by_way.get(way_id, {}).items():
                for linked_way_id in linked_way_ids:
                    if linked_way_id in component_way_ids:
                        continue
                    linked_info = way_info.get(linked_way_id)
                    if linked_info is None:
                        continue
                    if corridor_kind == "tunnel":
                        if linked_info["tunnel_flag"] == 0:
                            portals.add(shared_node_key)
                    elif corridor_kind == "motorway":
                        if linked_info["highway"] == "motorway_link":
                            portals.add(shared_node_key)
            if corridor_kind == "motorway":
                start_node_key, end_node_key = way_node_keys(way_id)
                for node_key in (start_node_key, end_node_key):
                    linked_mainline = [
                        linked_way_id
                        for linked_way_id in linked_nodes_by_way.get(way_id, {}).get(node_key, set())
                        if linked_way_id in component_way_ids
                    ]
                    if not linked_mainline:
                        portals.add(node_key)
        return portals

    def dijkstra_distances(graph: Dict[str, list[tuple[str, float]]], start_node_key: str) -> Dict[str, float]:
        distances: Dict[str, float] = {start_node_key: 0.0}
        queue: list[tuple[float, str]] = [(0.0, start_node_key)]
        while queue:
            current_distance, node_key = heappop(queue)
            if current_distance > distances.get(node_key, math.inf):
                continue
            for neighbor_node_key, edge_weight in graph.get(node_key, []):
                next_distance = current_distance + edge_weight
                if next_distance < distances.get(neighbor_node_key, math.inf):
                    distances[neighbor_node_key] = next_distance
                    heappush(queue, (next_distance, neighbor_node_key))
        return distances

    def bfs_node_distances(graph: Dict[str, list[tuple[str, float]]], start_node_key: str) -> Dict[str, int]:
        distances: Dict[str, int] = {start_node_key: 0}
        queue: deque[str] = deque([start_node_key])
        while queue:
            node_key = queue.popleft()
            current_distance = distances[node_key]
            for neighbor_node_key, _ in graph.get(node_key, []):
                if neighbor_node_key in distances:
                    continue
                distances[neighbor_node_key] = current_distance + 1
                queue.append(neighbor_node_key)
        return distances

    def graph_for_way_ids(component_way_ids: Set[int]) -> Dict[str, list[tuple[str, float]]]:
        graph: Dict[str, list[tuple[str, float]]] = defaultdict(list)
        for way_id in component_way_ids:
            start_node_key, end_node_key = way_node_keys(way_id)
            edge_length_m = max(float(way_info[way_id]["length_m"]), 0.1)
            graph[start_node_key].append((end_node_key, edge_length_m))
            graph[end_node_key].append((start_node_key, edge_length_m))
        return graph

    def insert_progress_rows(corridor_kind: str, corridor_id: int, corridor_way_ids: Set[int], side_node_keys: Set[str]) -> list[tuple]:
        if not corridor_way_ids or not side_node_keys:
            return []
        graph = graph_for_way_ids(corridor_way_ids)
        sorted_side_node_keys = sorted(side_node_keys)
        rows: list[tuple] = []
        for side_node_key in sorted_side_node_keys:
            distances = dijkstra_distances(graph, side_node_key)
            node_distances = bfs_node_distances(graph, side_node_key)
            span_m = max(
                (distances.get(other_node_key, 0.0) for other_node_key in sorted_side_node_keys if other_node_key != side_node_key),
                default=max(distances.values(), default=0.0),
            )
            span_nodes = max(
                (node_distances.get(other_node_key, 0) for other_node_key in sorted_side_node_keys if other_node_key != side_node_key),
                default=max(node_distances.values(), default=0),
            )
            for way_id in corridor_way_ids:
                start_node_key, end_node_key = way_node_keys(way_id)
                start_depth_m = distances.get(start_node_key)
                end_depth_m = distances.get(end_node_key)
                start_depth_nodes = node_distances.get(start_node_key)
                end_depth_nodes = node_distances.get(end_node_key)
                if (
                    start_depth_m is None
                    or end_depth_m is None
                    or start_depth_nodes is None
                    or end_depth_nodes is None
                ):
                    continue
                rows.append(
                    (
                        corridor_kind,
                        corridor_id,
                        side_node_key,
                        way_id,
                        start_depth_m,
                        end_depth_m,
                        start_depth_nodes,
                        end_depth_nodes,
                        span_m,
                        span_nodes,
                    )
                )
        return rows

    def decompose_linear_segments(component_way_ids: Set[int], portal_nodes: Set[str]) -> List[dict]:
        component_nodes = component_node_index(component_way_ids)
        boundary_nodes = set(portal_nodes)
        for node_key, node_way_ids in component_nodes.items():
            if len(node_way_ids) != 2:
                boundary_nodes.add(node_key)
        if not boundary_nodes:
            boundary_nodes = set(component_nodes.keys())

        visited_way_ids: Set[int] = set()
        segments: List[dict] = []
        for start_node_key in sorted(boundary_nodes):
            for start_way_id in sorted(component_nodes.get(start_node_key, set())):
                if start_way_id in visited_way_ids:
                    continue
                segment_way_ids: Set[int] = set()
                current_node_key = start_node_key
                current_way_id = start_way_id
                end_node_key = start_node_key
                while True:
                    if current_way_id in segment_way_ids:
                        break
                    segment_way_ids.add(current_way_id)
                    visited_way_ids.add(current_way_id)
                    next_node_key = other_node_key(current_way_id, current_node_key)
                    end_node_key = next_node_key
                    next_way_ids = [
                        neighbor_way_id
                        for neighbor_way_id in component_nodes.get(next_node_key, set())
                        if neighbor_way_id != current_way_id
                    ]
                    if next_node_key in boundary_nodes or len(next_way_ids) != 1:
                        break
                    current_node_key = next_node_key
                    current_way_id = next_way_ids[0]
                if segment_way_ids:
                    segments.append(
                        {
                            "way_ids": segment_way_ids,
                            "side_node_keys": {start_node_key, end_node_key},
                        }
                    )
        for way_id in sorted(component_way_ids - visited_way_ids):
            start_node_key, end_node_key = way_node_keys(way_id)
            segments.append({"way_ids": {way_id}, "side_node_keys": {start_node_key, end_node_key}})
        return segments

    def trace_paired_chain(
        portal_node_key: str,
        seed_way_id: int,
        main_kind: str,
        main_ref_norms: Set[str],
    ) -> dict | None:
        if not paired_way_allowed(main_kind, seed_way_id, main_ref_norms):
            return None
        segment_way_ids: Set[int] = set()
        current_node_key = portal_node_key
        current_way_id = seed_way_id
        end_node_key = portal_node_key
        while True:
            if current_way_id in segment_way_ids:
                break
            segment_way_ids.add(current_way_id)
            next_node_key = other_node_key(current_way_id, current_node_key)
            end_node_key = next_node_key
            next_way_ids = [
                neighbor_way_id
                for neighbor_way_id in node_to_way_ids.get(next_node_key, set())
                if neighbor_way_id != current_way_id and paired_way_allowed(main_kind, neighbor_way_id, main_ref_norms)
            ]
            if len(next_way_ids) != 1:
                break
            current_node_key = next_node_key
            current_way_id = next_way_ids[0]
        if not segment_way_ids:
            return None
        return {"way_ids": segment_way_ids, "side_node_keys": {portal_node_key, end_node_key}}

    insert_rows: list[tuple] = []
    pair_rows: Set[tuple] = set()
    corridor_count = 0
    next_corridor_id = 1
    main_corridors: List[dict] = []
    corridor_cache: Dict[tuple[str, frozenset[int], frozenset[str]], int] = {}

    def ensure_corridor(corridor_kind: str, segment: dict) -> int:
        nonlocal next_corridor_id, corridor_count
        cache_key = (
            corridor_kind,
            frozenset(segment["way_ids"]),
            frozenset(segment["side_node_keys"]),
        )
        cached_corridor_id = corridor_cache.get(cache_key)
        if cached_corridor_id is not None:
            return cached_corridor_id
        corridor_id = next_corridor_id
        next_corridor_id += 1
        corridor_count += 1
        corridor_cache[cache_key] = corridor_id
        insert_rows.extend(
            insert_progress_rows(
                corridor_kind,
                corridor_id,
                set(segment["way_ids"]),
                set(segment["side_node_keys"]),
            )
        )
        return corridor_id

    for corridor_kind in ("tunnel", "motorway"):
        eligible_way_ids = {
            way_id
            for way_id in way_info
            if corridor_kind_for_way(way_id) == corridor_kind
        }
        remaining_way_ids = set(eligible_way_ids)
        while remaining_way_ids:
            seed_way_id = remaining_way_ids.pop()
            component_way_ids = collect_component_way_ids(seed_way_id, corridor_kind, remaining_way_ids)
            portal_nodes = component_portal_nodes(component_way_ids, corridor_kind)
            if not portal_nodes:
                continue
            for segment in decompose_linear_segments(component_way_ids, portal_nodes):
                corridor_id = ensure_corridor(corridor_kind, segment)
                main_corridors.append(
                    {
                        "kind": corridor_kind,
                        "corridor_id": corridor_id,
                        "way_ids": set(segment["way_ids"]),
                        "side_node_keys": set(segment["side_node_keys"]),
                        "ref_norms": {
                            way_info[way_id]["ref_norm"]
                            for way_id in segment["way_ids"]
                            if way_info[way_id]["ref_norm"]
                        },
                    }
                )

    for main_corridor in main_corridors:
        main_kind = main_corridor["kind"]
        paired_kind = paired_kind_for_main_kind(main_kind)
        main_ref_norms: Set[str] = main_corridor["ref_norms"]
        for side_node_key in sorted(main_corridor["side_node_keys"]):
            seed_way_ids: Set[int] = set()
            for main_way_id in main_corridor["way_ids"]:
                for linked_way_id in linked_nodes_by_way.get(main_way_id, {}).get(side_node_key, set()):
                    if linked_way_id in main_corridor["way_ids"]:
                        continue
                    if paired_way_allowed(main_kind, linked_way_id, main_ref_norms):
                        seed_way_ids.add(linked_way_id)
            for seed_way_id in sorted(seed_way_ids):
                segment = trace_paired_chain(side_node_key, seed_way_id, main_kind, main_ref_norms)
                if segment is None:
                    continue
                paired_corridor_id = ensure_corridor(paired_kind, segment)
                pair_rows.add(
                    (
                        main_kind,
                        int(main_corridor["corridor_id"]),
                        side_node_key,
                        paired_kind,
                        paired_corridor_id,
                    )
                )

    if insert_rows:
        conn.executemany(
            """
            INSERT INTO corridor_progress(
              corridor_kind, corridor_id, side_node_key, way_id,
              start_depth_m, end_depth_m, start_depth_nodes, end_depth_nodes,
              corridor_span_m, corridor_span_nodes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            insert_rows,
        )
    if pair_rows:
        conn.executemany(
            """
            INSERT INTO corridor_pairs(
              corridor_kind, corridor_id, side_node_key, paired_kind, paired_corridor_id
            ) VALUES (?, ?, ?, ?, ?)
            """,
            sorted(pair_rows),
        )
    if insert_rows or pair_rows:
        conn.commit()
    return (corridor_count, len(insert_rows), len(pair_rows))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build v3 SQLite/SpatiaLite-style speed map DB")
    parser.add_argument("--v1-dist", required=True, help="Path to mapdata/dist/<region>")
    parser.add_argument("--out-db", required=True, help="Output SQLite database path")
    parser.add_argument("--input-pbf", help="Optional source PBF to build exact city polygon tables")
    parser.add_argument("--batch-size", type=int, default=20000, help="Insert batch size (default: 20000)")
    parser.add_argument("--progress-every", type=int, default=250000, help="Progress logging interval")
    parser.add_argument("--city-tile-size-m", type=int, default=4096, help="Tile size in EPSG:3857 meters for city boundary prefiltering")
    parser.add_argument("--max-city-tiles", type=int, default=512, help="Maximum tile fan-out before center-tile fallback")
    parser.add_argument("--max-city-ring-points", type=int, default=96, help="Maximum retained points per city boundary ring")
    parser.add_argument(
        "--city-admin-levels",
        default="6,8,9",
        help="Comma-separated admin levels used for primary municipal city labels (default: 6,8,9)",
    )
    parser.add_argument(
        "--build-way-links",
        action="store_true",
        help="Build endpoint-based way_links topology table",
    )
    parser.add_argument(
        "--way-links-schema",
        choices=("minimal", "detailed"),
        default="detailed",
        help="Topology schema for way_links: minimal=way pairs only, detailed=pair + shared_ref + shared_node_key",
    )
    parser.add_argument(
        "--corridor-mode",
        choices=("none", "paired"),
        default="none",
        help="Corridor precompute mode (requires detailed way-links for paired; default: none)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    v1_dist = Path(args.v1_dist)
    out_db = Path(args.out_db)
    try:
        city_boundary_admin_levels = _parse_admin_levels(args.city_admin_levels)
    except ValueError as exc:
        print(f"--city-admin-levels invalid: {exc}", file=sys.stderr)
        return 1
    if args.batch_size < 100:
        print("--batch-size must be >= 100", file=sys.stderr)
        return 1
    if args.city_tile_size_m < 256:
        print("--city-tile-size-m must be >= 256", file=sys.stderr)
        return 1
    if args.max_city_tiles < 1:
        print("--max-city-tiles must be >= 1", file=sys.stderr)
        return 1
    if args.max_city_ring_points < 4:
        print("--max-city-ring-points must be >= 4", file=sys.stderr)
        return 1
    if args.corridor_mode != "none" and not args.build_way_links:
        print("--corridor-mode requires --build-way-links", file=sys.stderr)
        return 1
    if args.corridor_mode == "paired" and args.way_links_schema != "detailed":
        print("--corridor-mode paired requires --way-links-schema detailed", file=sys.stderr)
        return 1

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
    if input_pbf and osmium is None:
        print("pyosmium is required to build exact city polygon tables", file=sys.stderr)
        return 1

    out_db.parent.mkdir(parents=True, exist_ok=True)
    if out_db.exists():
        out_db.unlink()

    conn = sqlite3.connect(str(out_db))
    conn.execute("PRAGMA journal_mode=MEMORY")
    conn.execute("PRAGMA synchronous=OFF")
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
          way_id INTEGER PRIMARY KEY,
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

        CREATE VIRTUAL TABLE ways_rtree USING rtree(
          way_id,
          min_lon, max_lon,
          min_lat, max_lat
        );

        CREATE TABLE way_geom (
          way_id INTEGER PRIMARY KEY,
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

    if args.build_way_links:
        if args.way_links_schema == "detailed":
            conn.executescript(
                """
                CREATE TABLE way_endpoints (
                  way_id INTEGER PRIMARY KEY,
                  ref_norm TEXT,
                  highway TEXT,
                  tunnel_flag INTEGER NOT NULL DEFAULT 0,
                  start_node_key TEXT NOT NULL,
                  start_lon REAL NOT NULL,
                  start_lat REAL NOT NULL,
                  end_node_key TEXT NOT NULL,
                  end_lon REAL NOT NULL,
                  end_lat REAL NOT NULL,
                  way_length_m REAL NOT NULL
                );

                CREATE TABLE way_links (
                  way_id INTEGER NOT NULL,
                  linked_way_id INTEGER NOT NULL,
                  shared_ref INTEGER NOT NULL DEFAULT 0,
                  shared_node_key TEXT NOT NULL,
                  PRIMARY KEY(way_id, linked_way_id, shared_node_key)
                );
                """
            )
        else:
            conn.executescript(
                """
                CREATE TABLE way_endpoints (
                  way_id INTEGER PRIMARY KEY,
                  ref_norm TEXT,
                  highway TEXT,
                  tunnel_flag INTEGER NOT NULL DEFAULT 0,
                  start_node_key TEXT NOT NULL,
                  start_lon REAL NOT NULL,
                  start_lat REAL NOT NULL,
                  end_node_key TEXT NOT NULL,
                  end_lon REAL NOT NULL,
                  end_lat REAL NOT NULL,
                  way_length_m REAL NOT NULL
                );

                CREATE TABLE way_links (
                  way_id INTEGER NOT NULL,
                  linked_way_id INTEGER NOT NULL,
                  PRIMARY KEY(way_id, linked_way_id)
                );
                """
            )

    conn.executemany(
        "INSERT INTO metadata(key, value) VALUES(?, ?)",
        [
            ("schema_version", "1"),
            ("backend", backend),
            ("source_v1_dist", str(v1_dist)),
            ("source_input_pbf", str(input_pbf) if input_pbf else ""),
            ("city_boundary_admin_levels", ",".join(city_boundary_admin_levels)),
            ("city_tile_size_m", str(args.city_tile_size_m)),
            ("max_city_tiles", str(args.max_city_tiles)),
            ("max_city_ring_points", str(args.max_city_ring_points)),
            (
                "way_links_mode",
                f"shared_endpoint_{args.way_links_schema}" if args.build_way_links else "none",
            ),
        ],
    )

    ways_batch: List[Tuple] = []
    ways_rtree_batch: List[Tuple] = []
    geom_batch: List[Tuple] = []
    endpoints_batch: List[Tuple] = []
    way_rows = 0

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

            way_rows += 1
            way_id = int(meta["way_id"])
            points = geom.get("points")
            if not isinstance(points, list):
                points = []

            ways_batch.append(
                (
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
                    float(meta["min_lon"]),
                    float(meta["min_lat"]),
                    float(meta["max_lon"]),
                    float(meta["max_lat"]),
                )
            )
            ways_rtree_batch.append(
                (
                    way_id,
                    float(meta["min_lon"]),
                    float(meta["max_lon"]),
                    float(meta["min_lat"]),
                    float(meta["max_lat"]),
                )
            )
            geom_batch.append((way_id, json.dumps(points, separators=(",", ":"))))
            if args.build_way_links:
                ref_norm = (meta.get("ref") or "").replace(" ", "").upper()
                first_lon = float(meta["first_lon"])
                first_lat = float(meta["first_lat"])
                last_lon = float(meta["last_lon"])
                last_lat = float(meta["last_lat"])
                endpoints_batch.append(
                    (
                        way_id,
                        ref_norm,
                        meta.get("highway"),
                        1 if _is_truthy_osm_tag(meta.get("tunnel")) else 0,
                        _coord_key(first_lon, first_lat),
                        first_lon,
                        first_lat,
                        _coord_key(last_lon, last_lat),
                        last_lon,
                        last_lat,
                        _points_length_m(points),
                    )
                )

            if len(ways_batch) >= args.batch_size:
                conn.executemany(
                    """
                    INSERT INTO ways(
                      way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed,
                      approx_heading_deg, service, tunnel,
                      min_lon, min_lat, max_lon, max_lat
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    ways_batch,
                )
                conn.executemany(
                    "INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat) VALUES(?, ?, ?, ?, ?)",
                    ways_rtree_batch,
                )
                conn.executemany(
                    "INSERT INTO way_geom(way_id, points_json) VALUES(?, ?)",
                    geom_batch,
                )
                if args.build_way_links and endpoints_batch:
                    conn.executemany(
                        """
                        INSERT INTO way_endpoints(
                          way_id, ref_norm, highway, tunnel_flag,
                          start_node_key, start_lon, start_lat,
                          end_node_key, end_lon, end_lat, way_length_m
                        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        endpoints_batch,
                    )
                conn.commit()
                ways_batch.clear()
                ways_rtree_batch.clear()
                geom_batch.clear()
                endpoints_batch.clear()

            if way_rows % args.progress_every == 0:
                print(f"  ways inserted: {way_rows}", file=sys.stderr)

    if ways_batch:
        conn.executemany(
            """
            INSERT INTO ways(
              way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed,
              approx_heading_deg, service, tunnel,
              min_lon, min_lat, max_lon, max_lat
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ways_batch,
        )
        conn.executemany(
            "INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat) VALUES(?, ?, ?, ?, ?)",
            ways_rtree_batch,
        )
        conn.executemany(
            "INSERT INTO way_geom(way_id, points_json) VALUES(?, ?)",
            geom_batch,
        )
        if args.build_way_links and endpoints_batch:
            conn.executemany(
                """
                INSERT INTO way_endpoints(
                  way_id, ref_norm, highway, tunnel_flag,
                  start_node_key, start_lon, start_lat,
                  end_node_key, end_lon, end_lat, way_length_m
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                endpoints_batch,
            )
        conn.commit()

    print(f"Ways done: {way_rows}", file=sys.stderr)

    if args.build_way_links:
        conn.executescript(
            """
            CREATE TEMP TABLE endpoint_nodes AS
            SELECT
              way_id,
              ref_norm,
              'start' AS endpoint_side,
              start_node_key AS node_key,
              start_lon AS lon,
              start_lat AS lat
            FROM way_endpoints
            UNION ALL
            SELECT
              way_id,
              ref_norm,
              'end' AS endpoint_side,
              end_node_key AS node_key,
              end_lon AS lon,
              end_lat AS lat
            FROM way_endpoints;

            CREATE INDEX idx_endpoint_nodes_key ON endpoint_nodes(node_key);
            """
        )
        if args.way_links_schema == "detailed":
            conn.executescript(
                """
                INSERT OR IGNORE INTO way_links(
                  way_id, linked_way_id, shared_ref, shared_node_key
                )
                SELECT
                  e1.way_id,
                  e2.way_id,
                  CASE
                    WHEN e1.ref_norm <> '' AND e1.ref_norm = e2.ref_norm THEN 1
                    ELSE 0
                  END,
                  e1.node_key
                FROM endpoint_nodes e1
                JOIN endpoint_nodes e2
                  ON e1.node_key = e2.node_key
                 AND e1.way_id <> e2.way_id;

                CREATE INDEX idx_way_links_way_id ON way_links(way_id);
                """
            )
        else:
            conn.executescript(
                """
                INSERT OR IGNORE INTO way_links(
                  way_id, linked_way_id
                )
                SELECT DISTINCT
                  e1.way_id,
                  e2.way_id
                FROM endpoint_nodes e1
                JOIN endpoint_nodes e2
                  ON e1.node_key = e2.node_key
                 AND e1.way_id <> e2.way_id;

                CREATE INDEX idx_way_links_way_id ON way_links(way_id);
                """
            )

        corridor_count = 0
        corridor_progress_count = 0
        corridor_pair_count = 0
        if args.corridor_mode == "paired":
            corridor_count, corridor_progress_count, corridor_pair_count = _build_corridor_progress(conn)
        conn.executescript(
            """
            DROP TABLE endpoint_nodes;
            DROP TABLE way_endpoints;
            """
        )
        way_links_count = conn.execute("SELECT COUNT(*) FROM way_links").fetchone()[0]
        conn.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)",
            ("way_links_count", str(way_links_count)),
        )
        conn.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)",
            ("corridor_progress_mode", "paired_portal_chain_v1" if args.corridor_mode == "paired" else "none"),
        )
        conn.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)",
            ("corridor_count", str(corridor_count)),
        )
        conn.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)",
            ("corridor_progress_count", str(corridor_progress_count)),
        )
        conn.execute(
            "INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)",
            ("corridor_pair_count", str(corridor_pair_count)),
        )
        conn.commit()
        print(f"Way links done: {way_links_count}", file=sys.stderr)
        if args.corridor_mode == "paired":
            print(
                f"Corridor progress done: components={corridor_count} rows={corridor_progress_count} pairs={corridor_pair_count}",
                file=sys.stderr,
            )

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

    conn.execute("CREATE INDEX idx_areas_place_admin ON areas(place, admin_level, boundary)")

    city_stats = {
        "city_boundaries": 0,
        "city_rings": 0,
        "city_tiles": 0,
        "city_tile_fallback_boundaries": 0,
        "city_places": 0,
    }
    if input_pbf:
        print(f"Extracting city polygons from PBF: {input_pbf}", file=sys.stderr)
        extractor = _CityContextExtractor(
            tile_size_m=args.city_tile_size_m,
            max_ring_points=args.max_city_ring_points,
            max_boundary_tiles=args.max_city_tiles,
            progress_every=args.progress_every,
            label_admin_levels=set(city_boundary_admin_levels),
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

    if city_stats["city_places"] == 0:
        city_stats["city_places"] = _populate_city_context_from_areas(conn, args.batch_size)

    conn.execute("CREATE INDEX idx_city_boundary_osm ON city_boundary(osm_type, osm_id)")
    conn.execute("CREATE INDEX idx_city_ring_boundary ON city_ring(boundary_row_id, outer_index, is_hole, ring_index)")
    conn.execute("CREATE INDEX idx_city_tile_xy ON city_tile(tile_x, tile_y, boundary_row_id)")
    conn.execute("CREATE INDEX idx_city_tile_boundary ON city_tile(boundary_row_id)")
    conn.execute("CREATE INDEX idx_city_place_place_name ON city_place(place, name)")

    for key, value in (
        ("city_boundaries", str(city_stats["city_boundaries"])),
        ("city_rings", str(city_stats["city_rings"])),
        ("city_tiles", str(city_stats["city_tiles"])),
        ("city_tile_fallback_boundaries", str(city_stats["city_tile_fallback_boundaries"])),
        ("city_places", str(city_stats["city_places"])),
    ):
        conn.execute("INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)", (key, value))

    conn.commit()
    conn.close()

    print(
        "City context stats: boundaries={city_boundaries}, rings={city_rings}, tiles={city_tiles}, places={city_places}, tile_fallback={city_tile_fallback_boundaries}".format(
            **city_stats
        ),
        file=sys.stderr,
    )
    print(f"Wrote v3 DB: {out_db}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
