#!/usr/bin/env python3
"""Qualify full shared LiteRT exports via ONNX using an existing verified trace.

Alternative to Google's Linux-only direct PyTorch converter. This bounded Mac
qualification uses pinned onnx2tf 1.20.0 with TensorFlow's legacy Keras frontend;
it never downloads calibration imagery or changes trained weights. It requires
the independent multi-image original/eager/trace checks from export_auxiliary_model.
"""
from __future__ import annotations

import argparse
from collections import Counter
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil

import numpy as np
import torch

if __package__:
    from . import export_auxiliary_model as export
else:
    import export_auxiliary_model as export

training = export.training


def bind_trace(qualification_dir, name):
    provenance = json.loads((qualification_dir / "artifact-sha256.json").read_text())
    entries = {row["path"]: row for row in provenance["files"]}
    filename = name + ".torchscript.pt"
    path = qualification_dir / filename
    if filename not in entries or training.sha256_file(path) != entries[filename]["sha256"]:
        raise ValueError("Source trace missing or SHA-256 mismatch")
    return path


def output_roles(details, shared, input_size=640):
    """Reject unknown layouts instead of silently guessing/transposing axes."""
    if input_size not in (640, 1280):
        raise ValueError("Only 640/1280 qualification shapes are supported")
    anchors = sum((input_size // stride) ** 2 for stride in (8, 16, 32))
    expected = {(1, 7, anchors): "detections"}
    if shared:
        expected[(1, input_size // 4, input_size // 4, 1)] = "lane_logits"
    if len(details) != len(expected):
        raise ValueError("Unexpected output count")
    result = {}
    for row in details:
        shape = tuple(int(x) for x in row["shape"])
        if shape not in expected or row["dtype"] != np.float32 or expected[shape] in result:
            raise ValueError("Unexpected or duplicate output shape/dtype")
        result[expected[shape]] = row["index"]
    return result


class LiteRTPredictor:
    def __init__(self, path, shared, input_size=640):
        import tensorflow as tf
        self.interpreter = tf.lite.Interpreter(model_path=str(path), num_threads=4)
        self.interpreter.allocate_tensors()
        inputs = self.interpreter.get_input_details()
        if len(inputs) != 1 or tuple(inputs[0]["shape"]) != (1, input_size, input_size, 3) or inputs[0]["dtype"] != np.float32:
            raise ValueError("Expected one NHWC float32 image input")
        self.input_index = inputs[0]["index"]
        self.roles = output_roles(self.interpreter.get_output_details(), shared, input_size)
        self.operators = Counter(op["op_name"] for op in self.interpreter._get_ops_details())

    def __call__(self, array):
        self.interpreter.set_tensor(self.input_index, array)
        self.interpreter.invoke()
        result = {name: self.interpreter.get_tensor(index) for name, index in self.roles.items()}
        if "lane_logits" in result:
            result["lane_logits"] = result["lane_logits"].transpose(0, 3, 1, 2)
        return result


def run(args):
    out = args.output_dir.resolve()
    if out == export.ROOT or export.ROOT in out.parents or out.exists():
        raise ValueError("Use a new external output directory")
    os.environ["TF_USE_LEGACY_KERAS"] = "1"
    import onnx
    import onnxruntime as ort
    from onnxsim import simplify
    import tensorflow as tf
    converter = importlib.import_module("onnx2tf.onnx2tf")
    required = {"onnx": "1.17.0", "onnxruntime": "1.19.2", "onnx2tf": "1.20.0",
                "onnxsim": "0.4.36", "tensorflow": "2.18.0"}
    for package, version in required.items():
        if importlib.metadata.version(package) != version:
            raise ValueError("Use pinned qualification dependency: " + package + "==" + version)
    previous = json.loads((args.qualification_dir / "summary.json").read_text())
    if previous.get("status") != "qualification_complete_production_deferred":
        raise ValueError("Require a completed independent original/eager/trace qualification")
    for kind in ("eagerChecks", "traceChecks"):
        if len(previous[kind]) < 2 or not all(row[k]["allclose"] for row in previous[kind] for k in ("detector", "lane", "baseline")):
            raise ValueError("Reference trace equivalence not verified")
    for path, digest in previous["sourceHashes"].items():
        if training.sha256_file(path) != digest:
            raise ValueError("Upstream qualification source changed: " + path)
    for path in (args.manifest, args.checkpoint):
        if str(path.resolve()) not in previous["sourceHashes"]:
            raise ValueError("Source was not bound by upstream qualification")
    traces = {name: bind_trace(args.qualification_dir, name) for name in ("baseline", "shared")}
    checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=True)
    provenance = export.validate_training_provenance(args.checkpoint, args.manifest,
        zod_manifest=getattr(args, "zod_manifest", None))
    if ((provenance["schema"] == "mixed-v1" or "trainingProvenance" in previous)
            and previous.get("trainingProvenance") != provenance):
        raise ValueError("Upstream qualification does not bind this training provenance")
    input_size = previous["inputSize"]
    samples = export.sample_validation(args.manifest, checkpoint["config"], args.samples, input_size)
    tf.config.threading.set_intra_op_parallelism_threads(4)
    tf.config.threading.set_inter_op_parallelism_threads(1)
    torch.set_num_threads(4)
    arrays = [np.ascontiguousarray(row["tensor"].numpy().transpose(0, 2, 3, 1)) for row in samples]
    out.mkdir(parents=True)
    shutil.copy2(__file__, out / Path(__file__).name)
    source_paths = [Path(__file__), Path(export.__file__), Path(training.__file__), args.manifest, args.checkpoint,
                    args.qualification_dir / "summary.json", args.qualification_dir / "artifact-sha256.json", *traces.values()]
    if getattr(args, "zod_manifest", None) is not None:
        source_paths.append(args.zod_manifest)
    hashes = {str(path.resolve()): training.sha256_file(path) for path in source_paths}
    report = dict(status="started", decision="DEFER_PRODUCTION", sourceHashes=hashes,
                  trainingProvenance=provenance, environment=required,
                  frames=len(samples), inputSize=input_size, trainingInputSize=checkpoint["config"]["inputSize"],
                  resolutionControlOnly=input_size != checkpoint["config"]["inputSize"], host=previous["host"], exports={},
                  sources=["https://github.com/PINTO0309/onnx2tf/tree/1.20.0",
                           "https://github.com/daquexian/onnx-simplifier",
                           "https://www.tensorflow.org/api_docs/python/tf/lite/Interpreter"],
                  qualification=["Shared complete whole-frame graph export; production uses a distinct TSR crop/full-scene contract.",
                                 "1280 is a numerical/cost control of weights trained at 640; no accuracy at 1280 is claimed.",
                                 "32 validation images check numerical parity, not recognition quality or independent acceptance.",
                                 "CPU XNNPACK on the Mac only; no Android delegate, device, thermal, memory or camera-to-overlay performance claim.",
                                 "FP16 LiteRT means weight storage reduction with CPU execution; it differs from Core ML float16 typed compute.",
                                 "No NMS, classifier, tracking or traffic-sign events are exported or evaluated."])
    try:
        sample_path = out / "verified-conversion-input.npy"
        np.save(sample_path, arrays[0], allow_pickle=False)
        # onnx2tf 1.20 downloads generic imagery even when a custom input is supplied.
        # Bind that helper to this verified input and restore it after conversion.
        original_download = converter.download_test_image_data
        converter.download_test_image_data = lambda: np.load(sample_path, allow_pickle=False)
        try:
            for name, trace_path in traces.items():
                model = torch.jit.load(str(trace_path)).eval()
                directory = out / name
                directory.mkdir()
                onnx_path = directory / (name + ".onnx")
                names = ["detections", "lane_logits"] if name == "shared" else ["detections"]
                with torch.inference_mode():
                    torch.onnx.export(model, samples[0]["tensor"], str(onnx_path), input_names=["image"],
                                      output_names=names, opset_version=17, dynamo=False)
                graph, valid = simplify(onnx.load(str(onnx_path)))
                if not valid:
                    raise ValueError("ONNX simplification check failed")
                onnx.save(graph, str(onnx_path))
                options = ort.SessionOptions(); options.intra_op_num_threads = 4
                session = ort.InferenceSession(str(onnx_path), sess_options=options, providers=["CPUExecutionProvider"])
                reference, checks = [], []
                with torch.inference_mode():
                    for row in samples:
                        values = model(row["tensor"])
                        values = values if isinstance(values, tuple) else (values,)
                        expected = {key: value.numpy() for key, value in zip(names, values)}
                        actual = session.run(names, {"image": row["tensor"].numpy()})
                        check = {key: export.compare_arrays(expected[key], value) for key, value in zip(names, actual)}
                        if not all(value["allclose"] for value in check.values()):
                            raise ValueError("ONNX failed multi-image trace equivalence")
                        checks.append(dict(key=row["key"], **check)); reference.append(expected)
                report[name + "OnnxChecks"] = checks
                converter.convert(input_onnx_file_path=str(onnx_path), output_folder_path=str(directory / "converted"),
                                  custom_input_op_name_np_data_path=[["image", str(sample_path)]],
                                  not_use_onnxsim=True, not_use_opname_auto_generate=True, non_verbose=True)
                for precision in ("float32", "float16"):
                    path = directory / "converted" / (name + "_" + precision + ".tflite")
                    predictor = LiteRTPredictor(path, name == "shared", input_size)
                    tolerance = dict(atol=1e-4, rtol=1e-4) if precision == "float32" else dict(atol=.05, rtol=.001)
                    checks, detections = [], []
                    for row, image, expected in zip(samples, arrays, reference):
                        output = predictor(image)
                        check = dict(key=row["key"], sha256=row["sha256"], detector=export.compare_detections(expected["detections"], output["detections"], **tolerance))
                        if name == "shared":
                            check["lane"] = export.compare_arrays(expected["lane_logits"], output["lane_logits"], **tolerance)
                            check["laneThresholdDisagreementPixels"] = int(np.count_nonzero((expected["lane_logits"] >= 0) != (output["lane_logits"] >= 0)))
                        checks.append(check); detections.append(output["detections"])
                    key = name + "-" + precision
                    np.savez_compressed(out / (key + "-detections.npz"), detections=np.stack(detections))
                    report["exports"][key] = dict(status="exported_and_host_checked", artifact=export.artifact(path),
                                                  checks=checks, operatorCounts=dict(predictor.operators),
                                                  requiresFlexOrCustom=any(op.startswith("Flex") or op == "CUSTOM" for op in predictor.operators),
                                                  allNumericalChecksPassed=all(row[k]["allclose"] for row in checks for k in (("detector", "lane") if name == "shared" else ("detector",))),
                                                  hostLatency=export.latency(predictor, arrays, repeats=args.repeats))
                    training.write_json(out / "summary.json", report)
        finally:
            converter.download_test_image_data = original_download
        for precision in ("float32", "float16"):
            a = np.load(out / ("baseline-" + precision + "-detections.npz"))["detections"]
            b = np.load(out / ("shared-" + precision + "-detections.npz"))["detections"]
            report["baselineVsShared-" + precision] = export.compare_arrays(a, b, atol=0, rtol=0)
        if any(training.sha256_file(path) != digest for path, digest in hashes.items()):
            raise ValueError("Source changed during qualification")
        report["status"] = "qualification_complete_production_deferred"
        training.write_json(out / "summary.json", report)
        training.write_json(out / "artifact-sha256.json", export.artifact(out))
        return report
    except BaseException as error:
        report.update(status="failed", error=repr(error))
        training.write_json(out / "summary.json", report)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--qualification-dir", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--zod-manifest", type=Path,
                        help="Exact original ZOD manifest required for mixed-experiment checkpoints; no ZOD images needed")
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=32)
    parser.add_argument("--repeats", type=int, default=32)
    args = parser.parse_args()
    if args.repeats < 2:
        parser.error("Require at least two timing samples")
    print(json.dumps(dict(status=run(args)["status"], output=str(args.output_dir))))


if __name__ == "__main__":
    main()
