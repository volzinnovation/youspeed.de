#!/usr/bin/env python3
"""Probe a traced classifier path when the native Ultralytics Core ML converter fails."""

from __future__ import annotations

import argparse
from pathlib import Path

import coremltools as ct
import torch
from ultralytics import YOLO


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    model = YOLO(str(args.model)).model.float().eval()
    example = torch.zeros(1, 3, 224, 224, dtype=torch.float32)
    with torch.no_grad():
        eager = model(example)
    print("eager_type", type(eager), "eager_shape", getattr(eager, "shape", None))
    traced = torch.jit.trace(model, example, strict=False)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    converted = ct.convert(
        traced,
        source="pytorch",
        convert_to="mlprogram",
        inputs=[
            ct.ImageType(
                name="images",
                shape=(1, 3, 224, 224),
                color_layout=ct.colorlayout.RGB,
                scale=1 / 255.0,
            )
        ],
        compute_precision=ct.precision.FLOAT16,
    )
    converted.save(str(args.output))
    print("saved", args.output)


if __name__ == "__main__":
    main()
