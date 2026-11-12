"""Rebind explicit image/identity reviews to a freshly built source inventory.

This module never accepts an old inventory or old coordinates. Reviews transfer
only while their annotation membership, source class and pixel boxes still match.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib

from inspector.place_sign_review import local_picture


def effective_pose(group):
    refinement = group.get("mobile_refinement") or {}
    return refinement.get("proposal") if refinement.get("status") == "refined" else group.get("proposal")


def merged_group(members, canonical_id, pose_source, withheld):
    group = deepcopy(next(item for item in members if item["id"] == canonical_id))
    anchors, following, mobile = {}, {}, {}
    for member in members:
        for key, target in (("observations", anchors), ("follow_on_observations", following)):
            for observation in member.get(key, []):
                prior = target.get(observation["image_id"])
                if prior and prior["annotation_id"] != observation["annotation_id"]:
                    raise ValueError("A same-frame identity conflict needs explicit adjudication")
                target[observation["image_id"]] = deepcopy(observation)
        for observation in member.get("mobile_observations", []):
            mobile[observation["evidence_id"]] = deepcopy(observation)
    for image_id in anchors.keys() & following.keys():
        if anchors[image_id]["annotation_id"] != following[image_id]["annotation_id"]:
            raise ValueError("Conflicting anchor and follow-on annotation identity")
    group["observations"] = list(anchors.values())
    group.pop("follow_on_observations", None)
    remaining = [row for key, row in following.items() if key not in anchors]
    if remaining:
        group["follow_on_observations"] = remaining
    group.pop("mobile_observations", None)
    if mobile:
        group["mobile_observations"] = list(mobile.values())
    source = next((member for member in members if member["id"] == pose_source), None)
    if source is None:
        raise ValueError("The reviewed pose source must be a current component member")
    group["proposal"] = deepcopy(source.get("proposal")) if not withheld else None
    group.pop("mobile_refinement", None)
    if not withheld and source.get("mobile_refinement", {}).get("status") == "refined":
        group["mobile_refinement"] = deepcopy(source["mobile_refinement"])
    if len(members) > 1:
        group.pop("follow_on_diagnostic", None)
        group.pop("challenged_proposal", None)
    return group


def apply_decisions(document, decisions, *, media_dir=None):
    groups = {group["id"]: group for group in document["groups"]}
    reviews = {review["group_id"]: review for review in decisions["reviews"]}
    if len(groups) != len(document["groups"]) or len(reviews) != len(decisions["reviews"]) or set(reviews) - set(groups):
        raise ValueError("Duplicate or missing current review group")
    verified_images = {}
    for key, review in reviews.items():
        group = groups[key]
        observations = group["observations"] + group.get("follow_on_observations", [])
        actual = {item["annotation_id"]: item for item in observations}
        bound = {item["annotation_id"]: item for item in review["current_evidence"]}
        if (len(actual) != len(observations) or len(bound) != len(review["current_evidence"])
                or set(actual) != set(bound) or set(actual) != set(review["current_annotation_ids"])):
            raise ValueError(f"Review membership changed; re-review group {key}")
        for annotation_id, observation in actual.items():
            evidence = bound[annotation_id]
            if (evidence["image_id"] != observation["image_id"]
                    or evidence["box_xyxy"] != observation["box_xyxy"]
                    or evidence["source_sign_code"] != group["sign_code"]):
                raise ValueError(f"Reviewed annotation changed; re-review group {key}")
            if media_dir is not None:
                picture_id = observation["image_id"]
                if picture_id not in verified_images:
                    raw = local_picture(media_dir, picture_id)
                    if raw is None:
                        raise ValueError("Reviewed original image is unavailable")
                    verified_images[picture_id] = hashlib.sha256(raw).hexdigest()
                if verified_images[picture_id] != evidence["image_sha256"]:
                    raise ValueError(f"Reviewed image bytes changed; re-review group {key}")
    aliases = decisions.get("aliases", {})
    if set(aliases) - set(groups) or set(aliases.values()) - set(groups):
        raise ValueError("Alias points outside the current source inventory")

    def canonical(key):
        seen = set()
        while key in aliases:
            if key in seen:
                raise ValueError("Identity alias cycle")
            seen.add(key)
            key = aliases[key]
        return key

    components = {}
    for key, group in groups.items():
        components.setdefault(canonical(key), []).append(group)
    excluded = set(decisions.get("excluded_identity_group_ids", []))
    withheld = decisions.get("withheld_positions", {})
    sources = decisions.get("pose_sources", {})
    if (excluded | set(withheld) | set(sources)) - set(components):
        raise ValueError("Decision references an absent canonical component")
    result = deepcopy(document)
    result["groups"] = []
    for key, members in components.items():
        reviewed = [reviews[member["id"]] for member in members if member["id"] in reviews]
        if len(members) > 1 and len(reviewed) != len(members):
            raise ValueError("Every merged identity member must have a bound image review")
        classes = {review["reviewed_class"] for review in reviewed}
        if len(classes) > 1:
            raise ValueError("Reviewed classes conflict within an identity component")
        choice = sources.get(key, key)
        group = merged_group(members, key, choice, key in withheld or key in excluded)
        group["benchmark_review"] = {
            "status": "assistant_image_reviewed" if reviewed else "not_reviewed",
            "reviewed_sign_code": next(iter(classes)) if classes else group["sign_code"],
            "source_group_ids": [member["id"] for member in members],
            "object_ground_truth_eligible": bool(reviewed) and key not in excluded,
            "identity_status": "mixed_group_excluded" if key in excluded else "reviewed_group" if reviewed else "unreviewed",
            "pose_source_group_id": choice if effective_pose(group) else None,
            "pose_is_ground_truth": False,
            "position_note": withheld.get(key, "Existing Inspector estimate; not a surveyed coordinate."),
        }
        result["groups"].append(group)
    result["default_group_id"] = canonical(document["default_group_id"]) if document.get("default_group_id") else None
    report = {"source_group_count": len(groups), "canonical_group_count": len(components),
              "bound_review_count": len(reviews), "verified_original_image_count": len(verified_images),
              "merged_alias_count": len(groups) - len(components), "excluded_identity_count": len(excluded),
              "review_binding": "annotation_identity_source_class_and_native_box",
              "old_inventory_or_coordinate_input": False, "spatial_ground_truth_established": False}
    result["summary"] = {**result.get("summary", {}), "groups": len(result["groups"]),
                         "groups_with_proposal": sum(effective_pose(group) is not None for group in result["groups"]),
                         "merged_alias_count": report["merged_alias_count"]}
    return result, report
