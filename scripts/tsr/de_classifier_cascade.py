#!/usr/bin/env python3
"""One bounded, diagnostic MobileNet Small -> YOLO crop-classifier cascade.

Only existing dev labels calibrate temperature and select a confidence gate.
The gate is persisted before report metrics are computed. Both component models
were selected using the full historical validation in an earlier experiment:
this partition is NOT an independent field test or a phone latency benchmark.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np


THRESHOLDS = (0., .5, .6, .7, .8, .85, .9, .95, .97, .99, 1.)
MACRO_TOLERANCE = .002
KEYS = ("val_logits", "val_labels", "class_names", "model_class_names",
        "val_sample_ids", "val_group_ids", "dev_indices", "report_indices",
        "train_sample_ids", "train_group_ids")
LIMITATIONS = [
    "Both frozen neural components were selected earlier on full reused validation",
    "This dev/report split prevents additional gate tuning on report; it does not undo earlier model-selection leakage",
    "Historical validation and upstream teacher exposure are unresolved; these are diagnostic metrics, not independent field F1",
    "City report support is one group; the original dev partition has no city truth",
    "The gate tests pre-cropped classification, not detection, localization or field false positives",
    "CPU component arithmetic estimates exclude decoding, resizing, routing, model loading, memory pressure and device execution",
    "Two resident networks require more storage/memory; native export and phone latency are unmeasured",
]


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dump(path, value):
    temporary = Path(path).with_suffix(".json.tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def validate_pair(small, yolo):
    """Reject remapping, mismatched observations, and new cross-partition leaks."""
    for family, arrays in (("small", small), ("yolo", yolo)):
        if missing := set(KEYS) - set(arrays):
            raise ValueError(f"{family}: missing arrays {sorted(missing)}")
        names = arrays["class_names"]
        if (names.dtype.kind not in "US" or names.shape != (136,)
                or len(set(names.tolist())) != 136 or names[-2:].tolist() != ["city:start", "city:end"]):
            raise ValueError("Require unique DE136 class order ending city:start/city:end")
        if not np.array_equal(names, arrays["model_class_names"]):
            raise ValueError("Model class order differs from global class order")
        logits, labels = arrays["val_logits"], arrays["val_labels"]
        if (labels.ndim != 1 or not len(labels) or labels.dtype.kind not in "iu"
                or (labels < 0).any() or (labels >= len(names)).any()):
            raise ValueError("Invalid validation target indices")
        count = len(labels)
        if logits.shape != (count, len(names)) or logits.dtype.kind != "f" or not np.isfinite(logits).all():
            raise ValueError("Require finite floating logits [rows,136]")
        for prefix, expected in (("val", count), ("train", None)):
            ids, groups = arrays[f"{prefix}_sample_ids"], arrays[f"{prefix}_group_ids"]
            if (ids.ndim != 1 or not len(ids) or groups.shape != ids.shape
                    or ids.dtype.kind not in "US" or groups.dtype.kind not in "US"
                    or not all(ids) or not all(groups) or len(set(ids.tolist())) != len(ids)
                    or (expected is not None and len(ids) != expected)):
                raise ValueError("Require aligned, nonempty groups and unique sample IDs")
        for key in ("sample_ids", "group_ids"):
            if set(arrays[f"train_{key}"].tolist()) & set(arrays[f"val_{key}"].tolist()):
                raise ValueError(f"Train/validation {key} overlap")
        dev, report = arrays["dev_indices"], arrays["report_indices"]
        for indices in (dev, report):
            if (indices.ndim != 1 or not len(indices) or indices.dtype.kind not in "iu"
                    or (indices < 0).any() or (indices >= count).any()
                    or len(set(indices.tolist())) != len(indices)):
                raise ValueError("Invalid partition indices")
        if set(dev.tolist()) & set(report.tolist()) or set(dev.tolist()) | set(report.tolist()) != set(range(count)):
            raise ValueError("Partitions must cover validation exactly once")
        if set(arrays["val_group_ids"][dev].tolist()) & set(arrays["val_group_ids"][report].tolist()):
            raise ValueError("Dev/report group overlap")
    for key in KEYS:
        if key != "val_logits" and not np.array_equal(small[key], yolo[key]):
            raise ValueError(f"Cascade sources disagree on exact {key} order")
    return small["class_names"].tolist()


def softmax(logits, temperature):
    logits = np.asarray(logits, dtype=np.float64)
    if (logits.ndim != 2 or not len(logits) or not np.isfinite(logits).all()
            or not np.isfinite(temperature) or temperature <= 0):
        raise ValueError("Finite logits and positive temperature required")
    shifted = (logits - logits.max(axis=1, keepdims=True)) / temperature
    values = np.exp(shifted)
    return values / values.sum(axis=1, keepdims=True)


def negative_log_likelihood(logits, labels, temperature):
    # Log-sum-exp avoids a probability floor changing the calibration objective.
    logits = np.asarray(logits, dtype=np.float64)
    centered = (logits - logits.max(axis=1, keepdims=True)) / temperature
    return float((np.log(np.exp(centered).sum(axis=1)) - centered[np.arange(len(labels)), labels]).mean())


def calibrate_temperature(dev_logits, dev_labels):
    """Fixed 80-step golden search over log(T), T in [0.05,20], dev NLL only."""
    dev_logits, dev_labels = np.asarray(dev_logits), np.asarray(dev_labels)
    if (dev_logits.ndim != 2 or not len(dev_logits) or not np.isfinite(dev_logits).all()
            or dev_labels.shape != (len(dev_logits),) or dev_labels.dtype.kind not in "iu"
            or (dev_labels < 0).any() or (dev_labels >= dev_logits.shape[1]).any()):
        raise ValueError("Invalid development logits or labels")
    lower, upper = np.log(.05), np.log(20.)
    ratio = (np.sqrt(5) - 1) / 2
    left, right = upper - ratio * (upper - lower), lower + ratio * (upper - lower)
    evaluate = lambda value: negative_log_likelihood(dev_logits, dev_labels, float(np.exp(value)))
    left_nll, right_nll = evaluate(left), evaluate(right)
    for _ in range(80):
        if left_nll <= right_nll:
            upper, right, right_nll = right, left, left_nll
            left = upper - ratio * (upper - lower)
            left_nll = evaluate(left)
        else:
            lower, left, left_nll = left, right, right_nll
            right = lower + ratio * (upper - lower)
            right_nll = evaluate(right)
    candidates = [(.05, evaluate(np.log(.05))), (20., evaluate(np.log(20.))),
                  (1., evaluate(0.)), (float(np.exp((lower + upper) / 2)), evaluate((lower + upper) / 2))]
    temperature, nll = min(candidates, key=lambda pair: (pair[1], abs(np.log(pair[0]))))
    return {"temperature": temperature, "dev_nll": nll, "uncalibrated_dev_nll": evaluate(0.),
            "method": "80 fixed golden-section steps in log-temperature, then compare bounds and T=1",
            "bounds": [.05, 20.], "calibration_rows": len(dev_labels), "calibration_uses_report": False}


def route_predictions(small_logits, yolo_logits, temperature, threshold):
    if not np.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError("Threshold must lie in [0,1]")
    small_logits, yolo_logits = np.asarray(small_logits), np.asarray(yolo_logits)
    if (small_logits.shape != yolo_logits.shape or small_logits.ndim != 2
            or not np.isfinite(yolo_logits).all()):
        raise ValueError("Aligned finite cascade logits required")
    confidence = softmax(small_logits, temperature).max(axis=1)
    # Explicit sentinel avoids softmax rounding to 1 and leaking early exits.
    early = confidence >= threshold if threshold < 1 else np.zeros(len(confidence), dtype=bool)
    prediction = np.where(early, small_logits.argmax(axis=1), yolo_logits.argmax(axis=1))
    return prediction, early, confidence


def is_critical(label):
    return label.startswith(("maxspeed:", "priority:")) or label in {
        "city:start", "city:end", "zone:30", "zone:30:end", "zone:end", "no:end",
        "motorway:end", "trunk:end", "no_overtaking:end", "give_way", "stop",
    }


def metrics(labels, predictions, class_names):
    count = len(class_names)
    truth, predicted = np.asarray(labels, dtype=np.int64), np.asarray(predictions, dtype=np.int64)
    if truth.shape != predicted.shape or truth.ndim != 1 or not len(truth):
        raise ValueError("Nonempty aligned metric vectors required")
    if ((truth < 0) | (truth >= count) | (predicted < 0) | (predicted >= count)).any():
        raise ValueError("Metric target/prediction outside class order")
    cm = np.bincount(truth * count + predicted, minlength=count ** 2).reshape(count, count)
    tp, support, outputs = np.diag(cm), cm.sum(axis=1), cm.sum(axis=0)
    fp, fn, denominator = outputs - tp, support - tp, support + outputs
    f1 = np.divide(2 * tp, denominator, out=np.zeros(count, dtype=float), where=denominator > 0)
    per_class = [{"class_id": name, "support": int(support[i]), "tp": int(tp[i]),
                  "fp": int(fp[i]), "fn": int(fn[i]), "f1": float(f1[i]) if denominator[i] else None,
                  "critical": is_critical(name)} for i, name in enumerate(class_names)]
    return {"rows": len(truth), "accuracy": float((truth == predicted).mean()),
            "macro_f1_supported": float(f1[support > 0].mean()),
            "macro_f1_all_136_zero_unobserved": float(f1.mean()),
            "supported_class_count": int((support > 0).sum()), "per_class": per_class,
            "confusion_matrix": cm.tolist()}


def critical_guard(baseline, candidate):
    violations = []
    if len(baseline["per_class"]) != len(candidate["per_class"]):
        raise ValueError("Guard class counts differ")
    for old, new in zip(baseline["per_class"], candidate["per_class"]):
        if old["class_id"] != new["class_id"]:
            raise ValueError("Guard class orders differ")
        if old["critical"] and (new["fp"] > old["fp"] or new["fn"] > old["fn"]):
            violations.append({"class_id": old["class_id"], "baseline_fp": old["fp"],
                               "cascade_fp": new["fp"], "baseline_fn": old["fn"], "cascade_fn": new["fn"]})
    return {"passes": not violations, "violations": violations}


def select_gate(dev_small_logits, dev_yolo_logits, dev_labels, class_names):
    """Only dev arrays enter this function; report cannot influence the gate."""
    calibration = calibrate_temperature(dev_small_logits, dev_labels)
    baseline = metrics(dev_labels, dev_yolo_logits.argmax(axis=1), class_names)
    grid = []
    for threshold in THRESHOLDS:
        predictions, early, _ = route_predictions(dev_small_logits, dev_yolo_logits,
                                                   calibration["temperature"], threshold)
        result = metrics(dev_labels, predictions, class_names)
        guard = critical_guard(baseline, result)
        macro_passes = result["macro_f1_supported"] >= baseline["macro_f1_supported"] - MACRO_TOLERANCE
        grid.append({"threshold": threshold, "small_stage_share": float(early.mean()),
                     "fallback_fraction": float((~early).mean()), "small_stage_rows": int(early.sum()),
                     "macro_f1_supported": result["macro_f1_supported"], "accuracy": result["accuracy"],
                     "critical_guard": guard, "macro_guard_passes": macro_passes,
                     "eligible": macro_passes and guard["passes"]})
    # Threshold 1 is always baseline-equivalent and eligible. Prefer most early
    # exits; equal shares use larger threshold, including the explicit sentinel.
    selected = max((item for item in grid if item["eligible"]),
                   key=lambda item: (item["small_stage_rows"], item["threshold"]))
    return {"calibration": calibration, "selected": selected, "development_grid": grid,
            "selection_rule": "Highest Small-stage share subject to dev supported macro-F1 >= YOLO minus 0.002 and no added per-critical-class FP/FN; ties use larger threshold",
            "macro_tolerance": MACRO_TOLERANCE, "thresholds": list(THRESHOLDS),
            "no_early_exit_gain": selected["small_stage_rows"] == 0,
            "selection_uses_report": False}


def load_source(path, metadata_path, family):
    metadata = json.loads(metadata_path.read_text())
    if metadata["family"] != family or sha256(path) != metadata["npz_sha256"]:
        raise ValueError("Source NPZ hash/family does not match extraction metadata")
    with np.load(path, allow_pickle=False) as archive:
        arrays = {key: archive[key] for key in KEYS}
    return arrays, metadata


def cost_estimate(small_metadata, yolo_metadata, fallback_fraction):
    small, yolo = small_metadata["feature_cpu_latency"], yolo_metadata["feature_cpu_latency"]
    if any(item["threads"] != 1 or item["dtype"] != "float32" for item in (small, yolo)):
        raise ValueError("Expected common single-thread Float32 component timing protocol")
    costs = [small["p50_ms"], yolo["p50_ms"]]
    if not all(np.isfinite(value) and value > 0 for value in costs) or not 0 <= fallback_fraction <= 1:
        raise ValueError("Invalid positive component timings or fallback fraction")
    estimate = costs[0] + fallback_fraction * costs[1]
    return {"small_component_p50_ms": costs[0], "yolo_component_p50_ms": costs[1],
            "fallback_fraction": fallback_fraction, "estimated_average_component_ms": estimate,
            "estimated_fraction_of_yolo_component_cost": estimate / costs[1],
            "estimated_cost_reduction_fraction": 1 - estimate / costs[1],
            "formula": "Small component p50 + fallback fraction * YOLO component p50",
            "scope": "Arithmetic expected component-cost estimate; not observed cascade p50, phone latency or end-to-end latency",
            "component_scope": small["scope"], "actual_cascade_timing_measured": False}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--small", type=Path, required=True)
    parser.add_argument("--yolo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        raise ValueError("Output must be a new directory; retain immutable prior results")
    small, small_meta = load_source(args.small, args.small.with_suffix(".json"), "small136")
    yolo, yolo_meta = load_source(args.yolo, args.yolo.with_suffix(".json"), "yolo136")
    if small_meta["manifest_sha256"] != yolo_meta["manifest_sha256"]:
        raise ValueError("Component manifest hashes differ")
    names = validate_pair(small, yolo)
    dev, report, labels = small["dev_indices"], small["report_indices"], small["val_labels"]
    selection = select_gate(small["val_logits"][dev], yolo["val_logits"][dev], labels[dev], names)
    selection.update(frozen_at=datetime.now(timezone.utc).isoformat(), script_sha256=sha256(__file__),
                     source_npz_sha256={"small": small_meta["npz_sha256"], "yolo": yolo_meta["npz_sha256"]},
                     limitations=LIMITATIONS)
    args.output.mkdir(parents=True)
    dump(args.output / "selection.json", selection)
    selection_sha = sha256(args.output / "selection.json")
    # Report metrics are first computed after this immutable selection receipt.
    prediction, early, confidence = route_predictions(
        small["val_logits"], yolo["val_logits"], selection["calibration"]["temperature"],
        selection["selected"]["threshold"])
    summaries = {}
    for split, indexes in (("development", dev), ("report", report)):
        baseline = metrics(labels[indexes], yolo["val_logits"][indexes].argmax(axis=1), names)
        standalone = metrics(labels[indexes], small["val_logits"][indexes].argmax(axis=1), names)
        cascade = metrics(labels[indexes], prediction[indexes], names)
        fallback = float((~early[indexes]).mean())
        result = {"split": split, "rows": len(indexes), "yolo": baseline, "small": standalone,
                  "cascade": cascade, "small_stage_share": float(early[indexes].mean()),
                  "fallback_fraction": fallback, "critical_guard_vs_yolo": critical_guard(baseline, cascade),
                  "component_cost_estimate": cost_estimate(small_meta, yolo_meta, fallback),
                  "frozen_selection_sha256": selection_sha}
        dump(args.output / f"{split}.json", result)
        summaries[split] = {key: result[key] for key in ("rows", "small_stage_share", "fallback_fraction",
                                                        "critical_guard_vs_yolo", "component_cost_estimate")}
        summaries[split]["metrics"] = {model: {key: result[model][key] for key in
            ("accuracy", "macro_f1_supported", "macro_f1_all_136_zero_unobserved", "supported_class_count")}
            for model in ("yolo", "small", "cascade")}
    np.savez_compressed(args.output / "cascade-predictions.npz", class_names=small["class_names"],
                        val_labels=labels, val_sample_ids=small["val_sample_ids"], val_group_ids=small["val_group_ids"],
                        dev_indices=dev, report_indices=report, cascade_prediction=prediction,
                        small_prediction=small["val_logits"].argmax(axis=1),
                        yolo_prediction=yolo["val_logits"].argmax(axis=1), small_stage=early,
                        calibrated_small_confidence=confidence)
    summary = {"created_at": datetime.now(timezone.utc).isoformat(), "protocol": "small-yolo-cascade-v1",
               "threshold": selection["selected"]["threshold"], "temperature": selection["calibration"]["temperature"],
               "no_early_exit_gain": selection["no_early_exit_gain"], "splits": summaries,
               "frozen_selection_sha256": selection_sha, "manifest_sha256": small_meta["manifest_sha256"],
               "source_metadata": {"small": small_meta, "yolo": yolo_meta},
               "source_metadata_sha256": {"small": sha256(args.small.with_suffix(".json")), "yolo": sha256(args.yolo.with_suffix(".json"))},
               "script_sha256": sha256(__file__), "numpy_version": np.__version__,
               "limitations": LIMITATIONS, "deployment_changes": False}
    dump(args.output / "summary.json", summary)
    dump(args.output / "complete.json", {"artifacts": {p.name: sha256(p) for p in sorted(args.output.iterdir()) if p.is_file()}})
    print(json.dumps({key: summary[key] for key in ("threshold", "temperature", "no_early_exit_gain", "splits")}, allow_nan=False))


if __name__ == "__main__":
    main()
