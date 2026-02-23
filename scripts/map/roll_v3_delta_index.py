#!/usr/bin/env python3
"""Roll forward v3 delta index with retention trimming."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Tuple


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_index(path: Path) -> List[dict]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    entries = payload.get("entries")
    if not isinstance(entries, list):
        return []
    out: List[dict] = []
    for item in entries:
        if isinstance(item, dict):
            out.append(item)
    return out


def _load_delta_manifest(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("format") != "youspeed.v3.delta.manifest":
        raise SystemExit(f"Unexpected delta manifest format in {path}")
    return payload


def _join_url(base: str, suffix: str) -> str:
    return f"{base.rstrip('/')}/{suffix.lstrip('/')}"


def _entry_key(entry: dict) -> Tuple[str, str]:
    return (
        str(entry.get("from_bundle_version", "")),
        str(entry.get("to_bundle_version", "")),
    )


def _retained(entries: List[dict], retention_count: int) -> List[dict]:
    if not entries:
        return []
    if retention_count <= 0:
        return []

    def _sort_key(e: dict) -> Tuple[str, str]:
        return (
            str(e.get("to_bundle_version", "")),
            str(e.get("from_bundle_version", "")),
        )

    sorted_entries = sorted(entries, key=_sort_key)
    if len(sorted_entries) <= retention_count:
        return sorted_entries
    return sorted_entries[-retention_count:]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Roll forward v3 delta index with rolling retention")
    parser.add_argument("--output", required=True, help="Output path for rolled delta index")
    parser.add_argument(
        "--existing-index",
        default="",
        help="Existing delta index path to merge from",
    )
    parser.add_argument(
        "--new-delta-manifest",
        default="",
        help="Optional new delta manifest path to append",
    )
    parser.add_argument(
        "--new-delta-manifest-asset-path",
        default="",
        help="Asset path for new delta manifest (used with --release-asset-base-url)",
    )
    parser.add_argument(
        "--release-asset-base-url",
        default="",
        help="Optional release asset base URL for delta_manifest_file in new entry",
    )
    parser.add_argument(
        "--retention-count",
        type=int,
        default=30,
        help="Retain latest N incremental entries by to_bundle_version (default: 30)",
    )
    parser.add_argument(
        "--retention-days",
        type=int,
        default=None,
        help="Deprecated alias for --retention-count",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    retention_count = int(args.retention_count)
    if args.retention_days is not None:
        retention_count = int(args.retention_days)

    merged: Dict[Tuple[str, str], dict] = {}

    if args.existing_index:
        for entry in _load_index(Path(args.existing_index)):
            merged[_entry_key(entry)] = entry

    if args.new_delta_manifest:
        manifest_path = Path(args.new_delta_manifest)
        payload = _load_delta_manifest(manifest_path)
        from_ver = str(payload.get("from_bundle_version", ""))
        to_ver = str(payload.get("to_bundle_version", ""))

        delta_manifest_file = str(manifest_path)
        if args.new_delta_manifest_asset_path:
            delta_manifest_file = args.new_delta_manifest_asset_path
        if args.release_asset_base_url:
            delta_manifest_file = _join_url(args.release_asset_base_url, delta_manifest_file)

        new_entry = {
            "from_bundle_version": from_ver,
            "to_bundle_version": to_ver,
            "region": payload.get("region"),
            "delta_manifest_file": delta_manifest_file,
            "patch_file": payload.get("patch", {}).get("file"),
            "patch_sha256": payload.get("patch", {}).get("sha256"),
            "patch_bytes": payload.get("patch", {}).get("bytes"),
            "patch_url": payload.get("patch", {}).get("url"),
        }
        merged[(from_ver, to_ver)] = new_entry

    entries = list(merged.values())
    entries = _retained(entries, retention_count=retention_count)

    out = {
        "format": "youspeed.v3.delta.index",
        "schema_version": 1,
        "generated_at_utc": _now_utc(),
        "retention_count": retention_count,
        "retention_days": retention_count,
        "count": len(entries),
        "entries": entries,
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(out, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote rolled delta index: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
