#!/usr/bin/env python3
"""Offline reviewed-image geometry ablation; never imported by a mobile app.

No detector, learned lane model, behavior rule, or recognition confirmation runs.
Road polygons and visible post anchors are reviewed inputs, not governing-road
labels. Expected labels are read only by score(). Public stills are not video.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[3]
SCHEMA_PATH = ROOT / "shared/tsr/applicability/fixtures/image-road-corpus-v1.schema.json"
CONFIG = {"max_anchor_distance": 0.025, "minimum_separation": 0.015,
          "max_track_gap_ms": 2500, "behavior_enabled": False,
          "learned_geometry_enabled": False,
          "manual_arrow_road_relations_enabled": False}


def digest(data):
    return hashlib.sha256(data).hexdigest()


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"),
                      allow_nan=False).encode()


def timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("Capture timestamp needs an explicit timezone")
    # Integer microseconds preserve original metadata ordering without rounding
    # distinct IGN positions into one millisecond. Ordering is not real cadence.
    delta = parsed.astimezone(timezone.utc) - datetime(1970, 1, 1, tzinfo=timezone.utc)
    return (delta.days * 86400 + delta.seconds) * 1_000_000 + delta.microseconds


def finite_unit(value):
    return type(value) in (float, int) and math.isfinite(value) and 0 <= value <= 1


def segment_distance(point, a, b):
    vx, vy = b[0] - a[0], b[1] - a[1]
    norm = vx * vx + vy * vy
    t = 0 if norm == 0 else max(0, min(1, ((point[0] - a[0]) * vx
                                        + (point[1] - a[1]) * vy) / norm))
    return math.hypot(point[0] - a[0] - t * vx, point[1] - a[1] - t * vy)


def polygon_distance(point, polygon):
    """Return (inside, edge distance); boundary is conservatively ambiguous."""
    inside = False
    for a, b in zip(polygon, polygon[1:] + polygon[:1]):
        if (a[1] > point[1]) != (b[1] > point[1]):
            cross_x = (b[0] - a[0]) * (point[1] - a[1]) / (b[1] - a[1]) + a[0]
            if point[0] < cross_x:
                inside = not inside
    edge = min(segment_distance(point, a, b)
               for a, b in zip(polygon, polygon[1:] + polygon[:1]))
    return inside, edge


def validate(corpus, *, image_root=ROOT, verify_images=True):
    schema = json.loads(SCHEMA_PATH.read_text())
    try:
        jsonschema.Draft202012Validator(schema, format_checker=jsonschema.FormatChecker()).validate(corpus)
    except jsonschema.ValidationError as error:
        raise ValueError(f"Invalid offline corpus schema: {error.message}") from error
    if corpus.get("schema_version") != 1 or not corpus.get("corpus_id"):
        raise ValueError("Expected named offline image corpus schema version 1")
    if not corpus.get("frames"):
        raise ValueError("Corpus must contain actual frames")
    frames, images, routes, sequences, last_time = set(), {}, {}, {}, {}
    for frame in corpus["frames"]:
        for key in ("frame_id", "sequence_id", "route_id", "captured_at", "image_path",
                    "image_sha256", "source", "split"):
            if not frame.get(key):
                raise ValueError(f"Frame missing {key}")
        fid = frame["frame_id"]
        if fid in frames:
            raise ValueError("Duplicate immutable frame identity")
        frames.add(fid)
        split = frame["split"]
        if split not in {"development", "held_out"}:
            raise ValueError("Split must be development or held_out")
        for grouping, key in ((routes, "route_id"), (sequences, "sequence_id")):
            if frame[key] in grouping and grouping[frame[key]] != split:
                raise ValueError(f"{key} leaks across splits")
            grouping[frame[key]] = split
        at = timestamp(frame["captured_at"])
        seq = frame["sequence_id"]
        if seq in last_time and at <= last_time[seq]:
            raise ValueError("Sequence capture times must strictly increase in corpus order")
        last_time[seq] = at
        sha = frame["image_sha256"]
        if len(sha) != 64 or any(c not in "0123456789abcdef" for c in sha):
            raise ValueError("Invalid image SHA-256")
        if sha in images:
            raise ValueError("Duplicate image bytes masquerade as a new observation")
        images[sha] = fid
        if verify_images:
            path = Path(frame["image_path"])
            path = path if path.is_absolute() else image_root / path
            if digest(path.read_bytes()) != sha:
                raise ValueError(f"Image hash mismatch: {fid}")
            from PIL import Image
            with Image.open(path) as image:
                dimensions = image.size
                if image.getexif().get(274) in (5, 6, 7, 8):
                    dimensions = dimensions[::-1]
                if dimensions != (frame["width"], frame["height"]):
                    raise ValueError(f"Image dimensions mismatch: {fid}")
        geometry = frame.get("geometry", {})
        roads = geometry.get("roads", [])
        ids = [road["road_id"] for road in roads]
        if len(ids) != len(set(ids)) or geometry.get("current_road_id") not in ids:
            raise ValueError("Roads need unique identities including current road")
        margin = geometry.get("uncertainty_margin", CONFIG["minimum_separation"])
        if not finite_unit(margin):
            raise ValueError("Invalid geometry uncertainty margin")
        for road in roads:
            poly = road["polygon"]
            if len(poly) < 3 or any(len(p) != 2 or not all(map(finite_unit, p)) for p in poly):
                raise ValueError("Invalid normalized road polygon")
            area = sum(a[0] * b[1] - b[0] * a[1]
                       for a, b in zip(poly, poly[1:] + poly[:1]))
            if abs(area) < 1e-8:
                raise ValueError("Degenerate road polygon")
        signs = frame.get("signs", [])
        if len({sign["sign_id"] for sign in signs}) != len(signs):
            raise ValueError("Duplicate sign in frame")
        track_ids = [s["track_id"] for s in signs if s.get("track_verified")]
        if len(track_ids) != len(set(track_ids)) or any(not x for x in track_ids):
            raise ValueError("Verified physical track must be unique within frame")
        for sign in signs:
            if sign.get("expected_applicability") not in {"ego", "other", "unknown"}:
                raise ValueError("Expected applicability must be explicitly labeled")
            box = sign["box"]
            if len(box) != 4 or not all(map(finite_unit, box)) or box[2] <= 0 or box[3] <= 0:
                raise ValueError("Invalid normalized sign box")
            if box[0] + box[2] > 1.000001 or box[1] + box[3] > 1.000001:
                raise ValueError("Sign box extends beyond image")
            anchor = sign.get("ground_anchor")
            if anchor is not None:
                if not all(finite_unit(anchor.get(k)) for k in ("x", "y", "uncertainty_radius")):
                    raise ValueError("Invalid ground anchor")
                if anchor.get("reliable") and anchor.get("source") not in {
                        "visible_post_base", "reviewed_support_projection"}:
                    raise ValueError("Reliable anchor requires visible support provenance")
    return {"frames": len(frames), "images": len(images), "routes": len(routes),
            "sequences": len(sequences), "image_hashes_verified": verify_images,
            "route_and_sequence_split_leakage": False}


def assign_road(geometry, sign):
    """No expected_* labels are used. Image-space relation, not metric 3-D."""
    if not geometry.get("reviewed"):
        return None, "geometry_not_reviewed"
    roads = [r for r in geometry["roads"] if r.get("direction_compatible", True)]
    # A manually supplied arrow→road relation is already a relation answer.
    # Retain it in the corpus for review but do not count it as inferred geometry.
    anchor = sign.get("ground_anchor")
    if not anchor or not anchor.get("reliable"):
        return None, "missing_reliable_ground_anchor"
    margin = max(CONFIG["minimum_separation"], geometry.get("uncertainty_margin", 0))
    radius = anchor["uncertainty_radius"]
    if radius > CONFIG["max_anchor_distance"]:
        return None, "anchor_uncertainty_too_large"
    distances, containing = [], []
    for road in roads:
        inside, edge = polygon_distance((anchor["x"], anchor["y"]), road["polygon"])
        distances.append((0 if inside else edge, road["road_id"]))
        if inside:
            containing.append((road["road_id"], edge))
    if len(containing) > 1:
        return None, "overlapping_road_polygons"
    if containing:
        road_id, clearance = containing[0]
        if clearance <= radius + margin:
            return None, "anchor_overlaps_road_boundary"
        competitors = [distance for distance, identity in distances if identity != road_id]
        if competitors and min(competitors) <= 2 * radius + margin:
            return None, "competing_road_within_uncertainty"
        return road_id, "anchor_inside_unique_road"
    distances.sort()
    if not distances or distances[0][0] + radius > CONFIG["max_anchor_distance"]:
        return None, "anchor_too_far_from_reviewed_roads"
    if len(distances) > 1 and distances[1][0] - distances[0][0] <= 2 * radius + margin:
        return None, "nearest_road_ambiguous"
    return distances[0][1], "anchor_near_unique_road_edge"


def classify(road_id, frame):
    if road_id is None:
        return "unknown"
    if road_id == frame["geometry"]["current_road_id"]:
        return "ego"
    topology = frame.get("topology", {})
    if topology.get("directed_branch_available") and road_id in topology.get("branch_road_ids", []):
        return "other"
    return "unknown"


def predict(corpus):
    rows, tracks = [], {}
    timing_eligible = {}
    for frame in corpus["frames"]:
        sequence = frame["sequence_id"]
        timing_eligible[sequence] = timing_eligible.get(sequence, True) and frame.get(
            "temporal_tracking_eligible", False)
    for frame in corpus["frames"]:
        at = timestamp(frame["captured_at"])
        topology = frame.get("topology", {})
        geometry = frame["geometry"]
        map_limit = topology.get("map_limit_kmh") or 0
        scope = (frame["route_id"], frame["sequence_id"], frame["split"],
                 geometry["current_road_id"])
        compatible_roads = {road["road_id"] for road in geometry["roads"]
                            if road.get("direction_compatible", True)}
        # Invalidate from every observed road-context frame, even when the sign
        # is temporarily absent. A later reappearance cannot resurrect evidence
        # that contradicted the intervening direction, road set, or ego scope.
        for cached_key, (_, cached_road) in list(tracks.items()):
            if cached_key[:3] == scope[:3] and (
                    cached_key[:4] != scope or not geometry.get("reviewed")
                    or cached_road not in compatible_roads
                    or classify(cached_road, frame) == "unknown"):
                del tracks[cached_key]
        for sign in frame.get("signs", []):
            x, _, width, _ = sign["box"]
            value = sign.get("value_kmh")
            baseline_unavailable = ("unsupported_panorama_projection"
                                    if frame.get("projection") == "equirectangular"
                                    else "numeric_speed_not_readable"
                                    if value is None else "historical_guard_context_unavailable"
                                    if not frame.get("legacy_evaluation_eligible", False) else None)
            legacy_reject = (topology.get("motorway")
                             and map_limit >= 100
                             and type(value) in (int, float) and 30 <= value <= 90
                             and value < map_limit and x + width / 2 >= .6
                             and topology.get("legacy_branch_available")
                             and topology.get("legacy_road_context_fresh"))
            road, reason = assign_road(geometry, sign)
            outcome = classify(road, frame)
            track_outcome, track_reason = outcome, reason
            key = scope + (sign.get("track_id"),)
            if sign.get("track_verified") and timing_eligible[frame["sequence_id"]]:
                previous = tracks.get(key)
                if outcome != "unknown":
                    tracks[key] = (at, road)
                elif reason == "missing_reliable_ground_anchor" and previous:
                    previous_at, previous_road = previous
                    if 0 < at - previous_at <= CONFIG["max_track_gap_ms"] * 1000:
                        track_outcome = classify(previous_road, frame)
                        if track_outcome != "unknown":
                            track_reason = "past_verified_track_assignment"
                elif reason != "missing_reliable_ground_anchor":
                    tracks.pop(key, None)
            elif sign.get("track_verified") and outcome == "unknown":
                track_reason = "temporal_cadence_not_verified"
            rows.append({"frame_id": frame["frame_id"], "sign_id": sign["sign_id"],
                         "sequence_id": frame["sequence_id"], "route_id": frame["route_id"],
                         "split": frame["split"], "captured_at": frame["captured_at"],
                         "track_id": sign.get("track_id"),
                         "temporal_tracking_eligible": timing_eligible[frame["sequence_id"]],
                         "projection": frame.get("projection", "rectilinear"),
                         "legacy_fixed_x_approximation": (
                             "not_evaluated" if baseline_unavailable
                             else "other" if legacy_reject else "ego"),
                         "legacy_reason": baseline_unavailable or "simplified_still_box_guard",
                         "reviewed_geometry": outcome, "geometry_reason": reason,
                         "assigned_road_id": road, "reviewed_geometry_and_track": track_outcome,
                         "track_reason": track_reason})
    return rows


def score(corpus, predictions):
    labels = {(f["frame_id"], s["sign_id"]): s["expected_applicability"]
              for f in corpus["frames"] for s in f.get("signs", [])}
    reports = {}
    for stage in ("legacy_fixed_x_approximation", "reviewed_geometry", "reviewed_geometry_and_track"):
        fields = ["observations", "legitimate_sign_rejections", "wrong_road_admissions",
                  "unresolved_ego_signs", "unresolved_other_signs"]
        fields += [f"{kind}_{value}" for kind in ("truth", "output")
                   for value in ("ego", "other", "unknown")]
        fields += ["output_not_evaluated"]
        fields += [f"truth_{truth}__output_{output}" for truth in ("ego", "other", "unknown")
                   for output in ("ego", "other", "unknown", "not_evaluated")]
        splits = defaultdict(lambda: Counter({key: 0 for key in fields}))
        for row in predictions:
            truth, output = labels[(row["frame_id"], row["sign_id"])], row[stage]
            for split in ("all", row["split"], f"projection:{row['projection']}"):
                counts = splits[split]
                counts["observations"] += 1
                counts[f"truth_{truth}"] += 1
                counts[f"output_{output}"] += 1
                counts[f"truth_{truth}__output_{output}"] += 1
                if truth == "ego" and output == "other":
                    counts["legitimate_sign_rejections"] += 1
                if truth == "other" and output == "ego":
                    counts["wrong_road_admissions"] += 1
                if truth in {"ego", "other"} and output == "unknown":
                    counts[f"unresolved_{truth}_signs"] += 1
        reports[stage] = {name: dict(sorted(counts.items())) for name, counts in splits.items()}
    return reports


def run(corpus_paths, *, image_root=ROOT, verify_images=True):
    frames, sources = [], []
    for corpus_path in corpus_paths:
        path = Path(corpus_path)
        raw = path.read_bytes()
        corpus = json.loads(raw)
        validate(corpus, image_root=image_root, verify_images=verify_images)
        frames.extend(corpus["frames"])
        sources.append({"path": str(path), "sha256": digest(raw), "corpus_id": corpus["corpus_id"],
                        "review": corpus.get("review", {}), "limitations": corpus.get("limitations", [])})
    frames.sort(key=lambda f: (f["sequence_id"], timestamp(f["captured_at"])))
    corpus = {"schema_version": 1, "corpus_id": "combined-offline-review", "frames": frames}
    checks = validate(corpus, image_root=image_root, verify_images=verify_images)
    predictions = predict(corpus)
    signs = [(f, s) for f in frames for s in f["signs"]]
    physical_tracks = {(f["route_id"], f["sequence_id"], s["track_id"])
                       for f, s in signs if s.get("track_verified")}
    coverage = {"sign_observations": len(signs),
                "verified_physical_tracks": len(physical_tracks),
                "untracked_sign_observations": sum(not s.get("track_verified", False) for f, s in signs),
                "reliable_ground_anchor_observations": sum(bool((s.get("ground_anchor") or {}).get("reliable"))
                                                           for f, s in signs),
                "geometry_reasons": dict(sorted(Counter(r["geometry_reason"] for r in predictions).items())),
                "track_reuses": sum(r["track_reason"] == "past_verified_track_assignment" for r in predictions)}
    return {"schema_version": 1, "experiment": "reviewed-image-road-geometry-ablation",
            "configuration": CONFIG, "runner_sha256": digest(Path(__file__).read_bytes()),
            "corpus_schema_sha256": digest(SCHEMA_PATH.read_bytes()),
            "corpora": sources, "validation": checks, "coverage": coverage,
            "stages": score(corpus, predictions),
            "predictions": predictions,
            "frame_provenance": [{"frame_id": f["frame_id"], "captured_at": f["captured_at"],
                                  "image_sha256": f["image_sha256"], "source": f["source"],
                                  "projection": f.get("projection", "rectilinear"),
                                  "temporal_tracking_eligible": f.get("temporal_tracking_eligible", False),
                                  "topology": f.get("topology", {}),
                                  "annotation_sha256": digest(canonical(f))} for f in frames],
            "limitations": [
                "Manually reviewed image geometry: an attribution upper-bound experiment, not learned-model accuracy.",
                "Fixed-x baseline is a simplified counterfactual on still-image boxes, not native live replay.",
                "Expected labels are separate from the geometry assignment and used only for scoring.",
                "No behavior features or learned lane estimates run; no incremental benefit is claimed for them.",
                "Manually supplied arrow-to-road relations are retained as annotations and never used as inferred predictions.",
                "Verified tracks may reuse only past assignments within 2500 ms in sequences explicitly marked as genuine cadence; sparse stills do not create confirmations.",
                "Original timestamp strings and microsecond ordering are preserved; normalized or unknown cadence disables temporal carry.",
                "Image-space road proximity is not a metric 3-D estimate or proof of legal applicability.",
                "Raw equirectangular panoramas have no comparable fixed-x baseline; projection groups are reported separately.",
                "Small manually reviewed corpus cannot establish field accuracy, mobile latency, or deployment readiness."]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("corpora", nargs="+", type=Path)
    parser.add_argument("--image-root", type=Path, default=ROOT)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    report = run(args.corpora, image_root=args.image_root)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n")
    fields = ("observations", "wrong_road_admissions", "legitimate_sign_rejections",
              "unresolved_ego_signs", "unresolved_other_signs", "output_not_evaluated")
    print(json.dumps({"output": str(args.output), "validation": report["validation"],
                      "coverage": report["coverage"],
                      "stages": {name: {field: counts["all"][field] for field in fields}
                                 for name, counts in report["stages"].items()}}, indent=2))


if __name__ == "__main__":
    main()
