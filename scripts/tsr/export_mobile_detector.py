#!/usr/bin/env python3
"""Convert the pinned SGBlur checkpoint to a fixed 1024-square mobile detector.

Run in the pinned Core ML/LiteRT conversion environments; this does not modify
the checkpoint or any server inference configuration.
"""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

SOURCE_SHA256 = "698a70566938d25c3c1eaa49b89fc176fe2f3a20631a9a01fa56035613c7972a"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--format", required=True, choices=("coreml", "tflite"))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    digest = hashlib.sha256(args.model.read_bytes()).hexdigest()
    if digest != SOURCE_SHA256:
        raise ValueError("The detector checkpoint does not match the pinned SGBlur source")
    args.output.mkdir(parents=True, exist_ok=True)
    checkpoint = args.output / "yolo11n_panoramax.pt"
    shutil.copy2(args.model, checkpoint)
    from ultralytics import YOLO
    import ultralytics
    import torch
    model = YOLO(str(checkpoint))
    exported = model.export(format=args.format, imgsz=1024, batch=1, half=True,
        nms=args.format == "coreml", device="cpu")
    report = dict(schema_version=1, source_checkpoint_sha256=digest, image_size=1024,
        format=args.format, artifact_path=str(exported), ultralytics=ultralytics.__version__,
        torch=torch.__version__, configuration=dict(imgsz=1024, batch=1, half=True,
            nms=args.format == "coreml", device="cpu"))
    (args.output / "mobile-detector-export.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
