#!/usr/bin/env python3
"""Assemble a country-level catalog from multiple regional v3 bundle manifests."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


def _sha256_path(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build v3 multi-region bundle catalog")
    parser.add_argument("--country", required=True, help="Country code/name (for example: DEU)")
    parser.add_argument("--bundle-version", required=True, help="Logical catalog version (for example: 2026-03-02)")
    parser.add_argument(
        "--max-country-pbf-bytes",
        type=int,
        default=1_000_000_000,
        help="Sharding threshold recorded in catalog metadata",
    )
    parser.add_argument(
        "--manifest",
        action="append",
        default=[],
        help="Path to one regional bundle manifest (repeat for multiple regions)",
    )
    parser.add_argument("--out-json", required=True, help="Output catalog JSON path")
    return parser.parse_args()


def _artifact_from_path(path: Path) -> Dict:
    return {
        "file": path.name,
        "bytes": path.stat().st_size,
        "sha256": _sha256_path(path),
        "url": None,
    }


def _load_manifest(path: Path) -> Dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("format") != "youspeed.v3.bundle.manifest":
        raise SystemExit(f"Unexpected manifest format in {path}: {payload.get('format')!r}")
    if payload.get("variant") != "v3":
        raise SystemExit(f"Unexpected manifest variant in {path}: {payload.get('variant')!r}")
    return payload


def main() -> int:
    args = parse_args()
    manifest_paths = [Path(x) for x in args.manifest]
    if not manifest_paths:
        raise SystemExit("Provide at least one --manifest")
    for path in manifest_paths:
        if not path.exists():
            raise SystemExit(f"Manifest file not found: {path}")

    regions: List[Dict] = []
    for manifest_path in sorted(manifest_paths):
        payload = _load_manifest(manifest_path)
        region = str(payload.get("region", "")).strip()
        if not region:
            raise SystemExit(f"Missing region in manifest: {manifest_path}")
        region_name = str(payload.get("region_name", region)).strip() or region
        region_entry: Dict = {
            "region": region,
            "name": region_name,
            "bundle_version": str(payload.get("bundle_version", args.bundle_version)),
            "manifest": _artifact_from_path(manifest_path),
            "coverage": payload.get("coverage"),
        }
        regions.append(region_entry)

    catalog = {
        "format": "youspeed.v3.bundle.catalog",
        "schema_version": 1,
        "variant": "v3",
        "country": args.country,
        "bundle_version": args.bundle_version,
        "created_at_utc": _now_utc(),
        "max_country_pbf_bytes": int(args.max_country_pbf_bytes),
        "regions": regions,
    }

    out_path = Path(args.out_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(catalog, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote catalog: {out_path}")
    print(f"Regions: {len(regions)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
