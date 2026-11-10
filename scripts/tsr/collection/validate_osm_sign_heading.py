"""Compare OSM heading fallback with the independently published Freiburg WFS."""

from __future__ import annotations

import argparse
from collections import Counter
from hashlib import sha256
import json
from pathlib import Path
from statistics import median, quantiles
from types import SimpleNamespace

from fiona.transform import transform
from shapely.geometry import Point

from scripts.tsr.collection.estimate_sign_poses import (
    METRIC,
    WGS84,
    SIGN_CODE,
    delta_angle,
    project,
)
from scripts.tsr.collection.osm_sign_heading import RoadHeadingIndex, SIDE_CLASSES


def run(reference, graph):
    raw = reference.read_bytes()
    source = json.loads(raw)
    if (
        source.get("crs", {}).get("properties", {}).get("name")
        != "urn:ogc:def:crs:EPSG::25832"
    ):
        raise ValueError("expected original Freiburg EPSG:25832 coordinates")
    features = source["features"]
    if source["numberMatched"] != len(features) or len(
        {row["properties"]["id"] for row in features}
    ) != len(features):
        raise ValueError("reference count mismatch or duplicate IDs")
    rows = []
    for row in features:
        fields = row["properties"]
        code = "DE:" + fields["stvo_nr"]
        if SIGN_CODE.fullmatch(code) and code[3:].split("-", 1)[0] in SIDE_CLASSES:
            rows.append(
                (tuple(row["geometry"]["coordinates"]), code, int(fields["azimut"]))
            )
    eastings, northings = zip(*(point for point, _, _ in rows))
    lons, lats = transform(METRIC, WGS84, eastings, northings)
    rotation = [value for _, value in project(lons, lats)]
    road_index = RoadHeadingIndex.load(graph)
    metrics = {}
    for radius in (0.5, 18.0):
        errors = []
        methods, withheld = Counter(), Counter()
        for (point, code, expected), lon, lat, convergence in zip(
            rows, lons, lats, rotation
        ):
            region = tuple(
                Point(point).buffer(radius, quad_segs=4).exterior.coords[:-1]
            )
            fit = SimpleNamespace(point=point, radius=radius, region=region, rays=())
            result = road_index.heading(fit, code, lon, lat)
            if result.facing is None:
                withheld[result.status] += 1
                continue
            errors.append(delta_angle(result.facing - convergence, expected))
            methods[result.method] += 1
        metrics[str(radius)] = {
            "evaluated": len(rows),
            "assigned": len(errors),
            "within_30_deg": sum(error <= 30 for error in errors),
            "near_reversal_150_deg_or_more": sum(error >= 150 for error in errors),
            "median_circular_error_deg": round(median(errors), 1) if errors else None,
            "p90_circular_error_deg": round(
                quantiles(errors, n=10, method="inclusive")[-1], 1
            )
            if len(errors) > 1
            else None,
            "methods": dict(methods),
            "withheld": dict(withheld),
        }
    return {
        "reference": {
            "source": "Stadt Freiburg im Breisgau Verkehrszeichen 2024",
            "url": "https://mobidata-bw.de/de/dataset/vz-freiburg",
            "sha256": sha256(raw).hexdigest(),
            "source_count": len(features),
            "eligible_class_count": len(rows),
            "used_reference_azimuth_only_for_scoring": True,
        },
        "osm_graph_source": road_index.source,
        "position_radius_m": metrics,
        "notes": "The 18 m condition expands the reference point's uncertainty envelope without moving the reference point. No image evidence was supplied.",
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--osm-road-graph", type=Path, required=True)
    args = parser.parse_args()
    print(
        json.dumps(run(args.reference, args.osm_road_graph), indent=2, sort_keys=True)
    )


if __name__ == "__main__":
    main()
