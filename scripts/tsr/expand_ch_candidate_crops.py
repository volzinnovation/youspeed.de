#!/usr/bin/env python3
"""Expand the CH proposal queue with a lower-threshold detector pass."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--crop-dir", type=Path, default=None)
    parser.add_argument("--device", default="0")
    parser.add_argument("--imgsz", type=int, default=1280)
    parser.add_argument("--confidence", type=float, default=0.05)
    parser.add_argument("--batch", type=int, default=8)
    parser.add_argument("--max-candidates", type=int, default=30000)
    args = parser.parse_args()
    output = args.output or args.run / "candidates-lowconf.jsonl"
    crop_dir = args.crop_dir or args.run / "crops-lowconf"
    queue = read_jsonl(args.run / "download-queue.jsonl")
    for row in queue:
        row["image_path"] = row.get("image_path") or f"images/{row['id']}.jpg"
    rows = [row for row in queue if (args.run / row["image_path"]).is_file()]

    from PIL import Image
    from ultralytics import YOLO

    model = YOLO(str(args.model))
    crop_dir.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with output.open("w", encoding="utf-8") as handle:
        for start in range(0, len(rows), args.batch):
            batch_rows = rows[start : start + args.batch]
            paths = [args.run / row["image_path"] for row in batch_rows]
            results = model([str(path) for path in paths], device=args.device, imgsz=args.imgsz, conf=args.confidence, verbose=False)
            for row, path, result in zip(batch_rows, paths, results):
                with Image.open(path) as image:
                    image = image.convert("RGB")
                    width, height = image.size
                    boxes = getattr(result, "boxes", None)
                    if boxes is None:
                        continue
                    for index, box in enumerate(boxes):
                        if count >= args.max_candidates:
                            print(json.dumps({"candidate_count": count, "truncated": True}, sort_keys=True))
                            return 0
                        class_id = int(box.cls.item())
                        class_name = str(result.names.get(class_id, class_id))
                        if class_name != "sign":
                            continue
                        confidence = float(box.conf.item())
                        x1, y1, x2, y2 = (float(value) for value in box.xyxy[0].tolist())
                        pad_x = max(4, int((x2 - x1) * 0.15))
                        pad_y = max(4, int((y2 - y1) * 0.15))
                        crop_box = (max(0, int(x1) - pad_x), max(0, int(y1) - pad_y), min(width, int(x2) + pad_x), min(height, int(y2) + pad_y))
                        candidate_id = f"{row['id']}-lowconf-{index}"
                        crop_path = crop_dir / f"{candidate_id}.jpg"
                        image.crop(crop_box).save(crop_path, format="JPEG", quality=95)
                        handle.write(json.dumps({
                            "candidate_id": candidate_id,
                            "picture_id": row["id"],
                            "collection": row["collection"],
                            "coordinates": row.get("coordinates"),
                            "datetime": row.get("datetime"),
                            "providers": row.get("providers", []),
                            "license": row.get("license"),
                            "source_item_url": row.get("source_item_url"),
                            "source_instance_url": row.get("source_instance_url"),
                            "image_url": row.get("image_url"),
                            "image_path": row["image_path"],
                            "crop_path": str(crop_path.relative_to(args.run)),
                            "detector": {"model": str(args.model), "class": class_name, "confidence": confidence, "xyxy": [x1, y1, x2, y2], "padding_ratio": 0.15, "proposal_threshold": args.confidence},
                            "label_status": "unreviewed_ch_candidate_lowconf_detector",
                        }, ensure_ascii=False) + "\n")
                        count += 1
    print(json.dumps({"candidate_count": count, "truncated": False}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
