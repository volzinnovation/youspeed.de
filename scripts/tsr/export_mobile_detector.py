#!/usr/bin/env python3
"""Convert a pinned SGBlur checkpoint to a fixed 1024-square mobile detector.

Run in the pinned Core ML/LiteRT conversion environments; this does not modify
the checkpoint, bundled app packs or server inference configuration. YOLO26s
is an evaluation candidate and must be selected explicitly. Both platforms use
its one-to-many branch so their existing Vision/raw-YOLO contracts remain valid.
"""
import argparse
import hashlib
import json
import shutil
from pathlib import Path

SOURCE_SHA256 = "698a70566938d25c3c1eaa49b89fc176fe2f3a20631a9a01fa56035613c7972a"
DETECTORS = {
    "yolo11n": {
        "sha256": SOURCE_SHA256,
        "filename": "yolo11n_panoramax.pt",
        "source_uri": "https://github.com/cquest/sgblur/blob/169451970702aca0dde9ff3106dba0f67e0b88a8/models/yolo11n_panoramax.pt",
        "status": "bundled_baseline",
    },
    "yolo26s": {
        "sha256": "86e2380d9dd13541280f74fac9e416618a4cdd1541ada02ae93d103195c524be",
        "filename": "yolo26s_face_plate_sign.pt",
        "source_uri": "https://github.com/cquest/sgblur/blob/fa83262033b6addb9c8085caa5a0fd82d212f16a/models/yolo26s_face_plate_sign.pt",
        "status": "evaluation_candidate_not_accepted",
    },
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", required=True, type=Path)
    parser.add_argument("--detector", choices=tuple(DETECTORS), default="yolo11n")
    parser.add_argument("--format", required=True, choices=("coreml", "tflite"))
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    selected = DETECTORS[args.detector]
    digest = hashlib.sha256(args.model.read_bytes()).hexdigest()
    if digest != selected["sha256"]:
        raise ValueError("The detector checkpoint does not match the pinned SGBlur source")
    args.output.mkdir(parents=True, exist_ok=True)
    checkpoint = args.output / selected["filename"]
    if checkpoint.resolve() == args.model.resolve():
        raise ValueError("Export to a separate directory to preserve the source checkpoint")
    shutil.copy2(args.model, checkpoint)
    from ultralytics import YOLO
    import ultralytics
    import torch
    model = YOLO(str(checkpoint))
    if model.names != {0: "sign", 1: "plate", 2: "face"}:
        raise ValueError("The mobile detector requires sign/plate/face in that exact order")
    # Default YOLO26 end-to-end output is [1,300,6] (xyxy,score,class).
    # Android requires [1,7,21504] (xywh + three class scores), and iPhone
    # requires a Core ML NMS pipeline producing Vision recognized objects.
    # Explicitly select the same compatible branch on both platforms.
    model.model.end2end = False
    model.model.eval()
    with torch.inference_mode():
        raw = model.model(torch.zeros(1, 3, 1024, 1024))[0]
    raw_shape = list(raw.shape)
    if raw_shape != [1, 7, 21504]:
        raise ValueError(f"Unexpected mobile raw detector output: {raw_shape}")
    exported = model.export(format=args.format, imgsz=1024, batch=1, half=True,
        nms=args.format == "coreml", end2end=False, device="cpu")
    report = dict(schema_version=1, source_checkpoint_sha256=digest, image_size=1024,
        detector=args.detector, source_uri=selected["source_uri"], status=selected["status"],
        class_names=model.names, raw_output_shape=raw_shape,
        format=args.format, artifact_path=str(exported), ultralytics=ultralytics.__version__,
        torch=torch.__version__, configuration=dict(imgsz=1024, batch=1, half=True,
            nms=args.format == "coreml", end2end=False, device="cpu"))
    (args.output / "mobile-detector-export.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
