#!/usr/bin/env python3
"""Publish a v3 consumer bundle (DB + manifest) for independent app updates."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Tuple


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


def _id_token(value: str) -> str:
    return (
        value.strip()
        .lower()
        .replace(" ", "-")
        .replace("_", "-")
        .replace("/", "-")
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Publish v3 map bundle for consumer app updates")
    parser.add_argument("--region", default="germany", help="Region identifier (default: germany)")
    parser.add_argument(
        "--country-code",
        default="",
        help="Optional ISO 3166-1 alpha-3 code linked to this bundle (for example: DEU)",
    )
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
        default="",
        help="Database file name inside the bundle directory (default: <region-id>_speeds.sqlite)",
    )
    parser.add_argument(
        "--db-compression",
        choices=("none", "gzip"),
        default="none",
        help="Optional compression for published DB download artifacts (default: none)",
    )
    parser.add_argument(
        "--manifest-name",
        default="",
        help="Manifest file name inside the bundle directory (default: <region-id>_manifest.json)",
    )
    parser.add_argument(
        "--delta-index",
        default="",
        help="Optional path to delta index JSON to copy into bundle directory",
    )
    parser.add_argument(
        "--delta-index-file-name",
        default="",
        help="Delta index file name inside the bundle directory (default: <region-id>_delta_index.json)",
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
    parser.add_argument(
        "--max-release-asset-bytes",
        type=int,
        default=1_900_000_000,
        help="Max bytes per release asset before DB is split into .partNNN files (default: 1900000000)",
    )
    parser.add_argument(
        "--no-split-db",
        action="store_true",
        help="Disable DB splitting even if DB exceeds --max-release-asset-bytes",
    )
    parser.add_argument(
        "--coverage-poly",
        default="",
        help="Optional Geofabrik .poly file describing regional coverage for this bundle",
    )
    parser.add_argument(
        "--coverage-poly-file-name",
        default="",
        help="Optional target file name for copied coverage poly (default: basename of --coverage-poly)",
    )
    parser.add_argument(
        "--penalty-rules",
        default="",
        help="Optional country penalty rules JSON to include in bundle and manifest",
    )
    parser.add_argument(
        "--penalty-rules-file-name",
        default="",
        help="Optional target file name for copied penalty rules (default: basename of --penalty-rules)",
    )
    return parser.parse_args()


def _artifact_payload(path: Path, rel_file: str, url: Optional[str]) -> dict:
    return {
        "file": rel_file,
        "bytes": path.stat().st_size,
        "sha256": _sha256_path(path),
        "url": url,
    }


def _logical_db_payload(
    src_db: Path,
    rel_file: str,
    url: Optional[str],
    *,
    published_path: Optional[Path] = None,
    compression: Optional[str] = None,
) -> dict:
    payload = {
        "file": rel_file,
        "bytes": (published_path or src_db).stat().st_size,
        "sha256": _sha256_path(published_path or src_db),
        "url": url,
    }
    normalized_compression = (compression or "").strip().lower()
    if normalized_compression and normalized_compression != "none":
        payload["compression"] = normalized_compression
        payload["uncompressed_bytes"] = src_db.stat().st_size
        payload["uncompressed_sha256"] = _sha256_path(src_db)
    return payload


def _gzip_file(src: Path, dst: Path, compresslevel: int = 6) -> None:
    tmp_path = dst.with_suffix(dst.suffix + ".tmp")
    with src.open("rb") as in_f, tmp_path.open("wb") as raw_out:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=raw_out,
            compresslevel=compresslevel,
            mtime=0,
        ) as gzip_out:
            shutil.copyfileobj(in_f, gzip_out, length=1024 * 1024)
    tmp_path.replace(dst)


def _cleanup_stale_db_outputs(out_dir: Path, db_file_name: str, preserve_main_name: Optional[str] = None) -> None:
    for base_name in (db_file_name, f"{db_file_name}.gz"):
        stale_main = out_dir / base_name
        if stale_main.is_file() and base_name != preserve_main_name:
            stale_main.unlink()
        for stale_part in out_dir.glob(f"{base_name}.part*"):
            if stale_part.is_file():
                stale_part.unlink()


def _split_file_to_parts(src: Path, out_dir: Path, base_name: str, max_part_bytes: int) -> List[Path]:
    if max_part_bytes <= 0:
        raise SystemExit("--max-release-asset-bytes must be > 0")
    out_dir.mkdir(parents=True, exist_ok=True)
    parts: List[Path] = []

    # Remove stale parts from prior bundle writes.
    for stale in out_dir.glob(f"{base_name}.part*"):
        if stale.is_file():
            stale.unlink()

    chunk_size = 8 * 1024 * 1024
    with src.open("rb") as in_f:
        part_idx = 1
        while True:
            part_name = f"{base_name}.part{part_idx:03d}"
            part_path = out_dir / part_name
            tmp_path = part_path.with_suffix(part_path.suffix + ".tmp")
            written = 0

            with tmp_path.open("wb") as out_f:
                while written < max_part_bytes:
                    to_read = min(chunk_size, max_part_bytes - written)
                    data = in_f.read(to_read)
                    if not data:
                        break
                    out_f.write(data)
                    written += len(data)

            if written == 0:
                tmp_path.unlink(missing_ok=True)
                break

            tmp_path.replace(part_path)
            parts.append(part_path)
            part_idx += 1

    if not parts:
        raise SystemExit(f"Failed to split DB into parts: {src}")
    return parts


def _parse_poly_bbox(poly_path: Path) -> Tuple[float, float, float, float]:
    text = poly_path.read_text(encoding="utf-8")
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    if len(lines) < 4:
        raise SystemExit(f"Coverage poly seems invalid (too few lines): {poly_path}")

    min_lon = float("inf")
    min_lat = float("inf")
    max_lon = float("-inf")
    max_lat = float("-inf")
    for line in lines[1:]:
        upper = line.upper()
        if upper == "END":
            continue
        if line.startswith("!"):
            continue
        if line.isdigit():
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        try:
            lon = float(parts[0])
            lat = float(parts[1])
        except ValueError:
            continue
        min_lon = min(min_lon, lon)
        min_lat = min(min_lat, lat)
        max_lon = max(max_lon, lon)
        max_lat = max(max_lat, lat)

    if not (min_lon < float("inf") and min_lat < float("inf") and max_lon > float("-inf") and max_lat > float("-inf")):
        raise SystemExit(f"Coverage poly contains no coordinates: {poly_path}")
    return min_lon, min_lat, max_lon, max_lat


def main() -> int:
    args = parse_args()
    src_db = Path(args.db)
    if not src_db.exists():
        raise SystemExit(f"Missing DB file: {src_db}")

    region_id_token = _id_token(args.region)
    if not region_id_token:
        raise SystemExit("--region must not be empty")

    db_file_name = args.db_file_name.strip() or f"{region_id_token}_speeds.sqlite"
    manifest_name = args.manifest_name.strip() or f"{region_id_token}_manifest.json"
    delta_index_file_name = args.delta_index_file_name.strip() or f"{region_id_token}_delta_index.json"

    bundle_dir_name = args.bundle_dir_name or args.bundle_version
    out_dir = Path(args.out_root) / args.region / bundle_dir_name
    out_dir.mkdir(parents=True, exist_ok=True)

    dst_db = out_dir / db_file_name
    normalized_db_compression = args.db_compression.strip().lower()
    if normalized_db_compression != "none" and args.no_copy_db:
        raise SystemExit("--no-copy-db cannot be combined with --db-compression")

    preserve_main_name = db_file_name if args.no_copy_db and normalized_db_compression == "none" else None
    _cleanup_stale_db_outputs(out_dir, db_file_name, preserve_main_name=preserve_main_name)

    coverage_poly_src: Optional[Path] = None
    if args.coverage_poly:
        coverage_poly_src = Path(args.coverage_poly)
        if not coverage_poly_src.exists():
            raise SystemExit(f"Coverage poly not found: {coverage_poly_src}")
    penalty_rules_src: Optional[Path] = None
    if args.penalty_rules:
        penalty_rules_src = Path(args.penalty_rules)
        if not penalty_rules_src.exists():
            raise SystemExit(f"Penalty rules file not found: {penalty_rules_src}")

    compressed_db_path: Optional[Path] = None
    if normalized_db_compression == "gzip":
        compressed_db_path = out_dir / f"{db_file_name}.gz"
        _gzip_file(src_db, compressed_db_path)
        publish_db_path = compressed_db_path
    else:
        publish_db_path = src_db

    db_size = publish_db_path.stat().st_size
    should_split_db = (
        (not args.no_split_db)
        and db_size > int(args.max_release_asset_bytes)
    )

    if should_split_db and args.no_copy_db:
        raise SystemExit("--no-copy-db cannot be combined with split DB output")

    db_download_file_name = f"{db_file_name}.gz" if normalized_db_compression == "gzip" else db_file_name

    part_paths: List[Path] = []
    if should_split_db:
        dst_db.unlink(missing_ok=True)
        part_paths = _split_file_to_parts(
            src=publish_db_path,
            out_dir=out_dir,
            base_name=db_download_file_name,
            max_part_bytes=int(args.max_release_asset_bytes),
        )
    else:
        if normalized_db_compression == "none":
            if args.no_copy_db:
                if not dst_db.exists():
                    raise SystemExit(f"--no-copy-db set but destination DB is missing: {dst_db}")
            else:
                tmp_db = dst_db.with_suffix(dst_db.suffix + ".tmp")
                shutil.copy2(src_db, tmp_db)
                tmp_db.replace(dst_db)

    coverage_poly_dst: Optional[Path] = None
    coverage_bbox_payload: Optional[dict] = None
    if coverage_poly_src is not None:
        coverage_name = args.coverage_poly_file_name.strip() or coverage_poly_src.name
        coverage_poly_dst = out_dir / coverage_name
        if coverage_poly_src.resolve() != coverage_poly_dst.resolve():
            shutil.copy2(coverage_poly_src, coverage_poly_dst)
        min_lon, min_lat, max_lon, max_lat = _parse_poly_bbox(coverage_poly_src)
        coverage_bbox_payload = {
            "min_lon": min_lon,
            "min_lat": min_lat,
            "max_lon": max_lon,
            "max_lat": max_lat,
        }

    penalty_rules_dst: Optional[Path] = None
    if penalty_rules_src is not None:
        penalty_rules_name = args.penalty_rules_file_name.strip() or penalty_rules_src.name
        penalty_rules_dst = out_dir / penalty_rules_name
        if penalty_rules_src.resolve() != penalty_rules_dst.resolve():
            shutil.copy2(penalty_rules_src, penalty_rules_dst)

    use_github_urls = bool(args.github_owner and args.github_repo and args.github_release_tag)
    asset_prefix = args.github_asset_prefix.strip("/")

    def artifact_url(file_name: str) -> Optional[str]:
        if use_github_urls:
            asset_name = f"{asset_prefix}/{file_name}" if asset_prefix else file_name
            return _github_release_asset_url(args.github_owner, args.github_repo, args.github_release_tag, asset_name)
        if args.base_url:
            return _join_url(args.base_url, args.region, bundle_dir_name, file_name)
        return None

    db_url: Optional[str]
    if should_split_db:
        db_url = None
    elif normalized_db_compression == "gzip":
        db_url = artifact_url(db_download_file_name) or db_download_file_name
    else:
        db_url = artifact_url(db_file_name)

    db_payload = _logical_db_payload(
        src_db,
        db_file_name,
        db_url,
        published_path=publish_db_path if normalized_db_compression != "none" else None,
        compression=normalized_db_compression,
    )
    manifest: dict = {
        "format": "youspeed.v3.bundle.manifest",
        "schema_version": args.schema_version,
        "variant": "v3",
        "region": args.region,
        "bundle_version": args.bundle_version,
        "created_at_utc": _now_utc(),
        "min_app_version": args.min_app_version,
        "db": db_payload,
        "delta_index": None,
        "db_parts": [],
        "source": {},
        "self": {
            "file": manifest_name,
            "url": artifact_url(manifest_name),
        },
    }
    country_code = args.country_code.strip().upper()
    if country_code:
        if len(country_code) != 3 or not country_code.isalpha():
            raise SystemExit(f"--country-code must be a 3-letter ISO alpha-3 code, got: {args.country_code!r}")
        manifest["country_code"] = country_code
    if coverage_poly_dst is not None and coverage_bbox_payload is not None:
        manifest["coverage"] = {
            "bbox": coverage_bbox_payload,
            "poly": _artifact_payload(coverage_poly_dst, coverage_poly_dst.name, artifact_url(coverage_poly_dst.name)),
        }
    if penalty_rules_dst is not None:
        manifest["penalty_rules"] = _artifact_payload(
            penalty_rules_dst,
            penalty_rules_dst.name,
            artifact_url(penalty_rules_dst.name),
        )
    if should_split_db:
        manifest["db_parts"] = [
            _artifact_payload(path, path.name, artifact_url(path.name))
            for path in part_paths
        ]
    if args.include_source_paths:
        manifest["source"]["db"] = str(src_db)
        if should_split_db:
            manifest["source"]["db_parts"] = [str(p) for p in part_paths]
        if coverage_poly_src is not None:
            manifest["source"]["coverage_poly"] = str(coverage_poly_src)
        if penalty_rules_src is not None:
            manifest["source"]["penalty_rules"] = str(penalty_rules_src)

    if args.delta_index:
        src_delta_index = Path(args.delta_index)
        if not src_delta_index.exists():
            raise SystemExit(f"Missing delta index file: {src_delta_index}")
        dst_delta_index = out_dir / delta_index_file_name
        if src_delta_index.resolve() != dst_delta_index.resolve():
            shutil.copy2(src_delta_index, dst_delta_index)
        delta_url = artifact_url(delta_index_file_name)
        manifest["delta_index"] = _artifact_payload(dst_delta_index, delta_index_file_name, delta_url)
        if args.include_source_paths:
            manifest["source"]["delta_index"] = str(src_delta_index)

    manifest_path = out_dir / manifest_name
    if not manifest["source"]:
        manifest.pop("source", None)
    if not manifest["db_parts"]:
        manifest.pop("db_parts", None)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    if should_split_db and compressed_db_path is not None:
        compressed_db_path.unlink(missing_ok=True)

    print(f"Wrote v3 bundle: {out_dir}")
    if should_split_db:
        print(f"DB was split into {len(part_paths)} part files (max bytes per asset: {args.max_release_asset_bytes})")
    print(f"Manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
