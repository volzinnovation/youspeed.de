#!/usr/bin/env python3
"""Create compact evidence figures for the SIGSPATIAL draft."""

from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path
from typing import Dict, List

import matplotlib.pyplot as plt


PAPER_DIR = Path(__file__).resolve().parents[1]
FIGURE_DIR = PAPER_DIR / "figures"


def _read_csv(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def plot_latency() -> None:
    rows = _read_csv(PAPER_DIR / "results" / "latency" / "latency_mode_summary.csv")
    modes = ["bbox", "hybrid", "polyline"]
    architectures = ["S1", "S3"]
    values = {
        (row["architecture"], row["distance_mode"]): float(row["median_p95_core_ms"])
        for row in rows
    }

    fig, ax = plt.subplots(figsize=(6.6, 2.6))
    x = range(len(modes))
    width = 0.34
    colors = {"S1": "#8a8f98", "S3": "#2f6f73"}
    for offset, arch in [(-width / 2, "S1"), (width / 2, "S3")]:
        ys = [values.get((arch, mode), 0.0) for mode in modes]
        ax.bar([i + offset for i in x], ys, width=width, label=arch, color=colors[arch])
    ax.set_xticks(list(x), modes)
    ax.set_ylabel("Median p95 query core (ms)")
    ax.set_xlabel("Distance mode")
    ax.grid(axis="y", color="#d9d9d9", linewidth=0.6)
    ax.set_axisbelow(True)
    ax.legend(frameon=False, ncols=2, loc="upper left")
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURE_DIR / "stratified_latency_p95.pdf", bbox_inches="tight")
    plt.close(fig)


def plot_update() -> None:
    rows = _read_csv(PAPER_DIR / "results" / "update_metrics" / "update_metrics_summary.csv")
    arch = [row["architecture"] for row in rows]
    touched = [float(row["median_touched_units_per_1000_changed_ways"]) for row in rows]
    apply_ms = [float(row["median_apply_ms_per_day"] or 0.0) for row in rows]

    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(6.6, 2.6))
    colors = ["#8a8f98", "#6f9aa3", "#2f6f73", "#b06a4a"]
    ax1.bar(arch, touched, color=colors)
    ax1.set_ylabel("Touched units / 1k changed ways")
    ax1.grid(axis="y", color="#d9d9d9", linewidth=0.6)
    ax1.set_axisbelow(True)
    ax2.bar(arch, apply_ms, color=colors)
    ax2.set_ylabel("Median apply ms/day")
    ax2.grid(axis="y", color="#d9d9d9", linewidth=0.6)
    ax2.set_axisbelow(True)
    for ax in (ax1, ax2):
        ax.spines["top"].set_visible(False)
        ax.spines["right"].set_visible(False)
    fig.tight_layout()
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURE_DIR / "update_metrics_summary.pdf", bbox_inches="tight")
    plt.close(fig)


def plot_hardcase_agreement() -> None:
    rows = []
    with (PAPER_DIR / "results" / "hard_cases" / "hard_case_candidate_context.jsonl").open(encoding="utf-8") as f:
        for line in f:
            rows.append(json.loads(line))

    counts = Counter()
    for row in rows:
        case = row["case"]
        query = row.get("query") or {}
        top = (query.get("top_candidates") or [{}])[0]
        top_way = str(top.get("way_id") or "")
        matched = False
        for label, key in [
            ("live", "live_way_id"),
            ("pseudo", "pseudo_label_way_id"),
            ("oracle", "oracle_way_id"),
        ]:
            if top_way and top_way == str(case.get(key) or ""):
                counts[label] += 1
                matched = True
        if not matched:
            counts["none"] += 1

    labels = ["live", "pseudo", "oracle", "none"]
    fig, ax = plt.subplots(figsize=(4.9, 2.4))
    ax.bar(labels, [counts[label] for label in labels], color=["#2f6f73", "#6f9aa3", "#b06a4a", "#8a8f98"])
    ax.set_ylabel("Seed cases")
    ax.set_xlabel("S3 top-candidate agreement")
    ax.set_ylim(0, max(counts.values() or [1]) + 1)
    ax.grid(axis="y", color="#d9d9d9", linewidth=0.6)
    ax.set_axisbelow(True)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    fig.tight_layout()
    FIGURE_DIR.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIGURE_DIR / "hardcase_top_candidate_agreement.pdf", bbox_inches="tight")
    plt.close(fig)


def main() -> int:
    plot_latency()
    plot_update()
    plot_hardcase_agreement()
    print(f"Wrote figures to {FIGURE_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
