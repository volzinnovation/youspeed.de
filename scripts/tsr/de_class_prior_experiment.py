#!/usr/bin/env python3
"""Test observed class-prior corrections on frozen classifier logits.

The captured class counts are selected, mostly model-labelled observations,
not unbiased road-sign prevalence. This is a diagnostic sensitivity experiment.
The correction is z/T + alpha*(log(target_prior)-log(training_prior)); it does
not multiply a learned posterior by raw class frequency a second time.
No images, checkpoints, native runtime policy or reserved test pixels are read.
"""
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np


SOURCE_COLUMNS = {
    "ios": "ios_prediction_crops",
    "android": "android_prediction_crops",
    "panoramax": "panoramax_source_label_crops",
    "pooled": "captured_crops",
}
ALPHAS = (0.0, 0.1, 0.25, 0.5, 1.0)
TEMPERATURES = (0.5, 0.75, 1.0, 1.5, 2.0, 3.0)


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write_json(path, data):
    path = Path(path)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, indent=2, allow_nan=False) + "\n")
    tmp.replace(path)


def normalized(values):
    values = np.asarray(values, dtype=np.float64)
    if values.ndim != 1 or not np.all(np.isfinite(values)) or np.any(values <= 0):
        raise ValueError("Prior elements must be positive and finite")
    return values / values.sum()


def smoothed_prior(counts, pseudocount=1.0):
    counts = np.asarray(counts, dtype=np.float64)
    if counts.ndim != 1 or not len(counts) or not np.all(np.isfinite(counts)) or np.any(counts < 0):
        raise ValueError("Class counts must be a nonempty nonnegative finite vector")
    if not np.isfinite(pseudocount) or pseudocount <= 0:
        raise ValueError("Positive pseudocount required, including unobserved classes")
    return normalized(counts + pseudocount)


def target_prior(counts, training_prior, trust=0.25, pseudocount=1.0):
    if not 0 <= trust <= 1:
        raise ValueError("Trust must lie in [0,1]")
    training_prior = normalized(training_prior)
    empirical = smoothed_prior(counts, pseudocount)
    if empirical.shape != training_prior.shape:
        raise ValueError("Prior dimensions disagree")
    return normalized((1.0 - trust) * training_prior + trust * empirical)


def effective_count_prior(counts, power=1.0):
    """Explicit recipe assumption; e.g. balanced-softmax tau => power=1-tau."""
    if not np.isfinite(power) or power < 0:
        raise ValueError("Effective-prior power must be finite and nonnegative")
    return normalized(smoothed_prior(counts) ** power)


def censored_target_prior(counts, training_prior, observable, trust=.25):
    """A source unable to emit a class cannot supply evidence of its absence.

    Preserve the prior mass of structurally censored classes; normalize source
    frequencies conditionally within its observable label space.
    """
    base = normalized(training_prior)
    counts = np.asarray(counts, dtype=np.float64)
    observed = np.asarray(observable, dtype=bool)
    if not np.isfinite(trust) or not 0 <= trust <= 1:
        raise ValueError("Trust must lie in [0,1]")
    if counts.shape != base.shape or observed.shape != base.shape or not observed.any():
        raise ValueError("A nonempty observable label space must align with prior counts")
    result = base.copy()
    available_mass = base[observed].sum()
    empirical = smoothed_prior(counts[observed]) * available_mass
    result[observed] = (1 - trust) * base[observed] + trust * empirical
    return normalized(result)


def softmax(logits):
    logits = np.asarray(logits, dtype=np.float64)
    if logits.ndim != 2 or not np.all(np.isfinite(logits)):
        raise ValueError("Logits must be a finite two-dimensional matrix")
    shifted = logits - logits.max(axis=1, keepdims=True)
    result = np.exp(shifted)
    return result / result.sum(axis=1, keepdims=True)


def corrected_logits(logits, training_prior, new_prior, alpha, temperature=1.0,
                     confidence_gate=None):
    if not np.isfinite(temperature) or temperature <= 0 or not np.isfinite(alpha) or alpha < 0:
        raise ValueError("Positive temperature and nonnegative alpha required")
    train, new = normalized(training_prior), normalized(new_prior)
    logits = np.asarray(logits, dtype=np.float64)
    if logits.ndim != 2 or logits.shape[1] != len(train) or new.shape != train.shape or not np.all(np.isfinite(logits)):
        raise ValueError("Logits and aligned prior vectors disagree")
    calibrated = logits / temperature
    offset = alpha * (np.log(new) - np.log(train))
    if confidence_gate is None:
        return calibrated + offset
    if not 0 < confidence_gate <= 1:
        raise ValueError("Confidence gate must lie in (0,1]")
    apply = softmax(calibrated).max(axis=1) < confidence_gate
    return calibrated + apply[:, None] * offset


def is_critical(label):
    return (label.startswith(("maxspeed:", "priority:")) or label in {
        "city:start", "city:end", "zone:30", "zone:30:end", "zone:end",
        "no:end", "motorway:end", "trunk:end", "no_overtaking:end",
        "give_way", "stop",
    })


def metrics(truth, probabilities, class_names, model_global_indices):
    truth = np.asarray(truth, dtype=np.int64)
    probability = np.asarray(probabilities, dtype=np.float64)
    model_indices = np.asarray(model_global_indices, dtype=np.int64)
    count = len(class_names)
    if len(truth) == 0 or probability.shape != (len(truth), len(model_indices)):
        raise ValueError("Nonempty aligned targets/probabilities required")
    if np.any(truth < 0) or np.any(truth >= count) or not np.all(np.isfinite(probability)):
        raise ValueError("Invalid target indices or probabilities")
    if np.any(probability < 0) or not np.allclose(probability.sum(axis=1), 1.0):
        raise ValueError("Probabilities must be normalized")
    predictions = model_indices[probability.argmax(axis=1)]
    confusion = np.bincount(truth * count + predictions, minlength=count * count).reshape(count, count)
    support, predicted = confusion.sum(1), confusion.sum(0)
    tp = np.diag(confusion)
    fp, fn = predicted - tp, support - tp
    denom = support + predicted
    f1 = np.divide(2 * tp, denom, out=np.zeros(count, dtype=float), where=denom > 0)
    supported = support > 0
    lookup = {int(global_index): col for col, global_index in enumerate(model_indices)}
    true_p = np.asarray([probability[i, lookup[int(y)]] if int(y) in lookup else 0.0 for i, y in enumerate(truth)])
    nll = float(-np.log(np.clip(true_p, 1e-12, 1)).mean())
    correct = predictions == truth
    confidence = probability.max(axis=1)
    ece = 0.0
    for low, high in zip(np.linspace(0, 1, 16)[:-1], np.linspace(0, 1, 16)[1:]):
        rows = (confidence >= low) & ((confidence <= high) if high == 1 else (confidence < high))
        if rows.any():
            ece += float(rows.mean() * abs(correct[rows].mean() - confidence[rows].mean()))
    per_class = []
    for i, name in enumerate(class_names):
        per_class.append({"index": i, "class_id": name, "support": int(support[i]),
                          "tp": int(tp[i]), "fp": int(fp[i]), "fn": int(fn[i]),
                          "precision": float(tp[i] / predicted[i]) if predicted[i] else None,
                          "recall": float(tp[i] / support[i]) if support[i] else None,
                          "f1": float(f1[i]) if denom[i] else None,
                          "critical": is_critical(name)})
    critical = np.asarray([is_critical(name) for name in class_names]) & supported
    critical_support = int(support[critical].sum())
    return {
        "samples": len(truth), "accuracy": float(correct.mean()),
        "micro_f1": float(correct.mean()), "macro_f1_supported": float(f1[supported].mean()),
        "macro_f1_all_classes_zero_for_unobserved": float(f1.mean()),
        "weighted_f1": float(np.dot(f1, support) / len(truth)),
        "supported_class_count": int(supported.sum()),
        "unsupported_classes": [class_names[i] for i in range(count) if not support[i]],
        "critical_micro_recall": float(tp[critical].sum() / critical_support) if critical_support else None,
        "critical_support": critical_support, "nll_clipped_at_1e_minus12": nll,
        "ece_15_equal_width_bins": ece, "per_class": per_class,
        "predictions": predictions.tolist(),
    }


def passes_critical_guard(baseline, candidate):
    """Development-only safeguard: no added critical-class FP/FN counts."""
    for old, new in zip(baseline["per_class"], candidate["per_class"]):
        if old["class_id"] != new["class_id"]:
            raise ValueError("Class alignment mismatch")
        if old["critical"] and (new["fp"] > old["fp"] or new["fn"] > old["fn"]):
            return False
    return True


def load_counts(path, names):
    records = {}
    with Path(path).open(newline="") as stream:
        for row in csv.DictReader(stream):
            if row["class_id"] in records:
                raise ValueError("Duplicate prior source class")
            records[row["class_id"]] = row
    missing = sorted(set(names) - set(records))
    if missing:
        raise ValueError(f"Missing class count records: {missing}")
    return {key: np.asarray([float(records[name][column]) for name in names])
            for key, column in SOURCE_COLUMNS.items()}


def validate_partitions(dev, report, groups, count):
    dev, report = np.asarray(dev, dtype=np.int64), np.asarray(report, dtype=np.int64)
    if not len(dev) or not len(report):
        raise ValueError("Both diagnostic partitions need samples")
    if len(set(dev)) != len(dev) or len(set(report)) != len(report):
        raise ValueError("Duplicate partition indices")
    if set(dev) & set(report) or set(dev) | set(report) != set(range(count)):
        raise ValueError("Development/report partitions must cover validation exactly once")
    if set(groups[dev]) & set(groups[report]):
        raise ValueError("Group crosses development/report partition")


def compact(result):
    return {key: value for key, value in result.items() if key not in {"per_class", "predictions"}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True, help="One model's frozen logits NPZ; allow_pickle=False")
    parser.add_argument("--counts", type=Path, required=True, help="Frozen de-class-support.csv")
    parser.add_argument("--output", type=Path, required=True, help="New output directory")
    parser.add_argument("--partition", type=Path, help="JSON with dev_indices and report_indices; otherwise use NPZ fields")
    parser.add_argument("--effective-prior-power", type=float,
                        help="Explicit training-recipe assumption: effective prior proportional to empirical prior**power; e.g. .75 for Balanced Softmax tau=.25")
    args = parser.parse_args()
    if args.output.exists():
        raise ValueError("Use a new output directory to preserve previous results")
    with np.load(args.input, allow_pickle=False) as archive:
        classes = [str(x) for x in archive["class_names"]]
        logits = np.asarray(archive["val_logits"], dtype=np.float64)
        names = [str(x) for x in archive["model_class_names"]] if "model_class_names" in archive else classes[:logits.shape[1]]
        targets = np.asarray(archive["val_labels"], dtype=np.int64)
        train_labels = np.asarray(archive["train_labels"], dtype=np.int64)
        explicit_prior = np.asarray(archive["effective_train_prior"], dtype=np.float64) if "effective_train_prior" in archive else None
        group_key = "val_group_ids" if "val_group_ids" in archive else "val_groups"
        groups = np.asarray(archive[group_key]).astype(str)
        sample_ids = np.asarray(archive["val_sample_ids"]).astype(str)
        if args.partition:
            partition = json.loads(args.partition.read_text())
            dev, report = np.asarray(partition["dev_indices"]), np.asarray(partition["report_indices"])
        else:
            dev, report = archive["dev_indices"], archive["report_indices"]
    if len(classes) != len(set(classes)) or len(names) != len(set(names)) or not set(names) <= set(classes):
        raise ValueError("Class names must be unique and model names a subset")
    if logits.shape != (len(targets), len(names)) or groups.shape != targets.shape or sample_ids.shape != targets.shape:
        raise ValueError("Model logits/label/identity arrays disagree")
    if train_labels.ndim != 1 or not len(train_labels) or np.any(train_labels < 0) or np.any(train_labels >= len(classes)):
        raise ValueError("Training class indices must refer to the declared global label space")
    if not np.all(np.isfinite(logits)) or len(set(sample_ids)) != len(sample_ids):
        raise ValueError("Nonfinite logits or duplicate sample identities")
    validate_partitions(dev, report, groups, len(targets))
    dev, report = np.asarray(dev, dtype=np.int64), np.asarray(report, dtype=np.int64)
    model_indices = np.asarray([classes.index(name) for name in names])
    train_count_all = np.bincount(train_labels, minlength=len(classes))
    if explicit_prior is not None:
        if args.effective_prior_power is not None:
            raise ValueError("Choose either NPZ effective_train_prior or --effective-prior-power")
        if explicit_prior.shape != (len(names),):
            raise ValueError("Explicit effective prior must align with model_class_names")
        training_prior = normalized(explicit_prior)
        prior_basis = "explicit effective_train_prior vector from input, aligned to model classes"
    else:
        power = 1.0 if args.effective_prior_power is None else args.effective_prior_power
        training_prior = effective_count_prior(train_count_all[model_indices], power)
        prior_basis = f"add-one-smoothed empirical current-training prior raised to power {power}; analytical recipe approximation"
    counts = load_counts(args.counts, names)
    priors = {key: target_prior(value, training_prior) for key, value in counts.items()}
    phone_observable = np.asarray([name not in {"city:start", "city:end"} for name in names])
    for key in ("ios", "android"):
        priors[key] = censored_target_prior(counts[key], training_prior, phone_observable)
    panoramax_observable = np.asarray([not (name == "bad" or name.startswith("bad:")) for name in names])
    priors["panoramax"] = censored_target_prior(counts["panoramax"], training_prior, panoramax_observable)
    priors["equal_source_mix"] = normalized(sum(priors[key] for key in ("ios", "android", "panoramax")) / 3)
    # Uniform target is a separate diagnostic control, not road prevalence.
    priors["uniform_control"] = normalized(np.ones(len(names)))

    def evaluate(indices, adjusted):
        return metrics(targets[indices], softmax(adjusted[indices]), classes, model_indices)

    raw = evaluate(dev, logits)
    calibrations = [(float(evaluate(dev, logits / t)["nll_clipped_at_1e_minus12"]), t) for t in TEMPERATURES]
    _, temperature = min(calibrations, key=lambda item: (item[0], abs(item[1] - 1)))
    calibrated = logits / temperature
    base = evaluate(dev, calibrated)
    best_key = (base["macro_f1_supported"], -base["nll_clipped_at_1e_minus12"], 0.0)
    best = {"source": "none", "alpha": 0.0, "confidence_gate": None, "temperature": temperature}
    best_adjusted = calibrated
    observed_best_key = best_key
    observed_best = dict(best)
    observed_best_adjusted = calibrated
    candidates = []
    for source, new_prior in priors.items():
        for alpha in ALPHAS:
            for gate in (None, 0.95):
                adjusted = corrected_logits(logits, training_prior, new_prior, alpha, temperature, gate)
                score = evaluate(dev, adjusted)
                guard = passes_critical_guard(base, score)
                candidate = {"source": source, "alpha": alpha, "confidence_gate": gate,
                             "temperature": temperature, "critical_guard_on_dev": guard,
                             "eligible_for_selection": source != "pooled",
                             "eligible_for_observed_selection": source not in {"pooled", "uniform_control"},
                             "dev": compact(score),
                             "changed_dev_predictions": sum(a != b for a, b in zip(base["predictions"], score["predictions"]))}
                candidates.append(candidate)
                key = (score["macro_f1_supported"], -score["nll_clipped_at_1e_minus12"], -alpha)
                if source != "pooled" and guard and key > best_key:
                    best_key, best, best_adjusted = key, {k: candidate[k] for k in ("source", "alpha", "confidence_gate", "temperature")}, adjusted
                if source not in {"pooled", "uniform_control"} and guard and key > observed_best_key:
                    observed_best_key = key
                    observed_best = {k: candidate[k] for k in ("source", "alpha", "confidence_gate", "temperature")}
                    observed_best_adjusted = adjusted

    raw_report = evaluate(report, logits)
    base_report = evaluate(report, calibrated)
    selected_dev, selected_report = evaluate(dev, best_adjusted), evaluate(report, best_adjusted)
    observed_selected_dev = evaluate(dev, observed_best_adjusted)
    observed_selected_report = evaluate(report, observed_best_adjusted)
    args.output.mkdir(parents=True)
    policy = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "script_sha256": sha(__file__), "input_sha256": sha(args.input), "counts_sha256": sha(args.counts),
        "partition_sha256": sha(args.partition) if args.partition else None,
        "class_names": classes, "model_class_names": names,
        "formula": "z / T + alpha * (log(p_target) - log(p_train))",
        "training_prior": prior_basis,
        "effective_prior_power_argument": args.effective_prior_power,
        "source_training_counts": train_count_all[model_indices].tolist(),
        "source_counts": {key: value.tolist() for key, value in counts.items()},
        "p_train": training_prior.tolist(), "target_priors": {key: value.tolist() for key, value in priors.items()},
        "target_smoothing_pseudocount": 1.0, "target_trust": .25,
        "phone_structural_censoring": "The installed134class head cannot emit city:start/end. iOS/Android priors preserve those classes' effective training-prior mass and normalize remaining counts conditionally.",
        "panoramax_structural_censoring": "Sign-annotation inventory cannot represent no-sign/rejection classes bad and bad:*. Panoramax priors preserve their effective training-prior masses.",
        "pooled_prior_caveat": "Pooled capture frequencies mix source label spaces and are a biased sensitivity control, EXCLUDED from candidate selection; structural censoring is not corrected by simply pooling crop counts.",
        "uniform_control": "unshrunk uniform class prior; control, not prevalence estimate",
        "temperature_grid": list(TEMPERATURES), "temperature_selection": "minimum development NLL; ties closest to1",
        "alpha_grid": list(ALPHAS), "confidence_gates": [None, .95],
        "selection": "development supported macro-F1, then lower NLL, then weaker alpha, subject to zero added critical-class FP/FN versus calibrated no-correction; pooled biased sensitivity arm excluded",
        "observed_selection": "same development-only criterion and guard, restricted to none, iOS, Android, Panoramax and equal-source mix; uniform control and pooled stress excluded; frozen independently of overall control winner",
        "dev_samples": len(dev), "report_samples": len(report),
        "dev_groups": len(set(groups[dev])), "report_groups": len(set(groups[report])),
        "critical_class_ids": [name for name in classes if is_critical(name)],
        "limitations": [
            "Counts estimate the distribution of detected, retained and labelled crops; not unbiased road-sign prevalence.",
            "Phone counts are predictions and many Panoramax tags come from the same teacher, so prior feedback is possible.",
            "Crop bursts and physical-sign repeats are not removed from the aggregate frequency CSV; the balanced review queue is not a prevalence sample and is not used here.",
            "Original teacher training/sampling prior is unknown; empirical current training counts are only a proxy even after fine-tuning.",
            "Weighted losses, resampling and balanced-softmax training change the effective prior; an explicit recipe-aware power or vector is required to avoid double correction.",
            "Exact label-shift correction assumes unchanged class-conditional image distributions, which mobile/source-domain and geometry shifts may violate.",
            "Both diagnostic partitions reuse historical validation already inspected in earlier work; neither is an independent field test.",
            "Only development labels choose temperature, source, alpha and gate; report labels are used after that choice.",
            "A zero observed count is not evidence a class is impossible; smoothing and shrinkage keep all supported model classes positive.",
            "Missing classifier outputs cannot be restored by a class prior; their evaluation targets remain misses.",
            "No runtime policy or deployed classifier is changed by this script.",
        ],
        "primary_sources": ["https://proceedings.mlr.press/v80/lipton18a.html", "https://arxiv.org/abs/2003.07554", "https://pubmed.ncbi.nlm.nih.gov/11747533/"],
    }
    write_json(args.output / "configuration.json", policy)
    write_json(args.output / "development-grid.json", candidates)
    write_json(args.output / "calibration-grid.json", [{"temperature": t, "development_nll": loss} for loss, t in calibrations])
    write_json(args.output / "selected.json", best)
    write_json(args.output / "observed-selected.json", observed_best)
    write_json(args.output / "metrics.json", {"raw_dev": compact(raw), "calibrated_dev": compact(base),
               "selected_dev": compact(selected_dev), "raw_report": compact(raw_report),
               "calibrated_report": compact(base_report), "selected_report": compact(selected_report),
               "critical_guard_on_report": passes_critical_guard(base_report, selected_report),
               "changed_report_predictions": sum(a != b for a, b in zip(base_report["predictions"], selected_report["predictions"])),
               "observed_selected_dev": compact(observed_selected_dev),
               "observed_selected_report": compact(observed_selected_report),
               "observed_critical_guard_on_report": passes_critical_guard(base_report, observed_selected_report),
               "observed_changed_report_predictions": sum(a != b for a, b in zip(base_report["predictions"], observed_selected_report["predictions"]))})
    with (args.output / "report-predictions.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["sample_id", "group_id", "truth", "baseline", "selected"])
        writer.writeheader()
        for j, i in enumerate(report):
            writer.writerow({"sample_id": sample_ids[i], "group_id": groups[i], "truth": classes[targets[i]],
                             "baseline": classes[base_report["predictions"][j]],
                             "selected": classes[selected_report["predictions"][j]]})
    with (args.output / "report-per-class.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["class_id", "support", "critical", "baseline_f1", "selected_f1", "baseline_fp", "selected_fp", "baseline_fn", "selected_fn"])
        writer.writeheader()
        for old, new in zip(base_report["per_class"], selected_report["per_class"]):
            writer.writerow({"class_id": old["class_id"], "support": old["support"], "critical": old["critical"],
                             "baseline_f1": old["f1"], "selected_f1": new["f1"],
                             "baseline_fp": old["fp"], "selected_fp": new["fp"],
                             "baseline_fn": old["fn"], "selected_fn": new["fn"]})
    with (args.output / "observed-report-predictions.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["sample_id", "group_id", "truth", "baseline", "selected"])
        writer.writeheader()
        for j, i in enumerate(report):
            writer.writerow({"sample_id": sample_ids[i], "group_id": groups[i], "truth": classes[targets[i]],
                             "baseline": classes[base_report["predictions"][j]],
                             "selected": classes[observed_selected_report["predictions"][j]]})
    with (args.output / "observed-report-per-class.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["class_id", "support", "critical", "baseline_f1", "selected_f1", "baseline_fp", "selected_fp", "baseline_fn", "selected_fn"])
        writer.writeheader()
        for old, new in zip(base_report["per_class"], observed_selected_report["per_class"]):
            writer.writerow({"class_id": old["class_id"], "support": old["support"], "critical": old["critical"],
                             "baseline_f1": old["f1"], "selected_f1": new["f1"],
                             "baseline_fp": old["fp"], "selected_fp": new["fp"],
                             "baseline_fn": old["fn"], "selected_fn": new["fn"]})
    write_json(args.output / "complete.json", {"completed_at": datetime.now(timezone.utc).isoformat(),
               "selected": best, "report_macro_f1": selected_report["macro_f1_supported"],
               "report_accuracy": selected_report["accuracy"],
               "observed_selected": observed_best,
               "observed_report_macro_f1": observed_selected_report["macro_f1_supported"],
               "observed_report_accuracy": observed_selected_report["accuracy"],
               "reserved_test_pixels_opened": False})
    print(json.dumps({"selected": best, "baseline_report_macro": base_report["macro_f1_supported"],
                      "selected_report_macro": selected_report["macro_f1_supported"],
                      "observed_selected": observed_best,
                      "observed_report_macro": observed_selected_report["macro_f1_supported"],
                      "critical_guard_on_report": passes_critical_guard(base_report, selected_report)}))


if __name__ == "__main__":
    main()
