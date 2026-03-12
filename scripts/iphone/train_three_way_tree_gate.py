#!/usr/bin/env python3
"""Train and export a shallow three-way expert gate."""

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


CLASS_CURRENT = 0
CLASS_DISTANCE = 1
CLASS_ENDPOINT = 2
CLASS_NAMES = ["current", "lowest_distance", "lowest_endpoint"]


@dataclass(frozen=True)
class ThreeWayCase:
    example_id: str
    timestamp_utc: str
    current_index: int
    distance_index: int
    endpoint_index: int
    current_row: dict[str, str]
    distance_row: dict[str, str]
    endpoint_row: dict[str, str]
    label_class: int | None


@dataclass(frozen=True)
class MultiClassTreeNode:
    probabilities: tuple[float, ...]
    feature_name: str | None = None
    threshold: float | None = None
    left: MultiClassTreeNode | None = None
    right: MultiClassTreeNode | None = None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate_csv", type=Path)
    parser.add_argument("--json-out", type=Path, required=True)
    parser.add_argument("--swift-out", type=Path)
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


def build_cases(examples: list[Example]) -> list[ThreeWayCase]:
    cases: list[ThreeWayCase] = []
    for example in examples:
        current_index = pick_current_index(example.rows)
        distance_index = pick_lowest_distance_index(example.rows)
        endpoint_index = pick_lowest_endpoint_index(example.rows)
        expert_indices = {current_index, distance_index, endpoint_index}
        if len(expert_indices) <= 1:
            continue
        pseudo_index = pick_pseudo_index(example.rows)
        label_class: int | None
        if pseudo_index == current_index:
            label_class = CLASS_CURRENT
        elif pseudo_index == distance_index:
            label_class = CLASS_DISTANCE
        elif pseudo_index == endpoint_index:
            label_class = CLASS_ENDPOINT
        else:
            label_class = None
        cases.append(
            ThreeWayCase(
                example_id=example.example_id,
                timestamp_utc=example.timestamp_utc,
                current_index=current_index,
                distance_index=distance_index,
                endpoint_index=endpoint_index,
                current_row=example.rows[current_index],
                distance_row=example.rows[distance_index],
                endpoint_row=example.rows[endpoint_index],
                label_class=label_class,
            )
        )
    cases.sort(key=lambda case: (case.timestamp_utc, case.example_id))
    return cases


def pair_features(left: dict[str, str], right: dict[str, str], prefix: str) -> dict[str, float]:
    left_distance_m = row_float(left, "candidate_distance_m")
    right_distance_m = row_float(right, "candidate_distance_m")
    left_score = row_float(left, "candidate_score")
    right_score = row_float(right, "candidate_score")
    left_endpoint_m = row_float(left, "candidate_endpoint_proximity_m")
    right_endpoint_m = row_float(right, "candidate_endpoint_proximity_m")
    left_rank = row_float(left, "candidate_rank")
    right_rank = row_float(right, "candidate_rank")
    left_band = row_float(left, "candidate_continuity_band")
    right_band = row_float(right, "candidate_continuity_band")
    features: dict[str, float] = {
        f"{prefix}_distance_advantage_m": left_distance_m - right_distance_m,
        f"{prefix}_score_advantage": left_score - right_score,
        f"{prefix}_endpoint_advantage_m": left_endpoint_m - right_endpoint_m,
        f"{prefix}_rank_advantage": left_rank - right_rank,
        f"{prefix}_band_advantage": left_band - right_band,
        f"{prefix}_same_ref": 1.0
        if (left.get("candidate_street_ref") or "")
        and left.get("candidate_street_ref") == right.get("candidate_street_ref")
        else 0.0,
        f"{prefix}_same_highway": 1.0 if highway_bucket(left) == highway_bucket(right) else 0.0,
        f"{prefix}_same_continuity": 1.0
        if (left.get("candidate_continuity_class") or "none")
        == (right.get("candidate_continuity_class") or "none")
        else 0.0,
    }
    return features


def feature_map(case: ThreeWayCase) -> dict[str, float]:
    current = case.current_row
    distance = case.distance_row
    endpoint = case.endpoint_row

    current_distance_m = row_float(current, "candidate_distance_m")
    distance_distance_m = row_float(distance, "candidate_distance_m")
    endpoint_distance_m = row_float(endpoint, "candidate_distance_m")
    current_endpoint_m = row_float(current, "candidate_endpoint_proximity_m")
    distance_endpoint_m = row_float(distance, "candidate_endpoint_proximity_m")
    endpoint_endpoint_m = row_float(endpoint, "candidate_endpoint_proximity_m")
    current_score = row_float(current, "candidate_score")
    distance_score = row_float(distance, "candidate_score")
    endpoint_score = row_float(endpoint, "candidate_score")
    current_rank = row_float(current, "candidate_rank")
    distance_rank = row_float(distance, "candidate_rank")
    endpoint_rank = row_float(endpoint, "candidate_rank")

    values: dict[str, float] = {
        "bias": 1.0,
        "speed_kmh": row_float(current, "speed_kmh"),
        "horizontal_acc_m": row_float(current, "horizontal_acc_m"),
        "gps_signal_bars": row_float(current, "gps_signal_bars"),
        "top2_margin": row_float(current, "top2_margin"),
        "used_mini_hmm": row_float(current, "used_mini_hmm"),
        "current_distance_m": current_distance_m,
        "distance_distance_m": distance_distance_m,
        "endpoint_distance_m": endpoint_distance_m,
        "current_endpoint_m": current_endpoint_m,
        "distance_endpoint_m": distance_endpoint_m,
        "endpoint_endpoint_m": endpoint_endpoint_m,
        "current_score": current_score,
        "distance_score": distance_score,
        "endpoint_score": endpoint_score,
        "current_rank": current_rank,
        "distance_rank": distance_rank,
        "endpoint_rank": endpoint_rank,
        "current_low_endpoint": 1.0 if current_endpoint_m <= 12.0 else 0.0,
        "distance_low_endpoint": 1.0 if distance_endpoint_m <= 12.0 else 0.0,
        "endpoint_low_endpoint": 1.0 if endpoint_endpoint_m <= 12.0 else 0.0,
        "current_rank1": 1.0 if current_rank <= 1.0 else 0.0,
        "distance_rank1": 1.0 if distance_rank <= 1.0 else 0.0,
        "endpoint_rank1": 1.0 if endpoint_rank <= 1.0 else 0.0,
        "current_mini_match": row_float(current, "mini_hmm_matches_candidate"),
        "distance_mini_match": row_float(distance, "mini_hmm_matches_candidate"),
        "endpoint_mini_match": row_float(endpoint, "mini_hmm_matches_candidate"),
        "current_has_ref": row_float(current, "candidate_has_street_ref"),
        "distance_has_ref": row_float(distance, "candidate_has_street_ref"),
        "endpoint_has_ref": row_float(endpoint, "candidate_has_street_ref"),
        "current_is_service": row_float(current, "candidate_is_service"),
        "distance_is_service": row_float(distance, "candidate_is_service"),
        "endpoint_is_service": row_float(endpoint, "candidate_is_service"),
    }

    values.update(pair_features(current, distance, "cd"))
    values.update(pair_features(current, endpoint, "ce"))
    values.update(pair_features(distance, endpoint, "de"))

    for name, row in [
        ("current", current),
        ("distance", distance),
        ("endpoint", endpoint),
    ]:
        continuity = row.get("candidate_continuity_class") or "none"
        for continuity_class in CONTINUITY_CLASSES:
            values[f"{name}_cont_{continuity_class}"] = 1.0 if continuity == continuity_class else 0.0

    return values


def feature_names_from_cases(cases: list[ThreeWayCase]) -> list[str]:
    sample = feature_map(cases[0])
    return list(sample.keys())


def class_probabilities(labels: list[int], sample_weights: list[float]) -> tuple[float, ...]:
    totals = [0.0, 0.0, 0.0]
    total_weight = sum(sample_weights)
    if total_weight <= 0.0:
        return (0.0, 0.0, 0.0)
    for label, weight in zip(labels, sample_weights):
        totals[label] += weight
    return tuple(value / total_weight for value in totals)


def multiclass_gini(labels: list[int], sample_weights: list[float]) -> float:
    probabilities = class_probabilities(labels, sample_weights)
    return 1.0 - sum(probability * probability for probability in probabilities)


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
) -> MultiClassTreeNode:
    probabilities = class_probabilities(labels, sample_weights)
    node = MultiClassTreeNode(probabilities=probabilities)
    if depth >= max_depth or len(feature_rows) < max(2 * min_leaf_size, 2) or len(set(labels)) <= 1:
        return node

    parent_impurity = multiclass_gini(labels, sample_weights)
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
                    (left_total / total) * multiclass_gini(left_labels, left_weights)
                    + (right_total / total) * multiclass_gini(right_labels, right_weights)
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
    return MultiClassTreeNode(
        probabilities=probabilities,
        feature_name=best_feature,
        threshold=best_threshold,
        left=fit_tree(left_rows, left_labels, left_weights, feature_names, depth + 1, max_depth, min_leaf_size),
        right=fit_tree(right_rows, right_labels, right_weights, feature_names, depth + 1, max_depth, min_leaf_size),
    )


def predict_class(node: MultiClassTreeNode, feature_row: dict[str, float]) -> int:
    probabilities = predict_probabilities(node, feature_row)
    return max(range(len(probabilities)), key=probabilities.__getitem__)


def predict_probabilities(node: MultiClassTreeNode, feature_row: dict[str, float]) -> tuple[float, ...]:
    current = node
    while current.feature_name is not None and current.threshold is not None:
        if feature_row[current.feature_name] <= current.threshold:
            assert current.left is not None
            current = current.left
        else:
            assert current.right is not None
            current = current.right
    return current.probabilities


def predicted_index_for_case(case: ThreeWayCase, predicted_class: int) -> int:
    if predicted_class == CLASS_DISTANCE:
        return case.distance_index
    if predicted_class == CLASS_ENDPOINT:
        return case.endpoint_index
    return case.current_index


def gate_predictions(examples: list[Example], tree: MultiClassTreeNode) -> list[int]:
    case_by_id = {case.example_id: case for case in build_cases(examples)}
    predictions: list[int] = []
    for example in examples:
        case = case_by_id.get(example.example_id)
        if case is None:
            predictions.append(pick_current_index(example.rows))
            continue
        predicted_class = predict_class(tree, feature_map(case))
        predictions.append(predicted_index_for_case(case, predicted_class))
    return predictions


def case_stats(cases: list[ThreeWayCase]) -> dict[str, int]:
    stats = {
        "expert_case_examples": len(cases),
        "eligible_examples": 0,
        "choose_current_examples": 0,
        "choose_distance_examples": 0,
        "choose_endpoint_examples": 0,
        "none_of_three_examples": 0,
    }
    for case in cases:
        if case.label_class is None:
            stats["none_of_three_examples"] += 1
            continue
        stats["eligible_examples"] += 1
        if case.label_class == CLASS_CURRENT:
            stats["choose_current_examples"] += 1
        elif case.label_class == CLASS_DISTANCE:
            stats["choose_distance_examples"] += 1
        else:
            stats["choose_endpoint_examples"] += 1
    return stats


def train(
    train_examples: list[Example],
    val_examples: list[Example],
) -> tuple[dict[str, Any], dict[str, Any]]:
    train_cases = build_cases(train_examples)
    val_cases = build_cases(val_examples)
    trainable_cases = [case for case in train_cases if case.label_class is not None]
    if not trainable_cases:
        raise ValueError("No three-way expert cases available for training.")

    feature_names = feature_names_from_cases(trainable_cases)
    feature_rows = [feature_map(case) for case in trainable_cases]
    labels = [int(case.label_class) for case in trainable_cases]
    counts = {
        CLASS_CURRENT: max(sum(1 for label in labels if label == CLASS_CURRENT), 1),
        CLASS_DISTANCE: max(sum(1 for label in labels if label == CLASS_DISTANCE), 1),
        CLASS_ENDPOINT: max(sum(1 for label in labels if label == CLASS_ENDPOINT), 1),
    }
    sample_weights = [float(len(labels) / (3.0 * counts[label])) for label in labels]

    best_summary: dict[str, Any] | None = None
    best_model: dict[str, Any] | None = None
    for max_depth in [1, 2, 3, 4]:
        for min_leaf_size in [2, 4, 6, 8]:
            tree = fit_tree(
                feature_rows,
                labels,
                sample_weights,
                feature_names,
                depth=0,
                max_depth=max_depth,
                min_leaf_size=min_leaf_size,
            )
            metrics = evaluate_examples(val_examples, gate_predictions(val_examples, tree))
            ranking = (
                metrics["accuracy"],
                metrics["unchanged_accuracy"],
                metrics["changed_recall"],
            )
            if best_summary is None or ranking > (
                best_summary["accuracy"],
                best_summary["unchanged_accuracy"],
                best_summary["changed_recall"],
            ):
                best_summary = {
                    **metrics,
                    "max_depth": max_depth,
                    "min_leaf_size": min_leaf_size,
                    "train_stats": case_stats(train_cases),
                    "val_stats": case_stats(val_cases),
                }
                best_model = {
                    "tree": tree,
                    "class_names": CLASS_NAMES,
                    "feature_names": feature_names,
                    "train_stats": case_stats(train_cases),
                    "val_stats": case_stats(val_cases),
                }

    assert best_summary is not None
    assert best_model is not None
    return best_summary, best_model


def tree_to_dict(node: MultiClassTreeNode) -> dict[str, Any]:
    data: dict[str, Any] = {"probabilities": list(node.probabilities)}
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


def render_swift(tree: MultiClassTreeNode) -> str:
    def render_leaf(node: MultiClassTreeNode) -> str:
        return "[" + ", ".join(f"{value:.12f}" for value in node.probabilities) + "]"

    def render_node(node: MultiClassTreeNode, indent: str) -> str:
        if node.feature_name is None or node.threshold is None or node.left is None or node.right is None:
            return f"{indent}return {render_leaf(node)}\n"
        return (
            f'{indent}if featureValues["{node.feature_name}", default: 0.0] <= {node.threshold:.12f} {{\n'
            f"{render_node(node.left, indent + '    ')}"
            f"{indent}}} else {{\n"
            f"{render_node(node.right, indent + '    ')}"
            f"{indent}}}\n"
        )

    class_names = ", ".join(f'"{name}"' for name in CLASS_NAMES)
    return (
        "import Foundation\n\n"
        "enum DriveMatchThreeWayGateModel {\n"
        f"    static let classNames: [String] = [{class_names}]\n\n"
        "    static func probabilities(featureValues: [String: Double]) -> [Double] {\n"
        f"{render_node(tree, '        ')}"
        "    }\n"
        "}\n"
    )


def main() -> None:
    args = parse_args()
    examples = load_examples(args.candidate_csv)
    train_examples, val_examples, test_examples = split_examples(examples)
    best_validation, model = train(train_examples, val_examples)
    test_metrics = evaluate_examples(test_examples, gate_predictions(test_examples, model["tree"]))
    payload = {
        "class_names": CLASS_NAMES,
        "feature_names": model["feature_names"],
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
        args.swift_out.write_text(render_swift(model["tree"]))
    print(json.dumps({"best_validation": best_validation, "test_metrics": test_metrics}, indent=2))


if __name__ == "__main__":
    main()
