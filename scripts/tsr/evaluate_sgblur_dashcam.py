#!/usr/bin/env python3
"""Score a hash-bound, frozen source-only review against paired dashcam replays.

Only the preselected annotated frames have accuracy metrics. Counts on other
frames are descriptive. This evaluates sign proposals, not classification,
temporal application state, faces/plates, or phone runtime performance.
"""
import argparse
import hashlib
import json
import math
import statistics
from pathlib import Path

from compare_sgblur_detectors import CHECKPOINTS

ARMS = ("yolo11n", "yolo26s")


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def area(box):
    return max(0, box[2] - box[0]) * max(0, box[3] - box[1])


def intersection(a, b):
    return area([max(a[0], b[0]), max(a[1], b[1]),
                 min(a[2], b[2]), min(a[3], b[3])])


def iou(a, b):
    common = intersection(a, b)
    union = area(a) + area(b) - common
    return common / union if union else 0


def score_frame(label, boxes, threshold, confidence):
    targets = label["targets"]
    available = set(range(len(targets)))
    matched, false, ignored = [], [], []
    signs = sorted((b for b in boxes if int(b[5]) == 0 and b[4] >= confidence),
                   key=lambda b: -b[4])
    for box in signs:
        overlaps = [(iou(box, targets[j]["box"]), j) for j in sorted(available)]
        overlap, target = max(overlaps, default=(0, -1))
        if target >= 0 and overlap >= threshold:
            available.remove(target)
            matched.append({"target_index": target, "iou": overlap, "prediction": box})
            continue
        if min(box[2] - box[0], box[3] - box[1]) < 20:
            ignored.append({"prediction": box, "reason": "shorter edge below 20px"})
        elif any(intersection(box, region["box"]) / area(box) >= .5
                 for region in label["ignore_regions"]):
            ignored.append({"prediction": box, "reason": "explicit ignore region"})
        else:
            false.append(box)
    return {"tp": len(matched), "fn": len(available), "fp": len(false),
            "matched": matched, "missed_target_indices": sorted(available),
            "false_proposals": false, "ignored": ignored}


def aggregate(rows):
    tp, fn, fp = (sum(row[key] for row in rows) for key in ("tp", "fn", "fp"))
    return {"tp": tp, "fn": fn, "fp": fp,
            "precision": tp / (tp + fp) if tp + fp else None,
            "recall": tp / (tp + fn) if tp + fn else None,
            "f1": 2 * tp / (2 * tp + fn + fp) if 2 * tp + fn + fp else None,
            "frames_with_false_proposals": sum(row["fp"] > 0 for row in rows),
            "ignored_proposals": sum(len(row["ignored"]) for row in rows)}


def evaluate(labels_path, receipt_path, replay, plan_path, allow_partial=False):
    labels, receipt, plan = (json.loads(p.read_text())
                            for p in (labels_path, receipt_path, plan_path))
    if sha(labels_path) != receipt["label_sha256"]:
        raise ValueError("Frozen annotation hash mismatch")
    if receipt["model_predictions_inspected_before_freeze"]:
        raise ValueError("Labels were not frozen blind")
    metadata = json.loads((replay / "replay-metadata.json").read_text())
    configuration = metadata["configuration"]
    if (metadata["checkpoints"] != CHECKPOINTS or metadata["end2end"] is not False
            or configuration["imgsz"] != plan["input_size"]
            or configuration["conf"] != plan["confidence_threshold"]
            or configuration["iou"] != plan["nms_iou"]):
        raise ValueError("Replay model/configuration mismatch")
    plan_hash = hashlib.sha256(json.dumps(plan, sort_keys=True).encode()).hexdigest()
    if plan_hash != metadata["plan_sha256"]:
        raise ValueError("Replay plan mismatch")
    reference = replay / "blind-frames.json"
    if sha(reference) != receipt["source_image_reference_sha256"]:
        raise ValueError("Blind source image reference changed")
    source = {f["frame_id"]: f for f in json.loads(reference.read_text())["frames"]}
    label_map = {f["frame_id"]: f for f in labels["frames"]}
    expected_labels = {key for key, f in source.items() if f["scored_keyframe"]}
    if len(label_map) != len(labels["frames"]) or set(label_map) != expected_labels:
        raise ValueError("Labels must cover exactly the fixed scoring frames")
    if (len(label_map) != receipt["reviewed_frames"]
            or sum(len(f["targets"]) for f in label_map.values()) != receipt["targets"]):
        raise ValueError("Annotation count mismatch")
    predictions, completeness, latency = {}, [], {arm: [] for arm in ARMS}
    raw = {arm: {"sign_proposals": 0, "frames_with_sign_proposals": 0} for arm in ARMS}
    for movie in plan["movies"]:
        path = replay / (movie["id"] + ".predictions.ndjson")
        rows = [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
        expected = math.floor(movie["duration_seconds"] * plan["sampling_hz"])
        frame_ids = {f"{movie['id']}-{round(i / plan['sampling_hz'] * 1000):07d}"
                     for i in range(expected)}
        actual = {r["frame_id"] for r in rows}
        if len(actual) != len(rows) or not actual.issubset(frame_ids):
            raise ValueError("Duplicate or unexpected replay frames")
        complete = actual == frame_ids
        if not complete and not allow_partial:
            raise ValueError(f"Incomplete replay: {movie['id']} {len(rows)}/{expected}")
        steps = [b["decoder_pts_seconds"] - a["decoder_pts_seconds"]
                 for a, b in zip(rows, rows[1:])]
        errors = [abs(r["decoder_pts_seconds"] - r["requested_seconds"]) for r in rows]
        completeness.append({"movie_id": movie["id"], "frames": len(rows),
                             "expected_frames": expected, "complete": complete,
                             "decoder_pts_step_min_seconds": min(steps) if steps else None,
                             "decoder_pts_step_max_seconds": max(steps) if steps else None,
                             "nonpositive_decoder_pts_steps": sum(step <= 0 for step in steps),
                             "requested_pts_error_median_seconds": statistics.median(errors) if errors else None,
                             "requested_pts_error_max_seconds": max(errors) if errors else None})
        for row in rows:
            if row["movie_id"] != movie["id"]:
                raise ValueError("Movie identity mismatch")
            predictions[row["frame_id"]] = row
            for arm in ARMS:
                output = row["arms"][arm]
                latency[arm].append(output["predict_wall_ms"])
                count = sum(int(b[5]) == 0 for b in output["boxes_xyxy_score_class"])
                raw[arm]["sign_proposals"] += count
                raw[arm]["frames_with_sign_proposals"] += count > 0
    frame_results = []
    for identifier, label in label_map.items():
        if identifier not in predictions:
            if allow_partial:
                continue
            raise ValueError(f"Missing annotated frame: {identifier}")
        row, original = predictions[identifier], source[identifier]
        if not label["reviewed"]:
            raise ValueError("Unreviewed scoring frame")
        for key in ("window_rgb_sha256", "image_sha256"):
            if label[key] != original[key]:
                raise ValueError("Annotation/source mismatch")
        if sha(Path(original["image_path"])) != label["image_sha256"]:
            raise ValueError("Frozen source image changed")
        if row["window_rgb_sha256"] != label["window_rgb_sha256"]:
            raise ValueError("Scoring prediction used different pixels")
        results = {}
        for threshold in (.5, .3):
            results[str(threshold)] = {arm: score_frame(
                label, row["arms"][arm]["boxes_xyxy_score_class"], threshold,
                plan["confidence_threshold"]) for arm in ARMS}
        frame_results.append({"frame_id": identifier, "movie_id": label["movie_id"],
                              "targets": label["targets"], "scores": results})
    scores = {}
    for threshold in ("0.5", "0.3"):
        per_arm = {arm: aggregate([f["scores"][threshold][arm] for f in frame_results])
                   for arm in ARMS}
        paired = {"both": 0, "candidate_only": 0, "baseline_only": 0, "neither": 0}
        disagreements = []
        for frame in frame_results:
            hits = {arm: {m["target_index"] for m in frame["scores"][threshold][arm]["matched"]}
                    for arm in ARMS}
            for index, target in enumerate(frame["targets"]):
                a, b = (index in hits[arm] for arm in ARMS)
                key = "both" if a and b else "baseline_only" if a else "candidate_only" if b else "neither"
                paired[key] += 1
                if a != b:
                    disagreements.append({"frame_id": frame["frame_id"], "target_index": index,
                                          "target": target, "outcome": key})
        scores[threshold] = {"overall": per_arm, "paired_targets": paired,
                             "disagreements": disagreements,
                             "by_movie": {m["id"]: {arm: aggregate([
                                 f["scores"][threshold][arm] for f in frame_results
                                 if f["movie_id"] == m["id"]]) for arm in ARMS}
                                 for m in plan["movies"]}}
    timing = {arm: {"samples": len(values), "median_ms": statistics.median(values),
                    "p95_ms": sorted(values)[math.ceil(.95 * len(values)) - 1]}
              for arm, values in latency.items() if values}
    return {"schema_version": 1, "complete": all(m["complete"] for m in completeness),
            "annotation_sha256": sha(labels_path), "freeze_receipt": receipt,
            "evaluator_sha256": sha(Path(__file__)), "replay_metadata": metadata,
            "replay_prediction_sha256": {m["id"]: sha(replay / (m["id"] + ".predictions.ndjson"))
                                         for m in plan["movies"]
                                         if (replay / (m["id"] + ".predictions.ndjson")).exists()},
            "completeness": completeness, "reviewed_frames": len(frame_results),
            "reviewed_targets": sum(len(f["targets"]) for f in frame_results),
            "scores": scores, "predict_wall_time": timing,
            "all_frame_raw_counts_not_accuracy": raw, "frames": frame_results,
            "limitations": ["Assistant labels, not independent human ground truth",
                            "Only fixed 30-second frames labeled; correlated video samples",
                            "Only recognizable sign faces >=20px in fixed mobile window",
                            "No classifier/OCR/state-machine, face/plate or phone-performance acceptance"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--freeze-receipt", type=Path, required=True)
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--replay", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--allow-partial", action="store_true", help="Diagnostic use only; output is marked incomplete")
    args = parser.parse_args()
    result = evaluate(args.labels, args.freeze_receipt, args.replay, args.plan, args.allow_partial)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + "\n")
    print(json.dumps({key: result[key] for key in ("complete", "reviewed_frames", "reviewed_targets", "predict_wall_time")}, indent=2))
    print(json.dumps(result["scores"]["0.5"]["overall"], indent=2))


if __name__ == "__main__":
    main()
