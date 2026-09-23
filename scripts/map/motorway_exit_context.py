"""Bounded, directed motorway-exit approaches across OSM way splits.

This is topology evidence, not a declaration that a sign applies to a lane.
Only endpoint-connected, legally directed motorway/mainline segments are used;
nearby unconnected roads and incoming entrance ramps cannot create an approach.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from heapq import heappop, heappush
import json
import math
from pathlib import Path
import sqlite3


def bearing(a, b):
    lat1, lon1, lat2, lon2 = map(math.radians, (*a, *b))
    delta = lon2 - lon1
    return math.degrees(math.atan2(math.sin(delta) * math.cos(lat2),
        math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(delta))) % 360


def build_motorway_exit_context(conn, ways_meta: Path, maximum_distance_m=350.0):
    roads = {}
    for line in ways_meta.open(encoding="utf-8"):
        row = json.loads(line)
        if row.get("highway") not in {"motorway", "motorway_link"}:
            continue
        tags = row.get("raw_tags", {})
        # Motorways (including their ramps) are implicitly one-way in OSM.
        direction = str(tags.get("oneway", "yes")).lower()
        if direction not in {"yes", "1", "true", "-1", "no", "0", "false"}:
            continue  # Reversible/alternating/conditional direction is unresolved.
        if any(key.startswith("oneway:") for key in tags):
            continue
        roads[int(row["way_id"])] = (row["highway"], direction)
    outgoing = defaultdict(list)
    starts = []
    for way, start, end, length, geometry in conn.execute("""
        SELECT e.way_id,e.start_node_key,e.end_node_key,e.way_length_m,g.points_json
        FROM way_endpoints e JOIN way_geom g USING(way_id)
        WHERE e.highway IN ('motorway','motorway_link')
    """):
        if way not in roads or length <= 0:
            continue
        road_class, direction = roads[way]
        points = json.loads(geometry)
        if len(points) < 2:
            continue
        for reverse in ([True] if direction == "-1" else [False, True] if direction in {"no", "0", "false"} else [False]):
            oriented = list(reversed(points)) if reverse else points
            origin, destination = (end, start) if reverse else (start, end)
            next_point = next((p for p in oriented[1:] if p != oriented[0]), None)
            if next_point is None:
                continue
            heading = bearing(oriented[0], next_point)
            outgoing[origin].append((way, destination, length, road_class, heading))
            if road_class == "motorway":
                starts.append((way, "start" if reverse else "end", destination))
    rows = []
    for origin_way, side, origin in starts:
        queue = [(0.0, origin)]
        best = {origin: 0.0}
        exits = {}
        while queue:
            distance, node = heappop(queue)
            if distance > best[node] or distance > maximum_distance_m:
                continue
            for way, destination, length, road_class, heading in outgoing[node]:
                if way == origin_way:
                    continue
                if road_class == "motorway_link":
                    if way not in exits or distance < exits[way][0]:
                        exits[way] = (distance, heading)
                else:
                    new_distance = distance + length
                    if new_distance <= maximum_distance_m and new_distance < best.get(destination, math.inf):
                        best[destination] = new_distance
                        heappush(queue, (new_distance, destination))
        rows.extend((origin_way, side, way, distance, heading) for way, (distance, heading) in sorted(exits.items()))
    conn.executescript("""
        DROP TABLE IF EXISTS motorway_exit_approach;
        CREATE TABLE motorway_exit_approach (
          way_id INTEGER NOT NULL, endpoint_side TEXT NOT NULL,
          exit_way_id INTEGER NOT NULL, path_distance_m REAL NOT NULL,
          branch_heading_deg REAL NOT NULL,
          PRIMARY KEY(way_id,endpoint_side,exit_way_id)
        );
    """)
    conn.executemany("INSERT INTO motorway_exit_approach VALUES(?,?,?,?,?)", rows)
    conn.executemany("INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)", [
        ("motorway_exit_approach_version", "1"),
        ("motorway_exit_approach_count", str(len(rows))),
        ("motorway_exit_approach_distance_m", str(maximum_distance_m)),
    ])
    conn.commit()
    return len(rows)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True)
    parser.add_argument("--ways-meta", required=True, type=Path)
    args = parser.parse_args()
    with sqlite3.connect(args.db) as conn:
        print(f"Directed motorway exit approaches: {build_motorway_exit_context(conn, args.ways_meta)}")
