"""Build conditional identity descriptors from a complete camera-scenario report.

No raw model label is promoted to a canonical sign class. Region diameter covers
the union of every feasible polygon in the common local EN frame, not just fitted
point spread. Nominal road agreement describes enumerated map hypotheses only.
Live eligibility, consent and immutable source verification remain caller-owned.
"""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import math
import re

from scripts.tsr.collection.sign_identity_proposals import propose_identities
from scripts.tsr.collection.sign_road_association import EARTH_M


VERSION = "localized-sign-identity-descriptors-v1"
MAX_REGION_VERTICES = 512


def _digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"),
                                    allow_nan=False).encode()).hexdigest()


def _finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _point(value):
    return isinstance(value, list) and len(value) == 2 and all(_finite(v) for v in value)


def _sha(value):
    return isinstance(value, str) and re.fullmatch(r"[0-9a-f]{64}", value) is not None


def _way(value):
    return (isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,18}", value) is not None
            and int(value) <= 9223372036854775807)


def canonical_classification(classification):
    """Return only an explicitly recorded country/canonical-code/value tuple."""
    if not isinstance(classification, dict):
        return None
    country, code = classification.get("country"), classification.get("canonical_code")
    if (not isinstance(country, str) or re.fullmatch(r"[A-Z]{2}", country) is None
            or not isinstance(code, str) or not 1 <= len(code) <= 160 or code != code.strip()
            or "value" not in classification):
        return None
    value = classification["value"]
    if value is not None and not _finite(value):
        return None
    return {"country": country, "code": code, "value": value}


def _cross(a, b, c):
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def _polygon(vertices):
    if (not isinstance(vertices, list) or not 3 <= len(vertices) <= MAX_REGION_VERTICES
            or not all(_point(p) and all(abs(v) <= 200000 for v in p) for p in vertices)):
        return False
    turns = [_cross(a, b, c) for a, b, c in zip(vertices, vertices[1:] + vertices[:1], vertices[2:] + vertices[:2])]
    if any(t > 1e-8 for t in turns) and any(t < -1e-8 for t in turns):
        return False
    # Local turns alone can admit self-intersecting star polygons. Every vertex
    # must lie on the same side of every oriented convex boundary edge.
    sides = [_cross(a, b, p) for a, b in zip(vertices, vertices[1:] + vertices[:1]) for p in vertices]
    if any(t > 1e-8 for t in sides) and any(t < -1e-8 for t in sides):
        return False
    area_twice = sum(a[0] * b[1] - b[0] * a[1] for a, b in zip(vertices, vertices[1:] + vertices[:1]))
    return abs(area_twice) > 1e-8


def _diameter(vertices):
    """Farthest union-vertex pair; convex-hull reduction preserves its diameter."""
    points = sorted({tuple(p) for p in vertices})
    if len(points) < 2:
        return 0.0
    lower, upper = [], []
    for chain, ordered in ((lower, points), (upper, reversed(points))):
        for p in ordered:
            while len(chain) >= 2 and _cross(chain[-2], chain[-1], p) <= 0:
                chain.pop()
            chain.append(p)
    hull = lower[:-1] + upper[:-1]
    return max(math.dist(a, b) for i, a in enumerate(hull) for b in hull[i + 1:])


def _nearest(association, frame):
    if not isinstance(association, dict) or association.get("local_frame") != frame:
        return None, None, "road_association_frame_missing_or_mismatched"
    source = association.get("map_source")
    if not isinstance(source, dict) or not _sha(source.get("sha256")):
        return None, None, "map_source_hash_missing_or_invalid"
    source_sha = source["sha256"]
    roads = association.get("roads")
    if not isinstance(roads, list):
        return None, source_sha, "road_candidates_missing"
    if (association.get("omitted_road_records", 0) != 0
            and association.get("summary_scope") != "nearest_five_nominal_projections_full_supplied_graph_results_in_group_evidence"):
        return None, source_sha, "truncated_road_summary_does_not_preserve_nearest_order"
    candidates, identities = [], set()
    for road in roads:
        if not isinstance(road, dict) or not _way(road.get("way_id")) or road["way_id"] in identities:
            return None, source_sha, "road_candidate_identity_invalid_or_duplicated"
        identities.add(road["way_id"])
        projection = road.get("nominal_projection")
        distance = projection.get("distance_m") if isinstance(projection, dict) else None
        if not _finite(distance) or distance < 0:
            return None, source_sha, "road_candidate_distance_missing_or_invalid"
        candidates.append((distance, road["way_id"]))
    if not candidates:
        return None, source_sha, "no_enumerated_road_candidate"
    candidates.sort()
    if len(candidates) > 1 and abs(candidates[1][0] - candidates[0][0]) <= 1e-7:
        return None, source_sha, "nearest_enumerated_road_tied"
    return candidates[0][1], source_sha, None


def _scenario_key(camera):
    if not isinstance(camera, dict) or set(camera) != {"horizontal_fov_degrees", "mount_yaw_degrees"}:
        return None
    fov, yaw = camera["horizontal_fov_degrees"], camera["mount_yaw_degrees"]
    return (float(fov), float(yaw)) if _finite(fov) and _finite(yaw) else None


def _descriptor(group, expected, nominal_key):
    gid = group.get("group_id")
    if not isinstance(gid, str) or not 1 <= len(gid) <= 512 or gid != gid.strip():
        raise ValueError("invalid_localized_group_identity")
    descriptor = {"group_id": gid, "classification_key": canonical_classification(group.get("classification")),
                  "candidate_lat_lon": None, "uncertainty_diameter_m": None,
                  "all_camera_scenarios_estimated": False, "all_regions_bounded": False,
                  "nominal_way_id": None, "way_proposal_stable_across_scenarios": False,
                  "source_frame_ids": group.get("source_frame_ids", [])}
    reasons = []
    if descriptor["classification_key"] is None:
        reasons.append("explicit_canonical_classification_unavailable")
    scenarios = group.get("scenarios")
    actual = [_scenario_key(s.get("camera")) if isinstance(s, dict) else None
              for s in scenarios] if isinstance(scenarios, list) else []
    if len(actual) != len(expected) or None in actual or set(actual) != expected or len(set(actual)) != len(actual):
        return descriptor, {"group_id": gid, "reasons": reasons + ["camera_scenario_population_incomplete_or_duplicated"],
                            "map_sha256": None}
    frame = group.get("local_frame")
    if (not isinstance(frame, dict) or frame.get("axes") != "east_north" or frame.get("units") != "metres"
            or not isinstance(frame.get("frame_id"), str) or not 1 <= len(frame["frame_id"]) <= 512
            or not isinstance(frame.get("provenance"), dict) or not _sha(frame["provenance"].get("sha256"))):
        return descriptor, {"group_id": gid, "reasons": reasons + ["common_local_frame_missing_or_invalid"],
                            "map_sha256": None}
    positions_ok, regions_ok, roads_ok = True, True, True
    vertices, maps, ways, nominal = [], set(), set(), None
    for key, scenario in sorted(zip(actual, scenarios), key=lambda row: row[0]):
        position = scenario.get("position")
        if not isinstance(position, dict) or position.get("status") != "estimated":
            positions_ok = regions_ok = roads_ok = False
            reasons.append("camera_scenario_not_estimated")
            continue
        if (position.get("local_frame") != frame or not _point(position.get("estimate_en_m"))
                or any(abs(v) > 200000 for v in position["estimate_en_m"])):
            positions_ok = regions_ok = roads_ok = False
            reasons.append("scenario_estimate_frame_or_point_invalid")
            continue
        if key == nominal_key:
            nominal = position["estimate_en_m"]
        region = position.get("feasible_region")
        if (not isinstance(region, dict) or region.get("bounds_known") is not True
                or region.get("range_clipped") is not False or not _polygon(region.get("vertices_en_m"))):
            regions_ok = False
            reasons.append("camera_scenario_region_unbounded_or_invalid")
        else:
            vertices.extend(region["vertices_en_m"])
        way, source_sha, problem = _nearest(scenario.get("road_association"), frame)
        if source_sha:
            maps.add(source_sha)
        if way:
            ways.add(way)
        if key == nominal_key:
            descriptor["nominal_way_id"] = way
        if problem:
            roads_ok = False
            reasons.append(problem)
    descriptor["all_camera_scenarios_estimated"] = positions_ok
    descriptor["all_regions_bounded"] = regions_ok and positions_ok
    if descriptor["all_regions_bounded"]:
        descriptor["uncertainty_diameter_m"] = _diameter(vertices)
    origin = group.get("origin_lat_lon")
    if nominal is not None and _point(origin) and -70 <= origin[0] <= 70 and -180 <= origin[1] <= 180:
        projected = [origin[0] + math.degrees(nominal[1] / EARTH_M),
                     origin[1] + math.degrees(nominal[0] / (EARTH_M * math.cos(math.radians(origin[0]))))]
        recorded = group.get("nominal_position_lat_lon")
        if (_point(recorded) and all(abs(a - b) <= 1e-9 for a, b in zip(projected, recorded))
                and -90 <= projected[0] <= 90 and -180 <= projected[1] <= 180):
            descriptor["candidate_lat_lon"] = projected
        else:
            reasons.append("nominal_position_missing_or_projection_mismatched")
    else:
        reasons.append("nominal_point_or_projection_origin_unavailable")
    if len(maps) != 1:
        roads_ok = False
        reasons.append("camera_scenario_map_sources_missing_or_mismatched")
    if len(ways) != 1:
        roads_ok = False
        reasons.append("nearest_enumerated_road_changes_across_scenarios")
    descriptor["way_proposal_stable_across_scenarios"] = roads_ok and positions_ok
    return descriptor, {"group_id": gid, "reasons": sorted(set(reasons)),
                        "map_sha256": next(iter(maps)) if len(maps) == 1 else None,
                        "scenario_count": len(actual), "union_vertex_count": len(vertices)}


def build_identity_report(localization_report: dict, policy: dict) -> dict:
    """Qualify all expected scenarios, then call the frozen identity-proposal core."""
    if (not isinstance(policy, dict) or policy.get("source_policy") != "live-crops-only-v1"
            or policy.get("acceptance_eligible") is not False or policy.get("training_eligible") is not False):
        raise ValueError("conditional_live_only_policy_required")
    camera = policy.get("camera_assumptions", {})
    try:
        expected_keys = [(float(fov), float(yaw)) for fov in camera["horizontal_fov_scenarios_degrees"]
                         for yaw in camera["mount_yaw_scenarios_degrees"] if _finite(fov) and _finite(yaw)]
        nominal_key = _scenario_key(camera["nominal_scenario"])
    except (KeyError, TypeError) as exc:
        raise ValueError("invalid_frozen_camera_scenario_policy") from exc
    expected = set(expected_keys)
    if len(expected_keys) != 12 or len(expected) != 12 or nominal_key not in expected:
        raise ValueError("exact_twelve_unique_declared_scenarios_required")
    if (not isinstance(localization_report, dict) or localization_report.get("schema_version") != 1
            or localization_report.get("protocol_sha256") != _digest(policy)):
        raise ValueError("localization_report_protocol_mismatch")
    groups = localization_report.get("groups")
    if not isinstance(groups, list) or len(groups) > 4096 or not all(isinstance(g, dict) for g in groups):
        raise ValueError("invalid_or_unbounded_localization_groups")
    rows = [_descriptor(g, expected, nominal_key) for g in groups]
    rows.sort(key=lambda row: row[0]["group_id"])
    if len({d["group_id"] for d, _ in rows}) != len(rows):
        raise ValueError("duplicate_localized_group_identity")
    maps = {diagnostic["map_sha256"] for _, diagnostic in rows if diagnostic["map_sha256"]}
    declared_map = localization_report.get("map_source_sha256")
    if declared_map is not None and not _sha(declared_map):
        raise ValueError("invalid_report_map_source_sha256")
    if len(maps) > 1:
        for descriptor, diagnostic in rows:
            descriptor["way_proposal_stable_across_scenarios"] = False
            diagnostic["reasons"] = sorted(set(diagnostic["reasons"] + ["report_contains_multiple_map_sources"]))
    if declared_map is not None and maps and maps != {declared_map}:
        for descriptor, diagnostic in rows:
            descriptor["way_proposal_stable_across_scenarios"] = False
            diagnostic["reasons"] = sorted(set(diagnostic["reasons"] + ["scenario_map_source_disagrees_with_report"]))
    descriptors = [d for d, _ in rows]
    identities = propose_identities(descriptors, policy["physical_identity"])
    return {"schema_version": 1, "algorithm_version": VERSION,
            "protocol_sha256": _digest(policy), "localization_report_canonical_sha256": _digest(localization_report),
            "map_source_sha256": next(iter(maps)) if len(maps) == 1 else None,
            "expected_camera_scenarios": len(expected), "descriptors": descriptors,
            "descriptor_qualification_counts": {
                "all_camera_scenarios_estimated": sum(d["all_camera_scenarios_estimated"] for d in descriptors),
                "all_regions_bounded": sum(d["all_regions_bounded"] for d in descriptors),
                "stable_nearest_way_across_scenarios": sum(d["way_proposal_stable_across_scenarios"] for d in descriptors),
                "all_geometry_and_way_gates": sum(d["all_regions_bounded"] and d["way_proposal_stable_across_scenarios"] for d in descriptors),
                "geometry_and_way_within_region_diameter_limit": sum(d["all_regions_bounded"] and d["way_proposal_stable_across_scenarios"] and d["uncertainty_diameter_m"] <= policy["physical_identity"]["max_region_diameter_m"] for d in descriptors),
                "canonical_classification_available": sum(d["classification_key"] is not None for d in descriptors),
            },
            "descriptor_diagnostics": [d for _, d in rows],
            "adapter_reason_counts": dict(sorted(Counter(r for _, d in rows for r in d["reasons"]).items())),
            "exclusion_reason_counts": dict(sorted(Counter(r for g in identities["excluded_groups"] for r in g["reasons"]).items())),
            "identity_result": identities,
            "reviewed": False, "proves_physical_identity": False, "acceptance_eligible": False,
            "publish_eligible": False, "training_eligible": False,
            "limitations": ["Classification uses recorded canonical code only; model labels and alternatives are not substituted.",
                            "Region diameter covers the union of all declared camera-scenario feasible polygons.",
                            "Stable nearest mapped road is conditional on the enumerated graph, not sign applicability.",
                            "Input source eligibility, lifecycle, provenance and camera assumptions are caller responsibilities."]}
