#!/usr/bin/env python3
"""Audit German urban/rural evidence in a generated v3 SQLite map bundle.

This diagnostic samples one distance-weighted midpoint from each retained road
polyline carrying an explicit urban or rural token. It compares existing OSM
evidence and stored geometry; it does not measure real-world accuracy or simulate
either app's classification logic. The bundle's geometry may already be simplified.
Recognized tokens are DE:urban, urban, DE:rural, and rural. The v3 ways, way_geom,
areas, city_boundary, city_ring, and associated spatial-index tables are required.

Only the Python standard library is required. SQLite is opened read-only, and
deterministic JSON is written to stdout. Redirect stdout to save a report.
"""

import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path
import sqlite3


METHOD = (
    "One distance-weighted midpoint per retained road polyline. Exact token "
    "DE:urban, urban, DE:rural, rural in maxspeed/maxspeed:type/source:maxspeed; "
    "semicolon split. Residential uses stored polygon ray casting; administrative "
    "uses stored outer/hole rings. OSM consistency only, not real-world accuracy "
    "or an app simulation. No external ground truth."
)


def point_in_ring(point, ring):
    """Ray-cast longitude/latitude coordinates without a boundary tolerance."""
    x, y = point
    inside = False
    for index, (x1, y1) in enumerate(ring):
        x2, y2 = ring[index - 1]
        if (y1 > y) != (y2 > y) and x < (x2 - x1) * (y - y1) / (y2 - y1) + x1:
            inside = not inside
    return inside


def boundary_contains(point, rings):
    """Respect each outer ring's associated holes in the stored boundary."""
    containing_outers = [
        outer_index
        for outer_index, is_hole, ring in rings
        if not is_hole and point_in_ring(point, ring)
    ]
    return any(
        not any(
            is_hole and outer_index == outer and point_in_ring(point, ring)
            for outer_index, is_hole, ring in rings
        )
        for outer in containing_outers
    )


def road_midpoint(points):
    """Return longitude/latitude at half the retained lat/lon polyline's length."""
    lengths = [
        math.hypot(
            (end[0] - start[0]) * 111320,
            (end[1] - start[1])
            * 111320
            * math.cos(math.radians((start[0] + end[0]) / 2)),
        )
        for start, end in zip(points, points[1:])
    ]
    remaining = sum(lengths) / 2
    for start, end, length in zip(points, points[1:], lengths):
        if length > 0 and remaining <= length:
            fraction = remaining / length
            return (
                start[1] + fraction * (end[1] - start[1]),
                start[0] + fraction * (end[0] - start[0]),
            )
        remaining -= length
    return (points[0][1], points[0][0])


def context_tokens(way):
    return {
        token.strip().lower()
        for field in ("maxspeed", "maxspeed_type", "source_maxspeed")
        for token in (way[field] or "").split(";")
    }


def sha256_file(path):
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def ring_closure_counts(connection):
    results = {}
    for table, predicate in (
        ("areas", "residential IS NOT NULL"),
        ("city_ring", "1"),
    ):
        counts = Counter()
        for row in connection.execute(
            f"SELECT points_json FROM {table} WHERE {predicate}"
        ):
            if not row["points_json"]:
                continue
            points = json.loads(row["points_json"])
            counts["rings"] += 1
            counts["closed_first_equals_last"] += points[0] == points[-1]
            counts["other_adjacent_duplicates"] += any(
                start == end for start, end in zip(points, points[1:])
            )
        results[table] = dict(counts)
    return results


def settlement_summary(connection):
    """Describe the optional nullable-boolean extension without interpreting NULL as false."""
    tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    if "settlement_segment" not in tables:
        return None
    version = connection.execute(
        "SELECT value FROM metadata WHERE key='settlement_context_version'"
    ).fetchone()
    grouped = [
        {"inside_city": None if row[0] is None else bool(row[0]),
         "source": row[1], "confidence": row[2], "segments": row[3]}
        for row in connection.execute(
            "SELECT inside_city,source,confidence,count(*) FROM settlement_segment "
            "GROUP BY inside_city,source,confidence ORDER BY inside_city,source,confidence"
        )
    ]
    return {
        "version": version[0] if version else None,
        "segments": connection.execute("SELECT count(*) FROM settlement_segment").fetchone()[0],
        "ways_with_context": connection.execute("SELECT count(DISTINCT way_id) FROM settlement_segment").fetchone()[0],
        "ways_without_context": connection.execute(
            "SELECT count(*) FROM ways w WHERE NOT EXISTS "
            "(SELECT 1 FROM settlement_segment s WHERE s.way_id=w.way_id)"
        ).fetchone()[0],
        "invalid_boolean_values": connection.execute(
            "SELECT count(*) FROM settlement_segment WHERE inside_city IS NOT NULL "
            "AND (typeof(inside_city)!='integer' OR inside_city NOT IN(0,1))"
        ).fetchone()[0],
        "segments_without_way": connection.execute(
            "SELECT count(*) FROM settlement_segment s WHERE NOT EXISTS "
            "(SELECT 1 FROM ways w WHERE w.way_id=s.way_id)"
        ).fetchone()[0],
        "metadata": dict(connection.execute(
            "SELECT key,value FROM metadata WHERE key GLOB 'settlement_*' ORDER BY key"
        )),
        "by_value_and_evidence": grouped,
        "sign_associations": dict(connection.execute(
            "SELECT association,count(*) FROM settlement_sign GROUP BY association ORDER BY association"
        )),
        "area_kinds": dict(connection.execute(
            "SELECT kind,count(*) FROM settlement_area GROUP BY kind ORDER BY kind"
        )),
    }


def audit(connection, bundle_path):
    areas = {
        row["row_id"]: dict(row)
        for row in connection.execute(
            """SELECT row_id, area_id, name, residential, points_json
               FROM areas
               WHERE residential IS NOT NULL AND geometry_type = 'Polygon'
               ORDER BY row_id"""
        )
    }
    for area in areas.values():
        area["points"] = json.loads(area.pop("points_json"))
    boundaries = {
        row["row_id"]: dict(row)
        for row in connection.execute(
            "SELECT row_id, name, admin_level FROM city_boundary ORDER BY row_id"
        )
    }
    rings = defaultdict(list)
    for row in connection.execute(
        "SELECT * FROM city_ring ORDER BY boundary_row_id, ring_index"
    ):
        rings[row["boundary_row_id"]].append(
            (row["outer_index"], row["is_hole"], json.loads(row["points_json"]))
        )

    stats = defaultdict(Counter)
    examples = defaultdict(list)
    token_fields = ("maxspeed", "maxspeed_type", "source_maxspeed")
    # Broad SQL prefilter; exact, semicolon-separated tokens are checked below.
    predicates = " OR ".join(
        f"lower(coalesce(w.{field}, '')) LIKE '%{kind}%'"
        for field in token_fields
        for kind in ("urban", "rural")
    )
    roads = connection.execute(
        "SELECT w.*, g.points_json FROM ways w "
        f"JOIN way_geom g USING (way_id) WHERE {predicates} ORDER BY w.way_id"
    )
    for way in roads:
        tokens = context_tokens(way)
        kinds = [
            kind for kind in ("urban", "rural")
            if kind in tokens or "de:" + kind in tokens
        ]
        if not kinds:
            continue
        point = road_midpoint(json.loads(way["points_json"]))
        lon, lat = point
        parameters = (lon, lon, lat, lat)
        residential_boxes = [
            row[0]
            for row in connection.execute(
                """SELECT row_id FROM areas_rtree
                   WHERE min_lon <= ? AND max_lon >= ?
                     AND min_lat <= ? AND max_lat >= ? ORDER BY row_id""",
                parameters,
            )
            if row[0] in areas
        ]
        residential_hits = [
            area for area in residential_boxes
            if point_in_ring(point, areas[area]["points"])
        ]
        boundary_hits = [
            row[0]
            for row in connection.execute(
                """SELECT row_id FROM city_boundary_rtree
                   WHERE min_lon <= ? AND max_lon >= ?
                     AND min_lat <= ? AND max_lat >= ? ORDER BY row_id""",
                parameters,
            )
            if boundary_contains(point, rings[row[0]])
        ]
        for kind in kinds:
            counts = stats[kind]
            counts["ways"] += 1
            counts["inside_residential_bbox"] += bool(residential_boxes)
            counts["inside_residential_bbox_but_outside_polygon"] += (
                bool(residential_boxes) and not bool(residential_hits)
            )
            counts["inside_residential"] += bool(residential_hits)
            counts["outside_residential"] += not bool(residential_hits)
            counts["inside_any_admin_boundary"] += bool(boundary_hits)
            counts["inside_admin_8_or_9"] += any(
                boundaries[boundary]["admin_level"] in (8, 9)
                for boundary in boundary_hits
            )
            counts["highway:" + str(way["highway"])] += 1
            explicit_low_speed = str(way["maxspeed"]) in ("30", "40")
            if explicit_low_speed:
                counts["explicit_maxspeed_" + str(way["maxspeed"])] += 1

            interesting = (
                (kind == "urban" and not residential_hits)
                or (kind == "rural" and residential_hits)
                or (kind == "rural" and explicit_low_speed)
            )
            if not interesting:
                continue
            example = {
                field: way[field]
                for field in (
                    "way_id", "highway", "maxspeed", "maxspeed_type", "source_maxspeed"
                )
            }
            example.update(
                name=way["street_name"],
                midpoint_lon_lat=point,
                residential_areas=[
                    {field: areas[area][field] for field in ("area_id", "name", "residential")}
                    for area in residential_hits
                ],
                administrative_areas=[boundaries[boundary] for boundary in boundary_hits],
            )
            key = kind + (
                "_inside_residential" if residential_hits else "_outside_residential"
            )
            if len(examples[key]) < 15:
                examples[key].append(example)
            if kind == "rural" and explicit_low_speed:
                speed_key = "rural_explicit_" + str(way["maxspeed"])
                if len(examples[speed_key]) < 8:
                    examples[speed_key].append(example)

    return {
        "bundle": str(bundle_path),
        "bundle_sha256": sha256_file(bundle_path),
        "method": METHOD,
        "settlement_context": settlement_summary(connection),
        "total_ways": connection.execute("SELECT count(*) FROM ways").fetchone()[0],
        "administrative_boundaries": len(boundaries),
        "administrative_boundary_counts_by_level": dict(
            Counter(boundary["admin_level"] for boundary in boundaries.values())
        ),
        "city_rings": sum(len(boundary_rings) for boundary_rings in rings.values()),
        "ring_closure": ring_closure_counts(connection),
        "residential_polygons": len(areas),
        "residential_point_count_distribution": dict(
            Counter(len(area["points"]) for area in areas.values())
        ),
        "all_area_point_count_distribution": dict(
            Counter(
                len(json.loads(row[0]))
                for row in connection.execute(
                    "SELECT points_json FROM areas WHERE points_json IS NOT NULL"
                )
            )
        ),
        "stats": dict(stats),
        "examples": dict(examples),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "database", type=Path,
        help="Path to a German v3 map SQLite bundle with area and city-boundary tables",
    )
    parser.add_argument(
        "--settlement-only", action="store_true",
        help="Report the additive contract and coverage without the legacy midpoint diagnostic",
    )
    args = parser.parse_args()
    bundle_path = args.database.resolve()
    connection = sqlite3.connect(bundle_path.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        result = {
            "bundle": str(bundle_path),
            "bundle_sha256": sha256_file(bundle_path),
            "method": "Counts of generated settlement segments; no claim of surveyed accuracy.",
            "total_ways": connection.execute("SELECT count(*) FROM ways").fetchone()[0],
            "settlement_context": settlement_summary(connection),
        } if args.settlement_only else audit(connection, bundle_path)
    finally:
        connection.close()
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
