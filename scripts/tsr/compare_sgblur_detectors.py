#!/usr/bin/env python3
"""Compare pinned SGBlur detectors on existing learning/validation images.

This is an exploratory known-box check, not a release acceptance test. Reserved
images are excluded. Partial annotations cannot establish precision or mAP.
Run with Ultralytics 8.4.56 and Torch 2.7.0 in an isolated environment.
"""
import argparse
import hashlib
import json
import platform
import statistics
import time
from pathlib import Path


CHECKPOINTS = {
    "yolo11n": "698a70566938d25c3c1eaa49b89fc176fe2f3a20631a9a01fa56035613c7972a",
    "yolo26s": "86e2380d9dd13541280f74fac9e416618a4cdd1541ada02ae93d103195c524be",
}
SIZE = 1024


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def overlap(a, b):
    intersection = max(0, min(a[2], b[2]) - max(a[0], b[0])) * max(
        0, min(a[3], b[3]) - max(a[1], b[1]))
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - intersection
    return intersection / union if union > 0 else 0


def prepare(image, boxes):
    """Match the mobile full-height, rightmost square with left padding."""
    from PIL import Image
    assert image.getexif().get(274, 1) == 1, "Registered GT requires upright source pixels"
    scale = SIZE / image.height
    scaled_width = round(image.width * scale)
    scaled = image.convert("RGB").resize((scaled_width, SIZE), Image.Resampling.BILINEAR)
    window = Image.new("RGB", (SIZE, SIZE), (114, 114, 114))
    offset = SIZE - scaled_width
    if offset < 0:
        window.paste(scaled.crop((-offset, 0, scaled_width, SIZE)))
    else:
        window.paste(scaled, (offset, 0))
    targets = []
    for box in boxes:
        if box["class_id"] != 0:
            continue
        x1, y1, x2, y2 = box["bbox_xyxy"]
        transformed = [x1 * scale + offset, y1 * scale, x2 * scale + offset, y2 * scale]
        # Exclude partially/fully cropped signs from the known-box denominator.
        if transformed[0] >= 0 and transformed[2] <= SIZE and transformed[1] >= 0 and transformed[3] <= SIZE:
            targets.append(transformed)
    return window, targets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--review", required=True, type=Path)
    parser.add_argument("--images-root", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    for key, path in (("yolo11n", args.baseline), ("yolo26s", args.candidate)):
        if sha(path) != CHECKPOINTS[key]:
            raise ValueError(f"Unexpected {key} checkpoint")
    if args.output.exists():
        raise FileExistsError("Use a fresh evidence output")
    import torch
    import ultralytics
    from ultralytics import YOLO
    from PIL import Image

    torch.set_num_threads(4)
    source = json.loads(args.review.read_text())
    frames = []
    for frame in source["frames"]:
        if frame["split"] not in ("train", "val"):
            continue
        path = args.images_root / frame["picture_id"] / "image.png"
        if sha(path) != frame["image_sha256"]:
            raise ValueError(f"Changed image {path}")
        with Image.open(path) as image:
            window, targets = prepare(image, frame["boxes"])
        frames.append((frame, window, targets))
    report = {
        "schema_version": 1,
        "purpose": "Exploratory known-box comparison on existing train/val images; reserved data excluded",
        "checkpoint_sha256": CHECKPOINTS,
        "review_sha256": sha(args.review),
        "script_sha256": sha(Path(__file__)),
        "environment": {"torch": torch.__version__, "ultralytics": ultralytics.__version__,
                        "platform": platform.platform(), "threads": 4, "device": "cpu"},
        "configuration": {"imgsz": SIZE, "rect": False, "conf": 0.25, "iou": 0.7, "max_det": 300,
                          "gt_match_iou": 0.5, "preprocessing": "full-height-rightmost-square-RGB-bilinear-left-pad114"},
        "limitations": ["13 existing learning/validation scenes, not an independent holdout",
                        "Assistant-reviewed partial boxes, not exhaustive human ground truth",
                        "Known-box recall only; no precision, mAP, face/plate or classifier assessment",
                        "Mac CPU timings do not establish iPhone/Android latency or thermal behavior",
                        "Pillow resize is an approximation of native app rendering; export parity is a separate check"],
        "arms": {},
    }
    for arm, path, end2end in (("yolo11n", args.baseline, False),
                              ("yolo26s_end2end", args.candidate, True),
                              ("yolo26s_one_to_many", args.candidate, False)):
        model = YOLO(path)
        parameters = sum(p.numel() for p in model.model.parameters())
        training_imgsz = model.ckpt["train_args"]["imgsz"]
        assert model.names == {0: "sign", 1: "plate", 2: "face"}
        model.model.end2end = end2end
        settings = dict(imgsz=SIZE, rect=False, conf=0.25, iou=0.7, max_det=300, device="cpu", verbose=False)
        for _ in range(3):
            model.predict(frames[0][1], **settings)
        rows, durations = [], []
        for frame, window, targets in frames:
            started = time.perf_counter()
            result = model.predict(window, **settings)[0]
            durations.append((time.perf_counter() - started) * 1000)
            boxes = result.boxes.data.cpu().tolist()
            signs = [b for b in boxes if int(b[5]) == 0]
            pairs = sorted(((overlap(t, b), i, j) for i, t in enumerate(targets)
                            for j, b in enumerate(signs)), reverse=True)
            used_targets, used_detections, matches = set(), set(), []
            for iou, i, j in pairs:
                if iou >= 0.5 and i not in used_targets and j not in used_detections:
                    used_targets.add(i)
                    used_detections.add(j)
                    matches.append({"target_index": i, "sign_index": j, "iou": iou})
            rows.append({"picture_id": frame["picture_id"], "source_split": frame["split"],
                         "image_sha256": frame["image_sha256"], "targets": targets,
                         "detections_xyxy_score_class": boxes, "matches": matches})
            print(f"{arm}: {len(rows)}/{len(frames)}", flush=True)
        # Repeated same-window measurements separate the size comparison from disk I/O.
        repeated_ms = []
        for _ in range(10):
            started = time.perf_counter()
            model.predict(frames[0][1], **settings)
            repeated_ms.append((time.perf_counter() - started) * 1000)
        known = sum(len(r["targets"]) for r in rows)
        matched = sum(len(r["matches"]) for r in rows)
        report["arms"][arm] = {"checkpoint_bytes": path.stat().st_size,
            "unfused_checkpoint_parameters": parameters, "training_imgsz": training_imgsz,
            "end2end": end2end, "frames": len(rows), "known_boxes": known,
            "matched_known_boxes": matched, "known_box_recall": matched / known if known else None,
            "mac_cpu_predict_median_ms": statistics.median(repeated_ms),
            "mac_cpu_predict_samples_ms": repeated_ms, "rows": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
    print(json.dumps({a: {k: v for k, v in r.items() if k not in ("rows", "mac_cpu_predict_samples_ms")}
                      for a, r in report["arms"].items()}, indent=2))


if __name__ == "__main__":
    main()
