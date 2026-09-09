#!/usr/bin/env python3
"""Verify pictograms offline, or restore pinned SVG/PNG assets with --fetch.

Fetching needs curl, ImageMagick 7.1.2-3 and network access. Downloads are
sequential and paced; a changed upstream file or renderer never updates hashes.
"""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile
import time
import xml.etree.ElementTree as ET

BASE = Path(__file__).resolve().parent


def sha256(data):
    return hashlib.sha256(data).hexdigest()


def safe_path(relative):
    path = (BASE / relative).resolve()
    if not path.is_relative_to(BASE):
        raise ValueError(f"Unsafe asset path: {relative}")
    return path


def valid(path, expected):
    return path.is_file() and sha256(path.read_bytes()) == expected


def check_svg(data):
    if b"<!ENTITY" in data or b"<!DOCTYPE" in data:
        raise ValueError("External/entity-bearing SVG is not allowed")
    root = ET.fromstring(data)
    if root.tag != "{http://www.w3.org/2000/svg}svg":
        raise ValueError("Expected SVG document")
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] in {"script", "foreignObject", "image"}:
            raise ValueError("Active or embedded SVG content is not allowed")
        for key, value in element.attrib.items():
            if key.rsplit("}", 1)[-1] == "href" and not value.startswith("#"):
                raise ValueError("External SVG reference is not allowed")


def restore(artwork, magick):
    original = safe_path(artwork["original_path"])
    if not valid(original, artwork["original_sha256"]):
        # Never overwrite an existing edited/corrupt asset silently.
        if original.exists():
            raise ValueError(f"Existing SVG hash mismatch: {original}")
        time.sleep(2)
        data = subprocess.check_output([
            "curl", "--fail", "--silent", "--show-error", "--location",
            "--retry", "2", "--retry-delay", "30", "--max-time", "45",
            "--user-agent",
            "YouSpeedAssetAudit/1.0 (https://github.com/volzinnovation/youspeed.de)",
            artwork["original_url"],
        ])
        if sha256(data) != artwork["original_sha256"]:
            raise ValueError(f"Changed upstream SVG: {artwork['sign_code']}")
        check_svg(data)
        original.parent.mkdir(parents=True, exist_ok=True)
        original.write_bytes(data)
    png = safe_path(artwork["png_path"])
    if valid(png, artwork["png_sha256"]):
        return
    if png.exists():
        raise ValueError(f"Existing PNG hash mismatch: {png}")
    check_svg(original.read_bytes())
    with tempfile.TemporaryDirectory() as directory:
        rendered = Path(directory) / "sign.png"
        source = original
        input_options = ["-background", "none"]
        if artwork.get("png_source_kind") == "commons_png":
            # Some SVG constructs render incorrectly in ImageMagick. Those
            # exceptions use a separately pinned Commons PNG rendition.
            time.sleep(2)
            data = subprocess.check_output([
                "curl", "--fail", "--silent", "--show-error", "--location",
                "--retry", "2", "--retry-delay", "30", "--max-time", "45",
                artwork["png_source_url"],
            ])
            if sha256(data) != artwork["png_source_sha256"] or not data.startswith(b"\x89PNG\r\n\x1a\n"):
                raise ValueError(f"Changed Commons PNG: {artwork['sign_code']}")
            source = Path(directory) / "source.png"
            source.write_bytes(data)
            input_options = []
        subprocess.run([
            magick, *input_options, str(source), "-filter", "Lanczos",
            "-resize", "256x256>", "-depth", "8", "-strip", "-define",
            "png:exclude-chunk=date,time", str(rendered),
        ], check=True)
        data = rendered.read_bytes()
        if sha256(data) != artwork["png_sha256"]:
            raise ValueError(f"Renderer output changed: {artwork['sign_code']}")
        png.parent.mkdir(parents=True, exist_ok=True)
        png.write_bytes(data)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch", action="store_true", help="Restore missing pinned assets")
    args = parser.parse_args()
    manifest = json.loads((BASE / "manifest.json").read_text())
    magick = shutil.which("magick")
    if args.fetch:
        if not magick:
            parser.error("--fetch requires ImageMagick 7.1.2-3 (magick)")
        version = subprocess.check_output([magick, "-version"], text=True)
        if "ImageMagick 7.1.2-3" not in version:
            parser.error("Pinned PNG generation requires ImageMagick 7.1.2-3")
    for artwork in manifest["artworks"]:
        if args.fetch:
            restore(artwork, magick)
        for kind in ["original", "png"]:
            path = safe_path(artwork[f"{kind}_path"])
            if not valid(path, artwork[f"{kind}_sha256"]):
                raise ValueError(f"Missing asset or hash mismatch: {path}")
            if path.stat().st_size != artwork[f"{kind}_bytes"]:
                raise ValueError(f"Size mismatch: {path}")
        check_svg(safe_path(artwork["original_path"]).read_bytes())
        data = safe_path(artwork["png_path"]).read_bytes()
        if data[:8] != b"\x89PNG\r\n\x1a\n":
            raise ValueError("Invalid PNG")
        width, height = struct.unpack(">II", data[16:24])
        if (width, height) != (artwork["png_width"], artwork["png_height"]) or max(width, height) > 256:
            raise ValueError(f"PNG dimensions changed: {artwork['sign_code']}")
        if artwork["license"] != "Public domain" or artwork["attribution_required"]:
            raise ValueError("Unexpected license; review before adding this asset")
        if artwork.get("png_source_kind") not in {"original_svg", "commons_png"}:
            raise ValueError("Unknown raster source kind")
    print(f"Verified {len(manifest['artworks'])} SVG/PNG pairs and their provenance.")


if __name__ == "__main__":
    main()
