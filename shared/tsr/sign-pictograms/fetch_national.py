#!/usr/bin/env python3
"""Fetch and rasterize reviewed national sign artwork from pinned Commons sources.

The source files are matched to the applicable national regulation by the
checked-in source index. Commons is used only for the editable vector artwork;
the regulation URL, sign code, and semantic mapping are kept in the generated
manifest. This deliberately produces artwork/selection evidence, not a TSR
model release.
"""

from __future__ import annotations

import argparse
import hashlib
import html
import json
import re
import shutil
import struct
import subprocess
import tempfile
import time
import urllib.parse
import xml.etree.ElementTree as ET
from pathlib import Path


BASE = Path(__file__).resolve().parent
USER_AGENT = "YouSpeedAssetAudit/1.0 (https://github.com/volzinnovation/youspeed.de)"
COMMERCIAL_LICENSE_RE = re.compile(
    r"^CC BY(?:-SA)?(?: 2\.0| 3\.0| 4\.0)?$"
)


def commercial_use_permitted(license_name: str) -> bool:
    """Return whether the declared Commons licence permits commercial use.

    This is deliberately narrower than a general licence parser: the checked-in
    national set accepts public-domain/CC0 works and the CC BY/CC BY-SA family,
    all of which permit commercial use when their notice/share-alike terms are
    respected. Non-commercial licences are excluded before artwork is copied.
    """

    return license_name in {"Public domain", "CC0"} or bool(
        COMMERCIAL_LICENSE_RE.fullmatch(license_name)
    )


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def clean_html(value: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", value or "")).strip()


def safe_path(relative: str) -> Path:
    path = (BASE / relative).resolve()
    if not path.is_relative_to(BASE):
        raise ValueError(f"Unsafe asset path: {relative}")
    return path


def check_svg(data: bytes) -> None:
    # Some otherwise harmless Commons Illustrator exports carry an internal
    # namespace entity declaration.  Validate it without permitting any
    # external DTD, parameter entity, or external resource reference.
    validation_data = data
    if b"<!DOCTYPE" in data:
        if b"http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd" not in data:
            raise ValueError("Unexpected external SVG doctype")
        doctype = (
            re.search(rb"<!DOCTYPE\s+svg[\s\S]*?\]\s*>", data)
            if b"[" in data[data.find(b"<!DOCTYPE") :]
            else re.search(rb"<!DOCTYPE\s+svg[^>]*>", data)
        )
        if not doctype:
            raise ValueError("Malformed SVG doctype")
        internal_subset = doctype.group(0)
        entity_declarations = re.findall(rb"<!ENTITY[\s\S]*?>", internal_subset)
        if any(
            re.search(rb"<!ENTITY\s+%|\b(?:SYSTEM|PUBLIC)\b", declaration)
            for declaration in entity_declarations
        ):
            raise ValueError("External or parameter SVG entity is not allowed")
        validation_data = data[: doctype.start()] + data[doctype.end() :]
    root = ET.fromstring(validation_data)
    if root.tag != "{http://www.w3.org/2000/svg}svg":
        raise ValueError("Expected SVG document")
    for element in root.iter():
        if element.tag.rsplit("}", 1)[-1] in {"script", "foreignObject", "image"}:
            raise ValueError("Active or embedded SVG content is not allowed")
        for key, value in element.attrib.items():
            if key.rsplit("}", 1)[-1] == "href" and not value.startswith("#"):
                raise ValueError("External SVG reference is not allowed")


def commons_query(titles: list[str]) -> dict[str, dict]:
    # MediaWiki limits the `titles` query to 50 titles for anonymous callers.
    # Keep the source-selection file freely expandable without silently losing
    # pages after the first API batch.
    pages: dict[str, dict] = {}
    for offset in range(0, len(titles), 50):
        params = urllib.parse.urlencode(
            {
                "action": "query",
                "format": "json",
                "formatversion": "2",
                "titles": "|".join(titles[offset : offset + 50]),
                "prop": "imageinfo",
                "iiprop": "url|size|sha1|timestamp|extmetadata",
            }
        )
        raw = subprocess.check_output(
            [
                "curl",
                "--fail",
                "--silent",
                "--show-error",
                "--location",
                "--retry",
                "2",
                "--retry-delay",
                "5",
                "--max-time",
                "60",
                "--user-agent",
                USER_AGENT,
                f"https://commons.wikimedia.org/w/api.php?{params}",
            ]
        )
        pages.update(
            {
                page.get("title", ""): page
                for page in json.loads(raw).get("query", {}).get("pages", [])
            }
        )
        if offset + 50 < len(titles):
            time.sleep(1)
    return pages


def fetch_bytes(url: str) -> bytes:
    return subprocess.check_output(
        [
            "curl",
            "--fail",
            "--silent",
            "--show-error",
            "--location",
            "--retry",
            "2",
            "--retry-delay",
            "5",
            "--max-time",
            "60",
            "--user-agent",
            USER_AGENT,
            url,
        ]
    )


def render_png(svg_path: Path, png_path: Path, magick: str) -> tuple[bytes, int, int]:
    with tempfile.TemporaryDirectory(prefix="youspeed-sign-") as temp:
        rendered = Path(temp) / "sign.png"
        subprocess.run(
            [
                magick,
                "-background",
                "none",
                str(svg_path),
                "-filter",
                "Lanczos",
                "-resize",
                "256x256>",
                "-depth",
                "8",
                "-strip",
                "-define",
                "png:exclude-chunk=date,time",
                str(rendered),
            ],
            check=True,
        )
        data = rendered.read_bytes()
    width, height = struct.unpack(">II", data[16:24])
    if max(width, height) > 256:
        raise ValueError(f"Unexpected PNG size: {(width, height)}")
    png_path.parent.mkdir(parents=True, exist_ok=True)
    png_path.write_bytes(data)
    return data, width, height


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("country", choices=["FR", "NL", "BE"])
    parser.add_argument("--fetch", action="store_true", help="Fetch and render missing assets")
    args = parser.parse_args()
    country_dir = BASE / "national" / args.country
    source_path = country_dir / "sources.json"
    if not source_path.is_file():
        raise SystemExit(f"Missing source index: {source_path}")
    source = json.loads(source_path.read_text(encoding="utf-8"))
    artworks = source.get("artworks", [])
    if not artworks:
        raise SystemExit("Source index has no artwork entries")
    if not args.fetch:
        manifest_path = country_dir / "manifest.json"
        if not manifest_path.is_file():
            raise SystemExit(f"Missing generated manifest: {manifest_path}")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for item in manifest.get("artworks", []):
            original = safe_path(item["original_path"])
            png = safe_path(item["png_path"])
            if not original.is_file() or sha256(original.read_bytes()) != item["original_sha256"]:
                raise ValueError(f"Missing or changed SVG: {original}")
            if not png.is_file() or sha256(png.read_bytes()) != item["png_sha256"]:
                raise ValueError(f"Missing or changed PNG: {png}")
            check_svg(original.read_bytes())
        print(f"Verified {args.country} manifest with {len(manifest.get('artworks', []))} reviewed artwork entries")
        return 0
    magick = shutil.which("magick")
    if args.fetch and not magick:
        raise SystemExit("--fetch requires ImageMagick magick")
    if args.fetch:
        version = subprocess.check_output([magick, "-version"], text=True)
        if "ImageMagick 7.1.2-3" not in version:
            raise SystemExit("Pinned PNG generation requires ImageMagick 7.1.2-3")

    pages = commons_query([item["commons_title"] for item in artworks]) if args.fetch else {}
    generated: list[dict] = []
    for index, item in enumerate(artworks):
        title = item["commons_title"]
        page = pages.get(title, {})
        if args.fetch:
            if page.get("missing") or not page.get("imageinfo"):
                raise ValueError(f"Commons source missing: {title}")
            info = page["imageinfo"][0]
            metadata = info.get("extmetadata", {})
            license_name = clean_html(metadata.get("LicenseShortName", {}).get("value", ""))
            if not commercial_use_permitted(license_name):
                raise ValueError(
                    "Excluded because Commons metadata does not permit commercial "
                    f"use ({license_name!r}): {title}"
                )
            original_url = info["url"]
            original_data = fetch_bytes(original_url)
            check_svg(original_data)
            time.sleep(1)
            page_id = page["pageid"]
            revision = None
            revision_timestamp = info.get("timestamp")
            artist = clean_html(metadata.get("Artist", {}).get("value", ""))
            source_page_url = "https://commons.wikimedia.org/wiki/" + urllib.parse.quote(
                title.replace(" ", "_"), safe=":/(),'"
            )
            original_rel = f"national/{args.country}/originals/{item['asset_id']}.svg"
            png_rel = f"national/{args.country}/png/{item['asset_id']}.png"
            original_path = safe_path(original_rel)
            png_path = safe_path(png_rel)
            if original_path.exists() and sha256(original_path.read_bytes()) != sha256(original_data):
                raise ValueError(f"Existing SVG hash mismatch: {original_path}")
            original_path.parent.mkdir(parents=True, exist_ok=True)
            original_path.write_bytes(original_data)
            png_data, png_width, png_height = render_png(original_path, png_path, magick)
            record = {
                **item,
                "commons_page_id": page_id,
                "commons_page_revision": revision,
                "commons_page_revision_timestamp": revision_timestamp,
                "source_page_url": source_page_url,
                "source_page_permanent_url": f"https://commons.wikimedia.org/w/index.php?curid={page_id}",
                "original_url": original_url,
                "original_timestamp": info.get("timestamp"),
                "original_commons_sha1": info.get("sha1"),
                "original_path": original_rel,
                "original_sha256": sha256(original_data),
                "original_bytes": len(original_data),
                "png_source_url": original_url,
                "png_source_sha256": sha256(original_data),
                "png_path": png_rel,
                "png_sha256": sha256(png_data),
                "png_bytes": len(png_data),
                "png_width": png_width,
                "png_height": png_height,
                "license": license_name,
                "license_basis": "Commons metadata; vector checked against the official national regulation source",
                "license_basis_url": metadata.get("LicenseUrl", {}).get("value") or "https://creativecommons.org/share-your-work/cclicenses/",
                "commercial_use_permitted": True,
                "license_source_url": source_page_url,
                "license_source_permanent_url": f"https://commons.wikimedia.org/w/index.php?curid={page_id}",
                "license_provenance": {
                    "repository": "Wikimedia Commons",
                    "file_title": title,
                    "artist": artist,
                    "source_page_url": source_page_url,
                    "source_page_permanent_url": f"https://commons.wikimedia.org/w/index.php?curid={page_id}",
                    "original_url": original_url,
                    "commons_sha1": info.get("sha1"),
                    "declared_license": license_name,
                    "commercial_use_basis": "Commons file metadata licence declaration",
                },
                "attribution_required": license_name not in {"Public domain", "CC0"},
                "artist": artist,
                "source_credit": "Official national road-sign regulation; Commons vector rendition",
                "changes": "Original SVG retained; SVG rasterized locally to a transparent 256 × 256 PNG with metadata stripped.",
                "png_source_kind": "original_svg",
            }
        else:
            record = dict(item)
        generated.append(record)

    manifest = {
        "schema_version": 1,
        "country": args.country,
        "reviewed_at": source["reviewed_at"],
        "status": "core_reviewed_artwork",
        "runtime_status": "not_ready",
        "artwork_approval": source.get("artwork_approval", {}),
        "license_review": source.get("license_review", {}),
        "regulation_sources": source["regulation_sources"],
        "coverage_evidence": source.get("coverage_evidence", {}),
        "artworks": generated,
    }
    (country_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    selection = {
        "schema_version": 1,
        "country": args.country,
        "status": "core_reviewed_artwork",
        "runtime_status": "not_ready",
        "entries": [
            {
                "semantic_id": item["semantic_id"],
                "sign_code": item["sign_code"],
                "artwork_id": item["asset_id"],
                "mapping_status": item["mapping_status"],
                "mapping_basis": item["mapping_basis"],
                "source_model_class": item.get("model_class_label"),
                "runtime_model_class": None,
            }
            for item in generated
        ],
    }
    (country_dir / "selection.json").write_text(json.dumps(selection, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"{'Generated' if args.fetch else 'Wrote'} {args.country} manifest with {len(generated)} reviewed artwork entries")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
