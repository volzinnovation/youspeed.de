#!/usr/bin/env python3
"""Prepare a pinned A2D2 semantic sample and score native paint-support diagnostics.

Each annotated still is an independent cold-start sequence. This is neither an
ego-lane benchmark nor temporal validation. Labels never enter native inference.
The downloaded source manifest must contain pairs[] and SHA-bound objects[].
"""
import argparse
import hashlib
import json
from pathlib import Path

import cv2
import numpy as np


PAINT_RGB = ((255, 193, 37), (128, 0, 255))  # Official solid/dashed line classes.


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def sample_indices(width, height):
    scale = min(384 / width, 216 / height, 1)
    w, h = round(width * scale), round(height * scale)
    if min(w, h) < 64:
        raise ValueError("Image is too small for the native replay contract")
    xs = np.minimum(width - 1, ((np.arange(w) + .5) * width / w).astype(int))
    ys = np.minimum(height - 1, ((np.arange(h) + .5) * height / h).astype(int))
    return xs, ys


def paint_mask(label_bgr):
    result = np.zeros(label_bgr.shape[:2], np.uint8)
    for rgb in PAINT_RGB:
        result[np.all(label_bgr == np.array(rgb[::-1], np.uint8), axis=2)] = 1
    return result


def prepare(source_manifest, output):
    data = json.loads(source_manifest.read_text())
    objects = {item["key"]: item for item in data["objects"]}
    frames, targets = [], []
    if output.exists():
        raise ValueError("Output directory already exists")
    # Verify every selected image and label before producing model inputs.
    for pair in data["pairs"]:
        for key in ("rgb", "label"):
            obj = objects[pair[key]]
            if sha(obj["local_path"]) != obj["sha256"]:
                raise ValueError(f"Source hash mismatch: {pair[key]}")
    output.mkdir(parents=True)
    for i, pair in enumerate(data["pairs"]):
        rgb_obj, label_obj = objects[pair["rgb"]], objects[pair["label"]]
        bgr = cv2.imread(rgb_obj["local_path"], cv2.IMREAD_COLOR)
        label = cv2.imread(label_obj["local_path"], cv2.IMREAD_COLOR)
        if bgr is None or label is None or bgr.shape != label.shape:
            raise ValueError("RGB and semantic label shapes must match")
        height, width = bgr.shape[:2]
        xs, ys = sample_indices(width, height)
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)[np.ix_(ys, xs)]
        # Reduce class occupancy with area pooling rather than losing thin paint
        # through nearest-neighbour categorical sampling. Original label retained.
        original_mask = paint_mask(label)
        occupancy = cv2.resize(original_mask.astype(np.float32), (len(xs), len(ys)),
                               interpolation=cv2.INTER_AREA)
        fid = f"a2d2-{i:03d}"
        gray_path, mask_path = output / f"{fid}.gray", output / f"{fid}-paint.png"
        gray_path.write_bytes(gray.tobytes())
        if not cv2.imwrite(str(mask_path), (occupancy > 0).astype(np.uint8) * 255):
            raise OSError("Could not save semantic target")
        frame = dict(id=fid, sequenceId=fid, time=0.0, source=rgb_obj["local_path"],
                     grayPath=str(gray_path.resolve()), graySha256=sha(gray_path),
                     width=len(xs), height=len(ys), decodedWidth=width,
                     decodedHeight=height, split=pair.get("split", "external-development"),
                     sceneTags=["a2d2", "independent-still", pair["sequence"]])
        frames.append(frame)
        targets.append(dict(id=fid, captureGroup=pair["sequence"], split=frame["split"],
                            imagePath=rgb_obj["local_path"], imageSha256=rgb_obj["sha256"],
                            labelPath=label_obj["local_path"], labelSha256=label_obj["sha256"],
                            paintMaskPath=str(mask_path.resolve()), paintMaskSha256=sha(mask_path),
                            inputSha256=sha(gray_path), width=len(xs), height=len(ys)))
    (output / "manifest.json").write_text(json.dumps(dict(schemaVersion=1, frames=frames), indent=2) + "\n")
    (output / "targets.json").write_text(json.dumps(dict(
        schemaVersion=1, sourceManifestSha256=sha(source_manifest), targets=targets,
        classes={"solid_line": PAINT_RGB[0], "dashed_line": PAINT_RGB[1]},
        transform="Aligned distorted original RGB/labels; full image, aspect preserved; BGR-to-gray center sampling; any-area label occupancy",
        qualification="Small externally annotated sample; source split assignments are preserved. Cold-start stills, no invented video chronology. Recording-date separation does not establish unseen routes. No ego-lane instance or visibility/passage truth.",
        license="A2D2 CC BY-ND 4.0; source/attribution retained outside repository; derived artifacts are local only."), indent=2) + "\n")
    return dict(images=len(frames), manifest=str(output / "manifest.json"))


def rasterize(boundaries, width, height, field):
    mask = np.zeros((height, width), np.uint8)
    for boundary in boundaries:
        if boundary.get("cue") != "paint":
            continue
        segments = boundary.get("observedSegments", []) if field == "observed" else [boundary["points"]]
        for segment in segments:
            points = np.array([[round(x * (width - 1)), round(y * (height - 1))] for x, y in segment], np.int32)
            if len(points) >= 2:
                cv2.polylines(mask, [points], False, 1, 1)
    return mask


def counts(prediction, truth, radius=2, y_range=(.58, .95)):
    h, w = truth.shape
    roi = np.zeros((h, w), bool)
    roi[round(y_range[0] * (h - 1)):round(y_range[1] * (h - 1)) + 1] = True
    p, t = prediction.astype(bool) & roi, truth.astype(bool) & roi
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1, 2 * radius + 1))
    td = cv2.dilate(t.astype(np.uint8), kernel).astype(bool)
    pd = cv2.dilate(p.astype(np.uint8), kernel).astype(bool)
    return dict(predictedCenterlinePixels=int(p.sum()), supportedCenterlinePixels=int((p & td).sum()),
                annotatedPaintPixels=int(t.sum()), coveredPaintPixels=int((t & pd).sum()))


def with_rates(values):
    return dict(**values,
                centerlineSupportPrecision=values["supportedCenterlinePixels"] / values["predictedCenterlinePixels"] if values["predictedCenterlinePixels"] else None,
                annotatedPaintCoverage=values["coveredPaintPixels"] / values["annotatedPaintPixels"] if values["annotatedPaintPixels"] else None)


def replay_splits(rows, normalized_path):
    """Native NDJSON omits splits; bind them to its normalized input by ID and hash."""
    if all("split" in row for row in rows):
        return {row["id"]: row["split"] for row in rows}
    normalized = json.loads(normalized_path.read_text())["frames"]
    byid = {row["id"]: row for row in normalized}
    if len(byid) != len(normalized) or set(byid) != {row["id"] for row in rows}:
        raise ValueError("Normalized replay input IDs differ")
    for row in rows:
        source = byid[row["id"]]
        if (source["graySha256"] != row["inputSha256"] or source["sequenceId"] != row["sequenceId"]
                or source["time"] != row["time"] or ("split" in row and row["split"] != source["split"])):
            raise ValueError("Normalized replay input identity/hash/split differs")
    return {fid: row["split"] for fid, row in byid.items()}


def score(target_file, replay_file, output, radius=2):
    if output.exists():
        raise ValueError("Score output already exists")
    target_data = json.loads(target_file.read_text())
    rows = [json.loads(line) for line in replay_file.read_text().splitlines() if line.strip()]
    byid = {row["id"]: row for row in rows}
    if len(byid) != len(rows) or set(byid) != {t["id"] for t in target_data["targets"]}:
        raise ValueError("Replay and target frame IDs must match exactly")
    normalized_path = replay_file.parent / "input.normalized.json"
    splits = replay_splits(rows, normalized_path) if any("split" in t for t in target_data["targets"]) else {}
    arms = {}
    for field in ("geometry", "observed"):
        records = []
        for target in target_data["targets"]:
            row = byid[target["id"]]
            if row.get("sequenceId") != target["id"] or row.get("time") != 0.0:
                raise ValueError("Each independent still must be replayed at time zero in its own sequence")
            if "split" in target and splits[row["id"]] != target["split"]:
                raise ValueError("Replay changed the source split")
            if row["inputSha256"] != target["inputSha256"] or sha(target["paintMaskPath"]) != target["paintMaskSha256"]:
                raise ValueError("Input/target bytes changed")
            truth = cv2.imread(target["paintMaskPath"], cv2.IMREAD_GRAYSCALE) > 0
            if truth.shape != (row["height"], row["width"]):
                raise ValueError("Replay and semantic target dimensions differ")
            pred = rasterize(row["rawBoundaries"], row["width"], row["height"], field)
            records.append(dict(id=row["id"], captureGroup=target["captureGroup"], split=target.get("split", "external-development"),
                                **with_rates(counts(pred, truth, radius))))
        keys = ("predictedCenterlinePixels", "supportedCenterlinePixels", "annotatedPaintPixels", "coveredPaintPixels")
        arms[field] = dict(total=with_rates({k: sum(r[k] for r in records) for k in keys}), frames=records)
    result = dict(schemaVersion=1, images=len(rows), targetsSha256=sha(target_file), replaySha256=sha(replay_file),
                  toleranceAnalysisPixels=radius, evaluationYRange=[.58, .95], arms=arms,
                  predictionScope="Cold-start pre-presentation, post-temporal native geometry; not published overlay performance. Geometry arm draws fitted curves; observed arm uses explicit paint segments only.",
                  qualification="Paint-support precision and coverage diagnostics; not instance lane F1, official A2D2 metric, ego-lane recall, future-teacher validation or device timing. Small selected sample with source split preserved; no uncertainty claim.")
    if splits and any("split" not in row for row in rows):
        result["splitBinding"] = dict(normalizedInput=str(normalized_path), sha256=sha(normalized_path),
                                      matchingFields=["id", "sequenceId", "time", "inputSha256/graySha256"])
    output.write_text(json.dumps(result, indent=2) + "\n")
    return dict(images=len(rows), **{k: v["total"] for k, v in arms.items()})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prep = sub.add_parser("prepare")
    prep.add_argument("--source-manifest", type=Path, required=True)
    prep.add_argument("--output-dir", type=Path, required=True)
    scoring = sub.add_parser("score")
    scoring.add_argument("--targets", type=Path, required=True)
    scoring.add_argument("--replay", type=Path, required=True)
    scoring.add_argument("--output", type=Path, required=True)
    scoring.add_argument("--tolerance-pixels", type=int, choices=range(0, 6), default=2)
    args = parser.parse_args()
    result = prepare(args.source_manifest, args.output_dir) if args.command == "prepare" else score(args.targets, args.replay, args.output, args.tolerance_pixels)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
