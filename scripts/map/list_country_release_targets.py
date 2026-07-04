#!/usr/bin/env python3
"""Resolve configured regional release targets for dispatcher workflows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable, List


def _load_country_regions(config_path: Path, country_id: str) -> List[str]:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if payload.get("format") != "youspeed.v3.bundle.targets":
        raise SystemExit(f"Unexpected bundle target config format in {config_path}")

    target_country_id = country_id.strip().lower()
    for row in payload.get("countries", []):
        if str(row.get("country_id", "")).strip().lower() != target_country_id:
            continue
        regions = []
        for region in row.get("regions", []):
            region_id = str(region.get("region_id", "")).strip().lower()
            if region_id:
                regions.append(_normalize_target_id(region_id, target_country_id))
        if not regions:
            raise SystemExit(f"{target_country_id} bundle target config has no regions")
        return regions

    raise SystemExit(f"{target_country_id} entry not found in bundle target config")


def _normalize_target_id(raw_target_id: str, country_id: str) -> str:
    target_id = raw_target_id.strip().lower()
    prefix = f"{country_id.strip().lower()}/"
    if target_id.startswith(prefix):
        target_id = target_id[len(prefix) :]
    return target_id


def _dedupe(items: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in items:
        if item not in seen:
            out.append(item)
            seen.add(item)
    return out


def resolve_targets(
    *,
    country_id: str,
    selector: str,
    config_path: Path,
    extra_shards: List[str],
) -> List[str]:
    country_key = country_id.strip().lower()
    if not country_key:
        raise SystemExit("--country must not be empty")

    country_regions = _load_country_regions(config_path, country_key)
    shard_targets = _dedupe(
        _normalize_target_id(item, country_key) for item in extra_shards if item.strip()
    )
    explicit_targets = _dedupe([country_key, *country_regions, *shard_targets])

    value = selector.strip().lower()
    if not value or value == "all":
        return _dedupe([*country_regions, *shard_targets])
    if value in {"regions", "states"}:
        return country_regions
    if value in {"root", country_key}:
        return [country_key]
    if value in {"all-root", "all-with-root"}:
        return explicit_targets

    selected = []
    invalid = []
    for raw_item in selector.split(","):
        item = _normalize_target_id(raw_item, country_key)
        if not item:
            continue
        if item == "root":
            item = country_key
        if item not in explicit_targets:
            invalid.append(item)
            continue
        selected.append(item)

    if invalid:
        valid_list = ", ".join(explicit_targets)
        raise SystemExit(
            f"Unknown {country_key} release target(s): {', '.join(invalid)}. "
            f"Valid targets: {valid_list}"
        )

    selected = _dedupe(selected)
    if not selected:
        raise SystemExit(f"No {country_key} targets selected")
    return selected


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="List configured country release targets")
    parser.add_argument("--country", required=True, help="Country id in BundleTargets.top10.json")
    parser.add_argument(
        "--selector",
        default="all",
        help="Special value (all, regions, states, root, all-root) or comma-separated ids",
    )
    parser.add_argument(
        "--config",
        default="iphone/SpeedConsumerApp/BundleTargets.top10.json",
        help="Bundle target config JSON path",
    )
    parser.add_argument(
        "--extra-shard",
        action="append",
        default=[],
        help="Additional shard id to include (repeatable)",
    )
    parser.add_argument(
        "--format",
        choices=("csv", "json", "lines"),
        default="csv",
        help="Output format (default: csv)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    targets = resolve_targets(
        country_id=args.country,
        selector=args.selector,
        config_path=Path(args.config),
        extra_shards=args.extra_shard or [],
    )

    if args.format == "json":
        print(json.dumps(targets, indent=2))
    elif args.format == "lines":
        for target in targets:
            print(target)
    else:
        print(",".join(targets))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
