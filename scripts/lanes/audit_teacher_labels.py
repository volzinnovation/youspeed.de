#!/usr/bin/env python3
"""Audit weak teacher points against bound development reviews; never edit labels.

Sparse ego-border support is not independent paint precision. Dense negative
intervals are scored separately. Contact sheets are automatic QA, not annotation.
"""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path

import cv2
import numpy as np


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def unique(items, name):
    result = {r["id"]: r for r in items}
    if len(result) != len(items):
        raise ValueError("Duplicate " + name + " frame ID")
    return result


def finite(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def y_range(value):
    if not isinstance(value, list) or len(value) != 2 or not all(finite(v) for v in value) or not 0 <= value[0] < value[1] <= 1:
        raise ValueError("Invalid evaluation Y range")
    return value


def x_at(points, y):
    for a, b in zip(points, points[1:]):
        if a[1] <= y <= b[1] and b[1] > a[1]:
            return a[0] + (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1])
    return None


def validate_geometry(points):
    if not isinstance(points, list) or len(points) < 2 or any(
            not isinstance(p, list) or len(p) != 2 or not all(finite(v) and 0 <= v <= 1 for v in p) for p in points):
        raise ValueError("Invalid reviewed geometry")
    if any(b[1] <= a[1] for a, b in zip(points, points[1:])):
        raise ValueError("Reviewed geometry must increase in Y")


def classify(point, label, settings):
    x, y = point
    lo, hi = label["evaluationYRange"]
    if not lo <= y <= hi:
        return "outsideEvaluationRange"
    # Match legacy point-support semantics: ignored geometry takes precedence.
    for region in label.get("ignoreGeometry", []):
        q = x_at(region["points"], y)
        if q is not None and abs(q - x) <= region["tolerance"]:
            return "ignoredGeometry"
    for border in label["borders"]:
        q = x_at(border["geometry"], y)
        if q is not None and abs(q - x) <= settings["paintToleranceX"] and any(
                a - settings["paintEndpointToleranceY"] <= y <= b + settings["paintEndpointToleranceY"]
                for a, b in border["paintedYIntervals"]):
            return "supportedByReviewedBorder"
    return "unsupportedByReviewedBorders"


def bind_label(label, row):
    for key in ("id", "sequenceId", "split", "inputSha256"):
        if key not in label or label[key] != row[key]:
            raise ValueError("Reviewed label binding mismatch: " + key + ": " + row["id"])
    if not finite(label.get("time")) or abs(label["time"] - row["time"]) > 1e-6:
        raise ValueError("Reviewed label time mismatch: " + row["id"])
    y_range(label["evaluationYRange"])
    for border in label["borders"]:
        validate_geometry(border["geometry"])
        for interval in border["paintedYIntervals"]:
            y_range(interval)
    for region in label.get("ignoreGeometry", []):
        validate_geometry(region["points"])
        if not finite(region["tolerance"]) or not 0 <= region["tolerance"] <= 1:
            raise ValueError("Invalid ignore geometry tolerance")


def load_teacher(directory):
    paths = {name: directory / name for name in ("metadata.json", "annotations.ndjson", "student-inputs.json")}
    metadata = json.loads(paths["metadata.json"].read_text())
    inputs_data = json.loads(paths["student-inputs.json"].read_text())
    rows = [json.loads(line) for line in paths["annotations.ndjson"].read_text().splitlines() if line.strip()]
    byid, inputs = unique(rows, "teacher"), unique(inputs_data["frames"], "input")
    if not rows or set(byid) != set(inputs):
        raise ValueError("Teacher/input IDs must match exactly and be nonempty")
    if (directory / "summary.json").exists():
        summary = json.loads((directory / "summary.json").read_text())
        for name, path in paths.items():
            if summary.get("artifacts", {}).get(name) != sha(path):
                raise ValueError("Teacher summary artifact hash mismatch: " + name)
    images = {}
    for row in rows:
        frame = inputs[row["id"]]
        for key in ("id", "sequenceId", "split", "time", "width", "height"):
            if key not in frame or row[key] != frame[key]:
                raise ValueError("Teacher/input alignment mismatch: " + key)
        if not finite(row["time"]):
            raise ValueError("Invalid teacher timestamp")
        w, h = row["width"], row["height"]
        if type(w) is not int or type(h) is not int or not 2 <= w <= 384 or not 2 <= h <= 216:
            raise ValueError("Invalid analysis dimensions")
        gray_path = Path(frame["grayPath"])
        if not gray_path.is_absolute():
            gray_path = directory / gray_path
        content = gray_path.read_bytes()
        digest = hashlib.sha256(content).hexdigest()
        if len(content) != w*h or digest != frame["graySha256"] or digest != row["inputSha256"]:
            raise ValueError("Teacher input bytes/hash mismatch: " + row["id"])
        images[row["id"]] = np.frombuffer(content, np.uint8).reshape(h, w)
        mask_path = (directory / row["maskPath"]).resolve()
        if directory.resolve() not in mask_path.parents or sha(mask_path) != row["maskSha256"]:
            raise ValueError("Teacher mask path/hash mismatch: " + row["id"])
        mask = cv2.imread(str(mask_path), cv2.IMREAD_UNCHANGED)
        if mask is None or mask.shape != (h, w) or not np.isin(mask, [0, 1]).all():
            raise ValueError("Teacher mask must contain only 0 unknown / 1 positive")
        declared = np.zeros((h, w), np.uint8)
        seen = set()
        for p in row["positivePoints"]:
            x, y = p["pixel"]
            if type(x) is not int or type(y) is not int or not 0 <= x < w or not 0 <= y < h or (x, y) in seen:
                raise ValueError("Invalid/duplicate teacher point pixel")
            seen.add((x, y))
            if len(p["point"]) != 2 or any(not finite(v) for v in p["point"]) or not np.allclose(p["point"], [x/(w-1), y/(h-1)], atol=1e-9, rtol=0):
                raise ValueError("Teacher point coordinate mismatch")
            source_ids = p["sourceFrameIds"]
            if len(source_ids) != len(set(source_ids)) or not source_ids or any(i not in byid for i in source_ids):
                raise ValueError("Invalid teacher support frame IDs")
            for sid in source_ids:
                if any(byid[sid][k] != row[k] for k in ("sequenceId", "split", "width", "height")):
                    raise ValueError("Teacher support crosses identity boundary")
            future = sum(byid[sid]["time"] > row["time"] for sid in source_ids)
            if future != p["futureSupportCount"] or (metadata.get("usesFutureFrames") is False and future):
                raise ValueError("Teacher future-support metadata mismatch")
            declared[y, x] = 1
        if not np.array_equal(mask, declared) or row["negativePixelCount"] != 0 or row["unknownPixelCount"] != w*h-len(seen):
            raise ValueError("Teacher mask/declared points disagree")
        for source in row.get("supportSources", []):
            sid = source["id"]
            if sid not in byid or source["inputSha256"] != byid[sid]["inputSha256"] or source["time"] != byid[sid]["time"]:
                raise ValueError("Teacher support source binding mismatch")
    return rows, images, metadata, {name: sha(path) for name, path in paths.items()}


def negative_scores(rows, labels):
    byid, seen = unique(rows, "teacher"), set()
    records, intervals = [], []
    for interval in labels["intervals"]:
        lo, hi = y_range(interval["evaluationYRange"])
        start, end = interval["startSeconds"], interval["endSeconds"]
        if not finite(start) or not finite(end) or start >= end:
            raise ValueError("Invalid negative interval bounds")
        ids = interval["frameIDs"]
        if not ids or len(ids) != len(set(ids)) or any(fid in seen or fid not in byid for fid in ids):
            raise ValueError("Missing/duplicate/overlapping negative frame IDs")
        seen.update(ids)
        ordered = [byid[fid] for fid in ids]
        if any(b["time"] <= a["time"] for a, b in zip(ordered, ordered[1:])):
            raise ValueError("Negative frames must increase in time")
        local, run, longest = [], 0., 0.
        for i, row in enumerate(ordered):
            if row["sequenceId"] != interval["sequenceId"] or not start <= row["time"] < end or row["inputSha256"] != interval["inputSha256"].get(row["id"]):
                raise ValueError("Negative interval identity/hash mismatch: " + row["id"])
            next_time = ordered[i+1]["time"] if i+1 < len(ordered) else end
            dt = min(.2, max(0., min(next_time, end)-row["time"]))
            n = sum(lo <= p["point"][1] <= hi for p in row["positivePoints"])
            if i and row["time"] - ordered[i-1]["time"] > .2 + 1e-9:
                run = 0.
            run = run + dt if n else 0.
            longest = max(longest, run)
            local.append(dict(id=row["id"], sequenceId=row["sequenceId"], time=row["time"],
                              candidatePointsInNegativeROI=n, attributedDurationSeconds=dt,
                              positiveDurationSeconds=dt if n else 0., evaluationYRange=[lo, hi]))
        records.extend(local)
        intervals.append(dict(sequenceId=interval["sequenceId"], startSeconds=start, endSeconds=end,
                              longestPositiveRunSeconds=longest, scoredFrames=len(local),
                              framesWithCandidatePoints=sum(r["candidatePointsInNegativeROI"] > 0 for r in local),
                              reviewedSampleDurationSeconds=sum(r["attributedDurationSeconds"] for r in local),
                              candidatePositiveDurationSeconds=sum(r["positiveDurationSeconds"] for r in local)))
    return dict(scoredFrames=len(records), framesWithCandidatePoints=sum(r["candidatePointsInNegativeROI"] > 0 for r in records),
                candidatePointsInNegativeROI=sum(r["candidatePointsInNegativeROI"] for r in records),
                reviewedSampleDurationSeconds=sum(r["attributedDurationSeconds"] for r in records),
                candidatePositiveDurationSeconds=sum(r["positiveDurationSeconds"] for r in records),
                longestPositiveRunSeconds=max((r["longestPositiveRunSeconds"] for r in intervals), default=0.),
                durationDefinition="Per-sample state held until the next reviewed sample or interval end, capped at 0.2 s. Gaps reset runs; no claim about intervening sensor exposures.",
                qualification=labels["qualification"], intervals=intervals, frames=records)


def select_diverse(ranked, byid, maximum=4):
    chosen = []
    for fid in ranked:
        if any(byid[fid]["sequenceId"] == byid[other]["sequenceId"] and abs(byid[fid]["time"]-byid[other]["time"]) < .5 for other in chosen):
            continue
        chosen.append(fid)
        if len(chosen) == maximum:
            break
    return chosen


def contact_sheet(path, selected, byid, images, labels, settings, negatives, title):
    if not selected:
        return None
    width, height, header = 384, 216, 54
    sheet = np.full((len(selected)*(height+header)+38, width*2, 3), 24, np.uint8)
    cv2.putText(sheet, title, (8, 16), cv2.FONT_HERSHEY_SIMPLEX, .44, (255, 255, 255), 1)
    cv2.putText(sheet, 'Green=supported Red=unsupported/negative Yellow=ignored/outside Cyan=unreviewed', (8, 32), cv2.FONT_HERSHEY_SIMPLEX, .35, (220, 220, 220), 1)
    for i, fid in enumerate(selected):
        row, image = byid[fid], images[fid]
        h, w = image.shape
        plain = cv2.cvtColor(image, cv2.COLOR_GRAY2BGR)
        marked = plain.copy()
        label = labels.get(fid)
        for point in row["positivePoints"]:
            status = classify(point["point"], label, settings) if label else "unreviewed"
            if fid in negatives and negatives[fid]["evaluationYRange"][0] <= point["point"][1] <= negatives[fid]["evaluationYRange"][1]:
                status = "negative"
            color = (0, 220, 0) if status == "supportedByReviewedBorder" else (0, 0, 255) if status in ("unsupportedByReviewedBorders", "negative") else (0, 255, 255) if status != "unreviewed" else (255, 255, 0)
            cv2.circle(marked, tuple(point["pixel"]), 1, color, -1)
        roi = negatives[fid]["evaluationYRange"] if fid in negatives else label["evaluationYRange"] if label else None
        if roi:
            for y in roi:
                cv2.line(marked, (0, round(y*(h-1))), (w-1, round(y*(h-1))), (120, 120, 0), 1)
        y0 = 38+i*(height+header)
        max_support = max((len(p["sourceFrameIds"]) for p in row["positivePoints"]), default=0)
        text = f'{fid} t={row["time"]:.2f} points={len(row["positivePoints"])} maxSources={max_support}'
        cv2.putText(sheet, text, (8, y0+17), cv2.FONT_HERSHEY_SIMPLEX, .40, (255,255,255), 1)
        cv2.putText(sheet, 'Plain target gray                         Candidate pixels (radius 1 for visibility)', (8, y0+36), cv2.FONT_HERSHEY_SIMPLEX, .39, (220,220,220), 1)
        sheet[y0+header:y0+header+h, :w] = plain
        sheet[y0+header:y0+header+h, width:width+w] = marked
    if not cv2.imwrite(str(path), sheet):
        raise OSError("Failed to write QA sheet")
    return dict(path=str(path.resolve()), sha256=sha(path), selectedFrameIds=selected)


def run(teacher_dir, labels_path, negative_path, output):
    if output.exists():
        raise ValueError("Output directory exists; choose a new external directory")
    rows, images, metadata, hashes = load_teacher(teacher_dir)
    byid = unique(rows, "teacher")
    settings = json.loads(labels_path.read_text())
    for key in ("paintToleranceX", "paintEndpointToleranceY"):
        if not finite(settings.get(key)) or not 0 <= settings[key] <= 1:
            raise ValueError("Invalid reviewed tolerance: " + key)
    labels = unique(settings["frames"], "reviewed label")
    if not set(labels) <= set(byid):
        raise ValueError("Reviewed label IDs missing from teacher")
    scores, classes = [], {}
    names = ("supportedByReviewedBorder", "unsupportedByReviewedBorders", "ignoredGeometry", "outsideEvaluationRange")
    for fid, label in labels.items():
        row = byid[fid]
        bind_label(label, row)
        count = Counter(classify(p["point"], label, settings) for p in row["positivePoints"])
        values = {key: count[key] for key in names}
        scores.append(dict(id=fid, sequenceId=row["sequenceId"], time=row["time"], candidatePoints=len(row["positivePoints"]), **values))
        classes[fid] = values
    totals = {key: sum(s[key] for s in scores) for key in ("candidatePoints", *names)}
    scored = totals["supportedByReviewedBorder"] + totals["unsupportedByReviewedBorders"]
    totals.update(labelledFrames=len(scores), framesWithCandidatePoints=sum(s["candidatePoints"] > 0 for s in scores),
                  reviewedBorderSupportFraction=totals["supportedByReviewedBorder"] / scored if scored else None)
    negative = negative_scores(rows, json.loads(negative_path.read_text()))
    negbyid = {r["id"]: r for r in negative["frames"]}
    positive_rows = [r for r in rows if r["positivePoints"]]
    selected = {
        "known-negative": select_diverse([r["id"] for r in sorted(negative["frames"], key=lambda r: (-r["candidatePointsInNegativeROI"], r["id"])) if r["candidatePointsInNegativeROI"]], byid),
        "review-supported": select_diverse([r["id"] for r in sorted(scores, key=lambda r: (-r["supportedByReviewedBorder"], r["id"])) if r["supportedByReviewedBorder"]], byid),
        "highest-consensus": select_diverse([r["id"] for r in sorted(positive_rows, key=lambda r: (-max(len(p["sourceFrameIds"]) for p in r["positivePoints"]), -len(r["positivePoints"]), r["id"]))], byid),
    }
    output.mkdir(parents=True, exist_ok=False)
    sheets = {}
    for name, ids in selected.items():
        artifact = contact_sheet(output/(name+'.png'), ids, byid, images, labels, settings, negbyid, name + ' - automatic QA; no manual adjudication')
        if artifact:
            sheets[name] = artifact
    result = dict(schemaVersion=1, teacherDir=str(teacher_dir.resolve()), teacherSourceMode=metadata.get("sourceMode"),
                  teacherUsesFuture=metadata.get("usesFutureFrames"), teacherInputHashes=hashes,
                  labelsSha256=sha(labels_path), negativeIntervalsSha256=sha(negative_path), codeSha256=sha(__file__),
                  sparseReviewed=dict(total=totals, frames=scores, paintToleranceX=settings["paintToleranceX"], paintEndpointToleranceY=settings["paintEndpointToleranceY"],
                    qualification="Approximate reviewed ego-border geometry/paint support on previously inspected development keyframes. Unsupported means absent from reviewed ego borders, not necessarily nonpaint. Ignore regions and outside-Y points excluded. Not independent paint precision; correlated points are not independent samples."),
                  denseNegative=negative, contactSheets=sheets,
                  qualification="Automatic QA only. Does not create or change annotations. Sparse labels do not establish duration or unseen-lane truth. No confidence intervals or held-out acceptance claim.")
    write_json(output/'audit.json', result)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--teacher-dir', type=Path, required=True)
    parser.add_argument('--labels', type=Path, required=True)
    parser.add_argument('--negative-intervals', type=Path, required=True)
    parser.add_argument('--output-dir', type=Path, required=True)
    args = parser.parse_args()
    try:
        report = run(args.teacher_dir, args.labels, args.negative_intervals, args.output_dir)
    except (ValueError, KeyError, OSError) as error:
        parser.error(str(error))
    print(json.dumps(dict(output=str(args.output_dir.resolve()), sparseReviewed=report['sparseReviewed']['total'],
                          denseNegative={k:v for k,v in report['denseNegative'].items() if k not in ('frames','intervals')},
                          contactSheets=report['contactSheets']), indent=2))


if __name__ == '__main__':
    main()
