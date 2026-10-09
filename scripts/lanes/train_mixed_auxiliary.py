#!/usr/bin/env python3
"""Compute-matched A2D2 versus A2D2+ZOD paint-head experiment, entirely offline.

Both arms start from identical random head weights. Only A2D2 validation selects
checkpoints; ZOD holdouts and private videos never choose epochs or thresholds.
The original detector, its input contract, and the phone apps are not changed.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess
import sys
import time

import cv2
import numpy as np
import torch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import train_a2d2_auxiliary as aux


def validate_zod_manifest(path, *, input_size=None):
    """Accept only hash-bound, complete visible-paint targets, with split guards."""
    manifest = json.loads(Path(path).read_text())
    if (manifest.get("dataset") != "ZOD" or manifest.get("target_kind") != "paint"
            or manifest.get("license") != "CC BY-SA 4.0"
            or not manifest.get("source_revision")):
        raise ValueError("Expected pinned ZOD visible-paint manifest with data license")
    if manifest.get("training_eligible") is not True:
        raise ValueError("ZOD importer has not qualified complete targets for training")
    cohort = manifest.get("cohort_selection")
    cohort_size = None
    if cohort is not None:
        qa_plan = cohort.get("qa_plan") if isinstance(cohort, dict) else None
        cohort_size = qa_plan.get("training_input_size") if isinstance(qa_plan, dict) else None
        if (type(cohort_size) is not int or not 32 <= cohort_size <= 1280 or cohort_size % 32
                or type(input_size) is not int or input_size != cohort_size):
            raise ValueError("Training input size must match predeclared ZOD cohort eligibility geometry")
    objects = {o["key"]: o for o in manifest["objects"]}
    if len(objects) != len(manifest["objects"]):
        raise ValueError("Duplicate ZOD object key")
    for key, obj in objects.items():
        if aux.sha256_file(obj["local_path"]) != obj["sha256"]:
            raise ValueError("ZOD source SHA-256 mismatch: " + key)
    partitions = {k: [] for k in ("train", "validation", "test")}
    identities, groups, seen_ids = {}, {}, set()
    for pair in manifest["pairs"]:
        split, frame_id = pair["split"], pair["frame_id"]
        if split not in partitions or frame_id in seen_ids:
            raise ValueError("Invalid split or duplicate ZOD exposure")
        seen_ids.add(frame_id)
        if pair["official_split"] not in ("train", "val", "validation"):
            raise ValueError("ZOD exposure lacks official split membership")
        if pair["official_split"] != "train" and split == "train":
            raise ValueError("Official ZOD validation cannot enter training")
        group = pair["group_id"]
        if not group or (group in groups and groups[group] != split):
            raise ValueError("ZOD collection/location group overlaps partitions")
        groups[group] = split
        identity = objects[pair["rgb"]]["sha256"]
        if identity in identities and identities[identity] != split:
            raise ValueError("ZOD image content overlaps partitions")
        identities[identity] = split
        coverage = pair.get("annotation_coverage")
        receipt_coverage = manifest.get("source_receipt", {}).get("annotation_coverage")
        if coverage is None:
            if receipt_coverage == "per_frame" or "coverage_counts" in manifest:
                raise ValueError("Per-frame coverage manifest has an unqualified row")
            # Legacy qualified complete-target manifests predate per-row coverage.
            coverage = receipt_coverage or "complete_lane_markings"
        if coverage not in ("complete_lane_markings", "positive_only"):
            raise ValueError("Unsupported ZOD annotation coverage")
        if coverage == "positive_only" and split != "train":
            raise ValueError("Positive-only ZOD rows cannot enter held-out evaluation")
        if receipt_coverage == "per_frame":
            expected_decision = "positive_only" if coverage == "positive_only" else "accept"
            if pair.get("coverage_decision") != expected_decision:
                raise ValueError("Coverage decision differs from the row's supervision")
        declared_size = pair.get("statistics", {}).get("training_input_size")
        if cohort_size is not None or declared_size is not None:
            if type(declared_size) is not int or declared_size != input_size:
                raise ValueError("ZOD row eligibility geometry differs from training input size")
        # All-black complete masks can legitimately repeat; do not deduplicate by mask hash.
        _, positive, valid = load_zod_pair(pair, objects)
        if coverage == "positive_only" and not np.array_equal(positive, valid):
            raise ValueError("Positive-only supervision cannot label unknown pixels as negatives")
        measured = dict(positive_pixels=int(np.count_nonzero(positive)), valid_pixels=int(np.count_nonzero(valid)),
                        negative_pixels=int(np.count_nonzero(valid & ~positive)))
        for key, value in measured.items():
            declared = pair.get("statistics", {}).get(key)
            if declared is not None and (type(declared) is not int or declared != value):
                raise ValueError("ZOD pixel statistics differ from source masks")
        partitions[split].append(dict(pair, annotation_coverage=coverage))
    if not partitions["train"] or not (partitions["validation"] or partitions["test"]):
        raise ValueError("Require nonempty ZOD train and independent held-out groups")
    return manifest, objects, partitions


def load_zod_pair(pair, objects):
    rgb = cv2.imread(objects[pair["rgb"]]["local_path"], cv2.IMREAD_COLOR)
    label = cv2.imread(objects[pair["label"]]["local_path"], cv2.IMREAD_UNCHANGED)
    valid = cv2.imread(objects[pair["valid"]]["local_path"], cv2.IMREAD_UNCHANGED)
    shape = (pair["height"], pair["width"])
    if rgb is None or rgb.shape != (*shape, 3):
        raise ValueError("ZOD RGB shape mismatch")
    for mask in (label, valid):
        if (mask is None or mask.shape != shape or mask.dtype != np.uint8
                or not np.isin(mask, (0, 255)).all()):
            raise ValueError("ZOD targets must be aligned binary uint8 PNGs")
    if np.any((label > 0) & (valid == 0)):
        raise ValueError("ZOD positives cannot overlap ignored pixels")
    if not np.any(valid):
        raise ValueError("ZOD target has no valid supervision")
    return cv2.cvtColor(rgb, cv2.COLOR_BGR2RGB), label > 0, valid > 0


def sampled_batches(a2d2, zod, *, arm, seed, epoch, steps, batch_size):
    """Cycle shuffled source indices. Each arm has identical update/pixel budgets."""
    if arm not in ("a2d2", "a2d2_zod") or steps < 1 or batch_size < 2 or batch_size % 2:
        raise ValueError("Use known arm, positive steps and even batch size >=2")
    if not a2d2 or (arm == "a2d2_zod" and not zod):
        raise ValueError("Empty training source")
    rng = np.random.default_rng(seed + epoch)

    def cycle(rows):
        while True:
            for index in rng.permutation(len(rows)):
                yield rows[index]

    a, z = cycle(a2d2), cycle(zod) if zod else None
    for _ in range(steps):
        if arm == "a2d2":
            yield [next(a) for _ in range(batch_size)]
        else:
            # Interleave so every batch has exactly equal source frame weight.
            yield [row for _ in range(batch_size // 2) for row in (next(a), next(z))]


def aligned_targets(positive, valid, transform):
    target, validity = aux.letterbox_labels(positive, valid, transform)
    if not bool(torch.isfinite(target).all() and torch.isfinite(validity).all()) or float(validity.sum()) <= 0:
        raise ValueError("No finite valid supervision remains after letterboxing")
    return target, validity


def checked_evaluate(*args, **kwargs):
    result = aux.evaluate(*args, **kwargs)

    def finite(value):
        if isinstance(value, dict):
            return all(finite(v) for v in value.values())
        if isinstance(value, list):
            return all(finite(v) for v in value)
        return not isinstance(value, (int, float)) or math.isfinite(value)

    if not finite(result):
        raise ValueError("Non-finite evaluation; checkpoint selection is invalid")
    return result


def feature_cache_plan(partitions_by_source, input_size, maximum_gib):
    """Bound retained float32 tensors before extraction; this is not peak RSS."""
    if not 32 <= input_size <= 1280 or input_size % 32:
        raise ValueError("Cache plan requires supported input geometry")
    if not math.isfinite(maximum_gib) or maximum_gib <= 0:
        raise ValueError("Cache tensor budget must be finite and positive")
    source_counts = {name: sum(map(len, partitions.values()))
                     for name, partitions in partitions_by_source.items()}
    # Two fixed feature taps plus full-resolution target and validity tensors.
    per_frame = 4 * (64 * (input_size // 4)**2 + 128 * (input_size // 8)**2 + 2 * input_size**2)
    total = sum(source_counts.values()) * per_frame
    numerator, denominator = maximum_gib.as_integer_ratio()
    maximum = numerator * 2**30 // denominator
    if total > maximum:
        raise ValueError("Feature cache requires %.3f GiB of tensors, above explicit %.3f GiB limit"
                         % (total / 2**30, maximum_gib))
    return dict(backend="host_ram", precision="float32", tensorBytesPerFrame=per_frame,
                sourceFrameCounts=source_counts, totalFrames=sum(source_counts.values()),
                estimatedTensorBytes=total, maximumTensorBytes=maximum,
                scope="Retained P2/P3 feature, target and validity tensors only; excludes image decode temporaries, "
                      "Python metadata, runtime allocations and training batches. Reserve additional process memory.")


def cached_tensor_bytes(cache):
    return sum(tensor.numel() * tensor.element_size()
               for partitions in cache.values() for rows in partitions.values() for row in rows
               for tensor in (*row["features"], row["target"], row["valid"]))


def declared_training_budget(partitions_by_source, epochs, steps, batch_size):
    if epochs < 1 or steps < 1 or batch_size < 2 or batch_size % 2:
        raise ValueError("Invalid comparison update budget")
    train_counts = {name: len(partitions["train"]) for name, partitions in partitions_by_source.items()}
    if set(train_counts) != {"A2D2", "ZOD"} or not all(train_counts.values()):
        raise ValueError("Both sources require nonempty training rows")
    updates, frames = epochs * steps, epochs * steps * batch_size
    exposures = {"a2d2": {"A2D2": frames}, "a2d2_zod": {"A2D2": frames // 2, "ZOD": frames // 2}}
    return dict(optimizerUpdatesPerArm=updates, frameExposuresPerArm=frames,
                selectionEvaluationsPerArm=epochs, trainingFramesPerSource=train_counts,
                sourceFrameExposuresByArm=exposures,
                meanExposuresPerTrainingFrameByArm={arm: {source: count / train_counts[source]
                                                         for source, count in counts.items()}
                                                   for arm, counts in exposures.items()},
                scope="Fixed source-composition comparison; same update/frame budget per arm. "
                      "Mean exposures do not imply identical per-frame sampling counts.")


def exposure_distribution(cache, frame_exposures):
    result = {}
    for source, partitions in cache.items():
        counts = [frame_exposures[(source, row["identity"])] for row in partitions["train"]]
        result[source] = dict(trainingFrames=len(counts), sampledFrames=sum(value > 0 for value in counts),
                              neverSampledFrames=sum(value == 0 for value in counts),
                              minimum=min(counts), maximum=max(counts), mean=sum(counts) / len(counts),
                              histogram={str(value): count for value, count in sorted(Counter(counts).items())})
    return result


def cached_supervision_summary(cache):
    """Count actual loss-space targets, preserving unknown/ignored pixels."""
    result = {}
    for source, partitions in cache.items():
        result[source] = {}
        for split, rows in partitions.items():
            positive = valid = cells = 0
            coverage, decisions = {}, Counter()
            for row in rows:
                p = int((row["target"] * row["valid"]).sum())
                v = int(row["valid"].sum())
                positive += p
                valid += v
                cells += row["valid"].numel()
                pair = row.get("pair", {})
                mode = pair.get("annotation_coverage", "complete_lane_markings") if source == "ZOD" else "dense_semantic"
                decision = pair.get("coverage_decision", "legacy_complete_target") if source == "ZOD" else "A2D2_class_map"
                decisions[decision] += 1
                stats = coverage.setdefault(mode, dict(frames=0, positivePixels=0, validPixels=0, negativePixels=0))
                stats["frames"] += 1
                stats["positivePixels"] += p
                stats["validPixels"] += v
                stats["negativePixels"] += v - p
            result[source][split] = dict(frames=len(rows), positivePixels=positive, validPixels=valid,
                                         negativePixels=valid-positive, ignoredOrPaddingPixels=cells-valid,
                                         coverage=coverage, coverageDecisions=dict(decisions))
    return result


def cache_source(name, partitions, objects, class_map, detector, device, size):
    cache = {}
    for split, pairs in partitions.items():
        cache[split] = []
        for pair in pairs:
            if name == "ZOD":
                rgb, positive, valid = load_zod_pair(pair, objects)
            else:
                rgb = cv2.cvtColor(cv2.imread(objects[pair["rgb"]]["local_path"]), cv2.COLOR_BGR2RGB)
                label = cv2.cvtColor(cv2.imread(objects[pair["label"]]["local_path"]), cv2.COLOR_BGR2RGB)
                if rgb.shape != label.shape:
                    raise ValueError("A2D2 RGB/label shape mismatch")
                positive, valid = aux.decode_labels(label, class_map)
            x, transform = aux.letterbox_rgb(rgb, size)
            target, validity = aligned_targets(positive, valid, transform)
            features = tuple(f.squeeze(0).cpu().clone() for f in detector(x[None].to(device)))
            if tuple(f.shape for f in features) != ((64, size // 4, size // 4), (128, size // 8, size // 8)):
                raise ValueError("Unexpected frozen detector feature geometry")
            cache[split].append(dict(features=features, target=target, valid=validity,
                                     pair=pair, transform=transform, dataset=name,
                                     identity=pair["rgb"]))
        print(json.dumps(dict(stage="cache", dataset=name, split=split, frames=len(pairs))), flush=True)
    if not any(float((r["target"] * r["valid"]).sum()) for r in cache["train"]):
        raise ValueError(name + " training split has no usable positive paint")
    return cache


def train_arm(arm, cache, initial, config, output, device):
    output.mkdir()
    head = aux.AuxiliaryMarkingHead().to(device)
    head.load_state_dict(initial)
    optimizer = torch.optim.AdamW(head.parameters(), lr=.001, weight_decay=.0001)
    curves, exposures, frame_exposures = [], Counter(), Counter()
    best_iou, best_state, best_epoch = -1., None, None
    started = time.perf_counter()
    for epoch in range(1, config["epochs"] + 1):
        head.train()
        total_loss = 0.
        for batch in sampled_batches(cache["A2D2"]["train"], cache["ZOD"]["train"], arm=arm,
                                     seed=config["seed"], epoch=epoch, steps=config["stepsPerEpoch"],
                                     batch_size=config["batchSize"]):
            exposures.update(r["dataset"] for r in batch)
            frame_exposures.update((r["dataset"], r["identity"]) for r in batch)
            features, target, valid = aux.batch_tensors(batch, device)
            optimizer.zero_grad(set_to_none=True)
            loss = aux.masked_loss(head(features), target, valid, config["positiveWeight"])
            if not torch.isfinite(loss):
                raise ValueError("Non-finite training loss")
            loss.backward()
            optimizer.step()
            total_loss += float(loss.detach())
        validation = checked_evaluate(head, cache["A2D2"]["validation"], device,
                                  config["batchSize"], config["positiveWeight"], config["inputSize"])
        row = dict(epoch=epoch, trainLoss=total_loss / config["stepsPerEpoch"], validation=validation)
        curves.append(row)
        if validation["marking"]["iou"] > best_iou:
            best_iou, best_epoch = validation["marking"]["iou"], epoch
            best_state = {k: v.detach().cpu().clone() for k, v in head.state_dict().items()}
        aux.write_json(output / "curves.json", curves)
        print(json.dumps(dict(stage="train", arm=arm, **row)), flush=True)
    head.load_state_dict(best_state)
    # All external holdouts are evaluated only after the arm's selection is final.
    metrics = dict(bestEpoch=best_epoch, validation=curves[best_epoch - 1]["validation"],
                   sourceFrameExposures=dict(exposures),
                   uniqueSourceFrames=dict(Counter(source for source, _ in frame_exposures)),
                   sourceFrameExposureDistribution=exposure_distribution(cache, frame_exposures),
                   optimizerUpdates=config["stepsPerEpoch"] * config["epochs"],
                   trainingSeconds=time.perf_counter() - started, evaluation={})
    for name, source in cache.items():
        for split in ("validation", "test"):
            if name == "A2D2" and split == "validation":
                continue
            if source[split]:
                details = {"include_frame_counts": True} if config.get("holdoutFrameCounts", False) else {}
                metrics["evaluation"][name + "/" + split] = checked_evaluate(
                    head, source[split], device, config["batchSize"], config["positiveWeight"], config["inputSize"], **details)
    arm_config = dict(config, arm=arm)
    aux.write_json(output / "config.json", arm_config)
    checkpoint = dict(headState=best_state, config=arm_config,
                      provenance=dict(bestEpoch=best_epoch, validationMarkingIoU=best_iou))
    # No loadable checkpoint exists until the complete experiment verifies the
    # unchanged detector, including its tensors, modes, file and output probe.
    aux.write_json(output / "provisional-metrics.json", metrics)
    return metrics, checkpoint


def finalize_arm(output, metrics, checkpoint, preservation, source_supervision_sha256=None):
    required = ("stateIdentical", "probeEqual", "allParametersFrozen", "allModulesEval")
    if (not all(preservation.get(k) is True for k in required)
            or preservation.get("checkpointHashBefore") != preservation.get("checkpointHashAfter")
            or preservation.get("checkpointHashBefore") != checkpoint["config"]["detectorSha256"]):
        raise ValueError("Cannot finalize without successful detector preservation proof")
    checkpoint["provenance"]["detectorPreservation"] = preservation
    checkpoint["provenance"]["configSha256"] = aux.sha256_file(output / "config.json")
    if source_supervision_sha256 is not None:
        checkpoint["provenance"]["sourceSupervisionSha256"] = source_supervision_sha256
        metrics["sourceSupervisionSha256"] = source_supervision_sha256
    torch.save(checkpoint, output / "auxiliary-marking.pt")
    metrics["checkpointSha256"] = aux.sha256_file(output / "auxiliary-marking.pt")
    aux.write_json(output / "metrics.json", metrics)


def build_parser():
    parser = argparse.ArgumentParser(description=__doc__, epilog=
        "CUDA launch environment: CUBLAS_WORKSPACE_CONFIG=:4096:8 and PYTHONHASHSEED matching --seed. "
        "Isolate the intended GPU with CUDA_VISIBLE_DEVICES or the container GPU selector; "
        "NVIDIA_TF32_OVERRIDE must be unset or 0. No cross-device bitwise guarantee.")
    parser.add_argument("--a2d2-manifest", type=Path, required=True)
    parser.add_argument("--zod-manifest", type=Path, required=True)
    parser.add_argument("--detector", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--device", type=aux.training_device, default="mps",
                        help="cpu, mps, cuda or cuda:N; index is relative to CUDA_VISIBLE_DEVICES")
    parser.add_argument("--cuda-determinism", choices=("seeded", "strict"), default="seeded",
                        help="CUDA: seeded retains unsupported deterministic kernels with recorded warnings; strict fails")
    parser.add_argument("--epochs", type=int, default=15)
    parser.add_argument("--steps-per-epoch", type=int, default=16)
    parser.add_argument("--batch-size", type=int, default=8)
    parser.add_argument("--input-size", type=int, default=640)
    parser.add_argument("--max-source-frames", type=int, default=512,
                        help="Per-source cache bound; default total ceiling ~9.3GB for192 A2D2+512 ZOD at640")
    parser.add_argument("--max-cache-gib", type=float, default=12.,
                        help="Retained host tensor budget in GiB; excludes decode/runtime/batch overhead")
    parser.add_argument("--holdout-frame-counts", action="store_true",
                        help="Record frame/group-bound confusion counts after checkpoint selection, for grouped analysis")
    parser.add_argument("--seed", type=int, default=20261008)
    return parser


def main():
    parser = build_parser()
    args = parser.parse_args()
    if (not 1 <= args.epochs <= 20 or not 1 <= args.steps_per_epoch <= 256
            or not 2 <= args.batch_size <= 32 or args.batch_size % 2
            or not 32 <= args.input_size <= 1280 or args.input_size % 32):
        parser.error("Use bounded epochs/steps, even batch size and input divisible by32")
    if args.output_dir.exists():
        parser.error("Preserve experiments: output directory must be new")
    repository = Path(__file__).resolve().parents[2]
    if args.output_dir.resolve() == repository or repository in args.output_dir.resolve().parents:
        parser.error("Keep dataset and experiment artifacts outside repository")
    try:
        args.device, runtime = aux.configure_execution(args.device, args.seed, args.cuda_determinism)
        if args.device.startswith("cuda"):
            runtime["trainingPreflight"] = aux.training_preflight(args.device)
    except (ValueError, RuntimeError) as error:
        parser.error(str(error))
    print(json.dumps(dict(stage="execution", **runtime)), flush=True)
    a_manifest, a_objects, a_parts, class_map = aux.validate_manifest(args.a2d2_manifest)
    z_manifest, z_objects, z_parts = validate_zod_manifest(args.zod_manifest, input_size=args.input_size)
    if args.max_source_frames < 1 or any(sum(map(len, p.values())) > args.max_source_frames for p in (a_parts, z_parts)):
        parser.error("Source exceeds explicit feature-cache frame budget; prepare a bounded subset first")
    try:
        cache_plan = feature_cache_plan({"A2D2": a_parts, "ZOD": z_parts}, args.input_size, args.max_cache_gib)
    except ValueError as error:
        parser.error(str(error))
    # Cross-corpus identical imagery cannot cross train/holdout either.
    rgb_splits = {}
    for parts, objects in ((a_parts, a_objects), (z_parts, z_objects)):
        for split, pairs in parts.items():
            for pair in pairs:
                identity = objects[pair["rgb"]]["sha256"]
                if identity in rgb_splits and rgb_splits[identity] != split:
                    raise ValueError("Cross-corpus image content overlaps partitions")
                rgb_splits[identity] = split
    detector = aux.load_detector(args.detector, args.device)
    initial = {k: v.detach().cpu().clone() for k, v in aux.AuxiliaryMarkingHead().state_dict().items()}
    initial_hash = hashlib.sha256(b"".join(k.encode() + v.numpy().tobytes() for k, v in sorted(initial.items()))).hexdigest()
    before = aux.state_hash(detector)
    probe_rgb = cv2.cvtColor(cv2.imread(a_objects[a_parts["train"][0]["rgb"]]["local_path"]), cv2.COLOR_BGR2RGB)
    probe = aux.letterbox_rgb(probe_rgb, args.input_size)[0][None].to(args.device)
    with torch.no_grad():
        probe_before = detector.detector(probe)[0].detach().cpu().clone()
    config = dict(schemaVersion=1, inputSize=args.input_size, threshold=.5,
                  featureLayers=[2, 4], featureChannels=[64, 128], hiddenChannels=16, headParameters=3457,
                  detectorSha256=aux.sha256_file(args.detector), detectorPath=str(args.detector.resolve()),
                  seed=args.seed, epochs=args.epochs, stepsPerEpoch=args.steps_per_epoch,
                  batchSize=args.batch_size, positiveWeight=20., device=args.device,
                  execution=runtime,
                  featureCache=cache_plan,
                  computeBudget=declared_training_budget({"A2D2": a_parts, "ZOD": z_parts}, args.epochs,
                                                        args.steps_per_epoch, args.batch_size),
                  holdoutFrameCounts=args.holdout_frame_counts,
                  headInitialStateSha256=initial_hash,
                  selection="Maximum A2D2 validation paint IoU, threshold0.5, earliest tie, both arms",
                  sampling="Fixed updates; baseline all A2D2; mixture 50:50 frame counts within every batch; seeded cycles",
                  loss="Pooled valid-pixel BCE positive weight20 plus soft Dice; identical both arms",
                  transform="RGB INTER_LINEAR + binary targets INTER_NEAREST_EXACT letterbox; no augmentation",
                  sourceManifestSha256={"A2D2": aux.sha256_file(args.a2d2_manifest), "ZOD": aux.sha256_file(args.zod_manifest)},
                  sourceCodeSha256={Path(p).name: aux.sha256_file(p) for p in (__file__, aux.__file__)},
                  splitCounts={name: {k: len(v) for k, v in part.items()} for name, part in (("A2D2", a_parts), ("ZOD", z_parts))},
                  qualification=["Developmental pilot, not an accuracy or deployment qualification",
                                 "A2D2 holdout previously exposed in earlier pilot; not a fresh blind evaluation",
                                 "Compute-matched mixture halves A2D2 frame exposures; not an added-compute comparison",
                                 "All private videos and retrospective labels excluded from training/selection",
                                 "ZOD holdouts scored after selection; any subsequent tuning requires fresh holdout",
                                 "Entire detector frozen; no phone export/runtime or speed-reference changes",
                                 "Frame-balanced sampling is not equal per-source loss weight; valid pixel counts differ",
                                 "Backend kernels may not reproduce bitwise on other hardware/software",
                                 "CUDA seeded mode records unsupported deterministic kernels; strict mode fails instead"])
    args.output_dir.mkdir(parents=True)
    # Persist protocol before any feature extraction, optimizer step or holdout score.
    aux.write_json(args.output_dir / "protocol.json", config)
    for path in (__file__, aux.__file__):
        shutil.copy2(path, args.output_dir / Path(path).name)
    for name, path in (("a2d2", args.a2d2_manifest), ("zod", args.zod_manifest)):
        shutil.copy2(path, args.output_dir / (name + "-manifest.json"))
    (args.output_dir / "environment.txt").write_text(subprocess.check_output([sys.executable, "-m", "pip", "freeze"], text=True))
    cache = {"A2D2": cache_source("A2D2", a_parts, a_objects, class_map, detector, args.device, args.input_size),
             "ZOD": cache_source("ZOD", z_parts, z_objects, None, detector, args.device, args.input_size)}
    observed_cache_bytes = cached_tensor_bytes(cache)
    if observed_cache_bytes != cache_plan["estimatedTensorBytes"]:
        raise RuntimeError("Actual cache tensors differ from the declared allocation plan; training not started")
    aux.write_json(args.output_dir / "feature-cache.json", dict(cache_plan, observedTensorBytes=observed_cache_bytes))
    supervision = cached_supervision_summary(cache)
    if supervision["A2D2"]["train"]["negativePixels"] <= 0:
        raise RuntimeError("A2D2 training cache must provide known-negative supervision")
    supervision_path = args.output_dir / "source-supervision.json"
    aux.write_json(supervision_path, dict(sourceManifestSha256=config["sourceManifestSha256"],
                                         inputSize=args.input_size, rasterSpace="letterboxed_loss_input",
                                         bySource=supervision,
                                         interpretation="50:50 frame sampling is not equal valid-pixel loss weight. "
                                                        "Positive-only ZOD rows contribute no negative pixels; A2D2 supplies dense known negatives. "
                                                        "The existing pooled valid-pixel BCE plus Dice loss is unchanged."))
    source_supervision_sha256 = aux.sha256_file(supervision_path)
    results, checkpoints = {}, {}
    for arm in ("a2d2", "a2d2_zod"):
        results[arm], checkpoints[arm] = train_arm(arm, cache, initial, config, args.output_dir / arm, args.device)
    with torch.no_grad():
        probe_after = detector.detector(probe)[0].detach().cpu()
    preservation = dict(stateHashBefore=before, stateHashAfter=aux.state_hash(detector),
                        stateIdentical=before == aux.state_hash(detector), probeEqual=torch.equal(probe_before, probe_after),
                        probeMaxAbsDifference=float((probe_before - probe_after).abs().max()),
                        checkpointHashBefore=config["detectorSha256"], checkpointHashAfter=aux.sha256_file(args.detector),
                        allParametersFrozen=all(not p.requires_grad and p.grad is None for p in detector.parameters()),
                        allModulesEval=all(not m.training for m in detector.modules()))
    aux.write_json(args.output_dir / "detector-preservation.json", preservation)
    if (not all(preservation[k] for k in ("stateIdentical", "probeEqual", "allParametersFrozen", "allModulesEval"))
            or preservation["checkpointHashBefore"] != preservation["checkpointHashAfter"]):
        raise RuntimeError("Frozen detector preservation failed; experiment not qualified")
    for arm in results:
        finalize_arm(args.output_dir / arm, results[arm], checkpoints[arm], preservation, source_supervision_sha256)
    aux.write_json(args.output_dir / "comparison.json", results)
    print(json.dumps(dict(stage="complete", output=str(args.output_dir))), flush=True)


if __name__ == "__main__":
    main()
