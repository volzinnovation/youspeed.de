#!/usr/bin/env python3
"""Generate v3 bundles for one region or top-N countries from maxspeed ranking."""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

ISO2_TO_ISO3: Dict[str, str] = {
    "DE": "DEU",
    "NL": "NLD",
    "RO": "ROU",
    "LU": "LUX",
    "BE": "BEL",
    "SE": "SWE",
    "LI": "LIE",
    "IS": "ISL",
    "MC": "MCO",
    "GB": "GBR",
}
ISO3_TO_ISO2: Dict[str, str] = {iso3: iso2 for iso2, iso3 in ISO2_TO_ISO3.items()}


@dataclass(frozen=True)
class RankingCountry:
    rank: int
    country: str
    iso2: str
    geofabrik_id: str
    pbf_url: str
    pbf_size_bytes: int


@dataclass(frozen=True)
class BundleTarget:
    country_name: str
    country_id: str
    iso2: str
    iso3: str
    region_id: str
    pbf_url: str
    poly_url: Optional[str]
    is_shard: bool


@dataclass(frozen=True)
class BundleTargetConfigRegion:
    region_id: str


@dataclass(frozen=True)
class BundleTargetConfigCountry:
    rank: int
    country_id: str
    country_code: str
    iso2: str
    mode: str
    regions: List[BundleTargetConfigRegion]


def _slug(value: str) -> str:
    return (
        value.strip()
        .lower()
        .replace(" ", "-")
        .replace("_", "-")
        .replace("/", "-")
    )


def _id_token(official_id: str) -> str:
    """Normalize Geofabrik IDs for filesystem/release asset names."""
    return _slug(official_id)


def _db_asset_name(official_id: str) -> str:
    return f"{_id_token(official_id)}_speeds.sqlite"


def _manifest_asset_name(official_id: str) -> str:
    return f"{_id_token(official_id)}_manifest.json"


def _catalog_asset_name(official_id: str) -> str:
    return f"{_id_token(official_id)}_catalog.json"


def _derive_poly_url_from_pbf_url(pbf_url: str) -> Optional[str]:
    url = pbf_url.strip()
    if not url:
        return None
    if url.endswith("-latest.osm.pbf"):
        return url[: -len("-latest.osm.pbf")] + ".poly"
    if url.endswith(".osm.pbf"):
        return url[: -len(".osm.pbf")] + ".poly"
    return None


def _load_bundle_target_config(path: Path) -> List[BundleTargetConfigCountry]:
    if not path.exists():
        return []
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("format") != "youspeed.v3.bundle.targets":
        raise SystemExit(f"Unexpected bundle target config format in {path}")

    countries_raw = payload.get("countries")
    if not isinstance(countries_raw, list):
        raise SystemExit(f"Invalid bundle target config (countries must be array): {path}")

    countries: List[BundleTargetConfigCountry] = []
    for row in countries_raw:
        if not isinstance(row, dict):
            continue
        country_id = str(row.get("country_id", "")).strip().lower()
        if not country_id:
            continue
        rank = int(row.get("rank", 9999))
        country_code = str(row.get("country_code", "")).strip().upper()
        iso2 = str(row.get("iso2", "")).strip().upper()
        if not iso2 and country_code:
            iso2 = ISO3_TO_ISO2.get(country_code, "")
        mode = str(row.get("mode", "single_country")).strip().lower() or "single_country"
        regions_raw = row.get("regions")
        if not isinstance(regions_raw, list):
            raise SystemExit(f"Invalid regions list for country '{country_id}' in {path}")
        regions: List[BundleTargetConfigRegion] = []
        for region_row in regions_raw:
            if not isinstance(region_row, dict):
                continue
            region_id = str(region_row.get("region_id", "")).strip().lower()
            if not region_id:
                continue
            regions.append(BundleTargetConfigRegion(region_id=region_id))
        if not regions:
            raise SystemExit(f"Country '{country_id}' has no regions in bundle target config: {path}")
        countries.append(
            BundleTargetConfigCountry(
                rank=rank,
                country_id=country_id,
                country_code=country_code,
                iso2=iso2,
                mode=mode,
                regions=regions,
            )
        )
    countries.sort(key=lambda item: (item.rank, item.country_id))
    return countries


def _now_bundle_version() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load_geofabrik_index(path: Path) -> Dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _iter_feature_props(index_payload: Dict) -> Iterable[Dict]:
    for feature in index_payload.get("features", []):
        props = feature.get("properties")
        if isinstance(props, dict):
            yield props


def _build_index_maps(index_payload: Dict) -> Tuple[Dict[str, Dict], Dict[str, List[Dict]]]:
    by_id: Dict[str, Dict] = {}
    children: Dict[str, List[Dict]] = {}
    for props in _iter_feature_props(index_payload):
        geofabrik_id = str(props.get("id", "")).strip().lower()
        if not geofabrik_id:
            continue
        by_id[geofabrik_id] = props
        parent = str(props.get("parent", "")).strip().lower()
        if parent:
            children.setdefault(parent, []).append(props)
    for parent, entries in children.items():
        entries.sort(key=lambda item: str(item.get("name", item.get("id", ""))).lower())
        children[parent] = entries
    return by_id, children


def _urls_from_props(props: Dict) -> Dict:
    urls = props.get("urls")
    return urls if isinstance(urls, dict) else {}


def _iso2_from_props(props: Dict) -> str:
    raw = props.get("iso3166-1:alpha2")
    if isinstance(raw, list) and raw:
        return str(raw[0]).upper()
    if isinstance(raw, str) and raw.strip():
        return raw.strip().upper()
    return ""


def _iso3_from_iso2(iso2: str) -> str:
    code = iso2.strip().upper()
    if len(code) == 3 and code.isalpha():
        return code
    iso3 = ISO2_TO_ISO3.get(code)
    if iso3:
        return iso3
    raise SystemExit(f"No ISO3 mapping known for ISO2 code: {iso2!r}")


def _load_ranking(path: Path) -> List[RankingCountry]:
    rows: List[RankingCountry] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        required = {
            "rank",
            "country",
            "iso2",
            "geofabrik_id",
            "pbf_url",
            "pbf_size_bytes",
        }
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise SystemExit(f"Ranking CSV missing columns: {sorted(missing)}")
        for row in reader:
            rows.append(
                RankingCountry(
                    rank=int(row["rank"]),
                    country=str(row["country"]),
                    iso2=str(row["iso2"]).upper(),
                    geofabrik_id=str(row["geofabrik_id"]).strip().lower(),
                    pbf_url=str(row["pbf_url"]).strip(),
                    pbf_size_bytes=int(row["pbf_size_bytes"]),
                )
            )
    rows.sort(key=lambda item: item.rank)
    return rows


def plan_targets_from_top_countries(
    *,
    ranking_rows: List[RankingCountry],
    index_by_id: Dict[str, Dict],
    child_regions_by_parent: Dict[str, List[Dict]],
    top_n: int,
    max_country_pbf_bytes: int,
) -> List[BundleTarget]:
    if top_n <= 0:
        raise SystemExit("--top-n must be > 0")

    targets: List[BundleTarget] = []
    for country in ranking_rows[:top_n]:
        country_props = index_by_id.get(country.geofabrik_id)
        if country_props is None:
            raise SystemExit(f"Geofabrik id not found in index: {country.geofabrik_id}")
        country_name = str(country_props.get("name", country.country))

        if country.pbf_size_bytes > max_country_pbf_bytes:
            shards = child_regions_by_parent.get(country.geofabrik_id, [])
            if not shards:
                raise SystemExit(
                    f"Country '{country.geofabrik_id}' exceeds threshold but has no child regions in index"
                )
            country_url_prefix = country.pbf_url.rsplit("/", 1)[0] + "/"
            for shard in shards:
                urls = _urls_from_props(shard)
                pbf_url = str(urls.get("pbf", "")).strip()
                if not pbf_url:
                    continue
                if not pbf_url.startswith(country_url_prefix):
                    # Exclude overseas/non-subtree extracts that are not in the
                    # country-specific Geofabrik subtree.
                    continue
                shard_id = str(shard.get("id", "")).strip().lower()
                if not shard_id:
                    continue
                if "/" not in shard_id:
                    shard_id = f"{country.geofabrik_id}/{shard_id}"
                poly_url = str(urls.get("poly", "")).strip() or _derive_poly_url_from_pbf_url(pbf_url)
                targets.append(
                    BundleTarget(
                        country_name=country_name,
                        country_id=country.geofabrik_id,
                        iso2=country.iso2,
                        iso3=_iso3_from_iso2(country.iso2),
                        region_id=shard_id,
                        pbf_url=pbf_url,
                        poly_url=poly_url,
                        is_shard=True,
                    )
                )
        else:
            urls = _urls_from_props(country_props)
            poly_url = str(urls.get("poly", "")).strip() or _derive_poly_url_from_pbf_url(country.pbf_url)
            targets.append(
                BundleTarget(
                    country_name=country_name,
                    country_id=country.geofabrik_id,
                    iso2=country.iso2,
                    iso3=_iso3_from_iso2(country.iso2),
                    region_id=country.geofabrik_id,
                    pbf_url=country.pbf_url,
                    poly_url=poly_url,
                    is_shard=False,
                )
            )
    return targets


def plan_targets_for_country(
    *,
    country_id: str,
    index_by_id: Dict[str, Dict],
    child_regions_by_parent: Dict[str, List[Dict]],
    max_country_pbf_bytes: int,
    iso2_override: str = "",
    country_pbf_size_bytes: Optional[int] = None,
) -> List[BundleTarget]:
    key = country_id.strip().lower()
    if not key:
        raise SystemExit("--bundle-country must not be empty")

    country_props = index_by_id.get(key)
    if country_props is None:
        raise SystemExit(f"Country id not found in Geofabrik index: {country_id}")

    urls = _urls_from_props(country_props)
    country_pbf_url = str(urls.get("pbf", "")).strip()
    if not country_pbf_url:
        raise SystemExit(f"Country has no PBF URL in index: {country_id}")

    country_name = str(country_props.get("name", country_id))
    iso2 = iso2_override.strip().upper() or _iso2_from_props(country_props)
    if not iso2:
        raise SystemExit(f"Country has no ISO2 in index and --iso2 was not provided: {country_id}")
    iso3 = _iso3_from_iso2(iso2)

    shards = child_regions_by_parent.get(key, [])
    country_url_prefix = country_pbf_url.rsplit("/", 1)[0] + "/"
    regional_targets: List[BundleTarget] = []
    for shard in shards:
        shard_urls = _urls_from_props(shard)
        pbf_url = str(shard_urls.get("pbf", "")).strip()
        if not pbf_url:
            continue
        if not pbf_url.startswith(country_url_prefix):
            # Exclude non-subtree extracts (for example overseas territories).
            continue
        shard_id = str(shard.get("id", "")).strip().lower()
        if not shard_id:
            continue
        if "/" not in shard_id:
            shard_id = f"{key}/{shard_id}"
        poly_url = str(shard_urls.get("poly", "")).strip() or _derive_poly_url_from_pbf_url(pbf_url)
        regional_targets.append(
            BundleTarget(
                country_name=country_name,
                country_id=key,
                iso2=iso2,
                iso3=iso3,
                region_id=shard_id,
                pbf_url=pbf_url,
                poly_url=poly_url,
                is_shard=True,
            )
        )

    # If explicit size is known, keep country-level bundle when below threshold.
    # Otherwise prefer regional shards to reduce per-run disk/time pressure.
    if regional_targets:
        if country_pbf_size_bytes is None or country_pbf_size_bytes > max_country_pbf_bytes:
            return regional_targets

    poly_url = str(urls.get("poly", "")).strip() or _derive_poly_url_from_pbf_url(country_pbf_url)
    return [
        BundleTarget(
            country_name=country_name,
            country_id=key,
            iso2=iso2,
            iso3=iso3,
            region_id=key,
            pbf_url=country_pbf_url,
            poly_url=poly_url,
            is_shard=False,
        )
    ]


def plan_single_region_target(
    *,
    region_id: str,
    index_by_id: Dict[str, Dict],
    iso2_override: str,
) -> BundleTarget:
    key = region_id.strip().lower()
    props = index_by_id.get(key)
    if props is None:
        raise SystemExit(f"Region id not found in Geofabrik index: {region_id}")
    urls = _urls_from_props(props)
    pbf_url = str(urls.get("pbf", "")).strip()
    if not pbf_url:
        raise SystemExit(f"Region has no PBF URL in index: {region_id}")
    parent = str(props.get("parent", "")).strip().lower()
    country_id = parent if "/" in key and parent else key
    iso2 = iso2_override.strip().upper() or _iso2_from_props(props)
    if not iso2:
        raise SystemExit(f"Region has no ISO2 in index and --iso2 was not provided: {region_id}")
    iso3 = _iso3_from_iso2(iso2)

    poly_url = str(urls.get("poly", "")).strip() or _derive_poly_url_from_pbf_url(pbf_url)

    return BundleTarget(
        country_name=str(props.get("name", region_id)),
        country_id=country_id,
        iso2=iso2,
        iso3=iso3,
        region_id=key,
        pbf_url=pbf_url,
        poly_url=poly_url,
        is_shard=False,
    )


def plan_targets_for_country_from_config(
    *,
    config_country: BundleTargetConfigCountry,
    index_by_id: Dict[str, Dict],
) -> List[BundleTarget]:
    iso2_override = config_country.iso2
    country_id = config_country.country_id
    mode = config_country.mode
    targets: List[BundleTarget] = []
    for region in config_country.regions:
        target = plan_single_region_target(
            region_id=region.region_id,
            index_by_id=index_by_id,
            iso2_override=iso2_override,
        )
        is_shard = mode == "regional_shards" and target.region_id != country_id
        targets.append(
            BundleTarget(
                country_name=target.country_name,
                country_id=country_id,
                iso2=target.iso2,
                iso3=target.iso3,
                region_id=target.region_id,
                pbf_url=target.pbf_url,
                poly_url=target.poly_url,
                is_shard=is_shard,
            )
        )
    return targets


def _download_file(url: str, out_path: Path, force: bool) -> None:
    if out_path.exists() and not force:
        return
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with urllib.request.urlopen(url) as response:
        with out_path.open("wb") as f:
            shutil.copyfileobj(response, f)


def _probe_content_length_bytes(url: str) -> Optional[int]:
    request = urllib.request.Request(url, method="HEAD")
    with urllib.request.urlopen(request) as response:
        raw = response.headers.get("Content-Length")
        if raw is None:
            return None
        value = str(raw).strip()
        if not value:
            return None
        return int(value)


def _run(cmd: List[str], dry_run: bool) -> None:
    printable = " ".join(cmd)
    print(f"$ {printable}")
    if dry_run:
        return
    subprocess.run(cmd, check=True)


def _bundle_commands(
    *,
    repo_root: Path,
    target: BundleTarget,
    bundle_version: str,
    max_geom_points: int,
    release_tag: str,
    skip_release_urls: bool,
    rules_dir: Path,
) -> List[List[str]]:
    region_slug = _slug(target.region_id)
    region_asset_id = _id_token(target.region_id)
    iso3 = target.iso3.upper()
    raw_dir = repo_root / "mapdata" / "raw"
    pbf_path = raw_dir / f"{region_slug}-latest.osm.pbf"
    poly_path = raw_dir / f"{region_slug}.poly"
    v1_dist = repo_root / "mapdata" / "dist" / region_slug
    v3_dist = repo_root / "mapdata" / "dist-v3" / region_slug
    db_path = v3_dist / "speeds_v3.sqlite"
    penalty_rules_path = rules_dir / f"{iso3}-rules.json"
    if not penalty_rules_path.exists():
        raise SystemExit(f"Missing penalty rules file for {iso3}: {penalty_rules_path}")

    commands: List[List[str]] = [
        [
            str(repo_root / "scripts" / "map" / "build_region_artifacts.sh"),
            "--region",
            region_slug,
            "--input",
            str(pbf_path),
            "--root",
            str(repo_root),
            "--max-geom-points",
            str(max_geom_points),
        ],
        [
            "python3",
            str(repo_root / "scripts" / "map" / "build_spatialite_v3.py"),
            "--v1-dist",
            str(v1_dist),
            "--out-db",
            str(db_path),
        ],
        [
            "python3",
            str(repo_root / "scripts" / "map" / "publish_v3_bundle.py"),
            "--region",
            region_slug,
            "--db",
            str(db_path),
            "--bundle-version",
            bundle_version,
            "--bundle-dir-name",
            "latest",
            "--out-root",
            str(repo_root / "mapdata" / "bundles" / "v3"),
            "--db-file-name",
            _db_asset_name(region_asset_id),
            "--manifest-name",
            _manifest_asset_name(region_asset_id),
            "--coverage-poly",
            str(poly_path),
            "--country-code",
            iso3,
            "--penalty-rules",
            str(penalty_rules_path),
        ],
    ]

    if not skip_release_urls:
        publish = commands[-1]
        publish.extend(
            [
                "--github-owner",
                "volzinnovation",
                "--github-repo",
                "youspeed.de",
                "--github-release-tag",
                release_tag,
            ]
        )
    return commands


def _catalog_command(
    *,
    repo_root: Path,
    country_id: str,
    bundle_version: str,
    region_ids: List[str],
) -> List[str]:
    cmd: List[str] = [
        "python3",
        str(repo_root / "scripts" / "map" / "build_v3_country_bundle_catalog.py"),
        "--country",
        country_id,
        "--bundle-version",
        bundle_version,
    ]
    for region_id in region_ids:
        region_slug = _slug(region_id)
        region_asset_id = _id_token(region_id)
        cmd.extend(
            [
                "--manifest",
                str(
                    repo_root
                    / "mapdata"
                    / "bundles"
                    / "v3"
                    / region_slug
                    / "latest"
                    / _manifest_asset_name(region_asset_id)
                ),
            ]
        )
    cmd.extend(
        [
            "--out-json",
            str(
                repo_root
                / "mapdata"
                / "bundles"
                / "v3"
                / _slug(country_id)
                / "latest"
                / _catalog_asset_name(country_id)
            ),
        ]
    )
    return cmd


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate v3 bundles for one region or top countries")
    parser.add_argument("--repo-root", default=".", help="Repository root (default: .)")
    parser.add_argument(
        "--ranking-csv",
        default="mapdata/reports/europe_maxspeed_with_germany.ranking.csv",
        help="Ranking CSV used for --top-n mode",
    )
    parser.add_argument(
        "--geofabrik-index",
        default="mapdata/build/geofabrik/index-v1.json",
        help="Geofabrik index-v1.json path",
    )
    parser.add_argument(
        "--geofabrik-index-url",
        default="https://download.geofabrik.de/index-v1.json",
        help="Download URL used when --geofabrik-index file is missing",
    )
    parser.add_argument("--max-country-pbf-bytes", type=int, default=1_000_000_000)
    parser.add_argument("--top-n", type=int, default=0, help="Generate bundles for top N ranked countries")
    parser.add_argument(
        "--bundle-country",
        default="",
        help="Generate one explicit Geofabrik country id (uses regional shards when appropriate)",
    )
    parser.add_argument(
        "--bundle-region",
        default="",
        help="Generate one explicit Geofabrik region id (bypasses --top-n)",
    )
    parser.add_argument("--iso2", default="", help="Optional ISO2 override for --bundle-region mode")
    parser.add_argument("--bundle-version", default="", help="Bundle version (default: UTC date)")
    parser.add_argument("--max-geom-points", type=int, default=8)
    parser.add_argument(
        "--rules-dir",
        default="iphone/SpeedConsumerApp/Rules",
        help="Directory containing <ISO3>-rules.json files",
    )
    parser.add_argument(
        "--bundle-target-config",
        default="iphone/SpeedConsumerApp/BundleTargets.top10.json",
        help="Shared country/region bundle target config path",
    )
    parser.add_argument(
        "--release-tag",
        default="",
        help="Release tag used when embedding release URLs in manifests. Empty => use <ID> in single-target mode.",
    )
    parser.add_argument(
        "--skip-release-urls",
        action="store_true",
        help="Do not embed GitHub release URLs in generated manifests",
    )
    parser.add_argument(
        "--force-download",
        action="store_true",
        help="Re-download PBF/poly even if local file already exists",
    )
    parser.add_argument(
        "--country-pbf-bytes",
        type=int,
        default=-1,
        help="Optional explicit size hint for --bundle-country (bytes). Overrides ranking/HTTP probe.",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Run generation commands (default: print plan only)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(args.repo_root).resolve()
    index_path = (repo_root / args.geofabrik_index).resolve()
    if not index_path.exists():
        index_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            print(f"Geofabrik index missing, downloading: {args.geofabrik_index_url}")
            _download_file(args.geofabrik_index_url, index_path, force=True)
        except Exception as exc:
            raise SystemExit(
                f"Missing geofabrik index at {index_path} and download failed: {exc}"
            ) from exc

    index_payload = _load_geofabrik_index(index_path)
    index_by_id, child_regions_by_parent = _build_index_maps(index_payload)
    target_config_path = (repo_root / args.bundle_target_config).resolve()
    config_countries = _load_bundle_target_config(target_config_path)
    config_country_by_id = {row.country_id: row for row in config_countries}

    bundle_version = args.bundle_version.strip() or _now_bundle_version()
    top_n = int(args.top_n)
    bundle_country = args.bundle_country.strip().lower()
    bundle_region = args.bundle_region.strip().lower()
    selected_modes = int(bool(bundle_region)) + int(bool(bundle_country)) + int(top_n > 0)
    if selected_modes != 1:
        raise SystemExit("Provide exactly one mode: --bundle-region, --bundle-country, or --top-n > 0")

    if bundle_region:
        targets = [
            plan_single_region_target(
                region_id=bundle_region,
                index_by_id=index_by_id,
                iso2_override=args.iso2,
            )
        ]
    elif bundle_country:
        config_country = config_country_by_id.get(bundle_country)
        if config_country is not None:
            targets = plan_targets_for_country_from_config(
                config_country=config_country,
                index_by_id=index_by_id,
            )
        else:
        # If ranking data is available, reuse known PBF bytes for threshold decisions.
            size_hint: Optional[int] = None
            if args.country_pbf_bytes >= 0:
                size_hint = int(args.country_pbf_bytes)

            ranking_path = (repo_root / args.ranking_csv).resolve()
            if size_hint is None and ranking_path.exists():
                for row in _load_ranking(ranking_path):
                    if row.geofabrik_id == bundle_country:
                        size_hint = row.pbf_size_bytes
                        break

            if size_hint is None:
                country_props = index_by_id.get(bundle_country)
                if country_props is None:
                    raise SystemExit(f"Country id not found in Geofabrik index: {bundle_country}")
                country_urls = _urls_from_props(country_props)
                country_pbf_url = str(country_urls.get("pbf", "")).strip()
                if not country_pbf_url:
                    raise SystemExit(f"Country has no PBF URL in index: {bundle_country}")
                try:
                    size_hint = _probe_content_length_bytes(country_pbf_url)
                except Exception as exc:
                    raise SystemExit(
                        "Unable to determine country PBF size for sharding decision "
                        f"({bundle_country}): {exc}"
                    ) from exc
                if size_hint is None:
                    raise SystemExit(
                        "Unable to determine country PBF size for sharding decision "
                        f"({bundle_country}): missing Content-Length"
                    )

            print(
                f"Country '{bundle_country}' PBF bytes: {size_hint} "
                f"(threshold: {int(args.max_country_pbf_bytes)})"
            )
            targets = plan_targets_for_country(
                country_id=bundle_country,
                index_by_id=index_by_id,
                child_regions_by_parent=child_regions_by_parent,
                max_country_pbf_bytes=int(args.max_country_pbf_bytes),
                iso2_override=args.iso2,
                country_pbf_size_bytes=size_hint,
            )
    else:
        if config_countries:
            selected_config = config_countries[:top_n]
            targets = []
            for config_country in selected_config:
                targets.extend(
                    plan_targets_for_country_from_config(
                        config_country=config_country,
                        index_by_id=index_by_id,
                    )
                )
        else:
            ranking_path = (repo_root / args.ranking_csv).resolve()
            ranking_rows = _load_ranking(ranking_path)
            targets = plan_targets_from_top_countries(
                ranking_rows=ranking_rows,
                index_by_id=index_by_id,
                child_regions_by_parent=child_regions_by_parent,
                top_n=top_n,
                max_country_pbf_bytes=int(args.max_country_pbf_bytes),
            )

    print(f"Bundle version: {bundle_version}")
    print(f"Targets: {len(targets)}")
    for idx, target in enumerate(targets, start=1):
        print(
            f"  {idx:02d}. country={target.country_id} region={target.region_id} "
            f"iso2={target.iso2} iso3={target.iso3} shard={'yes' if target.is_shard else 'no'}"
        )

    raw_dir = repo_root / "mapdata" / "raw"
    rules_dir = (repo_root / args.rules_dir).resolve()
    if not rules_dir.exists():
        raise SystemExit(f"Rules directory not found: {rules_dir}")
    effective_release_tag = args.release_tag.strip()
    if not args.skip_release_urls:
        if not effective_release_tag:
            unique_country_ids = sorted({target.country_id for target in targets})
            if len(targets) == 1:
                effective_release_tag = _id_token(targets[0].region_id)
            elif len(unique_country_ids) == 1:
                effective_release_tag = _id_token(unique_country_ids[0])
            else:
                raise SystemExit(
                    "--release-tag is required for multi-country runs when release URLs are enabled"
                )
        print(f"Release tag: {effective_release_tag}")

    for target in targets:
        region_slug = _slug(target.region_id)
        pbf_path = raw_dir / f"{region_slug}-latest.osm.pbf"
        poly_path = raw_dir / f"{region_slug}.poly"

        print(f"\n=== {target.country_name} / {target.region_id} ===")
        if args.execute:
            print(f"Downloading PBF: {target.pbf_url}")
            _download_file(target.pbf_url, pbf_path, force=args.force_download)
            if target.poly_url:
                print(f"Downloading POLY: {target.poly_url}")
                _download_file(target.poly_url, poly_path, force=args.force_download)
            elif not poly_path.exists():
                raise SystemExit(f"No poly URL in index and local poly missing for region {target.region_id}")
        else:
            print(f"PBF -> {pbf_path}")
            print(f"POLY -> {poly_path if target.poly_url else '[local required]'}")

        for cmd in _bundle_commands(
            repo_root=repo_root,
            target=target,
            bundle_version=bundle_version,
            max_geom_points=int(args.max_geom_points),
            release_tag=effective_release_tag,
            skip_release_urls=bool(args.skip_release_urls),
            rules_dir=rules_dir,
        ):
            _run(cmd, dry_run=not args.execute)

    by_country: Dict[str, List[str]] = {}
    for target in targets:
        key = target.country_id
        by_country.setdefault(key, []).append(target.region_id)
    for country_id, regions in sorted(by_country.items()):
        if len(regions) <= 1:
            continue
        print(f"\n=== Catalog {country_id} ({len(regions)} regions) ===")
        _run(
            _catalog_command(
                repo_root=repo_root,
                country_id=country_id,
                bundle_version=bundle_version,
                region_ids=regions,
            ),
            dry_run=not args.execute,
        )

    print("\nDone.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
