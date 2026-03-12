#!/usr/bin/env python3
"""Render LaTeX fragments for the personalized map-matching paper.

This script turns JSON/CSV benchmark artifacts into stable LaTeX fragments so
the paper can be refreshed when a new driving log is analyzed.
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


MODEL_LABELS = {
    "current_final": "Current final matcher",
    "mini_if_available_else_heuristic": "Mini-HMM else heuristic",
    "lowest_distance": "Lowest-distance baseline",
    "disagreement_tree_gate": "Two-way tree gate",
    "three_way_tree_gate": "Three-way tree gate",
    "three_way_fixed_lag_smoother": "Three-way fixed-lag smoother",
    "tree_candidate_ranker": "Tree candidate ranker",
    "logistic_ranker": "Logistic ranker",
    "tiny_mlp_ranker": "Tiny MLP ranker",
    "online_linear_ranker": "Online linear ranker",
}

MODEL_ORDER = [
    "current_final",
    "mini_if_available_else_heuristic",
    "lowest_distance",
    "disagreement_tree_gate",
    "three_way_tree_gate",
    "three_way_fixed_lag_smoother",
    "tree_candidate_ranker",
    "logistic_ranker",
    "tiny_mlp_ranker",
    "online_linear_ranker",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--match-summary", type=Path, required=True)
    parser.add_argument("--training-summary", type=Path, required=True)
    parser.add_argument("--benchmark", type=Path, required=True)
    parser.add_argument("--gate-csv", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    return parser.parse_args()


def read_json(path: Path) -> dict:
    return json.loads(path.read_text())


def load_gate_stats(path: Path) -> dict[str, int]:
    changed = 0
    changed_pseudo_top1 = 0
    changed_pseudo_top2 = 0
    changed_mini_recovers = 0
    changed_both_agree_and_miss = 0
    with path.open(newline="") as handle:
        for row in csv.DictReader(handle):
            if row["label_switch_to_pseudo"] != "1":
                continue
            changed += 1
            pseudo_rank = int(row["pseudo_rank"])
            if pseudo_rank == 1:
                changed_pseudo_top1 += 1
            if pseudo_rank <= 2:
                changed_pseudo_top2 += 1
            heuristic_disagrees = row["heuristic_disagrees_with_mini_hmm"] == "1"
            mini_matches_pseudo = row["mini_hmm_matches_pseudo"] == "1"
            heuristic_matches_pseudo = row["heuristic_matches_pseudo"] == "1"
            if heuristic_disagrees and mini_matches_pseudo:
                changed_mini_recovers += 1
            if (
                not heuristic_disagrees
                and not heuristic_matches_pseudo
                and not mini_matches_pseudo
            ):
                changed_both_agree_and_miss += 1
    return {
        "changed": changed,
        "changed_pseudo_top1": changed_pseudo_top1,
        "changed_pseudo_top2": changed_pseudo_top2,
        "changed_mini_recovers": changed_mini_recovers,
        "changed_both_agree_and_miss": changed_both_agree_and_miss,
    }


def format_int(value: int) -> str:
    return f"{value:,}"


def format_pct(numerator: int, denominator: int) -> str:
    if denominator == 0:
        return "0.0"
    return f"{(100.0 * numerator / denominator):.1f}"


def command(name: str, value: str) -> str:
    return f"\\newcommand{{\\{name}}}{{{value}}}"


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def render_macros(
    match_summary: dict,
    training_summary: dict,
    benchmark: dict,
    gate_stats: dict[str, int],
) -> str:
    transitions = match_summary["transition_summary"]["transition_count"]
    future_candidate = match_summary["transition_summary"]["future_way_seen_in_previous_candidates"]
    future_top2 = match_summary["transition_summary"]["future_way_seen_in_previous_top2"]
    future_ranked_better = match_summary["transition_summary"]["future_way_ranked_better_than_current_selection"]
    macros = [
        command("CurrentLogRows", format_int(match_summary["row_count"])),
        command("CurrentLogRunCount", format_int(match_summary["run_count"])),
        command("CurrentLogTransitions", format_int(transitions)),
        command("PseudoLabelExamples", format_int(training_summary["gate_row_count"])),
        command("PseudoLabelSwitchCount", format_int(training_summary["gate_switch_positive_count"])),
        command("FutureCandidateCount", format_int(future_candidate)),
        command("FutureCandidatePct", format_pct(future_candidate, transitions)),
        command("FutureTopTwoCount", format_int(future_top2)),
        command("FutureTopTwoPct", format_pct(future_top2, transitions)),
        command("FutureRankedBetterCount", format_int(future_ranked_better)),
        command("FutureRankedBetterPct", format_pct(future_ranked_better, transitions)),
        command("ChangedPseudoTopOneCount", format_int(gate_stats["changed_pseudo_top1"])),
        command("ChangedPseudoTopTwoCount", format_int(gate_stats["changed_pseudo_top2"])),
        command("ChangedMiniRecoverCount", format_int(gate_stats["changed_mini_recovers"])),
        command("ChangedBothAgreeMissCount", format_int(gate_stats["changed_both_agree_and_miss"])),
        command("BenchmarkTrainExamples", format_int(benchmark["split"]["train_examples"])),
        command("BenchmarkValExamples", format_int(benchmark["split"]["val_examples"])),
        command("BenchmarkTestExamples", format_int(benchmark["split"]["test_examples"])),
    ]
    return "\n".join(macros) + "\n"


def render_model_rows(benchmark: dict) -> str:
    rows_by_model = {entry["model"]: entry for entry in benchmark["results"]}
    lines: list[str] = []
    for model_name in MODEL_ORDER:
        entry = rows_by_model[model_name]
        test = entry["test"]
        lines.append(
            (
                f"{MODEL_LABELS[model_name]} & "
                f"{100.0 * test['accuracy']:.2f}\\% & "
                f"{100.0 * test['changed_recall']:.2f}\\% & "
                f"{100.0 * test['unchanged_accuracy']:.2f}\\% \\\\"
            )
        )
    body = "%\n".join(lines)
    return "\\newcommand{\\ModelBenchmarkRows}{%\n" + body + "\n}\n"


def main() -> None:
    args = parse_args()
    match_summary = read_json(args.match_summary)
    training_summary = read_json(args.training_summary)
    benchmark = read_json(args.benchmark)
    gate_stats = load_gate_stats(args.gate_csv)

    macros_tex = render_macros(match_summary, training_summary, benchmark, gate_stats)
    model_rows_tex = render_model_rows(benchmark)

    write_text(args.output_dir / "metrics_macros.tex", macros_tex)
    write_text(args.output_dir / "model_benchmark_rows.tex", model_rows_tex)


if __name__ == "__main__":
    main()
