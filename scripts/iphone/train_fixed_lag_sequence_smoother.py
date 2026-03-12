#!/usr/bin/env python3
"""Train and benchmark a fixed-lag sequence smoother over the three-way gate."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from train_disagreement_gate import evaluate_examples, highway_bucket, pick_current_index, row_float
from train_online_linear_ranker import Example, load_examples, split_examples
from train_three_way_tree_gate import (
    CLASS_CURRENT,
    CLASS_DISTANCE,
    CLASS_ENDPOINT,
    MultiClassTreeNode,
    build_cases,
    feature_map as three_way_feature_map,
    gate_predictions as three_way_gate_predictions,
    predict_probabilities,
    train as train_three_way_tree_gate,
)


@dataclass(frozen=True)
class SequenceState:
    candidate_index: int
    candidate_row: dict[str, str]
    probability: float
    emission_log_score: float


@dataclass(frozen=True)
class SequenceStep:
    example: Example
    source_log: str
    states: tuple[SequenceState, ...]


@dataclass(frozen=True)
class SmootherParams:
    lag: int
    stay_same_way_bonus: float
    switch_penalty: float
    same_ref_bonus: float
    same_street_bonus: float
    same_highway_bonus: float
    low_speed_switch_bonus: float
    high_speed_switch_penalty: float
    endpoint_switch_bonus: float


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate_csv", type=Path)
    parser.add_argument("--json-out", type=Path, required=True)
    return parser.parse_args()


def build_sequence_steps(examples: list[Example], tree: MultiClassTreeNode) -> list[SequenceStep]:
    case_by_id = {case.example_id: case for case in build_cases(examples)}
    steps: list[SequenceStep] = []
    for example in examples:
        case = case_by_id.get(example.example_id)
        source_log = str(example.rows[0].get("source_log") or "unknown")
        if case is None:
            current_index = pick_current_index(example.rows)
            candidate_row = example.rows[current_index]
            steps.append(
                SequenceStep(
                    example=example,
                    source_log=source_log,
                    states=(
                        SequenceState(
                            candidate_index=current_index,
                            candidate_row=candidate_row,
                            probability=1.0,
                            emission_log_score=0.0,
                        ),
                    ),
                )
            )
            continue

        class_probabilities = predict_probabilities(tree, three_way_feature_map(case))
        class_to_index = {
            CLASS_CURRENT: case.current_index,
            CLASS_DISTANCE: case.distance_index,
            CLASS_ENDPOINT: case.endpoint_index,
        }
        probability_by_index: dict[int, float] = {}
        ordered_indices: list[int] = []
        for class_id in [CLASS_CURRENT, CLASS_DISTANCE, CLASS_ENDPOINT]:
            candidate_index = class_to_index[class_id]
            if candidate_index not in probability_by_index:
                ordered_indices.append(candidate_index)
                probability_by_index[candidate_index] = 0.0
            probability_by_index[candidate_index] += class_probabilities[class_id]
        states = tuple(
            SequenceState(
                candidate_index=candidate_index,
                candidate_row=example.rows[candidate_index],
                probability=probability_by_index[candidate_index],
                emission_log_score=math.log(max(probability_by_index[candidate_index], 1e-6)),
            )
            for candidate_index in ordered_indices
        )
        steps.append(SequenceStep(example=example, source_log=source_log, states=states))
    return steps


def group_steps_by_log(steps: list[SequenceStep]) -> list[list[SequenceStep]]:
    grouped: dict[str, list[SequenceStep]] = {}
    for step in steps:
        grouped.setdefault(step.source_log, []).append(step)
    sequences = list(grouped.values())
    sequences.sort(key=lambda sequence: (sequence[0].source_log, sequence[0].example.timestamp_utc))
    return sequences


def transition_score(previous: SequenceState, current: SequenceState, params: SmootherParams) -> float:
    previous_row = previous.candidate_row
    current_row = current.candidate_row
    previous_way = previous_row.get("candidate_way_id") or ""
    current_way = current_row.get("candidate_way_id") or ""
    if previous_way and previous_way == current_way:
        return params.stay_same_way_bonus

    score = -params.switch_penalty
    speed_kmh = max(row_float(previous_row, "speed_kmh"), row_float(current_row, "speed_kmh"))
    if speed_kmh <= 45.0:
        score += params.low_speed_switch_bonus
    if speed_kmh >= 80.0:
        score -= params.high_speed_switch_penalty

    previous_ref = previous_row.get("candidate_street_ref") or ""
    current_ref = current_row.get("candidate_street_ref") or ""
    if previous_ref and previous_ref == current_ref:
        score += params.same_ref_bonus

    previous_name = previous_row.get("candidate_street_name") or ""
    current_name = current_row.get("candidate_street_name") or ""
    if previous_name and previous_name == current_name:
        score += params.same_street_bonus

    if highway_bucket(previous_row) == highway_bucket(current_row):
        score += params.same_highway_bonus

    if row_float(current_row, "candidate_endpoint_proximity_m") <= 12.0:
        score += params.endpoint_switch_bonus
    return score


def best_path_candidate_indices(window: list[SequenceStep], params: SmootherParams) -> list[int]:
    if not window:
        return []
    if len(window) == 1:
        best_state = max(window[0].states, key=lambda state: (state.emission_log_score, -state.candidate_index))
        return [best_state.candidate_index]

    path_scores: list[list[float]] = []
    backpointers: list[list[int]] = []
    first_scores = [state.emission_log_score for state in window[0].states]
    path_scores.append(first_scores)
    backpointers.append([-1] * len(window[0].states))

    for step_index in range(1, len(window)):
        previous_step = window[step_index - 1]
        current_step = window[step_index]
        current_scores: list[float] = []
        current_backpointers: list[int] = []
        for current_state in current_step.states:
            best_previous_index = 0
            best_score = -1e18
            for previous_index, previous_state in enumerate(previous_step.states):
                score = (
                    path_scores[step_index - 1][previous_index]
                    + transition_score(previous_state, current_state, params)
                    + current_state.emission_log_score
                )
                if score > best_score:
                    best_score = score
                    best_previous_index = previous_index
            current_scores.append(best_score)
            current_backpointers.append(best_previous_index)
        path_scores.append(current_scores)
        backpointers.append(current_backpointers)

    final_step_index = len(window) - 1
    final_state_index = max(range(len(window[final_step_index].states)), key=path_scores[final_step_index].__getitem__)
    chosen_state_indices = [0] * len(window)
    chosen_state_indices[final_step_index] = final_state_index
    for step_index in range(final_step_index, 0, -1):
        chosen_state_indices[step_index - 1] = backpointers[step_index][chosen_state_indices[step_index]]
    return [
        window[step_index].states[state_index].candidate_index
        for step_index, state_index in enumerate(chosen_state_indices)
    ]


def smooth_sequences(steps: list[SequenceStep], params: SmootherParams) -> tuple[list[int], dict[str, int]]:
    sequences = group_steps_by_log(steps)
    prediction_by_example_id: dict[str, int] = {}
    stats = {
        "adjusted_examples": 0,
        "log_count": len(sequences),
        "sequence_windows_evaluated": 0,
    }
    for sequence in sequences:
        base_predictions = [
            max(step.states, key=lambda state: (state.probability, -state.candidate_index)).candidate_index
            for step in sequence
        ]
        buffer: list[SequenceStep] = []
        sequence_predictions: list[int] = []
        for step in sequence:
            buffer.append(step)
            if len(buffer) > params.lag:
                best_path = best_path_candidate_indices(buffer, params)
                stats["sequence_windows_evaluated"] += 1
                sequence_predictions.append(best_path[0])
                buffer.pop(0)
        while buffer:
            best_path = best_path_candidate_indices(buffer, params)
            stats["sequence_windows_evaluated"] += 1
            sequence_predictions.append(best_path[0])
            buffer.pop(0)
        stats["adjusted_examples"] += sum(
            1 for base_prediction, smooth_prediction in zip(base_predictions, sequence_predictions) if base_prediction != smooth_prediction
        )
        for step, prediction in zip(sequence, sequence_predictions):
            prediction_by_example_id[step.example.example_id] = prediction
    predictions = [prediction_by_example_id[step.example.example_id] for step in steps]
    return predictions, stats


def train(
    train_examples: list[Example],
    val_examples: list[Example],
    three_way_tree: MultiClassTreeNode,
) -> tuple[dict[str, Any], dict[str, Any]]:
    val_steps = build_sequence_steps(val_examples, three_way_tree)
    best_summary: dict[str, Any] | None = None
    best_model: dict[str, Any] | None = None
    for lag in [1, 3, 5, 8]:
        for stay_same_way_bonus in [0.0, 0.15, 0.3]:
            for switch_penalty in [0.0, 0.05, 0.1, 0.15]:
                for same_ref_bonus in [0.0, 0.05, 0.1]:
                    for same_street_bonus in [0.0, 0.03]:
                        for same_highway_bonus in [0.0, 0.02]:
                            for low_speed_switch_bonus in [0.0, 0.04]:
                                for high_speed_switch_penalty in [0.0, 0.08]:
                                    for endpoint_switch_bonus in [0.0, 0.04]:
                                        params = SmootherParams(
                                            lag=lag,
                                            stay_same_way_bonus=stay_same_way_bonus,
                                            switch_penalty=switch_penalty,
                                            same_ref_bonus=same_ref_bonus,
                                            same_street_bonus=same_street_bonus,
                                            same_highway_bonus=same_highway_bonus,
                                            low_speed_switch_bonus=low_speed_switch_bonus,
                                            high_speed_switch_penalty=high_speed_switch_penalty,
                                            endpoint_switch_bonus=endpoint_switch_bonus,
                                        )
                                        predictions, stats = smooth_sequences(val_steps, params)
                                        metrics = evaluate_examples(val_examples, predictions)
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
                                            best_summary = {**metrics, **stats, **params.__dict__}
                                            best_model = {"params": params}
    assert best_summary is not None
    assert best_model is not None
    return best_summary, best_model


def main() -> None:
    args = parse_args()
    examples = load_examples(args.candidate_csv)
    train_examples, val_examples, test_examples = split_examples(examples)
    _, three_way_model = train_three_way_tree_gate(train_examples, val_examples)
    best_validation, model = train(train_examples, val_examples, three_way_model["tree"])
    test_steps = build_sequence_steps(test_examples, three_way_model["tree"])
    test_predictions, test_stats = smooth_sequences(test_steps, model["params"])
    test_metrics = {**evaluate_examples(test_examples, test_predictions), **test_stats}
    payload = {
        "split": {
            "train_examples": len(train_examples),
            "val_examples": len(val_examples),
            "test_examples": len(test_examples),
        },
        "best_validation": best_validation,
        "test_metrics": test_metrics,
        "params": model["params"].__dict__,
    }
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    print(json.dumps(payload, indent=2))


if __name__ == "__main__":
    main()
