#!/usr/bin/env python3
"""Export/qualify the frozen A2D2 lane-head prototype on a Mac, without training.

Core ML exports share the complete original detector graph and expose decoded
boxes/class scores plus stride-4 lane logits. A fixed-weight TensorFlow rewrite
exports a LiteRT *head-only* control; it is not an Android shared-model export.
All timings are warmed host CPU timings, not device performance claims.
"""
from __future__ import annotations

import argparse
from collections import Counter
import copy
import importlib.metadata
import json
from pathlib import Path
import platform
import shutil
import sys
import time

import cv2
import numpy as np
import torch
from torch import nn

if __package__:
    from . import train_a2d2_auxiliary as training
else:
    import train_a2d2_auxiliary as training

ROOT = Path(__file__).resolve().parents[2]


class SharedDetectorAndLane(nn.Module):
    """Explicit graph traversal: no hook-captured tensors become trace constants.

    The routing is the pinned Ultralytics BaseModel._predict_once routing. The
    original detector modules/weights and decode remain unchanged. Source module
    hooks must be removed before construction, then the module is deep-copied so
    export state cannot mutate the reference detector.
    """

    def __init__(self, detector, head=None, feature_layers=(2, 4)):
        super().__init__()
        if any(m._forward_hooks for m in detector.modules()):
            raise ValueError("Remove feature hooks before building the export graph")
        self.detector = copy.deepcopy(detector).eval()
        self.head = copy.deepcopy(head).eval() if head is not None else None
        self.feature_layers = tuple(feature_layers)
        self.save = frozenset(self.detector.save)
        if len(self.feature_layers) != 2 or len(set(self.feature_layers)) != 2:
            raise ValueError("Expected two distinct feature layers")
        if not all(0 <= i < len(self.detector.model) - 1 for i in self.feature_layers):
            raise ValueError("Feature taps must precede the detection output")
        for parameter in self.parameters():
            parameter.requires_grad_(False)
        self.eval()

    def forward(self, image):
        x, saved, features = image, [], {}
        for module in self.detector.model:
            if module.f != -1:
                x = saved[module.f] if isinstance(module.f, int) else [
                    x if index == -1 else saved[index] for index in module.f]
            x = module(x)
            saved.append(x if module.i in self.save else None)
            if module.i in self.feature_layers:
                features[module.i] = x
        decoded = x[0] if isinstance(x, tuple) else x
        if self.head is None:
            return decoded
        return decoded, self.head(tuple(features[i] for i in self.feature_layers))


def compare_arrays(reference, actual, *, atol=1e-4, rtol=1e-4):
    reference, actual = np.asarray(reference), np.asarray(actual)
    if reference.shape != actual.shape:
        raise ValueError(f"Output shape differs: {reference.shape} versus {actual.shape}")
    if not np.isfinite(reference).all() or not np.isfinite(actual).all():
        raise ValueError("Nonfinite reference or exported output")
    difference = np.abs(reference.astype(np.float64) - actual.astype(np.float64))
    return dict(maxAbsoluteDifference=float(difference.max()),
                meanAbsoluteDifference=float(difference.mean()),
                rootMeanSquareDifference=float(np.sqrt(np.mean(difference ** 2))),
                allclose=bool(np.allclose(reference, actual, atol=atol, rtol=rtol)),
                atol=atol, rtol=rtol, elements=int(reference.size))


def compare_detections(reference, actual, **tolerance):
    result = compare_arrays(reference, actual, **tolerance)
    if reference.ndim != 3 or reference.shape[1] != 7:
        raise ValueError("Expected original sign/plate/face decoded tensor [1,7,N]")
    result["coordinates"] = compare_arrays(reference[:, :4], actual[:, :4], **tolerance)
    result["classScores"] = compare_arrays(reference[:, 4:], actual[:, 4:], **tolerance)
    # Existing pack unknown-score threshold; diagnostic only, before NMS/classifier.
    selected = (reference[:, 4] >= .25) | (actual[:, 4] >= .25)
    result["signScoreThreshold"] = .25
    result["signAnchorThresholdTransitions"] = int(np.count_nonzero((reference[:, 4] >= .25) != (actual[:, 4] >= .25)))
    result["signAnchorsAboveThresholdInEither"] = int(selected.sum())
    result["selectedSignCoordinates"] = compare_arrays(reference[:, :4].transpose(0, 2, 1)[selected],
                                                         actual[:, :4].transpose(0, 2, 1)[selected], **tolerance) if selected.any() else None
    return result


def latency(run, samples, warmup=5, repeats=32):
    for index in range(warmup):
        run(samples[index % len(samples)])
    elapsed = []
    for index in range(repeats):
        start = time.perf_counter()
        run(samples[index % len(samples)])
        elapsed.append((time.perf_counter() - start) * 1000)
    return dict(samples=repeats, warmup=warmup, milliseconds=elapsed,
                meanMilliseconds=float(np.mean(elapsed)),
                p50Milliseconds=float(np.median(elapsed)),
                p95Milliseconds=float(np.quantile(elapsed, .95)),
                scope="Synchronous warmed host CPU invocation including input/output bridging; excludes RGB decode, letterbox, model loading, NMS, lane projection and rendering")


def artifact(path):
    path = Path(path)
    paths = sorted(p for p in path.rglob("*") if p.is_file()) if path.is_dir() else [path]
    entries = [dict(path=str(p.relative_to(path)) if path.is_dir() else p.name,
                    bytes=p.stat().st_size, sha256=training.sha256_file(p)) for p in paths]
    return dict(path=str(path), bytes=sum(row["bytes"] for row in entries), files=entries)


def convolution_cost(model, sample):
    """Count Conv2d multiply-accumulates, not total FLOPs or measured memory."""
    counts, hooks = [], []
    def record(module, inputs, output):
        macs = output.numel() * (module.in_channels // module.groups) * np.prod(module.kernel_size)
        counts.append(dict(multiplyAccumulates=int(macs), outputElements=output.numel()))
    for module in model.modules():
        if isinstance(module, nn.Conv2d):
            hooks.append(module.register_forward_hook(record))
    try:
        with torch.inference_mode():
            model(sample)
    finally:
        for hook in hooks:
            hook.remove()
    return dict(conv2dMultiplyAccumulates=sum(row["multiplyAccumulates"] for row in counts),
                conv2dCalls=len(counts), parameters=sum(p.numel() for p in model.parameters()),
                qualification="Conv2d MACs only; excludes attention matmuls, resizing, activation, decode and backend scheduling. Not a mobile latency or peak-memory estimate.")


def sample_validation(manifest_path, config, count, input_size=None):
    if training.sha256_file(manifest_path) != config["datasetManifestSha256"]:
        raise ValueError("Qualification manifest differs from the frozen training run")
    _, objects, partitions, _ = training.validate_manifest(manifest_path)
    pairs = partitions["validation"]
    if not 2 <= count <= len(pairs):
        raise ValueError("Use at least two and no more than the available validation images")
    # Fixed evenly spaced chronological validation frames, before any output scores.
    indices = np.linspace(0, len(pairs) - 1, count, dtype=int)
    samples = []
    for index in indices:
        pair = pairs[int(index)]
        source = objects[pair["rgb"]]
        image = cv2.imread(source["local_path"])
        if image is None:
            raise ValueError("Unreadable verified RGB")
        x, transform = training.letterbox_rgb(cv2.cvtColor(image, cv2.COLOR_BGR2RGB), input_size or config["inputSize"])
        samples.append(dict(key=pair["rgb"], sha256=source["sha256"], transform=transform,
                            tensor=x.unsqueeze(0)))
    return samples


def coreml_export(traced, path, *, half, sample, output_names):
    import coremltools as ct
    result = ct.convert(traced, source="pytorch", convert_to="mlprogram",
                        inputs=[ct.TensorType(name="image", shape=sample.shape, dtype=np.float32)],
                        outputs=[ct.TensorType(name=name, dtype=np.float32) for name in output_names],
                        minimum_deployment_target=ct.target.iOS16,
                        compute_precision=ct.precision.FLOAT16 if half else ct.precision.FLOAT32,
                        compute_units=ct.ComputeUnit.CPU_ONLY)
    result.short_description = f"Offline {sample.shape[-1]} whole-frame lane-hint export qualification; not a release model"
    result.save(str(path))
    # Reload persisted artifact to ensure saved bytes, rather than only converter memory, execute.
    result = ct.models.MLModel(str(path), compute_units=ct.ComputeUnit.CPU_ONLY)
    operators = Counter()
    for function in result.get_spec().mlProgram.functions.values():
        for block in function.block_specializations.values():
            operators.update(operation.type for operation in block.operations)
    return result, dict(artifact=artifact(path), operatorCounts=dict(operators),
                        computeUnits="CPU_ONLY", computePrecision="float16" if half else "float32",
                        input=f"float32 NCHW RGB /255, caller-applied exact {sample.shape[-1]} letterbox; no image preprocessing in exported graph",
                        outputs=output_names)


def make_tensorflow_head(head, feature_shapes):
    """Exact fixed-weight rewrite, not training or architecture substitution.

    Public TF ops use NHWC; OIHW conv weights become HWIO, depthwise O1HW
    becomes HWIM. ResizeBilinear's half-pixel centers match align_corners=False.
    """
    import tensorflow as tf
    state = {key: value.detach().cpu().numpy() for key, value in head.state_dict().items()}
    def conv(x, name, depthwise=False):
        weights = state[name + ".weight"]
        if depthwise:
            kernel = tf.constant(weights.transpose(2, 3, 0, 1))
            value = tf.nn.depthwise_conv2d(x, kernel, [1, 1, 1, 1], padding="SAME")
        else:
            kernel = tf.constant(weights.transpose(2, 3, 1, 0))
            value = tf.nn.conv2d(x, kernel, strides=1, padding="SAME")
        return tf.nn.bias_add(value, tf.constant(state[name + ".bias"]))
    shapes = [(s[0], s[2], s[3], s[1]) for s in feature_shapes]
    class Head(tf.Module):
        @tf.function(input_signature=[tf.TensorSpec(shapes[0], tf.float32, "p2"),
                                      tf.TensorSpec(shapes[1], tf.float32, "p3")])
        def __call__(self, p2, p3):
            low, high = conv(p2, "p2"), conv(p3, "p3")
            high = tf.raw_ops.ResizeBilinear(images=high, size=shapes[0][1:3],
                                           align_corners=False, half_pixel_centers=True)
            mixed = tf.nn.relu(conv(tf.concat([low, high], axis=-1), "mix.0", True))
            return {"lane_logits": conv(mixed, "mix.2")}
    return Head()


def litert_head_export(head, records, output_dir, repeats):
    import tensorflow as tf
    tf.config.threading.set_intra_op_parallelism_threads(4)
    tf.config.threading.set_inter_op_parallelism_threads(1)
    module = make_tensorflow_head(head, [f.shape for f in records[0]["features"]])
    converter = tf.lite.TFLiteConverter.from_concrete_functions([module.__call__.get_concrete_function()], module)
    converter.target_spec.supported_ops = [tf.lite.OpsSet.TFLITE_BUILTINS]
    flatbuffer = converter.convert()
    path = output_dir / "lane-head-only-float32.tflite"
    path.write_bytes(flatbuffer)
    interpreter = tf.lite.Interpreter(model_path=str(path), num_threads=4)
    interpreter.allocate_tensors()
    runner = interpreter.get_signature_runner()
    def inputs(row):
        return {name: np.ascontiguousarray(value.numpy().transpose(0, 2, 3, 1))
                for name, value in zip(("p2", "p3"), row["features"])}
    checks = []
    for row in records:
        feed = inputs(row)
        tf_value = module(**feed)["lane_logits"].numpy().transpose(0, 3, 1, 2)
        actual = runner(**feed)["lane_logits"].transpose(0, 3, 1, 2)
        checks.append(dict(key=row["key"], tensorflow=compare_arrays(row["logits"], tf_value),
                           litert=compare_arrays(row["logits"], actual)))
    operations = Counter(op["op_name"] for op in interpreter._get_ops_details())
    samples = [inputs(row) for row in records]
    return dict(status="exported_and_host_checked", scope="Head-only FP32 compatibility control. Inputs are original PyTorch P2/P3 features; this does not export or benchmark the shared Android backbone.",
                artifact=artifact(path), signature=interpreter.get_signature_list(), operatorCounts=dict(operations),
                checks=checks, hostLatency=latency(lambda feed: runner(**feed), samples, repeats=repeats),
                allNumericalChecksPassed=all(r[k]["allclose"] for r in checks for k in ("tensorflow", "litert")),
                tensorflowVersion=tf.__version__, inputLayout="NHWC", outputLayout="NHWC")


def run(args):
    out = args.output_dir.resolve()
    if out == ROOT or ROOT in out.parents or out.exists():
        raise ValueError("Use a new output directory outside the repository")
    torch.set_num_threads(4)
    cv2.setNumThreads(1)
    extractor, head, config = training.load_auxiliary(args.checkpoint, args.detector, "cpu")
    if config["inputSize"] != 640 or config["featureLayers"] != [2, 4]:
        raise ValueError("This qualification protocol requires the existing 640 P2/P3 pilot")
    input_size = getattr(args, "input_size", 640)
    if input_size not in (640, 1280):
        raise ValueError("Only 640 pilot and 1280 resolution-control exports are supported")
    samples = sample_validation(args.manifest, config, args.samples, input_size)
    source_hashes = {str(path.resolve()): training.sha256_file(path) for path in
                     (args.checkpoint, args.detector, args.manifest, Path(__file__), Path(training.__file__))}
    before = training.state_hash(extractor.detector)
    head_before = training.state_hash(head)
    out.mkdir(parents=True)
    shutil.copy2(__file__, out / Path(__file__).name)
    shutil.copy2(training.__file__, out / Path(training.__file__).name)
    report = dict(schemaVersion=1, decision="DEFER_PRODUCTION", sourceHashes=source_hashes,
                  validationSelection="Evenly spaced chronological validation frames; no fitting, calibration or test/private-video selection",
                  inputSize=input_size, trainingInputSize=config["inputSize"], resolutionControlOnly=input_size != config["inputSize"],
                  frames=len(samples), torchVersion=str(torch.__version__),
                  host=dict(platform=platform.platform(), machine=platform.machine(), processor=platform.processor(),
                            python=sys.version, torchThreads=4, cpuOnly=True),
                  qualification=["Only the frozen A2D2 run is exported. No training or threshold tuning.",
                                 "Whole-frame distorted RGB letterbox does not qualify the production TSR calibration-crop/full-scene contract.",
                                 "1280 export is a numerical/cost resolution control of weights trained at 640; no lane accuracy at 1280 is claimed.",
                                 "Raw detector tensor preservation does not replace end-to-end TSR classifier/event parity.",
                                 "No mobile invocation, ANE/GPU delegate, thermal, sustained camera, peak-memory or camera-to-overlay measurement.",
                                 "LiteRT head-only control does not qualify a complete Android shared model.",
                                 "No release model pack, app wiring or deployment is produced."],
                  sources=["https://apple.github.io/coremltools/docs-guides/source/convert-pytorch-workflow.html",
                           "https://apple.github.io/coremltools/docs-guides/source/convert-to-ml-program.html",
                           "https://github.com/google-ai-edge/litert-torch",
                           "https://www.tensorflow.org/api_docs/python/tf/lite/TFLiteConverter",
                           "https://www.tensorflow.org/api_docs/python/tf/raw_ops/ResizeBilinear"],
                  numericalTolerance="FP32 and trace allclose: atol=1e-4 rtol=1e-4; FP16: atol=0.05 rtol=0.001. Diagnostic engineering tolerances, not recognition acceptance thresholds.")
    try:
        with torch.inference_mode():
            for row in samples:
                decoded = extractor.detector(row["tensor"])[0]
                features = tuple(extractor.features[index].clone() for index in config["featureLayers"])
                row.update(detector=decoded.numpy().copy(), features=features, logits=head(features).numpy().copy())
        for handle in extractor.handles:
            handle.remove()
        extractor.handles.clear()
        joint = SharedDetectorAndLane(extractor.detector, head, config["featureLayers"])
        baseline = SharedDetectorAndLane(extractor.detector)
        tensors = [row["tensor"] for row in samples]
        report["eagerChecks"] = []
        with torch.inference_mode():
            for row in samples:
                decoded, logits = joint(row["tensor"])
                check = dict(key=row["key"], sha256=row["sha256"], transform=row["transform"],
                             detector=compare_arrays(row["detector"], decoded.numpy(), atol=0, rtol=0),
                             lane=compare_arrays(row["logits"], logits.numpy(), atol=0, rtol=0),
                             baseline=compare_arrays(row["detector"], baseline(row["tensor"]).numpy(), atol=0, rtol=0))
                if not all(check[k]["allclose"] for k in ("detector", "lane", "baseline")):
                    raise ValueError("Explicit graph differs from original detector/head")
                report["eagerChecks"].append(check)
            report["cost"] = {"baseline": convolution_cost(baseline, tensors[0]),
                              "shared": convolution_cost(joint, tensors[0])}
            report["torchHostLatency"] = {"baseline": latency(baseline, tensors, repeats=args.repeats),
                                          "shared": latency(joint, tensors, repeats=args.repeats)}
            # Warm cached YOLO anchor geometry before tracing. Fixed input shape only.
            joint(tensors[0]); baseline(tensors[0])
            traces = {"shared": torch.jit.trace(joint, tensors[0], check_inputs=[(x,) for x in tensors[1:3]]),
                      "baseline": torch.jit.trace(baseline, tensors[0], check_inputs=[(x,) for x in tensors[1:3]])}
            report["traceChecks"] = []
            for row in samples:
                outputs = traces["shared"](row["tensor"])
                checks = dict(key=row["key"], detector=compare_arrays(row["detector"], outputs[0].numpy()),
                              lane=compare_arrays(row["logits"], outputs[1].numpy()),
                              baseline=compare_arrays(row["detector"], traces["baseline"](row["tensor"]).numpy()))
                if not all(checks[k]["allclose"] for k in ("detector", "lane", "baseline")):
                    raise ValueError("Trace failed multiple-image reference comparison")
                report["traceChecks"].append(checks)
        for name, traced in traces.items():
            traced.save(str(out / (name + ".torchscript.pt")))
        report["coreml"] = {}
        for half in (False, True):
            precision = "float16" if half else "float32"
            for name in ("baseline", "shared"):
                key = name + "-" + precision
                names = ["detections", "lane_logits"] if name == "shared" else ["detections"]
                try:
                    model, result = coreml_export(traces[name], out / (key + ".mlpackage"),
                                                  half=half, sample=tensors[0], output_names=names)
                    checks = []
                    arrays = []
                    for row in samples:
                        output = model.predict({"image": row["tensor"].numpy()})
                        tolerance = dict(atol=.05, rtol=.001) if half else dict(atol=1e-4, rtol=1e-4)
                        check = dict(key=row["key"], detector=compare_detections(row["detector"], output["detections"], **tolerance))
                        if name == "shared":
                            check["lane"] = compare_arrays(row["logits"], output["lane_logits"], **tolerance)
                            check["laneThresholdDisagreementPixels"] = int(np.count_nonzero((row["logits"] >= 0) != (output["lane_logits"] >= 0)))
                        checks.append(check)
                        arrays.append(output["detections"])
                    np.savez_compressed(out / (key + "-detections.npz"), detections=np.stack(arrays))
                    result.update(status="exported_and_host_checked", checks=checks,
                                  allNumericalChecksPassed=all(r[k]["allclose"] for r in checks for k in (("detector", "lane") if name == "shared" else ("detector",))),
                                  hostLatency=latency(lambda x: model.predict({"image": x.numpy()}), tensors, repeats=args.repeats))
                    report["coreml"][key] = result
                except Exception as error:
                    report["coreml"][key] = dict(status="failed", error=str(error))
                training.write_json(out / "summary.json", report)
            a, b = out / ("baseline-" + precision + "-detections.npz"), out / ("shared-" + precision + "-detections.npz")
            if a.exists() and b.exists():
                report["coreml"]["baselineVsShared-" + precision] = compare_arrays(np.load(a)["detections"], np.load(b)["detections"], atol=0, rtol=0)
        try:
            report["litertHead"] = litert_head_export(head, samples, out, args.repeats)
        except Exception as error:
            report["litertHead"] = dict(status="failed", error=str(error))
        report["litertShared"] = dict(status="not_exported", reason="The official direct PyTorch converter requires Linux and Python >=3.10; this run is macOS/Python 3.9. Full graph operator/delegate compatibility remains unqualified.",
                                      source="https://github.com/google-ai-edge/litert-torch")
        report["sourceStatePreserved"] = dict(detectorBefore=before, detectorAfter=training.state_hash(extractor.detector),
                                              headBefore=head_before, headAfter=training.state_hash(head))
        if report["sourceStatePreserved"]["detectorAfter"] != before or report["sourceStatePreserved"]["headAfter"] != head_before:
            raise ValueError("Source model state changed during export")
        if any(training.sha256_file(path) != digest for path, digest in source_hashes.items()):
            raise ValueError("Source file changed during export")
        report["environment"] = {name: importlib.metadata.version(name) for name in
                                 ("torch", "ultralytics", "numpy", "opencv-python", "coremltools", "tensorflow")}
        report["status"] = "qualification_complete_production_deferred"
        training.write_json(out / "summary.json", report)
        training.write_json(out / "artifact-sha256.json", artifact(out))
        return report
    except Exception as error:
        report.update(status="incomplete", error=str(error))
        training.write_json(out / "summary.json", report)
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--detector", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--samples", type=int, default=32)
    parser.add_argument("--repeats", type=int, default=32)
    parser.add_argument("--input-size", type=int, choices=(640, 1280), default=640,
                        help="1280 is an untrained-resolution numerical/cost control, not an accuracy result")
    args = parser.parse_args()
    if args.repeats < 2:
        parser.error("Require at least two timed samples")
    result = run(args)
    print(json.dumps(dict(status=result["status"], output=str(args.output_dir), decision=result["decision"])))


if __name__ == "__main__":
    main()
