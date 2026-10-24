#!/usr/bin/env python3
"""Read-only route/inventory coverage audit for a materialized BW runtime bundle.

Accepts normalized JSON/JSONL/CSV fixes, GPX tracks or GeoJSON LineStrings. This
measures source coverage and records bundle exclusions; it does not recreate the
mobile map matcher or infer an app display outcome from route proximity alone.
"""
from __future__ import annotations

import argparse
from collections import Counter
import csv
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import xml.etree.ElementTree as ET

EARTH_RADIUS_M = 6371008.8
KEYS = {
    "lat": ("lat", "latitude", "gpsLatitude", "location.latitude", "fix.latitude", "gps.lat"),
    "lon": ("lon", "longitude", "lng", "gpsLongitude", "location.longitude", "fix.longitude", "gps.lon"),
    "timestamp": ("timestamp", "timestampUTC", "timestamp_utc", "time", "at", "utc", "location.timestamp", "fix.timestamp"),
    "accuracy": ("accuracy", "accuracy_m", "horizontalAccuracy", "horizontalAccM", "hacc", "hacc_m", "location.horizontalAccuracy", "fix.accuracy"),
    "heading": ("heading", "bearing", "bearing_deg", "course", "courseDeg", "course_deg", "location.course", "fix.heading"),
    "heading_accuracy": ("heading_accuracy", "headingAccuracy", "courseAccuracy", "course_accuracy", "fix.headingAccuracy"),
    "way_id": ("way_id", "wayID", "wayId", "matchedWayId", "matched_way", "result.wayID", "match.wayID", "fix.wayId"),
    "direction": ("direction", "inventory_direction", "result.inventorySigns.direction", "match.direction", "fix.direction"),
}


def field(row, names):
    for name in names:
        value = row
        for part in name.split("."):
            value = value.get(part) if isinstance(value, dict) else None
        if value is not None and value != "":
            return value
    return None


def numeric(value):
    try:
        result = float(value)
        return result if math.isfinite(result) else None
    except (TypeError, ValueError, OverflowError):
        return None


def timestamp(value):
    number = numeric(value)
    if number is not None:
        return number / 1000 if abs(number) >= 1e12 else number
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).timestamp()
    except (TypeError, ValueError, OverflowError):
        return None


def load_track(path, *, lat_key=None, lon_key=None):
    """Keep valid geographic fixes in input order, including duplicate positions."""
    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".gpx":
        rows = []
        for point in ET.parse(path).getroot().iter():
            if point.tag.rsplit("}", 1)[-1] in ("trkpt", "rtept"):
                at = next((child.text for child in point if child.tag.rsplit("}", 1)[-1] == "time"), None)
                rows.append({"lat": point.attrib.get("lat"), "lon": point.attrib.get("lon"), "timestamp": at})
    elif suffix == ".csv":
        with path.open(newline="") as source:
            rows = list(csv.DictReader(source))
    elif suffix in (".jsonl", ".ndjson"):
        rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    else:
        data = json.loads(path.read_text())
        if isinstance(data, list):
            rows = data
        elif data.get("type") in ("Feature", "LineString", "FeatureCollection"):
            features = data["features"] if data.get("type") == "FeatureCollection" else [data]
            rows = []
            part = 0
            for feature in features:
                geometry = feature.get("geometry", feature)
                lines = geometry["coordinates"] if geometry.get("type") == "MultiLineString" else [geometry["coordinates"]]
                if geometry.get("type") not in ("LineString", "MultiLineString"):
                    raise ValueError("Route GeoJSON requires LineString/MultiLineString geometry")
                for coordinates in lines:
                    rows.extend({"lat": p[1], "lon": p[0], "part": part} for p in coordinates)
                    part += 1
        else:
            rows = next((data[key] for key in ("points", "fixes", "track", "locations") if key in data), None)
            if rows is None:
                raise ValueError("JSON route needs a fix list, points/fixes/track/locations, or GeoJSON")
    fixes, rejected = [], 0
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            rejected += 1
            continue
        lat = numeric(field(row, (lat_key,) if lat_key else KEYS["lat"]))
        lon = numeric(field(row, (lon_key,) if lon_key else KEYS["lon"]))
        if lat is None or lon is None or abs(lat) >= 85 or not -180 <= lon <= 180:
            rejected += 1
            continue
        fix = dict(index=index, lat=lat, lon=lon, part=row.get("part", 0))
        fix["observed"] = {key: row[key] for key in ("source", "effective_speed", "bundle_speed", "effective_source", "effective_reason", "inside_city", "city_source", "status") if key in row}
        for key in KEYS:
            if key not in ("lat", "lon"):
                value = field(row, KEYS[key])
                fix[key] = value if key == "way_id" else timestamp(value) if key == "timestamp" else numeric(value)
        fixes.append(fix)
    if not fixes:
        raise ValueError("No valid geographic fixes found; supply explicit --lat-key/--lon-key if needed")
    return fixes, dict(input_rows=len(rows), valid_fixes=len(fixes), rejected_rows=rejected)


def distance(lat, lon, other_lat, other_lon):
    dy, dx = math.radians(other_lat - lat), math.radians(other_lon - lon)
    value = math.sin(dy / 2) ** 2 + math.cos(math.radians(lat)) * math.cos(math.radians(other_lat)) * math.sin(dx / 2) ** 2
    return EARTH_RADIUS_M * 2 * math.asin(math.sqrt(min(1, max(0, value))))


def route_segments(fixes, max_gap_m=200, max_gap_s=15):
    """Never draw an invented route line across missing/long-gap observations."""
    segments, covered, gaps = [], set(), []
    for i, (a, b) in enumerate(zip(fixes, fixes[1:])):
        length = distance(a["lat"], a["lon"], b["lat"], b["lon"])
        elapsed = b["timestamp"] - a["timestamp"] if a["timestamp"] is not None and b["timestamp"] is not None else None
        reasons = []
        if a["part"] != b["part"]:
            reasons.append("separate_track_parts")
        if abs(a["lon"] - b["lon"]) > 180:
            reasons.append("antimeridian_unsupported")
        if length > max_gap_m:
            reasons.append("distance_gap")
        if elapsed is not None and (elapsed < 0 or elapsed > max_gap_s):
            reasons.append("time_gap")
        if reasons:
            gaps.append(dict(from_fix=a["index"], to_fix=b["index"], distance_m=length, elapsed_s=elapsed, reasons=reasons))
        else:
            segments.append((a, b))
            covered.update((i, i + 1))
    segments.extend((fix, fix) for i, fix in enumerate(fixes) if i not in covered)
    return segments, gaps


def project_to_segment(lat, lon, a, b):
    scale = math.pi / 180 * EARTH_RADIUS_M
    cosine = math.cos(math.radians(lat))
    ax, ay = (a["lon"] - lon) * scale * cosine, (a["lat"] - lat) * scale
    bx, by = (b["lon"] - lon) * scale * cosine, (b["lat"] - lat) * scale
    dx, dy = bx - ax, by - ay
    squared = dx * dx + dy * dy
    fraction = max(0, min(1, -(ax * dx + ay * dy) / squared)) if squared > 0 else 0
    return (math.hypot(ax + fraction * dx, ay + fraction * dy), fraction,
            math.degrees(math.atan2(dx, dy)) % 360 if squared > 0 else None)


def angle(a, b):
    return abs((a - b + 180) % 360 - 180)


def summarize_signs(signs, predicate):
    chosen = [sign for sign in signs if predicate(sign)]
    return dict(count=len(chosen), by_source=dict(sorted(Counter(s["source_id"] for s in chosen).items())),
                by_kind=dict(sorted(Counter(s["kind"] for s in chosen).items())),
                by_code=dict(sorted(Counter(s["sign_code"] for s in chosen).items())),
                associations=dict(sorted(Counter(s["association_status"] or "missing" for s in chosen).items())))


def analyze_route(db_path, fixes, *, radius_m=100, max_gap_m=200, max_gap_s=15):
    if radius_m < 30 or radius_m > 1000:
        raise ValueError("Corridor radius must be between 30 and 1000 metres")
    path = Path(db_path).resolve()
    segments, gaps = route_segments(fixes, max_gap_m, max_gap_s)
    db = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    try:
        required = {"traffic_sign_runtime", "traffic_sign_association", "traffic_sign_way_rule"}
        names = {r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if required - names:
            raise ValueError("Runtime bundle missing tables: " + ", ".join(sorted(required - names)))
        global_counts = [dict(row) for row in db.execute("SELECT source_id,kind,count(*) AS records FROM traffic_sign_runtime GROUP BY source_id,kind")]
        signs = {}
        for a, b in segments:
            dy = math.degrees(radius_m / EARTH_RADIUS_M)
            dx = dy / min(math.cos(math.radians(a["lat"])), math.cos(math.radians(b["lat"])))
            rows = db.execute("""SELECT s.*,a.status AS association_status,a.way_id AS associated_way_id,
                a.direction AS associated_direction,a.station_chainage_m,a.local_heading_deg,a.confidence AS association_confidence,
                a.evidence_json FROM traffic_sign_runtime s LEFT JOIN traffic_sign_association a USING(sign_id)
                WHERE s.lat BETWEEN ? AND ? AND s.lon BETWEEN ? AND ?""",
                (min(a["lat"], b["lat"]) - dy, max(a["lat"], b["lat"]) + dy,
                 min(a["lon"], b["lon"]) - dx, max(a["lon"], b["lon"]) + dx))
            for row in rows:
                d, fraction, route_heading = project_to_segment(row["lat"], row["lon"], a, b)
                if d > radius_m:
                    continue
                sign_id = row["sign_id"]
                if sign_id not in signs:
                    signs[sign_id] = dict(row)
                    sign = signs[sign_id]
                    sign["model_classes"] = json.loads(sign.pop("model_classes_json"))
                    evidence = json.loads(sign.pop("evidence_json") or "{}")
                    sign["association_candidates"] = evidence.get("candidates", [])
                    sign["min_route_distance_m"] = math.inf
                    sign["min_fix_distance_m"] = math.inf
                    sign["nearest_fix"] = None
                    sign["nearest_usable_fix_distance_m"] = None
                    sign["rules"] = []
                sign = signs[sign_id]
                if d < sign["min_route_distance_m"]:
                    sign.update(min_route_distance_m=d, nearest_route_from_fix=a["index"], nearest_route_to_fix=b["index"],
                                nearest_route_fraction=fraction, nearest_route_heading=route_heading)
                for fix in (a, b):
                    fix_distance = distance(row["lat"], row["lon"], fix["lat"], fix["lon"])
                    if fix_distance < sign["min_fix_distance_m"]:
                        sign.update(min_fix_distance_m=fix_distance, nearest_fix=fix)
                    if fix["accuracy"] is not None and 0 <= fix["accuracy"] <= 25:
                        previous = sign["nearest_usable_fix_distance_m"]
                        if previous is None or fix_distance < previous:
                            sign["nearest_usable_fix_distance_m"] = fix_distance
        ids = sorted(signs)
        for start in range(0, len(ids), 900):
            subset = ids[start:start + 900]
            for rule in db.execute("SELECT rule_id,sign_id,way_id,direction,start_chainage_m,end_chainage_m,speed_kmh,inside_city,association_status,lane_scope FROM traffic_sign_way_rule WHERE sign_id IN (" + ",".join("?" for _ in subset) + ") ORDER BY sign_id,way_id,direction,start_chainage_m", subset):
                signs[rule["sign_id"]]["rules"].append(dict(rule))
        for sign in signs.values():
            radius = sign["display_radius_m"]
            sign["within_route_geofence"] = sign["min_route_distance_m"] <= radius
            sign["within_sampled_fix_geofence"] = sign["min_fix_distance_m"] <= radius
            sign["within_usable_fix_geofence"] = (sign["nearest_usable_fix_distance_m"] <= radius if sign["nearest_usable_fix_distance_m"] is not None else None)
            sign["requires_directed_evidence"] = sign["kind"] in ("speed_limit", "speed_limit_end", "settlement_boundary") or sign["sign_code"] == "DE:282"
            sign["lane_scopes"] = dict(sorted(Counter(r["lane_scope"] for r in sign["rules"]).items()))
            sign["all_lane_rules"] = sum(r["lane_scope"] == "all" and r["association_status"] == "accepted" for r in sign["rules"])
            heading = sign["local_heading_deg"]
            if heading is not None and sign["associated_direction"] == -1:
                heading = (heading + 180) % 360
            sign["associated_travel_heading"] = heading
            route_heading = sign["nearest_route_heading"]
            sign["route_heading_error_deg"] = angle(heading, route_heading) if heading is not None and route_heading is not None else None
            sign["static_exclusions"] = []
            if not sign["within_sampled_fix_geofence"]:
                sign["static_exclusions"].append("no_recorded_fix_within_display_radius")
            if sign["nearest_usable_fix_distance_m"] is None:
                sign["static_exclusions"].append("fix_accuracy_unavailable")
            elif not sign["within_usable_fix_geofence"]:
                sign["static_exclusions"].append("no_accuracy_0_to_25m_fix_within_radius")
            if sign["requires_directed_evidence"] and sign["association_status"] != "accepted":
                sign["static_exclusions"].append("directed_association_" + str(sign["association_status"]))
            if sign["kind"] == "speed_limit" and not sign["all_lane_rules"]:
                sign["static_exclusions"].append("no_accepted_all_lane_rule")
            if not sign["pictogram_path"]:
                sign["static_exclusions"].append("no_pictogram")
            if not sign["model_classes"]:
                sign["static_exclusions"].append("no_supported_model_class_for_confirmation")
            if sign["parameter_status"] not in ("not_applicable", "parsed_source_value", "missing_value"):
                sign["static_exclusions"].append("unverified_source_parameter")
            fix = sign["nearest_fix"]
            if sign["requires_directed_evidence"] and fix["way_id"] is not None:
                sign["nearest_fix_associated_way_matches"] = str(fix["way_id"]) == str(sign["associated_way_id"])
            if sign["requires_directed_evidence"] and fix["direction"] is not None:
                sign["nearest_fix_associated_direction_matches"] = fix["direction"] == sign["associated_direction"]
        records = sorted(signs.values(), key=lambda s: (s["min_route_distance_m"], s["sign_id"]))
        report = dict(format="youspeed.bw.route-sign-coverage.v1", db=str(path), read_only=True,
                      method="Runtime position-index bbox prefilter and local point-to-route-segment metric projection; separate actual-fix haversine distances.",
                      limits=["Proximity is not sign visibility or an app display prediction", "No mobile matcher replay",
                              "Primary speed intervals can apply after passing the physical sign", "Missing accuracy is unknown, not an accepted fix",
                              "Heading from route geometry is approximate; device heading/accuracy and stability gates need logs"],
                      corridor_radius_m=radius_m, max_join_gap_m=max_gap_m, max_join_gap_s=max_gap_s,
                      track=dict(fixes=len(fixes), analyzed_segments=len(segments), gaps=gaps,
                                 connected_distance_m=sum(distance(a["lat"], a["lon"], b["lat"], b["lon"]) for a, b in segments)),
                      bundle_global_counts=global_counts,
                      summaries={"within_own_radius_continuous_route": summarize_signs(records, lambda s: s["within_route_geofence"]),
                                 "within_own_radius_recorded_fixes": summarize_signs(records, lambda s: s["within_sampled_fix_geofence"])}, signs=records)
        for radius in (10, 25, 30, 50, 100):
            if radius <= radius_m:
                report["summaries"][f"within_{radius}m_route_corridor"] = summarize_signs(records, lambda s, radius=radius: s["min_route_distance_m"] <= radius)
        return report
    finally:
        db.close()


def map_geojson(db_path, fixes, report, *, road_corridor_m=300):
    """Compact source-backed street context; no tiles or external map service."""
    if not 30 <= road_corridor_m <= 2000:
        raise ValueError("Road corridor must be between 30 and 2000 metres")
    segments, _ = route_segments(fixes, report["max_join_gap_m"], report["max_join_gap_s"])
    lines, current, previous = [], [], None
    source_lines, source_current, source_previous, source_context = [], [], None, None
    for a, b in segments:
        if previous != a["index"] and current:
            if len(current) >= 2:
                lines.append(current)
            current = []
        if not current:
            current.append([round(a["lon"], 7), round(a["lat"], 7)])
        point = [round(b["lon"], 7), round(b["lat"], 7)]
        if point != current[-1]:
            current.append(point)
        previous = b["index"]
        context = {key: a.get("observed", {}).get(key) for key in ("source", "effective_speed", "effective_reason")}
        if (source_previous != a["index"] or source_context != context) and source_current:
            if len(source_current) >= 2:
                source_lines.append((source_current, source_context))
            source_current = []
        if not source_current:
            source_current = [[round(a["lon"], 7), round(a["lat"], 7)]]
        if point != source_current[-1]:
            source_current.append(point)
        source_previous, source_context = b["index"], context
    if len(current) >= 2:
        lines.append(current)
    if len(source_current) >= 2:
        source_lines.append((source_current, source_context))
    features = [dict(type="Feature", geometry=dict(type="LineString", coordinates=coordinates),
                     properties=dict(layer="route", **context)) for coordinates, context in source_lines]
    db = sqlite3.connect(Path(db_path).resolve().as_uri() + "?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA query_only=ON")
    roads = {}
    try:
        # Road context requires only a subset of fixes: each omitted point is
        # within half the corridor of the last selected point. Querying both
        # ends of these retained spans avoids visible gaps in the road layer.
        retained = []
        for fix in fixes:
            if not retained or distance(fix["lat"], fix["lon"], retained[-1]["lat"], retained[-1]["lon"]) >= road_corridor_m / 2:
                retained.append(fix)
        if fixes[-1] is not retained[-1]:
            retained.append(fixes[-1])
        for fix in retained:
            dy = math.degrees(road_corridor_m / EARTH_RADIUS_M)
            dx = dy / math.cos(math.radians(fix["lat"]))
            for road in db.execute("""SELECT w.way_id,w.highway,w.street_name,w.ref,w.maxspeed,g.points_json
                FROM ways_rtree r JOIN ways w ON w.way_id=r.way_id JOIN way_geom g ON g.way_id=w.way_id
                WHERE r.min_lon<=? AND r.max_lon>=? AND r.min_lat<=? AND r.max_lat>=?""",
                (fix["lon"] + dx, fix["lon"] - dx, fix["lat"] + dy, fix["lat"] - dy)):
                if road["way_id"] not in roads:
                    roads[road["way_id"]] = dict(road)
        for way_id in sorted(roads):
            road = roads[way_id]
            geometry = json.loads(road.pop("points_json"))
            if len(geometry) >= 2:
                properties = {key: value for key, value in road.items() if value is not None}
                features.append(dict(type="Feature", geometry=dict(type="LineString", coordinates=[[round(p[1], 6), round(p[0], 6)] for p in geometry]), properties=dict(layer="road", **properties)))
    finally:
        db.close()
    for sign in report["signs"]:
        keys = ("sign_id", "source_id", "sign_code", "kind", "numeric_value", "unit", "parameter_status",
                "display_radius_m", "pictogram_path", "association_status", "associated_way_id", "associated_direction",
                "min_route_distance_m", "min_fix_distance_m", "within_route_geofence", "within_sampled_fix_geofence",
                "within_usable_fix_geofence", "all_lane_rules", "lane_scopes", "route_heading_error_deg", "static_exclusions")
        properties = {key: sign[key] for key in keys}
        for key in ("min_route_distance_m", "min_fix_distance_m", "route_heading_error_deg"):
            if properties[key] is not None:
                properties[key] = round(properties[key], 2)
        properties.update(layer="sign", model_classes=sign["model_classes"])
        features.append(dict(type="Feature", geometry=dict(type="Point", coordinates=[sign["lon"], sign["lat"]]), properties=properties))
    return dict(type="FeatureCollection", features=features,
                attribution="© OpenStreetMap contributors; MobiData BW / Verkehrsministerium Baden-Württemberg, dl-de/by-2-0",
                metadata=dict(format="youspeed.bw.route-map.v1", road_features=len(roads), sign_features=len(report["signs"]),
                              route_parts=len(lines), source_db=str(Path(db_path).resolve()), road_corridor_m=road_corridor_m))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--track", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--lat-key")
    parser.add_argument("--lon-key")
    parser.add_argument("--radius-m", type=float, default=100)
    parser.add_argument("--max-join-gap-m", type=float, default=200)
    parser.add_argument("--max-join-gap-s", type=float, default=15)
    parser.add_argument("--out-geojson", type=Path, help="Optional offline route/road/sign map source")
    parser.add_argument("--road-corridor-m", type=float, default=300)
    args = parser.parse_args()
    fixes, load_report = load_track(args.track, lat_key=args.lat_key, lon_key=args.lon_key)
    report = analyze_route(args.db, fixes, radius_m=args.radius_m, max_gap_m=args.max_join_gap_m, max_gap_s=args.max_join_gap_s)
    report["input"] = dict(track=str(args.track.resolve()), track_sha256=hashlib.sha256(args.track.read_bytes()).hexdigest(), **load_report)
    if args.out_geojson:
        geojson = map_geojson(args.db, fixes, report, road_corridor_m=args.road_corridor_m)
        args.out_geojson.parent.mkdir(parents=True, exist_ok=True)
        args.out_geojson.write_text(json.dumps(geojson, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")
        report["map"] = dict(file=str(args.out_geojson.resolve()), features=len(geojson["features"]), road_corridor_m=args.road_corridor_m)
    args.out_json.parent.mkdir(parents=True, exist_ok=True)
    args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "signs"}, ensure_ascii=False, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
