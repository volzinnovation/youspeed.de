#!/usr/bin/env python3
"""Train and export a lightweight disagreement gate.

The gate only arbitrates between two experts:
- the current selected way from the log
- the lowest-distance candidate in the same candidate set

This matches the main residual decision boundary seen in hindsight labels while
keeping the exported on-device scorer tiny and auditable.
"""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from statistics import fmean
from typing import Any

import numpy as np

from train_online_linear_ranker import CONTINUITY_CLASSES, Example, HIGHWAY_CLASSES, load_examples, split_examples


NON_STANDARDIZED = {
    "bias",
    "used_mini_hmm",
    "mini_matches_current",
    "mini_matches_distance",
    "current_has_ref",
    "distance_has_ref",
    "current_is_service",
    "distance_is_service",
    "current_tunnel_selectable",
    "distance_tunnel_selectable",
    "same_ref",
    "same_highway",
    "same_continuity",
    "current_low_endpoint",
    "distance_low_endpoint",
    "current_rank1",
    "distance_rank1",
    "current_score_better",
    "distance_score_better",
}


@dataclass(frozen=True)
class GateCase:
    example_id: str
    timestamp_utc: str
    current_index: int
    distance_index: int
    current_row: dict[str, str]
    distance_row: dict[str, str]
    choose_distance: int | None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate_csv", type=Path)
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--swift-out", type=Path)
    return parser.parse_args()


def row_float(row: dict[str, str], key: str) -> float:
    value = row.get(key)
    return float(value or 0.0)


def row_int(row: dict[str, str], key: str) -> int:
    value = row.get(key)
    return int(value or 0)


def highway_bucket(row: dict[str, str]) -> str:
    highway = row.get("candidate_highway") or ""
    return highway if highway in HIGHWAY_CLASSES else "other"


def pick_current_index(rows: list[dict[str, str]]) -> int:
    for index, row in enumerate(rows):
        if row_int(row, "label_is_current_selected") == 1:
            return index
    return 0


def pick_lowest_distance_index(rows: list[dict[str, str]]) -> int:
    return min(
        range(len(rows)),
        key=lambda item: (
            row_float(rows[item], "candidate_distance_m"),
            row_int(rows[item], "candidate_rank") or 10_000,
        ),
    )


def pick_pseudo_index(rows: list[dict[str, str]]) -> int:
    for index, row in enumerate(rows):
        if row_int(row, "label_is_pseudo_label") == 1:
            return index
    return 0


def build_gate_cases(examples: list[Example]) -> list[GateCase]:
    cases: list[GateCase] = []
    for example in examples:
        current_index = pick_current_index(example.rows)
        distance_index = pick_lowest_distance_index(example.rows)
        if current_index == distance_index:
            continue
        pseudo_index = pick_pseudo_index(example.rows)
        choose_distance: int | None
        if pseudo_index == distance_index:
            choose_distance = 1
        elif pseudo_index == current_index:
            choose_distance = 0
        else:
            choose_distance = None
        cases.append(
            GateCase(
                example_id=example.example_id,
                timestamp_utc=example.timestamp_utc,
                current_index=current_index,
                distance_index=distance_index,
                current_row=example.rows[current_index],
                distance_row=example.rows[distance_index],
                choose_distance=choose_distance,
            )
        )
    cases.sort(key=lambda case: (case.timestamp_utc, case.example_id))
    return cases


def feature_map(case: GateCase) -> dict[str, float]:
    current = case.current_row
    distance = case.distance_row

    current_distance_m = row_float(current, "candidate_distance_m")
    distance_distance_m = row_float(distance, "candidate_distance_m")
    current_score = row_float(current, "candidate_score")
    distance_score = row_float(distance, "candidate_score")
    current_endpoint_m = row_float(current, "candidate_endpoint_proximity_m")
    distance_endpoint_m = row_float(distance, "candidate_endpoint_proximity_m")
    current_rank = row_float(current, "candidate_rank")
    distance_rank = row_float(distance, "candidate_rank")
    current_band = row_float(current, "candidate_continuity_band")
    distance_band = row_float(distance, "candidate_continuity_band")

    distance_advantage_m = current_distance_m - distance_distance_m
    score_advantage = current_score - distance_score
    endpoint_advantage_m = current_endpoint_m - distance_endpoint_m
    rank_advantage = current_rank - distance_rank
    band_advantage = current_band - distance_band
    speed_kmh = row_float(current, "speed_kmh")
    horizontal_acc_m = row_float(current, "horizontal_acc_m")
    gps_signal_bars = row_float(current, "gps_signal_bars")
    top2_margin = row_float(current, "top2_margin")

    values: dict[str, float] = {
        "bias": 1.0,
        "distance_advantage_m": distance_advantage_m,
        "score_advantage": score_advantage,
        "endpoint_advantage_m": endpoint_advantage_m,
        "rank_advantage": rank_advantage,
        "band_advantage": band_advantage,
        "current_distance_m": current_distance_m,
        "distance_distance_m": distance_distance_m,
        "current_score": current_score,
        "distance_score": distance_score,
        "speed_kmh": speed_kmh,
        "horizontal_acc_m": horizontal_acc_m,
        "gps_signal_bars": gps_signal_bars,
        "top2_margin": top2_margin,
        "used_mini_hmm": row_float(current, "used_mini_hmm"),
        "mini_matches_current": row_float(current, "mini_hmm_matches_candidate"),
        "mini_matches_distance": row_float(distance, "mini_hmm_matches_candidate"),
        "current_has_ref": row_float(current, "candidate_has_street_ref"),
        "distance_has_ref": row_float(distance, "candidate_has_street_ref"),
        "current_is_service": row_float(current, "candidate_is_service"),
        "distance_is_service": row_float(distance, "candidate_is_service"),
        "current_tunnel_selectable": row_float(current, "candidate_tunnel_selectable"),
        "distance_tunnel_selectable": row_float(distance, "candidate_tunnel_selectable"),
        "same_ref": 1.0
        if (current.get("candidate_street_ref") or "")
        and current.get("candidate_street_ref") == distance.get("candidate_street_ref")
        else 0.0,
        "same_highway": 1.0 if highway_bucket(current) == highway_bucket(distance) else 0.0,
        "same_continuity": 1.0
        if (current.get("candidate_continuity_class") or "none")
        == (distance.get("candidate_continuity_class") or "none")
        else 0.0,
        "current_low_endpoint": 1.0 if current_endpoint_m <= 12.0 else 0.0,
        "distance_low_endpoint": 1.0 if distance_endpoint_m <= 12.0 else 0.0,
        "current_rank1": 1.0 if current_rank <= 1.0 else 0.0,
        "distance_rank1": 1.0 if distance_rank <= 1.0 else 0.0,
        "current_score_better": 1.0 if current_score < distance_score else 0.0,
        "distance_score_better": 1.0 if distance_score < current_score else 0.0,
        "distance_advantage_per_accuracy": distance_advantage_m / max(horizontal_acc_m, 1.0),
        "score_advantage_per_accuracy": score_advantage / max(horizontal_acc_m, 1.0),
        "distance_advantage_times_current_preferred": 0.0,
        "distance_advantage_times_distance_preferred": 0.0,
        "distance_advantage_times_mini_current": distance_advantage_m * row_float(current, "mini_hmm_matches_candidate"),
        "distance_advantage_times_mini_distance": distance_advantage_m * row_float(distance, "mini_hmm_matches_candidate"),
    }

    current_continuity = current.get("candidate_continuity_class") or "none"
    distance_continuity = distance.get("candidate_continuity_class") or "none"
    for continuity_class in CONTINUITY_CLASSES:
        values[f"current_cont_{continuity_class}"] = 1.0 if current_continuity == continuity_class else 0.0
        values[f"distance_cont_{continuity_class}"] = 1.0 if distance_continuity == continuity_class else 0.0
    values["distance_advantage_times_current_preferred"] = distance_advantage_m * values["current_cont_preferredWay"]
    values["distance_advantage_times_distance_preferred"] = distance_advantage_m * values["distance_cont_preferredWay"]

    current_highway = highway_bucket(current)
    distance_highway = highway_bucket(distance)
    for highway_class in [*HIGHWAY_CLASSES, "other"]:
        values[f"current_hw_{highway_class}"] = 1.0 if current_highway == highway_class else 0.0
        values[f"distance_hw_{highway_class}"] = 1.0 if distance_highway == highway_class else 0.0
    return values


def build_feature_spec(train_cases: list[GateCase]) -> tuple[list[str], dict[str, float], dict[str, float]]:
    sample = feature_map(train_cases[0])
    feature_names = list(sample.keys())
    means: dict[str, float] = {}
    stds: dict[str, float] = {}
    flattened = [feature_map(case) for case in train_cases]
    for name in feature_names:
        values = [row[name] for row in flattened]
        if (
            name in NON_STANDARDIZED
            or name.startswith("current_cont_")
            or name.startswith("distance_cont_")
            or name.startswith("current_hw_")
            or name.startswith("distance_hw_")
        ):
            means[name] = 0.0
            stds[name] = 1.0
            continue
        mean = fmean(values)
        variance = fmean([(value - mean) ** 2 for value in values])
        means[name] = mean
        stds[name] = math.sqrt(variance) if variance > 1e-12 else 1.0
    return feature_names, means, stds


def vectorize(
    case: GateCase,
    feature_names: list[str],
    means: dict[str, float],
    stds: dict[str, float],
) -> np.ndarray:
    values = feature_map(case)
    return np.array([(values[name] - means[name]) / stds[name] for name in feature_names], dtype=np.float64)


def sigmoid(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, -40.0, 40.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def is_finite_array(*arrays: np.ndarray | float) -> bool:
    return all(np.all(np.isfinite(array)) for array in arrays)


def build_training_matrix(
    cases: list[GateCase],
    feature_names: list[str],
    means: dict[str, float],
    stds: dict[str, float],
) -> tuple[np.ndarray, np.ndarray]:
    eligible = [case for case in cases if case.choose_distance is not None]
    x = np.vstack([vectorize(case, feature_names, means, stds) for case in eligible])
    y = np.array([int(case.choose_distance) for case in eligible], dtype=np.float64)
    return x, y


def gate_score(
    case: GateCase,
    weights: np.ndarray,
    feature_names: list[str],
    means: dict[str, float],
    stds: dict[str, float],
) -> float:
    vector = vectorize(case, feature_names, means, stds)
    if not is_finite_array(vector, weights):
        return 0.0
    with np.errstate(all="ignore"):
        logit = float(vector @ weights)
    if not math.isfinite(logit):
        return 0.0
    return 1.0 / (1.0 + math.exp(-max(min(logit, 40.0), -40.0)))


def gate_predictions(
    examples: list[Example],
    weights: np.ndarray,
    threshold: float,
    feature_names: list[str],
    means: dict[str, float],
    stds: dict[str, float],
) -> list[int]:
    case_by_id = {case.example_id: case for case in build_gate_cases(examples)}
    predictions: list[int] = []
    for example in examples:
        current_index = pick_current_index(example.rows)
        distance_index = pick_lowest_distance_index(example.rows)
        if current_index == distance_index:
            predictions.append(current_index)
            continue
        case = case_by_id[example.example_id]
        predictions.append(distance_index if gate_score(case, weights, feature_names, means, stds) >= threshold else current_index)
    return predictions


def evaluate_examples(examples: list[Example], predicted_indices: list[int]) -> dict[str, float | int]:
    total = 0
    correct = 0
    changed_total = 0
    changed_correct = 0
    unchanged_total = 0
    unchanged_correct = 0
    disagreement_total = 0
    disagreement_correct = 0
    for example, predicted_index in zip(examples, predicted_indices):
        true_index = pick_pseudo_index(example.rows)
        current_index = pick_current_index(example.rows)
        distance_index = pick_lowest_distance_index(example.rows)
        changed = row_int(example.rows[0], "label_switch_to_pseudo") == 1
        disagrees = current_index != distance_index
        total += 1
        is_correct = predicted_index == true_index
        correct += int(is_correct)
        if changed:
            changed_total += 1
            changed_correct += int(is_correct)
        else:
            unchanged_total += 1
            unchanged_correct += int(is_correct)
        if disagrees:
            disagreement_total += 1
            disagreement_correct += int(is_correct)
    return {
        "examples": total,
        "correct": correct,
        "accuracy": correct / total if total else 0.0,
        "changed_examples": changed_total,
        "changed_recall": changed_correct / changed_total if changed_total else 0.0,
        "unchanged_examples": unchanged_total,
        "unchanged_accuracy": unchanged_correct / unchanged_total if unchanged_total else 0.0,
        "disagreement_examples": disagreement_total,
        "disagreement_accuracy": disagreement_correct / disagreement_total if disagreement_total else 0.0,
    }


def eligible_stats(cases: list[GateCase]) -> dict[str, int]:
    stats = {
        "disagreement_examples": len(cases),
        "eligible_examples": 0,
        "choose_current_examples": 0,
        "choose_distance_examples": 0,
        "neither_expert_examples": 0,
    }
    for case in cases:
        if case.choose_distance is None:
            stats["neither_expert_examples"] += 1
            continue
        stats["eligible_examples"] += 1
        if case.choose_distance == 1:
            stats["choose_distance_examples"] += 1
        else:
            stats["choose_current_examples"] += 1
    return stats


def train(
    train_examples: list[Example],
    val_examples: list[Example],
) -> tuple[dict[str, Any], dict[str, Any]]:
    train_cases = build_gate_cases(train_examples)
    val_cases = build_gate_cases(val_examples)
    trainable_cases = [case for case in train_cases if case.choose_distance is not None]
    if not trainable_cases:
        raise ValueError("No disagreement cases available for gate training.")

    feature_names, means, stds = build_feature_spec(trainable_cases)
    x_train, y_train = build_training_matrix(train_cases, feature_names, means, stds)
    pos_count = float(np.sum(y_train == 1.0))
    neg_count = float(len(y_train) - pos_count)
    pos_weight = neg_count / max(pos_count, 1.0)
    sample_weights = np.where(y_train == 1.0, pos_weight, 1.0)

    best_summary: dict[str, Any] | None = None
    best_weights: np.ndarray | None = None
    best_threshold = 0.5
    dimensions = x_train.shape[1]
    for learning_rate in [0.005, 0.01, 0.02, 0.05]:
        for l2 in [0.0, 1e-4, 1e-3]:
            weights = np.zeros(dimensions, dtype=np.float64)
            for epoch in range(1, 501):
                if not is_finite_array(x_train, y_train, sample_weights, weights):
                    break
                with np.errstate(all="ignore"):
                    logits = x_train @ weights
                    probs = sigmoid(logits)
                    errors = (probs - y_train) * sample_weights
                    gradient = (x_train.T @ errors) / len(y_train) + (l2 * weights)
                if not is_finite_array(logits, probs, errors, gradient):
                    break
                gradient = np.clip(gradient, -5.0, 5.0)
                weights -= learning_rate * gradient
                weights = np.clip(weights, -25.0, 25.0)
                if not is_finite_array(weights):
                    break
                if epoch not in {10, 25, 50, 100, 200, 300, 400, 500}:
                    continue
                for threshold in [0.35, 0.4, 0.45, 0.5, 0.55, 0.6]:
                    metrics = evaluate_examples(
                        val_examples,
                        gate_predictions(val_examples, weights, threshold, feature_names, means, stds),
                    )
                    ranking = (
                        metrics["accuracy"],
                        metrics["changed_recall"],
                        metrics["unchanged_accuracy"],
                        metrics["disagreement_accuracy"],
                    )
                    if best_summary is None or ranking > (
                        best_summary["accuracy"],
                        best_summary["changed_recall"],
                        best_summary["unchanged_accuracy"],
                        best_summary["disagreement_accuracy"],
                    ):
                        best_summary = {
                            **metrics,
                            "epoch": epoch,
                            "learning_rate": learning_rate,
                            "l2": l2,
                            "threshold": threshold,
                            "train_stats": eligible_stats(train_cases),
                            "val_stats": eligible_stats(val_cases),
                        }
                        best_weights = weights.copy()
                        best_threshold = threshold

    assert best_summary is not None
    assert best_weights is not None
    return best_summary, {
        "feature_names": feature_names,
        "means": means,
        "stds": stds,
        "weights": best_weights,
        "threshold": best_threshold,
        "train_stats": eligible_stats(train_cases),
        "val_stats": eligible_stats(val_cases),
    }


def render_swift(
    feature_names: list[str],
    means: dict[str, float],
    stds: dict[str, float],
    weights: np.ndarray,
    threshold: float,
) -> str:
    def array(values: list[float]) -> str:
        return ",\n            ".join(f"{value:.12f}" for value in values)

    escaped_feature_names = ",\n            ".join(f'"{name}"' for name in feature_names)
    mean_values = [means[name] for name in feature_names]
    std_values = [stds[name] for name in feature_names]
    weight_values = [float(value) for value in weights]
    return f"""import Foundation

enum DriveMatchDisagreementGateModel {{
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
            {array(weight_values)}
    ]

    static let threshold: Double = {threshold:.12f}
}}
"""


def main() -> None:
    args = parse_args()
    examples = load_examples(args.candidate_csv)
    train_examples, val_examples, test_examples = split_examples(examples)
    best_validation, model = train(train_examples, val_examples)
    test_metrics = evaluate_examples(
        test_examples,
        gate_predictions(
            test_examples,
            model["weights"],
            model["threshold"],
            model["feature_names"],
            model["means"],
            model["stds"],
        ),
    )
    payload = {
        "feature_names": model["feature_names"],
        "means": [model["means"][name] for name in model["feature_names"]],
        "standard_deviations": [model["stds"][name] for name in model["feature_names"]],
        "weights": [float(value) for value in model["weights"]],
        "threshold": model["threshold"],
        "split": {
            "train_examples": len(train_examples),
            "val_examples": len(val_examples),
            "test_examples": len(test_examples),
        },
        "train_stats": model["train_stats"],
        "val_stats": model["val_stats"],
        "best_validation": best_validation,
        "test_metrics": test_metrics,
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    if args.swift_out:
        args.swift_out.write_text(
            render_swift(
                model["feature_names"],
                model["means"],
                model["stds"],
                model["weights"],
                model["threshold"],
            )
        )
    print(json.dumps({"best_validation": best_validation, "test_metrics": test_metrics}, indent=2))


if __name__ == "__main__":
    main()
