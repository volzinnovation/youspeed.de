#!/usr/bin/env python3
"""Train an evaluation-only CH classifier from the route-aware crop dataset."""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--name", default="ch-classifier-bootstrap-v1")
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--batch", type=int, default=32)
    parser.add_argument("--imgsz", type=int, default=224)
    parser.add_argument("--device", default="0")
    parser.add_argument("--workers", type=int, default=8)
    args = parser.parse_args()
    if args.epochs <= 0 or args.batch <= 0 or args.imgsz <= 0:
        parser.error("epochs, batch, and imgsz must be positive")

    from ultralytics import YOLO

    model = YOLO(str(args.model))
    results = model.train(
        data=str(args.data),
        epochs=args.epochs,
        imgsz=args.imgsz,
        batch=args.batch,
        device=args.device,
        workers=args.workers,
        project=str(args.project),
        name=args.name,
        exist_ok=True,
        pretrained=True,
        patience=10,
        verbose=False,
    )
    output_dir = args.project / args.name
    summary = {
        "status": "evaluation_only",
        "data": str(args.data),
        "source_model": str(args.model),
        "output_dir": str(output_dir),
        "epochs": args.epochs,
        "batch": args.batch,
        "imgsz": args.imgsz,
        "device": args.device,
        "results": str(results) if results is not None else None,
        "best_checkpoint": str(output_dir / "weights" / "best.pt"),
    }
    (output_dir / "training-summary.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
