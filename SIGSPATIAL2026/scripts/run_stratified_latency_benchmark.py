#!/usr/bin/env python3
"""Run a stratified latency benchmark over existing YouSpeed query artifacts.

The historical architecture benchmark used one Berlin coordinate. This runner
keeps that probe as a control point and adds a small stratified set of points
drawn from replay hard cases. It records raw query-script JSON plus normalized
summary tables for the SIGSPATIAL paper.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import subprocess
import sys
import time
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


PAPER_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROBES = PAPER_DIR / "data" / "stratified_probe_points.csv"
DEFAULT_CONFIG = PAPER_DIR / "config" / "latency_architectures.json"
DEFAULT_OUT_DIR = PAPER_DIR / "results" / "latency"


def _read_csv_dicts(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write_csv(path: Path, rows: Sequence[Dict[str, Any]], fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _load_architectures(path: Path) -> List[Dict[str, Any]]:
    with path.open(encoding="utf-8") as f:
        payload = json.load(f)
    architectures = payload.get("architectures")
    if not isinstance(architectures, list):
        raise ValueError(f"{path} must contain an architectures list")
    return architectures


def _resolve_artifact(candidates: Iterable[str]) -> Optional[Path]:
    for candidate in candidates:
        path = (REPO_ROOT / candidate).resolve()
        if path.exists():
            return path
    return None


def _as_float(value: Any) -> Optional[float]:
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _percentile(values: Sequence[float], q: float) -> Optional[float]:
    clean = sorted(v for v in values if v is not None and not math.isnan(v))
    if not clean:
        return None
    rank = max(0, min(len(clean) - 1, math.ceil(q * len(clean)) - 1))
    return clean[rank]


def _fmt(value: Optional[float], digits: int = 3) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}"


def _query_core_ms(timing: Dict[str, Any]) -> Optional[float]:
    components = [
        _as_float(timing.get("load_candidates")),
        _as_float(timing.get("city_resolve")),
        _as_float(timing.get("polyline_refine")),
        _as_float(timing.get("score_and_rank")),
    ]
    if all(v is not None for v in components):
        return float(sum(v for v in components if v is not None))
    total = _as_float(timing.get("total"))
    load_index = _as_float(timing.get("load_index")) or 0.0
    if total is not None:
        return max(0.0, total - load_index)
    return None


def _build_command(
    arch: Dict[str, Any],
    artifact: Path,
    probe: Dict[str, str],
    mode: str,
    args: argparse.Namespace,
) -> List[str]:
    script = REPO_ROOT / arch["script"]
    cmd = [
        sys.executable,
        str(script),
        arch["artifact_flag"],
        str(artifact),
        "--lat",
        probe["lat"],
        "--lon",
        probe["lon"],
        "--top-k",
        str(args.top_k),
        "--distance-mode",
        mode,
        "--polyline-top-n",
        str(args.polyline_top_n),
    ]
    if arch.get("supports_search_radius_m", True):
        cmd.extend(["--search-radius-m", str(args.search_radius_m)])
    if arch.get("supports_max_candidates", True):
        cmd.extend(["--max-candidates", str(args.max_candidates)])
    heading = _as_float(probe.get("heading"))
    if heading is not None and 0.0 <= heading <= 360.0:
        cmd.extend(["--heading", f"{heading:.6f}"])
    cmd.extend(str(x) for x in arch.get("extra_args", []))
    return cmd


def _run_once(cmd: Sequence[str], timeout_s: int) -> Tuple[Optional[Dict[str, Any]], Optional[str], float]:
    started = time.perf_counter()
    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        text=True,
        capture_output=True,
        timeout=timeout_s,
        check=False,
    )
    wall_ms = (time.perf_counter() - started) * 1000.0
    if proc.returncode != 0:
        return None, proc.stderr.strip() or f"exit {proc.returncode}", wall_ms
    try:
        return json.loads(proc.stdout), None, wall_ms
    except json.JSONDecodeError as exc:
        return None, f"could not parse JSON stdout: {exc}", wall_ms


def _summarize(raw_rows: Sequence[Dict[str, Any]], include_empty_candidate_probes: bool) -> List[Dict[str, Any]]:
    groups: Dict[Tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)
    for row in raw_rows:
        candidate_count = _as_float(row.get("candidate_way_ids"))
        if row.get("status") == "ok" and (include_empty_candidate_probes or (candidate_count is not None and candidate_count > 0)):
            groups[(row["architecture"], row["stratum"], row["distance_mode"])].append(row)

    summary: List[Dict[str, Any]] = []
    for (architecture, stratum, mode), rows in sorted(groups.items()):
        core = [_as_float(r.get("query_core_ms")) for r in rows]
        total = [_as_float(r.get("reported_total_ms")) for r in rows]
        wall = [_as_float(r.get("host_wall_ms")) for r in rows]
        candidates = [_as_float(r.get("candidate_way_ids")) for r in rows]
        scored = [_as_float(r.get("scored_rows")) for r in rows]
        core_clean = [v for v in core if v is not None]
        total_clean = [v for v in total if v is not None]
        wall_clean = [v for v in wall if v is not None]
        cand_clean = [v for v in candidates if v is not None]
        scored_clean = [v for v in scored if v is not None]
        summary.append(
            {
                "architecture": architecture,
                "architecture_label": rows[0].get("architecture_label", ""),
                "stratum": stratum,
                "distance_mode": mode,
                "n": len(rows),
                "probe_count": len({r["probe_id"] for r in rows}),
                "mean_core_ms": _fmt(statistics.mean(core_clean) if core_clean else None),
                "p50_core_ms": _fmt(statistics.median(core_clean) if core_clean else None),
                "p95_core_ms": _fmt(_percentile(core_clean, 0.95)),
                "max_core_ms": _fmt(max(core_clean) if core_clean else None),
                "mean_total_ms": _fmt(statistics.mean(total_clean) if total_clean else None),
                "p95_total_ms": _fmt(_percentile(total_clean, 0.95)),
                "mean_wall_ms": _fmt(statistics.mean(wall_clean) if wall_clean else None),
                "p95_wall_ms": _fmt(_percentile(wall_clean, 0.95)),
                "mean_candidate_way_ids": _fmt(statistics.mean(cand_clean) if cand_clean else None, 2),
                "mean_scored_rows": _fmt(statistics.mean(scored_clean) if scored_clean else None, 2),
                "artifact_path": rows[0].get("artifact_path", ""),
            }
        )
    return summary


def _write_markdown(path: Path, summary_rows: Sequence[Dict[str, Any]], excluded_empty_count: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        "architecture",
        "stratum",
        "distance_mode",
        "n",
        "p50_core_ms",
        "p95_core_ms",
        "mean_candidate_way_ids",
    ]
    with path.open("w", encoding="utf-8") as f:
        f.write("# Stratified Latency Benchmark Summary\n\n")
        f.write("`query_core_ms = load_candidates + city_resolve + polyline_refine + score_and_rank`.\n")
        f.write("Host subprocess wall time and script-reported total are retained in the CSV but should not be the primary paper metric.\n\n")
        if excluded_empty_count:
            f.write(f"Excluded {excluded_empty_count} successful query rows with zero candidates from the summary table; they remain in the raw CSV/JSONL.\n\n")
        f.write("| " + " | ".join(columns) + " |\n")
        f.write("| " + " | ".join(["---"] * len(columns)) + " |\n")
        for row in summary_rows:
            f.write("| " + " | ".join(str(row.get(c, "")) for c in columns) + " |\n")


def _write_tex(path: Path, summary_rows: Sequence[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write("% Auto-generated by scripts/run_stratified_latency_benchmark.py\n")
        f.write("\\begin{tabular}{lllrrrr}\n")
        f.write("\\toprule\n")
        f.write("Arch. & Stratum & Mode & $n$ & p50 core & p95 core & mean cand.\\\\\n")
        f.write("\\midrule\n")
        for row in summary_rows:
            stratum = str(row["stratum"]).replace("_", "\\_")
            f.write(
                f"{row['architecture']} & {stratum} & {row['distance_mode']} & "
                f"{row['n']} & {row['p50_core_ms']} & {row['p95_core_ms']} & {row['mean_candidate_way_ids']}\\\\\n"
            )
        f.write("\\bottomrule\n")
        f.write("\\end{tabular}\n")


def _mode_summary(summary_rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    groups: Dict[Tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for row in summary_rows:
        groups[(row["architecture"], row["distance_mode"])].append(row)
    out: List[Dict[str, Any]] = []
    for (architecture, mode), rows in sorted(groups.items()):
        p95_values = [float(r["p95_core_ms"]) for r in rows if r.get("p95_core_ms")]
        p50_values = [float(r["p50_core_ms"]) for r in rows if r.get("p50_core_ms")]
        candidate_values = [float(r["mean_candidate_way_ids"]) for r in rows if r.get("mean_candidate_way_ids")]
        out.append(
            {
                "architecture": architecture,
                "architecture_label": rows[0].get("architecture_label", ""),
                "distance_mode": mode,
                "strata": len(rows),
                "median_p50_core_ms": _fmt(statistics.median(p50_values) if p50_values else None),
                "median_p95_core_ms": _fmt(statistics.median(p95_values) if p95_values else None),
                "max_p95_core_ms": _fmt(max(p95_values) if p95_values else None),
                "median_candidate_way_ids": _fmt(statistics.median(candidate_values) if candidate_values else None, 1),
            }
        )
    return out


def _write_mode_tex(path: Path, mode_rows: Sequence[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write("% Auto-generated by scripts/run_stratified_latency_benchmark.py\n")
        f.write("\\begin{tabular}{llrrrr}\n")
        f.write("\\toprule\n")
        f.write("Arch. & Mode & Strata & Median p50 & Median p95 & Worst p95\\\\\n")
        f.write("\\midrule\n")
        for row in mode_rows:
            f.write(
                f"{row['architecture']} & {row['distance_mode']} & {row['strata']} & "
                f"{row['median_p50_core_ms']} & {row['median_p95_core_ms']} & {row['max_p95_core_ms']}\\\\\n"
            )
        f.write("\\bottomrule\n")
        f.write("\\end{tabular}\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--probe-csv", type=Path, default=DEFAULT_PROBES)
    parser.add_argument("--architectures-json", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--architectures", default="S1,S2,S3,S4", help="Comma-separated architecture ids")
    parser.add_argument("--strata", default="", help="Optional comma-separated stratum filter")
    parser.add_argument("--distance-modes", default="bbox,hybrid,polyline")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--warmups", type=int, default=1)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--polyline-top-n", type=int, default=250)
    parser.add_argument("--search-radius-m", type=float, default=1200.0)
    parser.add_argument("--max-candidates", type=int, default=5000)
    parser.add_argument("--timeout-s", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--include-empty-candidate-probes",
        action="store_true",
        help="Include successful zero-candidate queries in aggregate latency summaries.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    requested_arches = {x.strip() for x in args.architectures.split(",") if x.strip()}
    requested_modes = [x.strip() for x in args.distance_modes.split(",") if x.strip()]
    requested_strata = {x.strip() for x in args.strata.split(",") if x.strip()}

    probes = _read_csv_dicts(args.probe_csv)
    if requested_strata:
        probes = [p for p in probes if p.get("stratum") in requested_strata]
    architectures = [a for a in _load_architectures(args.architectures_json) if a["id"] in requested_arches]

    resolved: List[Tuple[Dict[str, Any], Optional[Path]]] = []
    skipped: List[Dict[str, str]] = []
    for arch in architectures:
        artifact = _resolve_artifact(arch.get("artifact_candidates", []))
        if artifact is None:
            skipped.append({"architecture": arch["id"], "reason": "no configured artifact exists"})
        resolved.append((arch, artifact))

    args.out_dir.mkdir(parents=True, exist_ok=True)
    raw_path = args.out_dir / "latency_raw.jsonl"
    raw_rows: List[Dict[str, Any]] = []

    with raw_path.open("w", encoding="utf-8") as raw_f:
        for arch, artifact in resolved:
            if artifact is None:
                continue
            for probe in probes:
                for mode in requested_modes:
                    cmd = _build_command(arch, artifact, probe, mode, args)
                    if args.dry_run:
                        print(" ".join(cmd))
                        continue
                    for _ in range(args.warmups):
                        _run_once(cmd, args.timeout_s)
                    for repeat in range(args.repeats):
                        payload, error, wall_ms = _run_once(cmd, args.timeout_s)
                        row: Dict[str, Any] = {
                            "architecture": arch["id"],
                            "architecture_label": arch.get("label", ""),
                            "artifact_path": str(artifact.relative_to(REPO_ROOT)),
                            "probe_id": probe["probe_id"],
                            "stratum": probe["stratum"],
                            "region": probe["region"],
                            "lat": probe["lat"],
                            "lon": probe["lon"],
                            "heading": probe.get("heading", ""),
                            "distance_mode": mode,
                            "repeat": repeat,
                            "host_wall_ms": round(wall_ms, 3),
                            "status": "error" if error else "ok",
                            "error": error or "",
                        }
                        if payload:
                            timing = payload.get("timing_ms", {})
                            summary = payload.get("summary", {})
                            row.update(
                                {
                                    "reported_total_ms": _as_float(timing.get("total")),
                                    "load_index_ms": _as_float(timing.get("load_index")),
                                    "load_candidates_ms": _as_float(timing.get("load_candidates")),
                                    "city_resolve_ms": _as_float(timing.get("city_resolve")),
                                    "polyline_refine_ms": _as_float(timing.get("polyline_refine")),
                                    "score_and_rank_ms": _as_float(timing.get("score_and_rank")),
                                    "query_core_ms": _query_core_ms(timing),
                                    "candidate_way_ids": summary.get("candidate_way_ids"),
                                    "matched_way_rows": summary.get("matched_way_rows"),
                                    "scored_rows": summary.get("scored_rows"),
                                    "effective_speed_kmh": summary.get("effective_speed_kmh"),
                                    "city_name": summary.get("city_name"),
                                }
                            )
                        raw_f.write(json.dumps(row, sort_keys=True) + "\n")
                        raw_rows.append(row)

    if args.dry_run:
        if skipped:
            print("Skipped architectures:", skipped, file=sys.stderr)
        return 0

    excluded_empty_rows = [
        r
        for r in raw_rows
        if r.get("status") == "ok" and (_as_float(r.get("candidate_way_ids")) or 0.0) <= 0.0
    ]
    summary_rows = _summarize(raw_rows, args.include_empty_candidate_probes)
    mode_summary_rows = _mode_summary(summary_rows)
    summary_fields = [
        "architecture",
        "architecture_label",
        "stratum",
        "distance_mode",
        "n",
        "probe_count",
        "mean_core_ms",
        "p50_core_ms",
        "p95_core_ms",
        "max_core_ms",
        "mean_total_ms",
        "p95_total_ms",
        "mean_wall_ms",
        "p95_wall_ms",
        "mean_candidate_way_ids",
        "mean_scored_rows",
        "artifact_path",
    ]
    raw_fields = [
        "architecture",
        "architecture_label",
        "artifact_path",
        "probe_id",
        "stratum",
        "region",
        "lat",
        "lon",
        "heading",
        "distance_mode",
        "repeat",
        "status",
        "error",
        "query_core_ms",
        "reported_total_ms",
        "host_wall_ms",
        "load_index_ms",
        "load_candidates_ms",
        "city_resolve_ms",
        "polyline_refine_ms",
        "score_and_rank_ms",
        "candidate_way_ids",
        "matched_way_rows",
        "scored_rows",
        "effective_speed_kmh",
        "city_name",
    ]
    _write_csv(args.out_dir / "latency_raw.csv", raw_rows, raw_fields)
    _write_csv(args.out_dir / "latency_summary_by_stratum.csv", summary_rows, summary_fields)
    _write_csv(
        args.out_dir / "latency_mode_summary.csv",
        mode_summary_rows,
        [
            "architecture",
            "architecture_label",
            "distance_mode",
            "strata",
            "median_p50_core_ms",
            "median_p95_core_ms",
            "max_p95_core_ms",
            "median_candidate_way_ids",
        ],
    )
    _write_csv(
        args.out_dir / "latency_excluded_empty_candidates.csv",
        excluded_empty_rows,
        raw_fields,
    )
    _write_markdown(args.out_dir / "latency_summary.md", summary_rows, 0 if args.include_empty_candidate_probes else len(excluded_empty_rows))
    _write_tex(args.out_dir / "latency_summary_table.tex", summary_rows)
    _write_mode_tex(args.out_dir / "latency_mode_summary_table.tex", mode_summary_rows)

    if skipped:
        with (args.out_dir / "skipped_architectures.json").open("w", encoding="utf-8") as f:
            json.dump(skipped, f, indent=2, sort_keys=True)
    print(f"Wrote {len(raw_rows)} raw rows and {len(summary_rows)} summary rows to {args.out_dir}")
    if skipped:
        print(f"Skipped {len(skipped)} unavailable architectures; see skipped_architectures.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
