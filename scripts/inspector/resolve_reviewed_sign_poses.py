"""Recover bounded pose estimates from all observations of reviewed identities.

Canonical merges can promote follow-on frames to primary observations. Rebuild
their rank-adjacent tracks without using old proposals as geometric evidence.
This is an estimator replay, not a source refresh or a ground-truth adjudication.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import json
import math
from pathlib import Path

from fiona.transform import transform_geom
from shapely.geometry import Point, box, shape

from scripts.inspector.build_place_sign_review import (
    FOLLOW_ON_CONTEXT_M,
    MAX_FOLLOW_ON_FRAMES,
    MAX_PRIVATE_INPUT_BYTES,
    adjacent_proposal,
    compatible_next_frame,
)
from scripts.inspector.adjacent_sign_pose import MAX_ADJACENT_RADIUS_M, MAX_SEQUENCES
from scripts.inspector.refine_place_sign_pose import (
    distinct_views,
    measure,
    refine_group,
    supports_position,
)
from scripts.tsr.collection.estimate_sign_poses import METRIC, WGS84, project
from scripts.tsr.collection.osm_sign_heading import RoadHeadingIndex
from scripts.tsr.collection.panoramax_sequence_bridge import BridgeView
from scripts.tsr.collection.run_sign_pose_batch import read_private, write_private_json


class _ImageOnlyHeadings:
    def fallback(self, *args):
        return None


def _observations(group):
    return group["observations"] + group.get("follow_on_observations", [])


def _competing_annotations(document):
    """Retain the original next-frame gate against same-class competing boxes."""
    images = defaultdict(set)
    for group in document["groups"]:
        for row in _observations(group):
            images[row["sequence_id"], row["image_id"], group["sign_code"]].add(
                row["annotation_id"]
            )
    return images


def rebuild_tracks(group, *, competing_annotations=None):
    """Return one earliest compatible, rank-consecutive chain per sequence.

    Track selection uses source order and the existing compatibility gate only;
    it never searches for a combination which makes a downstream fit succeed.
    A chain is capped at the existing anchor plus two follow-on frames.
    """
    competing_annotations = competing_annotations or {}
    sequences = defaultdict(lambda: defaultdict(list))
    seen = set()
    rejected = Counter()
    measurements = defaultdict(set)
    fields = ("image_id", "sequence_id", "sequence_rank", "captured_at", "longitude",
              "latitude", "bearing_deg", "bearing_error_deg", "horizontal_error_m",
              "camera_heading_deg", "angular_height_deg", "fix_id", "fix_at")
    for row in _observations(group):
        measurements[row["annotation_id"]].add(tuple(row.get(key) for key in fields))
    for row in _observations(group):
        key = row["annotation_id"]
        if key in seen:
            continue
        seen.add(key)
        if len(measurements[key]) != 1:
            rejected["conflicting_annotation_measurements"] += 1
            continue
        rank = row.get("sequence_rank")
        if type(rank) is not int or rank < 0:
            rejected["missing_sequence_rank"] += 1
            continue
        try:
            heading, height = row["camera_heading_deg"], row["angular_height_deg"]
            if not (math.isfinite(heading) and 0 <= heading <= 360
                    and math.isfinite(height) and 0 < height < 180):
                raise ValueError("invalid camera heading or panel height")
            ray = measure(group, row, "panoramax")
            view = BridgeView(ray, heading % 360, height,
                              (row["longitude"], row["latitude"]))
        except (ValueError, TypeError, KeyError, OverflowError):
            rejected["invalid_observation"] += 1
            continue
        sequences[row["sequence_id"]][rank].append((row, view))

    anchors, continuations, selected = [], [], []
    for sequence, ranks in sorted(sequences.items()):
        for rank, entries in sorted(ranks.items()):
            if len(entries) != 1:
                rejected["ambiguous_anchor_rank"] += 1
                continue
            anchor, view = entries[0]
            previous, tail = view, []
            for offset in range(1, MAX_FOLLOW_ON_FRAMES + 1):
                following = ranks.get(rank + offset, [])
                if not following:
                    break
                if len(following) != 1:
                    rejected["ambiguous_next_rank"] += 1
                    break
                row, candidate = following[0]
                competitors = competing_annotations.get(
                    (sequence, row["image_id"], group["sign_code"]),
                    {row["annotation_id"]},
                )
                if len(competitors) != 1:
                    rejected["ambiguous_next_frame"] += 1
                    break
                if not compatible_next_frame(previous, candidate):
                    rejected["incompatible_next_frame"] += 1
                    break
                tail.append((row, offset, candidate))
                previous = candidate
            if tail:
                anchors.append(view)
                continuations.extend((anchor, offset, candidate)
                                     for _, offset, candidate in tail)
                selected.append({
                    "sequence_id": sequence,
                    "annotation_ids": [anchor["annotation_id"]]
                    + [row["annotation_id"] for row, _, _ in tail],
                    "sequence_ranks": [rank] + [rank + offset for _, offset, _ in tail],
                })
                break
    return anchors, continuations, {
        "observation_count": len(seen),
        "selected_tracks": selected,
        "rejected_observation_counts": dict(sorted(rejected.items())),
    }


def _window(document):
    place = document["place"]
    geometry = place.get("scope_geometry_wgs84") or place.get("boundary_wgs84")
    if geometry:
        return shape(transform_geom(WGS84, METRIC, geometry))
    return box(*place["bounds_en_m"])


def _mobile_proposal(group, window):
    result = refine_group(group)
    if not result or result["status"] != "refined":
        return None, result
    candidate = {**(group.get("proposal") or {}), **result["proposal"]}
    radius = candidate.get("position_radius_m")
    if radius is None or not math.isfinite(radius) or not 0 < radius <= MAX_ADJACENT_RADIUS_M:
        return None, {**result, "status": "mobile_position_unbounded"}
    point, _ = project([candidate["longitude"]], [candidate["latitude"]])[0]
    if window.distance(Point(point)) > FOLLOW_ON_CONTEXT_M:
        return None, {**result, "status": "outside_follow_on_context"}
    views, _ = distinct_views(group)
    supporting = [ray for ray, _ in views if supports_position(ray, point)]
    candidate.setdefault("position_method", "mobile_and_panoramax_optical_rays")
    candidate.update(support_count=len(supporting),
                     independent_sequence_count=result["drive_count"],
                     in_review_window=window.covers(Point(point)))
    return candidate, result


def resolve_document(document, *, roads=None):
    """Return a copied review document and auditable per-group resolution report.

    Only reviewed, object-eligible identities with no current proposal are
    attempted. Existing proposals, withheld hypotheses and truth fields are
    never inputs to a new position. Callers must refresh and validate source
    observations before calling this function for a new inventory snapshot.
    """
    output = deepcopy(document)
    window = _window(output)
    competitors = _competing_annotations(output)
    roads = roads if roads is not None else _ImageOnlyHeadings()
    entries, excluded, retained, unreviewed = [], [], [], []
    for group in output["groups"]:
        review = group.get("benchmark_review", {})
        if review.get("identity_status") == "mixed_group_excluded":
            excluded.append(group["id"])
            continue
        if review.get("object_ground_truth_eligible") is not True:
            unreviewed.append(group["id"])
            continue
        if group.get("proposal") is not None:
            retained.append(group["id"])
            continue
        anchors, continuations, details = rebuild_tracks(
            group, competing_annotations=competitors
        )
        if len(anchors) > MAX_SEQUENCES:
            proposal, status, diagnostics = None, "too_many_adjacent_sequences", {
                "input_sequence_count": len(anchors),
            }
        else:
            proposal, status, diagnostics = adjacent_proposal(
                anchors, continuations, window, roads
            )
        group["proposal"] = proposal
        mobile, mobile_result = _mobile_proposal(group, window)
        group.pop("mobile_refinement", None)
        if mobile_result:
            group["mobile_refinement"] = deepcopy(mobile_result)
        if mobile is not None:
            proposal = group["proposal"] = mobile
            group["mobile_refinement"]["proposal"] = deepcopy(mobile)
        entry = {
            "group_id": group["id"],
            "status": "estimated" if proposal else "unresolved",
            "adjacent_status": status,
            "adjacent_diagnostics": diagnostics,
            **details,
            "mobile_status": mobile_result["status"] if mobile_result else "no_mobile_evidence",
            "mobile_evidence_ids": mobile_result.get("mobile_evidence_ids", [])
            if mobile_result and mobile is not None else [],
            "pose_is_ground_truth": False,
            "previous_position_note": review.get("position_note"),
        }
        if proposal:
            entry["position_method"] = proposal["position_method"]
            entry["position_radius_m"] = proposal["position_radius_m"]
            review["pose_source_group_id"] = group["id"]
            review["pose_is_ground_truth"] = False
            review["position_note"] = (
                "Recomputed Inspector estimate from current canonical observations; "
                "conditional uncertainty envelope, not a surveyed coordinate."
            )
        group["pose_resolution"] = deepcopy(entry)
        entries.append(entry)

    resolved = [row["group_id"] for row in entries if row["status"] == "estimated"]
    unresolved = [row["group_id"] for row in entries if row["status"] == "unresolved"]
    positions = Counter(group["proposal"]["position_status"] if group.get("proposal")
                        else "unresolved" for group in output["groups"])
    output.setdefault("summary", {}).update(
        groups=len(output["groups"]),
        groups_with_proposal=len(output["groups"]) - positions["unresolved"],
        position_status_counts=dict(sorted(positions.items())),
    )
    report = {
        "schema_version": 1,
        "method": "canonical_observation_adjacent_track_replay",
        "source_snapshot_at": document.get("summary", {}).get("source_snapshot_at"),
        "source_refresh_performed": False,
        "pose_is_ground_truth": False,
        "attempted_group_count": len(entries),
        "resolved_group_count": len(resolved),
        "unresolved_group_count": len(unresolved),
        "resolved_group_ids": resolved,
        "unresolved_group_ids": unresolved,
        "retained_existing_pose_group_ids": retained,
        "excluded_group_ids": excluded,
        "unreviewed_group_count": len(unreviewed),
        "unresolved_reason_counts": dict(sorted(Counter(
            row["adjacent_status"] for row in entries if row["status"] == "unresolved"
        ).items())),
        "groups": entries,
    }
    return output, report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    parser.add_argument("--road-graph", type=Path)
    args = parser.parse_args()
    document = json.loads(read_private(args.input, MAX_PRIVATE_INPUT_BYTES))
    output, report = resolve_document(
        document, roads=RoadHeadingIndex.load(args.road_graph) if args.road_graph else None
    )
    write_private_json(args.output, output)
    write_private_json(args.report, report)
    print(json.dumps({key: value for key, value in report.items() if key.endswith("_count")},
                     sort_keys=True))


if __name__ == "__main__":
    main()
