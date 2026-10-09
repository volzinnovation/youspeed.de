"""Offline forward-camera sensitivity experiment on lifecycle-qualified crops.

This adapter turns recorded course + image boxes into EXPLICIT camera hypotheses,
not calibrated optical bearings. Future GPS fixes may interpolate capture poses.
All source dependencies are retained for later lifecycle-aware persistence.
"""
from __future__ import annotations

from bisect import bisect_left
from collections import Counter, defaultdict
from datetime import datetime
import hashlib
import json
import math

from scripts.tsr.collection.triangulate_sign_position import triangulate
from scripts.tsr.collection.sign_road_association import (
    EARTH_M, associate_roads, closest_segment, local_en, project_graph,
)

VERSION = "live-crop-camera-hypothesis-adapter-v1"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def seconds(value):
    result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if result.tzinfo is None:
        raise ValueError("timezone_required")
    return result.timestamp()


def utc(value):
    from datetime import timezone
    return datetime.fromtimestamp(value, timezone.utc).isoformat(timespec="microseconds").replace("+00:00", "Z")


def key(row):
    return (row["installation"], row["epoch"], row["crop_id"])


def session(row):
    return (row["installation"], row["epoch"], row["observation"]["collection_session_id"])


def own_position(row):
    # A parent sighting's GPS cannot manufacture separate camera origins.
    return row["manifest"].get("vehicle_position")


def source_frame_id(row):
    m = row["manifest"]
    return digest([session(row), m.get("source_upright_sha256") or m.get("local_frame_token")
                   or [m["source_frame_at"], m["source_width"], m["source_height"]]])


def frame_position(en, origin):
    return [origin[0] + math.degrees(en[1] / EARTH_M),
            origin[1] + math.degrees(en[0] / (EARTH_M * math.cos(math.radians(origin[0]))))]


def build_tracks(rows):
    grouped = defaultdict(lambda: defaultdict(list))
    for row in rows:
        p = own_position(row)
        if isinstance(p, dict):
            grouped[session(row)][seconds(p["fix_at"])].append(row)
    tracks = {}
    for sid, fixes in grouped.items():
        entries = []
        for at, sources in sorted(fixes.items()):
            positions = {(own_position(r)["latitude"], own_position(r)["longitude"]) for r in sources}
            if len(positions) != 1:
                entries.append({"at": at, "valid": False, "rows": sorted(sources, key=key)})
                continue  # Preserve conflicting evidence for lifecycle dependencies.
            chosen = min(sources, key=key)
            entries.append({"at": at, "valid": True, "lat_lon": list(next(iter(positions))), "row": chosen, "rows": sorted(sources, key=key),
                            "accuracy": max(own_position(r)["horizontal_accuracy_m"] for r in sources)})
        tracks[sid] = entries
    return tracks


def capture_pose(row, tracks, origin, policy):
    p = own_position(row)
    at = seconds(row["manifest"]["source_frame_at"])
    fix_at = seconds(p["fix_at"])
    all_entries = tracks.get(session(row), [])
    entries = [x for x in all_entries if x.get("valid", True)]
    index = bisect_left([x["at"] for x in entries], at)
    multiplier = policy["reported_accuracy_multiplier"]
    support = [row]
    for entry in all_entries:
        if not entry.get("valid", True) and abs(entry["at"] - at) <= policy["max_interpolation_gap_seconds"]:
            support.extend(entry["rows"])
    if index < len(entries) and abs(entries[index]["at"] - at) < 1e-6:
        a = entries[index]
        en, error, method = local_en(a["lat_lon"], origin), multiplier * a["accuracy"], "exact_recorded_fix_time"
        support.extend(a["rows"])
    elif 0 < index < len(entries) and entries[index]["at"] - entries[index - 1]["at"] <= policy["max_interpolation_gap_seconds"]:
        a, b = entries[index - 1], entries[index]
        duration = b["at"] - a["at"]
        fraction = (at - a["at"]) / duration
        pa, pb = local_en(a["lat_lon"], origin), local_en(b["lat_lon"], origin)
        en = [x + fraction * (y - x) for x, y in zip(pa, pb)]
        error = multiplier * ((1 - fraction) * a["accuracy"] + fraction * b["accuracy"])
        error += policy["maximum_assumed_acceleration_mps2"] * duration * duration / 8
        method = "offline_bracketed_linear_interpolation"
        support.extend(a["rows"] + b["rows"])
    else:
        en = local_en([p["latitude"], p["longitude"]], origin)
        error = multiplier * p["horizontal_accuracy_m"] + policy["unbracketed_max_speed_bound_mps"] * abs(at - fix_at)
        method = "recorded_fix_with_declared_capture_motion_envelope"
    provenance = {"method": method, "assumptions": policy, "captured_at": at, "fix_at": fix_at,
                  "support_keys": [list(key(r)) for r in sorted({key(r): r for r in support}.values(), key=key)],
                  "error_is_declared_sensitivity_bound_not_measured_accuracy": True}
    return en, max(policy["minimum_horizontal_bound_m"], error), provenance, support


def select_rays(group, policy):
    reasons, fixes, frames = Counter(), {}, set()
    for row in sorted(group, key=lambda r: (abs(own_position(r).get("frame_fix_delta_ms", math.inf))
                                          if isinstance(own_position(r), dict) else math.inf,
                                          r["manifest"]["source_frame_at"], key(r))):
        m, p = row["manifest"], own_position(row)
        if not isinstance(p, dict):
            reasons["no_crop_specific_position"] += 1
            continue
        course, accuracy = p.get("course_degrees"), p.get("course_accuracy_degrees")
        if not finite(course) or not 0 <= course < 360 or not finite(accuracy) or not 0 <= accuracy <= policy["course"]["max_reported_accuracy_degrees"]:
            reasons["course_uncertainty_or_missing"] += 1
            continue
        if abs(seconds(m["source_frame_at"]) - seconds(p["fix_at"])) > policy["position_model"]["max_original_frame_fix_delta_seconds"]:
            reasons["frame_fix_alignment"] += 1
            continue
        if m.get("orientation_version") != "upright-1":
            reasons["unsupported_orientation"] += 1
            continue
        fid = digest([session(row), p["fix_at"], p["latitude"], p["longitude"]])
        sfid = source_frame_id(row)
        if fid in fixes or sfid in frames:
            reasons["repeated_position_fix_or_source_frame"] += 1
            continue
        fixes[fid] = row
        frames.add(sfid)
    return sorted(fixes.items()), dict(reasons)


def camera_bearing(row, fov, yaw, policy):
    m, p = row["manifest"], own_position(row)
    box = m["supplied_box"]
    center = box["x"] + box["width"] / 2
    if not 0 <= center <= 1 or not finite(fov) or not 0 < fov < 180:
        raise ValueError("invalid_camera_geometry")
    scale = 2 * math.tan(math.radians(fov) / 2)
    offset = math.degrees(math.atan((center - .5) * scale))
    jitter = policy["camera_assumptions"]["pixel_center_assumed_error_pixels"] / m["source_width"]
    pixel_angle = max(abs(math.degrees(math.atan((center + delta - .5) * scale)) - offset) for delta in [-jitter, jitter])
    bound = max(policy["course"]["minimum_assumed_bound_degrees"], p["course_accuracy_degrees"])
    bound += policy["camera_assumptions"]["mount_residual_bound_degrees"] + pixel_angle
    return (p["course_degrees"] + yaw + offset) % 360, bound


def candidate_graph(graph, origin, margin):
    dlat = math.degrees(margin / EARTH_M)
    dlon = dlat / math.cos(math.radians(origin[0]))
    west, south, east, north = origin[1] - dlon, origin[0] - dlat, origin[1] + dlon, origin[0] + dlat
    roads = []
    far = 0
    for road in graph["roads"]:
        ps = road["points_lat_lon"]
        if max(p[1] for p in ps) < west or min(p[1] for p in ps) > east or max(p[0] for p in ps) < south or min(p[0] for p in ps) > north:
            continue
        try:
            for p in ps:
                local_en(p, origin)
        except ValueError:
            far += 1
            continue
        roads.append(road)
    return {**graph, "roads": roads, "extraction": {**graph.get("extraction", {}),
            "group_filter_bounds_wgs84": [west, south, east, north], "far_geometry_excluded": far}}


def travelled_path(poses, projected_graph):
    # Nominal closest geometry is retained explicitly as a hypothesis. Alternatives
    # and legal-direction uncertainty are not converted into a routing guarantee.
    matches = []
    for row, en, error in poses:
        course = own_position(row)["course_degrees"]
        candidates = []
        for road in projected_graph["roads"]:
            projection = closest_segment(en, road["points_en_m"])
            heading = projection["tangent_degrees"]
            delta = (course - heading + 180) % 360 - 180
            direction = ("unknown" if projection["tangent_ambiguous"] or abs(abs(delta) - 90) <= 1e-7
                         else "forward" if abs(delta) < 90 else "reverse")
            mismatch = min(abs(delta), 180 - abs(delta))
            candidates.append({"way_id": road["way_id"], "direction": direction,
                               "distance_m": projection["distance_m"], "heading_difference_degrees": mismatch})
        candidates.sort(key=lambda r: (r["distance_m"], r["heading_difference_degrees"], r["way_id"]))
        matches.append({"crop_key": list(key(row)), "position_error_bound_m": error,
                        "nearest": candidates[0] if candidates else None,
                        "alternatives_within_nominal_position_envelope": [r for r in candidates if r["distance_m"] <= error]})
    chosen = [m["nearest"] for m in matches if m["nearest"]]
    directions = {}
    for match in chosen:
        wid, direction = match["way_id"], match["direction"]
        directions[wid] = direction if wid not in directions or directions[wid] == direction else "unknown"
    return {"source_sha256": projected_graph["source"]["sha256"],
            "way_ids": sorted(directions), "direction_by_way": directions,
            "basis": "offline_nominal_nearest_segment_hypothesis_not_phone_match", "captures": matches}


def run_group(group, tracks, graph, policy):
    group = sorted(group, key=lambda r: (r["manifest"]["source_frame_at"], key(r)))
    identity_keys = [list(key(r)) for r in group]
    gid = digest([group[0]["installation"], group[0]["epoch"], group[0]["manifest"]["observation_id"]])
    chosen, dropped = select_rays(group, policy)
    output = {"group_id": gid, "identity_member_keys": identity_keys, "dependency_crop_keys": identity_keys[:],
              "selected_rays": len(chosen), "drop_reasons": dropped, "scenarios": [],
              "classification": group[0]["observation"].get("classification"),
              "source_frame_ids": sorted({source_frame_id(r) for r in group})}
    if len(chosen) < 2:
        return output | {"status": "underconstrained", "reason": "fewer_than_two_qualified_distinct_camera_origins"}
    first = own_position(chosen[0][1])
    origin = [first["latitude"], first["longitude"]]
    frame = {"frame_id": gid, "axes": "east_north", "units": "metres",
             "provenance": {"reference": "local-spherical-EN-origin", "sha256": digest({"origin": origin, "earth_m": EARTH_M})}}
    local_graph = project_graph(candidate_graph(graph, origin, policy["road_query_margin_m"]), origin, frame)
    prepared, dependencies, poses = [], {key(r): r for r in group}, []
    for fid, row in chosen:
        en, error, provenance, support = capture_pose(row, tracks, origin, policy["position_model"])
        prepared.append((fid, row, en, error, provenance))
        dependencies.update({key(r): r for r in support})
        poses.append((row, en, error))
    path = travelled_path(poses, local_graph)
    output.update({"origin_lat_lon": origin, "local_frame": frame, "travelled_path": path,
                   "dependency_crop_keys": [list(k) for k in sorted(dependencies)],
                   "camera_pose_methods": dict(Counter(p[4]["method"] for p in prepared)),
                   "capture_heading_hypothesis": {
                       "method": "hold_recorded_fix_course_constant_until_capture",
                       "capture_time_heading_error_bound_verified": False,
                       "turn_between_fix_and_capture_is_not_measured": True,
                       "rays": [{"sighting_id": digest(key(row)),
                                 "signed_frame_fix_delta_seconds": seconds(row["manifest"]["source_frame_at"]) - seconds(own_position(row)["fix_at"])}
                                for _, row, _, _, _ in prepared]}})
    for fov in policy["camera_assumptions"]["horizontal_fov_scenarios_degrees"]:
        for yaw in policy["camera_assumptions"]["mount_yaw_scenarios_degrees"]:
            scenario = {"horizontal_fov_degrees": fov, "mount_yaw_degrees": yaw}
            rays = []
            for fid, row, en, error, provenance in prepared:
                bearing, angle_bound = camera_bearing(row, fov, yaw, policy)
                rays.append({"sighting_id": digest(key(row)), "source_frame_id": source_frame_id(row),
                             "position_fix_id": fid, "source_kind": "qualified_live_crop",
                             "captured_at": utc(seconds(row["manifest"]["source_frame_at"])),
                             "fix_at": utc(seconds(own_position(row)["fix_at"])),
                             "ray_at": utc(seconds(row["manifest"]["source_frame_at"])),
                             "position_en_m": en, "horizontal_error_bound_m": error,
                             "position_error_covers_capture_time": True,
                             "optical_ray_bearing_degrees": bearing, "angular_error_bound_degrees": angle_bound,
                             "bearing_basis": "explicit_camera_hypothesis",
                             "source_provenance": {"reference": "qualified-source-manifest", "sha256": digest(row["manifest"])},
                             "position_provenance": {"reference": "offline-capture-pose", "sha256": digest(provenance)},
                             "bearing_provenance": {"reference": "declared-forward-camera-scenario", "sha256": digest({"scenario": scenario, "policy": policy, "capture_heading_hypothesis": output["capture_heading_hypothesis"]})}})
            solved = triangulate({"schema_version": 1, "local_frame": frame,
                                  "association": {"group_id": gid, "basis": "hypothesis",
                                                  "provenance": {"reference": "source-observation-lineage", "sha256": digest(identity_keys)}},
                                  "rays": rays}, policy["solver"])
            association = associate_roads(solved, local_graph, path, policy["road_search_radius_m"]) if solved["status"] == "estimated" else None
            output["scenarios"].append({"camera": scenario, "position": solved, "road_association": association})
    nominal = next(s for s in output["scenarios"] if s["camera"] == policy["camera_assumptions"]["nominal_scenario"])
    output["status"] = nominal["position"]["status"]
    if nominal["position"]["estimate_en_m"] is not None:
        output["nominal_position_lat_lon"] = frame_position(nominal["position"]["estimate_en_m"], origin)
    return output


def run(rows, graph, policy, source_validator):
    """Source validator must check live provenance/binding and explicitly return True.

    The outer runner also verifies the current lifecycle receipt and file hashes.
    This pure adapter cannot query consent or authenticate a receipt by itself.
    """
    if policy.get("source_policy") != "live-crops-only-v1":
        raise ValueError("live_only_policy_required")
    if len({key(r) for r in rows}) != len(rows):
        raise ValueError("duplicate_crop_identity")
    grouped = defaultdict(list)
    for row in rows:
        if source_validator(row) is not True:
            raise ValueError("source_validator_must_confirm_eligible_binding")
        grouped[(row["installation"], row["epoch"], row["manifest"]["observation_id"])].append(row)
    tracks = build_tracks(rows)
    results = [run_group(grouped[k], tracks, graph, policy) for k in sorted(grouped)]
    return {"schema_version": 1, "algorithm_version": VERSION, "protocol_sha256": digest(policy),
            "source_rows": len(rows), "observation_groups": len(results), "groups": results,
            "nominal_status_counts": dict(Counter(r["status"] for r in results)),
            "camera_scenario_status_counts": dict(Counter(s["position"]["status"] for r in results for s in r["scenarios"])),
            "training_eligible": False, "acceptance_eligible": False}
