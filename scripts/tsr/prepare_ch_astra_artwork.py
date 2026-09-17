#!/usr/bin/env python3
"""Prepare a reproducible CH SVG/PNG artwork set from ASTRA archives.

The output is explicitly a source-preparation set, not a runtime release. It
keeps the ASTRA archive/member identity and checksums for the later legal and
mapping review. Numeric 2.30 speed variants, retired 1.17, and owner-excluded
4.88/4.90 are omitted by policy.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import tempfile
import zipfile
from pathlib import Path, PurePosixPath


CODE_RE = re.compile(r"^CH:(?P<base>\d+\.\d+(?:\.\d+)?)(?P<suffix>[a-z])?(?:\[[^]]+\])?$")
MEMBER_RE = re.compile(r"^(?P<base>\d+\.\d+(?:\.\d+)?)(?=\s|\(|\.(?:eps|svg|wmf)$)", re.I)
RETIRED = {"1.17"}
EXCLUDED = {"4.88", "4.90"}


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def base_code(raw: str) -> tuple[str, bool]:
    match = CODE_RE.fullmatch(raw.strip())
    if not match:
        raise ValueError(f"Unsupported CH code: {raw!r}")
    base = match.group("base")
    return base, base == "2.30" and "[" in raw


def source_score(member: str, base: str) -> tuple[int, int, str]:
    filename = PurePosixPath(member).name
    extension = filename.rsplit(".", 1)[-1].lower()
    extension_score = {"svg": 0, "eps": 1, "wmf": 2}[extension]
    # Prefer the unqualified file, then the bilingual D+F rendition, then
    # other language/numbered variants.
    suffix = filename[len(base) : -len(extension) - 1]
    if suffix == "":
        variant_score = 0
    elif suffix.strip() == "(D+F)":
        variant_score = 1
    elif re.fullmatch(r"\s*\([0-9]+\)", suffix):
        variant_score = 3
    else:
        variant_score = 2
    return extension_score, variant_score, filename


def load_mapping(path: Path) -> dict[str, dict[str, str]]:
    by_base: dict[str, dict[str, str]] = {}
    with path.open(newline="", encoding="utf-8-sig") as handle:
        for row in csv.DictReader(handle):
            raw = (row.get("CH") or "").strip()
            if not raw:
                continue
            base, numeric_speed = base_code(raw)
            if numeric_speed or base in RETIRED or base in EXCLUDED:
                continue
            by_base.setdefault(
                base,
                {
                    "sign_code": raw,
                    "model_class_label": (row.get("YOLO") or "").strip(),
                },
            )
    return by_base


def archive_members(paths: list[tuple[str, Path]]) -> dict[str, list[tuple[str, Path, str]]]:
    found: dict[str, list[tuple[str, Path, str]]] = {}
    for label, path in paths:
        with zipfile.ZipFile(path) as archive:
            for member in archive.namelist():
                filename = PurePosixPath(member).name
                if not filename.lower().endswith((".eps", ".svg", ".wmf")):
                    continue
                match = MEMBER_RE.match(filename)
                if match:
                    found.setdefault(match.group("base"), []).append((label, path, member))
    return found


def extract(archive: Path, member: str, destination: Path) -> None:
    with zipfile.ZipFile(archive) as handle:
        destination.write_bytes(handle.read(member))


def convert_to_svg(source: Path, destination: Path) -> str:
    if source.suffix.lower() == ".svg":
        destination.write_bytes(source.read_bytes())
        return "source_svg"
    result = subprocess.run(
        ["pstoedit", "-f", "plot-svg", "-dt", "-flat", "0.5", str(source), str(destination)],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"pstoedit failed for {source.name}: {result.stderr[-500:]}")
    return "pstoedit_plot_svg"


def rasterize(svg: Path, png: Path) -> None:
    result = subprocess.run(
        [
            "magick",
            "-background",
            "none",
            str(svg),
            "-resize",
            "256x256",
            "-gravity",
            "center",
            "-extent",
            "256x256",
            "-strip",
            str(png),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(f"ImageMagick failed for {svg.name}: {result.stderr[-500:]}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping-csv", type=Path, required=True)
    parser.add_argument("--astra-archive", action="append", required=True, metavar="LABEL=PATH")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    archives: list[tuple[str, Path]] = []
    for raw in args.astra_archive:
        label, separator, path = raw.partition("=")
        if not separator or not label or not path:
            parser.error("--astra-archive must be LABEL=PATH")
        archive = Path(path)
        if not archive.is_file():
            parser.error(f"missing ASTRA archive: {archive}")
        archives.append((label, archive))

    requested = load_mapping(args.mapping_csv)
    members = archive_members(archives)
    missing = sorted(set(requested) - set(members), key=lambda value: tuple(map(int, value.split("."))))
    if missing:
        raise SystemExit(f"No ASTRA member found for in-scope codes: {', '.join(missing)}")

    originals = args.output / "originals"
    pngs = args.output / "png"
    originals.mkdir(parents=True, exist_ok=True)
    pngs.mkdir(parents=True, exist_ok=True)
    artworks = []
    with tempfile.TemporaryDirectory(prefix="ch-astra-artwork-") as temporary:
        temporary_path = Path(temporary)
        for base in sorted(requested, key=lambda value: tuple(map(int, value.split(".")))):
            candidates = sorted(members[base], key=lambda item: source_score(item[2], base))
            label, archive, member = candidates[0]
            source = temporary_path / f"{base}.source{PurePosixPath(member).suffix.lower()}"
            extract(archive, member, source)
            svg = originals / f"ch-{base.replace('.', '-')}.svg"
            conversion = convert_to_svg(source, svg)
            png = pngs / f"ch-{base.replace('.', '-')}.png"
            rasterize(svg, png)
            artworks.append(
                {
                    "asset_id": f"ch-{base.replace('.', '-')}",
                    "sign_code": requested[base]["sign_code"],
                    "model_class_label": requested[base]["model_class_label"],
                    "base_code": base,
                    "original_path": str(svg.relative_to(args.output)),
                    "original_sha256": sha256_file(svg),
                    "png_path": str(png.relative_to(args.output)),
                    "png_sha256": sha256_file(png),
                    "source_archive_label": label,
                    "source_archive": archive.name,
                    "source_archive_sha256": sha256_file(archive),
                    "source_member": member,
                    "source_member_sha256": sha256_bytes(zipfile.ZipFile(archive).read(member)),
                    "conversion": conversion,
                    "license_status": "source_preparation_only_redistribution_review_pending",
                }
            )

    manifest = {
        "schema_version": 1,
        "country": "CH",
        "status": "source_preparation_only",
        "runtime_status": "not_ready",
        "scope": {
            "artwork_base_codes": len(artworks),
            "excluded_base_codes": sorted(RETIRED | EXCLUDED),
            "numeric_speed_base_code": "2.30",
        },
        "source_policy": "ASTRA official vector archive; source availability is not redistribution permission.",
        "artworks": artworks,
    }
    (args.output / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"status": manifest["status"], "artwork_base_codes": len(artworks), "output": str(args.output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
