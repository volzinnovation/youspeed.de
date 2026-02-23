#!/usr/bin/env python3
"""Plot daily diff analysis chart from CSV.

Chart:
- x-axis: date
- y-axis lines: ways added, ways removed, maxspeed tag changes
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
from pathlib import Path
from typing import List, Sequence, Tuple


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plot daily diff analysis CSV to PNG")
    parser.add_argument(
        "--csv",
        default="mapdata/reports/deltas/daily_diff_analysis.csv",
        help="Input CSV path from analyze_daily_diff_impact.py",
    )
    parser.add_argument(
        "--out",
        default="mapdata/reports/deltas/daily_diff_analysis.svg",
        help="Output chart path (PNG with matplotlib, otherwise SVG fallback)",
    )
    parser.add_argument("--title", default="Daily OSM Diff Impact (Germany)", help="Chart title")
    return parser.parse_args()


def _render_svg_line_chart(
    out_path: Path,
    dates: Sequence[dt.date],
    ways_added: Sequence[int],
    ways_removed: Sequence[int],
    tag_changes: Sequence[int],
    title: str,
) -> None:
    width = 1400
    height = 640
    margin_left = 90
    margin_right = 30
    margin_top = 70
    margin_bottom = 120
    plot_w = width - margin_left - margin_right
    plot_h = height - margin_top - margin_bottom

    series: List[Tuple[str, Sequence[int], str]] = [
        ("Ways Added", ways_added, "#1b9e77"),
        ("Ways Removed", ways_removed, "#d95f02"),
        ("Maxspeed Tag Changes", tag_changes, "#7570b3"),
    ]

    n = len(dates)
    y_max = max(1, max(max(v) for _, v, _ in series))
    y_max = int(y_max * 1.1) + 1

    def x_pos(i: int) -> float:
        if n == 1:
            return margin_left + plot_w / 2.0
        return margin_left + (i / (n - 1)) * plot_w

    def y_pos(v: int) -> float:
        return margin_top + plot_h - (v / y_max) * plot_h

    lines = []
    lines.append(
        f"<svg xmlns='http://www.w3.org/2000/svg' width='{width}' height='{height}' "
        f"viewBox='0 0 {width} {height}'>"
    )
    lines.append("<rect x='0' y='0' width='100%' height='100%' fill='white'/>")
    lines.append(
        f"<text x='{width/2:.1f}' y='36' text-anchor='middle' font-family='Arial, sans-serif' "
        f"font-size='24' fill='#222'>{title}</text>"
    )

    # Axes
    lines.append(
        f"<line x1='{margin_left}' y1='{margin_top + plot_h}' x2='{margin_left + plot_w}' "
        f"y2='{margin_top + plot_h}' stroke='#333' stroke-width='1.5'/>"
    )
    lines.append(
        f"<line x1='{margin_left}' y1='{margin_top}' x2='{margin_left}' y2='{margin_top + plot_h}' "
        f"stroke='#333' stroke-width='1.5'/>"
    )

    # Y grid + labels
    y_ticks = 6
    for t in range(y_ticks + 1):
        val = int(round((y_max * t) / y_ticks))
        y = y_pos(val)
        lines.append(
            f"<line x1='{margin_left}' y1='{y:.2f}' x2='{margin_left + plot_w}' y2='{y:.2f}' "
            f"stroke='#ddd' stroke-width='1'/>"
        )
        lines.append(
            f"<text x='{margin_left - 12}' y='{y + 5:.2f}' text-anchor='end' "
            f"font-family='Arial, sans-serif' font-size='12' fill='#444'>{val}</text>"
        )

    # X labels (limit to <=10 ticks to keep readable)
    step = max(1, n // 10)
    for i in range(0, n, step):
        x = x_pos(i)
        label = dates[i].isoformat()
        lines.append(
            f"<line x1='{x:.2f}' y1='{margin_top + plot_h}' x2='{x:.2f}' y2='{margin_top + plot_h + 6}' "
            f"stroke='#333' stroke-width='1'/>"
        )
        lines.append(
            f"<text x='{x:.2f}' y='{margin_top + plot_h + 24}' text-anchor='end' "
            f"transform='rotate(-35 {x:.2f} {margin_top + plot_h + 24})' "
            f"font-family='Arial, sans-serif' font-size='11' fill='#444'>{label}</text>"
        )

    # Data lines
    for label, values, color in series:
        pts = " ".join(f"{x_pos(i):.2f},{y_pos(v):.2f}" for i, v in enumerate(values))
        lines.append(f"<polyline fill='none' stroke='{color}' stroke-width='2.5' points='{pts}'/>")

    # Axis labels
    lines.append(
        f"<text x='{width/2:.1f}' y='{height - 18}' text-anchor='middle' "
        f"font-family='Arial, sans-serif' font-size='14' fill='#222'>Date (UTC)</text>"
    )
    lines.append(
        f"<text x='24' y='{margin_top + plot_h/2:.1f}' text-anchor='middle' "
        f"transform='rotate(-90 24 {margin_top + plot_h/2:.1f})' "
        f"font-family='Arial, sans-serif' font-size='14' fill='#222'>Count per Daily Diff</text>"
    )

    # Legend
    legend_x = margin_left + 8
    legend_y = margin_top + 8
    for i, (label, _, color) in enumerate(series):
        y = legend_y + i * 24
        lines.append(f"<rect x='{legend_x}' y='{y}' width='14' height='14' fill='{color}'/>")
        lines.append(
            f"<text x='{legend_x + 22}' y='{y + 12}' font-family='Arial, sans-serif' "
            f"font-size='13' fill='#222'>{label}</text>"
        )

    lines.append("</svg>")
    out_path.write_text("\n".join(lines), encoding="utf-8")


def main() -> int:
    args = parse_args()
    csv_path = Path(args.csv)
    if not csv_path.exists():
        raise SystemExit(f"CSV not found: {csv_path}")

    dates = []
    ways_added = []
    ways_removed = []
    tag_changes = []

    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            dates.append(dt.datetime.strptime(row["date"], "%Y-%m-%d").date())
            ways_added.append(int(row["ways_added"]))
            ways_removed.append(int(row["ways_removed"]))
            tag_changes.append(int(row["maxspeed_tag_changes"]))

    if not dates:
        raise SystemExit("CSV has no rows")

    try:
        import matplotlib

        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        import matplotlib.dates as mdates
        has_matplotlib = True
    except Exception:
        has_matplotlib = False

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    if has_matplotlib:
        fig, ax = plt.subplots(figsize=(13, 5.5), dpi=140)
        ax.plot(dates, ways_added, label="Ways Added", linewidth=2.0, color="#1b9e77")
        ax.plot(dates, ways_removed, label="Ways Removed", linewidth=2.0, color="#d95f02")
        ax.plot(dates, tag_changes, label="Maxspeed Tag Changes", linewidth=2.0, color="#7570b3")

        ax.set_title(args.title)
        ax.set_xlabel("Date (UTC)")
        ax.set_ylabel("Count per Daily Diff")
        ax.grid(True, alpha=0.25)
        ax.legend(loc="upper left")

        ax.xaxis.set_major_formatter(mdates.DateFormatter("%Y-%m-%d"))
        fig.autofmt_xdate(rotation=35, ha="right")
        fig.tight_layout()
        fig.savefig(out_path, bbox_inches="tight")
        print(f"Wrote chart (matplotlib): {out_path}")
    else:
        if out_path.suffix.lower() != ".svg":
            out_path = out_path.with_suffix(".svg")
        _render_svg_line_chart(out_path, dates, ways_added, ways_removed, tag_changes, args.title)
        print(f"Wrote chart (SVG fallback): {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
