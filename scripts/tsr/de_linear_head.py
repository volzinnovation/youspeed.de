#!/usr/bin/env python3
"""Fold a fitted StandardScaler and multinomial logistic head into one Linear.

This utility only handles numerical arrays; it never loads pickle or model code.
The 136 fitted classes must match the expected DE output order exactly. Folding
is exact over real arithmetic, but Float32 rounding requires measured parity on
representative feature rows before a derived checkpoint can be accepted.

Input NPZ keys: mean, scale, coef, intercept, estimator_classes, class_names.
The expected class-index JSON contains a 136-element `classes` list.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

import numpy as np


CLASS_COUNT = 136
REQUIRED_ARRAYS = {"mean", "scale", "coef", "intercept", "estimator_classes", "class_names"}


def _numeric_array(value, name):
    array = np.asarray(value)
    if array.dtype.kind not in "fiu" or not np.isfinite(array).all():
        raise ValueError(f"{name} must contain finite real numerical values")
    return array


def validate_inputs(mean, scale, coef, intercept, estimator_classes,
                    fitted_class_names, expected_class_names):
    fitted = list(fitted_class_names)
    expected = list(expected_class_names)
    if (len(expected) != CLASS_COUNT
            or any(not isinstance(name, str) or not name for name in expected)
            or len(set(expected)) != CLASS_COUNT
            or expected[-2:] != ["city:start", "city:end"]):
        raise ValueError("Expected unique DE136 names ending with city:start/city:end")
    if fitted != expected:
        raise ValueError("Fitted class names do not match the expected output order")
    indices = np.asarray(estimator_classes)
    if (indices.shape != (CLASS_COUNT,) or indices.dtype.kind not in "iu"
            or not np.array_equal(indices, np.arange(CLASS_COUNT))):
        raise ValueError("Estimator classes must be exactly 0..135 in expected order")
    arrays = {name: _numeric_array(value, name) for name, value in
              (("mean", mean), ("scale", scale), ("coef", coef), ("intercept", intercept))}
    if arrays["coef"].ndim != 2 or arrays["coef"].shape[0] != CLASS_COUNT or arrays["coef"].shape[1] < 1:
        raise ValueError("coef must have shape [136, nonzero feature dimensions]")
    dimensions = arrays["coef"].shape[1]
    if arrays["mean"].shape != (dimensions,) or arrays["scale"].shape != (dimensions,):
        raise ValueError("Scaler mean and scale must match coefficient feature dimensions")
    if arrays["intercept"].shape != (CLASS_COUNT,):
        raise ValueError("intercept must have one value per output class")
    if (arrays["scale"] <= 0).any():
        raise ValueError("Scaler scale must be strictly positive; zero-variance features use scale=1")
    return {name: value.astype(np.float64, copy=False) for name, value in arrays.items()}


def fold_standardized_head(mean, scale, coef, intercept, estimator_classes,
                           fitted_class_names, expected_class_names, *, dtype="float32"):
    """Return [136,D] weights and [136] bias for unstandardized embeddings."""
    arrays = validate_inputs(mean, scale, coef, intercept, estimator_classes,
                             fitted_class_names, expected_class_names)
    if dtype not in ("float32", "float64"):
        raise ValueError("Only explicit float32 or float64 output is supported")
    # Check actual arrays below instead of depending on BLAS floating-point
    # status flags, whose warning behavior differs between host runtimes.
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        weights = arrays["coef"] / arrays["scale"][None, :]
        bias = arrays["intercept"] - weights @ arrays["mean"]
    if not np.isfinite(weights).all() or not np.isfinite(bias).all():
        raise ValueError("Folding produced nonfinite values")
    with np.errstate(over="ignore", invalid="ignore"):
        weights = weights.astype(dtype)
        bias = bias.astype(dtype)
    if not np.isfinite(weights).all() or not np.isfinite(bias).all():
        raise ValueError(f"Folded weights or bias cannot be represented in {dtype}")
    return weights, bias


def stable_softmax(logits):
    logits = np.asarray(logits, dtype=np.float64)
    shifted = logits - logits.max(axis=1, keepdims=True)
    values = np.exp(shifted)
    return values / values.sum(axis=1, keepdims=True)


def parity_report(features, mean, scale, coef, intercept, weights, bias):
    """Compare declared scaler arithmetic with folded arithmetic on exact rows.

    StandardScaler subtracts/divides in place, retaining input Float32/Float64.
    The reference here follows those two casts before applying fitted logistic
    coefficients. Probabilities use Float64 softmax for both logit arrays, so the
    reported probability difference isolates the folding/linear arithmetic.
    Native Core ML/LiteRT numerical parity is a separate check.
    """
    features = _numeric_array(features, "features")
    if features.ndim != 2 or not len(features) or features.dtype not in (np.dtype("float32"), np.dtype("float64")):
        raise ValueError("Parity features must be a nonempty Float32/Float64 matrix")
    weights, bias = _numeric_array(weights, "weights"), _numeric_array(bias, "bias")
    mean, scale = _numeric_array(mean, "mean"), _numeric_array(scale, "scale")
    coef, intercept = _numeric_array(coef, "coef"), _numeric_array(intercept, "intercept")
    if (weights.ndim != 2 or weights.shape[0] != CLASS_COUNT
            or coef.shape != weights.shape or len(features[0]) != weights.shape[1]
            or bias.shape != (weights.shape[0],) or intercept.shape != bias.shape
            or mean.shape != (weights.shape[1],) or scale.shape != mean.shape):
        raise ValueError("Parity array dimensions do not agree")
    if (scale <= 0).any() or weights.dtype not in (np.dtype("float32"), np.dtype("float64")) or bias.dtype != weights.dtype:
        raise ValueError("Parity needs positive scales and same-precision float weights/bias")
    with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
        standardized = features.copy()
        standardized -= mean
        standardized /= scale
        reference_logits = standardized @ coef.T + intercept
        folded_logits = features.astype(weights.dtype) @ weights.T + bias
    if not np.isfinite(reference_logits).all() or not np.isfinite(folded_logits).all():
        raise ValueError("Nonfinite parity logits")
    reference_probabilities = stable_softmax(reference_logits)
    folded_probabilities = stable_softmax(folded_logits)
    reference_labels = reference_logits.argmax(axis=1)
    folded_labels = folded_logits.argmax(axis=1)
    differences = np.flatnonzero(reference_labels != folded_labels)
    logit_errors = np.abs(reference_logits.astype(np.float64) - folded_logits.astype(np.float64))
    sorted_scores = np.sort(reference_logits, axis=1)
    return {
        "rows": len(features), "feature_dtype": str(features.dtype), "folded_dtype": str(weights.dtype),
        "max_absolute_logit_error": float(logit_errors.max()),
        "mean_absolute_logit_error": float(logit_errors.mean()),
        "max_absolute_probability_error": float(np.abs(reference_probabilities - folded_probabilities).max()),
        "argmax_disagreements": len(differences), "all_argmax_equal": len(differences) == 0,
        "disagreement_indices": differences.tolist(),
        "minimum_reference_top2_logit_margin": float((sorted_scores[:, -1] - sorted_scores[:, -2]).min()),
        "reference_arithmetic": "In-place StandardScaler-like subtraction/division retaining feature dtype, then fitted coefficient precision",
        "probability_arithmetic": "Float64 softmax of each logit array; native runtime softmax not measured",
        "scope": "Numerical head folding on supplied frozen features; not recognition or mobile-runtime acceptance",
    }


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--parameters", type=Path, required=True)
    parser.add_argument("--class-index", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="New .npz file; metadata uses the same stem.json")
    parser.add_argument("--dtype", choices=("float32", "float64"), default="float32")
    parser.add_argument("--parity-features", type=Path, help="Optional non-pickle feature NPZ")
    parser.add_argument("--feature-key", default="val_features")
    args = parser.parse_args(argv)
    metadata_path = args.output.with_suffix(".json")
    if args.output.suffix != ".npz" or args.output.exists() or metadata_path.exists():
        raise ValueError("Require a new .npz output and unused metadata filename")
    class_index = json.loads(args.class_index.read_text())
    expected = class_index["classes"]
    with np.load(args.parameters, allow_pickle=False) as archive:
        if missing := REQUIRED_ARRAYS - set(archive.files):
            raise ValueError(f"Missing fitted parameter arrays: {sorted(missing)}")
        arrays = {key: archive[key] for key in REQUIRED_ARRAYS}
    weights, bias = fold_standardized_head(
        arrays["mean"], arrays["scale"], arrays["coef"], arrays["intercept"], arrays["estimator_classes"],
        arrays["class_names"].tolist(), expected, dtype=args.dtype,
    )
    metadata = {"created_at": datetime.now(timezone.utc).isoformat(), "script_sha256": sha256(__file__),
                "parameters_npz_sha256": sha256(args.parameters), "class_index_sha256": sha256(args.class_index),
                "class_count": CLASS_COUNT, "feature_dimensions": weights.shape[1], "dtype": args.dtype,
                "formula": "W'=coef/scale; b'=intercept-W'@mean",
                "probability_link_assumption": "multinomial softmax, as in the fitted lbfgs logistic classifier",
                "calculation_precision": "float64 then cast to selected output dtype",
                "numpy": np.__version__, "native_model_exported": False,
                "parity": None}
    if args.parity_features:
        with np.load(args.parity_features, allow_pickle=False) as archive:
            features = archive[args.feature_key]
            if "class_names" in archive.files and archive["class_names"].tolist() != expected:
                raise ValueError("Parity feature taxonomy differs from expected class order")
        metadata["parity_feature_npz_sha256"] = sha256(args.parity_features)
        metadata["parity_feature_key"] = args.feature_key
        metadata["parity"] = parity_report(features, arrays["mean"], arrays["scale"], arrays["coef"],
                                            arrays["intercept"], weights, bias)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(args.output, weights=weights, bias=bias,
                        class_names=np.asarray(expected), estimator_classes=np.arange(CLASS_COUNT))
    metadata["output_npz_sha256"] = sha256(args.output)
    metadata_path.write_text(json.dumps(metadata, indent=2, allow_nan=False) + "\n")
    print(json.dumps({"output": str(args.output), "dtype": args.dtype, "parity": metadata["parity"]}))


if __name__ == "__main__":
    main()
