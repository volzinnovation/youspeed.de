#!/usr/bin/env python3
"""Daily Geofabrik diff pipeline for CI.

Behavior:
1) Read replication server state timestamp.
2) Skip if daily-diff-analysis CSV already contains that UTC date.
3) Update local PBF with pyosmium diffs and export merged delta.
4) Store the daily delta under mapdata/reports/deltas/daily/.
5) Upsert one row into daily-diff-analysis.csv.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Optional


def _ensure_trailing_slash(url: str) -> str:
    return url if url.endswith("/") else f"{url}/"


def _set_output(name: str, value: str) -> None:
    path = os.environ.get("GITHUB_OUTPUT")
    if not path:
        return
    with open(path, "a", encoding="utf-8") as f:
        f.write(f"{name}={value}\n")


def _read_state_txt(updates_url: str) -> Dict[str, Optional[str]]:
    state_url = f"{_ensure_trailing_slash(updates_url)}state.txt"
    with urllib.request.urlopen(state_url, timeout=60) as resp:
        text = resp.read().decode("utf-8", errors="replace")

    seq = None
    ts = None
    for line in text.splitlines():
        if line.startswith("sequenceNumber="):
            seq = line.split("=", 1)[1].strip()
        elif line.startswith("timestamp="):
            ts = line.split("=", 1)[1].strip()
    return {"sequence": seq, "timestamp": ts, "state_url": state_url}


def _latest_date_in_csv(csv_path: Path) -> Optional[str]:
    if not csv_path.exists():
        return None
    latest = None
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            d = row.get("date")
            if not d:
                continue
            if latest is None or d > latest:
                latest = d
    return latest


def _download_file(url: str, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(out_path.suffix + ".tmp")
    with urllib.request.urlopen(url, timeout=600) as resp, tmp.open("wb") as out:
        shutil.copyfileobj(resp, out)
    tmp.replace(out_path)


def _is_gzip(path: Path) -> bool:
    try:
        with path.open("rb") as f:
            return f.read(2) == b"\x1f\x8b"
    except Exception:
        return False


def _normalize_delta(delta_path: Path, out_path: Path) -> Path:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if delta_path.suffix == ".gz":
        shutil.copy2(delta_path, out_path)
        return out_path
    # convert .osc -> .osc.gz
    with delta_path.open("rb") as src, gzip.open(out_path, "wb") as dst:
        shutil.copyfileobj(src, dst)
    return out_path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run daily PBF update + CSV upsert pipeline")
    parser.add_argument("--region", default="germany")
    parser.add_argument("--updates-url", default="https://download.geofabrik.de/europe/germany-updates/")
    parser.add_argument("--latest-pbf-url", default="https://download.geofabrik.de/europe/germany-latest.osm.pbf")
    parser.add_argument("--input-pbf", default="mapdata/raw/germany-latest.osm.pbf")
    parser.add_argument("--state-file", default="mapdata/raw/germany.diff_state.json")
    parser.add_argument("--report-path", default="mapdata/reports/diff_update.germany.latest.json")
    parser.add_argument("--work-dir", default="mapdata/build/germany/updates")
    parser.add_argument("--daily-dir", default="mapdata/reports/deltas/daily")
    parser.add_argument("--csv-out", default="mapdata/reports/deltas/daily-diff-analysis.csv")
    parser.add_argument("--summary-json-out", default="mapdata/reports/deltas/daily-diff-analysis.summary.json")
    parser.add_argument("--v3-db", default="mapdata/dist-v3/germany/speeds_v3.sqlite")
    parser.add_argument("--v4-db", default="mapdata/dist-v4/germany/speeds_v4.sqlite")
    parser.add_argument("--v1-grid-scale", type=int, default=100)
    parser.add_argument("--v2-tile-size-m", type=int, default=4096)
    parser.add_argument("--v4-max-way-tiles", type=int, default=1024)
    parser.add_argument("--skip-sql-if-missing", action="store_true", default=True)
    parser.add_argument("--no-skip-sql-if-missing", action="store_false", dest="skip_sql_if_missing")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    input_pbf = Path(args.input_pbf)
    state_file = Path(args.state_file)
    report_path = Path(args.report_path)
    daily_dir = Path(args.daily_dir)
    csv_out = Path(args.csv_out)

    state = _read_state_txt(args.updates_url)
    server_ts = state["timestamp"]
    if not server_ts:
        print("Missing timestamp in replication state.txt", file=sys.stderr)
        return 1
    server_date = server_ts[:10]
    latest_csv_date = _latest_date_in_csv(csv_out)

    if latest_csv_date is not None and latest_csv_date >= server_date:
        print(f"No new diff day yet (server={server_date}, csv_latest={latest_csv_date})", file=sys.stderr)
        _set_output("changed", "0")
        _set_output("reason", "already_processed")
        _set_output("server_date", server_date)
        return 0

    if not input_pbf.exists():
        print(f"Bootstrapping missing PBF from {args.latest_pbf_url}", file=sys.stderr)
        _download_file(args.latest_pbf_url, input_pbf)

    report_path.parent.mkdir(parents=True, exist_ok=True)
    Path(args.work_dir).mkdir(parents=True, exist_ok=True)
    state_file.parent.mkdir(parents=True, exist_ok=True)

    update_cmd = [
        "bash",
        "scripts/map/update_from_geofabrik_diffs.sh",
        "--region",
        args.region,
        "--input-pbf",
        str(input_pbf),
        "--updates-url",
        args.updates_url,
        "--state-file",
        str(state_file),
        "--report-path",
        str(report_path),
        "--work-dir",
        args.work_dir,
        "--emit-delta",
    ]
    print("Running incremental update script...", file=sys.stderr)
    subprocess.run(update_cmd, check=True)

    if not report_path.exists():
        print(f"Expected report missing: {report_path}", file=sys.stderr)
        return 1
    report = json.loads(report_path.read_text(encoding="utf-8"))
    delta = report.get("delta_export", {}) if isinstance(report, dict) else {}
    delta_status = delta.get("status")
    delta_path_raw = delta.get("path")
    pbf_after = report.get("pbf_after", {}) if isinstance(report, dict) else {}
    after_ts = pbf_after.get("timestamp") or server_ts
    day = str(after_ts)[:10]

    if delta_status != "exported" or not delta_path_raw:
        print(f"No delta exported (status={delta_status}); skipping CSV upsert", file=sys.stderr)
        _set_output("changed", "0")
        _set_output("reason", "no_delta")
        _set_output("server_date", server_date)
        return 0

    delta_path = Path(delta_path_raw)
    if not delta_path.exists():
        print(f"Delta path from report does not exist: {delta_path}", file=sys.stderr)
        return 1

    out_daily = daily_dir / f"{args.region}-{day}.osc.gz"
    normalized = _normalize_delta(delta_path, out_daily)
    print(f"Daily delta stored: {normalized}", file=sys.stderr)

    upsert_cmd = [
        sys.executable,
        "scripts/map/upsert_daily_diff_analysis_row.py",
        "--diff-file",
        str(normalized),
        "--date",
        day,
        "--csv-out",
        args.csv_out,
        "--summary-json-out",
        args.summary_json_out,
        "--v3-db",
        args.v3_db,
        "--v4-db",
        args.v4_db,
        "--v1-grid-scale",
        str(args.v1_grid_scale),
        "--v2-tile-size-m",
        str(args.v2_tile_size_m),
        "--v4-max-way-tiles",
        str(args.v4_max_way_tiles),
    ]
    if args.skip_sql_if_missing:
        v3_exists = Path(args.v3_db).exists()
        v4_exists = Path(args.v4_db).exists()
        if not (v3_exists and v4_exists):
            upsert_cmd.append("--skip-sql-simulation")
            print("v3/v4 DBs missing, upsert will skip SQL simulation metrics", file=sys.stderr)

    subprocess.run(upsert_cmd, check=True)

    _set_output("changed", "1")
    _set_output("reason", "updated")
    _set_output("server_date", server_date)
    _set_output("processed_date", day)
    _set_output("daily_delta", str(normalized))
    _set_output("report_path", str(report_path))
    print(f"Processed daily diff date: {day}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
