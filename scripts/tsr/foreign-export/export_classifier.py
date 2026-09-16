#!/usr/bin/env python3
"""Export a Panoramax country classifier using the German classifier recipe."""

from __future__ import annotations

import argparse
import hashlib
import json
import platform
import shutil
from pathlib import Path

from ultralytics import YOLO


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--country", required=True, choices=("FR", "NL", "BE"))
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--format", required=True, choices=("coreml", "tflite"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    # Ultralytics writes the converted artifact beside the checkpoint stem;
    # copy the read-only mounted source into the writable evidence directory so
    # an export can never mutate or silently target the source mount.
    source_copy = args.output / f"{args.country.lower()}-source.pt"
    if not source_copy.exists():
        shutil.copy2(args.model, source_copy)
    model = YOLO(str(source_copy))
    export_path = model.export(
        format=args.format,
        imgsz=224,
        batch=1,
        half=True,
        nms=False,
        device="cpu",
        project=str(args.output),
        name=f"{args.country.lower()}-classifier",
        exist_ok=True,
    )
    export_path = Path(export_path)
    if not export_path.exists():
        raise RuntimeError(f"Ultralytics returned a missing export path: {export_path}")

    files = []
    for path in sorted(export_path.rglob("*")):
        if path.is_file():
            files.append({
                "path": str(path.relative_to(export_path)),
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            })
    report = {
        "schema_version": 1,
        "country": args.country,
        "format": args.format,
        "source_checkpoint_sha256": sha256_file(args.model),
        "source_checkpoint": str(args.model),
        "export_path": str(export_path),
        "files": files,
        "class_names": {str(k): v for k, v in model.names.items()},
        "exporter": {
            "ultralytics": __import__("ultralytics").__version__,
            "torch": __import__("torch").__version__,
            "python": platform.python_version(),
            "configuration": "imgsz=224,batch=1,half=true,nms=false,device=cpu",
        },
    }
    (args.output / f"{args.country.lower()}-{args.format}-export-report.json").write_text(
        json.dumps(report, indent=2) + "\n"
    )
    print(json.dumps({
        "country": args.country,
        "format": args.format,
        "export_path": str(export_path),
        "file_count": len(files),
        "source_checkpoint_sha256": report["source_checkpoint_sha256"],
    }, sort_keys=True))


if __name__ == "__main__":
    main()
