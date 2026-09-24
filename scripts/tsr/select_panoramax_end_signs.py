#!/usr/bin/env python3
"""Select a bounded, metadata-only end-sign review queue from Panoramax.

No image downloads, training, uploads, or assumption that machine tags are truth.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import math
from pathlib import Path
from urllib.parse import urlparse

import requests

DEFAULT_ENDPOINT = "https://panoramax.openstreetmap.fr/api/search"
DEFAULT_TAGS = ["FR:B31", "FR:B33[30]", "FR:B33[50]", "FR:B33[70]", "FR:B33[90]"]


def tag_filter(tag: str) -> str:
    return '"semantics.osm|traffic_sign" = \'' + tag.replace("'", "''") + "'"


def select_annotations(feature: dict, wanted: set[str]) -> list[dict]:
    properties = feature.get("properties", {})
    camera = properties.get("pers:interior_orientation", {})
    dimensions = camera.get("sensor_array_dimensions")
    records = []
    for annotation in properties.get("annotations", []):
        tags = annotation.get("semantics", [])
        labels = {t.get("value") for t in tags if t.get("key") == "osm|traffic_sign"} & wanted
        if not labels:
            continue
        shape = annotation.get("shape", {})
        rings = shape.get("coordinates", [])
        if shape.get("type") != "Polygon" or not rings or len(rings[0]) < 4:
            continue
        points = rings[0]
        if not all(isinstance(p, list) and len(p) >= 2 and
                   all(isinstance(v, (float, int)) and math.isfinite(v) for v in p[:2]) for p in points):
            continue
        xs, ys = [p[0] for p in points], [p[1] for p in points]
        box = [min(xs), min(ys), max(xs), max(ys)]
        if box[0] < 0 or box[1] < 0 or box[0] >= box[2] or box[1] >= box[3]:
            continue
        if dimensions and (box[2] > dimensions[0] or box[3] > dimensions[1]):
            continue
        records.append({
            "picture_id": feature["id"], "sequence_id": feature.get("collection"),
            "annotation_id": annotation["id"], "suggested_labels": sorted(labels),
            "review_status": "unreviewed", "eligible_for_training": False,
            "bbox_pixels": box, "shape": shape, "image_dimensions": dimensions,
            "field_of_view": camera.get("field_of_view"),
            "requires_perspective_projection": camera.get("field_of_view") == 360,
            "semantics": tags, "capture_time": properties.get("datetime"),
            "coordinates": feature.get("geometry", {}).get("coordinates"),
            "producer": properties.get("geovisio:producer"), "license": properties.get("license"),
            "source_url": next((v["href"] for v in feature.get("links", []) if v.get("rel") == "self"), None),
            "assets": feature.get("assets", {}),
            "grouping_required": ["sequence", "physical_sign_location", "image_hash"],
        })
    return records


def collect(endpoint: str, tags: list[str], limit: int, bbox: str | None = None,
            session=None) -> dict:
    session = session or requests.Session()
    session.headers.update({"User-Agent": "youspeed-end-sign-review/1.0"})
    records, queries, seen = [], [], set()
    for tag in tags:
        params = {"filter": tag_filter(tag), "limit": limit}
        if bbox:
            params["bbox"] = bbox
        response = session.get(endpoint, params=params, timeout=(10, 60))
        response.raise_for_status()
        payload = response.json()
        if payload.get("type") != "FeatureCollection" or not isinstance(payload.get("features"), list):
            raise ValueError("Expected a Panoramax FeatureCollection")
        features = payload["features"]
        queries.append({"tag": tag, "url": response.url, "returned_pictures": len(features),
                        "possibly_truncated": len(features) >= limit,
                        "next_links": [v for v in payload.get("links", []) if v.get("rel") == "next"]})
        for feature in features:
            for record in select_annotations(feature, set(tags)):
                key = (record["picture_id"], record["annotation_id"])
                if key not in seen:
                    seen.add(key)
                    records.append(record)
    return {"schema_version": 1, "created_at": datetime.now(timezone.utc).isoformat(),
            "endpoint": endpoint, "complete_inventory": False, "queries": queries,
            "records": records, "training_ready_count": 0}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--endpoint", default=DEFAULT_ENDPOINT)
    parser.add_argument("--tag", action="append", help="Repeat for exact OSM labels, e.g. FR:B33[50]")
    parser.add_argument("--limit", type=int, default=25, help="Bounded picture sample per tag, maximum 1000")
    parser.add_argument("--bbox", help="west,south,east,north")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if urlparse(args.endpoint).scheme != "https" or not 1 <= args.limit <= 1000:
        parser.error("Use an HTTPS endpoint and a limit between 1 and 1000")
    if args.bbox:
        try:
            w, s, e, n = map(float, args.bbox.split(','))
            if not (-180 <= w < e <= 180 and -90 <= s < n <= 90):
                raise ValueError()
        except ValueError:
            parser.error("bbox must be west,south,east,north within WGS84 bounds")
    try:
        result = collect(args.endpoint, args.tag or DEFAULT_TAGS, args.limit, args.bbox)
    except (requests.RequestException, ValueError) as exc:
        parser.exit(1, f"Selection failed; no complete output written: {exc}\n")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    print(f"Selected {len(result['records'])} unreviewed annotations; no training labels approved.")


if __name__ == "__main__":
    main()
