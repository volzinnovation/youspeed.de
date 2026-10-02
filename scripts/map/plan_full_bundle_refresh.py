#!/usr/bin/env python3
"""Plan a complete, commit-pinned refresh of app bundles and the Karlsruhe seed."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re


PRIORITY_TARGETS = (
    "switzerland", "rhone-alpes", "monaco", "liechtenstein", "luxembourg", "iceland",
)
EXTRA_TARGETS = ("karlsruhe-regbez",)
TARGET_PATTERN = re.compile(r"[a-z0-9]+(?:-[a-z0-9]+)*")
VERSION_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{0,127}")


def resolve_targets(config_path: Path, countries: str = "") -> list[str]:
    payload = json.loads(config_path.read_text(encoding="utf-8"))
    if payload.get("format") != "youspeed.v3.bundle.targets":
        raise ValueError("Unexpected bundle target configuration format")
    configured = []
    country_regions = {}
    for country in payload.get("countries", []):
        country_id = str(country.get("country_id", "")).strip().lower()
        regions = []
        for row in country.get("regions", []):
            region = str(row.get("region_id", "")).strip().lower()
            if region.startswith(country_id + "/"):
                region = region[len(country_id) + 1:]
            if not TARGET_PATTERN.fullmatch(region):
                raise ValueError(f"Invalid configured target: {region!r}")
            regions.append(region)
        if not country_id or not regions:
            raise ValueError("Each configured country must have an id and regions")
        country_regions[country_id] = regions
        configured.extend(regions)
    if not configured:
        raise ValueError("No bundle regions configured")
    available = list(dict.fromkeys([*configured, *EXTRA_TARGETS]))
    if countries.strip():
        selected = []
        for raw in countries.split(","):
            target = raw.strip().lower()
            if not target:
                raise ValueError("Empty target in countries override")
            if target in available:
                selected.append(target)
            elif target in country_regions:
                selected.extend(country_regions[target])
            else:
                raise ValueError(f"Unknown bundle target: {target}")
        return list(dict.fromkeys(selected))
    return list(dict.fromkeys([
        *(target for target in PRIORITY_TARGETS if target in available), *available,
    ]))


def resolve_version(override: str, run_id: str, run_attempt: str, *, now=None) -> str:
    version = override.strip()
    if not version:
        if not run_id.isdigit() or not run_attempt.isdigit():
            raise ValueError("An explicit bundle version or numeric workflow run id/attempt is required")
        day = (now or datetime.now(timezone.utc)).strftime("%Y-%m-%d")
        version = f"{day}-refresh-{run_id}-{run_attempt}"
    if not VERSION_PATTERN.fullmatch(version):
        raise ValueError("Bundle version must be a safe, nonempty filename component of at most 128 characters")
    return version


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--config", type=Path, default=Path("iphone/SpeedConsumerApp/BundleTargets.top10.json"))
    parser.add_argument("--countries", default="", help="Optional comma-separated region or country ids")
    parser.add_argument("--bundle-version", default="")
    parser.add_argument("--run-id", default=os.environ.get("GITHUB_RUN_ID", ""))
    parser.add_argument("--run-attempt", default=os.environ.get("GITHUB_RUN_ATTEMPT", "1"))
    parser.add_argument("--github-output", type=Path)
    args = parser.parse_args()
    try:
        targets = resolve_targets(args.config, args.countries)
        version = resolve_version(args.bundle_version, args.run_id, args.run_attempt)
    except (ValueError, KeyError, TypeError) as exc:
        parser.error(str(exc))
    if args.github_output:
        with args.github_output.open("a", encoding="utf-8") as output:
            output.write(f"targets={json.dumps(targets, separators=(',', ':'))}\n")
            output.write(f"version={version}\n")
    print(json.dumps({"targets": targets, "count": len(targets), "bundle_version": version}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
