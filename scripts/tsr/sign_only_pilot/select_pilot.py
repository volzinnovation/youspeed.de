#!/usr/bin/env python3
"""Freeze a small sign-only review queue with historical/geographic exclusions.

Selection reads metadata, existing review provenance and class-blind map-point
counts only. It neither inspects pixels nor turns proposals into ground truth.
New test images are selected without sign annotations or detector/map counts.
"""

import argparse
from collections import Counter, defaultdict
from hashlib import sha256
import json
import math
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "research"))
from audit_hf_mapillary_teacher import PointIndex, digest, distance_and_bearing, json_lines


class StateBoundary:
    """Exact polygon rings with latitude-bucketed edges; boundary is included."""

    def __init__(self, geometry):
        if geometry.get("type") == "Feature":
            geometry = geometry["geometry"]
        polygons = geometry.get("coordinates")
        if geometry.get("type") == "Polygon":
            polygons = [polygons]
        elif geometry.get("type") != "MultiPolygon":
            raise ValueError("Boundary must be a Polygon or MultiPolygon")
        self.polygons = []
        for polygon in polygons:
            rings = []
            for ring in polygon:
                buckets = defaultdict(list)
                for a, b in zip(ring, ring[1:] + ring[:1]):
                    for key in range(math.floor(min(a[1], b[1]) * 100), math.floor(max(a[1], b[1]) * 100) + 1):
                        buckets[key].append((a, b))
                rings.append(buckets)
            self.polygons.append(rings)

    @staticmethod
    def ring_relation(point, buckets):
        x, y = point
        inside = False
        for a, b in buckets.get(math.floor(y * 100), ()):
            ax, ay = a[:2]
            bx, by = b[:2]
            cross = (x - ax) * (by - ay) - (y - ay) * (bx - ax)
            if abs(cross) <= 1e-13 and min(ax, bx) - 1e-13 <= x <= max(ax, bx) + 1e-13 and min(ay, by) - 1e-13 <= y <= max(ay, by) + 1e-13:
                return 2
            if (ay > y) != (by > y) and x < ax + (y - ay) * (bx - ax) / (by - ay):
                inside = not inside
        return int(inside)

    def contains(self, point):
        for rings in self.polygons:
            outer = self.ring_relation(point, rings[0])
            if outer == 2:
                return True
            if outer == 1:
                holes = [self.ring_relation(point, hole) for hole in rings[1:]]
                if 2 in holes or 1 not in holes:
                    return True
        return False


def rank(seed, purpose, identifier):
    return sha256(f"{seed}:{purpose}:{identifier}".encode()).hexdigest()


def separated(row, others, distance_m):
    sequences = set(row["sequence_ids"])
    for other in others:
        if row["picture_id"] == other["picture_id"] or row["sha256"] == other["sha256"]:
            return False
        if sequences.intersection(other["sequence_ids"]):
            return False
        if distance_and_bearing(row["coordinates"], other["coordinates"])[0] < distance_m:
            return False
    return True


def spaced(row, others, distance_m=100):
    return all(distance_and_bearing(row["coordinates"], other["coordinates"])[0] >= distance_m for other in others)


def load_frames(metadata, source_plan, candidates):
    metadata_rows = {row["picture_id"]: row for row in json_lines(metadata) if row.get("task") == "detector"}
    counts = {row["picture_id"]: (row["candidate_count"], row["pose"]["cone_eligible"])
              for row in json_lines(candidates)}
    result = {}
    for planned in json_lines(source_plan):
        row = planned.get("row", {})
        if row.get("task") != "detector":
            continue
        pid = row["picture_id"]
        final = metadata_rows[pid]
        for key in ("sample_id", "dimensions", "source_revision", "path"):
            if row.get(key) != final.get(key):
                raise ValueError(f"Pinned source plan disagrees with final metadata for {pid}: {key}")
        annotation = planned["annotation"]
        source = annotation["source_metadata"]
        picture = source["picture"]
        points, qualified = counts.get(pid, (0, False))
        result[pid] = dict(picture_id=pid, image_id=final["sample_id"], sample_id=final["sample_id"],
            hf_path=final["path"], sha256=final["sha256"], image_sha256=final["sha256"],
            dimensions=final["dimensions"], width=final["dimensions"][0], height=final["dimensions"][1],
            coordinates=picture["geometry"]["coordinates"][:2],
            sequence_ids=sorted({c["id"] for c in source["collections"]}),
            capture_at=final.get("capture_at"), source_id=final.get("source_id"),
            source_revision=final["source_revision"], annotation_sha256=final.get("annotation_sha256"),
            source_annotations=[{k: box[k] for k in ("annotation_id", "box_xyxy", "label_origin") if k in box}
                                for box in annotation.get("annotations", []) if box.get("label") == "sign"],
            mapillary_candidate_count=points, mapillary_cone_eligible=qualified,
            existing_truth_boxes=[], existing_truth_complete=False,
            review_status="pending_complete_scene_review")
    return result


def select(args):
    frames = load_frames(args.metadata, args.source_plan, args.map_candidates)
    boundary = StateBoundary(json.loads(args.boundary.read_text()))
    outside_boundary = [dict(picture_id=row["picture_id"], coordinates=row["coordinates"], reason="outside_frozen_baden_wuerttemberg_polygon")
                        for row in frames.values() if not boundary.contains(row["coordinates"])]
    excluded_ids = {row["picture_id"] for row in outside_boundary}
    frames = {pid: row for pid, row in frames.items() if pid not in excluded_ids}
    history = json.loads(args.exposure.read_text())
    known = history["frames"]
    known_ids = {x["picture_id"] for x in known}
    known_hashes = {h for x in known for h in x.get("sha256s", [])}
    known_sequences = {s for x in known for s in x["sequence_ids"]}
    geography = PointIndex((dict(id=x["picture_id"], geometry=dict(type="Point", coordinates=x["coordinates"]))
                            for x in known if x.get("coordinates")), args.separation_m)
    reusable = json.loads(args.reusable.read_text())["frames"]
    old_training, old_validation = [], []
    for old in reusable:
        row = frames.get(old["picture_id"])
        if not row or row["sha256"] != old["source_sha256"] or row["dimensions"] != old["dimensions"]:
            continue
        row = row | dict(existing_truth_boxes=[dict(box_xyxy=box, label="sign", label_origin="historical_complete_review") for box in old["boxes"]],
                         existing_truth_complete=True, historical_review_source=old["label_source"],
                         historical_exposure=old["exposure"], review_status="historical_complete_review")
        if old["exposure"] in ("d4_optimization_complete_scene", "historical_training_review"):
            old_training.append(row)
        elif old["exposure"] == "d4_threshold_development":
            old_validation.append(row)

    exclusions, fresh = Counter(), []
    for row in frames.values():
        if row["picture_id"] in known_ids or row["sha256"] in known_hashes:
            exclusions["known_image_or_bytes"] += 1
        elif set(row["sequence_ids"]) & known_sequences:
            exclusions["known_sequence"] += 1
        elif not row["sequence_ids"] or not row["coordinates"]:
            exclusions["missing_group_or_coordinates"] += 1
        elif geography.nearby(row["coordinates"]):
            exclusions["within_historical_geographic_buffer"] += 1
        else:
            fresh.append(row)

    # Geographic tiles, chosen by available sample count, without consulting
    # sign annotations, Mapillary candidates, detector scores or test pixels.
    tiles = defaultdict(list)
    for row in fresh:
        lon, lat = row["coordinates"]
        tiles[(math.floor(lon / .05), math.floor(lat / .05))].append(row)
    clusters, test = [], []
    for key, pool in sorted(tiles.items(), key=lambda pair: (-len(pair[1]), pair[0])):
        center = [(key[0] + .5) * .05, (key[1] + .5) * .05]
        if any(distance_and_bearing(center, c["center"])[0] < 3000 for c in clusters):
            continue
        selected = []
        for row in sorted(pool, key=lambda r: rank(args.seed, "test", r["picture_id"])):
            if spaced(row, selected, 100):
                selected.append(row)
                if len(selected) == args.test_per_cluster:
                    break
        if len(selected) != args.test_per_cluster:
            continue
        cluster_id = f"geo-{key[0]}-{key[1]}"
        clusters.append(dict(id=cluster_id, center=center, eligible_pool=len(pool), selected=len(selected)))
        test.extend(row | dict(split="test", geographic_cluster=cluster_id,
                              selection_reason="hash_ranked_geographic_sample_without_label_or_proposal_selection") for row in selected)
        if len(clusters) == args.test_clusters:
            break
    if len(clusters) != args.test_clusters:
        raise ValueError("Insufficient fresh geography clusters; do not weaken the holdout silently")

    train = [row | dict(split="train", selection_reason="reuse_known_complete_training_scene")
             for row in old_training if separated(row, test, args.separation_m)]
    validation = []
    # Preserve empty-scene support in the existing, already-opened development
    # set. Its labels may guide selection; it is never called a fresh test set.
    for has_signs in (True, False):
        candidates = [r for r in old_validation if bool(r["existing_truth_boxes"]) == has_signs]
        added = 0
        for row in sorted(candidates, key=lambda r: rank(args.seed, "validation", r["picture_id"])):
            if separated(row, train + test, args.separation_m) and spaced(row, validation):
                validation.append(row | dict(split="validation", selection_reason="historical_complete_development_scene"))
                added += 1
                if added == args.validation // 2:
                    break
    if len(validation) != args.validation:
        raise ValueError(f"Only {len(validation)} complete development scenes satisfy separation")

    selected_ids = {r["picture_id"] for r in train + validation + test}
    eligible = [r for r in frames.values() if r["picture_id"] not in selected_ids
                and separated(r, validation + test, args.separation_m)]
    novel_train = []
    strata = [("map_candidates_without_source_boxes", args.new_train // 2,
               lambda r: not r["source_annotations"] and r["mapillary_cone_eligible"] and r["mapillary_candidate_count"] > 0),
              ("source_box_diversity", args.new_train // 4, lambda r: bool(r["source_annotations"])),
              ("random_scene_background_and_sign_discovery", args.new_train - args.new_train // 2 - args.new_train // 4, lambda r: True)]
    used_sequences = set()
    for name, quota, predicate in strata:
        added = 0
        for row in sorted((r for r in eligible if predicate(r)), key=lambda r: rank(args.seed, name, r["picture_id"])):
            if row["picture_id"] in selected_ids or set(row["sequence_ids"]) & used_sequences:
                continue
            if not spaced(row, train + novel_train):
                continue
            novel_train.append(row | dict(split="train", selection_reason=name))
            selected_ids.add(row["picture_id"])
            used_sequences.update(row["sequence_ids"])
            added += 1
            if added == quota:
                break
        if added != quota:
            raise ValueError(f"Training stratum {name} has only {added}/{quota} separated samples")
    train += novel_train
    chosen = train + validation + test
    # Shared sequences define connected groups, including sequences with more
    # than one membership; no group is split across train/validation/test.
    parents = {s: s for row in chosen for s in row["sequence_ids"]}
    def root(s):
        while parents[s] != s:
            parents[s] = parents[parents[s]]
            s = parents[s]
        return s
    for row in chosen:
        first = row["sequence_ids"][0]
        for s in row["sequence_ids"][1:]:
            a, b = root(first), root(s)
            parents[max(a, b)] = min(a, b)
    for row in chosen:
        row["group_id"] = "sequence:" + root(row["sequence_ids"][0])
    minimum_distances = {}
    for a, b in (("train", "validation"), ("train", "test"), ("validation", "test")):
        left, right = [r for r in chosen if r["split"] == a], [r for r in chosen if r["split"] == b]
        if any(not separated(row, right, args.separation_m) for row in left):
            raise AssertionError(f"Cross-split leakage: {a}/{b}")
        minimum_distances[f"{a}/{b}"] = min(distance_and_bearing(x["coordinates"], y["coordinates"])[0] for x in left for y in right)
    result = dict(schema="streetshots-sign-only-pilot-selection-v1", dataset_repo="loffenauer/streetshots",
        dataset_revision=args.dataset_revision, selection_seed=args.seed, status="pending_new_complete_scene_review",
        model_baseline_revision=history["model_revision"], baseline_checkpoint_sha256=history["checkpoint_sha256"],
        counts=dict(Counter(r["split"] for r in chosen)), new_training_count=len(novel_train),
        reused_complete_training_count=len(train)-len(novel_train), historical_exposure_records=len(known),
        geography_scope="inside_frozen_baden_wuerttemberg_polygon", in_scope_source_images=len(frames),
        outside_boundary_exclusions=outside_boundary,
        fresh_holdout_pool=len(fresh), holdout_exclusions=dict(exclusions), test_clusters=clusters,
        cross_split_minimum_image_distance_m=minimum_distances,
        selection_contract=dict(minimum_cross_split_distance_m=args.separation_m,
            prior_exposure_buffer_m=args.separation_m, minimum_within_selected_scene_spacing_m=100,
            test_geographic_cell_degrees=.05, minimum_test_cluster_center_distance_m=3000,
            test_selection_uses_annotations_or_model_scores=False,
            test_selection_uses_mapillary_counts=False,
            full_sequences_must_remain_in_one_partition=True),
        source_inputs={k: dict(path=str(v.resolve()), sha256=digest(v)) for k, v in
                       (("boundary", args.boundary), ("metadata", args.metadata), ("source_plan", args.source_plan),
                        ("map_candidates", args.map_candidates), ("exposure", args.exposure), ("reusable", args.reusable))},
        script_sha256=digest(__file__), limitations=[history["limitation"],
            "Geography is separated using camera positions and full sequence identities; physical-sign identity is not yet independently adjudicated.",
            "Source boxes and Mapillary points are proposals, not complete labels. New scenes require exhaustive review including missing signs and negatives.",
            "The existing development set was used to select the historical d4 model and its threshold.",
            "No candidate training or pixel inspection occurs in this selection script."], frames=chosen)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("metadata", "source-plan", "map-candidates", "exposure", "reusable", "boundary", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--dataset-revision", required=True)
    parser.add_argument("--seed", default="sign-only-mapillary-pilot-20261114-v1")
    parser.add_argument("--separation-m", type=float, default=500)
    parser.add_argument("--new-train", type=int, default=64)
    parser.add_argument("--validation", type=int, default=24)
    parser.add_argument("--test-clusters", type=int, default=3)
    parser.add_argument("--test-per-cluster", type=int, default=8)
    args = parser.parse_args()
    result = select(args)
    print(json.dumps({k: result[k] for k in ("counts", "fresh_holdout_pool", "test_clusters", "cross_split_minimum_image_distance_m")}, indent=2))


if __name__ == "__main__":
    main()
