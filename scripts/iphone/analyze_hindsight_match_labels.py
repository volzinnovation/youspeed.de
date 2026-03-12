#!/usr/bin/env python3
"""Analyze fixed-lag hindsight supervision in YouSpeed drive-match logs.

This script quantifies whether future selected ways can serve as high-confidence
pseudo-labels for earlier ambiguous fixes and optionally exports candidate-level
training examples for downstream ranking experiments.
"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any


SELECTED_WAY_PATTERN = re.compile(r"selected ([^ ]+)")


@dataclass
class CandidateTrace:
    rank: int
    way_id: str | None
    score: float | None
    distance_m: float | None
    geometry_score: float | None
    endpoint_proximity_m: float | None
    continuity_class: str | None
    highway: str | None
    service: str | None
    street_name: str | None
    street_ref: str | None
    tunnel_selectable: bool | None
    is_selected: bool | None


@dataclass
class LogRow:
    fix_id: int
    timestamp_utc: str
    dt: datetime
    lat: float
    lon: float
    speed_kmh: float
    horizontal_acc_m: float
    vertical_acc_m: float
    course_deg: float
    gps_signal_bars: int
    status: str
    selected_way_id: str | None
    used_mini_hmm: bool
    heuristic_way_id: str | None
    mini_hmm_way_id: str | None
    final_way_id: str | None
    candidate_traces: list[CandidateTrace]

    @property
    def candidate_way_ids(self) -> list[str]:
        return [candidate.way_id for candidate in self.candidate_traces if candidate.way_id]

    @property
    def top2_margin(self) -> float | None:
        scores = [candidate.score for candidate in self.candidate_traces if candidate.score is not None]
        if len(scores) < 2:
            return None
        return scores[1] - scores[0]


def parse_timestamp(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def parse_selected_way_ids(selection_trace: list[dict[str, Any]]) -> tuple[str | None, str | None, str | None]:
    heuristic_way_id = None
    mini_hmm_way_id = None
    final_way_id = None
    for step in selection_trace:
        match = SELECTED_WAY_PATTERN.search(step.get("detail", ""))
        if not match:
            continue
        selected_way_id = match.group(1)
        step_name = step.get("step")
        if step_name == "heuristic":
            heuristic_way_id = selected_way_id
        elif step_name == "mini_hmm":
            mini_hmm_way_id = selected_way_id
        elif step_name == "final":
            final_way_id = selected_way_id
    return heuristic_way_id, mini_hmm_way_id, final_way_id


def load_rows(path: Path) -> list[LogRow]:
    rows: list[LogRow] = []
    with path.open() as handle:
        for raw_line in handle:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            payload = json.loads(raw_line)
            result = payload.get("result") or {}
            selection_trace = result.get("selectionTrace") or []
            heuristic_way_id, mini_hmm_way_id, final_way_id = parse_selected_way_ids(selection_trace)
            candidates = [
                CandidateTrace(
                    rank=int(candidate.get("rank", 0)),
                    way_id=candidate.get("wayID"),
                    score=candidate.get("score"),
                    distance_m=candidate.get("distanceM"),
                    geometry_score=candidate.get("geometryScore"),
                    endpoint_proximity_m=candidate.get("endpointProximityM"),
                    continuity_class=candidate.get("continuityClass"),
                    highway=candidate.get("highway"),
                    service=candidate.get("service"),
                    street_name=candidate.get("streetName"),
                    street_ref=candidate.get("streetRef"),
                    tunnel_selectable=candidate.get("tunnelSelectable"),
                    is_selected=candidate.get("isSelected"),
                )
                for candidate in (result.get("candidateTraces") or [])
            ]
            row = LogRow(
                fix_id=int(payload["fixID"]),
                timestamp_utc=payload["timestampUTC"],
                dt=parse_timestamp(payload["timestampUTC"]),
                lat=float(payload["lat"]),
                lon=float(payload["lon"]),
                speed_kmh=float(payload["speedKmh"]),
                horizontal_acc_m=float(payload["horizontalAccM"]),
                vertical_acc_m=float(payload["verticalAccM"]),
                course_deg=float(payload["courseDeg"]),
                gps_signal_bars=int(payload["gpsSignalBars"]),
                status=payload["status"],
                selected_way_id=result.get("wayID"),
                used_mini_hmm=bool(result.get("usedMiniHMM", False)),
                heuristic_way_id=heuristic_way_id,
                mini_hmm_way_id=mini_hmm_way_id,
                final_way_id=final_way_id,
                candidate_traces=candidates,
            )
            rows.append(row)
    rows.sort(key=lambda row: (row.dt, row.fix_id))
    return rows


def build_runs(rows: list[LogRow]) -> list[dict[str, int | str | None]]:
    if not rows:
        return []
    runs: list[dict[str, int | str | None]] = []
    start_index = 0
    for index in range(1, len(rows) + 1):
        if index == len(rows) or rows[index].selected_way_id != rows[start_index].selected_way_id:
            runs.append(
                {
                    "way_id": rows[start_index].selected_way_id,
                    "start": start_index,
                    "end": index - 1,
                    "length": index - start_index,
                }
            )
            start_index = index
    return runs


def summarize_horizon(rows: list[LogRow], horizon: int, min_agreement_ratio: float) -> dict[str, int]:
    total = 0
    future_all_same = 0
    majority_in_current_candidates = 0
    majority_differs_from_current = 0
    majority_differs_in_top2 = 0
    for index, row in enumerate(rows[:-horizon]):
        future_way_ids = [rows[index + offset].selected_way_id for offset in range(1, horizon + 1)]
        if not future_way_ids:
            continue
        total += 1
        majority_way_id, agreement_count = Counter(future_way_ids).most_common(1)[0]
        if agreement_count == horizon:
            future_all_same += 1
        if agreement_count < math.ceil(horizon * min_agreement_ratio):
            continue
        if majority_way_id in row.candidate_way_ids:
            majority_in_current_candidates += 1
            if majority_way_id != row.selected_way_id:
                majority_differs_from_current += 1
                if majority_way_id in row.candidate_way_ids[:2]:
                    majority_differs_in_top2 += 1
    return {
        "total": total,
        "future_all_same": future_all_same,
        "majority_in_current_candidates": majority_in_current_candidates,
        "majority_differs_from_current": majority_differs_from_current,
        "majority_differs_in_top2": majority_differs_in_top2,
    }


def derive_pseudo_labels(
    rows: list[LogRow],
    future_window: int,
    min_future_run_length: int,
    min_agreement_ratio: float,
) -> list[dict[str, Any]]:
    examples: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        future_rows = rows[index + 1 : index + 1 + future_window]
        if len(future_rows) < future_window:
            break
        future_way_ids = [future_row.selected_way_id for future_row in future_rows]
        majority_way_id, agreement_count = Counter(future_way_ids).most_common(1)[0]
        if agreement_count < math.ceil(future_window * min_agreement_ratio):
            continue
        if majority_way_id not in row.candidate_way_ids:
            continue
        future_run_length = 0
        for future_row in future_rows:
            if future_row.selected_way_id == majority_way_id:
                future_run_length += 1
            else:
                break
        if future_run_length < min_future_run_length:
            continue
        current_rank = None
        if row.selected_way_id in row.candidate_way_ids:
            current_rank = row.candidate_way_ids.index(row.selected_way_id) + 1
        pseudo_rank = row.candidate_way_ids.index(majority_way_id) + 1
        example = {
            "fix_id": row.fix_id,
            "timestamp_utc": row.timestamp_utc,
            "lat": row.lat,
            "lon": row.lon,
            "speed_kmh": row.speed_kmh,
            "horizontal_acc_m": row.horizontal_acc_m,
            "vertical_acc_m": row.vertical_acc_m,
            "course_deg": row.course_deg,
            "gps_signal_bars": row.gps_signal_bars,
            "status": row.status,
            "future_window": future_window,
            "future_agreement_count": agreement_count,
            "future_majority_ratio": agreement_count / future_window,
            "future_run_length": future_run_length,
            "selected_way_id": row.selected_way_id,
            "pseudo_label_way_id": majority_way_id,
            "heuristic_way_id": row.heuristic_way_id,
            "mini_hmm_way_id": row.mini_hmm_way_id,
            "final_way_id": row.final_way_id,
            "used_mini_hmm": row.used_mini_hmm,
            "candidate_count": len(row.candidate_traces),
            "top2_margin": row.top2_margin,
            "selected_rank": current_rank,
            "pseudo_label_rank": pseudo_rank,
            "candidates": [
                {
                    "rank": candidate.rank,
                    "way_id": candidate.way_id,
                    "score": candidate.score,
                    "distance_m": candidate.distance_m,
                    "geometry_score": candidate.geometry_score,
                    "endpoint_proximity_m": candidate.endpoint_proximity_m,
                    "continuity_class": candidate.continuity_class,
                    "highway": candidate.highway,
                    "service": candidate.service,
                    "street_name": candidate.street_name,
                    "street_ref": candidate.street_ref,
                    "tunnel_selectable": candidate.tunnel_selectable,
                    "is_current_selected": candidate.way_id == row.selected_way_id,
                    "is_pseudo_label": candidate.way_id == majority_way_id,
                }
                for candidate in row.candidate_traces
            ],
        }
        examples.append(example)
    return examples


def summarize_transitions(rows: list[LogRow], runs: list[dict[str, int | str | None]]) -> dict[str, int]:
    summary: Counter[str] = Counter()
    for previous_run, next_run in zip(runs, runs[1:]):
        previous_row = rows[int(previous_run["end"])]
        future_way_id = str(next_run["way_id"]) if next_run["way_id"] is not None else None
        if future_way_id is None:
            continue
        summary["transition_count"] += 1
        if future_way_id in previous_row.candidate_way_ids:
            summary["future_way_seen_in_previous_candidates"] += 1
            future_rank = previous_row.candidate_way_ids.index(future_way_id) + 1
            if future_rank <= 2:
                summary["future_way_seen_in_previous_top2"] += 1
            if future_rank == 1:
                summary["future_way_seen_in_previous_top1"] += 1
            current_rank = None
            if previous_row.selected_way_id in previous_row.candidate_way_ids:
                current_rank = previous_row.candidate_way_ids.index(previous_row.selected_way_id) + 1
            if current_rank is not None and future_rank < current_rank:
                summary["future_way_ranked_better_than_current_selection"] += 1
        if previous_row.mini_hmm_way_id == future_way_id:
            summary["mini_hmm_agreed_with_future_transition"] += 1
            if previous_row.final_way_id == previous_row.heuristic_way_id:
                summary["heuristic_overrode_future_like_mini_transition"] += 1
    return dict(summary)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log_path", type=Path, help="Path to drive_match_log.ndjson")
    parser.add_argument(
        "--future-window",
        type=int,
        default=5,
        help="Number of future fixes to inspect for pseudo-label derivation (default: 5)",
    )
    parser.add_argument(
        "--min-future-run-length",
        type=int,
        default=3,
        help="Required consecutive future fixes on the majority way (default: 3)",
    )
    parser.add_argument(
        "--min-agreement-ratio",
        type=float,
        default=0.8,
        help="Required agreement ratio within the future window (default: 0.8)",
    )
    parser.add_argument(
        "--sweep-horizons",
        type=str,
        default="1,2,3,5,10",
        help="Comma-separated horizons to summarize (default: 1,2,3,5,10)",
    )
    parser.add_argument(
        "--summary-json",
        type=Path,
        help="Optional path for machine-readable summary JSON",
    )
    parser.add_argument(
        "--pseudo-label-jsonl",
        type=Path,
        help="Optional path to export pseudo-labeled candidate examples as JSONL",
    )
    parser.add_argument(
        "--max-example-print",
        type=int,
        default=8,
        help="Maximum number of pseudo-label examples to print (default: 8)",
    )
    return parser


def main() -> int:
    parser = build_argument_parser()
    args = parser.parse_args()

    rows = load_rows(args.log_path)
    if not rows:
        parser.error(f"No rows found in {args.log_path}")

    runs = build_runs(rows)
    horizons = [int(value) for value in args.sweep_horizons.split(",") if value.strip()]
    horizon_summary = {
        horizon: summarize_horizon(rows, horizon, args.min_agreement_ratio) for horizon in horizons
    }
    transition_summary = summarize_transitions(rows, runs)
    pseudo_labels = derive_pseudo_labels(
        rows,
        future_window=args.future_window,
        min_future_run_length=args.min_future_run_length,
        min_agreement_ratio=args.min_agreement_ratio,
    )

    selected_way_ids = [row.selected_way_id for row in rows if row.selected_way_id]
    margins = sorted(
        row.top2_margin
        for row in rows
        if row.top2_margin is not None
    )
    summary = {
        "log_path": str(args.log_path),
        "row_count": len(rows),
        "duration_seconds": (rows[-1].dt - rows[0].dt).total_seconds(),
        "unique_selected_way_count": len(set(selected_way_ids)),
        "used_mini_hmm_count": sum(1 for row in rows if row.used_mini_hmm),
        "run_count": len(runs),
        "median_run_length": sorted(int(run["length"]) for run in runs)[len(runs) // 2],
        "max_run_length": max(int(run["length"]) for run in runs),
        "median_top2_margin": margins[len(margins) // 2] if margins else None,
        "horizon_summary": horizon_summary,
        "transition_summary": transition_summary,
        "pseudo_label_example_count": len(pseudo_labels),
        "pseudo_label_changed_selection_count": sum(
            1 for example in pseudo_labels if example["pseudo_label_way_id"] != example["selected_way_id"]
        ),
        "pseudo_label_top2_count": sum(
            1 for example in pseudo_labels if example["pseudo_label_rank"] <= 2
        ),
        "pseudo_label_top1_count": sum(
            1 for example in pseudo_labels if example["pseudo_label_rank"] == 1
        ),
        "pseudo_label_mini_hmm_agreement_count": sum(
            1 for example in pseudo_labels if example["pseudo_label_way_id"] == example["mini_hmm_way_id"]
        ),
    }

    if args.summary_json:
        write_json(args.summary_json, summary)
    if args.pseudo_label_jsonl:
        write_jsonl(args.pseudo_label_jsonl, pseudo_labels)

    print(f"log_path: {args.log_path}")
    print(f"rows: {summary['row_count']}")
    print(f"duration_s: {summary['duration_seconds']:.1f}")
    print(f"unique_selected_way_count: {summary['unique_selected_way_count']}")
    print(
        f"used_mini_hmm: {summary['used_mini_hmm_count']} / {summary['row_count']}"
    )
    print(
        f"runs: {summary['run_count']} median={summary['median_run_length']} max={summary['max_run_length']}"
    )
    if summary["median_top2_margin"] is not None:
        print(f"median_top2_margin: {summary['median_top2_margin']:.3f}")
    print("horizon_summary:")
    for horizon in horizons:
        item = horizon_summary[horizon]
        print(
            "  "
            f"h={horizon} total={item['total']} "
            f"future_all_same={item['future_all_same']} "
            f"majority_in_current_candidates={item['majority_in_current_candidates']} "
            f"majority_differs_from_current={item['majority_differs_from_current']} "
            f"majority_differs_in_top2={item['majority_differs_in_top2']}"
        )
    print("transition_summary:")
    for key in sorted(transition_summary):
        print(f"  {key}={transition_summary[key]}")
    print(
        "pseudo_labels:"
        f" count={summary['pseudo_label_example_count']}"
        f" changed_selection={summary['pseudo_label_changed_selection_count']}"
        f" top1={summary['pseudo_label_top1_count']}"
        f" top2={summary['pseudo_label_top2_count']}"
        f" mini_hmm_agreement={summary['pseudo_label_mini_hmm_agreement_count']}"
        f" future_window={args.future_window}"
        f" min_future_run_length={args.min_future_run_length}"
        f" min_agreement_ratio={args.min_agreement_ratio:.2f}"
    )
    if pseudo_labels:
        print("pseudo_label_examples:")
        for example in pseudo_labels[: args.max_example_print]:
            print(
                "  "
                f"fix={example['fix_id']} "
                f"selected={example['selected_way_id']} "
                f"pseudo={example['pseudo_label_way_id']} "
                f"selected_rank={example['selected_rank']} "
                f"pseudo_rank={example['pseudo_label_rank']} "
                f"future_run={example['future_run_length']} "
                f"margin={example['top2_margin']}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
