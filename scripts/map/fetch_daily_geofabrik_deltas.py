#!/usr/bin/env python3
"""Fetch one Geofabrik replication diff per UTC day for a historical window.

Default behavior:
- infer first dataset date from earliest archived Germany PBF snapshot
- fetch 30 full UTC days before that date
- write daily .osc.gz files under mapdata/reports/deltas/daily
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import List, Optional

DEFAULT_UPDATES_URL = "https://download.geofabrik.de/europe/germany-updates/"
STAMP_RE = re.compile(r"(?P<stamp>\d{8}T\d{6}Z)")


@dataclass
class FetchResult:
    day: date
    start_utc: str
    end_utc: str
    path: str
    status: str
    size_bytes: int
    stdout: str
    stderr: str
    returncode: int


def _ensure_trailing_slash(url: str) -> str:
    if url.endswith("/"):
        return url
    return f"{url}/"


def _extract_dt_from_name(name: str) -> Optional[datetime]:
    m = STAMP_RE.search(name)
    if not m:
        return None
    return datetime.strptime(m.group("stamp"), "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def _read_pbf_header_timestamp(path: Path) -> Optional[datetime]:
    try:
        import osmium  # type: ignore
    except Exception:
        return None
    try:
        reader = osmium.io.Reader(str(path))
        header = reader.header()
        reader.close()
        raw = header.get("osmosis_replication_timestamp")
        if not raw:
            return None
        # Example: 2026-02-21T21:21:20Z
        if raw.endswith("Z"):
            return datetime.strptime(raw, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return datetime.fromisoformat(raw).astimezone(timezone.utc)
    except Exception:
        return None


def _infer_first_dataset_pbf(raw_archive_dir: Path) -> Path:
    candidates = sorted(raw_archive_dir.glob("*.osm.pbf"))
    if not candidates:
        raise FileNotFoundError(f"No .osm.pbf files found in archive dir: {raw_archive_dir}")

    by_stamp = []
    for p in candidates:
        dt = _extract_dt_from_name(p.name)
        if dt is not None:
            by_stamp.append((dt, p))
    if by_stamp:
        by_stamp.sort(key=lambda row: row[0])
        return by_stamp[0][1]

    # Fallback: oldest mtime
    return min(candidates, key=lambda p: p.stat().st_mtime)


def _first_dataset_dt(pbf_path: Path) -> datetime:
    dt = _extract_dt_from_name(pbf_path.name)
    if dt is not None:
        return dt
    header_dt = _read_pbf_header_timestamp(pbf_path)
    if header_dt is not None:
        return header_dt
    return datetime.fromtimestamp(pbf_path.stat().st_mtime, tz=timezone.utc)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Fetch daily Geofabrik replication diffs (.osc.gz)")
    parser.add_argument("--region", default="germany", help="Region label used in output filenames")
    parser.add_argument("--updates-url", default=DEFAULT_UPDATES_URL, help="Replication server base URL")
    parser.add_argument(
        "--first-dataset-pbf",
        help="Path to first dataset snapshot PBF; if omitted, inferred from --archive-dir",
    )
    parser.add_argument(
        "--archive-dir",
        default="mapdata/raw/archive",
        help="Directory with archived snapshot PBF files for inference",
    )
    parser.add_argument(
        "--days-prior",
        type=int,
        default=30,
        help="Number of full UTC days before first dataset date to fetch (default: 30)",
    )
    parser.add_argument(
        "--out-dir",
        default="mapdata/reports/deltas/daily",
        help="Output directory for daily .osc.gz files",
    )
    parser.add_argument("--size-mb", type=int, default=4096, help="Max diff payload size per request")
    parser.add_argument("--socket-timeout", type=int, default=180, help="Download timeout in seconds")
    parser.add_argument("--overwrite", action="store_true", help="Re-fetch files even if they already exist")
    parser.add_argument("--dry-run", action="store_true", help="Print planned range and exit")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.days_prior < 1:
        print("--days-prior must be >= 1", file=sys.stderr)
        return 1
    if args.size_mb < 1:
        print("--size-mb must be >= 1", file=sys.stderr)
        return 1

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    updates_url = _ensure_trailing_slash(args.updates_url.strip())

    if args.first_dataset_pbf:
        first_pbf = Path(args.first_dataset_pbf)
    else:
        first_pbf = _infer_first_dataset_pbf(Path(args.archive_dir))
    if not first_pbf.exists():
        print(f"First dataset PBF not found: {first_pbf}", file=sys.stderr)
        return 1

    first_dt = _first_dataset_dt(first_pbf)
    first_day = first_dt.date()
    start_day = first_day - timedelta(days=args.days_prior)
    end_day = first_day

    print(
        f"First dataset: {first_pbf} @ {first_dt.strftime('%Y-%m-%dT%H:%M:%SZ')}\n"
        f"Fetch window: {start_day.isoformat()} .. {end_day.isoformat()} (exclusive end), "
        f"{args.days_prior} day(s)",
        file=sys.stderr,
    )

    if args.dry_run:
        return 0

    results: List[FetchResult] = []
    ok = 0
    skipped = 0
    failed = 0

    day = start_day
    while day < end_day:
        next_day = day + timedelta(days=1)
        start_iso = f"{day.isoformat()}T00:00:00Z"
        end_iso = f"{next_day.isoformat()}T00:00:00Z"
        out_path = out_dir / f"{args.region}-{day.isoformat()}.osc.gz"

        if out_path.exists() and not args.overwrite:
            size = out_path.stat().st_size
            results.append(
                FetchResult(
                    day=day,
                    start_utc=start_iso,
                    end_utc=end_iso,
                    path=str(out_path),
                    status="skipped_exists",
                    size_bytes=size,
                    stdout="",
                    stderr="",
                    returncode=0,
                )
            )
            skipped += 1
            day = next_day
            continue

        cmd = [
            "pyosmium-get-changes",
            "--server",
            updates_url,
            "--start-date",
            start_iso,
            "--end-date",
            end_iso,
            "--size",
            str(args.size_mb),
            "--socket-timeout",
            str(args.socket_timeout),
            "--outfile",
            str(out_path),
        ]

        proc = subprocess.run(cmd, text=True, capture_output=True)
        status = "ok" if proc.returncode == 0 and out_path.exists() else "error"
        size = out_path.stat().st_size if out_path.exists() else 0

        if status == "ok":
            ok += 1
        else:
            failed += 1
            if out_path.exists() and size == 0:
                out_path.unlink(missing_ok=True)

        results.append(
            FetchResult(
                day=day,
                start_utc=start_iso,
                end_utc=end_iso,
                path=str(out_path),
                status=status,
                size_bytes=size,
                stdout=proc.stdout.strip(),
                stderr=proc.stderr.strip(),
                returncode=proc.returncode,
            )
        )

        print(f"{day.isoformat()} -> {status} ({size} bytes)", file=sys.stderr)
        day = next_day

    manifest = {
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "region": args.region,
        "updates_url": updates_url,
        "first_dataset_pbf": str(first_pbf),
        "first_dataset_utc": first_dt.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "start_day_utc": start_day.isoformat(),
        "end_day_utc_exclusive": end_day.isoformat(),
        "days_prior": args.days_prior,
        "counts": {"ok": ok, "skipped_exists": skipped, "error": failed},
        "results": [
            {
                "day": r.day.isoformat(),
                "start_utc": r.start_utc,
                "end_utc": r.end_utc,
                "path": r.path,
                "status": r.status,
                "size_bytes": r.size_bytes,
                "returncode": r.returncode,
                "stdout": r.stdout,
                "stderr": r.stderr,
            }
            for r in results
        ],
    }

    manifest_name = f"manifest.{args.region}.{start_day.isoformat()}_{(end_day - timedelta(days=1)).isoformat()}.json"
    manifest_path = out_dir / manifest_name
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    print(f"Wrote manifest: {manifest_path}", file=sys.stderr)

    return 0 if failed == 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
