#!/usr/bin/env python3
"""Download and concatenate DB part URLs from a manifest db_parts payload."""

from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path
from typing import List, Tuple


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Download db_parts URLs and concatenate to one file")
    parser.add_argument("--parts-json", required=True, help="JSON array payload from bundle manifest db_parts")
    parser.add_argument("--out", required=True, help="Output path for concatenated DB")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    payload = json.loads(args.parts_json)
    if not isinstance(payload, list) or not payload:
        return 0

    usable: List[Tuple[str, str]] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        file_name = str(item.get("file") or "")
        url = item.get("url")
        if not isinstance(url, str) or not url:
            continue
        usable.append((file_name, url))

    usable.sort(key=lambda row: row[0])
    if not usable:
        return 0

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.unlink(missing_ok=True)

    with out_path.open("wb") as out_f:
        for _, url in usable:
            with urllib.request.urlopen(url, timeout=900) as resp:
                while True:
                    chunk = resp.read(8 * 1024 * 1024)
                    if not chunk:
                        break
                    out_f.write(chunk)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
