#!/usr/bin/env python3
"""Run the source Ultralytics classifier on the fixed parity input."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import torch
from ultralytics import YOLO


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--country", required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--input-rgb", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    raw = np.fromfile(args.input_rgb, dtype=np.uint8)
    if raw.size != 224 * 224 * 3:
        raise ValueError("input must contain exactly 224*224*3 RGB bytes")
    model = YOLO(str(args.model))
    model.model.eval()
    image = torch.from_numpy(raw.reshape(1, 224, 224, 3).transpose(0, 3, 1, 2).copy()).float() / 255.0
    with torch.inference_mode():
        output = model.model(image)
    if isinstance(output, (tuple, list)):
        output = output[0]
    scores = output.detach().cpu().numpy().astype(np.float32)[0]
    names = [model.names[index] for index in range(len(model.names))]
    report = {
        "schema_version": 1,
        "country": args.country,
        "model": str(args.model),
        "input_rgb": str(args.input_rgb),
        "scores": scores.tolist(),
        "class_names": names,
        "top_class": names[int(scores.argmax())],
        "top_score": float(scores.max()),
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("country", "top_class", "top_score")}, sort_keys=True))


if __name__ == "__main__":
    main()
