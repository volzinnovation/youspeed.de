#!/usr/bin/env python3
"""Score raw and published PAINT from native replay against frozen partial labels.

Reuses the existing score_response definition. Only explicit noPaintROI pixels
are negative labels; all other unlabelled responses remain unclassified.
Requires NumPy/OpenCV. Never changes annotations or production implementation.
"""
import argparse
from collections import defaultdict
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np
from compare_recorded_filters import input_path, score_response


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def poly(points, width, height):
    return np.array([[round(x * (width - 1)), round(y * (height - 1))] for x, y in points], np.int32)


def aggregate(records):
    target = sum(r.get("annotatedPaintPixels", 0) for r in records)
    covered = sum(r.get("coveredPaintPixels", 0) for r in records)
    negative = sum(r.get("noPaintRoiPixels", 0) for r in records)
    response = sum(r.get("falseResponsePixelsInNoPaintRoi", 0) for r in records)
    return dict(frames=len(records), annotatedPaintPixels=target, coveredPaintPixels=covered,
                annotatedPaintCoverage=covered / target if target else None,
                noPaintRoiPixels=negative, responsePixelsInNoPaintRoi=response,
                responseDensityInNoPaintRoi=response / negative if negative else None)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path, required=True)
    parser.add_argument("--annotations", type=Path, action="append", required=True)
    parser.add_argument("--input", type=Path, action="append", required=True, help="Pipeline frames.ndjson; repeat for each variant")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--tolerance", type=int, default=3)
    parser.add_argument("--render", action="store_true", help="Render all labelled RGB frames at 640x360 per panel")
    args = parser.parse_args()
    if args.output_dir.exists():
        parser.error("Output directory already exists; choose a new name")
    if not 0 <= args.tolerance <= 20:
        parser.error("Tolerance must be 0..20 analysis pixels")
    cv2.setNumThreads(1)
    dataset = json.loads(args.dataset.read_text())
    frames = {f["id"]: f for f in dataset["frames"]}
    if len(frames) != len(dataset["frames"]):
        parser.error("Duplicate dataset frame IDs")
    annotations = {}
    for path in args.annotations:
        for row in json.loads(path.read_text())["frames"]:
            if row["id"] in annotations or row["id"] not in frames:
                parser.error(f"Duplicate or unknown annotation: {row['id']}")
            annotations[row["id"]] = row
    predictions, variants = {}, []
    for path in args.input:
        for line in path.read_text().splitlines():
            row = json.loads(line)
            variant = row["variant"]
            if variant not in variants:
                variants.append(variant)
            fid = row.get("sourceFrameId") or row["id"]
            if (variant, fid) in predictions:
                parser.error(f"Duplicate prediction: {variant}/{fid}")
            predictions[variant, fid] = row
    for fid in annotations:
        frame = frames[fid]
        digest = sha(input_path(frame["grayPath"], args.dataset))
        for variant in variants:
            row = predictions.get((variant, fid))
            if row is None or row["inputSha256"] != digest:
                parser.error(f"Missing or wrong-pixel prediction: {variant}/{fid}")
            if (row["width"], row["height"]) != (frame["width"], frame["height"]):
                parser.error(f"Prediction geometry mismatch: {variant}/{fid}")
    args.output_dir.mkdir(parents=True, exist_ok=False)
    records = []
    for fid, annotation in annotations.items():
        frame = frames[fid]
        width, height = frame["width"], frame["height"]
        for variant in variants:
            row = predictions[variant, fid]
            for stage, field in (("raw", "rawBoundaries"), ("visible", "confirmedBoundaries")):
                mask = np.zeros((height, width), np.uint8)
                for boundary in row[field]:
                    if boundary["cue"].lower() == "paint":
                        for segment in boundary.get("segments", [boundary["points"]]):
                            if len(segment) >= 2:
                                cv2.polylines(mask, [poly(segment, width, height)], False, 255, 1)
                score = score_response(mask > 0, annotation, args.tolerance)
                records.append(dict(id=fid, variant=variant, stage=stage,
                                    condition=annotation.get("condition", "unspecified"),
                                    split=annotation.get("split", "unspecified"), **score))
    groups = defaultdict(list)
    conditions = defaultdict(list)
    splits = defaultdict(list)
    for row in records:
        groups[row["variant"], row["stage"]].append(row)
        conditions[row["variant"], row["stage"], row["condition"]].append(row)
        splits[row["variant"], row["stage"], row["split"]].append(row)
    overlays = []
    if args.render:
        folder = args.output_dir / "overlays"
        folder.mkdir()
        for fid, annotation in annotations.items():
            frame = frames[fid]
            if not frame.get("rgbPath"):
                raise ValueError(f"Cannot render without original RGB: {fid}")
            rgb = cv2.imread(str(input_path(frame["rgbPath"], args.dataset)))
            if rgb is None:
                raise ValueError(f"Cannot read original RGB: {fid}")
            rgb = cv2.resize(rgb, (640, 360), interpolation=cv2.INTER_AREA)

            def panel(label):
                image = cv2.copyMakeBorder(rgb.copy(), 36, 0, 0, 0, cv2.BORDER_CONSTANT, value=(24, 24, 24))
                cv2.putText(image, label, (8, 24), cv2.FONT_HERSHEY_SIMPLEX, .52, (255, 255, 255), 1, cv2.LINE_AA)
                return image

            original = panel(fid + "  manual paint / no-paint region")
            for boundary in annotation.get("boundaries", []):
                if boundary.get("kind", "paint") == "paint":
                    cv2.polylines(original[36:], [poly(boundary["points"], 640, 360)], False, (255, 0, 255), 2, cv2.LINE_AA)
            if annotation.get("noPaintROI"):
                cv2.polylines(original[36:], [poly(annotation["noPaintROI"], 640, 360)], True, (255, 255, 0), 1, cv2.LINE_AA)
            strips = []
            for stage, field in (("raw", "rawBoundaries"), ("visible", "confirmedBoundaries")):
                panels = [original.copy()]
                for variant in variants:
                    image = panel(f"{variant}  {stage} PAINT (green)")
                    for boundary in predictions[variant, fid][field]:
                        if boundary["cue"].lower() == "paint":
                            for segment in boundary.get("segments", [boundary["points"]]):
                                if len(segment) >= 2:
                                    cv2.polylines(image[36:], [poly(segment, 640, 360)], False, (0, 235, 0), 2, cv2.LINE_AA)
                    panels.append(image)
                strips.append(np.hstack(panels))
            destination = folder / (hashlib.sha256(fid.encode()).hexdigest()[:16] + ".jpg")
            if not cv2.imwrite(str(destination), np.vstack(strips), [cv2.IMWRITE_JPEG_QUALITY, 95]):
                raise RuntimeError(f"Could not render: {fid}")
            overlays.append(dict(id=fid, condition=annotation.get("condition"), path=str(destination.resolve())))
    report = dict(schemaVersion=1,
                  scope="Partial manual PAINT coverage; negatives only in explicit noPaintROI. Unlabelled responses are not treated as false positives.",
                  tolerancePixels=args.tolerance, annotationFrames=len(annotations),
                  inputHashes={str(p): sha(p) for p in (args.dataset, *args.annotations, *args.input, Path(__file__), Path(__file__).with_name("compare_recorded_filters.py"))},
                  summary=[dict(variant=v, stage=s, **aggregate(rows)) for (v, s), rows in groups.items()],
                  byCondition=[dict(variant=v, stage=s, condition=c, **aggregate(rows)) for (v, s, c), rows in conditions.items()],
                  bySplit=[dict(variant=v, stage=s, split=c, **aggregate(rows)) for (v, s, c), rows in splits.items()],
                  perFrame=records, overlays=overlays)
    output = args.output_dir / "scores.json"
    output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps(dict(output=str(output.resolve()), summary=report["summary"]), indent=2))


if __name__ == "__main__":
    main()
