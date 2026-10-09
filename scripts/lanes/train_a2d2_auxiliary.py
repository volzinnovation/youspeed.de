#!/usr/bin/env python3
"""Local A2D2-only marking-head pilot; the entire existing detector stays frozen.

This is an offline research artifact, not a deployable model pack. A2D2 solid and
dashed line pixels form one foreground class. Road area and ego-lane topology are
not inferred. Private video, retrospective labels, and sign labels are not inputs.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import random
import re
import shutil
import subprocess
import time
import warnings

import cv2
import numpy as np
import torch
from torch import nn
from torch.nn import functional as F

DETECTOR_SHA256 = "698a70566938d25c3c1eaa49b89fc176fe2f3a20631a9a01fa56035613c7972a"
DETECTOR_URL = "https://raw.githubusercontent.com/cquest/sgblur/169451970702aca0dde9ff3106dba0f67e0b88a8/models/yolo11n_panoramax.pt"
POSITIVE_RGB = ((255, 193, 37), (128, 0, 255))
IGNORE_RGB = ((96, 69, 143), (53, 46, 82), (72, 209, 204))


def training_device(value):
    """One explicit backend; CUDA indices are relative to CUDA_VISIBLE_DEVICES."""
    if value not in ("cpu", "mps", "cuda") and not re.fullmatch(r"cuda:(0|[1-9][0-9]*)", value):
        raise argparse.ArgumentTypeError("Use cpu, mps, cuda or cuda:N (one visible GPU)")
    return value


def validate_cuda_environment(seed):
    # These must be present before process startup / the first CUDA operation.
    # Setting PYTHONHASHSEED here would not reseed the running Python interpreter.
    if os.environ.get("CUBLAS_WORKSPACE_CONFIG") not in (":4096:8", ":16:8"):
        raise ValueError("CUDA requires CUBLAS_WORKSPACE_CONFIG=:4096:8 (or :16:8) before launch")
    if os.environ.get("PYTHONHASHSEED") != str(seed):
        raise ValueError("CUDA requires PYTHONHASHSEED matching --seed before launch")
    if os.environ.get("NVIDIA_TF32_OVERRIDE") not in (None, "0"):
        raise ValueError("NVIDIA_TF32_OVERRIDE must be unset or 0; training uses float32 without TF32")


def configure_execution(device, seed, cuda_determinism="seeded"):
    """Seed existing computations; do not replace unsupported CUDA kernels.

    The unchanged head/loss differentiates bilinear interpolation. PyTorch lists
    its CUDA backward as nondeterministic. Seeded mode therefore requests
    deterministic implementations where available and records warnings for the
    rest; strict mode fails. Neither implies equality with CPU/MPS or another
    CUDA hardware/software stack.
    https://docs.pytorch.org/docs/stable/generated/torch.use_deterministic_algorithms.html
    """
    training_device(device)
    if not 0 <= seed <= 2**32 - 1:
        raise ValueError("Seed must be in [0, 2**32-1] for the existing NumPy sampler")
    if cuda_determinism not in ("seeded", "strict"):
        raise ValueError("Unknown CUDA determinism policy")
    requested = device
    cuda_info = None
    if device.startswith("cuda"):
        validate_cuda_environment(seed)
        if not torch.cuda.is_available():
            raise ValueError("CUDA requested but unavailable; no fallback to another device")
        index = torch.device(device).index
        index = 0 if index is None else index
        if index >= torch.cuda.device_count():
            raise ValueError("CUDA index is outside visible devices")
        device = "cuda:%d" % index
        torch.cuda.set_device(index)
        torch.backends.cudnn.benchmark = False
        torch.backends.cudnn.deterministic = True
        torch.backends.cuda.matmul.allow_tf32 = False
        torch.backends.cudnn.allow_tf32 = False
        torch.set_float32_matmul_precision("highest")
        torch.use_deterministic_algorithms(True, warn_only=cuda_determinism == "seeded")
        properties = torch.cuda.get_device_properties(index)
        cuda_info = dict(index=index, name=properties.name,
                         capability=[properties.major, properties.minor],
                         totalMemoryBytes=properties.total_memory,
                         runtimeVersion=torch.version.cuda, cudnnVersion=torch.backends.cudnn.version(),
                         cudnnBenchmark=torch.backends.cudnn.benchmark,
                         cudnnDeterministic=torch.backends.cudnn.deterministic,
                         cudnnAllowTF32=torch.backends.cudnn.allow_tf32,
                         matmulAllowTF32=torch.backends.cuda.matmul.allow_tf32,
                         float32MatmulPrecision=torch.get_float32_matmul_precision())
    elif device == "mps" and not torch.backends.mps.is_available():
        raise ValueError("MPS requested but unavailable; no fallback to another device")
    torch.manual_seed(seed)
    np.random.seed(seed)
    random.seed(seed)
    cv2.setNumThreads(1)
    torch.set_num_threads(4)
    runtime = dict(requestedDevice=requested, device=device, seed=seed,
                   torchVersion=str(torch.__version__), pythonVersion=platform.python_version(),
                   platform=platform.platform(), numpyVersion=np.__version__, opencvVersion=cv2.__version__,
                   torchThreads=torch.get_num_threads(), opencvThreads=cv2.getNumThreads(),
                   cudaDeterminism=cuda_determinism if cuda_info else None,
                   deterministicAlgorithms=torch.are_deterministic_algorithms_enabled(),
                   deterministicWarnOnly=torch.is_deterministic_algorithms_warn_only_enabled(),
                   environment={k: os.environ.get(k) for k in
                                ("CUBLAS_WORKSPACE_CONFIG", "PYTHONHASHSEED", "CUDA_VISIBLE_DEVICES",
                                 "NVIDIA_VISIBLE_DEVICES", "NVIDIA_TF32_OVERRIDE")},
                   cuda=cuda_info,
                   scope="Seeded same-stack execution; no cross-device/version bitwise guarantee. "
                         "CUDA seeded mode permits kernels without deterministic implementations with warnings; strict mode rejects them. "
                         "Actual support depends on the runtime; inspect preflight results and training warnings.")
    return device, runtime


def training_preflight(device):
    """Exercise the unchanged head, full-resolution loss and AdamW on fake data.

    No data/holdout access, no feature-extractor change, and no consumption of the
    training initialization RNG stream. Only the selected GPU is used.
    """
    devices = [torch.device(device).index] if str(device).startswith("cuda") else []
    with torch.random.fork_rng(devices=devices), warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        head = AuxiliaryMarkingHead().to(device)
        features = (torch.ones(2, 64, 8, 8, device=device), torch.ones(2, 128, 4, 4, device=device))
        target = torch.zeros(2, 1, 32, 32, device=device)
        target[:, :, :, 12:14] = 1
        valid = torch.ones_like(target)
        optimizer = torch.optim.AdamW(head.parameters(), lr=.001, weight_decay=.0001)
        optimizer.zero_grad(set_to_none=True)
        loss = masked_loss(head(features), target, valid, 20.)
        loss.backward()
        if not bool(torch.isfinite(loss)) or not all(p.grad is not None and bool(torch.isfinite(p.grad).all()) for p in head.parameters()):
            raise ValueError("Synthetic training preflight produced non-finite loss/gradients")
        optimizer.step()
        if not all(bool(torch.isfinite(p).all()) for p in head.parameters()):
            raise ValueError("Synthetic training preflight produced non-finite parameters")
        synchronize(device)
        return dict(status="passed", device=str(device), loss=float(loss.detach()),
                    warnings=sorted(set(str(w.message) for w in caught)),
                    scope="One synthetic head/loss/AdamW update; not detector, dataset, accuracy or throughput qualification")


def sha256_file(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, sort_keys=True, indent=2) + "\n")


def state_hash(model):
    h = hashlib.sha256()
    for name, tensor in sorted(model.state_dict().items()):
        a = tensor.detach().cpu().contiguous().numpy()
        h.update(name.encode())
        h.update(str((a.shape, str(a.dtype))).encode())
        h.update(a.tobytes())
    return h.hexdigest()


class FrozenYOLOFeatures(nn.Module):
    """P2/P3 taps while retaining (and checking) the complete original detector."""

    def __init__(self, detector, layers=(2, 4)):
        super().__init__()
        self.detector = detector
        self.layers = tuple(layers)
        self.features = {}
        self.handles = []
        for p in self.detector.parameters():
            p.requires_grad_(False)
        for index in self.layers:
            self.handles.append(self.detector.model[index].register_forward_hook(
                lambda _m, _i, output, index=index: self.features.__setitem__(index, output.detach())))
        self.train(False)

    def train(self, mode=True):
        # Parent train() calls must never update pretrained BN running statistics.
        super().train(False)
        return self

    def forward(self, x):
        self.features.clear()
        with torch.no_grad():
            self.detector(x)
        return tuple(self.features[index] for index in self.layers)


class AuxiliaryMarkingHead(nn.Module):
    def __init__(self, channels=(64, 128), hidden=16):
        super().__init__()
        self.p2 = nn.Conv2d(channels[0], hidden, 1)
        self.p3 = nn.Conv2d(channels[1], hidden, 1)
        self.mix = nn.Sequential(nn.Conv2d(hidden * 2, hidden * 2, 3, padding=1,
                                          groups=hidden * 2), nn.ReLU(),
                                 nn.Conv2d(hidden * 2, 1, 1))

    def forward(self, features):
        low = self.p2(features[0])
        high = F.interpolate(self.p3(features[1]), low.shape[-2:], mode="bilinear",
                             align_corners=False)
        return self.mix(torch.cat((low, high), dim=1))


def load_detector(path, device="cpu"):
    if sha256_file(path) != DETECTOR_SHA256:
        raise ValueError("Detector does not match the pinned deployed source checkpoint")
    import ultralytics
    if ultralytics.__version__ != "8.4.56":
        raise ValueError("Use pinned ultralytics==8.4.56")
    return FrozenYOLOFeatures(ultralytics.YOLO(str(path)).model.float().to(device))


def load_auxiliary(checkpoint_path, detector_path, device="cpu"):
    checkpoint = torch.load(checkpoint_path, map_location="cpu", weights_only=True)
    config = checkpoint["config"]
    if sha256_file(detector_path) != config["detectorSha256"]:
        raise ValueError("Detector SHA differs from auxiliary training source")
    extractor = load_detector(detector_path, device)
    head = AuxiliaryMarkingHead(tuple(config["featureChannels"]), config["hiddenChannels"])
    head.load_state_dict(checkpoint["headState"])
    return extractor, head.to(device).eval(), config


def letterbox_rgb(rgb, size=640):
    h, w = rgb.shape[:2]
    if rgb.dtype != np.uint8 or rgb.shape != (h, w, 3):
        raise ValueError("Expected HWC uint8 RGB image")
    scale = min(size / w, size / h)
    rw, rh = round(w * scale), round(h * scale)
    left, top = (size - rw) // 2, (size - rh) // 2
    canvas = np.full((size, size, 3), 114, dtype=np.uint8)
    canvas[top:top + rh, left:left + rw] = cv2.resize(rgb, (rw, rh), interpolation=cv2.INTER_LINEAR)
    transform = {"originalWidth": w, "originalHeight": h, "inputSize": size,
                 "resizedWidth": rw, "resizedHeight": rh, "padLeft": left, "padTop": top}
    return torch.from_numpy(canvas.transpose(2, 0, 1).copy()).float() / 255, transform


def decode_labels(label_rgb, class_map):
    packed = (label_rgb[..., 0].astype(np.uint32) << 16) | (label_rgb[..., 1].astype(np.uint32) << 8) | label_rgb[..., 2]
    known = np.array([int(key.lstrip("#"), 16) for key in class_map], dtype=np.uint32)
    valid = np.isin(packed, known)
    positive = np.zeros(packed.shape, dtype=bool)
    for rgb in POSITIVE_RGB:
        positive |= np.all(label_rgb == rgb, axis=-1)
    for rgb in IGNORE_RGB:
        valid &= ~np.all(label_rgb == rgb, axis=-1)
    return positive, valid


def letterbox_labels(positive, valid, transform):
    size, rw, rh = (transform[k] for k in ("inputSize", "resizedWidth", "resizedHeight"))
    left, top = transform["padLeft"], transform["padTop"]
    result = []
    for source in (positive, valid):
        target = np.zeros((size, size), np.float32)
        # Exact nearest uses the same pixel-center convention as RGB linear resize.
        target[top:top + rh, left:left + rw] = cv2.resize(source.astype(np.uint8), (rw, rh), interpolation=cv2.INTER_NEAREST_EXACT)
        result.append(torch.from_numpy(target).unsqueeze(0))
    return tuple(result)


def validate_manifest(path):
    manifest = json.loads(Path(path).read_text())
    if manifest.get("dataset") != "A2D2":
        raise ValueError("Only the pinned A2D2 dataset is accepted")
    objects = {o["key"]: o for o in manifest["objects"]}
    if len(objects) != len(manifest["objects"]):
        raise ValueError("Duplicate source object key")
    for obj in objects.values():
        if not obj.get("sha256") or sha256_file(obj["local_path"]) != obj["sha256"]:
            raise ValueError("Source SHA-256 mismatch: " + obj["key"])
    date_split, sequence_split, seen_hashes, seen_pairs = {}, {}, {}, set()
    partitions = {split: [] for split in ("train", "validation", "test")}
    for pair in manifest["pairs"]:
        split, date, sequence = (pair[k] for k in ("split", "capture_date", "sequence"))
        if split not in partitions or date != sequence[:8]:
            raise ValueError("Invalid split/date identity")
        for value, mapping in ((date, date_split), (sequence, sequence_split)):
            if value in mapping and mapping[value] != split:
                raise ValueError("Date/sequence overlaps dataset partitions")
            mapping[value] = split
        rgb, label = pair["rgb"], pair["label"]
        if not rgb.startswith("camera_lidar_semantic/" + sequence + "/") or "/cam_front_center/" not in rgb:
            raise ValueError("Expected original A2D2 front-center RGB")
        if Path(rgb).name.replace("_camera_", "_label_") != Path(label).name:
            raise ValueError("RGB/semantic filename mismatch")
        if (rgb, label) in seen_pairs:
            raise ValueError("Duplicate RGB/label pair")
        seen_pairs.add((rgb, label))
        for key in (rgb, label):
            identity = objects[key]["sha256"]
            if identity in seen_hashes and seen_hashes[identity] != split:
                raise ValueError("Source hash overlaps dataset partitions")
            seen_hashes[identity] = split
        objects[pair["camera_info"]]
        partitions[split].append(pair)
    if not all(partitions.values()):
        raise ValueError("Require nonempty date-disjoint train/validation/test sets")
    class_key = next(k for k in objects if k.endswith("/class_list.json"))
    class_map = json.loads(Path(objects[class_key]["local_path"]).read_text())
    if class_map.get("#ffc125") != "Solid line" or class_map.get("#8000ff") != "Dashed line":
        raise ValueError("Unexpected A2D2 class mapping")
    return manifest, objects, partitions, class_map


def masked_loss(logits, target, valid, positive_weight):
    logits = F.interpolate(logits, target.shape[-2:], mode="bilinear", align_corners=False)
    bce = F.binary_cross_entropy_with_logits(logits, target, reduction="none",
                                            pos_weight=logits.new_tensor(positive_weight))
    bce = (bce * valid).sum() / valid.sum().clamp_min(1)
    p = logits.sigmoid() * valid
    t = target * valid
    dice = 1 - (2 * (p * t).sum() + 1) / (p.sum() + t.sum() + 1)
    return bce + dice


def metrics_from_counts(tp, fp, fn, tn):
    def one(a, b, c):
        return {"precision": a / max(1, a + b), "recall": a / max(1, a + c),
                "f1": 2 * a / max(1, 2 * a + b + c), "iou": a / max(1, a + b + c)}
    return {"counts": {"tp": tp, "fp": fp, "fn": fn, "tn": tn},
            "marking": one(tp, fp, fn), "background": one(tn, fn, fp)}


@torch.no_grad()
def evaluate(head, records, device, batch_size, positive_weight, size):
    head.eval()
    counts = np.zeros(4, np.int64)
    total_loss = 0
    for start in range(0, len(records), batch_size):
        batch = records[start:start + batch_size]
        features, target, valid = batch_tensors(batch, device)
        logits = head(features)
        total_loss += float(masked_loss(logits, target, valid, positive_weight)) * len(batch)
        pred = F.interpolate(logits, (size, size), mode="bilinear", align_corners=False).sigmoid() >= .5
        truth, mask = target.bool(), valid.bool()
        counts += np.array([int((pred & truth & mask).sum()), int((pred & ~truth & mask).sum()),
                            int((~pred & truth & mask).sum()), int((~pred & ~truth & mask).sum())])
    result = metrics_from_counts(*(int(x) for x in counts))
    result["loss"] = total_loss / len(records)
    result["frames"] = len(records)
    return result


def batch_tensors(batch, device):
    features = tuple(torch.stack([r["features"][i] for r in batch]).to(device) for i in range(2))
    return features, torch.stack([r["target"] for r in batch]).to(device), torch.stack([r["valid"] for r in batch]).to(device)


def synchronize(device):
    if str(device) == "mps":
        torch.mps.synchronize()
    elif str(device).startswith("cuda"):
        torch.cuda.synchronize(device)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, epilog=
        "CUDA launch environment: CUBLAS_WORKSPACE_CONFIG=:4096:8 and PYTHONHASHSEED matching --seed. "
        "Isolate the intended GPU with CUDA_VISIBLE_DEVICES or the container GPU selector; "
        "NVIDIA_TF32_OVERRIDE must be unset or 0. No cross-device bitwise guarantee.")
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--detector", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=15)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--input-size", type=int, default=640)
    parser.add_argument("--device", type=training_device, default="mps",
                        help="cpu, mps, cuda or cuda:N; index is relative to CUDA_VISIBLE_DEVICES")
    parser.add_argument("--cuda-determinism", choices=("seeded", "strict"), default="seeded",
                        help="CUDA: seeded retains unsupported deterministic kernels with recorded warnings; strict fails")
    parser.add_argument("--seed", type=int, default=20261008)
    parser.add_argument("--supersedes-invalid-run", type=Path,
                        help="Disclose a prior invalid evaluation; never silently erase test exposure")
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    if not (1 <= args.epochs <= 20) or args.input_size % 32 or args.batch_size < 1:
        parser.error("Use 1–20 epochs, input size divisible by 32, positive batch size")
    if args.output_dir.exists():
        parser.error("Output directory already exists; preserve prior experiments")
    try:
        args.device, runtime = configure_execution(args.device, args.seed, args.cuda_determinism)
        if args.device.startswith("cuda"):
            runtime["trainingPreflight"] = training_preflight(args.device)
    except (ValueError, RuntimeError) as error:
        parser.error(str(error))
    print(json.dumps(dict(stage="execution", **runtime)), flush=True)
    manifest, objects, partitions, class_map = validate_manifest(args.manifest)
    args.output_dir.mkdir(parents=True)
    shutil.copy2(__file__, args.output_dir / "train_a2d2_auxiliary.py")
    shutil.copy2(args.manifest, args.output_dir / "dataset-manifest.json")
    detector = load_detector(args.detector, args.device)
    head = AuxiliaryMarkingHead().to(args.device)
    config = {"schemaVersion": 1, "inputSize": args.input_size, "threshold": .5,
              "featureLayers": [2, 4], "featureChannels": [64, 128], "hiddenChannels": 16,
              "headParameters": sum(p.numel() for p in head.parameters()),
              "detectorParameters": sum(p.numel() for p in detector.parameters()),
              "detectorSha256": sha256_file(args.detector), "detectorURL": DETECTOR_URL,
              "detectorPath": str(args.detector.resolve()), "datasetManifestSha256": sha256_file(args.manifest),
              "trainingSourceSha256": sha256_file(__file__), "seed": args.seed,
              "epochs": args.epochs, "batchSize": args.batch_size, "device": args.device,
              "torchVersion": str(torch.__version__), "ultralyticsVersion": "8.4.56",
              "execution": runtime,
              "positiveRgb": POSITIVE_RGB, "ignoreRgb": IGNORE_RGB,
              "unknownRgbIgnored": True, "paddingIgnored": True, "cachePrecision": "float32",
              "rgbInterpolation": "OpenCV INTER_LINEAR", "labelInterpolation": "OpenCV INTER_NEAREST_EXACT",
              "input": "whole-field original distorted RGB letterbox; target-only; no augmentation",
              "optimizer": {"name": "AdamW", "learningRate": .001, "weightDecay": .0001},
              "selection": "maximum validation marking IoU at fixed threshold 0.5; earliest tie",
              "loss": "train-only inverse-frequency positive BCE weight capped at 20 plus soft Dice",
              "evaluation": "pixel micro metrics at letterboxed input resolution, ignored pixels excluded",
              "splitCounts": {k: len(v) for k, v in partitions.items()},
              "splitDates": {k: sorted(set(p["capture_date"] for p in v)) for k, v in partitions.items()},
              "qualification": ["A2D2-only supervised auxiliary-head prototype; no runtime integration or mobile export",
                                "Entire pretrained detector frozen, including BN and original sign/plate/face head",
                                "Marking confidence only; no road-area, ego-lane, or topology target",
                                "P2/P3 taps offer limited semantic context; no architecture tuning from test/private-video results",
                                "Small date-grouped pilot; held-out dates are few and not a production accuracy estimate",
                                "Private dashcam and retrospective weak labels excluded from training and checkpoint selection",
                                "Backend kernels may not be bitwise reproducible across hardware or dependency versions",
                                "CUDA seeded mode records unsupported deterministic kernels; strict mode fails instead"]}
    if args.supersedes_invalid_run:
        config["priorInvalidEvaluation"] = {
            "path": str(args.supersedes_invalid_run.resolve()),
            "metricsSha256": sha256_file(args.supersedes_invalid_run / "metrics.json"),
            "reason": "Correct label pixel-center alignment: legacy nearest replaced by nearest-exact",
            "scope": "Same architecture, split, seed, optimizer, epochs, threshold and selection criterion; no test-driven tuning",
            "testExposure": "Same test frames were evaluated in the invalid run; corrected scores are not a first blind look"}
    write_json(args.output_dir / "config.json", config)
    (args.output_dir / "environment.txt").write_text(subprocess.check_output([os.sys.executable, "-m", "pip", "freeze"], text=True))
    before_hash = state_hash(detector)
    before_file_hash = sha256_file(args.detector)
    cache = {}
    probe_input = probe_before = None
    cache_start = time.perf_counter()
    for split, pairs in partitions.items():
        cache[split] = []
        for index, pair in enumerate(pairs):
            rgb = cv2.cvtColor(cv2.imread(objects[pair["rgb"]]["local_path"]), cv2.COLOR_BGR2RGB)
            label = cv2.cvtColor(cv2.imread(objects[pair["label"]]["local_path"]), cv2.COLOR_BGR2RGB)
            if rgb.shape != label.shape:
                raise ValueError("Original RGB/label shapes differ")
            x, transform = letterbox_rgb(rgb, args.input_size)
            positive, valid = decode_labels(label, class_map)
            target, valid = letterbox_labels(positive, valid, transform)
            features = tuple(f.squeeze(0).cpu().clone() for f in detector(x.unsqueeze(0).to(args.device)))
            if tuple(f.shape for f in features) != ((64, args.input_size // 4, args.input_size // 4),
                                                  (128, args.input_size // 8, args.input_size // 8)):
                raise ValueError("Unexpected actual checkpoint feature shapes")
            cache[split].append({"features": features, "target": target, "valid": valid,
                                 "pair": pair, "transform": transform})
            if probe_input is None:
                probe_input = x.unsqueeze(0).to(args.device)
                with torch.no_grad():
                    probe_before = detector.detector(probe_input)[0].detach().cpu().clone()
            if (index + 1) % 32 == 0 or index + 1 == len(pairs):
                print(json.dumps({"stage": "cache", "split": split, "frames": index + 1,
                                  "elapsedSeconds": round(time.perf_counter() - cache_start, 2)}), flush=True)
    pos = sum(float((r["target"] * r["valid"]).sum()) for r in cache["train"])
    nvalid = sum(float(r["valid"].sum()) for r in cache["train"])
    if pos <= 0:
        raise ValueError("Training partition contains no positive marking pixels")
    positive_weight = min(20., max(1., (nvalid - pos) / pos))
    config["positiveWeight"] = positive_weight
    config["trainPositivePixels"] = int(pos)
    config["trainValidPixels"] = int(nvalid)
    write_json(args.output_dir / "config.json", config)
    optimizer = torch.optim.AdamW(head.parameters(), lr=.001, weight_decay=.0001)
    curves, best_iou, best_state, best_epoch = [], -1., None, None
    started = time.perf_counter()
    for epoch in range(1, args.epochs + 1):
        start = time.perf_counter()
        head.train()
        order = np.random.default_rng(args.seed + epoch).permutation(len(cache["train"]))
        total_loss = 0
        for offset in range(0, len(order), args.batch_size):
            batch = [cache["train"][i] for i in order[offset:offset + args.batch_size]]
            features, target, valid = batch_tensors(batch, args.device)
            optimizer.zero_grad(set_to_none=True)
            loss = masked_loss(head(features), target, valid, positive_weight)
            if not bool(torch.isfinite(loss)):
                raise ValueError("Non-finite training loss")
            loss.backward()
            optimizer.step()
            total_loss += float(loss.detach()) * len(batch)
        validation = evaluate(head, cache["validation"], args.device, args.batch_size, positive_weight, args.input_size)
        synchronize(args.device)
        row = {"epoch": epoch, "trainLoss": total_loss / len(order), "validation": validation,
               "epochSeconds": time.perf_counter() - start}
        curves.append(row)
        if validation["marking"]["iou"] > best_iou:
            best_iou, best_epoch = validation["marking"]["iou"], epoch
            best_state = {k: v.detach().cpu().clone() for k, v in head.state_dict().items()}
        write_json(args.output_dir / "curves.json", curves)
        print(json.dumps(row), flush=True)
    head.load_state_dict(best_state)
    head.eval()
    # The held-out test labels are scored exactly once after validation selection.
    test = evaluate(head, cache["test"], args.device, args.batch_size, positive_weight, args.input_size)
    with torch.no_grad():
        probe_after = detector.detector(probe_input)[0].detach().cpu()
    after_hash = state_hash(detector)
    frozen = {"stateHashBefore": before_hash, "stateHashAfter": after_hash,
              "checkpointHashBefore": before_file_hash, "checkpointHashAfter": sha256_file(args.detector),
              "stateIdentical": before_hash == after_hash,
              "probeShape": list(probe_before.shape), "probeEqual": torch.equal(probe_before, probe_after),
              "probeMaxAbsDifference": float((probe_before - probe_after).abs().max()),
              "allParametersFrozen": all(not p.requires_grad and p.grad is None for p in detector.parameters()),
              "allModulesEval": all(not m.training for m in detector.modules()),
              "probeSource": partitions["train"][0]["rgb"]}
    write_json(args.output_dir / "detector-preservation.json", frozen)
    if not all(frozen[k] for k in ("stateIdentical", "probeEqual", "allParametersFrozen", "allModulesEval")):
        raise RuntimeError("Frozen detector preservation failed")
    checkpoint = {"headState": best_state, "config": config,
                  "provenance": {"bestEpoch": best_epoch, "validationMarkingIoU": best_iou,
                                 "configSha256": sha256_file(args.output_dir / "config.json"),
                                 "detectorPreservation": frozen}}
    output_checkpoint = args.output_dir / "auxiliary-marking.pt"
    torch.save(checkpoint, output_checkpoint)
    metrics = {"bestEpoch": best_epoch, "validation": curves[best_epoch - 1]["validation"],
               "test": test, "testEvaluations": 1, "trainingSeconds": time.perf_counter() - started,
               "cacheSeconds": started - cache_start,
               "checkpointSha256": sha256_file(output_checkpoint)}
    write_json(args.output_dir / "metrics.json", metrics)
    # Fixed first four samples per partition, not chosen by outcome.
    overlay_dir = args.output_dir / "overlays"
    overlay_dir.mkdir()
    with torch.no_grad():
        for split in cache:
            for index, record in enumerate(cache[split][:4]):
                features, target, valid = batch_tensors([record], args.device)
                logits = head(features)
                p = F.interpolate(logits, (args.input_size, args.input_size), mode="bilinear", align_corners=False).sigmoid()[0, 0].cpu().numpy()
                rgb = cv2.cvtColor(cv2.imread(objects[record["pair"]["rgb"]]["local_path"]), cv2.COLOR_BGR2RGB)
                tensor, _ = letterbox_rgb(rgb, args.input_size)
                base = (tensor.permute(1, 2, 0).numpy() * 255).astype(np.uint8)
                mask = valid[0, 0].cpu().numpy().astype(bool)
                truth = target[0, 0].cpu().numpy().astype(bool) & mask
                pred = (p >= .5) & mask
                images = [base]
                for selected in (truth, pred):
                    panel = base.copy()
                    panel[selected] = (panel[selected] * .4 + np.array([0, 255, 0]) * .6).astype(np.uint8)
                    images.append(panel)
                canvas = cv2.cvtColor(np.concatenate(images, axis=1), cv2.COLOR_RGB2BGR)
                for j, text in enumerate(("RGB", "A2D2 solid + dash", "prediction >= 0.5")):
                    cv2.putText(canvas, split + ": " + text, (j * args.input_size + 10, 30), cv2.FONT_HERSHEY_SIMPLEX, .6, (255, 255, 255), 1, cv2.LINE_AA)
                cv2.imwrite(str(overlay_dir / (split + "-%02d.jpg" % index)), canvas)
                np.save(overlay_dir / (split + "-%02d-feature-probability.npy" % index), logits.sigmoid()[0, 0].cpu().numpy())
    print(json.dumps({"stage": "complete", "checkpoint": str(output_checkpoint), "metrics": metrics}), flush=True)


if __name__ == "__main__":
    main()
