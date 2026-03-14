#!/usr/bin/env python3
"""Benchmark staged matcher complexity on hindsight pseudo-labeled replay logs.

The ladder stays causal and deterministic. It starts from pure geometric
selection and adds the same classes of logic that the live consumer matcher
adds in production:

1. pure distance
2. distance plus heading-aware geometry score
3. continuity/ref-following trace score
4. corridor/tunnel selectability filters
5. heuristic runtime arbitration
6. mini-HMM sequence arbitration
7. final deployed runtime
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from analyze_hindsight_match_labels import derive_pseudo_labels, load_rows
from retrain_hindsight_from_logs import default_log_paths, select_logs


STAGE_ORDER = [
    "distance_only",
    "heading_geometry",
    "continuity_trace",
    "selectable_trace",
    "heuristic_runtime",
    "mini_hmm_runtime",
    "final_runtime",
]

STAGE_LABELS = {
    "distance_only": "Distance only",
    "heading_geometry": "Distance + heading",
    "continuity_trace": "Continuity trace",
    "selectable_trace": "Corridor/tunnel selectable trace",
    "heuristic_runtime": "Runtime heuristic",
    "mini_hmm_runtime": "Raw mini-HMM pick",
    "final_runtime": "Current deployed final",
}

STAGE_NOTES = {
    "distance_only": "lowest candidate distance to way geometry",
    "heading_geometry": "lowest heading-aware geometry score from the logged runtime trace",
    "continuity_trace": "lowest trace score after continuity/ref banding",
    "selectable_trace": "lowest trace score after corridor/tunnel selectability filtering",
    "heuristic_runtime": "logged heuristic winner before sequence arbitration",
    "mini_hmm_runtime": "logged raw mini-HMM winner, before later final-hold behavior",
    "final_runtime": "logged deployed runtime output; this is the current live anchor",
}

FINAL_GATE_STEPS = [
    "three_way_gate",
    "same_ref_bounce_gate",
    "turn_feasibility_gate",
    "corridor_mode_lock",
    "corridor_entry_arm",
    "corridor_entry_gate",
    "tunnel_entry_gate",
    "tunnel_exit_gate",
]


def safe_float(value: Any) -> float:
    if value in (None, ""):
        return float("inf")
    return float(value)


def safe_int(value: Any, default: int = 1_000_000) -> int:
    if value in (None, ""):
        return default
    return int(value)


def enabled_or_missing(value: Any) -> bool:
    if value is None:
        return True
    return bool(value)


def pick_candidate_index(example: dict[str, Any], predicate) -> int | None:
    for index, candidate in enumerate(example["candidates"]):
        if predicate(candidate):
            return index
    return None


def min_candidate_index(example: dict[str, Any], key_fn) -> int:
    return min(range(len(example["candidates"])), key=lambda index: key_fn(example["candidates"][index]))


def fallback_index(example: dict[str, Any], *stage_names: str) -> int:
    for stage_name in stage_names:
        index = stage_prediction_index(example, stage_name)
        if index is not None:
            return index
    return 0


def stage_prediction_index(example: dict[str, Any], stage_name: str) -> int | None:
    candidates = example["candidates"]
    if not candidates:
        return None
    if stage_name == "distance_only":
        return min_candidate_index(
            example,
            lambda candidate: (
                safe_float(candidate["distance_m"]),
                safe_int(candidate["rank"]),
                safe_float(candidate["geometry_score"]),
            ),
        )
    if stage_name == "heading_geometry":
        return min_candidate_index(
            example,
            lambda candidate: (
                safe_float(candidate["geometry_score"]),
                safe_float(candidate["distance_m"]),
                safe_int(candidate["rank"]),
            ),
        )
    if stage_name == "continuity_trace":
        return min_candidate_index(
            example,
            lambda candidate: (
                safe_float(candidate["score"]),
                safe_float(candidate["geometry_score"]),
                safe_float(candidate["distance_m"]),
                safe_int(candidate["rank"]),
            ),
        )
    if stage_name == "selectable_trace":
        selectable_indices = [
            index
            for index, candidate in enumerate(candidates)
            if enabled_or_missing(candidate.get("corridor_selectable"))
            and enabled_or_missing(candidate.get("tunnel_selectable"))
        ]
        if selectable_indices:
            return min(
                selectable_indices,
                key=lambda index: (
                    safe_float(candidates[index]["score"]),
                    safe_float(candidates[index]["geometry_score"]),
                    safe_float(candidates[index]["distance_m"]),
                    safe_int(candidates[index]["rank"]),
                ),
            )
        return fallback_index(example, "continuity_trace")
    if stage_name == "heuristic_runtime":
        index = pick_candidate_index(example, lambda candidate: candidate["way_id"] == example["heuristic_way_id"])
        if index is not None:
            return index
        return fallback_index(example, "selectable_trace")
    if stage_name == "mini_hmm_runtime":
        index = pick_candidate_index(example, lambda candidate: candidate["way_id"] == example["mini_hmm_way_id"])
        if index is not None:
            return index
        return fallback_index(example, "heuristic_runtime")
    if stage_name == "final_runtime":
        index = pick_candidate_index(example, lambda candidate: candidate["way_id"] == example["final_way_id"])
        if index is not None:
            return index
        index = pick_candidate_index(example, lambda candidate: bool(candidate["is_current_selected"]))
        if index is not None:
            return index
        return fallback_index(example, "mini_hmm_runtime")
    raise ValueError(f"Unknown stage: {stage_name}")


def stage_metrics(examples: list[dict[str, Any]], stage_name: str) -> dict[str, Any]:
    total = 0
    correct = 0
    changed_total = 0
    changed_correct = 0
    unchanged_total = 0
    unchanged_correct = 0
    for example in examples:
        prediction = stage_prediction_index(example, stage_name)
        if prediction is None:
            continue
        total += 1
        predicted_candidate = example["candidates"][prediction]
        predicted_way_id = predicted_candidate["way_id"]
        expected_way_id = example["pseudo_label_way_id"]
        is_correct = predicted_way_id == expected_way_id
        correct += int(is_correct)
        changed = expected_way_id != example["selected_way_id"]
        if changed:
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
        "changed_correct": changed_correct,
        "changed_recall": changed_correct / changed_total if changed_total else 0.0,
        "unchanged_examples": unchanged_total,
        "unchanged_correct": unchanged_correct,
        "unchanged_accuracy": unchanged_correct / unchanged_total if unchanged_total else 0.0,
    }


def stage_delta_summary(
    examples: list[dict[str, Any]],
    previous_stage: str,
    next_stage: str,
) -> dict[str, Any]:
    changed_predictions = 0
    corrections = 0
    regressions = 0
    unchanged = 0
    changed_example_corrections = 0
    changed_example_regressions = 0
    unchanged_example_corrections = 0
    unchanged_example_regressions = 0

    for example in examples:
        previous_index = stage_prediction_index(example, previous_stage)
        next_index = stage_prediction_index(example, next_stage)
        if previous_index is None or next_index is None:
            continue
        previous_way_id = example["candidates"][previous_index]["way_id"]
        next_way_id = example["candidates"][next_index]["way_id"]
        label_way_id = example["pseudo_label_way_id"]
        changed_example = label_way_id != example["selected_way_id"]
        if previous_way_id == next_way_id:
            unchanged += 1
            continue
        changed_predictions += 1
        previous_correct = previous_way_id == label_way_id
        next_correct = next_way_id == label_way_id
        if not previous_correct and next_correct:
            corrections += 1
            if changed_example:
                changed_example_corrections += 1
            else:
                unchanged_example_corrections += 1
        elif previous_correct and not next_correct:
            regressions += 1
            if changed_example:
                changed_example_regressions += 1
            else:
                unchanged_example_regressions += 1

    return {
        "from_stage": previous_stage,
        "to_stage": next_stage,
        "changed_prediction_count": changed_predictions,
        "unchanged_prediction_count": unchanged,
        "corrections": corrections,
        "regressions": regressions,
        "net_corrections": corrections - regressions,
        "changed_example_corrections": changed_example_corrections,
        "changed_example_regressions": changed_example_regressions,
        "unchanged_example_corrections": unchanged_example_corrections,
        "unchanged_example_regressions": unchanged_example_regressions,
    }


def final_gate_audit(examples: list[dict[str, Any]]) -> dict[str, Any]:
    relevant_examples = 0
    final_better = 0
    final_worse = 0
    gate_counts = {step: 0 for step in FINAL_GATE_STEPS}
    gate_corrections = {step: 0 for step in FINAL_GATE_STEPS}
    gate_regressions = {step: 0 for step in FINAL_GATE_STEPS}

    for example in examples:
        mini_index = stage_prediction_index(example, "mini_hmm_runtime")
        final_index = stage_prediction_index(example, "final_runtime")
        if mini_index is None or final_index is None:
            continue
        mini_way_id = example["candidates"][mini_index]["way_id"]
        final_way_id = example["candidates"][final_index]["way_id"]
        if mini_way_id == final_way_id:
            continue
        relevant_examples += 1
        label_way_id = example["pseudo_label_way_id"]
        mini_correct = mini_way_id == label_way_id
        final_correct = final_way_id == label_way_id
        if not mini_correct and final_correct:
            final_better += 1
        elif mini_correct and not final_correct:
            final_worse += 1
        selection_steps = set(example.get("selection_steps") or [])
        for step in FINAL_GATE_STEPS:
            if step not in selection_steps:
                continue
            gate_counts[step] += 1
            if not mini_correct and final_correct:
                gate_corrections[step] += 1
            elif mini_correct and not final_correct:
                gate_regressions[step] += 1

    return {
        "examples_where_final_differs_from_mini_hmm": relevant_examples,
        "final_better_than_mini_hmm": final_better,
        "final_worse_than_mini_hmm": final_worse,
        "net_corrections": final_better - final_worse,
        "gate_counts": gate_counts,
        "gate_corrections": gate_corrections,
        "gate_regressions": gate_regressions,
    }


def summarize_logs(
    future_window: int,
    min_future_run_length: int,
    min_agreement_ratio: float,
    log_paths: list[Path],
) -> dict[str, Any]:
    examples: list[dict[str, Any]] = []
    per_log: list[dict[str, Any]] = []
    total_row_count = 0
    for path in log_paths:
        rows = load_rows(path)
        total_row_count += len(rows)
        pseudo_labels = derive_pseudo_labels(
            rows,
            future_window=future_window,
            min_future_run_length=min_future_run_length,
            min_agreement_ratio=min_agreement_ratio,
        )
        examples.extend(pseudo_labels)
        per_log.append(
            {
                "log_path": str(path),
                "row_count": len(rows),
                "pseudo_label_examples": len(pseudo_labels),
                "changed_examples": sum(
                    1 for example in pseudo_labels if example["pseudo_label_way_id"] != example["selected_way_id"]
                ),
            }
        )

    stage_results = {
        stage_name: stage_metrics(examples, stage_name)
        for stage_name in STAGE_ORDER
    }
    adjacent_deltas = [
        stage_delta_summary(examples, previous_stage, next_stage)
        for previous_stage, next_stage in zip(STAGE_ORDER, STAGE_ORDER[1:])
    ]

    return {
        "future_window": future_window,
        "min_future_run_length": min_future_run_length,
        "min_agreement_ratio": min_agreement_ratio,
        "log_paths": [str(path) for path in log_paths],
        "log_count": len(log_paths),
        "row_count": total_row_count,
        "example_count": len(examples),
        "changed_example_count": sum(
            1 for example in examples if example["pseudo_label_way_id"] != example["selected_way_id"]
        ),
        "per_log": per_log,
        "stage_order": STAGE_ORDER,
        "stage_labels": STAGE_LABELS,
        "stage_notes": STAGE_NOTES,
        "stage_results": stage_results,
        "adjacent_deltas": adjacent_deltas,
        "final_gate_audit": final_gate_audit(examples),
    }


def format_pct(value: float) -> str:
    return f"{100.0 * value:.2f}%"


def print_report(summary: dict[str, Any]) -> None:
    print(
        "MATCHER_COMPLEXITY_DATASET "
        + f"logs={summary['log_count']} examples={summary['example_count']} "
        + f"changed={summary['changed_example_count']}"
    )
    print("MATCHER_COMPLEXITY_STAGE_METRICS")
    for stage_name in summary["stage_order"]:
        metrics = summary["stage_results"][stage_name]
        print(
            f"- {stage_name}"
            + f" label=\"{summary['stage_labels'][stage_name]}\""
            + f" note=\"{summary['stage_notes'][stage_name]}\""
            + f" accuracy={format_pct(metrics['accuracy'])}"
            + f" changed_recall={format_pct(metrics['changed_recall'])}"
            + f" unchanged_accuracy={format_pct(metrics['unchanged_accuracy'])}"
            + f" correct={metrics['correct']}/{metrics['examples']}"
        )
    print("MATCHER_COMPLEXITY_ADJACENT_DELTAS")
    for delta in summary["adjacent_deltas"]:
        print(
            f"- {delta['from_stage']} -> {delta['to_stage']}"
            + f" changed_predictions={delta['changed_prediction_count']}"
            + f" corrections={delta['corrections']}"
            + f" regressions={delta['regressions']}"
            + f" net={delta['net_corrections']}"
        )
    gate_audit = summary["final_gate_audit"]
    print(
        "MATCHER_COMPLEXITY_FINAL_GATE_AUDIT "
        + f"examples={gate_audit['examples_where_final_differs_from_mini_hmm']} "
        + f"final_better={gate_audit['final_better_than_mini_hmm']} "
        + f"final_worse={gate_audit['final_worse_than_mini_hmm']} "
        + f"net={gate_audit['net_corrections']}"
    )
    for step in FINAL_GATE_STEPS:
        count = gate_audit["gate_counts"][step]
        corrections = gate_audit["gate_corrections"][step]
        regressions = gate_audit["gate_regressions"][step]
        if count == 0:
            continue
        print(
            f"  step={step} count={count} corrections={corrections} regressions={regressions}"
        )


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log_paths", nargs="*", type=Path, help="Optional explicit log paths")
    parser.add_argument("--future-window", type=int, default=5)
    parser.add_argument("--min-future-run-length", type=int, default=5)
    parser.add_argument("--min-agreement-ratio", type=float, default=0.8)
    parser.add_argument(
        "--include-subset-logs",
        action="store_true",
        help="Use every matching inspector log instead of dropping subset/duplicate sessions",
    )
    parser.add_argument("--summary-json", type=Path, help="Optional JSON output path")
    return parser


def main() -> int:
    parser = build_argument_parser()
    args = parser.parse_args()
    raw_paths = args.log_paths or default_log_paths()
    if args.include_subset_logs:
        kept_paths = sorted(raw_paths)
        dropped_paths: list[dict[str, str]] = []
    else:
        kept_paths, dropped_paths = select_logs(raw_paths)
    summary = summarize_logs(
        future_window=args.future_window,
        min_future_run_length=args.min_future_run_length,
        min_agreement_ratio=args.min_agreement_ratio,
        log_paths=kept_paths,
    )
    summary["dropped_logs"] = dropped_paths
    summary["selection_policy"] = "all_logs" if args.include_subset_logs else "deduplicated_non_subset_logs"
    if args.summary_json:
        args.summary_json.parent.mkdir(parents=True, exist_ok=True)
        args.summary_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print_report(summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
