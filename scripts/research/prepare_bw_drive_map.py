#!/usr/bin/env python3
"""Prepare private, compact map data from the read-only BW route audit.

No raw coordinates are stored in this script or uploaded. The output is intended
for a local visualization, not a public report or a new mobile bundle.
"""
import argparse
import base64
import json
import math
import sqlite3
from pathlib import Path


def coordinates(value):
    if isinstance(value, (float, int)):
        return round(value, 5)
    return [coordinates(v) for v in value]


def source_name(source):
    if source and source.startswith("INVENTORY"):
        return "inventory"
    if source in ("EXPLICIT_TAG", "EXPLICIT_UNLIMITED_TAG"):
        return "osm"
    if source in ("HIGHWAY_CLASS", "COUNTRY_DEFAULT", "ROAD_DEFAULT"):
        return "default"
    return "unknown"


def load_review(directory, platform):
    geo = json.loads((directory / "route-sign-map.geojson").read_text())
    track_path = directory / ("route-points-v15.json" if platform == "iphone" else "route-points-drive-overlap.json")
    track = json.loads(track_path.read_text())
    active = {}
    if platform == "iphone":
        for point in track:
            rule = point.get("inventory_rule")
            if rule:
                item = active.setdefault(rule["signID"], {"first": point["timestamp"], "last": point["timestamp"], "speed": rule.get("speedKmh"), "code": rule.get("code")})
                item["last"] = point["timestamp"]
    result = {"platform": platform, "roads": [], "route": [], "signs": [], "endpoints": []}
    for feature in geo["features"]:
        p, g = feature["properties"], feature["geometry"]
        if p["layer"] == "road":
            result["roads"].append([p.get("highway"), p.get("street_name") or p.get("street_ref"), coordinates(g["coordinates"])])
        elif p["layer"] == "route":
            # Android's historical enum conflated OSM tags and inventory rules.
            # Preserve that missing provenance instead of inventing a source.
            source = source_name(p.get("source")) if platform == "iphone" else "unknown"
            result["route"].append([source, p.get("effective_speed"), coordinates(g["coordinates"])])
        elif p["layer"] == "sign":
            sign_id = p["sign_id"]
            applied = active.get(sign_id)
            selected = [p.get("r%d_selected_slot_fix_count" % r, p.get("picked_fix_count", 0) if r == 10 else 0) for r in (10, 20, 30)]
            result["signs"].append({
                "id": sign_id, "xy": coordinates(g["coordinates"]),
                "code": p["sign_code"], "kind": p["kind"], "source": p["source_id"],
                "value": p.get("numeric_value"), "radius": p["display_radius_m"],
                "road": p.get("nearest_road"), "at": p.get("picked_first_at") or p.get("nearest_route_at"),
                "distance": p.get("min_fix_distance_m"),
                "chainage": p.get("nearest_route_chainage_m"), "selected": selected,
                "icon": Path(p["pictogram_path"]).name if p.get("pictogram_path") else None,
                "applied": applied,
                "runs": [{"fixes": x["fixes"]} for x in p.get("selection_runs", [])[:1]],
            })
    result["signs"].sort(key=lambda x: (x["chainage"] if x["chainage"] is not None else math.inf, x["id"]))
    result["endpoints"] = [[round(point["lon"], 5), round(point["lat"], 5)] for point in (track[0], track[-1])]
    coverage = json.loads((directory / "route-sign-coverage.json").read_text())
    result["km"] = round(coverage["track"]["connected_distance_m"] / 1000, 1)
    result["fixes"] = len(track)
    result["start"], result["end"] = track[0]["timestamp"], track[-1]["timestamp"]
    result["activeNumeric"] = sum(item["speed"] is not None for item in active.values())
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iphone", type=Path, required=True)
    parser.add_argument("--android", type=Path)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--artwork", type=Path, required=True)
    parser.add_argument("--comparison", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    reviews = [load_review(args.iphone, "iphone")]
    if args.android:
        reviews.append(load_review(args.android, "android"))
        shared_sign_context = {s["id"]: s for s in reviews[0]["signs"]}
        for sign in reviews[1]["signs"]:
            context = shared_sign_context.get(sign["id"])
            if context:
                # Road labels and route order describe the common source point;
                # never substitute iPhone trigger times for missing Android logs.
                sign["road"] = sign["road"] or context["road"]
                sign["chainage"] = context["chainage"]
        reviews[1]["signs"].sort(key=lambda s: (s["chainage"] if s["chainage"] is not None else math.inf, s["id"]))
    comparison = None
    faces = {}
    audit_file = args.iphone / "selected-opposite-direction-audit.json"
    if audit_file.exists():
        for row in json.loads(audit_file.read_text())["results"]:
            qualified = row["qualified_event_heading_errors"]
            raw = row["selected_course_errors"]
            faces[row["sign_id"]] = ("opposite" if qualified and min(qualified) > 90 else
                                      "opposite_unqualified" if raw and min(raw) > 90 else "aligned")
    comparison_by_id = {}
    if args.comparison:
        exclusive = json.loads((args.comparison / "exclusive-inventory-comparison.json").read_text())
        comparison = {"counts": exclusive["counts"]}
        reverse_file = args.comparison / "reverse-map-data.json"
        if reverse_file.exists():
            reverse = json.loads(reverse_file.read_text())
            comparison["reverse"] = {key: reverse[key] for key in ("counts", "categories", "photos", "annotation_count", "photo_count")}
            # Camera coordinates locate photos, not individual signs. Five
            # decimal places suffice for this overview; source precision stays
            # in the private evidence receipt.
            for photo in comparison["reverse"]["photos"]:
                photo[1:3] = coordinates(photo[1:3])
                photo[4] = photo[4][:10]
                photo[5] = None  # viewer links use the photo ID alone
                for annotation in photo[6]:
                    if len(annotation) > 4:
                        annotation[4][2:4] = coordinates(annotation[4][2:4])
        for record in exclusive["records"]:
            pair = record.get("best_pair")
            if not pair:
                continue
            comparison_by_id[record["sign_id"]] = {
                "status": record["status"], "code": pair["observed_code"],
                "photo": pair["photo_id"], "camera": [round(pair["camera_lon"], 5), round(pair["camera_lat"], 5)],
                "heading": pair["camera_heading"], "date": pair["captured_at"],
                "confidence": pair["observed_confidence"],
            }
    for review in reviews:
        for sign in review["signs"]:
            sign["face"] = faces.get(sign["id"])
            if sign["id"] in comparison_by_id:
                sign["comparison"] = comparison_by_id[sign["id"]]
    all_points = [point for review in reviews for segment in review["route"] for point in segment[2]]
    lo = min(p[0] for p in all_points); hi = max(p[0] for p in all_points)
    bottom = min(p[1] for p in all_points); top = max(p[1] for p in all_points)
    connection = sqlite3.connect(args.database.resolve().as_uri() + "?mode=ro", uri=True)
    places = [[name, kind, round(lon, 5), round(lat, 5)] for name, kind, lon, lat in connection.execute(
        "SELECT name,place,lon,lat FROM city_place WHERE lon BETWEEN ? AND ? AND lat BETWEEN ? AND ? AND place IN ('city','town','village')",
        (lo - .008, hi + .008, bottom - .008, top + .008))]
    icons = {}
    for name in {s["icon"] for review in reviews for s in review["signs"] if s["icon"] and s["kind"] != "speed_limit"}:
        file = args.artwork.parent / "originals" / Path(name).with_suffix(".svg")
        if file.is_file():
            icons[name] = "data:image/svg+xml;base64," + base64.b64encode(file.read_bytes()).decode()
    roads = {}
    for review in reviews:
        for road in review.pop("roads"):
            roads.setdefault(json.dumps(road, separators=(",", ":")), road)
    output = {"reviews": reviews, "roads": list(roads.values()), "places": places, "icons": icons, "comparison": comparison,
              "scope": "Reconstructed controller candidates, not evidence of a painted screen or camera confirmation.",
              "bundle": "2026-10-21-v1.5-runtime"}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, separators=(",", ":"), ensure_ascii=False).replace("<", "\\u003c"))
    print(json.dumps({"bytes": args.output.stat().st_size,
                      "platforms": [{"name": r["platform"], "signs": len(r["signs"]), "secondary10m": sum(s["selected"][0] > 0 for s in r["signs"]), "appliedNumeric": r["activeNumeric"]} for r in reviews],
                      "official_svg_assets": len(icons)}))


if __name__ == "__main__":
    main()
