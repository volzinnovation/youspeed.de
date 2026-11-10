"""Score frozen image/sign correspondences against Freiburg's WFS reference."""

from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
from statistics import median
from types import SimpleNamespace

from fiona.transform import transform

from scripts.tsr.collection.estimate_sign_poses import (
    MAX_HEADING_ERROR_DEG,
    METRIC,
    WGS84,
    Ray,
    delta_angle,
    heading_interval,
    image_bearing_candidate,
    independent,
    project,
)
from scripts.tsr.collection.sign_panel_pose import panel_heading


def summarize(errors):
    return {
        "count": len(errors),
        "median_circular_error_deg": round(median(errors), 1) if errors else None,
        "maximum_circular_error_deg": round(max(errors), 1) if errors else None,
        "within_30_deg": sum(error <= 30 for error in errors),
        "near_reversals_150_deg_or_more": sum(error >= 150 for error in errors),
    }


def benchmark(reference, matches, rays, panels=()):
    published = json.loads(reference.read_bytes())
    if (
        published.get("crs", {}).get("properties", {}).get("name")
        != "urn:ogc:def:crs:EPSG::25832"
    ):
        raise ValueError("expected Freiburg's original projected coordinates")
    features = {str(item["properties"]["id"]): item for item in published["features"]}
    by_group = defaultdict(list)
    for record in rays:
        by_group[record["group_id"]].append(record)
    by_panel = defaultdict(list)
    for item in panels:
        by_panel[str(item["survey_id"])].append(item)
    results, proxy_errors, narrow_errors, panel_errors = [], [], [], []
    seen = set()
    for match in matches:
        key = str(match["survey_id"])
        if key in seen:
            raise ValueError("duplicate reference sign in this validation cohort")
        seen.add(key)
        feature = features[key]
        point = tuple(feature["geometry"]["coordinates"])
        (lon,), (lat,) = transform(METRIC, WGS84, [point[0]], [point[1]])
        _, convergence = project([lon], [lat])[0]
        records = by_group[match["group_id"]]
        if not records or any(
            row["sign_code"] != "DE:" + feature["properties"]["stvo_nr"]
            for row in records
        ):
            raise ValueError("frozen association lacks matching sign class")
        positions = project(
            [r["longitude"] for r in records], [r["latitude"] for r in records]
        )
        observed = independent(
            [
                Ray.parse(row, position, rotation)
                for row, (position, rotation) in zip(records, positions)
            ]
        )
        proxy = image_bearing_candidate(observed)
        visibility = heading_interval(
            SimpleNamespace(point=point, radius=0.0, rays=observed)
        )
        accepted = visibility is not None and visibility[1] <= MAX_HEADING_ERROR_DEG
        reviewed_panels = by_panel[key]
        if {item["image_id"] for item in reviewed_panels} - {
            row["image_id"] for row in records
        }:
            raise ValueError("panel frame does not match the frozen image association")
        panel = panel_heading(reviewed_panels) if reviewed_panels else None
        # The reference angle is read only after candidate computation.
        azimut = float(feature["properties"]["azimut"])
        result = {
            "survey_id": key,
            "sightings": len(observed),
            "reference_deg": azimut,
            "poses": sorted({ray.pose_basis for ray in observed}),
        }
        if proxy is not None:
            predicted = (proxy.heading - convergence) % 360
            error = delta_angle(predicted, azimut)
            result.update(
                proxy_deg=round(predicted, 1), proxy_error_deg=round(error, 1)
            )
            proxy_errors.append(error)
        if accepted:
            narrow_errors.append(delta_angle(visibility[0] - convergence, azimut))
        if panel is not None:
            error = delta_angle(panel["azimut_deg"], azimut)
            result["panel"] = panel | {"error_deg": round(error, 1)}
            panel_errors.append(error)
        results.append(result)
    return {
        "matched_signs": len(results),
        "center_ray_proxy": summarize(proxy_errors),
        "narrow_visibility_estimates": summarize(narrow_errors),
        "panel_homography": summarize(panel_errors),
        "cases": results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, required=True)
    parser.add_argument("--matches", type=Path, required=True)
    parser.add_argument("--rays", type=Path, required=True)
    parser.add_argument("--panel-evidence", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            benchmark(
                args.reference,
                json.loads(args.matches.read_bytes()),
                [
                    json.loads(line)
                    for line in args.rays.read_text().splitlines()
                    if line.strip()
                ],
                json.loads(args.panel_evidence.read_bytes())
                if args.panel_evidence
                else (),
            ),
            indent=2,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
