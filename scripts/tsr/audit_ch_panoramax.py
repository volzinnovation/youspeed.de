#!/usr/bin/env python3
"""Audit Swiss Panoramax mapping coverage and official artwork archives.

This is an offline audit helper. It does not download or activate a model, and
it treats numeric speed-limit variants as model semantics rather than
pictogram assets. The mapping CSV is supplied by the caller so the audit can
run against a pinned external Panoramax snapshot.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import zipfile
from pathlib import Path, PurePosixPath


CODE_RE = re.compile(r"^(?P<base>\d+\.\d+(?:\.\d+)?)(?P<suffix>[a-z])?(?:\[(?P<value>[^]]+)\])?$")
ARCHIVE_RE = re.compile(r"^(?P<base>\d+\.\d+(?:\.\d+)?)(?:\s|\(|\.|$)", re.IGNORECASE)
RETIRED_CODES = {"1.17"}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def swiss_code(raw: str) -> dict[str, object]:
    value = raw.strip()
    if not value.startswith("CH:"):
        raise ValueError(f"Swiss mapping must start with CH:, got {raw!r}")
    code = value[3:]
    match = CODE_RE.fullmatch(code)
    if not match:
        raise ValueError(f"Unsupported Swiss sign code: {raw!r}")
    base = match.group("base")
    numeric_speed = base == "2.30" and match.group("value") is not None
    return {
        "raw": value,
        "code": code,
        "base_code": base,
        "variant_suffix": match.group("suffix"),
        "numeric_speed_variant": numeric_speed,
        "status": (
            "retired"
            if base in RETIRED_CODES
            else "numeric_speed_semantic"
            if numeric_speed
            else "artwork_candidate"
        ),
    }


def archive_codes(path: Path) -> set[str]:
    codes: set[str] = set()
    with zipfile.ZipFile(path) as archive:
        for member in archive.namelist():
            filename = PurePosixPath(member).name
            if not filename.lower().endswith((".eps", ".svg", ".wmf")):
                continue
            match = ARCHIVE_RE.match(filename)
            if match:
                codes.add(match.group("base"))
    return codes


def parse_archive_arg(value: str) -> tuple[str, Path]:
    label, separator, raw_path = value.partition("=")
    if not separator or not label or not raw_path:
        raise argparse.ArgumentTypeError("archive must be LABEL=PATH")
    return label, Path(raw_path)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mapping-csv", type=Path, required=True)
    parser.add_argument(
        "--astra-archive",
        action="append",
        type=parse_archive_arg,
        default=[],
        metavar="LABEL=PATH",
        help="Downloaded ASTRA ZIP; may be supplied more than once",
    )
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--panoramax-catalog-sample",
        type=Path,
        help="Saved read-only GeoJSON response from the Panoramax search API",
    )
    parser.add_argument(
        "--panoramax-bbox",
        default="5.9,45.8,10.6,47.9",
        help="Bbox recorded with --panoramax-catalog-sample",
    )
    parser.add_argument("--panoramax-limit", type=int, default=500)
    args = parser.parse_args()

    with args.mapping_csv.open(newline="", encoding="utf-8-sig") as handle:
        rows = list(csv.DictReader(handle))
    required = {"YOLO", "CH"}
    if not rows or not required.issubset(rows[0]):
        raise SystemExit(f"mapping CSV must contain {sorted(required)} columns")

    mapped: list[dict[str, object]] = []
    for row in rows:
        if row.get("CH", "").strip():
            item = swiss_code(row["CH"])
            item["model_class"] = row["YOLO"]
            mapped.append(item)

    archive_inventory = []
    available: set[str] = set()
    for label, path in args.astra_archive:
        if not path.is_file():
            raise SystemExit(f"missing ASTRA archive: {path}")
        codes = archive_codes(path)
        available.update(codes)
        archive_inventory.append(
            {
                "label": label,
                "file_name": path.name,
                "size_bytes": path.stat().st_size,
                "sha256": sha256_file(path),
                "sign_codes": len(codes),
            }
        )

    base_codes = {str(item["base_code"]) for item in mapped}
    numeric = [item for item in mapped if item["numeric_speed_variant"]]
    retired = [item for item in mapped if item["status"] == "retired"]
    artwork_candidates = [item for item in mapped if item["status"] == "artwork_candidate"]
    missing_archive = sorted(
        {str(item["base_code"]) for item in artwork_candidates} - available
    )
    for item in mapped:
        base = str(item["base_code"])
        if item["status"] == "retired":
            item["artwork_status"] = "retired_by_official_reference"
        elif item["numeric_speed_variant"]:
            item["artwork_status"] = "ui_schematic_numeric_exception"
        elif base in available:
            item["artwork_status"] = "official_archive_member"
        else:
            item["artwork_status"] = "official_archive_gap"

    catalog_sample = None
    if args.panoramax_catalog_sample:
        if not args.panoramax_catalog_sample.is_file():
            raise SystemExit(f"missing Panoramax catalog sample: {args.panoramax_catalog_sample}")
        payload = json.loads(args.panoramax_catalog_sample.read_text(encoding="utf-8"))
        features = payload.get("features", [])
        dates = [
            str(feature.get("properties", {}).get("datetime"))
            for feature in features
            if feature.get("properties", {}).get("datetime")
        ]
        coordinates = [
            feature.get("geometry", {}).get("coordinates", [])
            for feature in features
            if len(feature.get("geometry", {}).get("coordinates", [])) >= 2
        ]
        catalog_sample = {
            "endpoint": "https://api.panoramax.xyz/api/search",
            "bbox": args.panoramax_bbox,
            "limit": args.panoramax_limit,
            "sampled_features": len(features),
            "unique_collections": len({feature.get("collection") for feature in features}),
            "providers": sorted({
                provider.get("name")
                for feature in features
                for provider in feature.get("providers", [])
                if provider.get("name")
            }),
            "licenses": sorted({
                str(feature.get("properties", {}).get("license"))
                for feature in features
                if feature.get("properties", {}).get("license")
            }),
            "capture_datetime_min": min(dates) if dates else None,
            "capture_datetime_max": max(dates) if dates else None,
            "coordinate_bbox": [
                min(coordinate[0] for coordinate in coordinates),
                min(coordinate[1] for coordinate in coordinates),
                max(coordinate[0] for coordinate in coordinates),
                max(coordinate[1] for coordinate in coordinates),
            ] if coordinates else None,
            "note": "This is a metadata-only availability sample; it is not a training inventory and does not prove Swiss geographic completeness.",
        }

    result = {
        "schema_version": 1,
        "audit_id": "panoramax-ch-readiness-v1",
        "reviewed_at": "2026-09-17",
        "country": "CH",
        "mapping_source": {
            "path": args.mapping_csv.name,
            "location": "external workspace input supplied to the audit",
            "sha256": sha256_file(args.mapping_csv),
            "row_count": len(rows),
            "mapped_ch_rows": len(mapped),
            "unmapped_ch_rows": len(rows) - len(mapped),
        },
        "mapping_counts": {
            "unique_raw_ch_codes": len({str(item["code"]) for item in mapped}),
            "unique_base_codes": len(base_codes),
            "numeric_speed_variants": len(numeric),
            "retired_rows": len(retired),
            "artwork_candidate_base_codes": len({str(item["base_code"]) for item in artwork_candidates}),
        },
        "official_archive_audit": {
            "archive_count": len(archive_inventory),
            "archives": archive_inventory,
            "mapped_artwork_candidates_found": len(
                {str(item["base_code"]) for item in artwork_candidates} & available
            ),
            "mapped_artwork_candidates_missing": missing_archive,
            "retired_codes": sorted(RETIRED_CODES & base_codes),
            "notes": [
                "Archive presence proves source availability only; it does not grant reproduction rights.",
                "ASTRA downloads often contain legacy EPS/WMF alongside a smaller number of SVG files.",
                "The current ASTRA archive does not include 4.88 or 4.90 even though both remain official sign references; they need separately cleared artwork.",
            ],
        },
        "panoramax_inventory": {
            "swiss_dataset_available": False,
            "swiss_model_available": False,
            "bootstrap_dataset": "Panoramax/classified_de_road_signs",
            "bootstrap_validation_archive_sha256": "13ca882129a4e024fc865fc4a3187514a4554f8e323f612e338144fd1ff189ea",
            "bootstrap_validation_swiss_prefixed_members": 0,
            "public_catalog_sample": catalog_sample,
            "note": "Use existing country archives as detector/classifier bootstrap only; collect a Swiss, route-grouped corpus before claiming CH recognition.",
        },
        "model_readiness": {
            "status": "not_ready",
            "target_pipeline": "YOLOX-Nano-derived proposal detector + MobileNetV3-Large crop classifier + temporal passage reducer",
            "required_exports": ["coreml", "litert"],
            "blocking_gates": [
                "Swiss Panoramax imagery and annotation inventory",
                "route/source-grouped train/validation/holdout split",
                "CH legal/action review and cleared pictogram set",
                "Core ML/LiteRT export parity",
                "on-device iPhone and Android latency/thermal evidence",
                "dataset, model-lineage and Ultralytics license review",
            ],
        },
        "entries": mapped,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({
        "output": str(args.output),
        "mapped_ch_rows": len(mapped),
        "unique_base_codes": len(base_codes),
        "archive_gap_base_codes": missing_archive,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
