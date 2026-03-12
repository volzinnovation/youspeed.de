#!/usr/bin/env python3
"""Retrain hindsight matching models from one or more drive-match logs.

The runner keeps session boundaries intact, drops strict subset logs, regenerates
the canonical hindsight artifacts under tmp/, and recomputes the benchmark table
used by the paper.
"""

from __future__ import annotations

import argparse
import json
import math
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from analyze_hindsight_match_labels import (
    build_runs,
    derive_pseudo_labels,
    load_rows,
    summarize_horizon,
    summarize_transitions,
)
from export_hindsight_training_dataset import (
    build_candidate_rows,
    build_gate_rows,
    summarize_rows,
    write_csv,
    write_json,
    write_jsonl,
)
from train_disagreement_gate import (
    evaluate_examples as evaluate_disagreement_gate,
    gate_predictions as disagreement_gate_predictions,
    render_swift as render_disagreement_gate_swift,
    train as train_disagreement_gate,
)
from train_disagreement_tree_gate import (
    render_swift as render_disagreement_tree_gate_swift,
    train as train_disagreement_tree_gate,
    tree_gate_predictions as disagreement_tree_gate_predictions,
    tree_to_dict as disagreement_tree_to_dict,
)
from train_three_way_tree_gate import (
    render_swift as render_three_way_gate_swift,
    train as train_three_way_tree_gate,
    gate_predictions as three_way_gate_predictions,
    tree_to_dict as three_way_tree_to_dict,
)
from train_fixed_lag_sequence_smoother import (
    build_sequence_steps,
    smooth_sequences as smooth_fixed_lag_sequences,
    train as train_fixed_lag_sequence_smoother,
)
from train_tree_candidate_ranker import (
    build_rank_examples,
    evaluate_rank_examples,
    hybrid_predictions as tree_reranker_hybrid_predictions,
    reranker_predictions as tree_reranker_predictions,
    train as train_tree_candidate_ranker,
    train_hybrid as train_tree_candidate_hybrid,
    tree_to_dict as tree_candidate_tree_to_dict,
)
from train_online_linear_ranker import (
    Example,
    build_feature_spec,
    render_swift,
    split_examples,
    train as train_online_linear,
    vectorize,
)


@dataclass(frozen=True)
class LogSelection:
    path: Path
    row_keys: frozenset[tuple[Any, ...]]


@dataclass
class PreparedExample:
    example_id: str
    timestamp_utc: str
    rows: list[dict[str, Any]]
    vectors: np.ndarray
    labels: np.ndarray
    changed: bool


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "log_paths",
        nargs="*",
        type=Path,
        help="Input drive-match logs. Defaults to inspector/logs/*.ndjson",
    )
    parser.add_argument("--future-window", type=int, default=5)
    parser.add_argument("--min-future-run-length", type=int, default=5)
    parser.add_argument("--min-agreement-ratio", type=float, default=0.8)
    parser.add_argument("--sweep-horizons", type=str, default="1,2,3,5,10")
    parser.add_argument(
        "--output-prefix",
        type=Path,
        default=Path("tmp/hindsight"),
        help="Base output prefix, e.g. tmp/hindsight",
    )
    parser.add_argument(
        "--swift-model-out",
        type=Path,
        default=Path("tmp/DriveMatchOnlineLinearRankerModel.swift"),
    )
    parser.add_argument(
        "--model-json-out",
        type=Path,
        default=Path("tmp/online_linear_ranker_model.json"),
    )
    parser.add_argument(
        "--gate-model-json-out",
        type=Path,
        default=Path("tmp/disagreement_gate_model.json"),
    )
    parser.add_argument(
        "--gate-swift-model-out",
        type=Path,
        default=Path("tmp/DriveMatchDisagreementGateModel.swift"),
    )
    parser.add_argument(
        "--three-way-gate-model-json-out",
        type=Path,
        default=Path("tmp/three_way_gate_model.json"),
    )
    parser.add_argument(
        "--three-way-gate-swift-model-out",
        type=Path,
        default=Path("tmp/DriveMatchThreeWayGateModel.swift"),
    )
    parser.add_argument(
        "--tree-ranker-model-json-out",
        type=Path,
        default=Path("tmp/tree_candidate_ranker_model.json"),
    )
    parser.add_argument(
        "--sequence-smoother-model-json-out",
        type=Path,
        default=Path("tmp/three_way_sequence_smoother_model.json"),
    )
    return parser.parse_args()


def default_log_paths() -> list[Path]:
    return sorted(Path("inspector/logs").glob("*.ndjson"))


def row_identity(row: Any) -> tuple[Any, ...]:
    return (
        row.timestamp_utc,
        row.fix_id,
        row.lat,
        row.lon,
        row.selected_way_id,
        row.final_way_id,
    )


def select_logs(paths: list[Path]) -> tuple[list[Path], list[dict[str, str]]]:
    selections = [
        LogSelection(path=path, row_keys=frozenset(row_identity(row) for row in load_rows(path)))
        for path in paths
    ]
    dropped: list[dict[str, str]] = []
    kept: list[Path] = []
    for selection in selections:
        duplicate_or_subset_of: Path | None = None
        for other in selections:
            if selection.path == other.path:
                continue
            if not selection.row_keys:
                duplicate_or_subset_of = other.path
                break
            if selection.row_keys == other.row_keys:
                if str(selection.path) > str(other.path):
                    duplicate_or_subset_of = other.path
                    break
            elif selection.row_keys < other.row_keys:
                duplicate_or_subset_of = other.path
                break
        if duplicate_or_subset_of is None:
            kept.append(selection.path)
        else:
            dropped.append(
                {
                    "log_path": str(selection.path),
                    "reason": "subset_or_duplicate",
                    "covered_by": str(duplicate_or_subset_of),
                }
            )
    kept.sort()
    return kept, dropped


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[len(ordered) // 2]


def add_source(rows: list[dict[str, Any]], source_log: Path) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for row in rows:
        enriched = dict(row)
        enriched["source_log"] = source_log.name
        if "example_id" in enriched:
            enriched["example_id"] = f"{source_log.stem}:{enriched['example_id']}"
        out.append(enriched)
    return out


def combine_summaries(
    kept_paths: list[Path],
    dropped_paths: list[dict[str, str]],
    log_rows: dict[Path, list[Any]],
    future_window: int,
    min_future_run_length: int,
    min_agreement_ratio: float,
    horizons: list[int],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    combined_gate_rows: list[dict[str, Any]] = []
    combined_candidate_rows: list[dict[str, Any]] = []
    combined_gate_rows_changed: list[dict[str, Any]] = []
    combined_candidate_rows_changed: list[dict[str, Any]] = []
    combined_pseudo_labels: list[dict[str, Any]] = []
    all_raw_rows = [row for path in kept_paths for row in log_rows[path]]
    horizon_summary = {
        horizon: {
            "total": 0,
            "future_all_same": 0,
            "majority_in_current_candidates": 0,
            "majority_differs_from_current": 0,
            "majority_differs_in_top2": 0,
        }
        for horizon in horizons
    }
    transition_summary: Counter[str] = Counter()
    per_log: list[dict[str, Any]] = []

    for path in kept_paths:
        rows = log_rows[path]
        runs = build_runs(rows)
        log_horizons = {
            horizon: summarize_horizon(rows, horizon, min_agreement_ratio) for horizon in horizons
        }
        log_transitions = summarize_transitions(rows, runs)
        pseudo_labels = derive_pseudo_labels(
            rows,
            future_window=future_window,
            min_future_run_length=min_future_run_length,
            min_agreement_ratio=min_agreement_ratio,
        )
        gate_rows = add_source(build_gate_rows(pseudo_labels, only_changed=False), path)
        candidate_rows = add_source(build_candidate_rows(pseudo_labels, only_changed=False), path)
        gate_rows_changed = add_source(build_gate_rows(pseudo_labels, only_changed=True), path)
        candidate_rows_changed = add_source(build_candidate_rows(pseudo_labels, only_changed=True), path)
        enriched_pseudo = add_source(pseudo_labels, path)

        combined_gate_rows.extend(gate_rows)
        combined_candidate_rows.extend(candidate_rows)
        combined_gate_rows_changed.extend(gate_rows_changed)
        combined_candidate_rows_changed.extend(candidate_rows_changed)
        combined_pseudo_labels.extend(enriched_pseudo)

        for horizon in horizons:
            for key, value in log_horizons[horizon].items():
                horizon_summary[horizon][key] += value
        transition_summary.update(log_transitions)
        per_log.append(
            {
                "log_path": str(path),
                "row_count": len(rows),
                "duration_seconds": (rows[-1].dt - rows[0].dt).total_seconds() if rows else 0.0,
                "pseudo_label_example_count": len(pseudo_labels),
                "pseudo_label_changed_selection_count": sum(
                    1 for example in pseudo_labels if example["pseudo_label_way_id"] != example["selected_way_id"]
                ),
                "horizon_summary": log_horizons,
                "transition_summary": log_transitions,
            }
        )

    margins = [row.top2_margin for row in all_raw_rows if row.top2_margin is not None]
    selected_way_ids = [row.selected_way_id for row in all_raw_rows if row.selected_way_id]
    summary = {
        "log_paths": [str(path) for path in kept_paths],
        "dropped_logs": dropped_paths,
        "row_count": len(all_raw_rows),
        "duration_seconds": sum(item["duration_seconds"] for item in per_log),
        "unique_selected_way_count": len(set(selected_way_ids)),
        "used_mini_hmm_count": sum(1 for row in all_raw_rows if row.used_mini_hmm),
        "run_count": sum(len(build_runs(log_rows[path])) for path in kept_paths),
        "median_run_length": median(
            [float(run["length"]) for path in kept_paths for run in build_runs(log_rows[path])]
        ),
        "max_run_length": max(
            [int(run["length"]) for path in kept_paths for run in build_runs(log_rows[path])],
            default=0,
        ),
        "median_top2_margin": median(margins),
        "horizon_summary": horizon_summary,
        "transition_summary": dict(transition_summary),
        "pseudo_label_example_count": len(combined_pseudo_labels),
        "pseudo_label_changed_selection_count": sum(
            1 for example in combined_pseudo_labels if example["pseudo_label_way_id"] != example["selected_way_id"]
        ),
        "pseudo_label_top2_count": sum(
            1 for example in combined_pseudo_labels if example["pseudo_label_rank"] <= 2
        ),
        "pseudo_label_top1_count": sum(
            1 for example in combined_pseudo_labels if example["pseudo_label_rank"] == 1
        ),
        "pseudo_label_mini_hmm_agreement_count": sum(
            1 for example in combined_pseudo_labels if example["pseudo_label_way_id"] == example["mini_hmm_way_id"]
        ),
        "future_window": future_window,
        "min_future_run_length": min_future_run_length,
        "min_agreement_ratio": min_agreement_ratio,
        "per_log": per_log,
    }
    return (
        summary,
        combined_pseudo_labels,
        combined_gate_rows,
        combined_candidate_rows,
        combined_gate_rows_changed,
        combined_candidate_rows_changed,
    )


def build_examples(candidate_rows: list[dict[str, Any]]) -> list[Example]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in candidate_rows:
        grouped.setdefault(row["example_id"], []).append(row)
    examples = [
        Example(example_id=example_id, timestamp_utc=rows[0]["timestamp_utc"], rows=rows)
        for example_id, rows in grouped.items()
    ]
    examples.sort(key=lambda example: (example.timestamp_utc, example.example_id))
    return examples


def prepare_examples(
    examples: list[Example],
    feature_names: list[str],
    means: dict[str, float],
    stds: dict[str, float],
) -> list[PreparedExample]:
    prepared: list[PreparedExample] = []
    for example in examples:
        vectors = np.array(
            [vectorize(row, feature_names, means, stds) for row in example.rows],
            dtype=np.float64,
        )
        labels = np.array([int(row["label_is_pseudo_label"]) for row in example.rows], dtype=np.int64)
        prepared.append(
            PreparedExample(
                example_id=example.example_id,
                timestamp_utc=example.timestamp_utc,
                rows=example.rows,
                vectors=vectors,
                labels=labels,
                changed=bool(int(example.rows[0]["label_switch_to_pseudo"])),
            )
        )
    return prepared


def metrics_from_prediction_indices(examples: list[PreparedExample], predicted_indices: list[int]) -> dict[str, Any]:
    total = len(examples)
    correct = 0
    changed_total = 0
    changed_correct = 0
    unchanged_total = 0
    unchanged_correct = 0
    for example, predicted_index in zip(examples, predicted_indices):
        true_index = int(np.argmax(example.labels))
        is_correct = predicted_index == true_index
        correct += int(is_correct)
        if example.changed:
            changed_total += 1
            changed_correct += int(is_correct)
        else:
            unchanged_total += 1
            unchanged_correct += int(is_correct)
    return {
        "examples": total,
        "correct": correct,
        "accuracy": correct / total if total else 0.0,
        "changed_examples": changed_total,
        "changed_recall": changed_correct / changed_total if changed_total else 0.0,
        "unchanged_examples": unchanged_total,
        "unchanged_accuracy": unchanged_correct / unchanged_total if unchanged_total else 0.0,
    }


def pick_row_index(rows: list[dict[str, Any]], predicate: str) -> int | None:
    for index, row in enumerate(rows):
        if int(row[predicate]) == 1:
            return index
    return None


def baseline_predictions(examples: list[PreparedExample], model_name: str) -> list[int]:
    indices: list[int] = []
    for example in examples:
        rows = example.rows
        if model_name in {"current_final", "heuristic"}:
            index = pick_row_index(rows, "label_is_current_selected")
        elif model_name == "mini_if_available_else_heuristic":
            index = pick_row_index(rows, "mini_hmm_matches_candidate")
            if index is None:
                index = pick_row_index(rows, "heuristic_matches_candidate")
            if index is None:
                index = pick_row_index(rows, "label_is_current_selected")
        elif model_name == "trace_rank1":
            index = min(
                range(len(rows)),
                key=lambda item: (
                    int(rows[item]["candidate_rank"]) if rows[item]["candidate_rank"] not in ("", None) else 10_000,
                    float(rows[item]["candidate_score"]) if rows[item]["candidate_score"] not in ("", None) else 1e9,
                ),
            )
        elif model_name == "lowest_score":
            index = min(
                range(len(rows)),
                key=lambda item: (
                    float(rows[item]["candidate_score"]) if rows[item]["candidate_score"] not in ("", None) else 1e9,
                    int(rows[item]["candidate_rank"]) if rows[item]["candidate_rank"] not in ("", None) else 10_000,
                ),
            )
        elif model_name == "lowest_distance":
            index = min(
                range(len(rows)),
                key=lambda item: (
                    float(rows[item]["candidate_distance_m"]) if rows[item]["candidate_distance_m"] not in ("", None) else 1e9,
                    int(rows[item]["candidate_rank"]) if rows[item]["candidate_rank"] not in ("", None) else 10_000,
                ),
            )
        elif model_name == "lowest_endpoint":
            index = min(
                range(len(rows)),
                key=lambda item: (
                    float(rows[item]["candidate_endpoint_proximity_m"])
                    if rows[item]["candidate_endpoint_proximity_m"] not in ("", None)
                    else 1e9,
                    float(rows[item]["candidate_distance_m"])
                    if rows[item]["candidate_distance_m"] not in ("", None)
                    else 1e9,
                    int(rows[item]["candidate_rank"]) if rows[item]["candidate_rank"] not in ("", None) else 10_000,
                ),
            )
        else:
            raise ValueError(f"Unknown baseline model: {model_name}")
        if index is None:
            index = 0
        indices.append(index)
    return indices


def evaluate_weight_vector(examples: list[PreparedExample], weights: np.ndarray) -> dict[str, Any]:
    predictions: list[int] = []
    for example in examples:
        if not is_finite_array(example.vectors, weights):
            predictions.append(0)
            continue
        with np.errstate(all="ignore"):
            scores = example.vectors @ weights
        if not is_finite_array(scores):
            predictions.append(0)
            continue
        predictions.append(int(np.argmax(scores)))
    return metrics_from_prediction_indices(examples, predictions)


def sigmoid(values: np.ndarray) -> np.ndarray:
    clipped = np.clip(values, -40.0, 40.0)
    return 1.0 / (1.0 + np.exp(-clipped))


def is_finite_array(*arrays: np.ndarray | float) -> bool:
    return all(np.all(np.isfinite(array)) for array in arrays)


def flatten_examples(examples: list[PreparedExample]) -> tuple[np.ndarray, np.ndarray]:
    features = np.vstack([example.vectors for example in examples])
    labels = np.concatenate([example.labels.astype(np.float64) for example in examples])
    return features, labels


def train_logistic_ranker(
    train_examples: list[PreparedExample],
    val_examples: list[PreparedExample],
) -> tuple[dict[str, Any], np.ndarray]:
    x_train, y_train = flatten_examples(train_examples)
    pos_count = float(np.sum(y_train == 1.0))
    neg_count = float(len(y_train) - pos_count)
    pos_weight = neg_count / max(pos_count, 1.0)
    sample_weights = np.where(y_train == 1.0, pos_weight, 1.0)

    best_metrics: dict[str, Any] | None = None
    best_weights: np.ndarray | None = None
    best_epoch = 0
    dimensions = x_train.shape[1]
    for learning_rate in [0.002, 0.005, 0.01, 0.02]:
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
                if not is_finite_array(weights, gradient):
                    break
                if epoch not in {1, 5, 10, 20, 50, 100, 200, 300, 400, 500}:
                    continue
                metrics = evaluate_weight_vector(val_examples, weights)
                ranking = (
                    metrics["accuracy"],
                    metrics["changed_recall"],
                    metrics["unchanged_accuracy"],
                )
                if best_metrics is None or ranking > (
                    best_metrics["accuracy"],
                    best_metrics["changed_recall"],
                    best_metrics["unchanged_accuracy"],
                ):
                    best_metrics = {
                        **metrics,
                        "epoch": epoch,
                        "learning_rate": learning_rate,
                        "l2": l2,
                    }
                    best_weights = weights.copy()
                    best_epoch = epoch
    assert best_metrics is not None
    assert best_weights is not None
    best_metrics["epoch"] = best_epoch
    return best_metrics, best_weights


def evaluate_mlp(examples: list[PreparedExample], w1: np.ndarray, b1: np.ndarray, w2: np.ndarray, b2: float) -> dict[str, Any]:
    predictions: list[int] = []
    for example in examples:
        if not is_finite_array(example.vectors, w1, b1, w2, b2):
            predictions.append(0)
            continue
        with np.errstate(all="ignore"):
            hidden = np.maximum(example.vectors @ w1 + b1, 0.0)
            scores = hidden @ w2 + b2
        if not is_finite_array(hidden, scores):
            predictions.append(0)
            continue
        predictions.append(int(np.argmax(scores)))
    return metrics_from_prediction_indices(examples, predictions)


def train_tiny_mlp_ranker(
    train_examples: list[PreparedExample],
    val_examples: list[PreparedExample],
) -> tuple[dict[str, Any], tuple[np.ndarray, np.ndarray, np.ndarray, float]]:
    x_train, y_train = flatten_examples(train_examples)
    pos_count = float(np.sum(y_train == 1.0))
    neg_count = float(len(y_train) - pos_count)
    pos_weight = neg_count / max(pos_count, 1.0)
    sample_weights = np.where(y_train == 1.0, pos_weight, 1.0)[:, None]
    best_metrics: dict[str, Any] | None = None
    best_params: tuple[np.ndarray, np.ndarray, np.ndarray, float] | None = None
    dimensions = x_train.shape[1]
    for hidden_size in [8, 16]:
        for learning_rate in [0.001, 0.0025, 0.005]:
            for l2 in [1e-4, 5e-4]:
                rng = np.random.default_rng(hidden_size * 1000 + int(learning_rate * 10000) + int(l2 * 1e6))
                w1 = rng.normal(0.0, 0.05, size=(dimensions, hidden_size))
                b1 = np.zeros(hidden_size, dtype=np.float64)
                w2 = rng.normal(0.0, 0.05, size=hidden_size)
                b2 = 0.0
                for epoch in range(1, 61):
                    if not is_finite_array(x_train, y_train, sample_weights, w1, b1, w2, b2):
                        break
                    with np.errstate(all="ignore"):
                        hidden_linear = x_train @ w1 + b1
                        hidden = np.maximum(hidden_linear, 0.0)
                        logits = hidden @ w2 + b2
                        probs = sigmoid(logits)[:, None]
                        y_column = y_train[:, None]
                        delta = (probs - y_column) * sample_weights / len(y_train)
                        grad_w2 = hidden.T @ delta[:, 0] + (l2 * w2)
                        grad_b2 = float(np.sum(delta))
                        hidden_grad = (delta * w2) * (hidden_linear > 0.0)
                        grad_w1 = x_train.T @ hidden_grad + (l2 * w1)
                        grad_b1 = np.sum(hidden_grad, axis=0)
                    if not is_finite_array(
                        hidden_linear,
                        hidden,
                        logits,
                        probs,
                        delta,
                        grad_w2,
                        grad_b2,
                        hidden_grad,
                        grad_w1,
                        grad_b1,
                    ):
                        break
                    grad_w2 = np.clip(grad_w2, -5.0, 5.0)
                    grad_b2 = float(np.clip(grad_b2, -5.0, 5.0))
                    grad_w1 = np.clip(grad_w1, -5.0, 5.0)
                    grad_b1 = np.clip(grad_b1, -5.0, 5.0)
                    w2 -= learning_rate * grad_w2
                    b2 -= learning_rate * grad_b2
                    w1 -= learning_rate * grad_w1
                    b1 -= learning_rate * grad_b1
                    w2 = np.clip(w2, -25.0, 25.0)
                    b2 = float(np.clip(b2, -25.0, 25.0))
                    w1 = np.clip(w1, -25.0, 25.0)
                    b1 = np.clip(b1, -25.0, 25.0)
                    if not is_finite_array(w1, b1, w2, b2):
                        break
                    if epoch not in {5, 10, 15, 20, 30, 45, 60}:
                        continue
                    metrics = evaluate_mlp(val_examples, w1, b1, w2, b2)
                    ranking = (
                        metrics["accuracy"],
                        metrics["changed_recall"],
                        metrics["unchanged_accuracy"],
                    )
                    if best_metrics is None or ranking > (
                        best_metrics["accuracy"],
                        best_metrics["changed_recall"],
                        best_metrics["unchanged_accuracy"],
                    ):
                        best_metrics = {
                            **metrics,
                            "epoch": epoch,
                            "hidden_size": hidden_size,
                            "learning_rate": learning_rate,
                            "l2": l2,
                        }
                        best_params = (w1.copy(), b1.copy(), w2.copy(), float(b2))
    assert best_metrics is not None
    assert best_params is not None
    return best_metrics, best_params


def benchmark_models(
    candidate_rows: list[dict[str, Any]],
    model_json_out: Path,
    swift_model_out: Path,
    gate_model_json_out: Path,
    gate_swift_model_out: Path,
    three_way_gate_model_json_out: Path,
    three_way_gate_swift_model_out: Path,
    tree_ranker_model_json_out: Path,
    sequence_smoother_model_json_out: Path,
) -> dict[str, Any]:
    examples = build_examples(candidate_rows)
    train_examples, val_examples, test_examples = split_examples(examples)
    feature_names, means, stds = build_feature_spec(train_examples)
    prepared_train = prepare_examples(train_examples, feature_names, means, stds)
    prepared_val = prepare_examples(val_examples, feature_names, means, stds)
    prepared_test = prepare_examples(test_examples, feature_names, means, stds)

    results: list[dict[str, Any]] = []
    for baseline_name in [
        "current_final",
        "heuristic",
        "mini_if_available_else_heuristic",
        "trace_rank1",
        "lowest_score",
        "lowest_distance",
        "lowest_endpoint",
    ]:
        results.append(
            {
                "model": baseline_name,
                "val": metrics_from_prediction_indices(
                    prepared_val,
                    baseline_predictions(prepared_val, baseline_name),
                ),
                "test": metrics_from_prediction_indices(
                    prepared_test,
                    baseline_predictions(prepared_test, baseline_name),
                ),
            }
        )

    disagreement_val_summary, disagreement_model = train_disagreement_gate(train_examples, val_examples)
    disagreement_val = evaluate_disagreement_gate(
        val_examples,
        disagreement_gate_predictions(
            val_examples,
            disagreement_model["weights"],
            disagreement_model["threshold"],
            disagreement_model["feature_names"],
            disagreement_model["means"],
            disagreement_model["stds"],
        ),
    )
    disagreement_test = evaluate_disagreement_gate(
        test_examples,
        disagreement_gate_predictions(
            test_examples,
            disagreement_model["weights"],
            disagreement_model["threshold"],
            disagreement_model["feature_names"],
            disagreement_model["means"],
            disagreement_model["stds"],
        ),
    )
    results.append(
        {
            "model": "disagreement_logistic_gate",
            "val": disagreement_val,
            "test": disagreement_test,
            "epoch": disagreement_val_summary["epoch"],
            "threshold": disagreement_model["threshold"],
        }
    )

    disagreement_tree_val_summary, disagreement_tree_model = train_disagreement_tree_gate(train_examples, val_examples)
    disagreement_tree_val = evaluate_disagreement_gate(
        val_examples,
        disagreement_tree_gate_predictions(
            val_examples,
            disagreement_tree_model["tree"],
            disagreement_tree_model["threshold"],
        ),
    )
    disagreement_tree_test = evaluate_disagreement_gate(
        test_examples,
        disagreement_tree_gate_predictions(
            test_examples,
            disagreement_tree_model["tree"],
            disagreement_tree_model["threshold"],
        ),
    )
    results.append(
        {
            "model": "disagreement_tree_gate",
            "val": disagreement_tree_val,
            "test": disagreement_tree_test,
            "max_depth": disagreement_tree_val_summary["max_depth"],
            "min_leaf_size": disagreement_tree_val_summary["min_leaf_size"],
            "threshold": disagreement_tree_model["threshold"],
        }
    )

    three_way_val_summary, three_way_model = train_three_way_tree_gate(train_examples, val_examples)
    three_way_val = evaluate_disagreement_gate(
        val_examples,
        three_way_gate_predictions(
            val_examples,
            three_way_model["tree"],
        ),
    )
    three_way_test = evaluate_disagreement_gate(
        test_examples,
        three_way_gate_predictions(
            test_examples,
            three_way_model["tree"],
        ),
    )
    results.append(
        {
            "model": "three_way_tree_gate",
            "val": three_way_val,
            "test": three_way_test,
            "max_depth": three_way_val_summary["max_depth"],
            "min_leaf_size": three_way_val_summary["min_leaf_size"],
        }
    )

    sequence_smoother_val_summary, sequence_smoother_model = train_fixed_lag_sequence_smoother(
        train_examples,
        val_examples,
        three_way_model["tree"],
    )
    sequence_val_steps = build_sequence_steps(val_examples, three_way_model["tree"])
    sequence_test_steps = build_sequence_steps(test_examples, three_way_model["tree"])
    sequence_val_predictions, sequence_val_stats = smooth_fixed_lag_sequences(
        sequence_val_steps,
        sequence_smoother_model["params"],
    )
    sequence_test_predictions, sequence_test_stats = smooth_fixed_lag_sequences(
        sequence_test_steps,
        sequence_smoother_model["params"],
    )
    sequence_val = {**evaluate_disagreement_gate(val_examples, sequence_val_predictions), **sequence_val_stats}
    sequence_test = {**evaluate_disagreement_gate(test_examples, sequence_test_predictions), **sequence_test_stats}
    results.append(
        {
            "model": "three_way_fixed_lag_smoother",
            "val": sequence_val,
            "test": sequence_test,
            **sequence_smoother_model["params"].__dict__,
        }
    )

    tree_reranker_val_summary, tree_reranker_model = train_tree_candidate_ranker(train_examples, val_examples)
    tree_ranker_val_examples = build_rank_examples(val_examples)
    tree_ranker_test_examples = build_rank_examples(test_examples)
    tree_reranker_val = evaluate_rank_examples(
        tree_ranker_val_examples,
        tree_reranker_predictions(
            tree_ranker_val_examples,
            tree_reranker_model["tree"],
            tree_reranker_model["max_rank"],
        ),
    )
    tree_reranker_test = evaluate_rank_examples(
        tree_ranker_test_examples,
        tree_reranker_predictions(
            tree_ranker_test_examples,
            tree_reranker_model["tree"],
            tree_reranker_model["max_rank"],
        ),
    )
    results.append(
        {
            "model": "tree_candidate_ranker",
            "val": tree_reranker_val,
            "test": tree_reranker_test,
            "max_depth": tree_reranker_val_summary["max_depth"],
            "min_leaf_size": tree_reranker_val_summary["min_leaf_size"],
            "max_rank": tree_reranker_val_summary["max_rank"],
        }
    )

    tree_hybrid_val_summary, tree_hybrid_model = train_tree_candidate_hybrid(
        train_examples,
        val_examples,
        three_way_model["tree"],
        tree_reranker_model["tree"],
    )
    tree_hybrid_val_predictions, tree_hybrid_val_stats = tree_reranker_hybrid_predictions(
        val_examples,
        tree_ranker_val_examples,
        three_way_model["tree"],
        tree_reranker_model["tree"],
        prob_threshold=tree_hybrid_model["prob_threshold"],
        margin_threshold=tree_hybrid_model["margin_threshold"],
        max_rank=tree_hybrid_model["max_rank"],
        nonexpert_only=tree_hybrid_model["nonexpert_only"],
        require_low_gate_confidence=False,
    )
    tree_hybrid_test_predictions, tree_hybrid_test_stats = tree_reranker_hybrid_predictions(
        test_examples,
        tree_ranker_test_examples,
        three_way_model["tree"],
        tree_reranker_model["tree"],
        prob_threshold=tree_hybrid_model["prob_threshold"],
        margin_threshold=tree_hybrid_model["margin_threshold"],
        max_rank=tree_hybrid_model["max_rank"],
        nonexpert_only=tree_hybrid_model["nonexpert_only"],
        require_low_gate_confidence=False,
    )
    results.append(
        {
            "model": "three_way_plus_tree_reranker",
            "val": {**evaluate_rank_examples(tree_ranker_val_examples, tree_hybrid_val_predictions), **tree_hybrid_val_stats},
            "test": {**evaluate_rank_examples(tree_ranker_test_examples, tree_hybrid_test_predictions), **tree_hybrid_test_stats},
            "prob_threshold": tree_hybrid_val_summary["prob_threshold"],
            "margin_threshold": tree_hybrid_val_summary["margin_threshold"],
            "max_rank": tree_hybrid_val_summary["max_rank"],
            "nonexpert_only": tree_hybrid_val_summary["nonexpert_only"],
        }
    )

    logistic_val, logistic_weights = train_logistic_ranker(prepared_train, prepared_val)
    results.append(
        {
            "model": "logistic_ranker",
            "val": {k: v for k, v in logistic_val.items() if k not in {"epoch", "learning_rate", "l2"}},
            "test": evaluate_weight_vector(prepared_test, logistic_weights),
            "epoch": logistic_val["epoch"],
        }
    )

    online_val_summary, online_weights_list = train_online_linear(
        train_examples,
        val_examples,
        feature_names,
        means,
        stds,
    )
    online_weights = np.array(online_weights_list, dtype=np.float64)
    online_val = evaluate_weight_vector(prepared_val, online_weights)
    online_test = evaluate_weight_vector(prepared_test, online_weights)
    results.append(
        {
            "model": "online_linear_ranker",
            "val": online_val,
            "test": online_test,
        }
    )

    tiny_mlp_val, tiny_mlp_params = train_tiny_mlp_ranker(prepared_train, prepared_val)
    tiny_mlp_test = evaluate_mlp(prepared_test, *tiny_mlp_params)
    results.append(
        {
            "model": "tiny_mlp_ranker",
            "val": {k: v for k, v in tiny_mlp_val.items() if k not in {"epoch", "hidden_size", "learning_rate", "l2"}},
            "test": tiny_mlp_test,
            "epoch": tiny_mlp_val["epoch"],
        }
    )

    model_payload = {
        "feature_names": feature_names,
        "means": [means[name] for name in feature_names],
        "standard_deviations": [stds[name] for name in feature_names],
        "weights": online_weights_list,
        "split": {
            "train_examples": len(train_examples),
            "val_examples": len(val_examples),
            "test_examples": len(test_examples),
        },
        "best_validation": {**online_val_summary, **online_val},
        "test_metrics": online_test,
    }
    model_json_out.parent.mkdir(parents=True, exist_ok=True)
    model_json_out.write_text(json.dumps(model_payload, indent=2, sort_keys=True) + "\n")
    swift_model_out.parent.mkdir(parents=True, exist_ok=True)
    swift_model_out.write_text(render_swift(feature_names, means, stds, online_weights_list))

    best_gate_key = max(
        ["disagreement_logistic_gate", "disagreement_tree_gate"],
        key=lambda model_name: next(
            (
                (
                    entry["val"]["accuracy"],
                    entry["val"].get("disagreement_accuracy", 0.0),
                    entry["val"]["unchanged_accuracy"],
                    entry["val"]["changed_recall"],
                )
                for entry in results
                if entry["model"] == model_name
            ),
            (0.0, 0.0, 0.0, 0.0),
        ),
    )
    if best_gate_key == "disagreement_tree_gate":
        disagreement_payload = {
            "model_type": "tree",
            "feature_names": disagreement_tree_model["feature_names"],
            "threshold": disagreement_tree_model["threshold"],
            "split": {
                "train_examples": len(train_examples),
                "val_examples": len(val_examples),
                "test_examples": len(test_examples),
            },
            "train_stats": disagreement_tree_model["train_stats"],
            "val_stats": disagreement_tree_model["val_stats"],
            "best_validation": disagreement_tree_val_summary,
            "test_metrics": disagreement_tree_test,
            "tree": disagreement_tree_to_dict(disagreement_tree_model["tree"]),
        }
        gate_swift = render_disagreement_tree_gate_swift(
            disagreement_tree_model["tree"],
            disagreement_tree_model["threshold"],
        )
    else:
        disagreement_payload = {
            "model_type": "logistic",
            "feature_names": disagreement_model["feature_names"],
            "means": [disagreement_model["means"][name] for name in disagreement_model["feature_names"]],
            "standard_deviations": [disagreement_model["stds"][name] for name in disagreement_model["feature_names"]],
            "weights": [float(value) for value in disagreement_model["weights"]],
            "threshold": disagreement_model["threshold"],
            "split": {
                "train_examples": len(train_examples),
                "val_examples": len(val_examples),
                "test_examples": len(test_examples),
            },
            "train_stats": disagreement_model["train_stats"],
            "val_stats": disagreement_model["val_stats"],
            "best_validation": disagreement_val_summary,
            "test_metrics": disagreement_test,
        }
        gate_swift = render_disagreement_gate_swift(
            disagreement_model["feature_names"],
            disagreement_model["means"],
            disagreement_model["stds"],
            disagreement_model["weights"],
            disagreement_model["threshold"],
        )
    gate_model_json_out.parent.mkdir(parents=True, exist_ok=True)
    gate_model_json_out.write_text(json.dumps(disagreement_payload, indent=2, sort_keys=True) + "\n")
    gate_swift_model_out.parent.mkdir(parents=True, exist_ok=True)
    gate_swift_model_out.write_text(gate_swift)

    three_way_payload = {
        "model_type": "tree_multiclass",
        "class_names": three_way_model["class_names"],
        "feature_names": three_way_model["feature_names"],
        "split": {
            "train_examples": len(train_examples),
            "val_examples": len(val_examples),
            "test_examples": len(test_examples),
        },
        "train_stats": three_way_model["train_stats"],
        "val_stats": three_way_model["val_stats"],
        "best_validation": three_way_val_summary,
        "test_metrics": three_way_test,
        "tree": three_way_tree_to_dict(three_way_model["tree"]),
    }
    three_way_gate_model_json_out.parent.mkdir(parents=True, exist_ok=True)
    three_way_gate_model_json_out.write_text(json.dumps(three_way_payload, indent=2, sort_keys=True) + "\n")
    three_way_gate_swift_model_out.parent.mkdir(parents=True, exist_ok=True)
    three_way_gate_swift_model_out.write_text(render_three_way_gate_swift(three_way_model["tree"]))

    tree_ranker_payload = {
        "model_type": "tree_candidate_ranker",
        "feature_names": tree_reranker_model["feature_names"],
        "split": {
            "train_examples": len(train_examples),
            "val_examples": len(val_examples),
            "test_examples": len(test_examples),
        },
        "reranker": {
            "best_validation": tree_reranker_val_summary,
            "test_metrics": tree_reranker_test,
            "max_rank": tree_reranker_model["max_rank"],
            "tree": tree_candidate_tree_to_dict(tree_reranker_model["tree"]),
        },
        "hybrid": {
            "best_validation": tree_hybrid_val_summary,
            "test_metrics": {**evaluate_rank_examples(tree_ranker_test_examples, tree_hybrid_test_predictions), **tree_hybrid_test_stats},
            **tree_hybrid_model,
        },
    }
    tree_ranker_model_json_out.parent.mkdir(parents=True, exist_ok=True)
    tree_ranker_model_json_out.write_text(json.dumps(tree_ranker_payload, indent=2, sort_keys=True) + "\n")

    sequence_payload = {
        "model_type": "three_way_fixed_lag_smoother",
        "split": {
            "train_examples": len(train_examples),
            "val_examples": len(val_examples),
            "test_examples": len(test_examples),
        },
        "base_model": "three_way_tree_gate",
        "best_validation": sequence_smoother_val_summary,
        "test_metrics": sequence_test,
        "params": sequence_smoother_model["params"].__dict__,
    }
    sequence_smoother_model_json_out.parent.mkdir(parents=True, exist_ok=True)
    sequence_smoother_model_json_out.write_text(json.dumps(sequence_payload, indent=2, sort_keys=True) + "\n")

    prefix_logistic_test: list[dict[str, Any]] = []
    train_count = len(train_examples)
    for fraction in [0.1, 0.2, 0.4, 0.6]:
        subset_count = max(1, int(train_count * fraction))
        subset_train = train_examples[:subset_count]
        subset_feature_names, subset_means, subset_stds = build_feature_spec(subset_train)
        subset_prepared_train = prepare_examples(subset_train, subset_feature_names, subset_means, subset_stds)
        subset_prepared_val = prepare_examples(val_examples, subset_feature_names, subset_means, subset_stds)
        subset_prepared_test = prepare_examples(test_examples, subset_feature_names, subset_means, subset_stds)
        subset_val, subset_weights = train_logistic_ranker(subset_prepared_train, subset_prepared_val)
        subset_test = evaluate_weight_vector(subset_prepared_test, subset_weights)
        prefix_logistic_test.append(
            {
                "train_fraction": fraction,
                "epoch": subset_val["epoch"],
                **subset_test,
            }
        )

    return {
        "split": model_payload["split"],
        "best_disagreement_gate_model": best_gate_key,
        "results": results,
        "prefix_logistic_test": prefix_logistic_test,
    }


def main() -> int:
    args = parse_args()
    log_paths = args.log_paths or default_log_paths()
    if not log_paths:
        raise SystemExit("No input logs found.")

    kept_paths, dropped_logs = select_logs(log_paths)
    if not kept_paths:
        raise SystemExit("All input logs were dropped as duplicates/subsets.")

    horizons = [int(value) for value in args.sweep_horizons.split(",") if value.strip()]
    log_rows = {path: load_rows(path) for path in kept_paths}
    (
        match_summary,
        pseudo_labels,
        gate_rows,
        candidate_rows,
        gate_rows_changed,
        candidate_rows_changed,
    ) = combine_summaries(
        kept_paths=kept_paths,
        dropped_paths=dropped_logs,
        log_rows=log_rows,
        future_window=args.future_window,
        min_future_run_length=args.min_future_run_length,
        min_agreement_ratio=args.min_agreement_ratio,
        horizons=horizons,
    )

    training_summary = summarize_rows(gate_rows, candidate_rows)
    training_summary.update(
        {
            "log_paths": match_summary["log_paths"],
            "dropped_logs": dropped_logs,
            "future_window": args.future_window,
            "min_future_run_length": args.min_future_run_length,
            "min_agreement_ratio": args.min_agreement_ratio,
            "only_changed": False,
        }
    )
    training_summary_changed = summarize_rows(gate_rows_changed, candidate_rows_changed)
    training_summary_changed.update(
        {
            "log_paths": match_summary["log_paths"],
            "dropped_logs": dropped_logs,
            "future_window": args.future_window,
            "min_future_run_length": args.min_future_run_length,
            "min_agreement_ratio": args.min_agreement_ratio,
            "only_changed": True,
        }
    )

    benchmark = benchmark_models(
        candidate_rows,
        args.model_json_out,
        args.swift_model_out,
        args.gate_model_json_out,
        args.gate_swift_model_out,
        args.three_way_gate_model_json_out,
        args.three_way_gate_swift_model_out,
        args.tree_ranker_model_json_out,
        args.sequence_smoother_model_json_out,
    )

    output_dir = args.output_prefix.parent
    prefix = args.output_prefix.name
    write_json(output_dir / f"{prefix}_match_summary.json", match_summary)
    write_jsonl(output_dir / f"{prefix}_match_pseudolabels.jsonl", pseudo_labels)
    write_csv(output_dir / f"{prefix}_gate_dataset.csv", gate_rows)
    write_jsonl(output_dir / f"{prefix}_gate_dataset.jsonl", gate_rows)
    write_csv(output_dir / f"{prefix}_candidate_dataset.csv", candidate_rows)
    write_jsonl(output_dir / f"{prefix}_candidate_dataset.jsonl", candidate_rows)
    write_json(output_dir / f"{prefix}_training_summary.json", training_summary)
    write_csv(output_dir / f"{prefix}_gate_dataset_changed.csv", gate_rows_changed)
    write_jsonl(output_dir / f"{prefix}_gate_dataset_changed.jsonl", gate_rows_changed)
    write_csv(output_dir / f"{prefix}_candidate_dataset_changed.csv", candidate_rows_changed)
    write_jsonl(output_dir / f"{prefix}_candidate_dataset_changed.jsonl", candidate_rows_changed)
    write_json(output_dir / f"{prefix}_training_summary_changed.json", training_summary_changed)
    write_json(output_dir / f"{prefix}_model_benchmark.json", benchmark)

    print("selected_logs:")
    for path in kept_paths:
        print(f"  {path}")
    if dropped_logs:
        print("dropped_logs:")
        for item in dropped_logs:
            print(f"  {item['log_path']} -> {item['covered_by']} ({item['reason']})")
    print(
        "pseudo_labels:"
        f" count={match_summary['pseudo_label_example_count']}"
        f" changed={match_summary['pseudo_label_changed_selection_count']}"
        f" top1={match_summary['pseudo_label_top1_count']}"
        f" top2={match_summary['pseudo_label_top2_count']}"
    )
    print(
        "dataset:"
        f" gate_rows={training_summary['gate_row_count']}"
        f" candidate_rows={training_summary['candidate_row_count']}"
        f" switch_positive={training_summary['gate_switch_positive_count']}"
    )
    print("benchmark_test:")
    for item in benchmark["results"]:
        test = item["test"]
        print(
            "  "
            f"{item['model']}:"
            f" acc={test['accuracy']:.4f}"
            f" changed_recall={test['changed_recall']:.4f}"
            f" unchanged_acc={test['unchanged_accuracy']:.4f}"
        )
    print(f"best_disagreement_gate: {benchmark['best_disagreement_gate_model']}")
    print(f"wrote: {output_dir / f'{prefix}_model_benchmark.json'}")
    print(f"wrote: {args.model_json_out}")
    print(f"wrote: {args.swift_model_out}")
    print(f"wrote: {args.gate_model_json_out}")
    print(f"wrote: {args.gate_swift_model_out}")
    print(f"wrote: {args.three_way_gate_model_json_out}")
    print(f"wrote: {args.three_way_gate_swift_model_out}")
    print(f"wrote: {args.tree_ranker_model_json_out}")
    print(f"wrote: {args.sequence_smoother_model_json_out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
