#!/usr/bin/env python3
"""Build presentation-only source contours; never alter the shared sign artwork.

Requires Pillow and NumPy. Both apps draw the same small PNG behind the original
image. All silhouette processing happens here, never in the driving UI.
"""
from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[2] / "shared/tsr/sign-pictograms"
REFERENCE_SIZE = 256
PADDING = 16


def dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    """Disk dilation, without an additional image-processing dependency."""
    output = np.zeros_like(mask)
    height, width = mask.shape
    for dy in range(-radius, radius + 1):
        for dx in range(-radius, radius + 1):
            if dx * dx + dy * dy > radius * radius:
                continue
            y0, y1 = max(0, dy), min(height, height + dy)
            x0, x1 = max(0, dx), min(width, width + dx)
            output[y0:y1, x0:x1] |= mask[y0-dy:y1-dy, x0-dx:x1-dx]
    return output


def contour_png(source: bytes) -> bytes:
    image = Image.open(io.BytesIO(source)).convert("RGBA")
    scale = REFERENCE_SIZE / max(image.size)
    alpha = image.getchannel("A").resize(
        tuple(round(size * scale) for size in image.size), Image.Resampling.LANCZOS)
    side = REFERENCE_SIZE + PADDING * 2
    silhouette = Image.new("L", (side, side))
    silhouette.paste(alpha.point(lambda a: 255 if a >= 128 else 0),
                     ((side - alpha.width) // 2, (side - alpha.height) // 2))
    # Fill interior holes so lettering and artwork cutouts acquire no contour.
    exterior = silhouette.copy()
    ImageDraw.floodfill(exterior, (0, 0), 128)
    solid = np.asarray(exterior) != 128
    backing = dilate(solid, 16) & ~dilate(solid, 6)
    white = dilate(solid, 14) & ~dilate(solid, 8)
    rgba = np.zeros((side, side, 4), dtype=np.uint8)
    rgba[backing, 3] = 255
    rgba[white] = (255, 255, 255, 255)
    output = io.BytesIO()
    Image.fromarray(rgba).save(output, format="PNG", optimize=True)
    return output.getvalue()


def generate(root: Path = ROOT, check: bool = False) -> int:
    destination = root / "contours"
    manifest = json.loads((root / "manifest.json").read_text())
    entries = []
    payloads = {}
    for artwork in sorted(manifest["artworks"], key=lambda item: item["png_path"]):
        source_path = artwork["png_path"]
        source = (root / source_path).read_bytes()
        source_hash = hashlib.sha256(source).hexdigest()
        if source_hash != artwork["png_sha256"]:
            raise ValueError(f"Shared artwork hash mismatch: {source_path}")
        name = Path(source_path).name
        data = contour_png(source)
        payloads[name] = data
        entries.append({"source_path": source_path, "source_sha256": source_hash,
                        "contour_path": "contours/" + name,
                        "contour_sha256": hashlib.sha256(data).hexdigest()})
    metadata = {"schema_version": 1, "reference_size": REFERENCE_SIZE,
                "padding": PADDING, "display_scale": 1.125,
                "purpose": "MobiData source decoration only; original artwork is unchanged.",
                "artworks": entries}
    payloads["manifest.json"] = (json.dumps(metadata, indent=2) + "\n").encode()
    if check:
        for name, expected in payloads.items():
            if not (destination / name).is_file() or (destination / name).read_bytes() != expected:
                raise ValueError(f"Missing or outdated contour: {name}")
        if {p.name for p in destination.iterdir()} != set(payloads):
            raise ValueError("Unexpected contour files")
    else:
        destination.mkdir(exist_ok=True)
        for name, data in payloads.items():
            (destination / name).write_bytes(data)
    return len(entries)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    count = generate(check=arguments.check)
    print(f"{'Verified' if arguments.check else 'Generated'} {count} shared source contours")
