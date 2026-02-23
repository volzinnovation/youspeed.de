#!/usr/bin/env python3
"""Migrate v2 tile layout from flat g3857_x*_y* to nested x/y."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
from pathlib import Path
from typing import Dict, Tuple

OLD_TILE_RE = re.compile(r"^g3857_x(-?\d+)_y(-?\d+)$")
NEW_TILE_RE = re.compile(r"^-?\d+/-?\d+$")


def _sha256_path(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while True:
            chunk = f.read(1024 * 1024)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def _tile_to_xy(tile_id: str) -> Tuple[int, int]:
    if NEW_TILE_RE.match(tile_id):
        x, y = tile_id.split("/", 1)
        return int(x), int(y)
    m = OLD_TILE_RE.match(tile_id)
    if m:
        return int(m.group(1)), int(m.group(2))
    raise ValueError(f"unsupported tile_id format: {tile_id}")


def _tile_to_new_id(tile_id: str) -> str:
    x, y = _tile_to_xy(tile_id)
    return f"{x}/{y}"


def _tile_sort_key(tile_id: str) -> Tuple[int, int]:
    return _tile_to_xy(tile_id)


def _url_prefix(url: str) -> str:
    if "/tiles/" in url:
        return url.split("/tiles/", 1)[0]
    return url.rsplit("/", 1)[0]


def migrate_region(dist_dir: Path) -> int:
    catalog_path = dist_dir / "catalog.v2.json"
    tiles_root = dist_dir / "tiles"
    if not catalog_path.exists():
        print(f"Missing catalog: {catalog_path}", file=sys.stderr)
        return 1
    if not tiles_root.exists():
        print(f"Missing tiles dir: {tiles_root}", file=sys.stderr)
        return 1

    with catalog_path.open("r", encoding="utf-8") as f:
        catalog = json.load(f)
    tiles = catalog.get("tiles")
    if not isinstance(tiles, list):
        print("Invalid catalog: tiles must be array", file=sys.stderr)
        return 1

    migrated = 0
    rewritten = 0
    for entry in tiles:
        if not isinstance(entry, dict):
            continue
        old_id = entry.get("tile_id")
        if not isinstance(old_id, str):
            continue

        new_id = _tile_to_new_id(old_id)
        old_dir = tiles_root / old_id
        new_dir = tiles_root / new_id

        if old_dir != new_dir and old_dir.exists():
            new_dir.parent.mkdir(parents=True, exist_ok=True)
            if new_dir.exists():
                for p in old_dir.iterdir():
                    target = new_dir / p.name
                    if target.exists():
                        raise RuntimeError(f"Refusing to overwrite existing file: {target}")
                    shutil.move(str(p), str(target))
                old_dir.rmdir()
            else:
                shutil.move(str(old_dir), str(new_dir))
            migrated += 1

        manifest_path = new_dir / "tile_manifest.v2.json"
        if not manifest_path.exists():
            raise FileNotFoundError(f"Missing tile manifest after move: {manifest_path}")
        with manifest_path.open("r", encoding="utf-8") as f:
            manifest = json.load(f)

        manifest["tile_id"] = new_id
        tile_pack_sha = manifest.get("tile_pack_sha256")
        if not isinstance(tile_pack_sha, str):
            raise ValueError(f"tile_pack_sha256 missing in {manifest_path}")
        old_pack_url = manifest.get("tile_pack_url", "")
        base = _url_prefix(old_pack_url) if isinstance(old_pack_url, str) and old_pack_url else None
        if base:
            manifest["tile_pack_url"] = f"{base}/tiles/{new_id}/{tile_pack_sha}.tilepack"

        manifest_path.write_text(
            json.dumps(manifest, sort_keys=True, separators=(",", ":"), indent=2) + "\n",
            encoding="utf-8",
        )
        manifest_sha = _sha256_path(manifest_path)

        entry["tile_id"] = new_id
        old_manifest_url = entry.get("tile_manifest_url", "")
        if isinstance(old_manifest_url, str) and old_manifest_url:
            prefix = _url_prefix(old_manifest_url)
            entry["tile_manifest_url"] = f"{prefix}/tiles/{new_id}/tile_manifest.v2.json"
        entry["tile_manifest_sha256"] = manifest_sha
        rewritten += 1

    catalog["tiles"] = sorted(tiles, key=lambda t: _tile_sort_key(t["tile_id"]))
    catalog_path.write_text(
        json.dumps(catalog, sort_keys=True, separators=(",", ":"), indent=2) + "\n",
        encoding="utf-8",
    )

    print(
        f"Migrated tile layout in {dist_dir}: moved_dirs={migrated}, rewritten_entries={rewritten}",
        file=sys.stderr,
    )
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Migrate v2 tiles from g3857_x*_y* to x/y layout")
    parser.add_argument("--dist-dir", required=True, help="Path to v2 region directory (contains catalog.v2.json)")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    return migrate_region(Path(args.dist_dir))


if __name__ == "__main__":
    raise SystemExit(main())
