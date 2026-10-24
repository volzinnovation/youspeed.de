#!/usr/bin/env python3
"""Compare cached origin Panoramax annotations with route-local bundle signs.

Metadata-only evidence: photo GPS is a camera position, not a sign position.
Code compatibility is not a verified physical-object identity or ground truth.
"""
import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import re

from profile_bw_sign_route import angle, distance, load_track, project_to_segment, route_segments


class RouteIndex:
    def __init__(self, fixes):
        self.scale = math.pi / 180 * 6371008.8
        self.cosine = math.cos(math.radians(sum(p["lat"] for p in fixes) / len(fixes)))
        self.grid = defaultdict(list)
        self.segments = []
        chainage = 0
        for a, b in route_segments(fixes)[0]:
            length = distance(a["lat"], a["lon"], b["lat"], b["lon"])
            if length < 2:
                chainage += length
                continue
            index = len(self.segments)
            self.segments.append((a, b, chainage, length))
            x1, y1 = self.xy(a["lat"], a["lon"])
            x2, y2 = self.xy(b["lat"], b["lon"])
            for x in range(math.floor((min(x1, x2) - 100) / 100), math.floor((max(x1, x2) + 100) / 100) + 1):
                for y in range(math.floor((min(y1, y2) - 100) / 100), math.floor((max(y1, y2) + 100) / 100) + 1):
                    self.grid[x, y].append(index)
            chainage += length

    def xy(self, lat, lon):
        return lon * self.scale * self.cosine, lat * self.scale

    def project(self, lat, lon):
        x, y = self.xy(lat, lon)
        best = None
        for index in self.grid.get((math.floor(x / 100), math.floor(y / 100)), []):
            a, b, chainage, length = self.segments[index]
            d, fraction, heading = project_to_segment(lat, lon, a, b)
            if best is None or (d, index) < (best["distance_m"], best["segment"]):
                best = dict(distance_m=d, chainage_m=chainage + fraction * length, heading=heading, segment=index,
                            route_at=a["timestamp"] + fraction * (b["timestamp"] - a["timestamp"]))
        return best


def bearing(lat, lon, other_lat, other_lon):
    y = math.sin(math.radians(other_lon - lon)) * math.cos(math.radians(other_lat))
    x = math.cos(math.radians(lat)) * math.sin(math.radians(other_lat)) - math.sin(math.radians(lat)) * math.cos(math.radians(other_lat)) * math.cos(math.radians(other_lon - lon))
    return math.degrees(math.atan2(y, x)) % 360


def canonical(code):
    if not isinstance(code, str):
        return None
    code = code.strip()
    return code if re.fullmatch(r"DE:\d+(?:\.\d+)?(?:-\d+)?", code) else None


def family(code):
    match = re.match(r"(DE:\d+(?:\.\d+)?)", code or "")
    return match.group(1) if match else None


def annotation_rows(photo):
    properties = photo.get("properties", {})
    for annotation in properties.get("annotations", []):
        tags = annotation.get("semantics", [])
        codes = sorted({tag.get("value") for tag in tags if tag.get("key") == "osm|traffic_sign" and isinstance(tag.get("value"), str)})
        if not codes:
            continue
        for code in codes:
            qualified = f"[osm|traffic_sign={code}]"
            attributes = {tag["key"].split("[", 1)[0]: tag.get("value") for tag in tags if tag.get("key", "").endswith(qualified)}
            confidence = attributes.get("classification_confidence")
            try:
                confidence = float(confidence) if confidence is not None else None
            except (ValueError, TypeError):
                confidence = None
            yield dict(photo_id=photo["id"], collection_id=photo.get("collection"), annotation_id=annotation.get("id"),
                       observed_code=code, canonical_code=canonical(code), classification_confidence=confidence,
                       classification_model=attributes.get("classification_model"), classification_revision=attributes.get("classification_code_revision"),
                       shape=annotation.get("shape"), captured_at=properties.get("datetime"), updated_at=properties.get("updated"),
                       camera_heading=properties.get("view:azimuth"), camera_lon=photo["geometry"]["coordinates"][0],
                       camera_lat=photo["geometry"]["coordinates"][1],
                       item_url=next((link["href"] for link in photo.get("links", []) if link.get("rel") == "self"), None),
                       image_url=photo.get("assets", {}).get("sd", {}).get("href"),
                       license=properties.get("license"), producer=properties.get("geovisio:producer"))


def compare(photos, coverage, fixes, selection, *, camera_corridor_m=25, heading_tolerance=35, max_camera_sign_m=30):
    index = RouteIndex(fixes)
    signs = coverage["signs"]
    for sign in signs:
        sign["route_projection"] = index.project(sign["lat"], sign["lon"])
    photo_status = Counter()
    observations, pairs, retained_photos = [], [], []
    for photo in photos:
        lon, lat = photo["geometry"]["coordinates"][:2]
        projected = index.project(lat, lon)
        azimuth = photo.get("properties", {}).get("view:azimuth")
        if projected is None or projected["distance_m"] > camera_corridor_m:
            photo_status["outside_camera_route_corridor"] += 1
            continue
        if not isinstance(azimuth, (int, float)) or not math.isfinite(azimuth):
            photo_status["heading_unknown"] += 1
            continue
        heading_error = angle(azimuth, projected["heading"])
        if heading_error > heading_tolerance:
            photo_status["different_travel_direction"] += 1
            continue
        photo_status["aligned_route_camera"] += 1
        retained_photos.append(dict(photo_id=photo["id"], camera_lat=lat, camera_lon=lon,
                                    camera_heading=azimuth, route=projected, heading_error_deg=heading_error))
        candidates = []
        for sign in signs:
            sign_projection = sign["route_projection"]
            if sign_projection is None or sign_projection["distance_m"] > 30:
                continue
            along = sign_projection["chainage_m"] - projected["chainage_m"]
            if not -5 <= along <= max_camera_sign_m + 10:
                continue
            d = distance(lat, lon, sign["lat"], sign["lon"])
            if not .5 <= d <= max_camera_sign_m:
                continue
            fov_error = angle(azimuth, bearing(lat, lon, sign["lat"], sign["lon"]))
            fov = photo.get("properties", {}).get("pers:interior_orientation", {}).get("field_of_view")
            half_fov = min(55, max(25, fov / 2 + 10)) if isinstance(fov, (int, float)) else 45
            if fov_error > half_fov:
                continue
            sign_heading = sign.get("associated_travel_heading")
            verified_direction = sign["association_status"] == "accepted" and sign_heading is not None
            target_heading_error = angle(azimuth, sign_heading) if verified_direction else None
            if verified_direction and target_heading_error > 55:
                continue
            candidates.append(dict(sign_id=sign["sign_id"], code=sign["sign_code"], canonical_code=canonical(sign["normalized_code"]),
                                   kind=sign["kind"], numeric_value=sign["numeric_value"], distance_camera_to_sign_m=d,
                                   along_route_offset_m=along, field_of_view_error_deg=fov_error,
                                   source_direction_verified=verified_direction, source_heading_error_deg=target_heading_error,
                                   association_status=sign["association_status"], source_lat=sign["lat"], source_lon=sign["lon"]))
        for observation in annotation_rows(photo):
            observation.update(route_heading_error_deg=heading_error, camera_route_distance_m=projected["distance_m"],
                               camera_route_chainage_m=projected["chainage_m"], candidate_count=len(candidates))
            code = observation["canonical_code"]
            low_confidence = observation["classification_confidence"] is not None and observation["classification_confidence"] < .8
            exact = [c for c in candidates if code is not None and c["canonical_code"] == code]
            same_family = [c for c in candidates if family(code) is not None and family(c["canonical_code"]) == family(code)]
            selected_candidates = []
            if code is None:
                status = "unknown_or_unparameterized_annotation"
            elif low_confidence:
                status = "low_confidence_annotation"
            elif len(candidates) == 1 and exact and exact[0]["source_direction_verified"]:
                status = "unique_exact_code_value_compatible"
                selected_candidates = exact
            elif exact:
                status = "exact_code_compatible_candidate"
                selected_candidates = exact
            elif same_family:
                values = [c for c in same_family if c["kind"] == "speed_limit" and code.startswith("DE:274-")
                          and c["canonical_code"] and c["canonical_code"].startswith("DE:274-")]
                if values:
                    status = ("unique_numeric_value_conflict_candidate" if len(candidates) == 1 and values[0]["source_direction_verified"]
                              else "numeric_value_conflict_unresolved_identity")
                elif family(code) in ("DE:274", "DE:274.1", "DE:278"):
                    status = "same_family_missing_numeric_value"
                else:
                    status = "family_class_consistent_variant_unresolved"
                selected_candidates = same_family
            elif len(candidates) == 1 and candidates[0]["source_direction_verified"]:
                status = "unique_different_class_candidate_unresolved_identity"
                selected_candidates = candidates
            elif candidates:
                status = "multiple_candidates_no_exact_code"
            else:
                status = "no_inventory_candidate_in_camera_cone"
            observation["status"] = status
            observation["candidate_sign_ids"] = [c["sign_id"] for c in candidates]
            observations.append(observation)
            for candidate in selected_candidates:
                pairs.append(dict(status=status, photo_id=observation["photo_id"], collection_id=observation["collection_id"],
                                  annotation_id=observation["annotation_id"], observed_code=observation["observed_code"],
                                  observed_model=observation["classification_model"], observed_confidence=observation["classification_confidence"],
                                  captured_at=observation["captured_at"], updated_at=observation["updated_at"], item_url=observation["item_url"],
                                  image_url=observation["image_url"], camera_lat=lat, camera_lon=lon, camera_heading=azimuth,
                                  route_heading_error_deg=heading_error, camera_route_distance_m=projected["distance_m"],
                                  candidate_count=len(candidates), **candidate))
    statuses = Counter(o["status"] for o in observations)
    exact_statuses = {"unique_exact_code_value_compatible", "exact_code_compatible_candidate"}
    exact_ids = {p["sign_id"] for p in pairs if p["status"] in exact_statuses}
    unique_exact_ids = {p["sign_id"] for p in pairs if p["status"] == "unique_exact_code_value_compatible"}
    family_ids = {p["sign_id"] for p in pairs if p["status"] == "family_class_consistent_variant_unresolved"}
    conflict_ids = {p["sign_id"] for p in pairs if p["status"] == "unique_numeric_value_conflict_candidate"}
    unresolved_numeric_ids = {p["sign_id"] for p in pairs if p["status"] == "numeric_value_conflict_unresolved_identity"}
    unresolved_class_ids = {p["sign_id"] for p in pairs if p["status"] == "unique_different_class_candidate_unresolved_identity"}
    selected_ids = set(selection.get("selected_sign_ids", []))
    per_sign = []
    for sign in signs:
        related = [p for p in pairs if p["sign_id"] == sign["sign_id"]]
        if related:
            priority = {"unique_exact_code_value_compatible": 0, "exact_code_compatible_candidate": 1,
                        "family_class_consistent_variant_unresolved": 2, "unique_numeric_value_conflict_candidate": 3,
                        "numeric_value_conflict_unresolved_identity": 4}
            best = min(related, key=lambda p: (priority.get(p["status"], 5), p["distance_camera_to_sign_m"]))
            conflicts = [p for p in related if p["status"] in ("unique_numeric_value_conflict_candidate", "numeric_value_conflict_unresolved_identity")]
            per_sign.append(dict(sign_id=sign["sign_id"], code=sign["sign_code"], kind=sign["kind"], source_id=sign["source_id"],
                                 statuses=dict(Counter(p["status"] for p in related)),
                                 distinct_photo_ids=sorted({p["photo_id"] for p in related}), best_evidence=best,
                                 numeric_conflict_evidence=conflicts,
                                 inferred_secondary_slot_selected=sign["sign_id"] in selected_ids,
                                 painted_ui="unrecorded"))
    return dict(format="youspeed.panoramax.route-comparison.v1", snapshot_at=datetime.now(timezone.utc).isoformat(),
                source="https://panoramax.woladen.de/api", thresholds=dict(camera_route_corridor_m=camera_corridor_m,
                camera_route_heading_tolerance_deg=heading_tolerance, max_camera_to_inventory_sign_m=max_camera_sign_m,
                source_direction_tolerance_deg=55, minimum_reported_classification_confidence=.8),
                limitations=["Camera GPS is not a sign coordinate; all associations are metadata candidates",
                             "Exact-code counts require matching numeric values; incomplete variants/value families are separate",
                             "No confirmed physical sign mismatches from metadata alone; unique numeric conflicts are review candidates",
                             "Repeated photos/annotations are counted separately from distinct source sign IDs",
                             "Missing annotations and unsupported/low-confidence classes do not prove missing signs",
                             "Search snapshot covers queried origin bbox and returned records, not a complete database census",
                             "Old drive has no painted-UI telemetry; selected secondary IDs are inferred from logged lookups"],
                summary=dict(input_photos=len(photos), photo_direction_filters=dict(photo_status),
                directional_annotation_observations=len(observations), annotation_statuses=dict(statuses),
                distinct_inventory_ids_exact_code_compatible=len(exact_ids),
                distinct_inventory_ids_unique_direction_verified_exact=len(unique_exact_ids),
                distinct_inventory_ids_family_only=len(family_ids - exact_ids),
                distinct_inventory_ids_numeric_conflict_candidates=len(conflict_ids),
                distinct_inventory_ids_numeric_conflict_unresolved_identity=len(unresolved_numeric_ids),
                numeric_conflict_only_ids=len(conflict_ids - exact_ids),
                distinct_inventory_ids_different_class_unresolved_identity=len(unresolved_class_ids),
                confirmed_physical_mismatches=None,
                sampled_inventory_ids_without_exact_compatible_annotation=sum(s["within_sampled_fix_geofence"] and s["sign_id"] not in exact_ids for s in signs),
                sampled_inventory_ids_with_exact_compatible_annotation=sum(s["within_sampled_fix_geofence"] and s["sign_id"] in exact_ids for s in signs),
                inferred_secondary_slot_ids=len(selected_ids), inferred_selected_with_exact_compatible_annotation=len(selected_ids & exact_ids),
                inferred_selected_with_exact_or_family_consistent_annotation=len(selected_ids & (exact_ids | family_ids)),
                actual_painted_ui_count=None),
                photos=retained_photos, observations=observations, match_pairs=pairs, inventory_sign_evidence=per_sign)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--photos", type=Path, required=True)
    parser.add_argument("--coverage", type=Path, required=True)
    parser.add_argument("--track", type=Path, required=True)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--max-camera-sign-m", type=float, default=30)
    args = parser.parse_args()
    photos = json.loads(args.photos.read_text())["features"]
    coverage = json.loads(args.coverage.read_text())
    fixes, _ = load_track(args.track)
    selection = json.loads(args.selection.read_text())
    report = compare(photos, coverage, fixes, selection, max_camera_sign_m=args.max_camera_sign_m)
    report["inputs"] = {key: dict(path=str(path.resolve()), sha256=hashlib.sha256(path.read_bytes()).hexdigest())
                        for key, path in [("photos", args.photos), ("coverage", args.coverage), ("track", args.track), ("selection", args.selection)]}
    args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    print(json.dumps(report["summary"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
