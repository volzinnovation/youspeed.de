#!/usr/bin/env python3
"""Build a v3 delta index from delta manifest files."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Aggregate v3 delta manifests into one delta index")
    parser.add_argument(
        "--delta-manifest-dir",
        required=True,
        help="Directory containing v3 delta manifest files",
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Output path for delta index JSON",
    )
    parser.add_argument(
        "--manifest-glob",
        default="**/v3_delta_manifest*.json",
        help="Glob pattern under --delta-manifest-dir (default: **/v3_delta_manifest*.json)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    root = Path(args.delta_manifest_dir)
    if not root.exists():
        raise SystemExit(f"Missing directory: {root}")

    entries: List[Dict[str, object]] = []
    for path in sorted(root.glob(args.manifest_glob)):
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding="utf-8"))
        entries.append(
            {
                "from_bundle_version": payload.get("from_bundle_version"),
                "to_bundle_version": payload.get("to_bundle_version"),
                "region": payload.get("region"),
                "delta_manifest_file": str(path.relative_to(root)),
                "patch_file": payload.get("patch", {}).get("file"),
                "patch_sha256": payload.get("patch", {}).get("sha256"),
                "patch_bytes": payload.get("patch", {}).get("bytes"),
                "patch_url": payload.get("patch", {}).get("url"),
                "patch_compression": payload.get("patch", {}).get("compression"),
            }
        )

    index = {
        "format": "youspeed.v3.delta.index",
        "schema_version": 1,
        "generated_at_utc": _now_utc(),
        "count": len(entries),
        "entries": entries,
    }

    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(index, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote delta index: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
