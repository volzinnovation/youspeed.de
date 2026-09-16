#!/usr/bin/env python3
"""Compare one ONNX classifier output with its LiteRT/TFLite sibling."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import onnxruntime as ort
import tensorflow as tf


def run_onnx(model: Path, image: np.ndarray) -> np.ndarray:
    session = ort.InferenceSession(str(model), providers=["CPUExecutionProvider"])
    name = session.get_inputs()[0].name
    output = session.run(None, {name: image.transpose(0, 3, 1, 2)})[0]
    return np.asarray(output, dtype=np.float32)


def run_tflite(model: Path, image: np.ndarray) -> np.ndarray:
    interpreter = tf.lite.Interpreter(model_path=str(model), num_threads=4)
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()[0]
    output_details = interpreter.get_output_details()[0]
    interpreter.set_tensor(input_details["index"], image.astype(input_details["dtype"]))
    interpreter.invoke()
    return np.asarray(interpreter.get_tensor(output_details["index"]), dtype=np.float32)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--country", required=True)
    parser.add_argument("--onnx", type=Path, required=True)
    parser.add_argument("--tflite", type=Path, required=True)
    parser.add_argument("--input-rgb", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    raw = np.fromfile(args.input_rgb, dtype=np.uint8)
    expected = 224 * 224 * 3
    if raw.size != expected:
        raise ValueError(f"expected {expected} RGB bytes, received {raw.size}")
    # The shared Android encoder writes RGB float32 values scaled by 1/255.
    # Ultralytics' ONNX export and its LiteRT sibling both expect that tensor;
    # Core ML is probed separately with the raw pixel buffer because its image
    # input includes the equivalent scale operation in the compiled graph.
    image = raw.reshape(1, 224, 224, 3).astype(np.float32) / 255.0
    reference = run_onnx(args.onnx, image)
    converted = run_tflite(args.tflite, image)
    difference = np.abs(reference - converted)
    report = {
        "schema_version": 1,
        "country": args.country,
        "input": {
            "path": str(args.input_rgb),
            "sha256": __import__("hashlib").sha256(args.input_rgb.read_bytes()).hexdigest(),
            "shape_nhwc": [1, 224, 224, 3],
            "source_dtype": "uint8",
            "tensor_dtype": "float32",
            "scale": "1/255",
        },
        "reference": {"format": "onnx", "path": str(args.onnx)},
        "converted": {"format": "litert", "path": str(args.tflite)},
        "output_shape": list(reference.shape),
        "reference_scores": reference[0].tolist(),
        "converted_scores": converted[0].tolist(),
        "max_abs_difference": float(difference.max()),
        "mean_abs_difference": float(difference.mean()),
        "top1_reference": int(reference.argmax(axis=-1)[0]),
        "top1_converted": int(converted.argmax(axis=-1)[0]),
        "passed": bool(np.array_equal(reference.argmax(axis=-1), converted.argmax(axis=-1)) and difference.max() <= 0.02),
        "tolerance": 0.02,
    }
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, sort_keys=True))


if __name__ == "__main__":
    main()
