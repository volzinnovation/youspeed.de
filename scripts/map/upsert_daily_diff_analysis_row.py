#!/usr/bin/env python3
"""Upsert one day into daily-diff-analysis.csv from a single diff file."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import analyze_daily_diff_impact as impact  # noqa: E402


FIELDNAMES = [
    "date",
    "diff_file",
    "ways_added",
    "ways_removed",
    "ways_modified",
    "changed_way_count",
    "maxspeed_tag_events",
    "maxspeed_tag_changes",
    "invalidated_v1_tiles",
    "invalidated_v2_tiles",
    "unresolved_bbox_way_count",
    "sql_skipped_insert_way_count",
    "v3_sql_delete_rows",
    "v3_sql_insert_rows",
    "v3_sql_total_rows",
    "v3_patch_ms",
    "v3_patch_error",
    "v4_sql_delete_rows",
    "v4_sql_insert_rows",
    "v4_sql_total_rows",
    "v4_patch_ms",
    "v4_patch_error",
]


def _read_existing_rows(csv_path: Path) -> Dict[str, dict]:
    if not csv_path.exists():
        return {}
    out: Dict[str, dict] = {}
    with csv_path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            d = row.get("date")
            if d:
                out[d] = row
    return out


def _write_rows(csv_path: Path, rows_by_date: Dict[str, dict]) -> None:
    csv_path.parent.mkdir(parents=True, exist_ok=True)
    ordered_dates = sorted(rows_by_date.keys())
    with csv_path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDNAMES)
        writer.writeheader()
        for d in ordered_dates:
            row = rows_by_date[d]
            writer.writerow({k: row.get(k, "") for k in FIELDNAMES})


def _summary(rows_by_date: Dict[str, dict], csv_path: Path, run_dir: Path) -> dict:
    ordered = [rows_by_date[k] for k in sorted(rows_by_date.keys())]
    totals = {k: 0.0 for k in FIELDNAMES if k not in {"date", "diff_file", "v3_patch_error", "v4_patch_error"}}
    for row in ordered:
        for k in totals.keys():
            try:
                totals[k] += float(row.get(k, 0) or 0)
            except Exception:
                pass
    return {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "days": len(ordered),
        "csv_path": str(csv_path),
        "run_dir": str(run_dir),
        "totals": totals,
        "latest_date": ordered[-1]["date"] if ordered else None,
        "rows": ordered,
    }


def _infer_date(diff_file: Path) -> str:
    return impact._date_key(diff_file)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Upsert one daily diff analysis row")
    parser.add_argument("--diff-file", required=True, help="Path to one daily .osc.gz diff")
    parser.add_argument("--date", help="Date key YYYY-MM-DD (default: infer from filename)")
    parser.add_argument(
        "--csv-out",
        default="mapdata/reports/deltas/daily-diff-analysis.csv",
        help="CSV path to update",
    )
    parser.add_argument(
        "--summary-json-out",
        default="mapdata/reports/deltas/daily-diff-analysis.summary.json",
        help="Summary JSON output path",
    )
    parser.add_argument(
        "--work-dir-base",
        default="mapdata/build/germany/delta_analysis",
        help="Base work dir for run-specific DB copies",
    )
    parser.add_argument("--v3-db", default="mapdata/dist-v3/germany/speeds_v3.sqlite")
    parser.add_argument("--v4-db", default="mapdata/dist-v4/germany/speeds_v4.sqlite")
    parser.add_argument("--v1-grid-scale", type=int, default=100)
    parser.add_argument("--v2-tile-size-m", type=int, default=4096)
    parser.add_argument("--v4-max-way-tiles", type=int, default=1024)
    parser.add_argument(
        "--skip-sql-simulation",
        action="store_true",
        help="Skip v3/v4 SQL timing simulation if DB artifacts are unavailable",
    )
    parser.add_argument(
        "--copy-dbs",
        action="store_true",
        default=True,
        help="Copy v3/v4 DB files into run-specific workdir before simulation (default: on)",
    )
    parser.add_argument("--no-copy-dbs", action="store_false", dest="copy_dbs")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    diff_file = Path(args.diff_file)
    if not diff_file.exists():
        print(f"Diff file missing: {diff_file}", file=sys.stderr)
        return 1
    day = args.date or _infer_date(diff_file)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_dir = Path(args.work_dir_base) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    src_v3 = Path(args.v3_db)
    src_v4 = Path(args.v4_db)
    has_v3 = src_v3.exists()
    has_v4 = src_v4.exists()
    simulate_sql = not args.skip_sql_simulation and has_v3 and has_v4

    sim_v3: Optional[Path] = None
    sim_v4: Optional[Path] = None

    conn_v3: Optional[sqlite3.Connection] = None
    conn_v4: Optional[sqlite3.Connection] = None

    if has_v3:
        if args.copy_dbs:
            sim_v3 = run_dir / "speeds_v3.sim.sqlite"
            shutil.copy2(src_v3, sim_v3)
        else:
            sim_v3 = src_v3
        conn_v3 = sqlite3.connect(str(sim_v3), isolation_level=None)
        conn_v3.row_factory = sqlite3.Row
    if has_v4:
        if args.copy_dbs:
            sim_v4 = run_dir / "speeds_v4.sim.sqlite"
            shutil.copy2(src_v4, sim_v4)
        else:
            sim_v4 = src_v4
        conn_v4 = sqlite3.connect(str(sim_v4), isolation_level=None)
        conn_v4.row_factory = sqlite3.Row

    v4_tile_size_m = args.v2_tile_size_m
    v4_max_way_tiles = args.v4_max_way_tiles
    if conn_v4 is not None:
        tile_row = conn_v4.execute("SELECT value FROM metadata WHERE key='tile_size_m' LIMIT 1").fetchone()
        max_row = conn_v4.execute("SELECT value FROM metadata WHERE key='max_way_tiles' LIMIT 1").fetchone()
        if tile_row:
            v4_tile_size_m = int(tile_row["value"])
        if max_row:
            v4_max_way_tiles = int(max_row["value"])

    parsed = impact._parse_daily_diff(diff_file)
    changed_way_ids = sorted(parsed.ops_by_way.keys())

    existing: Dict[str, sqlite3.Row] = {}
    if conn_v3 is not None:
        existing = impact._fetch_existing_rows(conn_v3, changed_way_ids)

    invalid_v1 = set()
    invalid_v2 = set()
    unresolved_bbox = 0
    inserts: List[dict] = []
    skipped_inserts = 0
    delete_ids: List[str] = []

    for way_id, op in parsed.ops_by_way.items():
        ex = existing.get(way_id)
        bbox = None
        if ex is not None:
            bbox = (
                float(ex["min_lon"]),
                float(ex["min_lat"]),
                float(ex["max_lon"]),
                float(ex["max_lat"]),
            )
        else:
            bbox = impact._bbox_from_nodes(op.node_refs, parsed.node_coords)

        if bbox is None:
            unresolved_bbox += 1
        else:
            min_lon, min_lat, max_lon, max_lat = bbox
            x0, x1, y0, y1 = impact._cell_range_for_bbox(min_lon, min_lat, max_lon, max_lat, args.v1_grid_scale)
            for x in range(x0, x1 + 1):
                for y in range(y0, y1 + 1):
                    invalid_v1.add(f"{x}:{y}")
            tx0, tx1, ty0, ty1 = impact._tile_range_for_bbox(min_lon, min_lat, max_lon, max_lat, args.v2_tile_size_m)
            for tx in range(tx0, tx1 + 1):
                for ty in range(ty0, ty1 + 1):
                    invalid_v2.add(f"{tx}/{ty}")

        if op.action in {"delete", "modify"}:
            delete_ids.append(way_id)
        if op.action in {"create", "modify"}:
            payload = impact._build_insert_payload(way_id, op, ex, parsed.node_coords)
            if payload is None:
                skipped_inserts += 1
            else:
                if op.action == "create" and ex is not None and way_id not in delete_ids:
                    skipped_inserts += 1
                else:
                    inserts.append(payload)

    v3_ms = 0.0
    v3_delete_rows = 0
    v3_insert_rows = 0
    v3_error = "sql_simulation_skipped"
    v4_ms = 0.0
    v4_delete_rows = 0
    v4_insert_rows = 0
    v4_error = "sql_simulation_skipped"

    if simulate_sql and conn_v3 is not None and conn_v4 is not None:
        v3_ms, v3_delete_rows, v3_insert_rows, v3_err = impact._simulate_v3_patch(conn_v3, delete_ids, inserts)
        v4_ms, v4_delete_rows, v4_insert_rows, v4_err = impact._simulate_v4_patch(
            conn_v4,
            delete_ids,
            inserts,
            tile_size_m=v4_tile_size_m,
            max_way_tiles=v4_max_way_tiles,
        )
        v3_error = v3_err or ""
        v4_error = v4_err or ""

    if conn_v3 is not None:
        conn_v3.close()
    if conn_v4 is not None:
        conn_v4.close()

    row = {
        "date": day,
        "diff_file": str(diff_file),
        "ways_added": parsed.ways_added,
        "ways_removed": parsed.ways_removed,
        "ways_modified": parsed.ways_modified,
        "changed_way_count": len(parsed.ops_by_way),
        "maxspeed_tag_events": parsed.maxspeed_tag_events,
        "maxspeed_tag_changes": parsed.maxspeed_tag_changes,
        "invalidated_v1_tiles": len(invalid_v1),
        "invalidated_v2_tiles": len(invalid_v2),
        "unresolved_bbox_way_count": unresolved_bbox,
        "sql_skipped_insert_way_count": skipped_inserts,
        "v3_sql_delete_rows": v3_delete_rows,
        "v3_sql_insert_rows": v3_insert_rows,
        "v3_sql_total_rows": v3_delete_rows + v3_insert_rows,
        "v3_patch_ms": round(float(v3_ms), 3),
        "v3_patch_error": v3_error,
        "v4_sql_delete_rows": v4_delete_rows,
        "v4_sql_insert_rows": v4_insert_rows,
        "v4_sql_total_rows": v4_delete_rows + v4_insert_rows,
        "v4_patch_ms": round(float(v4_ms), 3),
        "v4_patch_error": v4_error,
    }

    csv_path = Path(args.csv_out)
    rows_by_date = _read_existing_rows(csv_path)
    rows_by_date[day] = row
    _write_rows(csv_path, rows_by_date)

    summary_path = Path(args.summary_json_out)
    summary_path.parent.mkdir(parents=True, exist_ok=True)
    payload = _summary(rows_by_date, csv_path, run_dir)
    summary_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

    print(json.dumps({"updated_date": day, "csv_path": str(csv_path), "summary_path": str(summary_path)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
