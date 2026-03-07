#!/usr/bin/env python3
"""Resolve country-level release parameters for incremental bundle workflows."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Dict

SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import generate_v3_country_bundles as bundles


def _updates_url_from_pbf_url(pbf_url: str) -> str:
    url = pbf_url.strip()
    suffix = "-latest.osm.pbf"
    if not url.endswith(suffix):
        raise SystemExit(f"Unable to derive Geofabrik updates URL from PBF URL: {pbf_url}")
    return f"{url[:-len(suffix)]}-updates/"


def _download_file(url: str, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    try:
        with urllib.request.urlopen(url, timeout=120) as resp, tmp_path.open("wb") as out:
            out.write(resp.read())
    except Exception:
        subprocess.run(
            [
                "curl",
                "-L",
                "--fail",
                "--silent",
                "--show-error",
                url,
                "-o",
                str(tmp_path),
            ],
            check=True,
        )
    tmp_path.replace(out_path)


def resolve_country_release_plan(
    *,
    repo_root: Path,
    bundle_country: str,
    geofabrik_index: Path,
    bundle_target_config: Path,
    geofabrik_index_url: str,
) -> Dict[str, str]:
    country_id = bundle_country.strip().lower()
    if not country_id:
        raise SystemExit("--bundle-country must not be empty")

    if not geofabrik_index.exists():
        _download_file(geofabrik_index_url, geofabrik_index)

    index_payload = bundles._load_geofabrik_index(geofabrik_index)
    index_by_id, _ = bundles._build_index_maps(index_payload)

    config_countries = bundles._load_bundle_target_config(bundle_target_config)
    config_country = {row.country_id: row for row in config_countries}.get(country_id)
    iso2_override = config_country.iso2 if config_country is not None else ""

    target = bundles.plan_single_region_target(
        region_id=country_id,
        index_by_id=index_by_id,
        iso2_override=iso2_override,
    )

    region_slug = bundles._slug(target.region_id)
    region_asset_id = bundles._id_token(target.region_id)
    iso3 = target.iso3.upper()
    pbf_asset_name = f"{iso3}-latest.osm.pbf"
    state_asset_name = f"{iso3}.diff_state.json"
    report_asset_name = f"diff_update.{iso3}.latest.json"

    poly_name = Path(target.poly_url).name if target.poly_url else f"{region_slug}.poly"

    return {
        "bundle_country": country_id,
        "country_name": target.country_name,
        "country_code": iso3,
        "iso2": target.iso2.upper(),
        "iso3": iso3,
        "region_id": target.region_id,
        "region_slug": region_slug,
        "pbf_url": target.pbf_url,
        "poly_url": target.poly_url or "",
        "updates_url": _updates_url_from_pbf_url(target.pbf_url),
        "bundle_release_tag_default": region_asset_id,
        "bundle_release_title_default": f"{target.country_name} YouSpeed Data",
        "pbf_release_tag_default": f"{iso3.lower()}-pbf-latest",
        "pbf_release_title_default": f"{iso3} latest PBF snapshot",
        "pbf_asset_name": pbf_asset_name,
        "pbf_parts_meta_asset_name": f"{pbf_asset_name}.parts.json",
        "state_asset_name": state_asset_name,
        "report_asset_name": report_asset_name,
        "daily_delta_prefix": iso3,
        "daily_delta_glob": f"{iso3}-*.osc.gz",
        "input_pbf_path": str(repo_root / "mapdata" / "raw" / pbf_asset_name),
        "input_poly_path": str(repo_root / "mapdata" / "raw" / poly_name),
        "state_file_path": str(repo_root / "mapdata" / "raw" / state_asset_name),
        "report_path": str(repo_root / "mapdata" / "reports" / report_asset_name),
        "daily_dir": str(repo_root / "mapdata" / "reports" / "deltas" / "daily"),
        "csv_out": str(
            repo_root / "mapdata" / "reports" / "deltas" / f"{region_slug}.daily-diff-analysis.csv"
        ),
        "summary_json_out": str(
            repo_root
            / "mapdata"
            / "reports"
            / "deltas"
            / f"{region_slug}.daily-diff-analysis.summary.json"
        ),
        "work_dir": str(repo_root / "mapdata" / "build" / region_slug / "updates"),
        "bundle_dir": str(repo_root / "mapdata" / "bundles" / "v3" / region_slug / "latest"),
        "bundle_db_asset": bundles._db_asset_name(region_asset_id),
        "bundle_manifest_asset": bundles._manifest_asset_name(region_asset_id),
        "delta_index_asset": f"{region_asset_id}_delta_index.json",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Resolve country-level release tags, assets, and local paths"
    )
    parser.add_argument("--repo-root", default=".", help="Repository root (default: .)")
    parser.add_argument(
        "--bundle-country",
        required=True,
        help="Country id from BundleTargets.top10.json / Geofabrik index",
    )
    parser.add_argument(
        "--geofabrik-index",
        default="mapdata/build/geofabrik/index-v1.json",
        help="Geofabrik index-v1.json path",
    )
    parser.add_argument(
        "--geofabrik-index-url",
        default="https://download.geofabrik.de/index-v1.json",
        help="Download URL used when --geofabrik-index is missing",
    )
    parser.add_argument(
        "--bundle-target-config",
        default="iphone/SpeedConsumerApp/BundleTargets.top10.json",
        help="Bundle target config path",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    plan = resolve_country_release_plan(
        repo_root=repo_root,
        bundle_country=args.bundle_country,
        geofabrik_index=(repo_root / args.geofabrik_index).resolve(),
        bundle_target_config=(repo_root / args.bundle_target_config).resolve(),
        geofabrik_index_url=args.geofabrik_index_url,
    )
    print(json.dumps(plan, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
