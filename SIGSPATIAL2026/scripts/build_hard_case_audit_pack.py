#!/usr/bin/env python3
"""Validate and summarize the SIGSPATIAL hard-case audit corpus."""

from __future__ import annotations

import argparse
import csv
import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Sequence


PAPER_DIR = Path(__file__).resolve().parents[1]
DEFAULT_CORPUS = PAPER_DIR / "data" / "hard_case_audit_cases.csv"
DEFAULT_OUT_DIR = PAPER_DIR / "results" / "hard_cases"
REQUIRED_COLUMNS = {
    "case_id",
    "category",
    "source_file",
    "log_name",
    "log_index",
    "fix_id",
    "lat",
    "lon",
    "candidate_label_source",
    "manual_audit_status",
}
VALID_AUDIT_STATUSES = {"needs_manual_review", "audited", "ambiguous"}


def _read_cases(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"{path} missing required columns: {sorted(missing)}")
        return list(reader)


def _validate(cases: Sequence[Dict[str, str]]) -> List[str]:
    errors: List[str] = []
    seen = set()
    for row in cases:
        case_id = row["case_id"]
        if case_id in seen:
            errors.append(f"duplicate case_id {case_id}")
        seen.add(case_id)
        for key in ("lat", "lon"):
            try:
                float(row[key])
            except ValueError:
                errors.append(f"{case_id}: invalid {key}={row[key]!r}")
        status = row.get("manual_audit_status", "")
        if status not in VALID_AUDIT_STATUSES:
            errors.append(f"{case_id}: invalid manual_audit_status {status!r}")
        if status == "audited" and not row.get("manual_correct_way_id"):
            errors.append(f"{case_id}: audited rows require manual_correct_way_id")
        if status == "audited" and not row.get("manual_evidence_note"):
            errors.append(f"{case_id}: audited rows require manual_evidence_note")
    return errors


def _write_markdown(path: Path, cases: Sequence[Dict[str, str]], errors: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    category_counts = Counter(row["category"] for row in cases)
    status_counts = Counter(row["manual_audit_status"] for row in cases)
    source_counts = Counter(row["candidate_label_source"] for row in cases)
    with path.open("w", encoding="utf-8") as f:
        f.write("# Hard-Case Audit Pack Summary\n\n")
        f.write(f"Cases: {len(cases)}\n\n")
        f.write("## Manual Audit Status\n\n")
        for key, value in sorted(status_counts.items()):
            f.write(f"- {key}: {value}\n")
        f.write("\n## Categories\n\n")
        for key, value in sorted(category_counts.items()):
            f.write(f"- {key}: {value}\n")
        f.write("\n## Candidate Label Sources\n\n")
        for key, value in sorted(source_counts.items()):
            f.write(f"- {key}: {value}\n")
        if errors:
            f.write("\n## Validation Errors\n\n")
            for error in errors:
                f.write(f"- {error}\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--corpus", type=Path, default=DEFAULT_CORPUS)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--strict", action="store_true", help="Return non-zero when validation errors are present")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    cases = _read_cases(args.corpus)
    errors = _validate(cases)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    summary = {
        "case_count": len(cases),
        "category_counts": dict(sorted(Counter(row["category"] for row in cases).items())),
        "manual_audit_status_counts": dict(sorted(Counter(row["manual_audit_status"] for row in cases).items())),
        "candidate_label_source_counts": dict(sorted(Counter(row["candidate_label_source"] for row in cases).items())),
        "validation_errors": errors,
    }
    with (args.out_dir / "hard_case_audit_summary.json").open("w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, sort_keys=True)
    _write_markdown(args.out_dir / "hard_case_audit_summary.md", cases, errors)
    print(f"Wrote hard-case audit summary to {args.out_dir}")
    if errors and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
