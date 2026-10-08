#!/usr/bin/env python3
"""Export a frozen P2/P3 backbone prefix plus the same trained paint head.

This lane-only full-field control measures a separate invocation while retaining
shipping cropped TSR. It must match the complete detector's P2/P3 head logits
before export. No model fitting, app integration or mobile performance claim.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
import importlib
import importlib.metadata
import json
import os
from pathlib import Path
import platform
import shutil

import cv2
import numpy as np
import torch
from torch import nn

if __package__:
    from . import export_auxiliary_model as export
else:
    import export_auxiliary_model as export

training = export.training


class FrozenLanePrefix(nn.Module):
    """Copy only the detector modules through the highest required feature tap."""
    def __init__(self, detector, head, feature_layers=(2, 4)):
        super().__init__()
        if len(feature_layers) != 2 or len(set(feature_layers)) != 2 or not all(
                0 <= layer < len(detector.model) - 1 for layer in feature_layers):
            raise ValueError("Require two distinct feature taps before the detector output")
        if any(module._forward_hooks for module in detector.modules()):
            raise ValueError("Remove source feature hooks before building a traceable prefix")
        self.layers = nn.ModuleList(copy.deepcopy(list(detector.model[:max(feature_layers) + 1])))
        self.head = copy.deepcopy(head)
        self.feature_layers = tuple(feature_layers)
        self.save = frozenset(detector.save)
        self.eval()
        for parameter in self.parameters():
            parameter.requires_grad_(False)

    def forward(self, image):
        x, saved, features = image, [], {}
        for module in self.layers:
            if module.f != -1:
                x = saved[module.f] if isinstance(module.f, int) else [
                    x if index == -1 else saved[index] for index in module.f]
            x = module(x)
            saved.append(x if module.i in self.save else None)
            if module.i in self.feature_layers:
                features[module.i] = x
        return self.head(tuple(features[index] for index in self.feature_layers))


def lane_output_index(details, size):
    if len(details) != 1 or tuple(details[0]["shape"]) != (1, size // 4, size // 4, 1) or details[0]["dtype"] != np.float32:
        raise ValueError("Expected one float32 NHWC stride-4 lane-logit output")
    return details[0]["index"]


def export_litert(traced, records, directory, size, repeats):
    import onnx
    import onnxruntime as ort
    from onnxsim import simplify
    import tensorflow as tf
    converter = importlib.import_module("onnx2tf.onnx2tf")
    onnx_path = directory / "lane-prefix.onnx"
    with torch.inference_mode():
        torch.onnx.export(traced, records[0]["tensor"], str(onnx_path), input_names=["image"],
                          output_names=["lane_logits"], opset_version=17, dynamo=False)
    graph, valid = simplify(onnx.load(str(onnx_path)))
    if not valid:
        raise ValueError("ONNX simplification failed verification")
    onnx.save(graph, str(onnx_path))
    options = ort.SessionOptions(); options.intra_op_num_threads = 4
    session = ort.InferenceSession(str(onnx_path), sess_options=options, providers=["CPUExecutionProvider"])
    onnx_checks = []
    for row in records:
        actual = session.run(["lane_logits"], {"image": row["tensor"].numpy()})[0]
        check = export.compare_arrays(row["reference"], actual)
        if not check["allclose"]:
            raise ValueError("ONNX failed full-detector reference equivalence")
        onnx_checks.append(dict(key=row["key"], **check))
    arrays = [np.ascontiguousarray(row["tensor"].numpy().transpose(0, 2, 3, 1)) for row in records]
    input_path = directory / "verified-conversion-input.npy"
    np.save(input_path, arrays[0], allow_pickle=False)
    original_download = converter.download_test_image_data
    converter.download_test_image_data = lambda: np.load(input_path, allow_pickle=False)
    try:
        converter.convert(input_onnx_file_path=str(onnx_path), output_folder_path=str(directory / "converted"),
                          custom_input_op_name_np_data_path=[["image", str(input_path)]],
                          not_use_onnxsim=True, not_use_opname_auto_generate=True, non_verbose=True)
    finally:
        converter.download_test_image_data = original_download
    path = directory / "converted/lane-prefix_float32.tflite"
    interpreter = tf.lite.Interpreter(model_path=str(path), num_threads=4)
    interpreter.allocate_tensors()
    inputs = interpreter.get_input_details()
    if len(inputs) != 1 or tuple(inputs[0]["shape"]) != (1, size, size, 3) or inputs[0]["dtype"] != np.float32:
        raise ValueError("Expected one float32 NHWC RGB image input")
    output_index = lane_output_index(interpreter.get_output_details(), size)
    def predict(image):
        interpreter.set_tensor(inputs[0]["index"], image)
        interpreter.invoke()
        return interpreter.get_tensor(output_index).transpose(0, 3, 1, 2)
    checks = []
    for row, image in zip(records, arrays):
        actual = predict(image)
        checks.append(dict(key=row["key"], **export.compare_arrays(row["reference"], actual),
                           thresholdDisagreementPixels=int(np.count_nonzero((row["reference"] >= 0) != (actual >= 0)))))
    operators = Counter(op["op_name"] for op in interpreter._get_ops_details())
    return dict(status="exported_and_host_checked", artifact=export.artifact(path), onnxChecks=onnx_checks,
                checks=checks, allNumericalChecksPassed=all(row["allclose"] for row in checks),
                operatorCounts=dict(operators), requiresFlexOrCustom=any(op.startswith("Flex") or op == "CUSTOM" for op in operators),
                hostLatency=export.latency(predict, arrays, repeats=repeats),
                qualification="FP32 CPU XNNPACK only. The converter also saves an FP16-weight file; that file is not qualified by this control.")


def run(args):
    out = args.output_dir.resolve()
    if out == export.ROOT or export.ROOT in out.parents or out.exists():
        raise ValueError("Use a new external output directory")
    os.environ["TF_USE_LEGACY_KERAS"] = "1"
    import tensorflow as tf
    versions = {"coremltools": "9.0", "onnx": "1.17.0", "onnxruntime": "1.19.2", "onnx2tf": "1.20.0",
                "onnxsim": "0.4.36", "tensorflow": "2.18.0", "torch": "2.8.0", "ultralytics": "8.4.56"}
    for package, version in versions.items():
        if importlib.metadata.version(package) != version:
            raise ValueError("Use pinned dependency: " + package + "==" + version)
    tf.config.threading.set_intra_op_parallelism_threads(4)
    tf.config.threading.set_inter_op_parallelism_threads(1)
    torch.set_num_threads(4); cv2.setNumThreads(1)
    extractor, head, config = training.load_auxiliary(args.checkpoint, args.detector, "cpu")
    if config["inputSize"] != 640 or config["featureLayers"] != [2, 4]:
        raise ValueError("Require the existing frozen 640 P2/P3 A2D2 pilot")
    detector_before, head_before = training.state_hash(extractor.detector), training.state_hash(head)
    sources = [Path(__file__), Path(export.__file__), Path(training.__file__), args.checkpoint, args.detector, args.manifest]
    hashes = {str(path.resolve()): training.sha256_file(path) for path in sources}
    # Validate bound source manifest and sample count before creating the output.
    records_640 = export.sample_validation(args.manifest, config, args.samples, 640)
    out.mkdir(parents=True)
    for path in sources[:3]:
        shutil.copy2(path, out / path.name)
    report = dict(status="started", decision="DEFER_PRODUCTION", control="separate_full_field_frozen_prefix_plus_head",
                  sourceHashes=hashes, environment=versions, trainingInputSize=640, trainedParametersChanged=False,
                  host=dict(platform=platform.platform(), machine=platform.machine(), torchThreads=4, cpuOnly=True),
                  resolutions={}, numericalTolerance=dict(atol=1e-4, rtol=1e-4),
                  sources=["https://apple.github.io/coremltools/docs-guides/source/convert-pytorch-workflow.html",
                           "https://github.com/PINTO0309/onnx2tf", "https://github.com/daquexian/onnx-simplifier"],
                  qualification=["Separate lane-only whole-field invocation; shipping cropped TSR is unchanged and is not part of this artifact.",
                                 "Exactly the original detector layers 0 through 4 and fixed trained lane head; later detector weights are excluded.",
                                 "640 and 1280 compare against the complete frozen detector at the same resolution; no lane accuracy at 1280 is claimed.",
                                 "No training, threshold selection, NMS, classification, device integration or deployment.",
                                 "Warmed Mac CPU timing excludes decoding, letterbox, model load, scheduling, full-frame projection and rendering.",
                                 "Host performance is not isolated or a phone, GPU/ANE/delegate, memory, thermal or camera cadence measurement."])
    try:
        for size in (640, 1280):
            directory = out / str(size); directory.mkdir()
            records = records_640 if size == 640 else export.sample_validation(args.manifest, config, args.samples, size)
            # Restore hooks for the independent complete original detector reference.
            with torch.inference_mode():
                for row in records:
                    features = extractor(row["tensor"])
                    row["reference"] = head(features).numpy().copy()
            for handle in extractor.handles:
                handle.remove()
            extractor.handles.clear()
            prefix = FrozenLanePrefix(extractor.detector, head, config["featureLayers"])
            with torch.inference_mode():
                eager_checks = []
                for row in records:
                    check = export.compare_arrays(row["reference"], prefix(row["tensor"]).numpy(), atol=0, rtol=0)
                    if not check["allclose"]:
                        raise ValueError("Prefix logits differ from complete original detector/head")
                    eager_checks.append(dict(key=row["key"], sha256=row["sha256"], transform=row["transform"], **check))
                traced = torch.jit.trace(prefix, records[0]["tensor"], check_inputs=[(row["tensor"],) for row in records[1:3]])
                trace_checks = []
                for row in records:
                    check = export.compare_arrays(row["reference"], traced(row["tensor"]).numpy())
                    if not check["allclose"]:
                        raise ValueError("Prefix trace failed independent multi-image equivalence")
                    trace_checks.append(dict(key=row["key"], **check))
                result = dict(frames=len(records), inputSize=size, resolutionControlOnly=size != 640,
                              eagerChecks=eager_checks, traceChecks=trace_checks,
                              cost=export.convolution_cost(prefix, records[0]["tensor"]))
            trace_path = directory / "lane-prefix.torchscript.pt"; traced.save(str(trace_path))
            # Execute the persisted TorchScript as the converter source.
            traced = torch.jit.load(str(trace_path)).eval()
            coreml, coreml_result = export.coreml_export(traced, directory / "lane-prefix-float32.mlpackage",
                                                        half=False, sample=records[0]["tensor"], output_names=["lane_logits"])
            coreml_checks = []
            for row in records:
                actual = coreml.predict({"image": row["tensor"].numpy()})["lane_logits"]
                coreml_checks.append(dict(key=row["key"], **export.compare_arrays(row["reference"], actual),
                                          thresholdDisagreementPixels=int(np.count_nonzero((row["reference"] >= 0) != (actual >= 0)))))
            coreml_result.update(status="exported_and_host_checked", checks=coreml_checks,
                                 allNumericalChecksPassed=all(row["allclose"] for row in coreml_checks),
                                 hostLatency=export.latency(lambda image: coreml.predict({"image": image.numpy()}),
                                                           [row["tensor"] for row in records], repeats=args.repeats))
            result["coreml"] = coreml_result
            result["litert"] = export_litert(traced, records, directory, size, args.repeats)
            result["sourceStatePreserved"] = dict(detectorBefore=detector_before, detectorAfter=training.state_hash(extractor.detector),
                                                   headBefore=head_before, headAfter=training.state_hash(head))
            if detector_before != result["sourceStatePreserved"]["detectorAfter"] or head_before != result["sourceStatePreserved"]["headAfter"]:
                raise ValueError("Frozen source state changed before the next resolution")
            report["resolutions"][str(size)] = result
            training.write_json(out / "summary.json", report)
            if size == 640:
                # A fresh independently loaded original detector restores feature hooks
                # for the 1280 reference. Exported prefix tensors never feed that reference.
                extractor, head, reloaded_config = training.load_auxiliary(args.checkpoint, args.detector, "cpu")
                if reloaded_config != config:
                    raise ValueError("Checkpoint configuration changed")
        report["sourceStatePreserved"] = dict(detectorBefore=detector_before, detectorAfter=training.state_hash(extractor.detector),
                                              headBefore=head_before, headAfter=training.state_hash(head))
        if detector_before != report["sourceStatePreserved"]["detectorAfter"] or head_before != report["sourceStatePreserved"]["headAfter"]:
            raise ValueError("Frozen source state changed")
        if any(training.sha256_file(path) != digest for path, digest in hashes.items()):
            raise ValueError("Source changed during prefix qualification")
        report["status"] = "qualification_complete_production_deferred"
        training.write_json(out / "summary.json", report)
        training.write_json(out / "artifact-sha256.json", export.artifact(out))
        return report
    except BaseException as error:
        report.update(status="failed", error=repr(error)); training.write_json(out / "summary.json", report)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--detector", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=32)
    parser.add_argument("--repeats", type=int, default=32)
    args = parser.parse_args()
    if args.repeats < 2:
        parser.error("Require at least two timed samples")
    print(json.dumps(dict(status=run(args)["status"], output=str(args.output_dir))))


if __name__ == "__main__":
    main()
