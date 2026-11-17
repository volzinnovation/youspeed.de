#!/usr/bin/env python3
"""Frozen mixed reviewed/pseudo sign training with development-only selection.

No database, Hub upload, model download, or deployment is performed. Heavy ML
imports are deferred so manifest and metric checks run without a CUDA runtime.
See --help and the module's MANIFEST_SCHEMA for the input contract.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
import csv
import hashlib
import json
import math
import os
from pathlib import Path
import random
import re
import time

MANIFEST_SCHEMA = "streetshots-sign-only-mixed-v1"
ULTRALYTICS_VERSION = "8.4.56"
D4_SHA = "f02bf99483c5ad2b79f254b1623b18593ed780c8f3c2df7051331633bb1a2a36"
COCO_SHA = "9b09cc8bf347f0fc8a5f7657480587f25db09b34bf33b0652110fb03a8ad4fef"
SGBLUR_SHA = "698a70566938d25c3c1eaa49b89fc176fe2f3a20631a9a01fa56035613c7972a"
SPLITS = ("train", "validation", "test")
AP_KEY = "metrics/mAP50-95(B)"


def sha(path):
    value = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            value.update(block)
    return value.hexdigest()


def write(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def checked_path(root, relative, expected):
    if not isinstance(relative, str) or Path(relative).is_absolute():
        raise ValueError("Input paths must be relative to dataset-root")
    path = (root / relative).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"Input escapes dataset-root or is absent: {relative}")
    if not isinstance(expected, str) or not re.fullmatch(r"[0-9a-f]{64}", expected) or sha(path) != expected:
        raise ValueError(f"Input SHA-256 mismatch: {relative}")
    return path


def partition_manifest(manifest):
    """Validate identities/completeness without reading held-out label content."""
    if manifest.get("schema") != MANIFEST_SCHEMA:
        raise ValueError(f"Expected {MANIFEST_SCHEMA}")
    if not re.fullmatch(r"[0-9a-f]{40}", manifest.get("dataset_revision", "")):
        raise ValueError("Pin the full dataset commit revision")
    if manifest.get("review_provenance") != "mixed_reviewed_and_pseudo":
        raise ValueError("Mixed training must explicitly report reviewed and teacher pseudo-label provenance")
    parts = {split: [] for split in SPLITS}
    owners, ids = {}, set()
    for frame in manifest.get("frames", []):
        split, group, image_id = frame.get("split"), frame.get("group_id"), frame.get("image_id")
        if split not in parts or not isinstance(group, str) or not group or not isinstance(image_id, str) or not image_id:
            raise ValueError("Every frame needs image_id, geographic group_id and explicit split")
        if image_id in ids:
            raise ValueError("Duplicate image_id")
        ids.add(image_id)
        if split == "train" and frame.get("supervision") == "teacher_pseudo":
            if frame.get("annotation_complete") is not False or frame.get("human_verified") is not False:
                raise ValueError("Pseudo-labels must not be certified complete or human-verified")
            if frame.get("pseudo_label_policy_sha256") != manifest.get("pseudo_policy_sha256") or not re.fullmatch(r"[0-9a-f]{64}", str(frame.get("pseudo_label_policy_sha256"))):
                raise ValueError("Unbound pseudo-label policy")
            if frame.get("pseudo_label_status") not in ("pseudo_positive", "pseudo_negative"):
                raise ValueError("Unresolved pseudo-label frame cannot enter training")
        elif frame.get("annotation_complete") is not True:
            raise ValueError("Development and diagnostic references must remain reviewed")
        if any(type(frame.get(k)) is not int or frame[k] <= 0 for k in ("width", "height")):
            raise ValueError("Positive integer raster dimensions are required")
        identity = [("group", group), ("bytes", frame.get("image_sha256"))]
        identity += [(key, frame[key]) for key in ("pixel_sha256", "parent_image_id", "source_image_sha256", "source_sha256") if frame.get(key)]
        identity += [("sequence", value) for value in frame.get("sequence_ids", [])]
        for key in identity:
            if not key[1]:
                raise ValueError("Missing image SHA-256")
            if key in owners and owners[key] != split:
                raise ValueError(f"Cross-split identity overlap: {key[0]}")
            owners[key] = split
        parts[split].append(frame)
    if any(not rows for rows in parts.values()):
        raise ValueError("Nonempty train, validation and test splits are required")
    return parts


def read_yolo_labels(path, width, height):
    boxes = []
    for number, line in enumerate(Path(path).read_text().splitlines(), 1):
        if not line.strip():
            continue
        values = line.split()
        if len(values) != 5 or values[0] != "0":
            raise ValueError(f"Expected one-class sign YOLO box at {path}:{number}")
        cx, cy, w, h = map(float, values[1:])
        if not all(math.isfinite(v) for v in (cx, cy, w, h)) or w <= 0 or h <= 0:
            raise ValueError("Invalid YOLO box")
        box = [(cx-w/2)*width, (cy-h/2)*height, (cx+w/2)*width, (cy+h/2)*height]
        tolerance = 1e-5 * max(width, height)
        if box[0] < -tolerance or box[1] < -tolerance or box[2] > width+tolerance or box[3] > height+tolerance:
            raise ValueError("YOLO box is outside registered raster")
        boxes.append([max(0., box[0]), max(0., box[1]), min(float(width), box[2]), min(float(height), box[3])])
    return boxes


def stage_dataset(manifest, dataset_root, directory):
    """Hash all inputs, but decode/parse only train/dev before the sealed test."""
    import yaml
    from PIL import Image
    root = Path(dataset_root).resolve()
    parts = partition_manifest(manifest)
    directory.mkdir(parents=True, exist_ok=False)
    for split, rows in parts.items():
        paths = []
        positives = 0
        for frame in rows:
            image = checked_path(root, frame["image_path"], frame["image_sha256"])
            label = checked_path(root, frame["label_path"], frame["label_sha256"])
            if split != "test":
                with Image.open(image) as raster:
                    if raster.size != (frame["width"], frame["height"]) or raster.getexif().get(274, 1) != 1:
                        raise ValueError("Canonical upright raster with registered dimensions required")
                positives += len(read_yolo_labels(label, frame["width"], frame["height"]))
            # Hash-based names avoid separators and collisions in arbitrary source IDs.
            stem = hashlib.sha256(frame["image_id"].encode()).hexdigest()
            target = directory / "images" / split / (stem + image.suffix.lower())
            target_label = directory / "labels" / split / (stem + ".txt")
            target.parent.mkdir(parents=True, exist_ok=True)
            target_label.parent.mkdir(parents=True, exist_ok=True)
            target.symlink_to(image)
            target_label.symlink_to(label)
            paths.append(str(target.absolute()))
        if split != "test" and not positives:
            raise ValueError(f"At least one reviewed positive sign is required in {split}")
        (directory / f"{split}.txt").write_text("\n".join(paths) + "\n")
    data = {"path": str(directory.absolute()), "train": "train.txt", "val": "validation.txt", "test": "test.txt", "names": {0: "sign"}}
    path = directory / "data.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False))
    return path, parts


def iou(a, b):
    intersection = max(0., min(a[2], b[2])-max(a[0], b[0])) * max(0., min(a[3], b[3])-max(a[1], b[1]))
    union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - intersection
    return intersection/union if union > 0 else 0.


def frame_counts(truth, predictions, threshold, match_iou=.5, acceptable_extras=None):
    """Score-ordered one-to-one matching; each sign face is counted once."""
    selected = sorted((p for p in predictions if p["score"] >= threshold), key=lambda p: -p["score"])
    unused, tp, unmatched = set(range(len(truth))), 0, []
    for prediction in selected:
        best = max(unused, key=lambda j: (iou(truth[j], prediction["box"]), -j), default=None)
        if best is not None and iou(truth[best], prediction["box"]) >= match_iou:
            unused.remove(best)
            tp += 1
        else:
            unmatched.append(prediction)
    counts = {"tp": tp, "fp": len(selected)-tp, "fn": len(truth)-tp}
    if acceptable_extras is not None:
        lights = [x["box_xyxy"] for x in acceptable_extras if x.get("kind") == "traffic_light"]
        counts["fp_on_reviewed_traffic_lights"] = sum(
            any(iou(prediction["box"], box) >= match_iou for box in lights) for prediction in unmatched)
    return counts


def metrics(counts):
    tp, fp, fn = (counts[k] for k in ("tp", "fp", "fn"))
    precision = tp/(tp+fp) if tp+fp else 0.
    recall = tp/(tp+fn) if tp+fn else 0.
    return {**counts, "precision": precision, "recall": recall,
            "f1": 2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0.,
            "f2": 5*tp/(5*tp+fp+4*fn) if 5*tp+fp+4*fn else 0.}


def score_frames(records, threshold):
    rows = [{"image_id": r["image_id"], "group_id": r["group_id"],
             **frame_counts(r["truth"], r["predictions"], threshold,
                            acceptable_extras=r.get("acceptable_extra_candidates", []))} for r in records]
    total = {key: sum(r[key] for r in rows) for key in ("tp", "fp", "fn", "fp_on_reviewed_traffic_lights")}
    return {"threshold": threshold, **metrics(total), "image_count": len(rows),
            "fp_per_image": total["fp"]/len(rows) if rows else 0., "frames": rows,
            "traffic_light_note": "Subset of raw sign FP overlapping explicitly reviewed traffic-light regions at IoU >= 0.5; never removed from raw precision or F2. Extra regions may be incomplete."}


def threshold_sweep(records):
    # This frozen grid is selected before inspecting test labels/pixels.
    points = [score_frames(records, t/100) for t in range(1, 100)]
    best = max(points, key=lambda r: (r["f2"], r["recall"], r["precision"], r["threshold"]))
    return {"selection": "maximum development F2 (beta=2); then recall, precision, higher threshold", "threshold": best["threshold"],
            "points": [{k: v for k, v in p.items() if k != "frames"} for p in points]}


def bootstrap_groups(scored, iterations=2000, seed=14):
    groups = defaultdict(Counter)
    for row in scored["frames"]:
        groups[row["group_id"]].update({k: row[k] for k in ("tp", "fp", "fn")})
    keys = sorted(groups)
    if len(keys) < 2:
        return {"groups": len(keys), "intervals": None, "reason": "At least two geographic groups required"}
    generator = random.Random(seed)
    values = defaultdict(list)
    for _ in range(iterations):
        total = Counter()
        for key in generator.choices(keys, k=len(keys)):
            total.update(groups[key])
        result = metrics({k: total[k] for k in ("tp", "fp", "fn")})
        for name in ("precision", "recall", "f1", "f2"):
            values[name].append(result[name])
    intervals = {}
    for name, samples in values.items():
        samples.sort()
        intervals[name] = [samples[int(.025*(iterations-1))], samples[int(.975*(iterations-1))]]
    return {"groups": len(keys), "iterations": iterations, "seed": seed, "method": "geographic-group percentile bootstrap", "intervals": intervals,
            "limitation": "Intervals describe model-assisted reference labels; few groups provide weak support."}


def ml_dependencies():
    os.environ.setdefault("CUBLAS_WORKSPACE_CONFIG", ":4096:8")
    import torch
    import ultralytics
    if ultralytics.__version__ != ULTRALYTICS_VERSION or not torch.cuda.is_available():
        raise RuntimeError(f"CUDA and Ultralytics {ULTRALYTICS_VERSION} required")
    torch.set_num_threads(4)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    return torch


def verified_weights(path, expected):
    path = Path(path).resolve()
    if not path.is_file() or sha(path) != expected:
        raise ValueError(f"Pinned checkpoint mismatch: {path}")
    return path


def sign_model(initialization, coco, d4=None):
    """Build non-end-to-end nc=1 YOLO26n, preserving the d4 state ABI."""
    import torch
    from ultralytics import YOLO
    from ultralytics.nn.tasks import DetectionModel
    source = YOLO(str(verified_weights(coco, COCO_SHA))).model.float()
    architecture = deepcopy(source.yaml)
    architecture["end2end"] = False
    model = DetectionModel(architecture, nc=1, verbose=False)
    model.end2end = False
    model.names = {0: "sign"}
    if initialization == "d4":
        state = torch.load(verified_weights(d4, D4_SHA), map_location="cpu", weights_only=True)
        model.load_state_dict(state["model"], strict=True)
    else:
        destination = model.state_dict()
        head = len(model.model)-1
        transferred = {k: v for k, v in source.state_dict().items() if k in destination and v.shape == destination[k].shape and not (k.startswith(f"model.{head}.") and ".cv3." in k)}
        if not transferred:
            raise ValueError("No COCO pretrained tensors transferred")
        model.load_state_dict(transferred, strict=False)
    return model.float().eval()


def sign_only_sgblur(path):
    import torch
    from torch import nn
    from ultralytics import YOLO
    original = YOLO(str(verified_weights(path, SGBLUR_SHA))).model.float().eval()
    if original.names.get(0) not in ("sign", "traffic_sign"):
        raise ValueError(f"SGBlur class zero must be confirmed as sign: {original.names}")
    model = deepcopy(original)
    head = model.model[-1]
    for branch in head.cv3:
        previous = branch[-1]
        replacement = nn.Conv2d(previous.in_channels, 1, 1)
        with torch.no_grad():
            replacement.weight.copy_(previous.weight[:1])
            replacement.bias.copy_(previous.bias[:1])
        branch[-1] = replacement
    head.nc = 1
    head.no = 4*head.reg_max+1
    model.names = {0: "sign"}
    pixels = torch.rand((1, 3, 256, 256), generator=torch.Generator().manual_seed(14))
    with torch.inference_mode():
        expected, actual = original(pixels)[0], model(pixels)[0]
    torch.testing.assert_close(actual, expected[:, :5], rtol=1e-5, atol=1e-5)
    return model.eval()


def save_yolo(path, model, epoch=-1):
    import torch
    temporary = Path(path).with_suffix(".tmp")
    torch.save({"model": deepcopy(model).cpu().float(), "epoch": epoch, "train_args": {"task": "detect", "imgsz": 1024}}, temporary)
    temporary.replace(path)


def ap_metrics(model_file, data_yaml, output, args, split="val"):
    from ultralytics import YOLO
    result = YOLO(str(model_file)).val(data=str(data_yaml), split=split, imgsz=args.imgsz, batch=args.batch,
        device=args.device, workers=2, rect=False, conf=.001, iou=.45, max_det=300, plots=False,
        project=str(output), name=f"ap-{split}", exist_ok=True, verbose=False, half=False)
    return {"precision": float(result.box.mp), "recall": float(result.box.mr), "ap50": float(result.box.map50), "ap50_95": float(result.box.map)}


def predict_records(model_file, frames, root, args):
    from ultralytics import YOLO
    from PIL import Image
    records = []
    paths = []
    for frame in frames:
        path = checked_path(root, frame["image_path"], frame["image_sha256"])
        with Image.open(path) as raster:
            if raster.size != (frame["width"], frame["height"]) or raster.getexif().get(274, 1) != 1:
                raise ValueError("Evaluation raster is not the reviewed upright raster")
        paths.append(str(path))
    results = YOLO(str(model_file)).predict(source=paths, stream=True, imgsz=args.imgsz, batch=args.batch,
        device=args.device, rect=False, conf=.001, iou=.45, max_det=300, half=False, verbose=False)
    for frame, result in zip(frames, results, strict=True):
        predictions = [{"box": box, "score": score} for box, score, cls in zip(result.boxes.xyxy.cpu().tolist(), result.boxes.conf.cpu().tolist(), result.boxes.cls.cpu().tolist()) if cls == 0]
        label = checked_path(root, frame["label_path"], frame["label_sha256"])
        records.append({"image_id": frame["image_id"], "group_id": frame["group_id"],
            "truth": read_yolo_labels(label, frame["width"], frame["height"]), "predictions": predictions,
            "acceptable_extra_candidates": frame.get("acceptable_extra_candidates", [])})
    return records


def plot_history(history, destination):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    figure, axes = plt.subplots(1, 2, figsize=(11, 4))
    for key, label in (("ap50_95", "AP50–95"), ("ap50", "AP50"), ("precision", "Precision"), ("recall", "Recall")):
        axes[0].plot([r["epoch"] for r in history], [r[key] for r in history], label=label)
    axes[0].set(xlabel="Epoch", ylabel="Development metric", ylim=(0, 1))
    axes[0].legend()
    for key in ("box", "cls", "dfl"):
        rows = [r for r in history if key in r.get("train_loss", {})]
        axes[1].plot([r["epoch"] for r in rows], [r["train_loss"][key] for r in rows], label=key)
    axes[1].set(xlabel="Epoch", ylabel="Mean training loss")
    axes[1].legend()
    figure.suptitle("Sign-only detector · development reference metrics")
    figure.tight_layout()
    figure.savefig(destination, dpi=150)
    plt.close(figure)


def train(args):
    if not re.fullmatch(r"[0-9a-f]{40}", args.dataset_revision):
        raise ValueError("Pin the full published overlay dataset revision")
    from ultralytics.models.yolo.detect import DetectionTrainer
    torch = ml_dependencies()
    torch.manual_seed(args.seed)
    random.seed(args.seed)
    manifest_path = Path(args.manifest).resolve()
    if sha(manifest_path) != args.manifest_sha256:
        raise ValueError("Manifest hash differs from frozen launch input")
    manifest = json.loads(manifest_path.read_text())
    output = Path(args.output).resolve()
    output.mkdir(parents=True, exist_ok=False)
    write(output/"manifest.json", manifest)
    data_yaml, parts = stage_dataset(manifest, Path(args.dataset_root), output/"data")
    model = sign_model(args.initialization, args.coco, args.d4)
    save_yolo(output/"initial.pt", model, 0)
    baseline = ap_metrics(output/"initial.pt", data_yaml, output/"epoch-000", args)
    best = {"epoch": 0, "ap50_95": baseline["ap50_95"]}
    save_yolo(output/"selected.pt", model, 0)
    history = [{"epoch": 0, **baseline, "duration_seconds": 0., "train_loss": {}, "learning_rates": {}}]
    write(output/"history.json", history)
    config = {"manifest_sha256": args.manifest_sha256, "dataset_root": str(Path(args.dataset_root).resolve()),
        "dataset_revision": args.dataset_revision, "source_dataset_revision": manifest["dataset_revision"],
        "review_provenance": manifest["review_provenance"], "initialization": args.initialization,
        "initial_checkpoint_sha256": sha(output/"initial.pt"), "script_sha256": sha(__file__), "torch": str(torch.__version__),
        "ultralytics": ULTRALYTICS_VERSION, "seed": args.seed, "epochs": args.epochs, "imgsz": args.imgsz, "batch": args.batch,
        "lr0": args.lr, "device": args.device, "gpu": torch.cuda.get_device_name(0), "amp_requested": args.amp, "split_frames": {k: len(v) for k,v in parts.items()},
        "optimizer": "AdamW", "warmup_epochs": 2., "warmup_bias_lr": args.lr, "warmup_momentum": .8,
        "selection": "highest development AP50-95, earliest epoch wins ties; epoch zero eligible", "test_usage_during_training": "Only file hashes checked; no test image decode, label parse, inference or selection"}
    write(output/"configuration.json", config)

    class APTrainer(DetectionTrainer):
        def build_dataset(self, img_path, mode="train", batch=None):
            # Pinned DetectionTrainer otherwise forces rectangular validation,
            # even with rect=False; keep epoch zero and all contenders aligned.
            from ultralytics.data import build_yolo_dataset
            from ultralytics.utils.torch_utils import unwrap_model
            stride = max(int(unwrap_model(self.model).stride.max()), 32)
            return build_yolo_dataset(self.args, img_path, batch, self.data, mode=mode, rect=False, stride=stride)

        def validate(self):
            measured = self.validator(self)
            measured.pop("fitness", None)
            fitness = float(measured[AP_KEY])
            if self.best_fitness is None or fitness > self.best_fitness:
                self.best_fitness = fitness
            return measured, fitness

    trainer = APTrainer(overrides={"model": str(output/"initial.pt"), "data": str(data_yaml), "epochs": args.epochs,
        "imgsz": args.imgsz, "batch": args.batch, "device": args.device, "workers": 4, "seed": args.seed,
        "deterministic": True, "optimizer": "AdamW", "lr0": args.lr, "lrf": .1, "weight_decay": .0005,
        "warmup_epochs": 2., "warmup_bias_lr": args.lr, "warmup_momentum": .8,
        "patience": 0, "freeze": None, "amp": args.amp, "rect": False,
        "mosaic": .25, "close_mosaic": 5, "mixup": 0., "fliplr": 0., "flipud": 0.,
        "degrees": 2., "translate": .05, "scale": .25, "hsv_h": .01, "hsv_s": .3, "hsv_v": .3,
        "iou": .45, "max_det": 300, "plots": True, "save": True, "save_period": 1,
        "project": str(output), "name": "fit", "exist_ok": False, "val": True, "pretrained": False})
    trainer.model = model
    clock = {"start": time.monotonic()}

    def start_epoch(_):
        clock["start"] = time.monotonic()

    def record_epoch(current):
        epoch = current.epoch + 1
        if epoch > args.epochs or any(row["epoch"] == epoch for row in history):
            return  # Pinned final_eval emits an extra callback at epochs+1.
        if current.batch_size != args.batch:
            raise RuntimeError("Trainer changed batch size during recovery; record a new explicitly configured run")
        values = current.metrics
        row = {"epoch": epoch, "precision": float(values["metrics/precision(B)"]), "recall": float(values["metrics/recall(B)"]),
            "ap50": float(values["metrics/mAP50(B)"]), "ap50_95": float(values[AP_KEY]),
            "duration_seconds": time.monotonic()-clock["start"],
            "actual_batch": current.batch_size,
            "train_loss": dict(zip(("box", "cls", "dfl"), [float(v) for v in current.tloss])),
            "validation_loss": {k: float(v) for k,v in values.items() if k.startswith("val/")},
            "learning_rates": {k: float(v) for k,v in current.lr.items()}}
        if not all(math.isfinite(row[k]) for k in ("precision", "recall", "ap50", "ap50_95")):
            raise RuntimeError("Nonfinite development metric")
        if row["ap50_95"] > best["ap50_95"]:
            best.update(epoch=epoch, ap50_95=row["ap50_95"])
            save_yolo(output/"selected.pt", current.ema.ema, epoch)
        history.append(row)
        with (output/"epochs.jsonl").open("a") as stream:
            stream.write(json.dumps(row, allow_nan=False)+"\n")
        write(output/"history.json", history)
        write(output/"selection.json", best)
        plot_history(history, output/"learning-curves.png")
        print(json.dumps({"stage": "epoch_complete", **row, "selected_epoch": best["epoch"]}), flush=True)

    trainer.add_callback("on_train_epoch_start", start_epoch)
    trainer.add_callback("on_fit_epoch_end", record_epoch)
    trainer.train()
    config['amp_enabled'] = bool(trainer.amp)
    write(output/'configuration.json', config)
    predictions = predict_records(output/"selected.pt", parts["validation"], Path(args.dataset_root).resolve(), args)
    sweep = threshold_sweep(predictions)
    write(output/"development-predictions.json", predictions)
    write(output/"development-threshold-sweep.json", sweep)
    seal = {"schema": "streetshots-detector-seal-v1", "checkpoint": "selected.pt", "checkpoint_sha256": sha(output/"selected.pt"),
        "selected_epoch": best["epoch"], "development_ap50_95": best["ap50_95"], "threshold": sweep["threshold"],
        "manifest_sha256": sha(output/"manifest.json"), "configuration_sha256": sha(output/"configuration.json"),
        "threshold_sweep_sha256": sha(output/"development-threshold-sweep.json"),
        "history_sha256": sha(output/"history.json"), "test_evaluated": False}
    write(output/"seal.json", seal)


def verified_run(run):
    run = Path(run).resolve()
    seal = json.loads((run/"seal.json").read_text())
    config = json.loads((run/"configuration.json").read_text())
    for path, expected in ((run/"manifest.json", seal["manifest_sha256"]), (run/"selected.pt", seal["checkpoint_sha256"]),
                           (run/"configuration.json", seal["configuration_sha256"]),
                           (run/"development-threshold-sweep.json", seal["threshold_sweep_sha256"]),
                           (run/"history.json", seal["history_sha256"])):
        if sha(path) != expected:
            raise ValueError(f"Sealed input changed: {path}")
    history = json.loads((run/"history.json").read_text())
    if [row["epoch"] for row in history] != list(range(config["epochs"]+1)):
        raise ValueError("Every planned training epoch plus epoch zero must be complete before arm selection")
    selected = max(history, key=lambda row: (row["ap50_95"], -row["epoch"]))
    if selected["epoch"] != seal["selected_epoch"] or selected["ap50_95"] != seal["development_ap50_95"]:
        raise ValueError("Sealed checkpoint does not match the development-only selection rule")
    if (run/"holdout-started.json").exists() or (run/"holdout-complete.json").exists():
        raise ValueError("This training cohort has already entered holdout evaluation")
    return seal, config, history


def choose_arm(candidates):
    if set(candidates) != {"d4", "coco"}:
        raise ValueError("Both d4 and coco initialization arms must be sealed")
    for candidate in candidates.values():
        if not math.isfinite(candidate["development_ap50_95"]):
            raise ValueError("Nonfinite development AP")
    # Within an arm, earliest epoch wins. Across arms, an exact AP tie prefers
    # the existing sign-pretrained d4 lineage; test metrics are never inputs.
    return max(candidates, key=lambda arm: (candidates[arm]["development_ap50_95"], arm == "d4"))


def plot_arm_comparison(histories, winner, destination):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    figure, axes = plt.subplots(2, 2, figsize=(11, 8))
    panels = (("ap50_95", "Development AP50–95"), ("ap50", "Development AP50"),
              ("precision", "Development precision"), ("recall", "Development recall"))
    for axis, (metric, title) in zip(axes.flat, panels):
        for arm, history in histories.items():
            axis.plot([r["epoch"] for r in history], [r[metric] for r in history], label=f"{arm} initialization")
            if metric == "ap50_95":
                chosen = max(history, key=lambda r: (r[metric], -r["epoch"]))
                axis.scatter([chosen["epoch"]], [chosen[metric]], marker="*", s=100)
        axis.set(title=title, xlabel="Epoch", ylim=(0, 1))
        axis.legend()
    figure.suptitle(f"Model-assisted reference labels · development-selected arm: {winner}")
    figure.tight_layout()
    figure.savefig(destination, dpi=150)
    plt.close(figure)


def select(args):
    runs = {"d4": Path(args.d4_run).resolve(), "coco": Path(args.coco_run).resolve()}
    inspected = {arm: verified_run(run) for arm,run in runs.items()}
    comparison_keys = ("dataset_revision", "seed", "epochs", "imgsz", "batch", "lr0", "script_sha256", "torch", "ultralytics",
                       "optimizer", "warmup_epochs", "warmup_bias_lr", "warmup_momentum")
    first_seal, first_config, _ = inspected["d4"]
    for arm, (seal, config, _) in inspected.items():
        if config["initialization"] != arm:
            raise ValueError("Arm path disagrees with recorded initialization")
        if seal["manifest_sha256"] != first_seal["manifest_sha256"] or any(config[key] != first_config[key] for key in comparison_keys):
            raise ValueError("Initialization arms must share frozen data, environment and training settings")
    candidates = {arm: {"run": str(runs[arm]), "seal_sha256": sha(runs[arm]/"seal.json"),
        "configuration_sha256": seal["configuration_sha256"], "history_sha256": seal["history_sha256"],
        "checkpoint_sha256": seal["checkpoint_sha256"], "selected_epoch": seal["selected_epoch"],
        "development_ap50_95": seal["development_ap50_95"], "threshold": seal["threshold"]}
        for arm, (seal, _, _) in inspected.items()}
    winner = choose_arm(candidates)
    destination = Path(args.output).resolve()
    destination.mkdir(parents=True, exist_ok=False)
    selection = {"schema": "streetshots-two-arm-selection-v1", "winner": winner, "candidates": candidates,
        "manifest_sha256": first_seal["manifest_sha256"], "selection_rule": "Maximum development AP50-95; earliest epoch within each arm; exact AP tie across arms prefers d4",
        "test_used_for_selection": False, "review_provenance": "model_assisted", "comparison_settings": {k:first_config[k] for k in comparison_keys}}
    write(destination/"arm-selection.json", selection)
    rows = []
    summaries = {}
    for arm, (_, _, history) in inspected.items():
        initial = history[0]["ap50_95"]
        for row in history:
            rows.append({"arm": arm, "epoch": row["epoch"], "ap50_95": row["ap50_95"], "ap50": row["ap50"],
                "precision": row["precision"], "recall": row["recall"], "ap50_95_delta_from_epoch_zero": row["ap50_95"]-initial,
                "duration_seconds": row["duration_seconds"], **{f"train_{k}":v for k,v in row.get("train_loss", {}).items()}})
        summaries[arm] = {"epoch_zero_ap50_95": initial, "selected_ap50_95": candidates[arm]["development_ap50_95"],
                          "ap50_95_improvement": candidates[arm]["development_ap50_95"]-initial,
                          "selected_epoch": candidates[arm]["selected_epoch"]}
    write(destination/"epoch-comparison.json", rows)
    fields = list(dict.fromkeys(k for row in rows for k in row))
    with (destination/"epoch-comparison.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    write(destination/"development-summary.json", {"winner": winner, "arms": summaries,
        "interpretation": "Development metrics against model-assisted complete-scene labels; no independent human-accuracy claim."})
    plot_arm_comparison({arm: parts[2] for arm,parts in inspected.items()}, winner, destination/"arm-learning-curves.png")
    print(json.dumps({"stage": "two_arm_selection_sealed", "winner": winner, "selection": str(destination/"arm-selection.json")}), flush=True)


def evaluation_inputs(args):
    """Resolve a sealed winner without permitting per-arm real holdout fishing."""
    selection_path = Path(args.selection).resolve() if args.selection else None
    if selection_path:
        selection = json.loads(selection_path.read_text())
        if selection.get("schema") != "streetshots-two-arm-selection-v1" or selection.get("test_used_for_selection") is not False:
            raise ValueError("Expected sealed development-only two-arm selection")
        if choose_arm(selection["candidates"]) != selection["winner"]:
            raise ValueError("Winner differs from the declared development selection rule")
        participating = {}
        for arm, record in selection["candidates"].items():
            run = Path(record["run"]).resolve()
            seal, config, _ = verified_run(run)
            if config["initialization"] != arm:
                raise ValueError("Selection arm label disagrees with its initialization")
            if sha(run/"seal.json") != record["seal_sha256"] or seal["manifest_sha256"] != selection["manifest_sha256"]:
                raise ValueError("An initialization arm changed after winner selection")
            if record["development_ap50_95"] != seal["development_ap50_95"] or record["selected_epoch"] != seal["selected_epoch"]:
                raise ValueError("Selection metrics differ from the sealed development result")
            participating[arm] = run
        run = participating[selection["winner"]]
        seal, config, _ = verified_run(run)
        return run, seal, config, participating, selection_path.parent, selection_path
    run = Path(args.run).resolve()
    manifest = json.loads((run/"manifest.json").read_text())
    if manifest.get("synthetic_fixture") is not True:
        raise ValueError("Real holdout evaluation requires --selection from both initialization arms")
    seal, config, _ = verified_run(run)
    return run, seal, config, {"synthetic_smoke": run}, run, None


def verified_evaluation_provenance(config, torch_version, ultralytics_version):
    """Bind evaluation to the exact recipe/runtime sealed before holdout access."""
    observed = {
        "script_sha256": sha(__file__),
        "torch": str(torch_version),
        "ultralytics": str(ultralytics_version),
    }
    for key, value in observed.items():
        if config.get(key) != value:
            raise ValueError(
                f"Evaluation {key} differs from the sealed training configuration"
            )
    return observed


def evaluate(args):
    run, seal, config, participating, comparison_root, selection_path = evaluation_inputs(args)
    torch = ml_dependencies()
    import ultralytics
    evaluation_provenance = verified_evaluation_provenance(
        config, torch.__version__, ultralytics.__version__
    )
    args.imgsz, args.batch = config["imgsz"], config["batch"]
    manifest = json.loads((run/"manifest.json").read_text())
    parts = partition_manifest(manifest)
    root = Path(config["dataset_root"]).resolve()
    destination = comparison_root/"comparison"
    destination.mkdir(exist_ok=False)
    save_yolo(destination/"d4.pt", sign_model("d4", args.coco, args.d4))
    save_yolo(destination/"sgblur-sign.pt", sign_only_sgblur(args.sgblur))
    models = {"student": run/"selected.pt", "d4": destination/"d4.pt", "sgblur": destination/"sgblur-sign.pt"}
    thresholds, development = {}, {}
    for name, path in models.items():
        records = predict_records(path, parts["validation"], root, args)
        sweep = threshold_sweep(records)
        if name == "student" and sweep["threshold"] != seal["threshold"]:
            raise ValueError("Sealed student threshold is not reproducible")
        thresholds[name] = sweep["threshold"]
        development[name] = {"checkpoint_sha256": sha(path), "threshold": sweep["threshold"],
            "counts": score_frames(records, sweep["threshold"]), "ap": ap_metrics(path, run/"data/data.yaml", destination/name, args)}
        write(destination/f"{name}-development-sweep.json", sweep)
    # Exclusive marker persists if evaluation fails: partial test exposure cannot
    # silently become an untouched rerun. Operator must investigate a failed run.
    test_seal = {"training_seal_sha256": sha(run/"seal.json"), "thresholds": thresholds,
                 "arm_selection_sha256": sha(selection_path) if selection_path else None,
                 "evaluation_provenance": evaluation_provenance,
                 "checkpoints": {name: sha(path) for name,path in models.items()}, "status": "started"}
    for protected_run in set(participating.values()) | {comparison_root}:
        with (protected_run/"holdout-started.json").open("x") as stream:
            json.dump(test_seal, stream, indent=2)
    report = {"review_provenance": "model_assisted", "evaluation_provenance": evaluation_provenance,
              "iou": .5, "nms_iou": .45, "prediction_floor": .001,
              "max_det": 300, "square_letterbox": True, "imgsz": args.imgsz, "development": development, "test": {}}
    for name, path in models.items():
        records = predict_records(path, parts["test"], root, args)
        scored = score_frames(records, thresholds[name])
        report["test"][name] = {"counts": scored, "bootstrap": bootstrap_groups(scored),
            "ap": ap_metrics(path, run/"data/data.yaml", destination/name, args, split="test")}
        write(destination/f"{name}-test-predictions.json", records)
        write(destination/"comparison.json", report)
    write(comparison_root/"holdout-complete.json", {**test_seal, "status": "complete", "comparison_sha256": sha(destination/"comparison.json")})


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    training = commands.add_parser("train")
    training.add_argument("--manifest", required=True)
    training.add_argument("--manifest-sha256", required=True)
    training.add_argument("--dataset-root", required=True)
    training.add_argument("--output", required=True)
    training.add_argument("--initialization", choices=("d4", "coco"), default="d4")
    training.add_argument("--epochs", type=int, default=40)
    training.add_argument("--dataset-revision", required=True, help="Immutable published label-overlay revision, distinct from the source monthly revision")
    training.add_argument("--amp", action=argparse.BooleanOptionalAction, default=True,
                          help="AMP requires the pinned runtime's native CUDA check; stage yolo26n.pt in working directory")
    training.add_argument("--imgsz", type=int, choices=(1024,), default=1024)
    training.add_argument("--batch", type=int, default=4)
    training.add_argument("--seed", type=int, default=14)
    training.add_argument("--lr", type=float, default=.0002)
    selection = commands.add_parser("select", help="Choose the initialization arm using development only")
    selection.add_argument("--d4-run", required=True)
    selection.add_argument("--coco-run", required=True)
    selection.add_argument("--output", required=True)
    evaluation = commands.add_parser("evaluate")
    source = evaluation.add_mutually_exclusive_group(required=True)
    source.add_argument("--selection", help="Sealed arm-selection.json for a real candidate comparison")
    source.add_argument("--run", help="Single-run evaluation is allowed only for synthetic smoke fixtures")
    evaluation.add_argument("--sgblur", required=True)
    for command in (training, evaluation):
        command.add_argument("--coco", required=True, help="Pinned yolo26n.pt, used for architecture and optional initialization")
        command.add_argument("--d4", required=True, help="Pinned d4 one-class state checkpoint")
        command.add_argument("--device", default="0")
    args = parser.parse_args()
    if args.command == "train" and (args.epochs < 1 or args.batch < 1 or not 0 < args.lr <= .001):
        parser.error("Positive epochs/batch and learning rate in (0, .001] required")
    if args.command != "select" and not re.fullmatch(r"\d", args.device):
        parser.error("This reproducible pilot supports one explicit CUDA device index")
    {"train": train, "select": select, "evaluate": evaluate}[args.command](args)


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2 or sys.argv[1] != "train":
        raise SystemExit("Mixed recipe permits training only; no holdout evaluation")
    main()
