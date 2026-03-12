#!/usr/bin/env python3
"""Train and export a lightweight online linear candidate ranker.

The model is intentionally simple:
- pointwise candidate features
- perceptron-style online ranking updates on hindsight pseudo-labels
- averaged weights

This is designed to match a tiny on-device scorer that can be mirrored in Swift.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean


CONTINUITY_CLASSES = ["preferredWay", "sameRef", "linkedWay", "recentWay", "none"]
HIGHWAY_CLASSES = ["primary", "secondary", "residential", "tertiary", "unclassified", "service"]
NON_STANDARDIZED = {
    "bias",
    "candidate_has_street_ref",
    "candidate_is_service",
    "heuristic_matches_candidate",
    "mini_hmm_matches_candidate",
    "used_mini_hmm",
    "candidate_tunnel_selectable",
    "is_stationary",
    "mini_and_mini_candidate",
    "mini_and_heuristic_candidate",
    "low_endpoint",
}


@dataclass(frozen=True)
class Example:
    example_id: str
    timestamp_utc: str
    rows: list[dict[str, str]]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate_csv", type=Path)
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--swift-out", type=Path)
    return parser.parse_args()


def load_examples(path: Path) -> list[Example]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    with path.open(newline="") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            grouped[row["example_id"]].append(row)
    examples = [
        Example(example_id=example_id, timestamp_utc=rows[0]["timestamp_utc"], rows=rows)
        for example_id, rows in grouped.items()
    ]
    examples.sort(key=lambda example: example.timestamp_utc)
    return examples


def feature_map(row: dict[str, str]) -> dict[str, float]:
    values: dict[str, float] = {
        "bias": 1.0,
        "candidate_score": float(row["candidate_score"] or 0.0),
        "candidate_distance_m": float(row["candidate_distance_m"] or 0.0),
        "candidate_endpoint_proximity_m": float(row["candidate_endpoint_proximity_m"] or 0.0),
        "candidate_rank": float(row["candidate_rank"] or 0.0),
        "speed_kmh": float(row["speed_kmh"] or 0.0),
        "horizontal_acc_m": float(row["horizontal_acc_m"] or 0.0),
        "gps_signal_bars": float(row["gps_signal_bars"] or 0.0),
        "top2_margin": float(row["top2_margin"] or 0.0),
        "candidate_has_street_ref": float(row["candidate_has_street_ref"] or 0.0),
        "candidate_is_service": float(row["candidate_is_service"] or 0.0),
        "heuristic_matches_candidate": float(row["heuristic_matches_candidate"] or 0.0),
        "mini_hmm_matches_candidate": float(row["mini_hmm_matches_candidate"] or 0.0),
        "used_mini_hmm": float(row["used_mini_hmm"] or 0.0),
        "candidate_tunnel_selectable": float(row["candidate_tunnel_selectable"] or 0.0),
    }

    continuity = row["candidate_continuity_class"] or "none"
    for continuity_class in CONTINUITY_CLASSES:
        values[f"cont_{continuity_class}"] = 1.0 if continuity == continuity_class else 0.0

    highway = row["candidate_highway"] or ""
    matched_highway = False
    for highway_class in HIGHWAY_CLASSES:
        is_match = highway == highway_class
        values[f"hw_{highway_class}"] = 1.0 if is_match else 0.0
        matched_highway = matched_highway or is_match
    values["hw_other"] = 0.0 if matched_highway or not highway else 1.0

    endpoint_proximity = values["candidate_endpoint_proximity_m"]
    values["is_stationary"] = 1.0 if values["speed_kmh"] < 3.0 else 0.0
    values["mini_and_mini_candidate"] = values["used_mini_hmm"] * values["mini_hmm_matches_candidate"]
    values["mini_and_heuristic_candidate"] = values["used_mini_hmm"] * values["heuristic_matches_candidate"]
    values["low_endpoint"] = 1.0 if endpoint_proximity <= 12.0 else 0.0
    return values


def build_feature_spec(train_examples: list[Example]) -> tuple[list[str], dict[str, float], dict[str, float]]:
    sample = feature_map(train_examples[0].rows[0])
    feature_names = list(sample.keys())
    means: dict[str, float] = {}
    stds: dict[str, float] = {}
    flattened_rows = [row for example in train_examples for row in example.rows]

    for name in feature_names:
        values = [feature_map(row)[name] for row in flattened_rows]
        if name in NON_STANDARDIZED or name.startswith("cont_") or name.startswith("hw_"):
            means[name] = 0.0
            stds[name] = 1.0
            continue
        mean = fmean(values)
        variance = fmean([(value - mean) ** 2 for value in values])
        means[name] = mean
        stds[name] = math.sqrt(variance) if variance > 1e-12 else 1.0
    return feature_names, means, stds


def vectorize(
    row: dict[str, str],
    feature_names: list[str],
    means: dict[str, float],
    stds: dict[str, float],
) -> list[float]:
    values = feature_map(row)
    return [(values[name] - means[name]) / stds[name] for name in feature_names]


def dot(weights: list[float], vector: list[float]) -> float:
    return sum(weight * value for weight, value in zip(weights, vector))


def split_examples(examples: list[Example]) -> tuple[list[Example], list[Example], list[Example]]:
    total = len(examples)
    train_end = int(total * 0.6)
    val_end = int(total * 0.8)
    return examples[:train_end], examples[train_end:val_end], examples[val_end:]


def evaluate(
    examples: list[Example],
    weights: list[float],
    feature_names: list[str],
    means: dict[str, float],
    stds: dict[str, float],
) -> dict[str, float | int]:
    total = 0
    correct = 0
    changed_total = 0
    changed_correct = 0
    unchanged_total = 0
    unchanged_correct = 0
    for example in examples:
        vectors = [vectorize(row, feature_names, means, stds) for row in example.rows]
        scores = [dot(weights, vector) for vector in vectors]
        predicted_index = max(range(len(scores)), key=scores.__getitem__)
        true_index = max(range(len(example.rows)), key=lambda index: int(example.rows[index]["label_is_pseudo_label"]))
        is_changed = int(example.rows[0]["label_switch_to_pseudo"]) == 1
        total += 1
        if predicted_index == true_index:
            correct += 1
        if is_changed:
            changed_total += 1
            if predicted_index == true_index:
                changed_correct += 1
        else:
            unchanged_total += 1
            if predicted_index == true_index:
                unchanged_correct += 1
    return {
        "examples": total,
        "accuracy": correct / total if total else 0.0,
        "changed_examples": changed_total,
        "changed_recall": changed_correct / changed_total if changed_total else 0.0,
        "unchanged_examples": unchanged_total,
        "unchanged_accuracy": unchanged_correct / unchanged_total if unchanged_total else 0.0,
    }


def train(
    train_examples: list[Example],
    val_examples: list[Example],
    feature_names: list[str],
    means: dict[str, float],
    stds: dict[str, float],
) -> tuple[dict[str, float], list[float]]:
    best_metrics: dict[str, float] | None = None
    best_weights: list[float] | None = None
    best_params: dict[str, float] | None = None
    dimensions = len(feature_names)

    for learning_rate in [0.02, 0.05, 0.1, 0.2]:
        for weight_decay in [0.0, 1e-4, 5e-4]:
            for epochs in [1, 2, 4, 8, 12]:
                weights = [0.0] * dimensions
                averaged = [0.0] * dimensions
                update_count = 0
                for _ in range(epochs):
                    for example in train_examples:
                        vectors = [vectorize(row, feature_names, means, stds) for row in example.rows]
                        scores = [dot(weights, vector) for vector in vectors]
                        predicted_index = max(range(len(scores)), key=scores.__getitem__)
                        true_index = max(range(len(example.rows)), key=lambda index: int(example.rows[index]["label_is_pseudo_label"]))
                        for index in range(dimensions):
                            weights[index] *= 1.0 - weight_decay
                        if predicted_index != true_index:
                            for index in range(dimensions):
                                weights[index] += learning_rate * (
                                    vectors[true_index][index] - vectors[predicted_index][index]
                                )
                        update_count += 1
                        for index in range(dimensions):
                            averaged[index] += weights[index]
                averaged_weights = [value / max(update_count, 1) for value in averaged]
                metrics = evaluate(val_examples, averaged_weights, feature_names, means, stds)
                ranking = (metrics["accuracy"], metrics["changed_recall"], metrics["unchanged_accuracy"])
                if best_metrics is None or ranking > (
                    best_metrics["accuracy"],
                    best_metrics["changed_recall"],
                    best_metrics["unchanged_accuracy"],
                ):
                    best_metrics = metrics
                    best_weights = averaged_weights
                    best_params = {
                        "learning_rate": learning_rate,
                        "weight_decay": weight_decay,
                        "epochs": epochs,
                    }

    assert best_metrics is not None
    assert best_weights is not None
    assert best_params is not None
    return {**best_metrics, **best_params}, best_weights


def render_swift(
    feature_names: list[str],
    means: dict[str, float],
    stds: dict[str, float],
    weights: list[float],
) -> str:
    def array(values: list[float]) -> str:
        return ",\n            ".join(f"{value:.12f}" for value in values)

    escaped_feature_names = ",\n            ".join(f'"{name}"' for name in feature_names)
    mean_values = [means[name] for name in feature_names]
    std_values = [stds[name] for name in feature_names]
    return f"""import Foundation

enum DriveMatchOnlineLinearRankerModel {{
    static let featureNames: [String] = [
            {escaped_feature_names}
    ]

    static let means: [Double] = [
            {array(mean_values)}
    ]

    static let standardDeviations: [Double] = [
            {array(std_values)}
    ]

    static let weights: [Double] = [
            {array(weights)}
    ]
}}
"""


def main() -> None:
    args = parse_args()
    examples = load_examples(args.candidate_csv)
    train_examples, val_examples, test_examples = split_examples(examples)
    feature_names, means, stds = build_feature_spec(train_examples)
    best_params, weights = train(train_examples, val_examples, feature_names, means, stds)
    payload = {
        "feature_names": feature_names,
        "means": [means[name] for name in feature_names],
        "standard_deviations": [stds[name] for name in feature_names],
        "weights": weights,
        "split": {
            "train_examples": len(train_examples),
            "val_examples": len(val_examples),
            "test_examples": len(test_examples),
        },
        "best_validation": best_params,
        "test_metrics": evaluate(test_examples, weights, feature_names, means, stds),
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    if args.swift_out:
        args.swift_out.write_text(render_swift(feature_names, means, stds, weights))
    print(json.dumps({"best_validation": best_params, "test_metrics": payload["test_metrics"]}, indent=2))


if __name__ == "__main__":
    main()
