#!/usr/bin/env python3
"""Normalize update metrics across S1-S4 evidence sources for SIGSPATIAL."""

from __future__ import annotations

import argparse
import csv
import glob
import hashlib
import json
import math
import statistics
import time
import zlib
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence


PAPER_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_DAILY_CSV = REPO_ROOT / "mapdata" / "reports" / "deltas" / "daily-diff-analysis.csv"
DEFAULT_OUT_DIR = PAPER_DIR / "results" / "update_metrics"

REFERENCE_REGIONS = [
    "germany",
    "baden-wuerttemberg-bench",
    "karlsruhe-regbez",
]


SCENARIOS = [
    {
        "architecture": "S1",
        "label": "global index files",
        "unit": "invalidated index partitions",
        "touched_column": "invalidated_v1_tiles",
        "apply_ms_column": "",
        "notes": "Partition invalidation proxy; replacement bytes are a reference full-artifact replacement when a manifest is present.",
    },
    {
        "architecture": "S2",
        "label": "content-addressed tile packs",
        "unit": "invalidated tile packs",
        "touched_column": "invalidated_v2_tiles",
        "apply_ms_column": "",
        "notes": "Tile invalidation proxy; replacement bytes are estimated from the available v2 tile-pack size distribution.",
    },
    {
        "architecture": "S3",
        "label": "SQLite/RTree",
        "unit": "SQL rows touched",
        "touched_column": "v3_sql_total_rows",
        "apply_ms_column": "v3_patch_ms",
        "notes": "Host-side rollback simulation of exact SQL patch apply.",
    },
    {
        "architecture": "S4",
        "label": "SQLite/RTree plus tile prefilter",
        "unit": "SQL rows touched",
        "touched_column": "v4_sql_total_rows",
        "apply_ms_column": "v4_patch_ms",
        "notes": "Host-side rollback simulation of exact SQL patch apply.",
    },
]


def _float(row: Dict[str, str], key: str) -> Optional[float]:
    raw = row.get(key)
    if raw in (None, ""):
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _fmt(value: Optional[float], digits: int = 3) -> str:
    if value is None:
        return ""
    return f"{value:.{digits}f}"


def _median(values: Iterable[Optional[float]]) -> Optional[float]:
    clean = [v for v in values if v is not None and not math.isnan(v)]
    if not clean:
        return None
    return statistics.median(clean)


def _mean(values: Iterable[Optional[float]]) -> Optional[float]:
    clean = [v for v in values if v is not None and not math.isnan(v)]
    if not clean:
        return None
    return statistics.mean(clean)


def _read_daily(path: Path) -> List[Dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _write_csv(path: Path, rows: Sequence[Dict[str, Any]], fieldnames: Sequence[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def _rel(path: Optional[Path]) -> str:
    if path is None:
        return ""
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _manifest_artifact_total(manifest_path: Path) -> Optional[int]:
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    artifacts = payload.get("artifacts", {})
    if not isinstance(artifacts, dict):
        return None
    total = 0
    for artifact in artifacts.values():
        if isinstance(artifact, dict):
            try:
                total += int(artifact.get("bytes", 0) or 0)
            except (TypeError, ValueError):
                continue
    return total or None


def _first_existing(paths: Iterable[Path]) -> Optional[Path]:
    for path in paths:
        if path.exists():
            return path
    return None


def _reference_payloads() -> Dict[str, Dict[str, Any]]:
    s1_manifest = _first_existing(
        REPO_ROOT / "mapdata" / "dist" / region / "manifest.json"
        for region in REFERENCE_REGIONS
    )
    s1_bytes = _manifest_artifact_total(s1_manifest) if s1_manifest else None

    s2_catalog = _first_existing(
        REPO_ROOT / "mapdata" / "dist-v2" / region / "catalog.v2.json"
        for region in REFERENCE_REGIONS
    )
    s2_tile_bytes: List[float] = []
    if s2_catalog:
        try:
            payload = json.loads(s2_catalog.read_text(encoding="utf-8"))
            for tile in payload.get("tiles", []):
                if isinstance(tile, dict) and tile.get("content_bytes") not in (None, ""):
                    s2_tile_bytes.append(float(tile["content_bytes"]))
        except (OSError, json.JSONDecodeError, TypeError, ValueError):
            s2_tile_bytes = []

    references: Dict[str, Dict[str, Any]] = {
        "S1": {
            "payload_bytes_per_update": s1_bytes,
            "payload_bytes_per_touched_unit": None,
            "payload_status": "observed_reference_full_replacement" if s1_bytes else "missing_reference_manifest",
            "payload_source": _rel(s1_manifest),
        },
        "S2": {
            "payload_bytes_per_update": None,
            "payload_bytes_per_touched_unit": statistics.median(s2_tile_bytes) if s2_tile_bytes else None,
            "payload_status": "estimated_from_reference_tilepack_median" if s2_tile_bytes else "missing_reference_v2_catalog",
            "payload_source": _rel(s2_catalog),
        },
        "S3": {
            "payload_bytes_per_update": None,
            "payload_bytes_per_touched_unit": None,
            "payload_status": "sampled_sql_patch_payloads",
            "payload_source": "mapdata/bench/karlsruhe_osc/*/v3_delta_manifest.json",
        },
        "S4": {
            "payload_bytes_per_update": None,
            "payload_bytes_per_touched_unit": None,
            "payload_status": "sampled_sql_patch_payloads",
            "payload_source": "mapdata/bench/karlsruhe_osc/*/v3_delta_manifest.json",
        },
    }
    return references


def _normalized_daily_rows(
    daily_rows: Sequence[Dict[str, str]],
    references: Dict[str, Dict[str, Any]],
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for source in daily_rows:
        changed = _float(source, "changed_way_count") or 0.0
        speed_changes = _float(source, "maxspeed_tag_changes") or 0.0
        for scenario in SCENARIOS:
            touched = _float(source, scenario["touched_column"])
            apply_ms = _float(source, scenario["apply_ms_column"]) if scenario["apply_ms_column"] else None
            ref = references.get(scenario["architecture"], {})
            payload_bytes: Optional[float] = None
            payload_observed = "false"
            if ref.get("payload_bytes_per_update") is not None and touched and touched > 0:
                payload_bytes = float(ref["payload_bytes_per_update"])
                payload_observed = "reference"
            elif ref.get("payload_bytes_per_touched_unit") is not None and touched is not None:
                payload_bytes = float(ref["payload_bytes_per_touched_unit"]) * touched
                payload_observed = "estimated"
            out.append(
                {
                    "date": source["date"],
                    "architecture": scenario["architecture"],
                    "architecture_label": scenario["label"],
                    "update_unit": scenario["unit"],
                    "changed_way_count": int(changed),
                    "maxspeed_tag_changes": int(speed_changes),
                    "touched_units": "" if touched is None else int(touched),
                    "touched_units_per_1000_changed_ways": _fmt(
                        (touched / changed * 1000.0) if touched is not None and changed else None
                    ),
                    "apply_ms": _fmt(apply_ms),
                    "apply_ms_per_1000_touched_units": _fmt(
                        (apply_ms / touched * 1000.0) if apply_ms is not None and touched else None
                    ),
                    "payload_bytes": "" if payload_bytes is None else int(round(payload_bytes)),
                    "payload_mb": _fmt((payload_bytes / 1_000_000.0) if payload_bytes is not None else None, 6),
                    "payload_observed": payload_observed,
                    "payload_status": ref.get("payload_status", ""),
                    "payload_source": ref.get("payload_source", ""),
                    "source": "mapdata/reports/deltas/daily-diff-analysis.csv",
                    "notes": scenario["notes"],
                }
            )
    return out


def _summary_rows(
    normalized: Sequence[Dict[str, Any]],
    patch_rows: Sequence[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    groups: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in normalized:
        groups[row["architecture"]].append(row)
    patch_payload = [float(r["patch_bytes"]) for r in patch_rows if r.get("patch_bytes") not in (None, "")]
    patch_decompressed = [float(r["decompressed_patch_bytes"]) for r in patch_rows if r.get("decompressed_patch_bytes") not in (None, "")]
    validation_ms = [float(r["sha256_validation_ms"]) for r in patch_rows if r.get("sha256_validation_ms") not in (None, "")]
    decompression_ms = [float(r["zlib_decompression_ms"]) for r in patch_rows if r.get("zlib_decompression_ms") not in (None, "")]
    out: List[Dict[str, Any]] = []
    for architecture, rows in sorted(groups.items()):
        payload_values = [float(r["payload_bytes"]) for r in rows if r.get("payload_bytes") not in (None, "")]
        median_payload = statistics.median(payload_values) if payload_values else None
        median_patch_payload = statistics.median(patch_payload) if architecture in {"S3", "S4"} and patch_payload else None
        median_patch_decompressed = statistics.median(patch_decompressed) if architecture in {"S3", "S4"} and patch_decompressed else None
        out.append(
            {
                "architecture": architecture,
                "architecture_label": rows[0]["architecture_label"],
                "update_unit": rows[0]["update_unit"],
                "days": len(rows),
                "mean_changed_ways_per_day": _fmt(_mean(float(r["changed_way_count"]) for r in rows), 1),
                "median_changed_ways_per_day": _fmt(_median(float(r["changed_way_count"]) for r in rows), 1),
                "median_speed_tag_changes_per_day": _fmt(
                    _median(float(r["maxspeed_tag_changes"]) for r in rows), 1
                ),
                "median_touched_units_per_day": _fmt(
                    _median(float(r["touched_units"]) for r in rows if r["touched_units"] != ""), 1
                ),
                "median_touched_units_per_1000_changed_ways": _fmt(
                    _median(float(r["touched_units_per_1000_changed_ways"]) for r in rows)
                ),
                "median_apply_ms_per_day": _fmt(
                    _median(float(r["apply_ms"]) for r in rows if r["apply_ms"] != "")
                ),
                "median_apply_ms_per_1000_touched_units": _fmt(
                    _median(float(r["apply_ms_per_1000_touched_units"]) for r in rows if r["apply_ms_per_1000_touched_units"] != "")
                ),
                "median_payload_mb_per_day": _fmt((median_payload / 1_000_000.0) if median_payload is not None else None, 3),
                "median_patch_payload_kb": _fmt((median_patch_payload / 1000.0) if median_patch_payload is not None else None, 3),
                "median_decompressed_patch_kb": _fmt((median_patch_decompressed / 1000.0) if median_patch_decompressed is not None else None, 3),
                "median_validation_ms": _fmt(_median(validation_ms) if architecture in {"S3", "S4"} else None, 4),
                "median_decompression_ms": _fmt(_median(decompression_ms) if architecture in {"S3", "S4"} else None, 4),
                "payload_status": rows[0].get("payload_status", ""),
                "payload_source": rows[0].get("payload_source", ""),
                "notes": rows[0]["notes"],
            }
        )
    return out


def _patch_manifest_rows() -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    for raw_path in sorted(glob.glob(str(REPO_ROOT / "mapdata" / "bench" / "karlsruhe_osc" / "*" / "v3_delta_manifest.json"))):
        path = Path(raw_path)
        with path.open(encoding="utf-8") as f:
            payload = json.load(f)
        stats = payload.get("stats", {})
        patch = payload.get("patch", {})
        changed = stats.get("changed_way_count") or 0
        speed_events = stats.get("maxspeed_tag_events") or 0
        patch_bytes = patch.get("bytes")
        patch_path = path.parent / str(patch.get("file", "v3_patch.sql.zlib"))
        compressed = b""
        validation_ok = ""
        decompressed_bytes: Optional[int] = None
        validation_ms: Optional[float] = None
        decompression_ms: Optional[float] = None
        sql_statement_count: Optional[int] = None
        if patch_path.exists():
            compressed = patch_path.read_bytes()
            started = time.perf_counter()
            actual_sha = hashlib.sha256(compressed).hexdigest()
            validation_ms = (time.perf_counter() - started) * 1000.0
            validation_ok = str(actual_sha == patch.get("sha256")).lower()
            started = time.perf_counter()
            decompressed = zlib.decompress(compressed)
            decompression_ms = (time.perf_counter() - started) * 1000.0
            decompressed_bytes = len(decompressed)
            sql_text = decompressed.decode("utf-8", errors="replace")
            sql_statement_count = sum(1 for part in sql_text.split(";") if part.strip())
        sql_rows = sum(
            int(stats.get(k, 0) or 0)
            for k in (
                "delete_way_count",
                "insert_way_count",
                "delete_area_count",
                "insert_area_count",
                "delete_way_link_count",
                "insert_way_link_count",
            )
        )
        rows.append(
            {
                "sample": path.parent.name,
                "region": payload.get("region", ""),
                "source_diff_file": payload.get("source_diff_file", ""),
                "generation_mode": payload.get("generation_mode", ""),
                "way_links_mode": stats.get("way_links_mode", ""),
                "changed_way_count": changed,
                "maxspeed_tag_events": speed_events,
                "patch_bytes": patch_bytes,
                "patch_mb": _fmt((float(patch_bytes) / 1_000_000.0) if patch_bytes else None, 6),
                "decompressed_patch_bytes": decompressed_bytes,
                "decompressed_patch_mb": _fmt((float(decompressed_bytes) / 1_000_000.0) if decompressed_bytes else None, 6),
                "sha256_validation_ms": _fmt(validation_ms, 4),
                "sha256_validation_ok": validation_ok,
                "zlib_decompression_ms": _fmt(decompression_ms, 4),
                "sql_statement_count": sql_statement_count,
                "bytes_per_changed_way": _fmt((float(patch_bytes) / float(changed)) if patch_bytes and changed else None),
                "bytes_per_maxspeed_event": _fmt((float(patch_bytes) / float(speed_events)) if patch_bytes and speed_events else None),
                "sql_rows_in_patch_manifest": sql_rows,
            }
        )
    return rows


def _write_markdown(path: Path, summary: Sequence[Dict[str, Any]], patch_rows: Sequence[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        f.write("# Normalized Update Metrics\n\n")
        f.write("Daily rows normalize each architecture to touched units per 1,000 changed OSM ways. ")
        f.write("S1 replacement bytes use the first available region manifest as a full-replacement reference; S2 bytes use the median tile-pack size when a v2 catalog is present. ")
        f.write("S3/S4 validation and decompression timings are measured from checked-in zlib SQL patch samples.\n\n")
        f.write("| Arch. | Unit | Days | Median touched/day | Touched/1k changed | Median apply ms/day | Payload MB/day | Payload status |\n")
        f.write("| --- | --- | ---: | ---: | ---: | ---: | ---: | --- |\n")
        for row in summary:
            f.write(
                f"| {row['architecture']} | {row['update_unit']} | {row['days']} | "
                f"{row['median_touched_units_per_day']} | {row['median_touched_units_per_1000_changed_ways']} | "
                f"{row['median_apply_ms_per_day']} | {row['median_payload_mb_per_day']} | {row['payload_status']} |\n"
            )
        if patch_rows:
            f.write("\n## Karlsruhe Patch Manifest Samples\n\n")
            f.write("| Sample | Patch KB | Inflated KB | SHA-256 ms | Inflate ms | Changed ways | Way links |\n")
            f.write("| --- | ---: | ---: | ---: | ---: | ---: | --- |\n")
            for row in patch_rows:
                f.write(
                    f"| {row['sample']} | {_fmt((float(row['patch_bytes']) / 1000.0) if row.get('patch_bytes') else None, 3)} | "
                    f"{_fmt((float(row['decompressed_patch_bytes']) / 1000.0) if row.get('decompressed_patch_bytes') else None, 3)} | "
                    f"{row['sha256_validation_ms']} | {row['zlib_decompression_ms']} | "
                    f"{row['changed_way_count']} | {row['way_links_mode']} |\n"
                )


def _write_tex(path: Path, summary: Sequence[Dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    short_units = {
        "S1": "partitions",
        "S2": "tiles",
        "S3": "SQL rows",
        "S4": "SQL rows",
    }
    with path.open("w", encoding="utf-8") as f:
        f.write("% Auto-generated by scripts/normalize_update_metrics.py\n")
        f.write("\\begingroup\n")
        f.write("\\setlength{\\tabcolsep}{2.4pt}\n")
        f.write("\\begin{tabular}{llrrrrrr}\n")
        f.write("\\toprule\n")
        f.write("Arch. & Unit & Touch & /1k & Repl. MB & Patch KB & Apply & Val/decomp.\\\\\n")
        f.write("\\midrule\n")
        for row in summary:
            unit = short_units.get(str(row["architecture"]), str(row["update_unit"])).replace("_", "\\_")
            validation = row.get("median_validation_ms", "")
            decompression = row.get("median_decompression_ms", "")
            validate_decompress = f"{validation}/{decompression}" if validation or decompression else ""
            f.write(
                f"{row['architecture']} & {unit} & {row['median_touched_units_per_day']} & "
                f"{row['median_touched_units_per_1000_changed_ways']} & {row['median_payload_mb_per_day']} & "
                f"{row['median_patch_payload_kb']} & {row['median_apply_ms_per_day']} & {validate_decompress}\\\\\n"
            )
        f.write("\\bottomrule\n")
        f.write("\\end{tabular}\n")
        f.write("\\endgroup\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--daily-csv", type=Path, default=DEFAULT_DAILY_CSV)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    daily_rows = _read_daily(args.daily_csv)
    patch_rows = _patch_manifest_rows()
    references = _reference_payloads()
    normalized = _normalized_daily_rows(daily_rows, references)
    summary = _summary_rows(normalized, patch_rows)

    _write_csv(
        args.out_dir / "update_metrics_by_day.csv",
        normalized,
        [
            "date",
            "architecture",
            "architecture_label",
            "update_unit",
            "changed_way_count",
            "maxspeed_tag_changes",
            "touched_units",
            "touched_units_per_1000_changed_ways",
            "apply_ms",
            "apply_ms_per_1000_touched_units",
            "payload_bytes",
            "payload_mb",
            "payload_observed",
            "payload_status",
            "payload_source",
            "source",
            "notes",
        ],
    )
    _write_csv(
        args.out_dir / "update_metrics_summary.csv",
        summary,
        [
            "architecture",
            "architecture_label",
            "update_unit",
            "days",
            "mean_changed_ways_per_day",
            "median_changed_ways_per_day",
            "median_speed_tag_changes_per_day",
            "median_touched_units_per_day",
            "median_touched_units_per_1000_changed_ways",
            "median_apply_ms_per_day",
            "median_apply_ms_per_1000_touched_units",
            "median_payload_mb_per_day",
            "median_patch_payload_kb",
            "median_decompressed_patch_kb",
            "median_validation_ms",
            "median_decompression_ms",
            "payload_status",
            "payload_source",
            "notes",
        ],
    )
    _write_csv(
        args.out_dir / "karlsruhe_patch_manifest_samples.csv",
        patch_rows,
        [
            "sample",
            "region",
            "source_diff_file",
            "generation_mode",
            "way_links_mode",
            "changed_way_count",
            "maxspeed_tag_events",
            "patch_bytes",
            "patch_mb",
            "decompressed_patch_bytes",
            "decompressed_patch_mb",
            "sha256_validation_ms",
            "sha256_validation_ok",
            "zlib_decompression_ms",
            "sql_statement_count",
            "bytes_per_changed_way",
            "bytes_per_maxspeed_event",
            "sql_rows_in_patch_manifest",
        ],
    )
    _write_markdown(args.out_dir / "update_metrics_summary.md", summary, patch_rows)
    _write_tex(args.out_dir / "update_metrics_table.tex", summary)
    print(f"Wrote normalized update metrics to {args.out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
