#!/usr/bin/env python3
"""Freeze Geofabrik extract geometry for first-fix discovery, before downloads.

Input is the public index-v1.json (no PBFs are fetched). Output is deliberately
limited to the app's bundle targets and retains the exact MultiPolygon rings.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
TARGETS = ROOT / "iphone/SpeedConsumerApp/BundleTargets.top10.json"
OUTPUT = ROOT / "shared/RegionalCoverage/catalog-v1.json"


def geometry_coordinates(geometry):
    if geometry["type"] == "Polygon":
        polygons = [geometry["coordinates"]]
    elif geometry["type"] == "MultiPolygon":
        polygons = geometry["coordinates"]
    else:
        raise ValueError("Only Polygon and MultiPolygon are supported")
    if not polygons:
        raise ValueError("Empty geometry")
    for polygon in polygons:
        if not polygon:
            raise ValueError("Missing outer ring")
        for ring in polygon:
            if len(ring) < 4 or ring[0] != ring[-1]:
                raise ValueError("Rings must be closed and contain at least three vertices")
            for point in ring:
                if (len(point) != 2 or not all(math.isfinite(v) for v in point)
                        or not -180 <= point[0] <= 180 or not -90 <= point[1] <= 90):
                    raise ValueError("Invalid longitude/latitude")
    return polygons


def build_catalog(index_bytes: bytes, targets_bytes: bytes):
    features = {f["properties"]["id"]: f for f in json.loads(index_bytes)["features"]}
    entries = []
    for country in json.loads(targets_bytes)["countries"]:
        for region in country["regions"]:
            region_id = region["region_id"]
            if country["mode"] == "regional_shards" and "/" not in region_id:
                region_id = country["country_id"] + "/" + region_id
            # Geofabrik ids are not always path-qualified. Resolve by the
            # configured parent, never by an arbitrary similarly named region.
            feature = features.get(region_id) or features.get(region_id.rsplit("/", 1)[-1])
            if feature is None:
                raise ValueError(f"Missing Geofabrik geometry: {region_id}")
            props = feature["properties"]
            if country["mode"] == "regional_shards" and props["parent"] != region_id.rsplit("/", 1)[0].rsplit("/", 1)[-1]:
                raise ValueError(f"Unexpected Geofabrik parent: {region_id}")
            polygons = geometry_coordinates(feature["geometry"])
            points = [p for polygon in polygons for ring in polygon for p in ring]
            pbf_url = props["urls"]["pbf"]
            if not pbf_url.startswith("https://download.geofabrik.de/") or not pbf_url.endswith("-latest.osm.pbf"):
                raise ValueError("Unexpected public Geofabrik PBF URL")
            entries.append({
                "id": country["country_id"] + "|" + region_id.rsplit("/", 1)[-1],
                "country": country["iso2"],
                "region": region_id.rsplit("/", 1)[-1],
                "source_pbf": pbf_url,
                "source_poly": pbf_url.removesuffix("-latest.osm.pbf") + ".poly",
                "bbox": [min(p[0] for p in points), min(p[1] for p in points),
                         max(p[0] for p in points), max(p[1] for p in points)],
                "polygons": polygons,
            })
    if len({e["id"] for e in entries}) != len(entries):
        raise ValueError("Duplicate region")
    return {
        "schema_version": 1,
        "source": "https://download.geofabrik.de/index-v1.json",
        "source_sha256": hashlib.sha256(index_bytes).hexdigest(),
        "targets_sha256": hashlib.sha256(targets_bytes).hexdigest(),
        "attribution": "Geofabrik GmbH and OpenStreetMap contributors; ODbL 1.0",
        "boundary_kind": "buffered_extract_coverage",
        "regions": sorted(entries, key=lambda e: e["id"]),
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", type=Path, required=True)
    parser.add_argument("--targets", type=Path, default=TARGETS)
    parser.add_argument("--output", type=Path, default=OUTPUT)
    args = parser.parse_args()
    result = build_catalog(args.index.read_bytes(), args.targets.read_bytes())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, separators=(",", ":"), allow_nan=False) + "\n")
    print(f"Wrote {len(result['regions'])} regions to {args.output}")


if __name__ == "__main__":
    main()
