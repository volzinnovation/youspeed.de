#!/usr/bin/env python3
"""Export model-ready hindsight datasets from YouSpeed drive-match logs.

The output is intended for lightweight offline experiments such as:
- logistic regression or tiny MLP gate: keep current match vs switch to
  hindsight pseudo-label
- candidate-ranking model: score each candidate against the hindsight label
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any

from analyze_hindsight_match_labels import derive_pseudo_labels, load_rows


CONTINUITY_BAND_BY_NAME = {
    "preferredWay": 0,
    "sameRef": 1,
    "linkedWay": 2,
    "recentWay": 3,
    "none": 4,
}


def continuity_band(name: str | None) -> int:
    if not name:
        return 4
    return CONTINUITY_BAND_BY_NAME.get(name, 4)


def safe_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def safe_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)


def bool_int(value: bool) -> int:
    return 1 if value else 0


def flatten_value(value: Any) -> Any:
    if value is None:
        return ""
    if isinstance(value, bool):
        return int(value)
    return value


def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w") as handle:
        for row in rows:
            handle.write(json.dumps(row, sort_keys=True) + "\n")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if not rows:
        path.write_text("")
        return
    fieldnames: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                fieldnames.append(key)
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: flatten_value(row.get(key)) for key in fieldnames})


def write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")


def find_candidate(example: dict[str, Any], way_id: str | None) -> dict[str, Any] | None:
    if way_id is None:
        return None
    for candidate in example["candidates"]:
        if candidate["way_id"] == way_id:
            return candidate
    return None


def candidate_pair_features(
    example: dict[str, Any],
    current_candidate: dict[str, Any],
    pseudo_candidate: dict[str, Any],
) -> dict[str, Any]:
    current_score = safe_float(current_candidate["score"])
    pseudo_score = safe_float(pseudo_candidate["score"])
    current_distance = safe_float(current_candidate["distance_m"])
    pseudo_distance = safe_float(pseudo_candidate["distance_m"])
    current_endpoint = safe_float(current_candidate["endpoint_proximity_m"])
    pseudo_endpoint = safe_float(pseudo_candidate["endpoint_proximity_m"])
    current_band = continuity_band(current_candidate["continuity_class"])
    pseudo_band = continuity_band(pseudo_candidate["continuity_class"])

    current_street_name = current_candidate.get("street_name") or ""
    pseudo_street_name = pseudo_candidate.get("street_name") or ""
    current_street_ref = current_candidate.get("street_ref") or ""
    pseudo_street_ref = pseudo_candidate.get("street_ref") or ""
    current_highway = current_candidate.get("highway") or ""
    pseudo_highway = pseudo_candidate.get("highway") or ""
    current_service = current_candidate.get("service") or ""
    pseudo_service = pseudo_candidate.get("service") or ""

    return {
        "current_score": current_score,
        "pseudo_score": pseudo_score,
        "score_delta_current_minus_pseudo": (
            current_score - pseudo_score if current_score is not None and pseudo_score is not None else None
        ),
        "score_delta_pseudo_minus_current": (
            pseudo_score - current_score if current_score is not None and pseudo_score is not None else None
        ),
        "current_distance_m": current_distance,
        "pseudo_distance_m": pseudo_distance,
        "distance_delta_current_minus_pseudo": (
            current_distance - pseudo_distance
            if current_distance is not None and pseudo_distance is not None
            else None
        ),
        "current_endpoint_proximity_m": current_endpoint,
        "pseudo_endpoint_proximity_m": pseudo_endpoint,
        "endpoint_proximity_delta_current_minus_pseudo": (
            current_endpoint - pseudo_endpoint
            if current_endpoint is not None and pseudo_endpoint is not None
            else None
        ),
        "current_rank": safe_int(current_candidate["rank"]),
        "pseudo_rank": safe_int(pseudo_candidate["rank"]),
        "current_continuity_class": current_candidate.get("continuity_class"),
        "pseudo_continuity_class": pseudo_candidate.get("continuity_class"),
        "current_continuity_band": current_band,
        "pseudo_continuity_band": pseudo_band,
        "continuity_band_delta_current_minus_pseudo": current_band - pseudo_band,
        "current_highway": current_highway,
        "pseudo_highway": pseudo_highway,
        "same_highway": bool_int(current_highway == pseudo_highway and current_highway != ""),
        "current_service": current_service,
        "pseudo_service": pseudo_service,
        "current_is_service": bool_int(current_service != ""),
        "pseudo_is_service": bool_int(pseudo_service != ""),
        "same_service": bool_int(current_service == pseudo_service and current_service != ""),
        "current_street_name": current_street_name,
        "pseudo_street_name": pseudo_street_name,
        "same_street_name": bool_int(current_street_name == pseudo_street_name and current_street_name != ""),
        "current_street_ref": current_street_ref,
        "pseudo_street_ref": pseudo_street_ref,
        "same_street_ref": bool_int(current_street_ref == pseudo_street_ref and current_street_ref != ""),
        "current_has_street_ref": bool_int(current_street_ref != ""),
        "pseudo_has_street_ref": bool_int(pseudo_street_ref != ""),
        "current_tunnel_selectable": bool_int(bool(current_candidate.get("tunnel_selectable"))),
        "pseudo_tunnel_selectable": bool_int(bool(pseudo_candidate.get("tunnel_selectable"))),
    }


def build_gate_rows(
    examples: list[dict[str, Any]],
    only_changed: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for example in examples:
        example_id = (
            f"{example['timestamp_utc']}:{example['fix_id']}:"
            f"{example['selected_way_id']}->{example['pseudo_label_way_id']}"
        )
        label_switch = example["pseudo_label_way_id"] != example["selected_way_id"]
        if only_changed and not label_switch:
            continue
        current_candidate = find_candidate(example, example["selected_way_id"])
        pseudo_candidate = find_candidate(example, example["pseudo_label_way_id"])
        if current_candidate is None or pseudo_candidate is None:
            continue
        row = {
            "example_id": example_id,
            "fix_id": example["fix_id"],
            "timestamp_utc": example["timestamp_utc"],
            "label_switch_to_pseudo": bool_int(label_switch),
            "selected_way_id": example["selected_way_id"],
            "pseudo_label_way_id": example["pseudo_label_way_id"],
            "heuristic_way_id": example["heuristic_way_id"],
            "mini_hmm_way_id": example["mini_hmm_way_id"],
            "final_way_id": example["final_way_id"],
            "used_mini_hmm": bool_int(bool(example["used_mini_hmm"])),
            "heuristic_matches_selected": bool_int(example["heuristic_way_id"] == example["selected_way_id"]),
            "heuristic_matches_pseudo": bool_int(example["heuristic_way_id"] == example["pseudo_label_way_id"]),
            "mini_hmm_matches_selected": bool_int(example["mini_hmm_way_id"] == example["selected_way_id"]),
            "mini_hmm_matches_pseudo": bool_int(example["mini_hmm_way_id"] == example["pseudo_label_way_id"]),
            "heuristic_disagrees_with_mini_hmm": bool_int(example["heuristic_way_id"] != example["mini_hmm_way_id"]),
            "future_window": example["future_window"],
            "future_agreement_count": example["future_agreement_count"],
            "future_majority_ratio": example["future_majority_ratio"],
            "future_run_length": example["future_run_length"],
            "candidate_count": example["candidate_count"],
            "top2_margin": example["top2_margin"],
            "speed_kmh": example["speed_kmh"],
            "horizontal_acc_m": example["horizontal_acc_m"],
            "vertical_acc_m": example["vertical_acc_m"],
            "course_deg": example["course_deg"],
            "gps_signal_bars": example["gps_signal_bars"],
            "course_available": bool_int(example["course_deg"] >= 0),
            "speed_is_stationary": bool_int(example["speed_kmh"] < 3.0),
        }
        row.update(candidate_pair_features(example, current_candidate, pseudo_candidate))
        rows.append(row)
    return rows


def build_candidate_rows(
    examples: list[dict[str, Any]],
    only_changed: bool,
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for example in examples:
        example_id = (
            f"{example['timestamp_utc']}:{example['fix_id']}:"
            f"{example['selected_way_id']}->{example['pseudo_label_way_id']}"
        )
        label_switch = example["pseudo_label_way_id"] != example["selected_way_id"]
        if only_changed and not label_switch:
            continue
        for candidate in example["candidates"]:
            row = {
                "example_id": example_id,
                "fix_id": example["fix_id"],
                "timestamp_utc": example["timestamp_utc"],
                "selected_way_id": example["selected_way_id"],
                "pseudo_label_way_id": example["pseudo_label_way_id"],
                "candidate_way_id": candidate["way_id"],
                "label_is_pseudo_label": bool_int(candidate["is_pseudo_label"]),
                "label_is_current_selected": bool_int(candidate["is_current_selected"]),
                "label_switch_to_pseudo": bool_int(label_switch),
                "future_window": example["future_window"],
                "future_agreement_count": example["future_agreement_count"],
                "future_majority_ratio": example["future_majority_ratio"],
                "future_run_length": example["future_run_length"],
                "candidate_count": example["candidate_count"],
                "top2_margin": example["top2_margin"],
                "speed_kmh": example["speed_kmh"],
                "horizontal_acc_m": example["horizontal_acc_m"],
                "vertical_acc_m": example["vertical_acc_m"],
                "course_deg": example["course_deg"],
                "gps_signal_bars": example["gps_signal_bars"],
                "used_mini_hmm": bool_int(bool(example["used_mini_hmm"])),
                "heuristic_matches_candidate": bool_int(example["heuristic_way_id"] == candidate["way_id"]),
                "mini_hmm_matches_candidate": bool_int(example["mini_hmm_way_id"] == candidate["way_id"]),
                "final_matches_candidate": bool_int(example["final_way_id"] == candidate["way_id"]),
                "candidate_rank": safe_int(candidate["rank"]),
                "candidate_score": safe_float(candidate["score"]),
                "candidate_distance_m": safe_float(candidate["distance_m"]),
                "candidate_geometry_score": safe_float(candidate["geometry_score"]),
                "candidate_endpoint_proximity_m": safe_float(candidate["endpoint_proximity_m"]),
                "candidate_continuity_class": candidate["continuity_class"],
                "candidate_continuity_band": continuity_band(candidate["continuity_class"]),
                "candidate_highway": candidate["highway"],
                "candidate_service": candidate["service"],
                "candidate_street_name": candidate["street_name"],
                "candidate_street_ref": candidate["street_ref"],
                "candidate_tunnel_selectable": bool_int(bool(candidate["tunnel_selectable"])),
                "candidate_is_service": bool_int(bool(candidate["service"])),
                "candidate_has_street_ref": bool_int(bool(candidate["street_ref"])),
            }
            rows.append(row)
    return rows


def summarize_rows(gate_rows: list[dict[str, Any]], candidate_rows: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "gate_row_count": len(gate_rows),
        "gate_switch_positive_count": sum(row["label_switch_to_pseudo"] for row in gate_rows),
        "gate_mini_hmm_matches_pseudo_count": sum(row["mini_hmm_matches_pseudo"] for row in gate_rows),
        "gate_heuristic_matches_pseudo_count": sum(row["heuristic_matches_pseudo"] for row in gate_rows),
        "candidate_row_count": len(candidate_rows),
        "candidate_positive_count": sum(row["label_is_pseudo_label"] for row in candidate_rows),
        "candidate_selected_positive_count": sum(row["label_is_current_selected"] for row in candidate_rows),
    }


def build_argument_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("log_path", type=Path, help="Path to drive_match_log.ndjson")
    parser.add_argument("--future-window", type=int, default=5)
    parser.add_argument("--min-future-run-length", type=int, default=5)
    parser.add_argument("--min-agreement-ratio", type=float, default=0.8)
    parser.add_argument(
        "--only-changed",
        action="store_true",
        help="Export only examples where the hindsight label differs from the current selection",
    )
    parser.add_argument("--gate-jsonl", type=Path, help="Output JSONL for gate examples")
    parser.add_argument("--gate-csv", type=Path, help="Output CSV for gate examples")
    parser.add_argument("--candidate-jsonl", type=Path, help="Output JSONL for candidate examples")
    parser.add_argument("--candidate-csv", type=Path, help="Output CSV for candidate examples")
    parser.add_argument("--summary-json", type=Path, help="Optional summary JSON output")
    return parser


def main() -> int:
    parser = build_argument_parser()
    args = parser.parse_args()

    rows = load_rows(args.log_path)
    pseudo_labels = derive_pseudo_labels(
        rows,
        future_window=args.future_window,
        min_future_run_length=args.min_future_run_length,
        min_agreement_ratio=args.min_agreement_ratio,
    )
    gate_rows = build_gate_rows(pseudo_labels, only_changed=args.only_changed)
    candidate_rows = build_candidate_rows(pseudo_labels, only_changed=args.only_changed)
    summary = summarize_rows(gate_rows, candidate_rows)
    summary.update(
        {
            "log_path": str(args.log_path),
            "future_window": args.future_window,
            "min_future_run_length": args.min_future_run_length,
            "min_agreement_ratio": args.min_agreement_ratio,
            "only_changed": args.only_changed,
        }
    )

    if args.gate_jsonl:
        write_jsonl(args.gate_jsonl, gate_rows)
    if args.gate_csv:
        write_csv(args.gate_csv, gate_rows)
    if args.candidate_jsonl:
        write_jsonl(args.candidate_jsonl, candidate_rows)
    if args.candidate_csv:
        write_csv(args.candidate_csv, candidate_rows)
    if args.summary_json:
        write_json(args.summary_json, summary)

    print(f"log_path: {args.log_path}")
    print(
        "pseudo_label_source:"
        f" future_window={args.future_window}"
        f" min_future_run_length={args.min_future_run_length}"
        f" min_agreement_ratio={args.min_agreement_ratio:.2f}"
        f" only_changed={args.only_changed}"
    )
    print(
        "gate_rows:"
        f" total={summary['gate_row_count']}"
        f" positive_switch={summary['gate_switch_positive_count']}"
        f" mini_hmm_matches_pseudo={summary['gate_mini_hmm_matches_pseudo_count']}"
        f" heuristic_matches_pseudo={summary['gate_heuristic_matches_pseudo_count']}"
    )
    print(
        "candidate_rows:"
        f" total={summary['candidate_row_count']}"
        f" pseudo_positive={summary['candidate_positive_count']}"
        f" selected_positive={summary['candidate_selected_positive_count']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
