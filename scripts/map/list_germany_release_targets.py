#!/usr/bin/env python3
"""Resolve Germany regional release targets for dispatcher workflows."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Iterable, List


DEFAULT_EXTRA_SHARDS = ["karlsruhe-regbez"]


def _load_germany_regions(config_path: Path) -> List[str]:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if payload.get("format") != "youspeed.v3.bundle.targets":
        raise SystemExit(f"Unexpected bundle target config format in {config_path}")

    for row in payload.get("countries", []):
        if str(row.get("country_id", "")).strip().lower() != "germany":
            continue
        regions = []
        for region in row.get("regions", []):
            region_id = str(region.get("region_id", "")).strip().lower()
            if region_id:
                regions.append(region_id)
        if not regions:
            raise SystemExit("Germany bundle target config has no regions")
        return regions

    raise SystemExit("Germany entry not found in bundle target config")


def _normalize_target_id(raw_target_id: str) -> str:
    target_id = raw_target_id.strip().lower()
    if target_id.startswith("germany/"):
        target_id = target_id.split("/", 1)[1]
    return target_id


def _dedupe(items: Iterable[str]) -> List[str]:
    out: List[str] = []
    seen = set()
    for item in items:
        if item not in seen:
            out.append(item)
            seen.add(item)
    return out


def resolve_targets(*, selector: str, config_path: Path, extra_shards: List[str]) -> List[str]:
    germany_regions = _load_germany_regions(config_path)
    shard_targets = _dedupe(_normalize_target_id(item) for item in extra_shards if item.strip())
    explicit_targets = _dedupe(["germany", *germany_regions, *shard_targets])

    value = selector.strip().lower()
    if not value or value == "all":
        return _dedupe([*germany_regions, *shard_targets])
    if value == "states":
        return germany_regions
    if value in {"root", "germany"}:
        return ["germany"]
    if value in {"all-root", "all-with-root"}:
        return _dedupe(["germany", *germany_regions, *shard_targets])

    selected = []
    invalid = []
    for raw_item in selector.split(","):
        item = _normalize_target_id(raw_item)
        if not item:
            continue
        if item == "root":
            item = "germany"
        if item not in explicit_targets:
            invalid.append(item)
            continue
        selected.append(item)

    if invalid:
        valid_list = ", ".join(explicit_targets)
        raise SystemExit(f"Unknown Germany release target(s): {', '.join(invalid)}. Valid targets: {valid_list}")

    selected = _dedupe(selected)
    if not selected:
        raise SystemExit("No Germany targets selected")
    return selected


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="List Germany release targets for workflow dispatch")
    parser.add_argument(
        "--selector",
        default="all",
        help="Special value (all, states, germany, all-root) or comma-separated region/shard ids",
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
        help="Additional Germany shard id to include (repeatable)",
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
    extra_shards = args.extra_shard or DEFAULT_EXTRA_SHARDS
    targets = resolve_targets(
        selector=args.selector,
        config_path=Path(args.config),
        extra_shards=extra_shards,
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
