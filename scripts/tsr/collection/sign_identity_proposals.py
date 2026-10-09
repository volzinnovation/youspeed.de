"""Conditional offline physical-sign identity proposals, never reviewed identity.

The caller supplies one descriptor per source-observation after every declared
camera scenario has run. Region diameter must bound the UNION of feasible regions
across scenarios, not just the spread of fitted points. Source-frame IDs must be
globally scoped identities: a shared frame can contain two distinct visible signs.
This module cannot authenticate those declarations or establish live eligibility;
the lifecycle-aware live-crop adapter owns that qualification.

Deterministic complete-link agglomeration checks every cross-member pair. It
cannot merge A/B/C merely because A/B and B/C are close when A/C is incompatible.
Neither matching classification nor proximity proves a common physical sign.
"""

from __future__ import annotations

import hashlib
import heapq
import json
import math
import re


ALGORITHM = "conditional-sign-identity-complete-link-v1"
DEFAULT_SETTINGS = {
    "clustering": "complete_link_conditional_proposals_only",
    "max_pair_distance_m": 20,
    "max_region_diameter_m": 30,
    "requires_compatible_classification": True,
    "requires_consistent_road_hypothesis": True,
}
MAX_DESCRIPTORS = 4096
MAX_ELIGIBLE_DESCRIPTORS = 512
EARTH_RADIUS_M = 6371008.8
FIELDS = {
    "group_id", "classification_key", "candidate_lat_lon", "uncertainty_diameter_m",
    "all_camera_scenarios_estimated", "all_regions_bounded", "nominal_way_id",
    "way_proposal_stable_across_scenarios", "source_frame_ids",
}


def _hash(value):
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                         allow_nan=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _finite(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except OverflowError:
        return False


def _text(value):
    return isinstance(value, str) and 1 <= len(value) <= 512 and value == value.strip()


def _way_id(value):
    return (isinstance(value, str) and re.fullmatch(r"[1-9][0-9]{0,18}", value) is not None
            and int(value) <= 9223372036854775807)


def _settings(settings):
    if settings is None:
        return dict(DEFAULT_SETTINGS)
    if not isinstance(settings, dict) or set(settings) != set(DEFAULT_SETTINGS):
        raise ValueError("exact_identity_settings_required")
    result = dict(settings)
    if result["clustering"] != DEFAULT_SETTINGS["clustering"]:
        raise ValueError("unsupported_clustering")
    for field in ("requires_compatible_classification", "requires_consistent_road_hypothesis"):
        if result[field] is not True:
            raise ValueError("classification_and_road_checks_cannot_be_disabled")
    for field in ("max_pair_distance_m", "max_region_diameter_m"):
        if not _finite(result[field]) or not 0 < result[field] <= 1000:
            raise ValueError("invalid_identity_distance_limit")
    return result


def _descriptor(row, settings):
    if not isinstance(row, dict) or not _text(row.get("group_id")):
        raise ValueError("every_descriptor_requires_unique_bounded_group_id")
    identity = row["group_id"]
    if set(row) != FIELDS:
        return None, {"group_id": identity, "reasons": ["descriptor_fields_missing_or_unknown"]}
    reasons = []
    normalized = dict(row)
    classification = row["classification_key"]
    if classification is None:
        reasons.append("classification_unavailable")
    elif (not isinstance(classification, dict) or set(classification) != {"country", "code", "value"}
          or not isinstance(classification["country"], str)
          or re.fullmatch(r"[A-Z]{2}", classification["country"]) is None
          or not _text(classification["code"])
          or (classification["value"] is not None and not _finite(classification["value"]))):
        reasons.append("classification_invalid")
    else:
        value = classification["value"]
        normalized["classification_key"] = {**classification,
                                             "value": None if value is None else 0.0 if value == 0 else float(value)}
    position = row["candidate_lat_lon"]
    if position is None:
        reasons.append("candidate_position_unavailable")
    elif (not isinstance(position, list) or len(position) != 2 or not all(_finite(v) for v in position)
          or not -90 <= position[0] <= 90 or not -180 <= position[1] <= 180):
        reasons.append("candidate_position_invalid")
    else:
        normalized["candidate_lat_lon"] = [float(v) if v != 0 else 0.0 for v in position]
    diameter = row["uncertainty_diameter_m"]
    if diameter is None:
        reasons.append("uncertainty_diameter_unavailable")
    elif not _finite(diameter) or diameter < 0:
        reasons.append("uncertainty_diameter_invalid")
    elif diameter > settings["max_region_diameter_m"]:
        reasons.append("uncertainty_region_too_large")
    else:
        normalized["uncertainty_diameter_m"] = float(diameter)
    for flag, reason in (
        ("all_camera_scenarios_estimated", "not_all_camera_scenarios_estimated"),
        ("all_regions_bounded", "not_all_regions_bounded"),
        ("way_proposal_stable_across_scenarios", "road_hypothesis_not_stable"),
    ):
        if row[flag] is not True:
            reasons.append(reason)
    if not _way_id(row["nominal_way_id"]):
        reasons.append("road_hypothesis_unavailable_or_invalid")
    frames = row["source_frame_ids"]
    if (not isinstance(frames, list) or not 1 <= len(frames) <= 4096
            or not all(_text(value) for value in frames) or len(set(frames)) != len(frames)):
        reasons.append("source_frame_identity_unavailable_or_invalid")
    else:
        normalized["source_frame_ids"] = sorted(frames)
    if reasons:
        return None, {"group_id": identity, "reasons": reasons}
    return normalized, None


def _distance(a, b):
    """Spherical great-circle distance in metres, bounded to local candidate pairs."""
    lat_a, lon_a = map(math.radians, a)
    lat_b, lon_b = map(math.radians, b)
    h = math.sin((lat_b - lat_a) / 2) ** 2 + math.cos(lat_a) * math.cos(lat_b) * math.sin((lon_b - lon_a) / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(math.sqrt(max(0, min(1, h))))


def propose_identities(descriptors: list[dict], settings: dict | None = None) -> dict:
    """Return stable multi-group proposals plus excluded and unmerged populations.

    IDs hash all eligible member descriptors, algorithm, and settings. They identify
    this inference artifact, not a durable physical-sign truth ID. Singletons are
    explicitly unmerged and are never forced into an inferred multi-group identity.
    """
    policy = _settings(settings)
    if not isinstance(descriptors, list) or len(descriptors) > MAX_DESCRIPTORS:
        raise ValueError("descriptor_population_cap_exceeded_or_not_a_list")
    eligible, excluded, identities = {}, [], set()
    for row in descriptors:
        normalized, failure = _descriptor(row, policy)
        identity = row["group_id"]
        if identity in identities:
            raise ValueError("duplicate_group_id")
        identities.add(identity)
        if failure:
            excluded.append(failure)
        else:
            eligible[identity] = normalized
    if len(eligible) > MAX_ELIGIBLE_DESCRIPTORS:
        raise ValueError("eligible_population_cap_exceeded_no_partial_result")
    keys = sorted(eligible)
    blocked, pair_distances, heap = [], {}, []
    for i, left in enumerate(keys):
        a = eligible[left]
        for right in keys[i + 1:]:
            b = eligible[right]
            reasons = []
            distance = _distance(a["candidate_lat_lon"], b["candidate_lat_lon"])
            if distance > policy["max_pair_distance_m"]:
                reasons.append("pair_distance_exceeds_limit")
            if a["classification_key"] != b["classification_key"]:
                reasons.append("classification_mismatch")
            if a["nominal_way_id"] != b["nominal_way_id"]:
                reasons.append("road_hypothesis_mismatch")
            if set(a["source_frame_ids"]) & set(b["source_frame_ids"]):
                reasons.append("shared_source_frame_possible_co_visible_signs")
            if reasons:
                blocked.append({"member_group_ids": [left, right], "distance_m": distance, "reasons": reasons})
            else:
                pair_distances[(left, right)] = distance
                heapq.heappush(heap, (distance, (left,), (right,)))
    active = {(identity,): (identity,) for identity in keys}
    merge_steps = []
    while heap:
        distance, left, right = heapq.heappop(heap)
        if left not in active or right not in active:
            continue
        del active[left], active[right]
        merged = tuple(sorted(left + right))
        for other in sorted(active):
            distances = [pair_distances.get(tuple(sorted((a, b)))) for a in merged for b in other]
            if all(value is not None for value in distances):
                a, b = sorted((merged, other))
                heapq.heappush(heap, (max(distances), a, b))
        active[merged] = merged
        merge_steps.append({"left_group_ids": list(left), "right_group_ids": list(right),
                            "complete_link_distance_m": distance})
    proposals, unmerged = [], []
    for members in sorted(active):
        if len(members) == 1:
            identity = members[0]
            has_pair = any(identity in pair for pair in pair_distances)
            unmerged.append({"group_id": identity,
                             "reason": "complete_link_partition_prevents_merge" if has_pair else "no_compatible_eligible_group"})
            continue
        member_descriptors = [eligible[identity] for identity in members]
        identity_content = {"algorithm": ALGORITHM, "settings": policy, "members": member_descriptors}
        max_distance = max(pair_distances[(a, b)] for i, a in enumerate(members) for b in members[i + 1:])
        proposals.append({"proposal_id": _hash(identity_content), "member_group_ids": list(members),
                          "member_descriptors_sha256": _hash(member_descriptors),
                          "status": "conditional_inferred", "max_pair_distance_m": max_distance,
                          "classification_key": member_descriptors[0]["classification_key"],
                          "nominal_way_id": member_descriptors[0]["nominal_way_id"],
                          "reviewed": False, "proves_physical_identity": False,
                          "acceptance_eligible": False, "publish_eligible": False})
    return {"schema_version": 1, "algorithm": ALGORITHM, "settings": policy,
            "scope": "conditional_offline_identity_proposals", "source_eligibility_owned_by_caller": True,
            "proposals": proposals, "excluded_groups": sorted(excluded, key=lambda row: row["group_id"]),
            "unmerged_groups": unmerged, "blocked_pairs": blocked, "merge_steps": merge_steps,
            "counts": {"input_groups": len(descriptors), "eligible_groups": len(eligible),
                       "excluded_groups": len(excluded), "unmerged_groups": len(unmerged),
                       "proposals": len(proposals), "proposed_member_groups": sum(len(p["member_group_ids"]) for p in proposals)},
            "reviewed": False, "proves_physical_identity": False, "acceptance_eligible": False,
            "publish_eligible": False, "training_eligible": False,
            "limitations": ["A source observation is not a reviewed physical sign identity.",
                            "All camera scenarios, region-union bounds and frame identities are caller-supplied declarations.",
                            "Matching class, road and nearby position can still describe distinct signs.",
                            "Complete-link tie breaking is deterministic, not evidence favoring one physical partition.",
                            "No calibrated position accuracy, legal applicability or physical identity is established."]}
