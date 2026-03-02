#!/usr/bin/env python3
"""Plan single-country vs multi-region v3 bundle generation from Geofabrik metadata.

Rule:
- If the country PBF is <= threshold, keep a single country bundle.
- If it is > threshold, switch to Geofabrik child regions (for example Germany Bundeslaender).
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Dict, Iterable, List, Optional


def _load_index(index_path: Path) -> Dict:
    return json.loads(index_path.read_text(encoding="utf-8"))


def _iter_features(index_payload: Dict) -> Iterable[Dict]:
    for feature in index_payload.get("features", []):
        props = feature.get("properties")
        if isinstance(props, dict):
            yield props


def _find_feature_by_id(index_payload: Dict, geofabrik_id: str) -> Optional[Dict]:
    target = geofabrik_id.strip().lower()
    for props in _iter_features(index_payload):
        if str(props.get("id", "")).strip().lower() == target:
            return props
    return None


def _child_regions(index_payload: Dict, parent_id: str) -> List[Dict]:
    out: List[Dict] = []
    for props in _iter_features(index_payload):
        if str(props.get("parent", "")).strip().lower() != parent_id.strip().lower():
            continue
        urls = props.get("urls") or {}
        if not isinstance(urls, dict):
            continue
        if not urls.get("pbf"):
            continue
        out.append(props)
    out.sort(key=lambda p: str(p.get("name", p.get("id", ""))).lower())
    return out


def _entry_from_props(props: Dict) -> Dict:
    urls = props.get("urls") or {}
    iso_values = props.get("iso3166-1:alpha2")
    iso2 = ""
    if isinstance(iso_values, list) and iso_values:
        iso2 = str(iso_values[0]).upper()
    return {
        "id": str(props.get("id", "")),
        "name": str(props.get("name", props.get("id", ""))),
        "iso2": iso2,
        "pbf_url": urls.get("pbf"),
        "poly_url": urls.get("poly"),
        "parent": props.get("parent"),
    }


def build_plan(
    *,
    index_payload: Dict,
    country_id: str,
    country_pbf_bytes: int,
    max_country_pbf_bytes: int,
) -> Dict:
    country = _find_feature_by_id(index_payload, country_id)
    if country is None:
        raise SystemExit(f"Country id not found in Geofabrik index: {country_id}")

    use_subregions = country_pbf_bytes > max_country_pbf_bytes
    if use_subregions:
        regions = _child_regions(index_payload, country_id)
        if not regions:
            raise SystemExit(
                f"Country exceeds threshold ({country_pbf_bytes} > {max_country_pbf_bytes}) "
                f"but no child regions were found for '{country_id}'."
            )
        selected = [_entry_from_props(props) for props in regions]
        mode = "regional_shards"
    else:
        selected = [_entry_from_props(country)]
        mode = "single_country_bundle"

    return {
        "format": "youspeed.v3.country.bundle.plan",
        "schema_version": 1,
        "country_id": country_id,
        "country_name": str(country.get("name", country_id)),
        "country_pbf_bytes": int(country_pbf_bytes),
        "max_country_pbf_bytes": int(max_country_pbf_bytes),
        "mode": mode,
        "regions": selected,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Plan country bundle sharding strategy from Geofabrik metadata")
    parser.add_argument("--country-id", required=True, help="Geofabrik country id (for example: germany)")
    parser.add_argument(
        "--country-pbf",
        default="",
        help="Path to country PBF used to decide threshold crossing; optional if --country-pbf-bytes is provided",
    )
    parser.add_argument(
        "--country-pbf-bytes",
        type=int,
        default=-1,
        help="Optional explicit country PBF size in bytes (overrides --country-pbf file size)",
    )
    parser.add_argument(
        "--max-country-pbf-bytes",
        type=int,
        default=1_000_000_000,
        help="Threshold above which regional sharding is used (default: 1,000,000,000)",
    )
    parser.add_argument(
        "--geofabrik-index",
        default="mapdata/build/geofabrik/index-v1.json",
        help="Path to Geofabrik index-v1.json (download beforehand)",
    )
    parser.add_argument(
        "--out-json",
        required=True,
        help="Output plan JSON path",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.max_country_pbf_bytes <= 0:
        raise SystemExit("--max-country-pbf-bytes must be > 0")

    if args.country_pbf_bytes >= 0:
        country_pbf_bytes = int(args.country_pbf_bytes)
    else:
        if not args.country_pbf:
            raise SystemExit("Provide either --country-pbf-bytes or --country-pbf")
        pbf_path = Path(args.country_pbf)
        if not pbf_path.exists():
            raise SystemExit(f"Country PBF not found: {pbf_path}")
        country_pbf_bytes = pbf_path.stat().st_size

    index_path = Path(args.geofabrik_index)
    if not index_path.exists():
        raise SystemExit(f"Geofabrik index file not found: {index_path}")
    index_payload = _load_index(index_path)
    plan = build_plan(
        index_payload=index_payload,
        country_id=args.country_id,
        country_pbf_bytes=country_pbf_bytes,
        max_country_pbf_bytes=args.max_country_pbf_bytes,
    )

    out_path = Path(args.out_json)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote plan: {out_path}")
    print(f"Mode: {plan['mode']} (regions={len(plan['regions'])})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
