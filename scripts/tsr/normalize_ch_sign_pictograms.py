#!/usr/bin/env python3
"""Crop the Swiss sign vectors to their artwork and rebuild their PNG renditions.

The ASTRA EPS-to-SVG conversion stores the artwork in a small region of a
1x1 canvas and adds a white background rectangle.  That canvas is useful for
the source conversion, but it is not a suitable display asset.  This script
keeps the vector paths intact, removes only that background rectangle, and
updates the SVG viewBox to the rendered artwork bounds before rasterizing.
"""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
CH_ROOT = ROOT / "shared/tsr/sign-pictograms/national/CH"
RASTER_SIZE = 2048
ALPHA_THRESHOLD = "12.55%"  # approximately alpha > 32/255


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_view_box(source: str) -> tuple[float, float, float, float]:
    match = re.search(r'\bviewBox="([^"]+)"', source)
    if not match:
        raise RuntimeError(f"SVG has no viewBox: {source[:120]!r}")
    values = [float(value) for value in match.group(1).replace(",", " ").split()]
    if len(values) != 4 or values[2] <= 0 or values[3] <= 0:
        raise RuntimeError(f"Invalid SVG viewBox: {match.group(1)!r}")
    return tuple(values)  # type: ignore[return-value]


def artwork_geometry(
    source: str, temporary_source: Path
) -> tuple[float, float, float, float]:
    source = re.sub(r'<rect id="background"[^>]*/>\n?', "", source)
    temporary_source.write_text(source)

    result = subprocess.run(
        [
            "magick",
            "-background",
            "none",
            str(temporary_source),
            "-resize",
            f"{RASTER_SIZE}x{RASTER_SIZE}",
            "-alpha",
            "extract",
            "-threshold",
            ALPHA_THRESHOLD,
            "-format",
            "%@",
            "info:",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    match = re.fullmatch(r"(\d+)x(\d+)\+(\d+)\+(\d+)", result.stdout.strip())
    if not match:
        raise RuntimeError(f"Could not determine artwork bounds for {svg}: {result.stdout!r}")
    width, height, left, top = (int(value) for value in match.groups())
    view_x, view_y, view_width, view_height = source_view_box(source)
    return (
        view_x + left / RASTER_SIZE * view_width,
        view_y + top / RASTER_SIZE * view_height,
        width / RASTER_SIZE * view_width,
        height / RASTER_SIZE * view_height,
    )


def normalized_dimensions(width: float, height: float) -> tuple[int, int]:
    if width >= height:
        return 256, max(1, round(256 * height / width))
    return max(1, round(256 * width / height)), 256


def normalize_svg(source: str, view_box: tuple[float, float, float, float]) -> tuple[str, int, int]:
    source = re.sub(r'<rect id="background"[^>]*/>\n?', "", source)
    x, y, width, height = view_box
    pixel_width, pixel_height = normalized_dimensions(width, height)
    view_box_text = f"{x:.12f} {y:.12f} {width:.12f} {height:.12f}"

    def replace_root(match: re.Match[str]) -> str:
        root = match.group(0)[:-1].rstrip()
        if re.search(r'\bwidth="', root):
            root = re.sub(r'\bwidth="[^"]+"', f'width="{pixel_width}"', root)
        else:
            root += f' width="{pixel_width}"'
        if re.search(r'\bheight="', root):
            root = re.sub(r'\bheight="[^"]+"', f'height="{pixel_height}"', root)
        else:
            root += f' height="{pixel_height}"'
        root = re.sub(r'\bviewBox="[^"]+"', f'viewBox="{view_box_text}"', root)
        if re.search(r'\bpreserveAspectRatio="', root):
            root = re.sub(r'\bpreserveAspectRatio="[^"]+"', 'preserveAspectRatio="none"', root)
        else:
            root += ' preserveAspectRatio="none"'
        return root + ' data-normalized="artwork-bounds">'

    normalized = re.sub(r"<svg\b[^>]*>", replace_root, source, count=1)
    if normalized == source or "<rect id=\"background\"" in normalized:
        raise RuntimeError("Failed to normalize SVG root or remove background")
    return normalized, pixel_width, pixel_height


def update_metadata(
    node: object,
    digests: dict[str, dict[str, str]],
    inherited_asset_id: str | None = None,
) -> None:
    if isinstance(node, dict):
        asset_id = node.get("asset_id") or node.get("artwork_id") or inherited_asset_id
        if isinstance(asset_id, str) and asset_id in digests:
            digest = digests[asset_id]
            if "original_sha256" in node:
                node.setdefault("source_original_sha256", node["original_sha256"])
                node["original_sha256"] = digest["svg"]
            if "png_sha256" in node:
                node["png_sha256"] = digest["png"]
            if "conversion" in node:
                node["conversion"] = "pstoedit_plot_svg_normalized_viewbox"
        for value in node.values():
            update_metadata(value, digests, asset_id if isinstance(asset_id, str) else None)
    elif isinstance(node, list):
        for value in node:
            update_metadata(value, digests, inherited_asset_id)


def main() -> None:
    originals = CH_ROOT / "originals"
    pngs = CH_ROOT / "png"
    digests: dict[str, dict[str, str]] = {}

    with tempfile.TemporaryDirectory(prefix="normalize-ch-signs-") as temporary_directory:
        temporary = Path(temporary_directory)
        for svg in sorted(originals.glob("*.svg")):
            source = svg.read_text()
            if 'data-normalized="artwork-bounds"' in source:
                digests[svg.stem] = {
                    "svg": sha256(svg),
                    "png": sha256(pngs / f"{svg.stem}.png"),
                }
                continue
            with (temporary / f"{svg.stem}.svg").open("w") as temporary_source:
                view_box = artwork_geometry(source, Path(temporary_source.name))
            normalized, width, height = normalize_svg(source, view_box)
            svg.write_text(normalized)

            png = pngs / f"{svg.stem}.png"
            subprocess.run(
                ["magick", "-background", "none", str(svg), "-depth", "8", str(png)],
                check=True,
            )
            actual = subprocess.run(
                ["magick", "identify", "-format", "%wx%h", str(png)],
                check=True,
                capture_output=True,
                text=True,
            ).stdout
            expected = f"{width}x{height}"
            if actual != expected:
                raise RuntimeError(f"Unexpected PNG dimensions for {png}: {actual} != {expected}")
            digests[svg.stem] = {"svg": sha256(svg), "png": sha256(png)}

    for manifest_path in (
        CH_ROOT / "manifest.json",
        CH_ROOT / "source-preparation-manifest.json",
        ROOT / "shared/tsr/prolix-ch-class-catalog-v1.json",
    ):
        manifest = json.loads(manifest_path.read_text())
        update_metadata(manifest, digests)
        manifest_path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    main()
