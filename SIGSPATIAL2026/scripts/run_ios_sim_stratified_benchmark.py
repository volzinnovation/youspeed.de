#!/usr/bin/env python3
"""Run the SpeedDBBench stratified latency XCTest on an iOS simulator."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import statistics
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence


PAPER_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PROBES = PAPER_DIR / "data" / "stratified_probe_points.csv"
DEFAULT_OUT_DIR = PAPER_DIR / "results" / "device"
DEFAULT_V4_DB = REPO_ROOT / "mapdata" / "dist-v4" / "baden-wuerttemberg-bench" / "speeds_v4.sqlite"
DEFAULT_V3_DB = REPO_ROOT / "tmp" / "build" / "baden-wuerttemberg-bench" / "baden-wuerttemberg_speeds.sqlite"


def _write_csv(path: Path, rows: Sequence[Dict[str, Any]], fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _fmt(value: float | None, digits: int = 3) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}"


def _default_db() -> Path:
    if DEFAULT_V4_DB.exists():
        return DEFAULT_V4_DB
    return DEFAULT_V3_DB


def _extract_payload(log_text: str) -> Dict[str, Any]:
    matches = re.findall(r"STRATIFIED_BENCHMARK_JSON=(\{.*\})", log_text)
    if not matches:
        raise RuntimeError("Could not find STRATIFIED_BENCHMARK_JSON in xcodebuild output")
    return json.loads(matches[-1])


def _booted_simulator_udids() -> List[str]:
    proc = subprocess.run(
        ["xcrun", "simctl", "list", "devices", "booted", "-j"],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return []
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []
    udids: List[str] = []
    for devices in payload.get("devices", {}).values():
        for device in devices:
            udid = device.get("udid")
            if udid:
                udids.append(str(udid))
    return udids


def _destination_value(destination: str, key: str) -> str | None:
    prefix = f"{key}="
    for part in destination.split(","):
        value = part.strip()
        if value.startswith(prefix):
            return value[len(prefix):]
    return None


def _destination_simulator_udids(destination: str) -> List[str]:
    name = _destination_value(destination, "name")
    os_version = _destination_value(destination, "OS")
    proc = subprocess.run(
        ["xcrun", "simctl", "list", "devices", "-j"],
        text=True,
        capture_output=True,
        check=False,
    )
    if proc.returncode != 0:
        return []
    try:
        payload = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []
    matches: List[str] = []
    for runtime, devices in payload.get("devices", {}).items():
        if os_version and os_version.replace(".", "-") not in runtime:
            continue
        for device in devices:
            if name and device.get("name") != name:
                continue
            if device.get("isAvailable") is False:
                continue
            udid = device.get("udid")
            if udid:
                matches.append(str(udid))
    return matches


def _boot_simulators(udids: Sequence[str]) -> None:
    for udid in udids:
        subprocess.run(
            ["xcrun", "simctl", "boot", udid],
            text=True,
            capture_output=True,
            check=False,
        )
        subprocess.run(
            ["xcrun", "simctl", "bootstatus", udid, "-b"],
            text=True,
            capture_output=True,
            check=False,
        )


def _set_simulator_env(env_values: Dict[str, str], udids: Sequence[str] | None = None) -> None:
    target_udids = list(udids or _booted_simulator_udids())
    for udid in target_udids:
        for key, value in env_values.items():
            subprocess.run(
                ["xcrun", "simctl", "spawn", udid, "launchctl", "setenv", key, value],
                text=True,
                capture_output=True,
                check=False,
            )


def _raw_rows(payload: Dict[str, Any], device: str, db_path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for entry in payload.get("reports", []):
        probe = entry.get("probe", {})
        report = entry.get("report", {})
        for variant, per_mode in sorted((report.get("benchmarkMs") or {}).items()):
            for mode, timing in sorted((per_mode or {}).items()):
                rows.append(
                    {
                        "device": device,
                        "dataset_kind": payload.get("datasetKind", ""),
                        "db_path": str(db_path),
                        "db_size_bytes": report.get("dbSizeBytes", ""),
                        "has_way_tile_table": str(report.get("hasWayTileTable", "")).lower(),
                        "probe_id": probe.get("probeID", ""),
                        "stratum": probe.get("stratum", ""),
                        "region": probe.get("region", ""),
                        "lat": probe.get("lat", ""),
                        "lon": probe.get("lon", ""),
                        "variant": variant,
                        "distance_mode": mode,
                        "avg_ms": timing.get("avgMs", ""),
                        "p50_ms": timing.get("p50Ms", ""),
                        "min_ms": timing.get("minMs", ""),
                        "max_ms": timing.get("maxMs", ""),
                        "generated_at_utc": report.get("generatedAtUTC", ""),
                    }
                )
    return rows


def _summary_rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    groups: Dict[tuple[str, str], List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(str(row["variant"]), str(row["distance_mode"]))].append(row)
    out: List[Dict[str, Any]] = []
    for (variant, mode), grouped in sorted(groups.items()):
        avg_values = [float(r["avg_ms"]) for r in grouped if r.get("avg_ms") not in ("", None)]
        max_values = [float(r["max_ms"]) for r in grouped if r.get("max_ms") not in ("", None)]
        out.append(
            {
                "variant": variant,
                "distance_mode": mode,
                "probe_count": len({r["probe_id"] for r in grouped}),
                "median_avg_ms": _fmt(statistics.median(avg_values) if avg_values else None),
                "median_max_ms": _fmt(statistics.median(max_values) if max_values else None),
                "max_ms": _fmt(max(max_values) if max_values else None),
            }
        )
    return out


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=_default_db())
    parser.add_argument("--probe-csv", type=Path, default=DEFAULT_PROBES)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--destination", default="platform=iOS Simulator,name=iPhone 16")
    parser.add_argument("--region-filter", default="karlsruhe-regbez,baden-wuerttemberg-bench")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--timeout-s", type=int, default=1800)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.db.exists():
        print(f"Benchmark DB does not exist: {args.db}", file=sys.stderr)
        return 2
    if not args.probe_csv.exists():
        print(f"Probe CSV does not exist: {args.probe_csv}", file=sys.stderr)
        return 2

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = args.out_dir / f"ios_sim_xcodebuild_{stamp}.log"
    json_path = args.out_dir / f"ios_sim_stratified_latency_{stamp}.json"

    benchmark_env = {
        "SPEEDDBBENCH_DB_PATH": str(args.db.resolve()),
        "SPEEDDBBENCH_PROBE_CSV": str(args.probe_csv.resolve()),
        "SPEEDDBBENCH_DATASET_KIND": "baden_wuerttemberg_v4" if "dist-v4" in str(args.db) else "baden_wuerttemberg_s3",
        "SPEEDDBBENCH_REGION_FILTER": args.region_filter,
        "SPEEDDBBENCH_REPEATS": str(args.repeats),
        "SPEEDDBBENCH_REQUIRE_WAY_TILE": "1" if "dist-v4" in str(args.db) else "0",
    }
    simulator_udids = _destination_simulator_udids(args.destination)
    _boot_simulators(simulator_udids)
    _set_simulator_env(benchmark_env, simulator_udids)
    env = os.environ.copy()
    env.update(benchmark_env)
    cmd = [
        "xcodebuild",
        "test",
        "-project",
        "iphone/SpeedDBBench.xcodeproj",
        "-scheme",
        "SpeedDBBench",
        "-destination",
        args.destination,
        "-only-testing:SpeedDBBenchTests/SpeedDBBenchTests/testStratifiedLatencyBenchmarkFromEnvironment",
    ]
    proc = subprocess.run(
        cmd,
        cwd=str(REPO_ROOT),
        env=env,
        text=True,
        capture_output=True,
        timeout=args.timeout_s,
        check=False,
    )
    log_text = proc.stdout + "\n" + proc.stderr
    log_path.write_text(log_text, encoding="utf-8")
    if proc.returncode != 0:
        print(f"xcodebuild failed with exit {proc.returncode}; see {log_path}", file=sys.stderr)
        return proc.returncode

    payload = _extract_payload(log_text)
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    raw_rows = _raw_rows(payload, args.destination, args.db.resolve())
    summary = _summary_rows(raw_rows)
    _write_csv(
        args.out_dir / "ios_sim_stratified_latency_raw.csv",
        raw_rows,
        [
            "device",
            "dataset_kind",
            "db_path",
            "db_size_bytes",
            "has_way_tile_table",
            "probe_id",
            "stratum",
            "region",
            "lat",
            "lon",
            "variant",
            "distance_mode",
            "avg_ms",
            "p50_ms",
            "min_ms",
            "max_ms",
            "generated_at_utc",
        ],
    )
    _write_csv(
        args.out_dir / "ios_sim_stratified_latency_summary.csv",
        summary,
        ["variant", "distance_mode", "probe_count", "median_avg_ms", "median_max_ms", "max_ms"],
    )
    print(f"Wrote iOS simulator benchmark JSON to {json_path}")
    print(f"Wrote iOS simulator benchmark CSVs to {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
