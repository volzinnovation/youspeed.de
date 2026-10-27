#!/usr/bin/env python3
"""Prepare a local, reproducible traffic/OSM study without uploading a GPX.

Network requests are opt-in (--fetch). They disclose the study bounding box to
the traffic and Overpass services. Raw GPX points never leave this process.
Use --traffic-file and --osm-file for entirely offline input preparation.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sqlite3
import ssl
import urllib.parse
import urllib.request

from rank_traffic_hotspots import load_gpx, geometry_points, Projection, sample_geometry, analyze, write_outputs

TRAFFIC_COLLECTION = "https://geoapi.goat.plan4better.de/collections/58f3d092-4837-473b-bf8b-c14dfb26f049"
OVERPASS = "https://overpass-api.de/api/interpreter"
USER_AGENT = "YouSpeed-research-prototype/0.1 (one-off local route analysis)"


def save_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def request_json(url, data=None):
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = urllib.request.Request(url, data=data, headers=headers)
    context = ssl.create_default_context()
    # Some macOS Python distributions point at a missing private CA bundle.
    # Use the OS CA bundle in that case; never disable certificate validation.
    if not context.cert_store_stats().get("x509_ca") and Path("/etc/ssl/cert.pem").is_file():
        context.load_verify_locations(cafile="/etc/ssl/cert.pem")
    with urllib.request.urlopen(request, timeout=60, context=context) as response:
        return json.load(response), dict(response.headers)


def bounds(points, margin_m=0):
    if not points:
        raise ValueError("Cannot bound an empty geometry")
    center_lat = sum(p[1] for p in points) / len(points)
    dy = margin_m / 111195
    dx = dy / math.cos(math.radians(center_lat))
    return [min(p[0] for p in points) - dx, min(p[1] for p in points) - dy,
            max(p[0] for p in points) + dx, max(p[1] for p in points) + dy]


def map_scope(url, width, height):
    parameters = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    loc = parameters.get("loc", ["48.80602,8.53271,13.41z"])[0].split(",")
    lat, lon, zoom = float(loc[0]), float(loc[1]), float(loc[2].rstrip("z"))
    scale = 512 * 2 ** zoom  # MapLibre's logical 512-pixel zoom convention.
    x = (lon + 180) / 360 * scale
    y = (1 - math.asinh(math.tan(math.radians(lat))) / math.pi) / 2 * scale
    def inverse(px, py):
        return [px / scale * 360 - 180,
                math.degrees(math.atan(math.sinh(math.pi * (1 - 2 * py / scale))))]
    west, south = inverse(x - width / 2, y + height / 2)
    east, north = inverse(x + width / 2, y - height / 2)
    return dict(kind="viewport", label="Linked map window", center=[lon, lat], zoom=zoom,
                viewport=dict(width=width, height=height), bbox=[west, south, east, north], url=url)


def fetch_traffic(bbox):
    features, seen, pages, total = [], set(), [], None
    # Keep the spatial filter on EVERY page; the service's next link drops it.
    for offset in range(0, 20000, 1000):
        query = urllib.parse.urlencode(dict(limit=1000, offset=offset, f="json", bbox=",".join(map(str, bbox))))
        url = TRAFFIC_COLLECTION + "/items?" + query
        data, headers = request_json(url)
        batch = data.get("features", [])
        if data.get("type") != "FeatureCollection":
            raise ValueError("Traffic service did not return a FeatureCollection")
        matched = data.get("numberMatched")
        if total is None:
            total = matched
        if total is not None and matched != total:
            raise ValueError("Traffic collection changed during pagination; retry one complete snapshot")
        for feature in batch:
            identity = str(feature.get("properties", {}).get("XDSegID") or feature.get("id"))
            if identity in seen:
                raise ValueError("Duplicate traffic identity during pagination")
            seen.add(identity)
            features.append(feature)
        pages.append(dict(url=url, http_date=headers.get("Date"), returned=len(batch)))
        if (total is not None and len(features) >= total) or len(batch) < 1000:
            break
    else:
        raise ValueError("Study exceeds the bounded 20,000-feature fetch limit")
    if total is not None and len(features) != total:
        raise ValueError("Incomplete traffic response")
    return dict(type="FeatureCollection", features=features, numberMatched=total,
                numberReturned=len(features)), pages


def overpass_query(bbox):
    west, south, east, north = bbox
    highways = "motorway|trunk|primary|secondary|tertiary|unclassified|residential|service|living_street|road|motorway_link|trunk_link|primary_link|secondary_link|tertiary_link"
    return f'[out:json][timeout:50];way["highway"~"^({highways})$"]({south},{west},{north},{east});out meta geom;'


def build_osm_database(data, path, source_sha):
    if data.get("remark"):
        raise ValueError("Overpass returned an error/partial response: " + str(data["remark"]))
    # This DB belongs to the prototype and is disposable; source datasets remain read-only.
    if path.exists():
        path.unlink()
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT NOT NULL);
        CREATE TABLE ways(way_id INTEGER PRIMARY KEY,highway TEXT,street_name TEXT,ref TEXT,
          maxspeed TEXT,maxspeed_forward TEXT,maxspeed_backward TEXT,maxspeed_type TEXT,
          source_maxspeed TEXT,min_lon REAL,min_lat REAL,max_lon REAL,max_lat REAL);
        CREATE TABLE way_geom(way_id INTEGER PRIMARY KEY,points_json TEXT NOT NULL);
        CREATE VIRTUAL TABLE ways_rtree USING rtree(way_id,min_lon,max_lon,min_lat,max_lat);
        CREATE TABLE road_speed_source_tag(way_id INTEGER,key TEXT,raw_value TEXT,
          source_snapshot TEXT,PRIMARY KEY(way_id,key));
        CREATE TABLE traffic_sign_way_direction(way_id INTEGER PRIMARY KEY,oneway INTEGER,
          forward_allowed INTEGER,backward_allowed INTEGER,start_node_key TEXT,end_node_key TEXT);
    """)
    count = 0
    for way in data.get("elements", []):
        if way.get("type") != "way" or not way.get("tags", {}).get("highway"):
            continue
        coordinates = way.get("geometry", [])
        nodes = way.get("nodes", [])
        if len(coordinates) < 2 or len(nodes) != len(coordinates) or any(p is None for p in coordinates):
            raise ValueError("Incomplete OSM source geometry for " + str(way.get("id")))
        tags, identity = way["tags"], way["id"]
        b = bounds([[p["lon"], p["lat"]] for p in coordinates])
        values = [identity, tags.get("highway"), tags.get("name"), tags.get("ref"),
                  tags.get("maxspeed"), tags.get("maxspeed:forward"), tags.get("maxspeed:backward"),
                  tags.get("maxspeed:type"), tags.get("source:maxspeed"), *b]
        db.execute("INSERT INTO ways VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)", values)
        db.execute("INSERT INTO way_geom VALUES (?,?)", (identity, json.dumps([[p["lat"], p["lon"]] for p in coordinates])))
        db.execute("INSERT INTO ways_rtree VALUES (?,?,?,?,?)", (identity, b[0], b[2], b[1], b[3]))
        db.executemany("INSERT INTO road_speed_source_tag VALUES (?,?,?,?)",
                       [(identity, key, str(value), source_sha) for key, value in tags.items()])
        raw_oneway = str(tags.get("oneway:motorcar", tags.get("oneway:motor_vehicle", tags.get("oneway", "")))).lower()
        implied = tags.get("junction") == "roundabout" or tags.get("highway") in ("motorway", "motorway_link")
        oneway = -1 if raw_oneway in ("-1", "reverse") else 1 if raw_oneway in ("yes", "true", "1") or (not raw_oneway and implied) else 0
        unresolved_direction = raw_oneway not in ("", "0", "no", "false", "yes", "true", "1", "-1", "reverse") or any(
            key.startswith("oneway") and "conditional" in key for key in tags)
        db.execute("INSERT INTO traffic_sign_way_direction VALUES (?,?,?,?,?,?)",
                   (identity, oneway, int(oneway != -1 and not unresolved_direction),
                    int(oneway != 1 and not unresolved_direction), str(nodes[0]), str(nodes[-1])))
        count += 1
    if not count:
        raise ValueError("No usable OSM ways")
    metadata = dict(source_type="fresh_overpass_extract", source_snapshot_sha256=source_sha,
                    source_osm_timestamp=data.get("osm3s", {}).get("timestamp_osm_base", "unknown"),
                    road_geometry_policy="source_vertices_v1", source_way_count=str(count))
    db.executemany("INSERT INTO metadata VALUES (?,?)", metadata.items())
    db.commit()
    db.close()
    return metadata


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--gpx", type=Path)
    parser.add_argument("--map-url", default="https://verkehrsinfo-bw.de/?loc=48.80602,8.53271,13.41z")
    parser.add_argument("--width", type=int, default=1280)
    parser.add_argument("--height", type=int, default=800)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--traffic-file", type=Path)
    parser.add_argument("--osm-file", type=Path)
    parser.add_argument("--fetched-at", help="Actual traffic retrieval time, ISO 8601 with UTC offset")
    parser.add_argument("--fetch", action="store_true", help="Send only study bounding boxes to both public services")
    parser.add_argument("--analyze", action="store_true", help="Also run the conservative matcher and write viewer data")
    parser.add_argument("--speed-field", choices=("speed", "average_speed"), default="average_speed",
                        help="Rank Durchschnitt (average_speed, default) or Aktuell (speed)")
    args = parser.parse_args()
    output = args.output_dir.resolve()
    inputs = output / "inputs"
    inputs.mkdir(parents=True, exist_ok=True)
    if args.gpx:
        route = load_gpx(args.gpx)
        points = geometry_points(route)
        b = bounds(points, margin_m=250)
        projection = Projection((b[0] + b[2]) / 2, (b[1] + b[3]) / 2)
        distance = sum(p["weight"] for p in sample_geometry(route, projection, spacing=20))
        scope = dict(kind="gpx", label="Way to work", route_name=args.gpx.stem, route=route,
                     bbox=b, center=[(b[0] + b[2]) / 2, (b[1] + b[3]) / 2], route_distance_m=distance,
                     gpx_sha256=sha256(args.gpx), timestamp_scope="planned route; no recorded driving time used")
    else:
        scope = map_scope(args.map_url, args.width, args.height)
    if not args.fetch and not (args.traffic_file and args.osm_file):
        parser.error("Use --fetch after approving bounding-box disclosure, or provide both offline source files")
    pages = []
    if args.traffic_file:
        traffic = json.loads(args.traffic_file.read_text())
    else:
        traffic, pages = fetch_traffic(scope["bbox"])
    traffic_fetched_at = args.fetched_at or datetime.now(timezone.utc).isoformat()
    traffic_path = inputs / "traffic.geojson"
    save_json(traffic_path, traffic)
    traffic_points = [p for feature in traffic.get("features", []) for p in geometry_points(feature["geometry"])]
    osm_bbox = bounds(traffic_points + (geometry_points(scope["route"]) if args.gpx else []), margin_m=100)
    query = overpass_query(osm_bbox)
    (inputs / "osm-query.overpassql").write_text(query + "\n")
    if args.osm_file:
        osm_data = json.loads(args.osm_file.read_text())
    else:
        osm_data, _ = request_json(OVERPASS, urllib.parse.urlencode({"data": query}).encode())
    osm_path = inputs / "osm.json"
    save_json(osm_path, osm_data)
    osm_metadata = build_osm_database(osm_data, inputs / "osm-study.sqlite", sha256(osm_path))
    metadata = dict(scope=scope, fetched_at=traffic_fetched_at, selected_speed_field=args.speed_field,
                    input=dict(traffic_sha256=sha256(traffic_path), osm_sha256=sha256(osm_path),
                               traffic_pages=pages, osm_metadata=osm_metadata),
                    provider_timestamp_note="Source observed_at has no UTC offset. Displayed verbatim; Europe/Berlin is an unverified interpretation, not a confirmed source timezone.",
                    sources=[dict(name="VerkehrsInfo BW / INRIX traffic", url=TRAFFIC_COLLECTION,
                                  description="Current, historical and reference segment speeds. Public access verified; reuse/caching licence and speed capping remain unconfirmed."),
                             dict(name="OpenStreetMap contributors", url="https://www.openstreetmap.org/copyright",
                                  description="ODbL. Fresh road geometry and full source speed tags via Overpass; database time " + osm_metadata["source_osm_timestamp"]),
                             dict(name="INRIX confidence definitions", url="https://docs.inrix.com/ra/datanetworkandxdtraffic/",
                                  description="Source score and c-value describe Aktuell. A separate confidence score or sample size for Durchschnitt is not supplied; the current quality index does not rate the historical profile.")])
    save_json(output / "input-metadata.json", metadata)
    if args.analyze:
        report = analyze(inputs / "osm-study.sqlite", traffic, scope["bbox"], metadata,
                         route_geometry=scope.get("route"), speed_field=args.speed_field)
        write_outputs(report, output)
    print(json.dumps(dict(scope=scope["kind"], bbox=scope["bbox"], traffic_features=len(traffic.get("features", [])),
                          osm_ways=osm_metadata["source_way_count"], metadata=str(output / "input-metadata.json"))))


if __name__ == "__main__":
    main()
