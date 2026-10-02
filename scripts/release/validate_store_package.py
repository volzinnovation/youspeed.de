#!/usr/bin/env python3
"""Validate local listing limits, image specifications and Fastlane parity.

This check does not approve runtime behavior, legal rights, privacy answers,
console availability or a store submission. It never contacts either store.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
APPLE_LOCALES = ("de-DE", "en-US", "fr-FR", "nl-NL")
PLAY_LOCALES = APPLE_LOCALES + ("es-ES", "it-IT", "pl-PL", "pt-BR", "sv-SE")
APPLE_LIMITS = {"name.txt": 30, "subtitle.txt": 30, "description.txt": 4000,
                "promotional_text.txt": 170, "release_notes.txt": 4000,
                "keywords.txt": 100}
PLAY_LIMITS = {"title.txt": 30, "short_description.txt": 80,
               "full_description.txt": 4000, "release_notes.txt": 500}
APPLE_IMAGES = ("01-safe-speed.png", "02-camera-speed-limit.png", "03-secondary-sign.png",
                "04-dashcam.png", "05-france-fine.png", "06-switzerland-fine.png",
                "07-belgium-fine.png", "08-netherlands-fine.png",
                "09-pedestrian-zone.png", "10-autobahn-unlimited.png")
PLAY_IMAGES = ("01-safe-speed.png", "02-dashcam.png", "03-camera-recognition.png",
               "04-traffic-signs.png", "05-france-fine.png", "06-switzerland-fine.png",
               "07-belgium-fine.png", "08-netherlands-warning.png")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", type=Path, help="Write the local evidence as JSON")
    args = parser.parse_args()
    errors: list[str] = []
    files: list[dict] = []

    def problem(path: Path, message: str) -> None:
        errors.append(f"{path.relative_to(ROOT)}: {message}")

    def record(path: Path, **details: object) -> None:
        raw = path.read_bytes()
        files.append({"path": str(path.relative_to(ROOT)), "bytes": len(raw),
                      "sha256": hashlib.sha256(raw).hexdigest(), **details})

    def text_file(path: Path, limit: int | None = None, byte_limit: bool = False) -> str:
        if not path.is_file():
            problem(path, "missing")
            return ""
        value = path.read_text(encoding="utf-8").strip()
        count = len(value.encode("utf-8")) if byte_limit else len(value)
        if not value:
            problem(path, "empty")
        if limit is not None and count > limit:
            problem(path, f"length {count} exceeds {limit}")
        record(path, length=count)
        return value

    def png(path: Path, specification: str) -> None:
        if not path.is_file():
            problem(path, "missing")
            return
        raw = path.read_bytes()
        if len(raw) < 33 or raw[:8] != b"\x89PNG\r\n\x1a\n":
            problem(path, "invalid PNG header")
            return
        width, height, depth, color = struct.unpack(">IIBB", raw[16:26])
        transparency = color in (4, 6)
        offset = 8
        while offset + 12 <= len(raw):
            size = struct.unpack(">I", raw[offset:offset + 4])[0]
            if raw[offset + 4:offset + 8] == b"tRNS":
                transparency = True
            offset += size + 12
        if specification == "apple":
            if (width, height) not in {(1260, 2736), (1290, 2796), (1320, 2868)}:
                problem(path, f"unexpected 6.9-inch size {width}×{height}")
            if transparency:
                problem(path, "Apple screenshots must have no alpha channel")
        elif specification == "play":
            if min(width, height) < 320 or max(width, height) > 3840 or max(width, height) > 2 * min(width, height):
                problem(path, f"invalid Play screenshot size {width}×{height}")
        elif specification == "feature":
            if (width, height) != (1024, 500) or transparency:
                problem(path, "feature graphic must be opaque 1024×500 PNG")
        elif specification == "icon" and (width, height) != (512, 512):
            problem(path, "Play icon must be 512×512")
        record(path, width=width, height=height, png_bit_depth=depth, alpha=transparency)

    def identical(left: Path, right: Path) -> None:
        if not right.is_file() or left.read_bytes() != right.read_bytes():
            problem(right, f"does not match {left.relative_to(ROOT)}")

    gradle = (ROOT / "android/app/build.gradle.kts").read_text()
    version_match = re.search(r'releaseBaseVersionCode\s*=.*?"(\d+)"', gradle)
    version_code = version_match.group(1) if version_match else None
    if not version_code:
        errors.append("Cannot resolve Android source version code")

    for locale in APPLE_LOCALES:
        metadata = ROOT / "store/apple/metadata" / locale
        for name, limit in APPLE_LIMITS.items():
            text_file(metadata / name, limit, byte_limit=name == "keywords.txt")
        for name in ("support_url.txt", "privacy_url.txt"):
            if not text_file(metadata / name).startswith("https://"):
                problem(metadata / name, "must use an HTTPS URL")
        text_file(metadata / "review_notes.md")
        directory = ROOT / "store/apple/screenshots" / locale / "iphone-6.9"
        if {p.name for p in directory.glob("*.png")} != set(APPLE_IMAGES):
            problem(directory, "gallery must contain exactly the selected ten images")
        for name in APPLE_IMAGES:
            png(directory / name, "apple")

    for locale in PLAY_LOCALES:
        metadata = ROOT / "store/android/metadata" / locale
        fastlane = ROOT / "fastlane/metadata/android" / locale
        for name, limit in PLAY_LIMITS.items():
            text_file(metadata / name, limit)
            if name != "release_notes.txt" and (metadata / name).is_file():
                identical(metadata / name, fastlane / name)
        if version_code:
            identical(metadata / "release_notes.txt", fastlane / "changelogs" / f"{version_code}.txt")
        text_file(metadata / "review_instructions.md")
        if not text_file(metadata / "privacy_policy_url.txt").startswith("https://"):
            problem(metadata / "privacy_policy_url.txt", "must use an HTTPS URL")
        listing = ROOT / "store/android/listing" / locale
        for name, specification, mirror in (("feature-graphic-1024x500.png", "feature", "featureGraphic.png"),
                                             ("icon-512.png", "icon", "icon.png")):
            png(listing / name, specification)
            if (listing / name).is_file():
                identical(listing / name, fastlane / "images" / mirror)
        gallery = listing / "phone-screenshots"
        if {p.name for p in gallery.glob("*.png")} != set(PLAY_IMAGES):
            problem(gallery, "gallery must contain exactly the selected eight images")
        mirror_gallery = fastlane / "images/phoneScreenshots"
        if {p.name for p in mirror_gallery.glob("*.png")} != set(PLAY_IMAGES):
            problem(mirror_gallery, "gallery must contain exactly the selected eight images")
        for name in PLAY_IMAGES:
            png(gallery / name, "play")
            if (gallery / name).is_file():
                identical(gallery / name, fastlane / "images/phoneScreenshots" / name)

    report = {"format": "youspeed.store-package.validation.v1", "android_version_code": version_code,
              "apple_locales": list(APPLE_LOCALES), "play_locales": list(PLAY_LOCALES),
              "status": "passed" if not errors else "failed", "errors": errors, "files": files}
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(f"Checked {len(files)} metadata/image files; {len(errors)} error(s)")
    for error in errors:
        print(error, file=sys.stderr)
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
