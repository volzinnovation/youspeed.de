#!/usr/bin/env python3
"""Export frozen DE training features/logits for classical and prior experiments.

No test pixels are read. Historical validation is reused diagnostic evidence;
the chosen neural feature checkpoints were previously selected on that data.
Inputs are hash-checked; outputs are non-pickle NPZ arrays and JSON provenance.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import sys
import time


CHECKPOINTS = {
    "yolo136": ("results/pilots-v1/yolo_ce/best.pt", "65de1a9c942eead20083b1cf66b411141a54bc7a239bf87da795d58aa7ebef41"),
    "small136": ("results/students-20epochs/small_kd/best.pt", "404e2a26d2184ae910ab97e50e1897bb04c86ce94475ebcece02c97964e8c2ae"),
    "large136": ("results/students-20epochs/large_kd/best.pt", "ed4e16fde8a4148e0f399832f1b4aeaf4f96db1b1a2feccf54e682e6d7a433ee"),
}


def dump(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def handcrafted(rgb, np, cv2, Image, hog):
    """HOG64 + HSV histograms + RGB8 layout + aspect ratio, 2005 values."""
    width, height = rgb.size
    resized = np.asarray(rgb.resize((64, 64), Image.Resampling.BILINEAR))
    gray = cv2.cvtColor(resized, cv2.COLOR_RGB2GRAY)
    edge = hog.compute(gray).reshape(-1)
    hsv = cv2.cvtColor(resized, cv2.COLOR_RGB2HSV)
    hist = [np.histogram(hsv[:, :, k], bins=16, range=(0, limit))[0] / 4096
            for k, limit in enumerate((180, 256, 256))]
    layout = np.asarray(rgb.resize((8, 8), Image.Resampling.BILINEAR), dtype=np.float32).reshape(-1) / 255
    return np.concatenate([edge, *hist, layout, [max(-2., min(2., math.log(width / height)))] ]).astype(np.float32)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--data", type=Path, required=True)
    p.add_argument("--course-code", type=Path, required=True)
    p.add_argument("--model", type=Path, required=True)
    p.add_argument("--experiment-root", type=Path, required=True)
    p.add_argument("--partition", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--device", default="cuda:0")
    args = p.parse_args()
    if args.output.exists():
        raise ValueError("Require a new output directory")
    sys.path.insert(0, str(args.course_code))
    import model_utils as mu
    from de_neural_refinement import validate_partition
    torch, ultralytics, np, Image, ImageOps = mu.dependencies()
    import cv2
    import timm
    torch.set_num_threads(1); torch.set_num_interop_threads(1)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.benchmark = False
    cv2.setNumThreads(1)
    classes = mu.load_classes(args.data / "class-index.json")
    manifest, manifest_sha = mu.load_manifest(args.data, classes)
    train = mu.samples_for_split(args.data, manifest, "train", classes, require_all=True)
    val = mu.samples_for_split(args.data, manifest, "val", classes)
    partition = json.loads(args.partition.read_text())
    dev, report = validate_partition(partition, val, manifest_sha, classes)
    common = {
        "class_names": np.asarray(classes),
        "train_labels": np.asarray([r["class_index"] for r in train], dtype=np.int64),
        "val_labels": np.asarray([r["class_index"] for r in val], dtype=np.int64),
        "dev_indices": np.asarray(dev, dtype=np.int64), "report_indices": np.asarray(report, dtype=np.int64),
    }
    for split, rows in (("train", train), ("val", val)):
        common[f"{split}_sample_ids"] = np.asarray([r["sample_id"] for r in rows])
        common[f"{split}_groups"] = np.asarray([r["group_id"] for r in rows])
        common[f"{split}_group_ids"] = common[f"{split}_groups"]
    args.output.mkdir(parents=True)
    config = {"created_at": datetime.now(timezone.utc).isoformat(),
              "script_sha256": mu.sha256(Path(__file__)), "helper_sha256": mu.sha256(args.course_code / "model_utils.py"),
              "manifest_sha256": manifest_sha, "partition_sha256": mu.sha256(args.partition),
              "train_count": len(train), "validation_count": len(val), "test_pixels_opened": False,
              "torch": str(torch.__version__), "timm": timm.__version__, "opencv": cv2.__version__,
              "limitations": ["Previously inspected historical validation", "Upstream teacher exposure unresolved", "Selected neural checkpoints used the full historical validation in previous runs", "One city reporting group", "GPU FP32 features; native export numerical parity unverified"]}
    dump(args.output / "configuration.json", config)
    features = {}
    for family in ("yolo134", "yolo136", "small136", "large136"):
        checkpoint_sha = mu.BASELINE_SHA256
        if family.startswith("yolo"):
            model = mu.load_baseline(torch, ultralytics, args.model, classes)
            if family == "yolo136":
                model = mu.extend_classifier(torch, model, classes)
            head = model.model[-1].linear
        else:
            size = "small" if family.startswith("small") else "large"
            model = timm.create_model(f"mobilenetv3_{size}_100", pretrained=False, num_classes=136)
            head = model.classifier
        if family in CHECKPOINTS:
            relative, checkpoint_sha = CHECKPOINTS[family]
            path = args.experiment_root / relative
            if mu.sha256(path) != checkpoint_sha:
                raise ValueError(f"Unexpected checkpoint {family}")
            state = torch.load(path, map_location="cpu", weights_only=True)
            if state["classes"] != classes or state["manifest_sha256"] != manifest_sha:
                raise ValueError("Checkpoint taxonomy or dataset mismatch")
            model.load_state_dict(state["state_dict"], strict=True)
        model.to(args.device).eval()
        captured = []
        def capture(_module, inputs):
            captured[:] = [inputs[0].detach()]
        handle = head.register_forward_pre_hook(capture)
        def forward(images):
            if not family.startswith("yolo"):
                mean = images.new_tensor([.485, .456, .406])[None, :, None, None]
                std = images.new_tensor([.229, .224, .225])[None, :, None, None]
                images = (images - mean) / std
            output = mu.logits_from_output(model(images))
            return output, captured[0]
        values = dict(common)
        started = time.monotonic()
        with torch.inference_mode():
            for split, rows in (("train", train), ("val", val)):
                loader = torch.utils.data.DataLoader(mu.dataset(torch, np, Image, ImageOps, rows),
                            batch_size=64, shuffle=False, num_workers=4, pin_memory=True)
                embedding, logits = [], []
                for images, _labels in loader:
                    scores, vector = forward(images.to(args.device, non_blocking=True))
                    embedding.append(vector.cpu().numpy().copy())
                    logits.append(scores.cpu().numpy().copy())
                values[f"{split}_features"] = np.concatenate(embedding).astype(np.float32)
                values[f"{split}_logits"] = np.concatenate(logits).astype(np.float32)
        values["model_class_names"] = np.asarray(classes[:134] if family == "yolo134" else classes)
        extraction_seconds = time.monotonic() - started
        model.to("cpu"); timings = []
        x = torch.rand((1, 3, 224, 224), generator=torch.Generator().manual_seed(20261109))
        with torch.inference_mode():
            for index in range(60):
                start = time.perf_counter_ns(); forward(x)
                elapsed = (time.perf_counter_ns() - start) / 1e6
                if index >= 10: timings.append(elapsed)
        path = args.output / f"{family}.npz"
        np.savez_compressed(path, **values)
        meta = {"family": family, "checkpoint_sha256": checkpoint_sha, "manifest_sha256": manifest_sha,
                "npz_sha256": mu.sha256(path), "feature_dimension": values["train_features"].shape[1],
                "extraction_seconds": extraction_seconds, "parameters": sum(p.numel() for p in model.parameters()),
                "feature_definition": "Input to the final linear classifier after global pooling/projection, eval mode",
                "feature_cpu_latency": {"p50_ms": float(np.median(timings)), "p95_ms": float(np.quantile(timings,.95)),
                    "samples_ms": timings, "threads": 1, "dtype": "float32", "scope": "Network forward and normalization; includes discarded neural output head; excludes image decoding and resizing"},
                "source_selection": "frozen original checkpoint" if family == "yolo134" else "checkpoint selected on full reused validation in preceding investigation",
                "limitations": config["limitations"]}
        dump(args.output / f"{family}.json", meta)
        features[family] = {"npz_sha256": meta["npz_sha256"], "dimension": meta["feature_dimension"]}
        print(json.dumps({"family": family, "seconds": extraction_seconds, "dimension": meta["feature_dimension"]}), flush=True)
        handle.remove(); del model, values, embedding, logits, captured
        torch.cuda.empty_cache()
    hog = cv2.HOGDescriptor((64,64),(16,16),(8,8),(8,8),9)
    values = dict(common)
    for split, rows in (("train", train), ("val", val)):
        data = []
        for row in rows:
            with Image.open(row["resolved_path"]) as raw:
                rgb = ImageOps.exif_transpose(raw).convert("RGB")
                data.append(handcrafted(rgb, np, cv2, Image, hog))
        values[f"{split}_features"] = np.stack(data)
    with Image.open(train[0]["resolved_path"]) as raw:
        rgb = ImageOps.exif_transpose(raw).convert("RGB")
    timings = []
    for index in range(120):
        start = time.perf_counter_ns(); handcrafted(rgb, np, cv2, Image, hog)
        if index >= 20: timings.append((time.perf_counter_ns() - start) / 1e6)
    path = args.output / "handcrafted.npz"
    np.savez_compressed(path, **values)
    meta = {"family": "handcrafted", "feature_dimension": values["train_features"].shape[1],
            "npz_sha256": mu.sha256(path), "manifest_sha256": manifest_sha,
            "feature_definition": "64px HOG1764 + normalized16-bin HSV histograms48 + RGB8x8 layout192 + clippedlogaspect1",
            "feature_cpu_latency": {"p50_ms": float(np.median(timings)), "p95_ms": float(np.quantile(timings,.95)),
                "samples_ms": timings, "threads": 1, "scope": "Pillow resize plus HOG/color/shape extraction on one decoded source image; image decoding excluded"},
            "limitations": config["limitations"]}
    dump(args.output / "handcrafted.json", meta)
    features["handcrafted"] = {"npz_sha256": meta["npz_sha256"], "dimension": meta["feature_dimension"]}
    dump(args.output / "complete.json", {"completed_at": datetime.now(timezone.utc).isoformat(), "families": features})


if __name__ == "__main__":
    main()
