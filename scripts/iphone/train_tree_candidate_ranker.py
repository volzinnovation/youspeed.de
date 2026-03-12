#!/usr/bin/env python3
"""Train a shallow tree candidate reranker and a selective hybrid with the three-way gate."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from train_disagreement_gate import (
    evaluate_examples,
    highway_bucket,
    pick_current_index,
    pick_lowest_distance_index,
    pick_pseudo_index,
    row_float,
    row_int,
)
from train_online_linear_ranker import CONTINUITY_CLASSES, Example, load_examples, split_examples
from train_three_way_tree_gate import (
    MultiClassTreeNode,
    build_cases as build_three_way_cases,
    feature_map as three_way_feature_map,
    gate_predictions as three_way_gate_predictions,
    train as train_three_way_tree_gate,
)


@dataclass(frozen=True)
class TreeNode:
    probability: float
    feature_name: str | None = None
    threshold: float | None = None
    left: TreeNode | None = None
    right: TreeNode | None = None


@dataclass(frozen=True)
class RankExample:
    example_id: str
    timestamp_utc: str
    rows: list[dict[str, str]]
    current_index: int
    distance_index: int
    endpoint_index: int
    feature_rows: list[dict[str, float]]
    labels: list[int]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate_csv", type=Path)
    parser.add_argument("--json-out", type=Path, required=True)
    return parser.parse_args()


def pick_lowest_endpoint_index(rows: list[dict[str, str]]) -> int:
    return min(
        range(len(rows)),
        key=lambda item: (
            row_float(rows[item], "candidate_endpoint_proximity_m"),
            row_float(rows[item], "candidate_distance_m"),
            row_int(rows[item], "candidate_rank") or 10_000,
        ),
    )


def pair_features(candidate: dict[str, str], expert: dict[str, str], prefix: str) -> dict[str, float]:
    candidate_distance_m = row_float(candidate, "candidate_distance_m")
    expert_distance_m = row_float(expert, "candidate_distance_m")
    candidate_score = row_float(candidate, "candidate_score")
    expert_score = row_float(expert, "candidate_score")
    candidate_endpoint_m = row_float(candidate, "candidate_endpoint_proximity_m")
    expert_endpoint_m = row_float(expert, "candidate_endpoint_proximity_m")
    candidate_rank = row_float(candidate, "candidate_rank")
    expert_rank = row_float(expert, "candidate_rank")
    candidate_band = row_float(candidate, "candidate_continuity_band")
    expert_band = row_float(expert, "candidate_continuity_band")
    return {
        f"{prefix}_distance_advantage_m": expert_distance_m - candidate_distance_m,
        f"{prefix}_score_advantage": expert_score - candidate_score,
        f"{prefix}_endpoint_advantage_m": expert_endpoint_m - candidate_endpoint_m,
        f"{prefix}_rank_advantage": expert_rank - candidate_rank,
        f"{prefix}_band_advantage": expert_band - candidate_band,
        f"{prefix}_same_ref": 1.0
        if (candidate.get("candidate_street_ref") or "")
        and candidate.get("candidate_street_ref") == expert.get("candidate_street_ref")
        else 0.0,
        f"{prefix}_same_highway": 1.0 if highway_bucket(candidate) == highway_bucket(expert) else 0.0,
        f"{prefix}_same_continuity": 1.0
        if (candidate.get("candidate_continuity_class") or "none")
        == (expert.get("candidate_continuity_class") or "none")
        else 0.0,
    }


def feature_map(
    rows: list[dict[str, str]],
    candidate_index: int,
    current_index: int,
    distance_index: int,
    endpoint_index: int,
) -> dict[str, float]:
    candidate = rows[candidate_index]
    current = rows[current_index]
    distance = rows[distance_index]
    endpoint = rows[endpoint_index]

    distances = [row_float(row, "candidate_distance_m") for row in rows]
    scores = [row_float(row, "candidate_score") for row in rows]
    endpoints = [row_float(row, "candidate_endpoint_proximity_m") for row in rows]
    ranks = [row_float(row, "candidate_rank") for row in rows]

    candidate_distance_m = row_float(candidate, "candidate_distance_m")
    candidate_score = row_float(candidate, "candidate_score")
    candidate_endpoint_m = row_float(candidate, "candidate_endpoint_proximity_m")
    candidate_rank = row_float(candidate, "candidate_rank")
    speed_kmh = row_float(candidate, "speed_kmh")
    horizontal_acc_m = max(row_float(candidate, "horizontal_acc_m"), 1.0)

    values: dict[str, float] = {
        "bias": 1.0,
        "candidate_count": float(len(rows)),
        "candidate_distance_m": candidate_distance_m,
        "candidate_score": candidate_score,
        "candidate_geometry_score": row_float(candidate, "candidate_geometry_score"),
        "candidate_endpoint_m": candidate_endpoint_m,
        "candidate_rank": candidate_rank,
        "speed_kmh": speed_kmh,
        "horizontal_acc_m": row_float(candidate, "horizontal_acc_m"),
        "gps_signal_bars": row_float(candidate, "gps_signal_bars"),
        "top2_margin": row_float(candidate, "top2_margin"),
        "used_mini_hmm": row_float(candidate, "used_mini_hmm"),
        "heuristic_matches_candidate": row_float(candidate, "heuristic_matches_candidate"),
        "mini_hmm_matches_candidate": row_float(candidate, "mini_hmm_matches_candidate"),
        "candidate_tunnel_selectable": row_float(candidate, "candidate_tunnel_selectable"),
        "candidate_is_service": row_float(candidate, "candidate_is_service"),
        "candidate_has_ref": row_float(candidate, "candidate_has_street_ref"),
        "is_current_selected": 1.0 if candidate_index == current_index else 0.0,
        "is_lowest_distance": 1.0 if candidate_index == distance_index else 0.0,
        "is_lowest_endpoint": 1.0 if candidate_index == endpoint_index else 0.0,
        "is_nonexpert": 1.0
        if candidate_index not in {current_index, distance_index, endpoint_index}
        else 0.0,
        "distance_gap_to_best_m": candidate_distance_m - min(distances),
        "score_gap_to_best": candidate_score - min(scores),
        "endpoint_gap_to_best_m": candidate_endpoint_m - min(endpoints),
        "rank_gap_to_best": candidate_rank - min(ranks),
        "candidate_distance_over_accuracy": candidate_distance_m / horizontal_acc_m,
        "candidate_endpoint_over_accuracy": candidate_endpoint_m / horizontal_acc_m,
        "candidate_low_endpoint": 1.0 if candidate_endpoint_m <= 12.0 else 0.0,
        "candidate_rank1": 1.0 if candidate_rank <= 1.0 else 0.0,
        "candidate_rank_le2": 1.0 if candidate_rank <= 2.0 else 0.0,
        "candidate_rank_le3": 1.0 if candidate_rank <= 3.0 else 0.0,
    }
    values.update(pair_features(candidate, current, "vs_current"))
    values.update(pair_features(candidate, distance, "vs_distance"))
    values.update(pair_features(candidate, endpoint, "vs_endpoint"))

    continuity = candidate.get("candidate_continuity_class") or "none"
    for continuity_class in CONTINUITY_CLASSES:
        values[f"cont_{continuity_class}"] = 1.0 if continuity == continuity_class else 0.0

    highway = highway_bucket(candidate)
    for highway_class in [
        "primary",
        "secondary",
        "residential",
        "tertiary",
        "unclassified",
        "service",
        "other",
    ]:
        values[f"hw_{highway_class}"] = 1.0 if highway == highway_class else 0.0
    return values


def build_rank_examples(examples: list[Example]) -> list[RankExample]:
    rank_examples: list[RankExample] = []
    for example in examples:
        current_index = pick_current_index(example.rows)
        distance_index = pick_lowest_distance_index(example.rows)
        endpoint_index = pick_lowest_endpoint_index(example.rows)
        feature_rows = [
            feature_map(example.rows, index, current_index, distance_index, endpoint_index)
            for index in range(len(example.rows))
        ]
        labels = [row_int(row, "label_is_pseudo_label") for row in example.rows]
        rank_examples.append(
            RankExample(
                example_id=example.example_id,
                timestamp_utc=example.timestamp_utc,
                rows=example.rows,
                current_index=current_index,
                distance_index=distance_index,
                endpoint_index=endpoint_index,
                feature_rows=feature_rows,
                labels=labels,
            )
        )
    rank_examples.sort(key=lambda example: (example.timestamp_utc, example.example_id))
    return rank_examples


def feature_names_from_examples(rank_examples: list[RankExample]) -> list[str]:
    return list(rank_examples[0].feature_rows[0].keys())


def weighted_probability(labels: list[int], sample_weights: list[float]) -> float:
    total_weight = sum(sample_weights)
    if total_weight <= 0.0:
        return 0.0
    positive_weight = sum(weight for label, weight in zip(labels, sample_weights) if label == 1)
    return positive_weight / total_weight


def weighted_gini(labels: list[int], sample_weights: list[float]) -> float:
    probability = weighted_probability(labels, sample_weights)
    return 1.0 - (probability * probability + (1.0 - probability) * (1.0 - probability))


def candidate_thresholds(values: list[float]) -> list[float]:
    unique = sorted(set(values))
    if len(unique) <= 1:
        return []
    thresholds = [(left + right) / 2.0 for left, right in zip(unique, unique[1:])]
    if len(thresholds) <= 24:
        return thresholds
    indices = {
        int(round(index * (len(thresholds) - 1) / 23.0))
        for index in range(24)
    }
    return [thresholds[index] for index in sorted(indices)]


def fit_tree(
    feature_rows: list[dict[str, float]],
    labels: list[int],
    sample_weights: list[float],
    feature_names: list[str],
    depth: int,
    max_depth: int,
    min_leaf_size: int,
) -> TreeNode:
    probability = weighted_probability(labels, sample_weights)
    node = TreeNode(probability=probability)
    if depth >= max_depth or len(feature_rows) < max(2 * min_leaf_size, 2) or len(set(labels)) <= 1:
        return node

    parent_impurity = weighted_gini(labels, sample_weights)
    best_gain = 0.0
    best_feature: str | None = None
    best_threshold: float | None = None
    best_left_indices: list[int] | None = None
    best_right_indices: list[int] | None = None
    for feature_name in feature_names:
        thresholds = candidate_thresholds([row[feature_name] for row in feature_rows])
        for threshold in thresholds:
            left_indices: list[int] = []
            right_indices: list[int] = []
            for index, row in enumerate(feature_rows):
                if row[feature_name] <= threshold:
                    left_indices.append(index)
                else:
                    right_indices.append(index)
            if len(left_indices) < min_leaf_size or len(right_indices) < min_leaf_size:
                continue
            left_labels = [labels[index] for index in left_indices]
            right_labels = [labels[index] for index in right_indices]
            left_weights = [sample_weights[index] for index in left_indices]
            right_weights = [sample_weights[index] for index in right_indices]
            left_total = sum(left_weights)
            right_total = sum(right_weights)
            total = left_total + right_total
            child_impurity = 0.0
            if total > 0.0:
                child_impurity = (
                    (left_total / total) * weighted_gini(left_labels, left_weights)
                    + (right_total / total) * weighted_gini(right_labels, right_weights)
                )
            gain = parent_impurity - child_impurity
            if gain > best_gain:
                best_gain = gain
                best_feature = feature_name
                best_threshold = threshold
                best_left_indices = left_indices
                best_right_indices = right_indices

    if best_feature is None or best_threshold is None or best_left_indices is None or best_right_indices is None:
        return node

    left_rows = [feature_rows[index] for index in best_left_indices]
    right_rows = [feature_rows[index] for index in best_right_indices]
    left_labels = [labels[index] for index in best_left_indices]
    right_labels = [labels[index] for index in best_right_indices]
    left_weights = [sample_weights[index] for index in best_left_indices]
    right_weights = [sample_weights[index] for index in best_right_indices]
    return TreeNode(
        probability=probability,
        feature_name=best_feature,
        threshold=best_threshold,
        left=fit_tree(left_rows, left_labels, left_weights, feature_names, depth + 1, max_depth, min_leaf_size),
        right=fit_tree(right_rows, right_labels, right_weights, feature_names, depth + 1, max_depth, min_leaf_size),
    )


def predict_probability(node: TreeNode, feature_row: dict[str, float]) -> float:
    current = node
    while current.feature_name is not None and current.threshold is not None:
        if feature_row[current.feature_name] <= current.threshold:
            assert current.left is not None
            current = current.left
        else:
            assert current.right is not None
            current = current.right
    return current.probability


def best_candidate_index(example: RankExample, tree: TreeNode, max_rank: int | None = None) -> tuple[int, list[float]]:
    probabilities = [predict_probability(tree, feature_row) for feature_row in example.feature_rows]
    eligible_indices = list(range(len(example.rows)))
    if max_rank is not None:
        filtered = [
            index
            for index in eligible_indices
            if row_float(example.rows[index], "candidate_rank") <= float(max_rank)
        ]
        if filtered:
            eligible_indices = filtered
    best_index = max(
        eligible_indices,
        key=lambda index: (
            probabilities[index],
            -row_float(example.rows[index], "candidate_rank"),
            -row_float(example.rows[index], "candidate_distance_m"),
        ),
    )
    return best_index, probabilities


def reranker_predictions(rank_examples: list[RankExample], tree: TreeNode, max_rank: int | None = None) -> list[int]:
    return [best_candidate_index(example, tree, max_rank=max_rank)[0] for example in rank_examples]


def three_way_leaf_probabilities(node: MultiClassTreeNode, feature_row: dict[str, float]) -> tuple[float, ...]:
    current = node
    while current.feature_name is not None and current.threshold is not None:
        if feature_row[current.feature_name] <= current.threshold:
            assert current.left is not None
            current = current.left
        else:
            assert current.right is not None
            current = current.right
    return current.probabilities


def hybrid_predictions(
    examples: list[Example],
    rank_examples: list[RankExample],
    three_way_tree: MultiClassTreeNode,
    reranker_tree: TreeNode,
    prob_threshold: float,
    margin_threshold: float,
    max_rank: int,
    nonexpert_only: bool,
    require_low_gate_confidence: bool,
) -> tuple[list[int], dict[str, int]]:
    base_predictions = three_way_gate_predictions(examples, three_way_tree)
    rank_by_id = {example.example_id: example for example in rank_examples}
    predictions: list[int] = []
    stats = {
        "defer_examples": 0,
        "nonexpert_defers": 0,
        "expert_defers": 0,
    }
    for example, base_index in zip(examples, base_predictions):
        rank_example = rank_by_id[example.example_id]
        rerank_index, probabilities = best_candidate_index(rank_example, reranker_tree, max_rank=max_rank)
        if rerank_index == base_index:
            predictions.append(base_index)
            continue
        rerank_prob = probabilities[rerank_index]
        base_prob = probabilities[base_index]
        if rerank_prob < prob_threshold or rerank_prob - base_prob < margin_threshold:
            predictions.append(base_index)
            continue
        if nonexpert_only and rerank_index in {
            rank_example.current_index,
            rank_example.distance_index,
            rank_example.endpoint_index,
        }:
            predictions.append(base_index)
            continue
        if require_low_gate_confidence:
            case = build_three_way_cases([example])[0]
            case_probs = three_way_leaf_probabilities(
                three_way_tree,
                three_way_feature_map(case),
            )
            if max(case_probs) >= 0.75:
                predictions.append(base_index)
                continue
        predictions.append(rerank_index)
        stats["defer_examples"] += 1
        if rerank_index in {rank_example.current_index, rank_example.distance_index, rank_example.endpoint_index}:
            stats["expert_defers"] += 1
        else:
            stats["nonexpert_defers"] += 1
    return predictions, stats


def evaluate_rank_examples(rank_examples: list[RankExample], predicted_indices: list[int]) -> dict[str, Any]:
    as_examples = [
        Example(example_id=example.example_id, timestamp_utc=example.timestamp_utc, rows=example.rows)
        for example in rank_examples
    ]
    return evaluate_examples(as_examples, predicted_indices)


def train(
    train_examples: list[Example],
    val_examples: list[Example],
) -> tuple[dict[str, Any], dict[str, Any]]:
    train_rank_examples = build_rank_examples(train_examples)
    val_rank_examples = build_rank_examples(val_examples)
    feature_names = feature_names_from_examples(train_rank_examples)
    flattened_rows = [row for example in train_rank_examples for row in example.feature_rows]
    labels = [label for example in train_rank_examples for label in example.labels]
    pos_count = sum(labels)
    neg_count = len(labels) - pos_count
    pos_weight = neg_count / max(pos_count, 1)
    sample_weights = [float(pos_weight if label == 1 else 1.0) for label in labels]

    best_summary: dict[str, Any] | None = None
    best_model: dict[str, Any] | None = None
    for max_depth in [2, 3, 4]:
        for min_leaf_size in [4, 6, 10]:
            tree = fit_tree(
                flattened_rows,
                labels,
                sample_weights,
                feature_names,
                depth=0,
                max_depth=max_depth,
                min_leaf_size=min_leaf_size,
            )
            for max_rank in [None, 3, 4]:
                predictions = reranker_predictions(val_rank_examples, tree, max_rank=max_rank)
                metrics = evaluate_rank_examples(val_rank_examples, predictions)
                ranking = (
                    metrics["accuracy"],
                    metrics["changed_recall"],
                    metrics["unchanged_accuracy"],
                )
                if best_summary is None or ranking > (
                    best_summary["accuracy"],
                    best_summary["changed_recall"],
                    best_summary["unchanged_accuracy"],
                ):
                    best_summary = {
                        **metrics,
                        "max_depth": max_depth,
                        "min_leaf_size": min_leaf_size,
                        "max_rank": max_rank,
                    }
                    best_model = {
                        "tree": tree,
                        "feature_names": feature_names,
                        "max_rank": max_rank,
                    }

    assert best_summary is not None
    assert best_model is not None
    return best_summary, best_model


def train_hybrid(
    train_examples: list[Example],
    val_examples: list[Example],
    three_way_tree: MultiClassTreeNode,
    reranker_tree: TreeNode,
) -> tuple[dict[str, Any], dict[str, Any]]:
    val_rank_examples = build_rank_examples(val_examples)
    best_summary: dict[str, Any] | None = None
    best_model: dict[str, Any] | None = None
    for prob_threshold in [0.45, 0.5, 0.55, 0.6]:
        for margin_threshold in [0.05, 0.1, 0.15]:
            for max_rank in [3, 4]:
                for nonexpert_only in [True, False]:
                    predictions, stats = hybrid_predictions(
                        val_examples,
                        val_rank_examples,
                        three_way_tree,
                        reranker_tree,
                        prob_threshold=prob_threshold,
                        margin_threshold=margin_threshold,
                        max_rank=max_rank,
                        nonexpert_only=nonexpert_only,
                        require_low_gate_confidence=False,
                    )
                    metrics = evaluate_rank_examples(val_rank_examples, predictions)
                    ranking = (
                        metrics["accuracy"],
                        metrics["changed_recall"],
                        metrics["unchanged_accuracy"],
                    )
                    if best_summary is None or ranking > (
                        best_summary["accuracy"],
                        best_summary["changed_recall"],
                        best_summary["unchanged_accuracy"],
                    ):
                        best_summary = {
                            **metrics,
                            **stats,
                            "prob_threshold": prob_threshold,
                            "margin_threshold": margin_threshold,
                            "max_rank": max_rank,
                            "nonexpert_only": nonexpert_only,
                        }
                        best_model = {
                            "prob_threshold": prob_threshold,
                            "margin_threshold": margin_threshold,
                            "max_rank": max_rank,
                            "nonexpert_only": nonexpert_only,
                        }
    assert best_summary is not None
    assert best_model is not None
    return best_summary, best_model


def tree_to_dict(node: TreeNode) -> dict[str, Any]:
    data: dict[str, Any] = {"probability": node.probability}
    if node.feature_name is not None and node.threshold is not None:
        data.update(
            {
                "feature_name": node.feature_name,
                "threshold": node.threshold,
                "left": tree_to_dict(node.left) if node.left is not None else None,
                "right": tree_to_dict(node.right) if node.right is not None else None,
            }
        )
    return data


def main() -> None:
    args = parse_args()
    examples = load_examples(args.candidate_csv)
    train_examples, val_examples, test_examples = split_examples(examples)
    reranker_val, reranker_model = train(train_examples, val_examples)
    three_way_val, three_way_model = train_three_way_tree_gate(train_examples, val_examples)
    hybrid_val, hybrid_model = train_hybrid(
        train_examples,
        val_examples,
        three_way_model["tree"],
        reranker_model["tree"],
    )

    test_rank_examples = build_rank_examples(test_examples)
    reranker_test = evaluate_rank_examples(
        test_rank_examples,
        reranker_predictions(test_rank_examples, reranker_model["tree"], reranker_model["max_rank"]),
    )
    hybrid_predictions_test, hybrid_stats = hybrid_predictions(
        test_examples,
        test_rank_examples,
        three_way_model["tree"],
        reranker_model["tree"],
        prob_threshold=hybrid_model["prob_threshold"],
        margin_threshold=hybrid_model["margin_threshold"],
        max_rank=hybrid_model["max_rank"],
        nonexpert_only=hybrid_model["nonexpert_only"],
        require_low_gate_confidence=False,
    )
    hybrid_test = {
        **evaluate_rank_examples(test_rank_examples, hybrid_predictions_test),
        **hybrid_stats,
    }

    payload = {
        "feature_names": reranker_model["feature_names"],
        "reranker": {
            "best_validation": reranker_val,
            "test_metrics": reranker_test,
            "tree": tree_to_dict(reranker_model["tree"]),
        },
        "hybrid": {
            "best_validation": hybrid_val,
            "test_metrics": hybrid_test,
            **hybrid_model,
        },
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
