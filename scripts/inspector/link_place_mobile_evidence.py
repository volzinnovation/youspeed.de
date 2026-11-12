"""Propose time-aligned mobile evidence links to existing Panoramax groups."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import math

from scripts.inspector.match_place_sign_inventory import distance_m


MAX_TIME_DELTA_S = 2
MAX_CAMERA_DISTANCE_M = 20
MAX_BEARING_DELTA_DEG = 30
MAX_POSITION_ERROR_M = 50


def captured_seconds(row):
    value = datetime.fromisoformat(row["captured_at"].replace("Z", "+00:00"))
    if value.utcoffset() is None:
        raise ValueError("mobile links require timezone-qualified frame timestamps")
    return value.timestamp()


def in_review_window(row, place, boundary=None):
    if boundary is None:
        geometry = place.get("scope_geometry_wgs84") or place.get("boundary_wgs84")
        if geometry:
            from shapely.geometry import shape

            boundary = shape(geometry)
    if boundary is not None:
        from shapely.geometry import Point

        return boundary.covers(Point(row["longitude"], row["latitude"]))
    ring = place.get("bounds_ring_wgs84")
    if not ring:
        return True
    # The local review window is a convex quadrilateral, with a closed ring.
    longitude, latitude = row["longitude"], row["latitude"]
    sides = [(b[0] - a[0]) * (latitude - a[1]) - (b[1] - a[1]) * (longitude - a[0])
             for a, b in zip(ring, ring[1:])]
    return all(value >= 0 for value in sides) or all(value <= 0 for value in sides)


def attach_mobile_evidence(document, rows, bindings=None):
    """Keep associations provisional, retaining every existing group and pose."""
    bindings = bindings or {}
    place = document.get("place", {})
    boundary = None
    geometry = place.get("scope_geometry_wgs84") or place.get("boundary_wgs84")
    if geometry:
        from shapely.geometry import shape

        boundary = shape(geometry)
    by_code = defaultdict(list)
    annotations = defaultdict(set)
    for group in document["groups"]:
        group.pop("mobile_observations", None)
        for view in group["observations"] + group.get("follow_on_observations", []):
            by_code[group["sign_code"]].append((group, view, captured_seconds(view)))
            annotations[view["annotation_id"]].add(group["id"])
    seen = set()
    linked_ids = set()
    for row in sorted(rows, key=lambda item: (item["captured_at"], item["observation_id"])):
        if row.get("source") != "mobile":
            raise ValueError("expected a mobile observation")
        identifier = row["observation_id"]
        if identifier in seen:
            continue
        seen.add(identifier)
        values = [row[key] for key in (
            "longitude", "latitude", "horizontal_error_m", "bearing_degrees", "bearing_error_deg"
        )]
        if not all(type(value) in (int, float) and math.isfinite(value) for value in values):
            continue
        if not (0 < row["horizontal_error_m"] <= MAX_POSITION_ERROR_M):
            continue
        matches = {}
        different_drive = {}
        timestamp = captured_seconds(row)
        for group, view, seconds in by_code[row["sign_code"]]:
            delta = timestamp - seconds
            distance = distance_m(
                (row["longitude"], row["latitude"]), (view["longitude"], view["latitude"])
            )
            bearing_delta = abs((row["bearing_degrees"] - view["bearing_deg"] + 180) % 360 - 180)
            if distance > MAX_CAMERA_DISTANCE_M or bearing_delta > MAX_BEARING_DELTA_DEG:
                continue
            if abs(delta) <= MAX_TIME_DELTA_S:
                target = matches
                rank = (abs(delta), distance, bearing_delta, view["annotation_id"])
            elif row["captured_at"][:10] != view["captured_at"][:10]:
                target = different_drive
                rank = (distance, bearing_delta, abs(delta), view["annotation_id"])
            else:
                continue
            previous = target.get(group["id"])
            if previous is None or rank < previous[0]:
                target[group["id"]] = (rank, group, view, delta, distance, bearing_delta)
        basis = "same_class_near_camera_similar_bearing_close_frame_time"
        if not matches and len(different_drive) == 1:
            candidate = next(iter(different_drive.values()))
            proposal = candidate[1].get("proposal")
            if proposal and proposal.get("position_radius_m"):
                east = (proposal["longitude"] - row["longitude"]) * math.cos(math.radians(row["latitude"]))
                north = proposal["latitude"] - row["latitude"]
                direction = math.degrees(math.atan2(east, north))
                error = abs((row["bearing_degrees"] - direction + 180) % 360 - 180)
                distance = distance_m(
                    (row["longitude"], row["latitude"]), (proposal["longitude"], proposal["latitude"])
                )
                if 4 <= distance <= 100 and error <= min(12, row["bearing_error_deg"]):
                    matches = different_drive
                    basis = "same_class_other_drive_compatible_pose"
        for _, group, view, delta, distance, bearing_delta in matches.values():
            kind = "sighting" if row.get("evidence_kind") == "sighting" else "crop"
            binding = bindings.get(identifier, {})
            observation = {
                "evidence_id": identifier,
                "source_id": "mobile",
                "mobile_kind": kind,
                "sequence_id": row["sequence_id"],
                "image_id": row.get("image_id"),
                "fix_id": row.get("fix_id"),
                "fix_at": row.get("fix_at"),
                "captured_at": row["captured_at"],
                "in_review_window": in_review_window(row, place, boundary),
                "longitude": row["longitude"],
                "latitude": row["latitude"],
                "bearing_deg": row["bearing_degrees"],
                "bearing_error_deg": row["bearing_error_deg"],
                "horizontal_error_m": row["horizontal_error_m"],
                "phone_road_match": row.get("phone_road_match"),
                "association": {
                    "status": "proposed",
                    "basis": basis,
                    "matched_annotation_id": view["annotation_id"],
                    "matched_image_id": view["image_id"],
                    "matched_captured_at": view["captured_at"],
                    "time_delta_s": delta,
                    "camera_distance_m": distance,
                    "bearing_delta_deg": bearing_delta,
                    "candidate_group_ids": sorted(matches),
                    "shared_panoramax_group_ids": sorted(annotations[view["annotation_id"]]),
                    "independence_status": "same_capture_or_drive_possible"
                    if abs(delta) <= MAX_TIME_DELTA_S else "different_capture_day",
                },
                **{key: binding[key] for key in (
                    "source_binding", "camera_heading_deg", "first_seen_at", "last_seen_at"
                ) if key in binding},
            }
            group.setdefault("mobile_observations", []).append(observation)
            linked_ids.add(identifier)
    document["mobile_reference"] = {
        "status": "proposed_links",
        "max_time_delta_s": MAX_TIME_DELTA_S,
        "max_camera_distance_m": MAX_CAMERA_DISTANCE_M,
        "max_bearing_delta_deg": MAX_BEARING_DELTA_DEG,
        "max_position_error_m": MAX_POSITION_ERROR_M,
        "unique_mobile_observations": len(linked_ids),
        "groups_with_candidates": sum(bool(g.get("mobile_observations")) for g in document["groups"]),
    }
    return document


def attach_collection_context(document, collection):
    """Show other records of an exactly linked sighting as gallery context."""
    bindings = collection["bindings"]
    siblings = defaultdict(list)

    def parent(binding):
        return binding["installation"], binding["epoch"], binding["event_id"]

    for record in collection["collection"]:
        identifier = record["evidence_id"]
        if identifier in bindings:
            siblings[parent(bindings[identifier]["source_binding"])].append(record)
    for group in document["groups"]:
        observations = group.get("mobile_observations", [])
        present = {row["evidence_id"] for row in observations}
        for anchor in tuple(observations):
            for record in siblings[parent(anchor["source_binding"])]:
                identifier = record["evidence_id"]
                if identifier in present:
                    continue
                manifest, event = record["crop"], record["sighting"]
                timestamp = manifest.get("source_frame_at") if manifest else event.get("representative_frame_at")
                if not timestamp:
                    continue
                link = anchor["association"]
                observations.append({
                    "evidence_id": identifier, "source_id": "mobile",
                    "mobile_kind": record["kind"], "captured_at": timestamp,
                    "gallery_only": True,
                    "source_binding": bindings[identifier]["source_binding"],
                    "association": {
                        **link, "basis": "same_parent_sighting",
                        "independence_status": "same_parent_sighting",
                    },
                })
                present.add(identifier)
        observations.sort(key=lambda row: (captured_seconds(row), row["evidence_id"]))
    document["mobile_reference"]["collection_counts"] = collection["counts"]
    return document
