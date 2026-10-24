#!/usr/bin/env python3
"""Add disabled v1.5 traffic-sign proposals to a cloned inventory bundle.

This is a local data-contract pilot. Spatial candidates are NOT decoded OpenLR
associations or verified driving directions. Existing mobile runtime tables,
source usage roles and policy bytes are never changed.
"""
from __future__ import annotations

import argparse
from collections import Counter
from functools import lru_cache
import json
import math
from pathlib import Path
import re
import sqlite3

EARTH_RADIUS_M = 6371008.8
CANDIDATE_RADIUS_M = 30.0
FORMAT = "youspeed.mobidata.v1.5.proposal-only.1"
SCHEMA = """
CREATE TABLE IF NOT EXISTS traffic_sign_v15_rule (
 inventory_row_id INTEGER PRIMARY KEY REFERENCES traffic_sign_inventory(row_id),
 source_id TEXT NOT NULL, record_key TEXT NOT NULL,
 literal_code TEXT NOT NULL, normalized_code TEXT NOT NULL, sign_family TEXT NOT NULL,
 kind TEXT NOT NULL, numeric_value REAL, unit TEXT, parameter_status TEXT NOT NULL,
 display_radius_m REAL NOT NULL CHECK(display_radius_m IN (10,30)),
 proposed_boundary_event TEXT,
 proposed_reset_prior_speed_limits INTEGER NOT NULL CHECK(proposed_reset_prior_speed_limits IN (0,1)),
 association_status TEXT NOT NULL, candidate_count INTEGER NOT NULL CHECK(candidate_count>=0),
 enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled=0)
);
CREATE TABLE IF NOT EXISTS traffic_sign_v15_way_candidate (
 inventory_row_id INTEGER NOT NULL REFERENCES traffic_sign_v15_rule(inventory_row_id),
 candidate_rank INTEGER NOT NULL, way_id INTEGER NOT NULL REFERENCES ways(way_id),
 segment_index INTEGER NOT NULL, distance_m REAL NOT NULL, chainage_m REAL NOT NULL,
 projection_lat REAL NOT NULL, projection_lon REAL NOT NULL, local_heading_deg REAL NOT NULL,
 osm_maxspeed TEXT, travel_direction TEXT NOT NULL CHECK(travel_direction='unknown'),
 association_status TEXT NOT NULL, enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled=0),
 PRIMARY KEY(inventory_row_id,way_id)
);
CREATE INDEX IF NOT EXISTS idx_traffic_sign_v15_candidate_way ON traffic_sign_v15_way_candidate(way_id);
CREATE INDEX IF NOT EXISTS idx_traffic_sign_v15_rule_kind ON traffic_sign_v15_rule(kind);
CREATE TABLE IF NOT EXISTS traffic_sign_v15_metadata (key TEXT PRIMARY KEY,value TEXT NOT NULL);
"""

# All quantities are source attributes, not active limits. Generic unparameterised
# families remain unknown; numbers in arbitrary annotation text are never guessed.
PARAMETERS = {
    "274": ("speed_limit", "km/h", 300),
    "278": ("speed_limit_end", "km/h", 300),
    "108": ("descent", "%", 100),
    "110": ("incline", "%", 100),
    "262": ("maximum_weight", "t", 1000),
    "263": ("maximum_axle_weight", "t", 1000),
    "264": ("maximum_width", "m", 100),
    "265": ("maximum_height", "m", 100),
    "266": ("maximum_length", "m", 100),
}
NUMERIC = re.compile(r"(\d+(?:[.,]\d+)?)(?:\s*(%|t|m|km/h))?", re.IGNORECASE)
CODE = re.compile(r"DE:(\d+(?:\.\d+)?)(?:-([^\[\]]+))?(?:\[([^\[\]]*)\])?")
RULE_FIELDS = ("literal_code", "normalized_code", "sign_family", "kind", "numeric_value", "unit",
               "parameter_status", "display_radius_m", "proposed_boundary_event",
               "proposed_reset_prior_speed_limits")


def normalize_sign(literal):
    """Preserve literal code and return conservative, disabled interpretation."""
    result = dict(literal_code=literal, normalized_code=literal, sign_family="unknown",
                  kind="secondary", numeric_value=None, unit=None,
                  parameter_status="not_applicable", display_radius_m=10,
                  proposed_boundary_event=None, proposed_reset_prior_speed_limits=0)
    match = CODE.fullmatch(literal)
    if not match:
        result["parameter_status"] = "malformed_code"
        return result
    family, suffix, annotation = match.groups()
    result["sign_family"] = "DE:" + family
    result["normalized_code"] = "DE:" + family + ("-" + suffix if suffix else "")
    if family in ("310", "311"):
        # Only exact class codes can propose settlement transitions.
        if suffix is None and annotation is None:
            result.update(kind="settlement_boundary", display_radius_m=30,
                          proposed_boundary_event="city_entry" if family == "310" else "city_exit",
                          proposed_reset_prior_speed_limits=1)
        else:
            result["parameter_status"] = "annotation_unverified"
        return result
    if family not in PARAMETERS:
        if annotation is not None:
            result["parameter_status"] = "annotation_unverified"
        return result
    kind, unit, maximum = PARAMETERS[family]
    result.update(kind=kind, unit=unit)
    value_match = NUMERIC.fullmatch(suffix or "")
    # Bracket quantities are supported only with an explicit unit. Empty [] is
    # never a zero and a free-text plate is never a source of inferred numbers.
    if suffix is None and annotation is not None:
        bracket_match = NUMERIC.fullmatch(annotation.strip())
        if bracket_match and bracket_match.group(2):
            value_match = bracket_match
    if value_match:
        number, explicit_unit = value_match.groups()
        value = float(number.replace(",", "."))
        if not math.isfinite(value) or not 0 < value <= maximum or (explicit_unit and explicit_unit.lower() != unit.lower()):
            result["parameter_status"] = "invalid_value"
        elif family in ("274", "278") and not value.is_integer():
            result["parameter_status"] = "invalid_value"
        else:
            result.update(numeric_value=value, parameter_status="parsed_source_value")
    else:
        result["parameter_status"] = "missing_value" if suffix is None else "invalid_value"
    if annotation is not None and not (suffix is None and value_match and value_match.group(2)):
        result["parameter_status"] = "dynamic_unverified" if "WVZ" in annotation.upper() else "annotation_unverified"
    return result


def validate_query(lat, lon):
    """This local BW projection deliberately excludes polar coordinates."""
    if any(type(value) not in (int, float) or not math.isfinite(value) for value in (lat, lon)):
        raise ValueError("Query must contain finite WGS84 coordinates")
    if not -90 <= lat <= 90 or not -180 <= lon <= 180:
        raise ValueError("Query coordinate outside WGS84")
    if abs(lat) >= 85:
        raise ValueError("Local projection requires absolute latitude below 85 degrees")


def project_polyline(lat, lon, points):
    """Nearest segment projection using a local metric plane; points are [lat,lon].

    Heading follows stored OSM geometry, not travel direction or sign orientation.
    Chainage is measured along that stored geometry. Degenerate polylines have no
    usable direction and return None.
    """
    validate_query(lat, lon)
    if not isinstance(points, list) or len(points) < 2:
        raise ValueError("Polyline needs at least two points")
    for point in points:
        if not isinstance(point, list) or len(point) != 2 or any(type(v) not in (int, float) or not math.isfinite(v) for v in point):
            raise ValueError("Invalid polyline coordinate")
        if not -90 <= point[0] <= 90 or not -180 <= point[1] <= 180:
            raise ValueError("Polyline coordinate outside WGS84")
        if abs(point[0]) >= 85:
            raise ValueError("Local projection requires absolute latitude below 85 degrees")
        if abs(point[1] - lon) > 180:
            raise ValueError("Antimeridian projection is unsupported")
    if any(abs(b[1] - a[1]) > 180 for a, b in zip(points, points[1:])):
        raise ValueError("Antimeridian crossing geometry is unsupported")
    cosine = math.cos(math.radians(lat))
    scale_lat = math.pi / 180 * EARTH_RADIUS_M
    scale_lon = scale_lat * cosine
    projected = [((p[1] - lon) * scale_lon, (p[0] - lat) * scale_lat) for p in points]
    best, chainage = None, 0.0
    for index, ((ax, ay), (bx, by)) in enumerate(zip(projected, projected[1:])):
        dx, dy = bx - ax, by - ay
        length = math.hypot(dx, dy)
        if length == 0:
            continue
        fraction = max(0.0, min(1.0, -(ax * dx + ay * dy) / (length * length)))
        px, py = ax + fraction * dx, ay + fraction * dy
        distance = math.hypot(px, py)
        candidate = dict(segment_index=index, distance_m=distance,
                         chainage_m=chainage + fraction * length,
                         projection_lat=lat + py / scale_lat,
                         projection_lon=lon + px / scale_lon,
                         local_heading_deg=math.degrees(math.atan2(dx, dy)) % 360)
        if best is None or (distance, index) < (best["distance_m"], best["segment_index"]):
            best = candidate
        chainage += length
    return best


def enrich_pilot(db, *, include_way_candidates=True):
    """Atomically replace only this helper's additive proposal tables."""
    names = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    required = {"traffic_sign_inventory", "traffic_sign_source"}
    if include_way_candidates:
        required |= {"ways", "ways_rtree", "way_geom"}
    if required - names:
        raise ValueError("Missing input tables: " + ", ".join(sorted(required - names)))
    if not db.execute("SELECT 1 FROM traffic_sign_inventory LIMIT 1").fetchone():
        raise ValueError("Refusing empty source inventory")
    report = dict(format=FORMAT, usage_role="proposal_only", enabled=False, field_ready=False,
                  candidate_radius_m=CANDIDATE_RADIUS_M, way_candidates_computed=include_way_candidates,
                  direction_semantics="unknown; local heading follows stored OSM geometry only",
                  limitations=["OpenLR not decoded", "Source orientation convention not verified",
                               "No legal/directional speed-rule application", "No mobile runtime integration"],
                  counts={}, kinds={}, parameter_statuses={}, associations={}, invalid_geometry_ways=0)
    invalid_geometry = set()

    @lru_cache(maxsize=20000)
    def geometry(way_id):
        row = db.execute("SELECT points_json FROM way_geom WHERE way_id=?", (way_id,)).fetchone()
        if row is None:
            invalid_geometry.add(way_id)
            return None
        try:
            points = json.loads(row[0])
            # Validate even if the sign is not near the first segment.
            project_polyline(points[0][0], points[0][1], points)
            return points
        except (ValueError, TypeError, IndexError, KeyError):
            invalid_geometry.add(way_id)
            return None

    @lru_cache(maxsize=20000)
    def candidates(lat, lon):
        validate_query(lat, lon)
        dy = math.degrees(CANDIDATE_RADIUS_M / EARTH_RADIUS_M)
        dx = dy / math.cos(math.radians(lat))
        if lon - dx < -180 or lon + dx > 180:
            raise ValueError("Antimeridian candidate bounds are unsupported")
        found = []
        rows = db.execute("""SELECT w.way_id,w.maxspeed FROM ways_rtree r
            JOIN ways w ON w.way_id=r.way_id
            WHERE r.min_lon<=? AND r.max_lon>=? AND r.min_lat<=? AND r.max_lat>=?""",
            (lon + dx, lon - dx, lat + dy, lat - dy)).fetchall()
        for way_id, maxspeed in rows:
            points = geometry(way_id)
            if points is None:
                continue
            projection = project_polyline(lat, lon, points)
            if projection is not None and projection["distance_m"] <= CANDIDATE_RADIUS_M:
                found.append(dict(way_id=way_id, osm_maxspeed=maxspeed, **projection))
        return sorted(found, key=lambda row: (row["distance_m"], row["way_id"]))

    db.execute("SAVEPOINT mobidata_v15_pilot")
    try:
        for statement in SCHEMA.split(";"):
            if statement.strip():
                db.execute(statement)
        db.execute("DELETE FROM traffic_sign_v15_way_candidate")
        db.execute("DELETE FROM traffic_sign_v15_rule")
        db.execute("DELETE FROM traffic_sign_v15_metadata")
        kinds, statuses, associations = Counter(), Counter(), Counter()
        sign_count = candidate_count = 0
        # Coordinate order groups repeated signs at the same site for bounded LRU
        # reuse. This is still deterministic and avoids caching the whole region.
        rows = db.execute("""SELECT row_id,source_id,record_key,sign_code,latitude,longitude
            FROM traffic_sign_inventory ORDER BY latitude,longitude,row_id""")
        for row_id, source_id, record_key, code, lat, lon in rows:
            validate_query(lat, lon)
            rule = normalize_sign(code)
            nearby = candidates(lat, lon) if include_way_candidates else []
            association = ("not_computed" if not include_way_candidates else
                           "no_candidate" if not nearby else
                           "single_candidate_direction_unverified" if len(nearby) == 1 else "ambiguous")
            values = (row_id, source_id, record_key, *(rule[field] for field in RULE_FIELDS), association, len(nearby), 0)
            db.execute("INSERT INTO traffic_sign_v15_rule VALUES(" + ",".join("?" for _ in values) + ")", values)
            for rank, candidate in enumerate(nearby, 1):
                db.execute("INSERT INTO traffic_sign_v15_way_candidate VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                           (row_id, rank, candidate["way_id"], candidate["segment_index"],
                            candidate["distance_m"], candidate["chainage_m"], candidate["projection_lat"],
                            candidate["projection_lon"], candidate["local_heading_deg"], candidate["osm_maxspeed"],
                            "unknown", association, 0))
            sign_count += 1
            candidate_count += len(nearby)
            kinds[rule["kind"]] += 1
            statuses[rule["parameter_status"]] += 1
            associations[association] += 1
        report.update(counts=dict(signs=sign_count, way_candidates=candidate_count),
                      kinds=dict(sorted(kinds.items())), parameter_statuses=dict(sorted(statuses.items())),
                      associations=dict(sorted(associations.items())), invalid_geometry_ways=len(invalid_geometry))
        provenance = [dict(zip(("source_id", "snapshot_sha256", "snapshot_timestamp", "record_count"), row))
                      for row in db.execute("SELECT source_id,snapshot_sha256,snapshot_timestamp,record_count FROM traffic_sign_source ORDER BY source_id")]
        report["sources"] = provenance
        db.executemany("INSERT INTO traffic_sign_v15_metadata VALUES(?,?)", [
            ("format", FORMAT), ("usage_role", "proposal_only"), ("enabled", "0"),
            ("report_json", json.dumps(report, sort_keys=True, ensure_ascii=False, separators=(",", ":")))])
        db.execute("RELEASE mobidata_v15_pilot")
    except BaseException:
        db.execute("ROLLBACK TO mobidata_v15_pilot")
        db.execute("RELEASE mobidata_v15_pilot")
        raise
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path, help="Existing cloned inventory DB to enrich in place")
    parser.add_argument("--report", required=True, type=Path, help="Local proposal-only build report")
    parser.add_argument("--no-way-candidates", action="store_true")
    args = parser.parse_args()
    if not args.db.is_file():
        parser.error("Input DB does not exist; clone the inventory bundle first")
    with sqlite3.connect(args.db) as db:
        report = enrich_pilot(db, include_way_candidates=not args.no_way_candidates)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False))


if __name__ == "__main__":
    main()
