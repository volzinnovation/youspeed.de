#!/usr/bin/env python3
"""Fit bounded classical DE crop classifiers on frozen, inspectable features.

Each NPZ is one feature family. Required non-object arrays: train_features,
train_labels, val_features, val_labels, class_names, train_sample_ids,
val_sample_ids, train_groups, val_groups, dev_indices, report_indices.
Features are extracted upstream; no images, checkpoints or test pixels are read.
The reused historical validation partitions are diagnostic, not a new blind test.
Run with numpy, scikit-learn, joblib and threadpoolctl in an isolated environment.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import platform
import time
import warnings


REQUIRED = {
    "train_features", "train_labels", "val_features", "val_labels", "class_names",
    "train_sample_ids", "val_sample_ids", "train_groups", "val_groups",
    "dev_indices", "report_indices",
}


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dump(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


def validate_arrays(arrays, np):
    """Reject silent label/index remapping and declared-group leakage."""
    if missing := REQUIRED - set(arrays):
        raise ValueError(f"Missing feature arrays: {sorted(missing)}")
    for key, value in arrays.items():
        if value.dtype.kind == "O":
            raise ValueError(f"Object arrays are not permitted: {key}")
    classes = arrays["class_names"]
    if classes.ndim != 1 or classes.dtype.kind not in "US" or len(set(classes.tolist())) != len(classes):
        raise ValueError("class_names must be unique strings in frozen output order")
    if len(classes) < 2 or any(not str(name) for name in classes):
        raise ValueError("At least two nonempty class names required")
    dimensions = []
    for split in ("train", "val"):
        x, y = arrays[f"{split}_features"], arrays[f"{split}_labels"]
        if x.ndim != 2 or not len(x) or x.shape[1] < 1 or x.dtype.kind not in "fiu":
            raise ValueError(f"{split} features must be a nonempty numeric matrix")
        if not np.isfinite(x).all():
            raise ValueError(f"Nonfinite {split} features")
        if y.ndim != 1 or len(y) != len(x) or y.dtype.kind not in "iu":
            raise ValueError(f"{split} labels must be integer class indices")
        if (y < 0).any() or (y >= len(classes)).any():
            raise ValueError(f"{split} label lies outside frozen class order")
        for suffix in ("sample_ids", "groups"):
            values = arrays[f"{split}_{suffix}"]
            if values.ndim != 1 or len(values) != len(x) or values.dtype.kind not in "US":
                raise ValueError(f"{split}_{suffix} must be one string per feature row")
            if any(not str(value) for value in values):
                raise ValueError(f"Empty {split}_{suffix}")
        if len(set(arrays[f"{split}_sample_ids"].tolist())) != len(x):
            raise ValueError(f"Duplicate {split} sample identities")
        dimensions.append(x.shape[1])
    if dimensions[0] != dimensions[1]:
        raise ValueError("Train and validation feature dimensions differ")
    for suffix in ("sample_ids", "groups"):
        if set(arrays[f"train_{suffix}"].tolist()) & set(arrays[f"val_{suffix}"].tolist()):
            raise ValueError(f"Train/validation {suffix} overlap")
    dev, report = arrays["dev_indices"], arrays["report_indices"]
    for label, indices in (("dev", dev), ("report", report)):
        if indices.ndim != 1 or not len(indices) or indices.dtype.kind not in "iu":
            raise ValueError(f"{label} indices must be nonempty integers")
        if (indices < 0).any() or (indices >= len(arrays["val_labels"])).any():
            raise ValueError(f"{label} index outside validation")
        if len(set(indices.tolist())) != len(indices):
            raise ValueError(f"Duplicate {label} indices")
    if set(dev.tolist()) & set(report.tolist()):
        raise ValueError("Development/report indices overlap")
    if set(dev.tolist()) | set(report.tolist()) != set(range(len(arrays["val_labels"]))):
        raise ValueError("Development/report indices must partition all validation rows")
    if set(arrays["val_groups"][dev].tolist()) & set(arrays["val_groups"][report].tolist()):
        raise ValueError("Development/report groups overlap")
    return {"train_rows": len(arrays["train_labels"]), "validation_rows": len(arrays["val_labels"]),
            "feature_dimensions": dimensions[0], "classes": len(classes),
            "development_rows": len(dev), "report_rows": len(report),
            "train_groups": len(set(arrays["train_groups"].tolist())),
            "development_groups": len(set(arrays["val_groups"][dev].tolist())),
            "report_groups": len(set(arrays["val_groups"][report].tolist()))}


def calculate_metrics(truth, predicted, classes):
    """Explicit class support; absent true classes do not gain fabricated F1."""
    if len(truth) != len(predicted) or not len(truth):
        raise ValueError("Nonempty equal-length targets/predictions required")
    count = len(classes)
    matrix = [[0] * count for _ in classes]
    for actual, guess in zip(truth, predicted):
        actual, guess = int(actual), int(guess)
        if not (0 <= actual < count and 0 <= guess < count):
            raise ValueError("Target/prediction outside class inventory")
        matrix[actual][guess] += 1
    rows = []
    for index, label in enumerate(classes):
        tp = matrix[index][index]
        support = sum(matrix[index])
        predictions = sum(row[index] for row in matrix)
        fp, fn = predictions - tp, support - tp
        rows.append({"index": index, "label": str(label), "support": support,
                     "predicted_count": predictions, "tp": tp, "fp": fp, "fn": fn,
                     "precision": tp / predictions if predictions else None,
                     "recall": tp / support if support else None,
                     "f1": 2 * tp / (support + predictions) if support + predictions else None})

    def macro(selected):
        supported = [row for row in selected if row["support"]]
        return sum(row["f1"] or 0.0 for row in supported) / len(supported) if supported else None

    accuracy = sum(row["tp"] for row in rows) / len(truth)
    return {"samples": len(truth), "accuracy": accuracy, "micro_f1": accuracy,
            "macro_f1_supported": macro(rows),
            "weighted_f1": sum(row["support"] * (row["f1"] or 0.0) for row in rows) / len(truth),
            "old_class_macro_f1_supported": macro(rows[:134]),
            "city_macro_f1_supported": macro(rows[134:136]),
            "supported_classes": sum(row["support"] > 0 for row in rows),
            "unsupported_true_classes": [row["label"] for row in rows if not row["support"]],
            "confusion": matrix, "per_class": rows}


def aligned_probabilities(estimator, features, class_count, np):
    probabilities = estimator.predict_proba(features)
    aligned = np.zeros((len(features), class_count), dtype=np.float32)
    classes = np.asarray(estimator.classes_)
    if classes.ndim != 1 or classes.dtype.kind not in "iu" or len(set(classes.tolist())) != len(classes):
        raise ValueError("Estimator returned invalid class identities")
    if (classes < 0).any() or (classes >= class_count).any():
        raise ValueError("Estimator class outside frozen inventory")
    if probabilities.shape != (len(features), len(classes)):
        raise ValueError("Unexpected probability shape")
    if not np.isfinite(probabilities).all() or (probabilities < 0).any():
        raise ValueError("Nonfinite/negative probabilities")
    if not np.allclose(probabilities.sum(axis=1), 1.0, atol=1e-5):
        raise ValueError("Probability rows do not sum to one")
    aligned[:, classes.astype(int)] = probabilities
    return aligned


def candidate_specs(quick=False):
    # Explicit leaf caps bound multiclass value arrays (~136 doubles per node).
    specs = [
        {"id": "rf128_depth16_leaf256", "kind": "random_forest", "n_estimators": 128,
         "max_depth": 16, "max_leaf_nodes": 256, "min_samples_leaf": 2,
         "max_features": "sqrt", "class_weight": "balanced_subsample"},
        {"id": "rf256_depth16_leaf512", "kind": "random_forest", "n_estimators": 256,
         "max_depth": 16, "max_leaf_nodes": 512, "min_samples_leaf": 2,
         "max_features": "sqrt", "class_weight": "balanced_subsample"},
        {"id": "extra256_depth16_leaf512", "kind": "extra_trees", "n_estimators": 256,
         "max_depth": 16, "max_leaf_nodes": 512, "min_samples_leaf": 2,
         "max_features": "sqrt", "class_weight": "balanced"},
        {"id": "logistic_c1", "kind": "logistic_regression", "C": 1.0,
         "max_iter": 200, "class_weight": None},
        {"id": "logistic_c1_balanced", "kind": "logistic_regression", "C": 1.0,
         "max_iter": 200, "class_weight": "balanced"},
    ]
    return [specs[0], specs[3]] if quick else specs


def build_estimator(spec, seed, jobs):
    from sklearn.ensemble import ExtraTreesClassifier, RandomForestClassifier
    from sklearn.linear_model import LogisticRegression
    from sklearn.pipeline import make_pipeline
    from sklearn.preprocessing import StandardScaler
    arguments = {key: value for key, value in spec.items() if key not in {"id", "kind"}}
    if spec["kind"] == "logistic_regression":
        return make_pipeline(StandardScaler(), LogisticRegression(**arguments, solver="lbfgs", random_state=seed))
    constructor = RandomForestClassifier if spec["kind"] == "random_forest" else ExtraTreesClassifier
    return constructor(**arguments, random_state=seed, n_jobs=jobs)


def raw_model_storage(estimator):
    if hasattr(estimator, "estimators_"):
        states = [tree.tree_.__getstate__() for tree in estimator.estimators_]
        return {"trees": len(states), "total_nodes": sum(state["node_count"] for state in states),
                "tree_array_bytes": sum(state["nodes"].nbytes + state["values"].nbytes for state in states),
                "meaning": "NumPy tree arrays only; excludes Python object/runtime working memory"}
    classifier = estimator.steps[-1][1]
    scaler = estimator.steps[0][1]
    return {"coefficient_elements": int(classifier.coef_.size + classifier.intercept_.size),
            "numeric_array_bytes": int(classifier.coef_.nbytes + classifier.intercept_.nbytes
                                       + scaler.mean_.nbytes + scaler.scale_.nbytes + scaler.var_.nbytes),
            "meaning": "Learned coefficients and scaling arrays; excludes Python object/runtime working memory"}


def time_head(estimator, rows, np, warmup=20, repetitions=100):
    from threadpoolctl import threadpool_limits
    # Forest sklearn batching uses workers for trees. Report single-thread,
    # one-crop calls; do not equate batch throughput to device latency.
    original_jobs = getattr(estimator, "n_jobs", None)
    if original_jobs is not None:
        estimator.set_params(n_jobs=1)
    times = []
    try:
        with threadpool_limits(limits=1):
            for index in range(warmup + repetitions):
                value = rows[index % len(rows):index % len(rows) + 1]
                start = time.perf_counter_ns()
                estimator.predict_proba(value)
                elapsed = (time.perf_counter_ns() - start) / 1e6
                if index >= warmup:
                    times.append(elapsed)
    finally:
        if original_jobs is not None:
            estimator.set_params(n_jobs=original_jobs)
    return {"warmup": warmup, "samples": repetitions, "batch_size": 1,
            "threads": 1, "p50_ms": float(np.quantile(times, 0.5)),
            "p95_ms": float(np.quantile(times, 0.95)), "samples_ms": times,
            "scope": "sklearn predict_proba including scaler, excluding feature extraction and image decoding"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--features", type=Path, required=True)
    parser.add_argument("--feature-metadata", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20261109)
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--quick", action="store_true")
    args = parser.parse_args(argv)
    if args.output.exists() or args.jobs < 1:
        raise ValueError("Require a new output directory and positive job count")
    import numpy as np
    import joblib
    import sklearn
    from threadpoolctl import threadpool_limits

    with np.load(args.features, allow_pickle=False) as archive:
        arrays = {key: archive[key] for key in archive.files}
    counts = validate_arrays(arrays, np)
    classes = [str(name) for name in arrays["class_names"]]
    feature_meta = json.loads(args.feature_metadata.read_text()) if args.feature_metadata else None
    args.output.mkdir(parents=True)
    x = np.asarray(arrays["train_features"], dtype=np.float32, order="C")
    val = np.asarray(arrays["val_features"], dtype=np.float32, order="C")
    y = arrays["train_labels"]
    dev, report = arrays["dev_indices"], arrays["report_indices"]
    config = {"created_at": datetime.now(timezone.utc).isoformat(), "script_sha256": sha256(__file__),
              "feature_npz_sha256": sha256(args.features), "feature_metadata": feature_meta,
              "feature_metadata_sha256": sha256(args.feature_metadata) if args.feature_metadata else None,
              "seed": args.seed, "jobs": args.jobs, "counts": counts, "classes": classes,
              "environment": {"python": platform.python_version(), "numpy": np.__version__, "sklearn": sklearn.__version__},
              "candidate_specs": candidate_specs(args.quick),
              "empirical_training_class_counts": np.bincount(y, minlength=len(classes)).tolist(),
              "selection": "maximum supported-class development macro-F1; exact ties use listed candidate order",
              "report_partition_used_for_selection": False,
              "caveats": ["Historical validation was previously inspected; neither partition is a new blind field test.",
                          "Original baseline pretraining exposure and imperfect physical-sign grouping remain.",
                          "Neural feature extractors may already have been selected using the full historical validation set.",
                          "A forest on CNN embeddings still pays the neural feature-extractor cost.",
                          "CPU head timing and joblib artifact size are not mobile latency or native model size."]}
    dump(args.output / "configuration.json", config)
    development_membership = set(dev.tolist())
    dump(args.output / "validation-identities.json", [
        {"index": i, "sample_id": str(arrays["val_sample_ids"][i]), "group": str(arrays["val_groups"][i]),
         "class_index": int(arrays["val_labels"][i]), "partition": "development" if i in development_membership else "report"}
        for i in range(len(val))])
    summaries = []
    # First pass sees training and development rows only. Save every candidate;
    # freeze selection before computing any report-partition metrics.
    for spec in config["candidate_specs"]:
        directory = args.output / spec["id"]
        directory.mkdir()
        estimator = build_estimator(spec, args.seed, args.jobs)
        start = time.monotonic()
        with warnings.catch_warnings(record=True) as captured, threadpool_limits(limits=args.jobs):
            warnings.simplefilter("always")
            estimator.fit(x, y)
        elapsed = time.monotonic() - start
        with threadpool_limits(limits=args.jobs):
            probabilities = aligned_probabilities(estimator, val[dev], len(classes), np)
        metrics = calculate_metrics(arrays["val_labels"][dev], probabilities.argmax(1), classes)
        dump(directory / "development-metrics.json", metrics)
        warning_messages = sorted({str(item.message) for item in captured})
        model_path = directory / "model.joblib"
        joblib.dump(estimator, model_path, compress=3)
        cost = time_head(estimator, val[dev[:32]], np)
        result = {"candidate": spec["id"], "fit_seconds": elapsed,
                  "class_weight": spec["class_weight"],
                  "nominal_weighted_training_prior": ((np.bincount(y, minlength=len(classes)) > 0).astype(float)
                     / len(np.unique(y))).tolist() if spec["class_weight"] else
                     (np.bincount(y, minlength=len(classes)) / len(y)).tolist(),
                  "prior_caveat": "Nominal loss/sample weights are not proof of calibrated posterior probabilities or label shift.",
                  "development_macro_f1_supported": metrics["macro_f1_supported"],
                  "model_file_bytes": model_path.stat().st_size, "model_sha256": sha256(model_path),
                  "storage": raw_model_storage(estimator), "head_cpu_latency": cost,
                  "fit_warnings": warning_messages}
        if hasattr(estimator, "steps"):
            result["optimizer_iterations"] = estimator.steps[-1][1].n_iter_.tolist()
        dump(directory / "cost.json", result)
        summaries.append(result)
        dump(args.output / "development-summary.json", summaries)
        print(json.dumps({key: result[key] for key in ("candidate", "fit_seconds", "development_macro_f1_supported", "model_file_bytes", "fit_warnings")}), flush=True)
        del estimator
    selected = max(summaries, key=lambda row: row["development_macro_f1_supported"])["candidate"]
    dump(args.output / "selection.json", {"selected_candidate": selected,
         "selection_frozen_at": datetime.now(timezone.utc).isoformat(), "report_metrics_computed": False,
         "method": config["selection"]})
    for summary in summaries:
        directory = args.output / summary["candidate"]
        # Only load models produced by this process, with byte identity checked.
        model_path = directory / "model.joblib"
        if sha256(model_path) != summary["model_sha256"]:
            raise ValueError("Model changed between training and reporting")
        estimator = joblib.load(model_path)
        with threadpool_limits(limits=args.jobs):
            probabilities = aligned_probabilities(estimator, val, len(classes), np)
        predicted = probabilities.argmax(1)
        np.savez_compressed(directory / "validation-probabilities.npz", probabilities=probabilities,
                            class_names=arrays["class_names"], val_labels=arrays["val_labels"],
                            val_sample_ids=arrays["val_sample_ids"], val_groups=arrays["val_groups"],
                            dev_indices=dev, report_indices=report)
        partitions = {"report": report, "all_reused_validation": np.arange(len(val))}
        for name, indices in partitions.items():
            metrics = calculate_metrics(arrays["val_labels"][indices], predicted[indices], classes)
            old = indices[arrays["val_labels"][indices] < 134]
            metrics["old_targets_only"] = calculate_metrics(arrays["val_labels"][old], predicted[old], classes) if len(old) else None
            dump(directory / f"{name}-metrics.json", metrics)
            summary[f"{name}_macro_f1_supported"] = metrics["macro_f1_supported"]
        summary["selected_on_development"] = summary["candidate"] == selected
        print(json.dumps({"candidate": summary["candidate"], "selected": summary["selected_on_development"],
                          "report_macro_f1_supported": summary["report_macro_f1_supported"]}), flush=True)
        del estimator
    dump(args.output / "summary.json", summaries)
    dump(args.output / "complete.json", {"completed_at": datetime.now(timezone.utc).isoformat(),
         "selected_candidate": selected, "candidate_count": len(summaries),
         "report_partition_used_for_selection": False, "test_images_read": False})


if __name__ == "__main__":
    main()
