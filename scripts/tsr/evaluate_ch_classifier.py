#!/usr/bin/env python3
"""Evaluate a classifier on a folder-of-labels split without changing the dataset."""

from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--split", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--batch", type=int, default=32)
    parser.add_argument("--imgsz", type=int, default=224)
    parser.add_argument("--device", default="0")
    args = parser.parse_args()

    from ultralytics import YOLO

    model = YOLO(str(args.model))
    paths = sorted(
        path for path in args.split.rglob("*")
        if path.suffix.lower() in {".jpg", ".jpeg", ".png"}
    )
    if not paths:
        raise SystemExit(f"no images found below {args.split}")

    counts = Counter()
    correct_top1 = 0
    correct_top5 = 0
    per_class = defaultdict(lambda: {"samples": 0, "top1": 0, "top5": 0})
    for start in range(0, len(paths), args.batch):
        batch_paths = paths[start : start + args.batch]
        results = model.predict(
            source=[str(path) for path in batch_paths],
            imgsz=args.imgsz,
            device=args.device,
            batch=args.batch,
            verbose=False,
        )
        for path, result in zip(batch_paths, results):
            truth = path.parent.name
            probs = result.probs
            top5 = [str(model.names[index]) for index in probs.top5]
            top1 = top5[0]
            counts[truth] += 1
            per_class[truth]["samples"] += 1
            if top1 == truth:
                correct_top1 += 1
                per_class[truth]["top1"] += 1
            if truth in top5:
                correct_top5 += 1
                per_class[truth]["top5"] += 1

    summary = {
        "schema_version": 1,
        "status": "evaluation_only",
        "model": str(args.model),
        "split": str(args.split),
        "sample_count": len(paths),
        "class_count": len(counts),
        "top1": correct_top1 / len(paths),
        "top5": correct_top5 / len(paths),
        "class_counts": dict(sorted(counts.items())),
        "per_class": dict(sorted(per_class.items())),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
