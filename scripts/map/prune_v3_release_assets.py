#!/usr/bin/env python3
"""Prune old v3 release assets outside the rolling retention window."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import List, Set
from urllib.parse import urlparse


def _run(args: List[str]) -> str:
    proc = subprocess.run(args, text=True, capture_output=True, check=True)
    return proc.stdout


def _extract_asset_name_from_release_url(url: str, release_tag: str) -> str | None:
    parsed = urlparse(url)
    parts = [p for p in parsed.path.split("/") if p]
    # expected: /<owner>/<repo>/releases/download/<tag>/<asset>
    marker = ["releases", "download", release_tag]
    for i in range(len(parts) - len(marker)):
        if parts[i : i + len(marker)] == marker:
            suffix = parts[i + len(marker) :]
            if suffix:
                return "/".join(suffix)
    return None


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prune v3 release assets based on delta index keep set")
    parser.add_argument("--repo", required=True, help="owner/repo")
    parser.add_argument("--release-tag", required=True, help="Release tag to prune")
    parser.add_argument("--delta-index", required=True, help="Path to current rolled delta-index.v3.json")
    parser.add_argument(
        "--bundle-manifest",
        default="",
        help="Optional latest bundle manifest path to keep db_parts assets",
    )
    parser.add_argument(
        "--asset-prefix",
        default="",
        help="Optional prefix; when set, only assets under this prefix are considered for pruning",
    )
    parser.add_argument(
        "--bundle-manifest-name",
        default="DEU-latest.bundle-manifest.v3.json",
        help="Latest bundle manifest asset name (default: DEU-latest.bundle-manifest.v3.json)",
    )
    parser.add_argument(
        "--delta-index-name",
        default="DEU-latest.delta-index.v3.json",
        help="Latest delta index asset name (default: DEU-latest.delta-index.v3.json)",
    )
    parser.add_argument(
        "--db-file-name",
        default="DEU-latest.speeds_v3.sqlite",
        help="Latest full DB asset name (default: DEU-latest.speeds_v3.sqlite)",
    )
    parser.add_argument(
        "--delta-manifest-prefix",
        default="DEU-",
        help="Prefix used for rolling delta manifest assets (default: DEU-)",
    )
    parser.add_argument(
        "--patch-prefix",
        default="DEU-",
        help="Prefix used for rolling SQL patch assets (default: DEU-)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print deletions without deleting assets",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    delta_index = Path(args.delta_index)
    payload = json.loads(delta_index.read_text(encoding="utf-8"))
    entries = payload.get("entries", [])
    keep: Set[str] = set()
    prefix = args.asset_prefix
    if prefix and not prefix.endswith("/"):
        prefix += "/"

    bundle_manifest_name = args.bundle_manifest_name.strip()
    delta_index_name = args.delta_index_name.strip()
    db_file_name = args.db_file_name.strip()
    delta_manifest_prefix = args.delta_manifest_prefix.strip()
    patch_prefix = args.patch_prefix.strip()

    if not bundle_manifest_name or not delta_index_name or not db_file_name:
        raise SystemExit("bundle/delta/db asset names must be non-empty")

    keep.add(f"{prefix}{bundle_manifest_name}")
    keep.add(f"{prefix}{delta_index_name}")
    keep.add(f"{prefix}{db_file_name}")

    if args.bundle_manifest:
        manifest_path = Path(args.bundle_manifest)
        if manifest_path.exists():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            db_parts = manifest.get("db_parts", [])
            if isinstance(db_parts, list):
                for part in db_parts:
                    if not isinstance(part, dict):
                        continue
                    file_name = part.get("file")
                    url = part.get("url")
                    if isinstance(file_name, str) and file_name:
                        keep.add(f"{prefix}{file_name}" if prefix else file_name)
                    if isinstance(url, str) and (url.startswith("http://") or url.startswith("https://")):
                        name = _extract_asset_name_from_release_url(url, args.release_tag)
                        if name:
                            keep.add(name)

    for entry in entries:
        if not isinstance(entry, dict):
            continue
        dmf = entry.get("delta_manifest_file")
        if isinstance(dmf, str):
            if dmf.startswith("http://") or dmf.startswith("https://"):
                name = _extract_asset_name_from_release_url(dmf, args.release_tag)
                if name:
                    keep.add(name)
            elif prefix and dmf.startswith(prefix):
                keep.add(dmf)
        patch_url = entry.get("patch_url")
        if isinstance(patch_url, str) and (patch_url.startswith("http://") or patch_url.startswith("https://")):
            name = _extract_asset_name_from_release_url(patch_url, args.release_tag)
            if name:
                keep.add(name)

    assets_raw = _run(
        [
            "gh",
            "release",
            "view",
            args.release_tag,
            "--repo",
            args.repo,
            "--json",
            "assets",
        ]
    )
    assets_payload = json.loads(assets_raw)
    assets = assets_payload.get("assets", [])
    to_delete: List[str] = []
    for asset in assets:
        name = str(asset.get("name", ""))
        managed = (
            name == f"{prefix}{bundle_manifest_name}"
            or name == f"{prefix}{delta_index_name}"
            or name == f"{prefix}{db_file_name}"
            or name.startswith(f"{prefix}{db_file_name}.part")
            or (bool(delta_manifest_prefix) and name.startswith(f"{prefix}{delta_manifest_prefix}"))
            or (bool(patch_prefix) and name.startswith(f"{prefix}{patch_prefix}"))
        )
        if prefix:
            managed = managed and name.startswith(prefix)
        if not managed:
            continue
        if name not in keep:
            to_delete.append(name)

    if not to_delete:
        print("No release assets to prune.")
        return 0

    for name in sorted(to_delete):
        if args.dry_run:
            print(f"would delete: {name}")
            continue
        subprocess.run(
            [
                "gh",
                "release",
                "delete-asset",
                args.release_tag,
                name,
                "--repo",
                args.repo,
                "--yes",
            ],
            check=True,
        )
        print(f"deleted: {name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
