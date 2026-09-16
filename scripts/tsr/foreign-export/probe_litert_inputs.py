#!/usr/bin/env python3
"""Probe LiteRT input preprocessing against an ONNX reference."""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import onnxruntime as ort
import tensorflow as tf


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--onnx", type=Path, required=True)
    parser.add_argument("--tflite", type=Path, required=True)
    parser.add_argument("--input-rgb", type=Path, required=True)
    args = parser.parse_args()

    raw = np.fromfile(args.input_rgb, dtype=np.uint8).reshape(1, 224, 224, 3)
    onnx_session = ort.InferenceSession(str(args.onnx), providers=["CPUExecutionProvider"])
    onnx_name = onnx_session.get_inputs()[0].name
    onnx_variants = {
        "raw_0_255": raw.astype(np.float32),
        "normalized_0_1": raw.astype(np.float32) / 255.0,
        "bgr_raw_0_255": raw[..., ::-1].astype(np.float32),
        "bgr_normalized_0_1": raw[..., ::-1].astype(np.float32) / 255.0,
    }
    onnx_outputs = {
        name: np.asarray(
            onnx_session.run(None, {onnx_name: image.transpose(0, 3, 1, 2)})[0],
            dtype=np.float32,
        )[0]
        for name, image in onnx_variants.items()
    }

    interpreter = tf.lite.Interpreter(model_path=str(args.tflite), num_threads=4)
    interpreter.allocate_tensors()
    input_details = interpreter.get_input_details()[0]
    output_details = interpreter.get_output_details()[0]
    variants = {
        "raw_0_255": raw.astype(np.float32),
        "normalized_0_1": raw.astype(np.float32) / 255.0,
        "bgr_raw_0_255": raw[..., ::-1].astype(np.float32),
        "bgr_normalized_0_1": raw[..., ::-1].astype(np.float32) / 255.0,
    }
    print({
        "input": {
            "shape": input_details["shape"].tolist(),
            "dtype": str(input_details["dtype"]),
            "quantization": input_details["quantization"],
        },
        "onnx": {
            name: {"top1": int(output.argmax()), "score": float(output.max())}
            for name, output in onnx_outputs.items()
        },
    })
    for name, image in variants.items():
        interpreter.set_tensor(input_details["index"], image.astype(input_details["dtype"]))
        interpreter.invoke()
        output = np.asarray(interpreter.get_tensor(output_details["index"]), dtype=np.float32)[0]
        difference = np.abs(onnx_outputs[name] - output)
        print({
            "variant": name,
            "top1": int(output.argmax()),
            "score": float(output.max()),
            "max_abs_difference": float(difference.max()),
            "mean_abs_difference": float(difference.mean()),
        })


if __name__ == "__main__":
    main()
