#!/usr/bin/env python3
"""Train and export a shallow tree disagreement gate."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from train_disagreement_gate import GateCase, build_gate_cases, evaluate_examples, feature_map
from train_online_linear_ranker import Example, load_examples, split_examples


@dataclass(frozen=True)
class TreeNode:
    probability: float
    feature_name: str | None = None
    threshold: float | None = None
    left: TreeNode | None = None
    right: TreeNode | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate_csv", type=Path)
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--swift-out", type=Path)
    return parser.parse_args()


def weighted_probability(labels: list[int], sample_weights: list[float]) -> float:
    total_weight = sum(sample_weights)
    if total_weight <= 0.0:
        return 0.0
    positive_weight = sum(weight for label, weight in zip(labels, sample_weights) if label == 1)
    return positive_weight / total_weight


def weighted_gini(labels: list[int], sample_weights: list[float]) -> float:
    probability = weighted_probability(labels, sample_weights)
    return 1.0 - (probability**2 + (1.0 - probability) ** 2)


def candidate_thresholds(values: list[float]) -> list[float]:
    unique = sorted(set(values))
    if len(unique) <= 1:
        return []
    return [(left + right) / 2.0 for left, right in zip(unique, unique[1:])]


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
            left_indices = [index for index, row in enumerate(feature_rows) if row[feature_name] <= threshold]
            right_indices = [index for index in range(len(feature_rows)) if index not in left_indices]
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


def tree_gate_predictions(examples: list[Example], tree: TreeNode, threshold: float) -> list[int]:
    case_by_id = {case.example_id: case for case in build_gate_cases(examples)}
    predictions: list[int] = []
    for example in examples:
        case = case_by_id.get(example.example_id)
        if case is None:
            predictions.append(next((index for index, row in enumerate(example.rows) if int(row["label_is_current_selected"]) == 1), 0))
            continue
        probability = predict_probability(tree, feature_map(case))
        predictions.append(case.distance_index if probability >= threshold else case.current_index)
    return predictions


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


def collect_feature_names(cases: list[GateCase]) -> list[str]:
    sample = feature_map(cases[0])
    return list(sample.keys())


def train(
    train_examples: list[Example],
    val_examples: list[Example],
) -> tuple[dict[str, Any], dict[str, Any]]:
    train_cases = build_gate_cases(train_examples)
    val_cases = build_gate_cases(val_examples)
    trainable_cases = [case for case in train_cases if case.choose_distance is not None]
    if not trainable_cases:
        raise ValueError("No disagreement cases available for tree gate training.")

    feature_names = collect_feature_names(trainable_cases)
    feature_rows = [feature_map(case) for case in trainable_cases]
    labels = [int(case.choose_distance) for case in trainable_cases]
    pos_count = sum(labels)
    neg_count = len(labels) - pos_count
    pos_weight = neg_count / max(pos_count, 1)
    sample_weights = [float(pos_weight if label == 1 else 1.0) for label in labels]

    best_summary: dict[str, Any] | None = None
    best_model: dict[str, Any] | None = None
    for max_depth in [1, 2, 3, 4]:
        for min_leaf_size in [2, 3, 4, 6]:
            tree = fit_tree(
                feature_rows,
                labels,
                sample_weights,
                feature_names,
                depth=0,
                max_depth=max_depth,
                min_leaf_size=min_leaf_size,
            )
            for threshold in [0.35, 0.4, 0.45, 0.5, 0.55, 0.6]:
                metrics = evaluate_examples(val_examples, tree_gate_predictions(val_examples, tree, threshold))
                ranking = (
                    metrics["accuracy"],
                    metrics["disagreement_accuracy"],
                    metrics["unchanged_accuracy"],
                    metrics["changed_recall"],
                )
                if best_summary is None or ranking > (
                    best_summary["accuracy"],
                    best_summary["disagreement_accuracy"],
                    best_summary["unchanged_accuracy"],
                    best_summary["changed_recall"],
                ):
                    best_summary = {
                        **metrics,
                        "max_depth": max_depth,
                        "min_leaf_size": min_leaf_size,
                        "threshold": threshold,
                        "train_stats": eligible_stats(train_cases),
                        "val_stats": eligible_stats(val_cases),
                    }
                    best_model = {
                        "tree": tree,
                        "threshold": threshold,
                        "feature_names": feature_names,
                        "train_stats": eligible_stats(train_cases),
                        "val_stats": eligible_stats(val_cases),
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


def render_swift(tree: TreeNode, threshold: float) -> str:
    def render_node(node: TreeNode, indent: str) -> str:
        if node.feature_name is None or node.threshold is None or node.left is None or node.right is None:
            return f"{indent}return {node.probability:.12f}\n"
        return (
            f'{indent}if featureValues["{node.feature_name}", default: 0.0] <= {node.threshold:.12f} {{\n'
            f"{render_node(node.left, indent + '    ')}"
            f"{indent}}} else {{\n"
            f"{render_node(node.right, indent + '    ')}"
            f"{indent}}}\n"
        )

    return (
        "import Foundation\n\n"
        "enum DriveMatchDisagreementTreeGateModel {\n"
        f"    static let threshold: Double = {threshold:.12f}\n\n"
        "    static func probability(featureValues: [String: Double]) -> Double {\n"
        f"{render_node(tree, '        ')}"
        "    }\n"
        "}\n"
    )


def main() -> None:
    args = parse_args()
    examples = load_examples(args.candidate_csv)
    train_examples, val_examples, test_examples = split_examples(examples)
    best_validation, model = train(train_examples, val_examples)
    test_metrics = evaluate_examples(
        test_examples,
        tree_gate_predictions(test_examples, model["tree"], model["threshold"]),
    )
    payload = {
        "feature_names": model["feature_names"],
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
        "tree": tree_to_dict(model["tree"]),
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    if args.swift_out:
        args.swift_out.write_text(render_swift(model["tree"], model["threshold"]))
    print(json.dumps({"best_validation": best_validation, "test_metrics": test_metrics}, indent=2))


if __name__ == "__main__":
    main()
