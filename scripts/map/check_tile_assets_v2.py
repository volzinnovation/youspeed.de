#!/usr/bin/env python3
"""Validate v2 tile/segment map asset metadata contracts."""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

TILE_ID_RE = re.compile(r"^-?\d+/-?\d+$")
SHA256_RE = re.compile(r"^[a-f0-9]{64}$")
URL_RE = re.compile(r"^https://[^\s]+$")
RFC3339_UTC_FMT = "%Y-%m-%dT%H:%M:%SZ"

VALID_CHUNK_NAMES = {
    "segment_index",
    "segment_geom",
    "speed_rules",
    "adjacency",
    "area_index",
}
VALID_CODECS = {"raw", "zstd"}
REQUIRED_CHUNK_NAMES = {
    "segment_index",
    "segment_geom",
    "speed_rules",
    "area_index",
}


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_non_empty_string(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _check_rfc3339_utc(value: Any, field: str, errors: List[str]) -> None:
    if not isinstance(value, str):
        errors.append(f"{field} must be a string")
        return
    try:
        datetime.strptime(value, RFC3339_UTC_FMT)
    except ValueError:
        errors.append(f"{field} must match RFC3339 UTC format YYYY-MM-DDTHH:MM:SSZ")


def _check_sha256(value: Any, field: str, errors: List[str]) -> None:
    if not isinstance(value, str) or not SHA256_RE.match(value):
        errors.append(f"{field} must be a lowercase hex sha256 string")


def _check_url(value: Any, field: str, errors: List[str]) -> None:
    if not isinstance(value, str) or not URL_RE.match(value):
        errors.append(f"{field} must be an https URL")


def _check_tile_id(value: Any, field: str, errors: List[str]) -> None:
    if not isinstance(value, str) or not TILE_ID_RE.match(value):
        errors.append(f"{field} must match x/y where x,y are integers")


def _check_bbox_wgs84(value: Any, field: str, errors: List[str]) -> None:
    if not isinstance(value, dict):
        errors.append(f"{field} must be an object")
        return

    for key in ("min_lat", "min_lon", "max_lat", "max_lon"):
        if key not in value:
            errors.append(f"{field}.{key} is required")
            return
        if not _is_number(value[key]):
            errors.append(f"{field}.{key} must be a number")
            return

    min_lat = float(value["min_lat"])
    min_lon = float(value["min_lon"])
    max_lat = float(value["max_lat"])
    max_lon = float(value["max_lon"])

    if not (-90.0 <= min_lat <= 90.0 and -90.0 <= max_lat <= 90.0):
        errors.append(f"{field} lat must be in [-90, 90]")
    if not (-180.0 <= min_lon <= 180.0 and -180.0 <= max_lon <= 180.0):
        errors.append(f"{field} lon must be in [-180, 180]")
    if min_lat > max_lat:
        errors.append(f"{field}.min_lat must be <= {field}.max_lat")
    if min_lon > max_lon:
        errors.append(f"{field}.min_lon must be <= {field}.max_lon")


def validate_catalog_payload(payload: Dict[str, Any]) -> List[str]:
    errors: List[str] = []

    if payload.get("schema_version") != 2:
        errors.append("schema_version must be 2")

    if not _is_non_empty_string(payload.get("region")):
        errors.append("region must be a non-empty string")

    _check_rfc3339_utc(payload.get("generated_at_utc"), "generated_at_utc", errors)

    app_compat = payload.get("app_compat")
    if not isinstance(app_compat, dict):
        errors.append("app_compat must be an object")
    else:
        min_v = app_compat.get("min_data_runtime_version")
        max_v = app_compat.get("max_data_runtime_version")
        if not _is_int(min_v) or min_v < 1:
            errors.append("app_compat.min_data_runtime_version must be an integer >= 1")
        if not _is_int(max_v) or max_v < 1:
            errors.append("app_compat.max_data_runtime_version must be an integer >= 1")
        if _is_int(min_v) and _is_int(max_v) and min_v > max_v:
            errors.append("app_compat.min_data_runtime_version must be <= max_data_runtime_version")

    tile_grid = payload.get("tile_grid")
    if not isinstance(tile_grid, dict):
        errors.append("tile_grid must be an object")
    else:
        if tile_grid.get("crs") != "EPSG:3857":
            errors.append("tile_grid.crs must be EPSG:3857")
        tile_size_m = tile_grid.get("tile_size_m")
        if not _is_int(tile_size_m) or tile_size_m < 256:
            errors.append("tile_grid.tile_size_m must be an integer >= 256")

    channels = payload.get("channels")
    if not isinstance(channels, list) or not channels:
        errors.append("channels must be a non-empty array")
    else:
        seen_channels = set()
        for idx, channel in enumerate(channels):
            if not _is_non_empty_string(channel):
                errors.append(f"channels[{idx}] must be a non-empty string")
                continue
            if channel in seen_channels:
                errors.append(f"channels[{idx}] duplicates channel '{channel}'")
                continue
            seen_channels.add(channel)
        if "stable" not in seen_channels:
            errors.append("channels must include 'stable'")

    tiles = payload.get("tiles")
    if not isinstance(tiles, list) or not tiles:
        errors.append("tiles must be a non-empty array")
        return errors

    seen_tile_ids = set()
    for idx, tile in enumerate(tiles):
        prefix = f"tiles[{idx}]"
        if not isinstance(tile, dict):
            errors.append(f"{prefix} must be an object")
            continue

        tile_id = tile.get("tile_id")
        _check_tile_id(tile_id, f"{prefix}.tile_id", errors)
        if isinstance(tile_id, str):
            if tile_id in seen_tile_ids:
                errors.append(f"{prefix}.tile_id duplicates '{tile_id}'")
            seen_tile_ids.add(tile_id)

        _check_url(tile.get("tile_manifest_url"), f"{prefix}.tile_manifest_url", errors)
        _check_sha256(tile.get("tile_manifest_sha256"), f"{prefix}.tile_manifest_sha256", errors)

        content_version = tile.get("content_version")
        if not _is_int(content_version) or content_version < 1:
            errors.append(f"{prefix}.content_version must be an integer >= 1")

        content_bytes = tile.get("content_bytes")
        if not _is_int(content_bytes) or content_bytes < 0:
            errors.append(f"{prefix}.content_bytes must be an integer >= 0")

        _check_sha256(tile.get("content_sha256"), f"{prefix}.content_sha256", errors)
        _check_bbox_wgs84(tile.get("bbox_wgs84"), f"{prefix}.bbox_wgs84", errors)

    return errors


def validate_tile_manifest_payload(payload: Dict[str, Any]) -> List[str]:
    errors: List[str] = []

    if payload.get("schema_version") != 2:
        errors.append("schema_version must be 2")

    _check_tile_id(payload.get("tile_id"), "tile_id", errors)
    _check_rfc3339_utc(payload.get("generated_at_utc"), "generated_at_utc", errors)
    _check_url(payload.get("tile_pack_url"), "tile_pack_url", errors)
    _check_sha256(payload.get("tile_pack_sha256"), "tile_pack_sha256", errors)
    _check_bbox_wgs84(payload.get("bbox_wgs84"), "bbox_wgs84", errors)

    content_version = payload.get("content_version")
    if not _is_int(content_version) or content_version < 1:
        errors.append("content_version must be an integer >= 1")

    tile_pack_bytes = payload.get("tile_pack_bytes")
    if not _is_int(tile_pack_bytes) or tile_pack_bytes < 0:
        errors.append("tile_pack_bytes must be an integer >= 0")

    stats = payload.get("stats")
    if not isinstance(stats, dict):
        errors.append("stats must be an object")
    else:
        for key in ("segment_count", "node_count", "area_count"):
            value = stats.get(key)
            if not _is_int(value) or value < 0:
                errors.append(f"stats.{key} must be an integer >= 0")

    chunks = payload.get("chunks")
    if not isinstance(chunks, list) or not chunks:
        errors.append("chunks must be a non-empty array")
        return errors

    prev_offset: Optional[int] = None
    prev_end: Optional[int] = None
    seen_chunk_names = set()

    for idx, chunk in enumerate(chunks):
        prefix = f"chunks[{idx}]"
        if not isinstance(chunk, dict):
            errors.append(f"{prefix} must be an object")
            continue

        name = chunk.get("name")
        if not isinstance(name, str) or name not in VALID_CHUNK_NAMES:
            errors.append(f"{prefix}.name must be one of {sorted(VALID_CHUNK_NAMES)}")
        elif name in seen_chunk_names:
            errors.append(f"{prefix}.name duplicates '{name}'")
        else:
            seen_chunk_names.add(name)

        codec = chunk.get("codec")
        if not isinstance(codec, str) or codec not in VALID_CODECS:
            errors.append(f"{prefix}.codec must be one of {sorted(VALID_CODECS)}")

        offset = chunk.get("offset")
        length = chunk.get("length")
        if not _is_int(offset) or offset < 0:
            errors.append(f"{prefix}.offset must be an integer >= 0")
            offset = None
        if not _is_int(length) or length < 0:
            errors.append(f"{prefix}.length must be an integer >= 0")
            length = None

        if offset is not None:
            if prev_offset is not None and offset <= prev_offset:
                errors.append(f"{prefix}.offset must be strictly increasing")
            if prev_end is not None and offset < prev_end:
                errors.append(f"{prefix}.offset must not overlap previous chunk")

        if offset is not None and length is not None:
            prev_offset = offset
            prev_end = offset + length
            if _is_int(tile_pack_bytes) and prev_end > tile_pack_bytes:
                errors.append(f"{prefix} exceeds tile_pack_bytes")

    missing_required = REQUIRED_CHUNK_NAMES - seen_chunk_names
    if missing_required:
        errors.append(f"missing required chunk names: {sorted(missing_required)}")

    return errors


def _read_json(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError("top-level JSON must be an object")
    return payload


def _validate_file(path: Path, validator) -> List[str]:
    try:
        payload = _read_json(path)
    except FileNotFoundError:
        return [f"file not found: {path}"]
    except json.JSONDecodeError as exc:
        return [f"invalid JSON in {path}: {exc}"]
    except ValueError as exc:
        return [f"{path}: {exc}"]

    return validator(payload)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate map tile/segment v2 catalog and tile manifests")
    parser.add_argument("--catalog", help="Path to catalog.v2.json")
    parser.add_argument(
        "--tile-manifest",
        action="append",
        default=[],
        help="Path to tile_manifest.v2.json (can be specified multiple times)",
    )
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)

    if not args.catalog and not args.tile_manifest:
        print("Provide --catalog and/or --tile-manifest", file=sys.stderr)
        return 2

    has_error = False

    if args.catalog:
        catalog_path = Path(args.catalog)
        catalog_errors = _validate_file(catalog_path, validate_catalog_payload)
        if catalog_errors:
            has_error = True
            for error in catalog_errors:
                print(f"[catalog] {error}", file=sys.stderr)

    for manifest_path_raw in args.tile_manifest:
        manifest_path = Path(manifest_path_raw)
        manifest_errors = _validate_file(manifest_path, validate_tile_manifest_payload)
        if manifest_errors:
            has_error = True
            for error in manifest_errors:
                print(f"[tile_manifest:{manifest_path}] {error}", file=sys.stderr)

    if has_error:
        return 1

    print("v2 asset validation passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
