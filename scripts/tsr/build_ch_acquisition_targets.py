#!/usr/bin/env python3
"""Build a prioritized CH field-imagery and artwork acquisition list."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import json
from pathlib import Path
import re
from typing import Any


CH_CODE_RE = re.compile(r"^CH:(?P<code>[^\[]+)(?:\[[^]]+\])?$")


def base_code(raw: str) -> str:
    value = str(raw)
    match = CH_CODE_RE.match(value)
    return match.group("code") if match else value.removeprefix("CH:")


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--readiness", type=Path, required=True)
    parser.add_argument("--weak-labels", type=Path, action="append", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--exclude-code", action="append", default=[])
    parser.add_argument("--generated-at", default=None)
    args = parser.parse_args()

    readiness = json.loads(args.readiness.read_text(encoding="utf-8"))
    weak_labels = [row for path in args.weak_labels for row in read_jsonl(path)]
    readiness_entries = readiness["entries"]
    raw_to_base = {entry["raw"]: entry["base_code"] for entry in readiness_entries}

    accepted_counts: Counter[str] = Counter()
    accepted_raw_code_set: set[str] = set()
    for row in weak_labels:
        weak = row.get("weak_label", {})
        if not weak.get("ground_truth_substitute") or not weak.get("ch_code"):
            continue
        raw = str(weak["ch_code"])
        code = raw_to_base.get(raw, base_code(raw))
        accepted_raw_code_set.add(raw)
        accepted_counts[code] += 1

    grouped: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for entry in readiness_entries:
        grouped[entry["base_code"]].append(entry)

    artwork_codes = {
        code: entries
        for code, entries in grouped.items()
        if any(entry["status"] == "artwork_candidate" for entry in entries)
    }
    excluded_codes = set(args.exclude_code)
    targets: list[dict[str, Any]] = []
    covered_codes: list[str] = []
    excluded_targets: list[dict[str, Any]] = []
    for code, entries in sorted(artwork_codes.items()):
        accepted = accepted_counts.get(code, 0)
        artwork_statuses = sorted({entry["artwork_status"] for entry in entries})
        model_classes = sorted({entry["model_class"] for entry in entries})
        raw_codes = sorted({entry["raw"] for entry in entries})
        if code in excluded_codes:
            excluded_targets.append({
                "base_code": code,
                "raw_ch_codes": raw_codes,
                "reason": "excluded by owner decision; no cleared artwork source in current scope",
            })
            continue
        if accepted:
            covered_codes.append(code)
            continue
        if "official_archive_gap" in artwork_statuses:
            priority = 1
            status = "artwork_gap_and_no_pseudo_label"
            next_action = "clear a reproducible official or public-domain pictogram, then collect Swiss field examples"
        else:
            priority = 2
            status = "field_imagery_and_review_needed"
            next_action = "target Swiss Panoramax sequences for this class, then route-group and review candidate crops"
        targets.append({
            "priority": priority,
            "base_code": code,
            "model_classes": model_classes,
            "mapping_rows": len(entries),
            "raw_ch_codes": raw_codes,
            "artwork_statuses": artwork_statuses,
            "status": status,
            "accepted_dual_classifier_samples": 0,
            "next_action": next_action,
        })

    targets.sort(key=lambda row: (row["priority"], row["base_code"]))
    output = {
        "schema_version": 1,
        "target_list_id": "ch-panoramax-acquisition-targets-v1",
        "generated_at": args.generated_at or datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "country": "CH",
        "scope": {
            "excluded_base_codes": sorted(excluded_codes),
            "exclusion_reason": "Owner decision: leave out CH 4.88 and 4.90 because no cleared artwork source is available in the current scope.",
        },
        "sources": {
            "readiness": str(args.readiness),
            "weak_labels": [str(path) for path in args.weak_labels],
            "weak_label_policy": "Only identical DE+FR CH codes with both confidences >= 0.90 are counted; this is pseudo-label evidence, not human ground truth.",
        },
        "coverage": {
            "artwork_candidate_base_codes": len(artwork_codes),
            "excluded_artwork_base_codes": len(excluded_targets),
            "in_scope_artwork_base_codes": len(artwork_codes) - len(excluded_targets),
            "covered_by_dual_classifier_base_codes": len(covered_codes),
            "missing_pseudo_label_base_codes": len(targets),
            "artwork_gap_base_codes": sum(row["priority"] == 1 for row in targets),
            "accepted_sample_count": sum(accepted_counts.values()),
            "accepted_raw_code_count": len(accepted_raw_code_set),
            "accepted_base_code_count": len(accepted_counts),
            "covered_codes": covered_codes,
        },
        "excluded_targets": excluded_targets,
        "targets": targets,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(output, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(output["coverage"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
