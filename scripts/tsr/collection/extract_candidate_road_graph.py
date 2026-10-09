#!/usr/bin/env python3
"""Build a bounded offline graph from a pinned OSM source, preserving node IDs.

The output is analyst context, not a deployable bundle or legal routing graph.
Bounds derived from private journeys and their output belong to the same source
lifecycle as those journeys. Do not put them in public/aggregate backups.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tempfile
import xml.etree.ElementTree as ET

try:
    from .sign_road_association import direction_from_tags, point, sha256, validate_bounds
except ImportError:  # Direct command-line invocation from this directory.
    from sign_road_association import direction_from_tags, point, sha256, validate_bounds

ROAD_CLASSES = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified",
                "residential", "service", "living_street", "road", "motorway_link", "trunk_link",
                "primary_link", "secondary_link", "tertiary_link"}
TAGS = {"highway", "name", "ref", "oneway", "junction", "layer", "bridge", "tunnel",
        "lanes", "lanes:forward", "lanes:backward", "turn:lanes", "turn:lanes:forward",
        "turn:lanes:backward", "destination", "destination:ref", "access", "vehicle",
        "motor_vehicle", "motorcar", "service"}


def extract_graph(source, bounds_wgs84, expected_sha256, max_ways=100000, max_points=2000000):
    source = Path(source)
    if not 1 <= len(bounds_wgs84) <= 256:
        raise ValueError("invalid_region_count")
    regions = [validate_bounds(b) for b in bounds_wgs84]
    if any((e - w) * (n - s) > 4 for w, s, e, n in regions):
        raise ValueError("region_area_cap_exceeded")
    if type(max_ways) is not int or type(max_points) is not int or not (1 <= max_ways <= 1000000 and 2 <= max_points <= 10000000):
        raise ValueError("invalid_extraction_caps")
    if source.is_symlink() or source.stat().st_size > 4 * 1024**3:
        raise ValueError("invalid_source_file")
    before = source.stat()
    if sha256(source) != expected_sha256:
        raise ValueError("source_hash_mismatch")
    roads = []
    retained_ids = set()
    counts = {"source_eligible_ways_scanned": 0, "retained_points": 0}

    def keep(identity, tags, refs, coords):
        if tags.get("highway") not in ROAD_CLASSES:
            return
        counts["source_eligible_ways_scanned"] += 1
        if len(refs) < 2 or len(refs) != len(coords):
            raise ValueError("source_way_missing_geometry")
        for coord in coords:
            lat, lon = point(coord)
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                raise ValueError("invalid_source_coordinate")
        xs, ys = [p[1] for p in coords], [p[0] for p in coords]
        west, east, south, north = min(xs), max(xs), min(ys), max(ys)
        if not any(west <= e and east >= w and south <= n and north >= s for w, s, e, n in regions):
            return
        identity = str(identity)
        if identity in retained_ids:
            raise ValueError("duplicate_source_way")
        retained_ids.add(identity)
        counts["retained_points"] += len(coords)
        if len(roads) >= max_ways or counts["retained_points"] > max_points:
            raise ValueError("extraction_cap_exceeded_no_partial_result")
        kept_tags = {k: v for k, v in tags.items() if k in TAGS or k.startswith(("oneway:", "access:", "motor_vehicle:", "restriction:"))}
        roads.append({"way_id": identity, "node_ids": list(map(str, refs)), "points_lat_lon": coords,
                      "tags": kept_tags, "direction": direction_from_tags(kept_tags),
                      "geometry_error_bound_m": 0.0})

    if source.suffix == ".pbf":
        import osmium
        reader = osmium.io.Reader(str(source))
        header = reader.header()
        source_header = {k: header.get(k) for k in ("generator", "osmosis_replication_base_url",
                         "osmosis_replication_timestamp", "osmosis_replication_sequence_number")}
        reader.close()

        class Handler(osmium.SimpleHandler):
            def way(self, way):
                if way.tags.get("highway") not in ROAD_CLASSES:
                    return
                if any(not n.location.valid() for n in way.nodes):
                    raise ValueError("source_way_missing_referenced_node")
                keep(way.id, dict(way.tags), [n.ref for n in way.nodes],
                     [[n.location.lat, n.location.lon] for n in way.nodes])

        # File-backed node-location cache: no regional all-node Python dictionary.
        # Only retained way geometries occupy the returned Python graph.
        with tempfile.TemporaryDirectory(prefix="youspeed-osm-node-index-") as scratch:
            Handler().apply_file(str(source), locations=True,
                                 idx="sparse_file_array," + str(Path(scratch) / "nodes.idx"))
    else:
        if source.stat().st_size > 10 * 1024 * 1024:
            raise ValueError("xml_fixture_size_cap")
        root = ET.fromstring(source.read_bytes())
        if root.tag != "osm":
            raise ValueError("expected_osm")
        nodes = {n.attrib["id"]: [float(n.attrib["lat"]), float(n.attrib["lon"])] for n in root.findall("node")}
        source_header = {"format": "osm-xml", "generator": root.get("generator")}
        for way in root.findall("way"):
            refs = [n.attrib["ref"] for n in way.findall("nd")]
            tags = {t.attrib["k"]: t.attrib["v"] for t in way.findall("tag")}
            if tags.get("highway") in ROAD_CLASSES:
                if any(ref not in nodes for ref in refs):
                    raise ValueError("source_way_missing_referenced_node")
                keep(way.attrib["id"], tags, refs, [nodes[ref] for ref in refs])
    after = source.stat()
    if (before.st_dev, before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns) or sha256(source) != expected_sha256:
        raise ValueError("source_changed_during_extraction")
    roads.sort(key=lambda r: int(r["way_id"]))
    return {"schema_version": 1,
            "source": {"kind": "original_osm", "sha256": expected_sha256, "bytes": after.st_size,
                       "header": source_header, "topology": "original_osm_node_ids",
                       "geometry_bounds_known": True, "geometry_policy": "complete_source_vertices_v1",
                       "geometry_bound_meaning": "zero simplification error relative to original OSM segments, not real-world road accuracy",
                       "is_as_driven": False, "attribution": "OpenStreetMap contributors", "license": "ODbL-1.0"},
            "extraction": {"bounds_wgs84": [list(b) for b in regions], "road_classes": sorted(ROAD_CLASSES),
                           "candidate_complete_within_source_bbox": True, "node_geometry_complete": True,
                           "legal_routing_complete": False, "max_ways": max_ways, "max_points": max_points,
                           **counts, "retained_ways": len(roads)},
            "limitations": ["Original OSM geometry is not ground-truth geometry or sign applicability.",
                            "Whole intersecting ways retain all nodes; coverage is bounded and may omit remote connecting routes.",
                            "Missing direction stays unknown; turn-restriction relations and conditional/access legality are not resolved.",
                            "Query footprint and graph derivatives inherit source journey lifecycle when based on private captures."],
            "roads": roads}


def write_once(path, value):
    data = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode()
    with Path(path).open("xb") as stream:
        stream.write(data)
    return hashlib.sha256(data).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--source-sha256", required=True)
    parser.add_argument("--regions-json", type=Path, required=True, help="List of [west,south,east,north] rectangles")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--max-ways", type=int, default=100000)
    parser.add_argument("--max-points", type=int, default=2000000)
    args = parser.parse_args()
    if args.output.exists() or args.output.with_suffix(".receipt.json").exists():
        raise ValueError("output_already_exists")
    regions = args.regions_json.read_bytes()
    result = extract_graph(args.source, json.loads(regions), args.source_sha256, args.max_ways, args.max_points)
    args.output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    output_sha = write_once(args.output, result)
    receipt = {"schema_version": 1, "output_sha256": output_sha, "source_sha256": args.source_sha256,
               "regions_sha256": hashlib.sha256(regions).hexdigest(), "script_sha256": sha256(__file__),
               "road_module_sha256": sha256(Path(__file__).with_name("sign_road_association.py")),
               "retained_ways": len(result["roads"]), "retained_points": result["extraction"]["retained_points"],
               "source_modified": False, "crop_payloads_included": False,
               "query_footprint_privacy": "derived context; preserve under source lifecycle, not public aggregate backup"}
    write_once(args.output.with_suffix(".receipt.json"), receipt)
    print(json.dumps({"retained_ways": receipt["retained_ways"], "retained_points": receipt["retained_points"], "output_sha256": output_sha}))


if __name__ == "__main__":
    main()
