#!/usr/bin/env python3
"""Remove an entirely opaque PNG alpha channel without changing visible pixels.

Requires Pillow (see requirements-screenshots.txt). Non-opaque input is rejected.
Original captures can be retained outside the repository with --backup-root.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import struct
from pathlib import Path

from PIL import Image, PngImagePlugin

ROOT = Path(__file__).resolve().parents[2]


def normalize(path: Path, backup_root: Path | None) -> dict:
    before = path.read_bytes()
    with Image.open(path) as source:
        source.load()
        if source.format != "PNG" or source.mode not in ("RGB", "RGBA"):
            raise ValueError(f"Expected RGB/RGBA PNG: {path}")
        mode = source.mode
        alpha = source.getchannel("A").getextrema() if mode == "RGBA" else None
        if alpha is not None and alpha != (255, 255):
            raise ValueError(f"Refusing to remove non-opaque alpha {alpha}: {path}")
        rgb = source.convert("RGB")
        pixel_hash = hashlib.sha256(rgb.tobytes()).hexdigest()
        metadata = {key: source.info[key] for key in ("icc_profile", "exif", "dpi") if key in source.info}
        pnginfo = PngImagePlugin.PngInfo()
        # Retain the simulator capture's color-space metadata as exact chunks.
        offset = 8
        while offset + 12 <= len(before):
            size = struct.unpack(">I", before[offset:offset + 4])[0]
            key = before[offset + 4:offset + 8]
            if key in (b"sRGB", b"gAMA", b"cHRM"):
                pnginfo.add(key, before[offset + 8:offset + 8 + size])
            offset += size + 12
        if backup_root:
            try:
                relative = path.resolve().relative_to(ROOT)
            except ValueError:
                relative = Path(path.name)
            backup = backup_root / relative
            backup.parent.mkdir(parents=True, exist_ok=True)
            if backup.exists() and backup.read_bytes() != before:
                raise ValueError(f"Refusing to overwrite a different original: {backup}")
            shutil.copyfile(path, backup)
        temporary = path.with_name(path.name + ".rgb-tmp")
        try:
            rgb.save(temporary, format="PNG", pnginfo=pnginfo, **metadata)
            with Image.open(temporary) as result:
                result.load()
                if result.mode != "RGB" or result.size != source.size or result.tobytes() != rgb.tobytes():
                    raise ValueError(f"Decoded pixels changed: {path}")
                for key in ("icc_profile", "srgb", "exif"):
                    if result.info.get(key) != source.info.get(key):
                        raise ValueError(f"Color-space/EXIF metadata changed ({key}): {path}")
            temporary.replace(path)
        finally:
            temporary.unlink(missing_ok=True)
        return {"path": str(path.resolve()), "width": source.width, "height": source.height,
                "mode_before": mode, "mode_after": "RGB", "alpha_extrema_before": alpha,
                "decoded_rgb_sha256_before": pixel_hash, "decoded_rgb_sha256_after": pixel_hash,
                "sha256_before": hashlib.sha256(before).hexdigest(),
                "sha256_after": hashlib.sha256(path.read_bytes()).hexdigest(),
                "color_space_and_exif_preserved": True}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", type=Path, nargs="+")
    parser.add_argument("--backup-root", type=Path)
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    records = [normalize(path, args.backup_root) for path in args.paths]
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(records, indent=2) + "\n")
    print(f"Normalized {len(records)} PNG(s) to opaque RGB; decoded pixels and color metadata match.")


if __name__ == "__main__":
    main()
