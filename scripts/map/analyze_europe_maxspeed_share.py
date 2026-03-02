#!/usr/bin/env python3
"""Analyze maxspeed-tag coverage across Geofabrik Europe country extracts.

Produces:
1) Country ranking by maxspeed share (descending).
2) Per-country, per-highway counts similar to Table 1 in the tech report.

The script is resumable: it writes progress after each country.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple

try:
    import osmium  # type: ignore
except Exception as exc:  # pragma: no cover
    print(f"Missing dependency: pyosmium ({exc})", file=sys.stderr)
    raise SystemExit(2)


DRIVABLE_HIGHWAYS_CAR = {
    "motorway",
    "trunk",
    "primary",
    "secondary",
    "tertiary",
    "unclassified",
    "residential",
    "service",
    "living_street",
    "motorway_link",
    "trunk_link",
    "primary_link",
    "secondary_link",
    "tertiary_link",
    "road",
}


HIGHWAY_INTERPRETATION: Dict[str, str] = {
    "service": "Access roads to premises, parking, and service areas.",
    "residential": "Roads primarily serving housing areas.",
    "secondary": "Secondary inter-settlement connectors in the network hierarchy.",
    "tertiary": "Tertiary connectors between local centers.",
    "unclassified": "Minor public through roads (not unknown class).",
    "primary": "Primary roads with high network importance below trunk/motorway.",
    "living_street": "Traffic-calmed shared street.",
    "motorway": "Controlled-access motorway corridor.",
    "motorway_link": "Motorway ramps/connectors.",
    "trunk": "Major non-motorway long-distance routes.",
    "trunk_link": "Connector ramps between trunk and other classes.",
    "primary_link": "Connector ramps related to primary roads.",
    "secondary_link": "Connector ramps related to secondary roads.",
    "tertiary_link": "Connector ramps related to tertiary roads.",
    "road": "Temporary placeholder until precise class is surveyed.",
}


@dataclass
class CountryTarget:
    geofabrik_id: str
    name: str
    iso2: str
    pbf_url: str


@dataclass
class CountryResult:
    geofabrik_id: str
    name: str
    iso2: str
    pbf_url: str
    pbf_size_bytes: int
    drivable_way_count: int
    maxspeed_way_count: int
    maxspeed_share_pct: float
    highway_counts: Dict[str, Dict[str, int]]


class HighwayCounter(osmium.SimpleHandler):
    def __init__(self) -> None:
        super().__init__()
        self.total_ways = 0
        self.maxspeed_ways = 0
        self.by_highway: Dict[str, Dict[str, int]] = {
            h: {"ways": 0, "maxspeed": 0} for h in DRIVABLE_HIGHWAYS_CAR
        }

    def way(self, way: "osmium.osm.Way") -> None:
        highway = way.tags.get("highway")
        if highway not in DRIVABLE_HIGHWAYS_CAR:
            return

        self.total_ways += 1
        stats = self.by_highway[highway]
        stats["ways"] += 1

        maxspeed = way.tags.get("maxspeed")
        if maxspeed is not None and maxspeed.strip() != "":
            self.maxspeed_ways += 1
            stats["maxspeed"] += 1


def _read_index_json(path_or_url: str, scratch_dir: Path) -> Dict:
    if path_or_url.startswith("http://") or path_or_url.startswith("https://"):
        out_path = scratch_dir / "geofabrik-index-v1.json"
        _download(path_or_url, out_path)
        return json.loads(out_path.read_text())
    return json.loads(Path(path_or_url).read_text())


def _download(url: str, out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = out_path.with_suffix(out_path.suffix + ".tmp")
    if tmp_path.exists():
        tmp_path.unlink()
    cmd = ["curl", "-L", "--fail", url, "-o", str(tmp_path)]
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise RuntimeError(f"Download failed ({proc.returncode}) for {url}: {proc.stderr.strip()}")
    if tmp_path.exists():
        tmp_path.replace(out_path)
        return
    # Defensive fallback: if output already exists (e.g., concurrent/interrupted run),
    # keep it and continue.
    if out_path.exists():
        return
    raise RuntimeError(f"Download completed but temp artifact missing: {tmp_path}")


def _extract_targets(index_payload: Dict, exclude_iso: Iterable[str], include_iso: Optional[Iterable[str]]) -> List[CountryTarget]:
    exclude = {x.strip().upper() for x in exclude_iso if x.strip()}
    include = None
    if include_iso:
        include = {x.strip().upper() for x in include_iso if x.strip()}

    per_iso: Dict[str, CountryTarget] = {}
    for feature in index_payload.get("features", []):
        props = feature.get("properties", {})
        if props.get("parent") != "europe":
            continue
        pbf_url = (props.get("urls") or {}).get("pbf")
        if not pbf_url:
            continue
        iso_list = props.get("iso3166-1:alpha2")
        if not isinstance(iso_list, list) or not iso_list:
            continue

        iso2 = str(iso_list[0]).upper()
        if include is not None and iso2 not in include:
            continue
        if iso2 in exclude:
            continue

        geofabrik_id = str(props.get("id") or "").strip()
        name = str(props.get("name") or geofabrik_id).strip()
        if not geofabrik_id:
            continue

        candidate = CountryTarget(
            geofabrik_id=geofabrik_id,
            name=name,
            iso2=iso2,
            pbf_url=str(pbf_url),
        )

        # Prefer canonical country-level UK extract over Great Britain extract.
        existing = per_iso.get(iso2)
        if existing is None:
            per_iso[iso2] = candidate
            continue
        preferred_id = {
            "GB": "united-kingdom",
        }.get(iso2)
        if preferred_id and candidate.geofabrik_id == preferred_id:
            per_iso[iso2] = candidate

    return sorted(per_iso.values(), key=lambda t: (t.name.lower(), t.iso2))


def _count_country(pbf_path: Path) -> Tuple[int, int, Dict[str, Dict[str, int]]]:
    handler = HighwayCounter()
    handler.apply_file(str(pbf_path), locations=False)
    return handler.total_ways, handler.maxspeed_ways, handler.by_highway


def _save_progress(progress_path: Path, results: List[CountryResult]) -> None:
    payload = {"results": [asdict(r) for r in results]}
    progress_path.parent.mkdir(parents=True, exist_ok=True)
    progress_path.write_text(json.dumps(payload, indent=2, sort_keys=True))


def _load_progress(progress_path: Path) -> List[CountryResult]:
    if not progress_path.exists():
        return []
    payload = json.loads(progress_path.read_text())
    out: List[CountryResult] = []
    for item in payload.get("results", []):
        out.append(
            CountryResult(
                geofabrik_id=item["geofabrik_id"],
                name=item["name"],
                iso2=item["iso2"],
                pbf_url=item["pbf_url"],
                pbf_size_bytes=int(item["pbf_size_bytes"]),
                drivable_way_count=int(item["drivable_way_count"]),
                maxspeed_way_count=int(item["maxspeed_way_count"]),
                maxspeed_share_pct=float(item["maxspeed_share_pct"]),
                highway_counts=item["highway_counts"],
            )
        )
    return out


def _write_country_ranking_csv(path: Path, ranked: List[CountryResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "rank",
                "country",
                "iso2",
                "geofabrik_id",
                "pbf_url",
                "pbf_size_bytes",
                "drivable_way_count",
                "maxspeed_way_count",
                "maxspeed_share_pct",
            ]
        )
        for i, row in enumerate(ranked, start=1):
            writer.writerow(
                [
                    i,
                    row.name,
                    row.iso2,
                    row.geofabrik_id,
                    row.pbf_url,
                    row.pbf_size_bytes,
                    row.drivable_way_count,
                    row.maxspeed_way_count,
                    f"{row.maxspeed_share_pct:.4f}",
                ]
            )


def _write_highway_table_csv(path: Path, ranked: List[CountryResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered_highways = [
        "service",
        "residential",
        "secondary",
        "tertiary",
        "unclassified",
        "primary",
        "living_street",
        "motorway",
        "motorway_link",
        "trunk",
        "trunk_link",
        "primary_link",
        "secondary_link",
        "tertiary_link",
        "road",
    ]
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "country",
                "iso2",
                "rank",
                "highway_tag",
                "interpretation",
                "ways",
                "maxspeed_tagged",
                "maxspeed_share_pct",
            ]
        )
        for rank, country in enumerate(ranked, start=1):
            for highway in ordered_highways:
                stats = country.highway_counts.get(highway, {"ways": 0, "maxspeed": 0})
                ways = int(stats.get("ways", 0))
                maxspeed = int(stats.get("maxspeed", 0))
                share_pct = (100.0 * maxspeed / ways) if ways else 0.0
                writer.writerow(
                    [
                        country.name,
                        country.iso2,
                        rank,
                        highway,
                        HIGHWAY_INTERPRETATION.get(highway, ""),
                        ways,
                        maxspeed,
                        f"{share_pct:.4f}",
                    ]
                )


def _write_ranking_markdown(path: Path, ranked: List[CountryResult]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = [
        "# European Countries Ranked by `maxspeed` Share (Descending)",
        "",
        "| Rank | Country | ISO2 | Drivable ways | `maxspeed` tagged ways | Share (%) |",
        "|---:|---|---|---:|---:|---:|",
    ]
    for i, row in enumerate(ranked, start=1):
        lines.append(
            f"| {i} | {row.name} | {row.iso2} | {row.drivable_way_count:,} | {row.maxspeed_way_count:,} | {row.maxspeed_share_pct:.2f} |"
        )
    path.write_text("\n".join(lines) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze maxspeed share for Geofabrik Europe countries.")
    parser.add_argument("--index", default="https://download.geofabrik.de/index-v1.json")
    parser.add_argument("--output-prefix", default="mapdata/reports/europe_maxspeed")
    parser.add_argument("--work-dir", default="mapdata/raw/europe-country-scan")
    parser.add_argument("--resume-json", default="mapdata/reports/europe_maxspeed.progress.json")
    parser.add_argument("--exclude-iso", default="DE")
    parser.add_argument("--include-iso", default="")
    parser.add_argument("--max-countries", type=int, default=0)
    parser.add_argument("--keep-pbf", action="store_true")
    args = parser.parse_args()

    work_dir = Path(args.work_dir)
    work_dir.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="geofabrik-index-") as td:
        index = _read_index_json(args.index, Path(td))

    targets = _extract_targets(
        index,
        exclude_iso=[x for x in args.exclude_iso.split(",") if x.strip()],
        include_iso=[x for x in args.include_iso.split(",") if x.strip()] if args.include_iso.strip() else None,
    )
    if args.max_countries > 0:
        targets = targets[: args.max_countries]

    if not targets:
        print("No country targets selected.", file=sys.stderr)
        return 1

    progress_path = Path(args.resume_json)
    completed = _load_progress(progress_path)
    completed_by_iso = {c.iso2: c for c in completed}
    results: List[CountryResult] = list(completed)

    pending = [t for t in targets if t.iso2 not in completed_by_iso]
    print(
        f"Selected {len(targets)} countries; already completed {len(completed_by_iso)}; pending {len(pending)}.",
        file=sys.stderr,
    )

    for idx, target in enumerate(pending, start=1):
        print(
            f"[{idx}/{len(pending)}] {target.name} ({target.iso2}) downloading: {target.pbf_url}",
            file=sys.stderr,
        )
        country_pbf = work_dir / f"{target.geofabrik_id}-latest.osm.pbf"
        _download(target.pbf_url, country_pbf)
        size_bytes = country_pbf.stat().st_size
        print(
            f"[{idx}/{len(pending)}] {target.name} ({target.iso2}) counting ways (size={size_bytes:,} bytes)...",
            file=sys.stderr,
        )
        total_ways, maxspeed_ways, by_highway = _count_country(country_pbf)
        share_pct = (100.0 * maxspeed_ways / total_ways) if total_ways else 0.0
        result = CountryResult(
            geofabrik_id=target.geofabrik_id,
            name=target.name,
            iso2=target.iso2,
            pbf_url=target.pbf_url,
            pbf_size_bytes=size_bytes,
            drivable_way_count=total_ways,
            maxspeed_way_count=maxspeed_ways,
            maxspeed_share_pct=share_pct,
            highway_counts=by_highway,
        )
        results = [r for r in results if r.iso2 != target.iso2] + [result]
        _save_progress(progress_path, results)
        print(
            f"[{idx}/{len(pending)}] {target.name} ({target.iso2}) done: "
            f"ways={total_ways:,}, maxspeed={maxspeed_ways:,}, share={share_pct:.2f}%",
            file=sys.stderr,
        )

        if not args.keep_pbf:
            try:
                country_pbf.unlink()
            except FileNotFoundError:
                pass

    ranked = sorted(results, key=lambda r: (-r.maxspeed_share_pct, r.name.lower()))
    prefix = Path(args.output_prefix)
    _write_country_ranking_csv(Path(f"{prefix}.ranking.csv"), ranked)
    _write_highway_table_csv(Path(f"{prefix}.highway_table.csv"), ranked)
    _write_ranking_markdown(Path(f"{prefix}.ranking.md"), ranked)
    _save_progress(progress_path, ranked)

    print(f"Saved ranking: {prefix}.ranking.csv", file=sys.stderr)
    print(f"Saved highway table: {prefix}.highway_table.csv", file=sys.stderr)
    print(f"Saved markdown: {prefix}.ranking.md", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
