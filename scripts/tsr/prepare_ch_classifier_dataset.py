#!/usr/bin/env python3
"""Materialize accepted CH pseudo-label crops into a route-aware classifier set."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re
import shutil
from typing import Any


def read_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def safe_label(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.:-]+", "_", value)


def split_for_group(collection: str, candidate_id: str) -> str:
    digest = hashlib.sha256(f"{collection}\0{candidate_id}".encode()).digest()
    return "val" if digest[0] < 51 else "train"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, action="append", required=True, help="Run roots containing weak-labels-lowconf.jsonl")
    parser.add_argument("--mapping", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--min-detector-confidence", type=float, default=0.0)
    args = parser.parse_args()

    mapping = json.loads(args.mapping.read_text(encoding="utf-8"))
    raw_to_label = {
        entry["country_codes"]["CH"]["raw"]: entry["model_class_label"]
        for entry in mapping["entries"]
        if entry.get("country_codes", {}).get("CH", {}).get("raw")
    }
    rows: list[dict[str, Any]] = []
    for run in args.run:
        ledger = run / "weak-labels-lowconf.jsonl"
        for row in read_jsonl(ledger):
            weak = row.get("weak_label", {})
            raw_code = weak.get("ch_code")
            if not weak.get("ground_truth_substitute") or raw_code not in raw_to_label:
                continue
            detector_confidence = float(row.get("detector", {}).get("confidence", 0.0) or 0.0)
            if detector_confidence < args.min_detector_confidence:
                continue
            source_crop = run / row["crop_path"]
            if not source_crop.is_file():
                continue
            rows.append({
                "candidate_id": row["candidate_id"],
                "collection": row.get("collection", ""),
                "raw_ch_code": raw_code,
                "label": raw_to_label[raw_code],
                "source_crop": source_crop,
                "source_run": str(run),
                "source_item_url": row.get("source_item_url"),
                "license": row.get("license"),
            })

    args.output.mkdir(parents=True, exist_ok=True)
    for row in rows:
        split = split_for_group(row["collection"], row["candidate_id"])
        destination = args.output / split / safe_label(row["label"]) / f"{row['candidate_id']}.jpg"
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(row["source_crop"], destination)
        row["split"] = split
        row["destination"] = str(destination.relative_to(args.output))
        row["source_crop"] = str(row["source_crop"])

    labels = sorted({row["label"] for row in rows})
    summary = {
        "schema_version": 1,
        "dataset_id": "ch-panoramax-dual-classifier-bootstrap-v1",
        "policy": "Only DE+FR identical CH predictions at confidence >= 0.90; pseudo-ground truth, not human ground truth or an independent holdout.",
        "min_detector_confidence": args.min_detector_confidence,
        "source_runs": [str(run) for run in args.run],
        "accepted_samples": len(rows),
        "labels": labels,
        "label_count": len(labels),
        "split_counts": dict(Counter(row["split"] for row in rows)),
        "class_counts": dict(sorted(Counter(row["label"] for row in rows).items())),
        "group_counts": {
            split: len({row["collection"] for row in rows if row["split"] == split})
            for split in ("train", "val")
        },
        "license_counts": dict(Counter(row["license"] for row in rows)),
        "rows": [{key: value for key, value in row.items() if key != "source_crop"} for row in rows],
    }
    (args.output / "dataset-summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")
    print(json.dumps({key: summary[key] for key in ("accepted_samples", "label_count", "split_counts", "group_counts")}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
