#!/usr/bin/env python3
"""Build, stage, and run the Android stratified SQLite benchmark on an emulator."""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
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
APP_ID = "de.youspeed.android.alpha"
TEST_RUNNER = f"{APP_ID}.test/androidx.test.runner.AndroidJUnitRunner"


def _default_db() -> Path:
    if DEFAULT_V4_DB.exists():
        return DEFAULT_V4_DB
    return DEFAULT_V3_DB


def _run(cmd: Sequence[str], *, cwd: Path = REPO_ROOT, timeout_s: int = 600) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(cmd),
        cwd=str(cwd),
        text=True,
        capture_output=True,
        timeout=timeout_s,
        check=False,
    )


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


def _adb_path(explicit: str | None) -> str:
    if explicit:
        return explicit
    sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if sdk:
        candidate = Path(sdk) / "platform-tools" / "adb"
        if candidate.exists():
            return str(candidate)
    candidate = Path.home() / "Library" / "Android" / "sdk" / "platform-tools" / "adb"
    if candidate.exists():
        return str(candidate)
    return shutil.which("adb") or "adb"


def _emulator_path(explicit: str | None) -> str:
    if explicit:
        return explicit
    sdk = os.environ.get("ANDROID_HOME") or os.environ.get("ANDROID_SDK_ROOT")
    if sdk:
        candidate = Path(sdk) / "emulator" / "emulator"
        if candidate.exists():
            return str(candidate)
    candidate = Path.home() / "Library" / "Android" / "sdk" / "emulator" / "emulator"
    if candidate.exists():
        return str(candidate)
    return shutil.which("emulator") or "emulator"


def _connected_device(adb: str) -> bool:
    proc = _run([adb, "devices"], timeout_s=30)
    return any(line.strip().endswith("\tdevice") for line in proc.stdout.splitlines()[1:])


def _start_emulator(adb: str, emulator: str, avd: str, timeout_s: int) -> subprocess.Popen[str] | None:
    if _connected_device(adb):
        return None
    proc = subprocess.Popen(
        [emulator, "-avd", avd, "-no-snapshot-save", "-no-boot-anim"],
        cwd=str(REPO_ROOT),
        text=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + timeout_s
    while time.time() < deadline:
        if _connected_device(adb):
            booted = _run([adb, "shell", "getprop", "sys.boot_completed"], timeout_s=30)
            if booted.stdout.strip() == "1":
                return proc
        time.sleep(5)
    raise RuntimeError(f"Timed out waiting for Android emulator {avd}")


def _extract_payload(text: str) -> Dict[str, Any]:
    matches = re.findall(r"ANDROID_STRATIFIED_BENCHMARK_JSON=(\{.*\})", text)
    if not matches:
        raise RuntimeError("Could not find ANDROID_STRATIFIED_BENCHMARK_JSON in instrumentation output")
    return json.loads(matches[-1])


def _read_result_file(adb: str) -> Dict[str, Any]:
    proc = _run(
        [adb, "shell", "run-as", APP_ID, "cat", "files/benchmark/stratified_latency_result.json"],
        timeout_s=60,
    )
    if proc.returncode != 0:
        raise RuntimeError("Could not read Android benchmark result file")
    return json.loads(proc.stdout)


def _summary_rows(rows: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    groups: Dict[tuple[str, str, str], List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(str(row["variant"]), str(row.get("effective_variant", "")), str(row["distance_mode"]))].append(row)
    out: List[Dict[str, Any]] = []
    for (variant, effective_variant, mode), grouped in sorted(groups.items()):
        avg_values = [float(r["avg_ms"]) for r in grouped if r.get("avg_ms") not in ("", None)]
        max_values = [float(r["max_ms"]) for r in grouped if r.get("max_ms") not in ("", None)]
        out.append(
            {
                "variant": variant,
                "effective_variant": effective_variant,
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
    parser.add_argument("--avd", default="Pixel_API_36")
    parser.add_argument("--adb")
    parser.add_argument("--emulator")
    parser.add_argument("--region-filter", default="karlsruhe-regbez,baden-wuerttemberg-bench")
    parser.add_argument("--repeats", type=int, default=5)
    parser.add_argument("--skip-build", action="store_true")
    parser.add_argument("--emulator-timeout-s", type=int, default=300)
    parser.add_argument("--instrumentation-timeout-s", type=int, default=1800)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if not args.db.exists():
        print(f"Benchmark DB does not exist: {args.db}", file=sys.stderr)
        return 2
    if not args.probe_csv.exists():
        print(f"Probe CSV does not exist: {args.probe_csv}", file=sys.stderr)
        return 2

    adb = _adb_path(args.adb)
    emulator = _emulator_path(args.emulator)
    started_emulator = _start_emulator(adb, emulator, args.avd, args.emulator_timeout_s)

    if not args.skip_build:
        gradle = _run(["./gradlew", ":app:assembleDebug", ":app:assembleDebugAndroidTest"], cwd=REPO_ROOT / "android", timeout_s=1200)
        if gradle.returncode != 0:
            print(gradle.stdout + gradle.stderr, file=sys.stderr)
            return gradle.returncode

    app_apk = REPO_ROOT / "android" / "app" / "build" / "outputs" / "apk" / "debug" / "app-debug.apk"
    test_apk = REPO_ROOT / "android" / "app" / "build" / "outputs" / "apk" / "androidTest" / "debug" / "app-debug-androidTest.apk"
    for apk in (app_apk, test_apk):
        install = _run([adb, "install", "-r", str(apk)], timeout_s=300)
        if install.returncode != 0:
            print(install.stdout + install.stderr, file=sys.stderr)
            return install.returncode

    remote_root = "/data/local/tmp/youspeed_bench"
    for cmd in (
        [adb, "shell", "mkdir", "-p", remote_root],
        [adb, "push", str(args.db), f"{remote_root}/speeds.sqlite"],
        [adb, "push", str(args.probe_csv), f"{remote_root}/stratified_probe_points.csv"],
        [adb, "shell", "chmod", "644", f"{remote_root}/speeds.sqlite", f"{remote_root}/stratified_probe_points.csv"],
        [adb, "shell", "run-as", APP_ID, "mkdir", "-p", "files/benchmark"],
        [adb, "shell", "run-as", APP_ID, "cp", f"{remote_root}/speeds.sqlite", "files/benchmark/speeds.sqlite"],
        [adb, "shell", "run-as", APP_ID, "cp", f"{remote_root}/stratified_probe_points.csv", "files/benchmark/stratified_probe_points.csv"],
    ):
        proc = _run(cmd, timeout_s=900)
        if proc.returncode != 0:
            print(proc.stdout + proc.stderr, file=sys.stderr)
            return proc.returncode

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    log_path = args.out_dir / f"android_emulator_instrumentation_{stamp}.log"
    instrument = _run(
        [
            adb,
            "shell",
            "am",
            "instrument",
            "-w",
            "-e",
            "class",
            "de.youspeed.android.alpha.StratifiedSQLiteBenchmarkInstrumentedTest",
            "-e",
            "benchmark_repeats",
            str(args.repeats),
            "-e",
            "benchmark_region_filter",
            args.region_filter,
            "-e",
            "benchmark_dataset_kind",
            "baden_wuerttemberg_v4" if "dist-v4" in str(args.db) else "baden_wuerttemberg_s3",
            TEST_RUNNER,
        ],
        timeout_s=args.instrumentation_timeout_s,
    )
    log_text = instrument.stdout + "\n" + instrument.stderr
    log_path.write_text(log_text, encoding="utf-8")
    if instrument.returncode != 0:
        print(f"Android instrumentation failed with exit {instrument.returncode}; see {log_path}", file=sys.stderr)
        return instrument.returncode

    try:
        payload = _extract_payload(log_text)
    except RuntimeError:
        payload = _read_result_file(adb)
    json_path = args.out_dir / f"android_emulator_stratified_latency_{stamp}.json"
    json_path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    raw_rows = [dict(row) for row in payload.get("rows", [])]
    for row in raw_rows:
        row["device"] = args.avd if started_emulator is not None else "connected_android_device"
        row["dataset_kind"] = payload.get("dataset_kind", "")
        row["db_size_bytes"] = payload.get("db_size_bytes", "")
        row["has_way_tile_table"] = str(payload.get("has_way_tile_table", "")).lower()
        row["has_ways_rtree_table"] = str(payload.get("has_ways_rtree_table", "")).lower()
    _write_csv(
        args.out_dir / "android_emulator_stratified_latency_raw.csv",
        raw_rows,
        [
            "device",
            "dataset_kind",
            "db_size_bytes",
            "has_way_tile_table",
            "has_ways_rtree_table",
            "probe_id",
            "stratum",
            "region",
            "variant",
            "effective_variant",
            "distance_mode",
            "avg_ms",
            "p50_ms",
            "min_ms",
            "max_ms",
        ],
    )
    _write_csv(
        args.out_dir / "android_emulator_stratified_latency_summary.csv",
        _summary_rows(raw_rows),
        ["variant", "effective_variant", "distance_mode", "probe_count", "median_avg_ms", "median_max_ms", "max_ms"],
    )
    print(f"Wrote Android emulator benchmark JSON to {json_path}")
    print(f"Wrote Android emulator benchmark CSVs to {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
