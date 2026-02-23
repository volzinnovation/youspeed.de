#!/usr/bin/env python3
"""Publish a v3 consumer bundle (DB + manifest) for independent app updates."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _sha256_path(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _join_url(base: str, *parts: str) -> str:
    clean = base.rstrip("/")
    suffix = "/".join(p.strip("/") for p in parts if p)
    return f"{clean}/{suffix}" if suffix else clean


def _github_release_asset_url(owner: str, repo: str, tag: str, asset_name: str) -> str:
    return f"https://github.com/{owner}/{repo}/releases/download/{tag}/{asset_name}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish v3 map bundle for consumer app updates")
    parser.add_argument("--region", default="germany", help="Region identifier (default: germany)")
    parser.add_argument("--db", required=True, help="Path to source speeds_v3.sqlite")
    parser.add_argument("--bundle-version", required=True, help="Bundle version (for example: 2026-02-23)")
    parser.add_argument(
        "--bundle-dir-name",
        default="",
        help="Optional output directory name under region (default: bundle-version)",
    )
    parser.add_argument(
        "--out-root",
        default="mapdata/bundles/v3",
        help="Bundle root directory. Output goes to <out-root>/<region>/<bundle-version>/",
    )
    parser.add_argument(
        "--db-file-name",
        default="speeds_v3.sqlite",
        help="Database file name inside the bundle directory",
    )
    parser.add_argument(
        "--manifest-name",
        default="bundle-manifest.v3.json",
        help="Manifest file name inside the bundle directory",
    )
    parser.add_argument(
        "--delta-index",
        default="",
        help="Optional path to delta index JSON to copy into bundle directory",
    )
    parser.add_argument(
        "--delta-index-file-name",
        default="delta-index.v3.json",
        help="Delta index file name inside the bundle directory",
    )
    parser.add_argument("--min-app-version", default="1.0.0", help="Minimum app version compatible with this bundle")
    parser.add_argument("--schema-version", type=int, default=1, help="Bundle schema version (default: 1)")
    parser.add_argument(
        "--include-source-paths",
        action="store_true",
        help="Include local source paths in manifest.source (default: off)",
    )
    parser.add_argument(
        "--base-url",
        default="",
        help="Optional CDN base URL for generated artifact URLs",
    )
    parser.add_argument("--github-owner", default="", help="GitHub owner/org for release asset URLs")
    parser.add_argument("--github-repo", default="", help="GitHub repo for release asset URLs")
    parser.add_argument("--github-release-tag", default="", help="GitHub release tag for asset URLs")
    parser.add_argument(
        "--github-asset-prefix",
        default="",
        help="Optional prefix for release asset names (for example: germany/2026-02-23/)",
    )
    parser.add_argument(
        "--no-copy-db",
        action="store_true",
        help="Do not copy DB into output bundle (expects the target file to already exist)",
    )
    return parser.parse_args()


def _artifact_payload(path: Path, rel_file: str, url: Optional[str]) -> dict:
    return {
        "file": rel_file,
        "bytes": path.stat().st_size,
        "sha256": _sha256_path(path),
        "url": url,
    }


def main() -> int:
    args = parse_args()
    src_db = Path(args.db)
    if not src_db.exists():
        raise SystemExit(f"Missing DB file: {src_db}")

    bundle_dir_name = args.bundle_dir_name or args.bundle_version
    out_dir = Path(args.out_root) / args.region / bundle_dir_name
    out_dir.mkdir(parents=True, exist_ok=True)

    dst_db = out_dir / args.db_file_name
    if args.no_copy_db:
        if not dst_db.exists():
            raise SystemExit(f"--no-copy-db set but destination DB is missing: {dst_db}")
    else:
        tmp_db = dst_db.with_suffix(dst_db.suffix + ".tmp")
        shutil.copy2(src_db, tmp_db)
        tmp_db.replace(dst_db)

    use_github_urls = bool(args.github_owner and args.github_repo and args.github_release_tag)
    asset_prefix = args.github_asset_prefix.strip("/")

    def artifact_url(file_name: str) -> Optional[str]:
        if use_github_urls:
            asset_name = f"{asset_prefix}/{file_name}" if asset_prefix else file_name
            return _github_release_asset_url(args.github_owner, args.github_repo, args.github_release_tag, asset_name)
        if args.base_url:
            return _join_url(args.base_url, args.region, bundle_dir_name, file_name)
        return None

    db_url = artifact_url(args.db_file_name)
    manifest: dict = {
        "format": "youspeed.v3.bundle.manifest",
        "schema_version": args.schema_version,
        "variant": "v3",
        "region": args.region,
        "bundle_version": args.bundle_version,
        "created_at_utc": _now_utc(),
        "min_app_version": args.min_app_version,
        "db": _artifact_payload(dst_db, args.db_file_name, db_url),
        "delta_index": None,
        "source": {},
        "self": {
            "file": args.manifest_name,
            "url": artifact_url(args.manifest_name),
        },
    }
    if args.include_source_paths:
        manifest["source"]["db"] = str(src_db)

    if args.delta_index:
        src_delta_index = Path(args.delta_index)
        if not src_delta_index.exists():
            raise SystemExit(f"Missing delta index file: {src_delta_index}")
        dst_delta_index = out_dir / args.delta_index_file_name
        if src_delta_index.resolve() != dst_delta_index.resolve():
            shutil.copy2(src_delta_index, dst_delta_index)
        delta_url = artifact_url(args.delta_index_file_name)
        manifest["delta_index"] = _artifact_payload(dst_delta_index, args.delta_index_file_name, delta_url)
        if args.include_source_paths:
            manifest["source"]["delta_index"] = str(src_delta_index)

    manifest_path = out_dir / args.manifest_name
    if not manifest["source"]:
        manifest.pop("source", None)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(f"Wrote v3 bundle: {out_dir}")
    print(f"Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
