#!/usr/bin/env python3
"""Build v1-v4 map assets and write a benchmark report JSON."""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List


REPO_ROOT = Path(__file__).resolve().parents[2]
BUILD_V1 = REPO_ROOT / "scripts/map/build_region_artifacts.sh"
BUILD_V2 = REPO_ROOT / "scripts/map/build_tile_assets_v2.py"
BUILD_V3 = REPO_ROOT / "scripts/map/build_spatialite_v3.py"
BUILD_V4 = REPO_ROOT / "scripts/map/build_spatialite_v4.py"
ANALYZE_DAILY_DIFF = REPO_ROOT / "scripts/map/analyze_daily_diff_impact.py"
QUERY_V1 = REPO_ROOT / "scripts/map/query_speed_limit.py"
QUERY_V2 = REPO_ROOT / "scripts/map/query_speed_limit_v2.py"
QUERY_V3 = REPO_ROOT / "scripts/map/query_speed_limit_v3.py"
QUERY_V4 = REPO_ROOT / "scripts/map/query_speed_limit_v4.py"


def run_cmd(args: List[str]) -> subprocess.CompletedProcess:
    return subprocess.run(args, text=True, capture_output=True, check=True)


def bytes_recursive(path: Path) -> int:
    total = 0
    if not path.exists():
        return total
    for p in path.rglob("*"):
        if p.is_file():
            total += p.stat().st_size
    return total


def bytes_file(path: Path) -> int:
    if not path.exists() or not path.is_file():
        return 0
    return path.stat().st_size


def summarize(values: List[float]) -> Dict[str, float]:
    return {
        "avg_ms": round(statistics.mean(values), 2),
        "p50_ms": round(statistics.median(values), 2),
        "min_ms": round(min(values), 2),
        "max_ms": round(max(values), 2),
    }


def benchmark_v1(
    dist_dir: Path,
    city_db_path: Path,
    lat: float,
    lon: float,
    heading: float,
    repeats: int,
    top_k: int,
    polyline_top_n: int,
) -> Dict[str, Dict[str, Dict[str, float]]]:
    out_maxspeed: Dict[str, Dict[str, float]] = {}
    out_street_name: Dict[str, Dict[str, float]] = {}
    out_city_name: Dict[str, Dict[str, float]] = {}
    out_polygon: Dict[str, Dict[str, float]] = {}
    for mode in ("bbox", "hybrid", "polyline"):
        maxspeed_totals: List[float] = []
        street_name_totals: List[float] = []
        city_name: List[float] = []
        polygon: List[float] = []
        for _ in range(repeats):
            result = run_cmd(
                [
                    str(QUERY_V1),
                    "--dist-dir",
                    str(dist_dir),
                    "--city-db",
                    str(city_db_path),
                    "--lat",
                    str(lat),
                    "--lon",
                    str(lon),
                    "--heading",
                    str(heading),
                    "--top-k",
                    str(top_k),
                    "--distance-mode",
                    mode,
                    "--polyline-top-n",
                    str(polyline_top_n),
                ]
            )
            payload = json.loads(result.stdout)
            query_total_ms = float(payload["timing_ms"]["total"])
            city_resolve_ms = float(payload["timing_ms"].get("city_resolve", 0.0))
            maxspeed_totals.append(query_total_ms)
            street_name_totals.append(query_total_ms)
            city_name.append(city_resolve_ms)
            polygon.append(city_resolve_ms)
        out_maxspeed[mode] = summarize(maxspeed_totals)
        out_street_name[mode] = summarize(street_name_totals)
        out_city_name[mode] = summarize(city_name)
        out_polygon[mode] = summarize(polygon)
    return {
        "maxspeed": out_maxspeed,
        "street_name": out_street_name,
        "city_name": out_city_name,
        "polygon_containment": out_polygon,
    }


def benchmark_v2(
    dist_dir: Path,
    city_db_path: Path,
    lat: float,
    lon: float,
    heading: float,
    repeats: int,
    top_k: int,
    polyline_top_n: int,
    tile_radius: int,
) -> Dict[str, Dict[str, Dict[str, float]]]:
    out_maxspeed: Dict[str, Dict[str, float]] = {}
    out_street_name: Dict[str, Dict[str, float]] = {}
    out_city_name: Dict[str, Dict[str, float]] = {}
    out_polygon: Dict[str, Dict[str, float]] = {}
    for mode in ("bbox", "hybrid", "polyline"):
        maxspeed_totals: List[float] = []
        street_name_totals: List[float] = []
        city_name: List[float] = []
        polygon: List[float] = []
        for _ in range(repeats):
            result = run_cmd(
                [
                    str(QUERY_V2),
                    "--dist-dir",
                    str(dist_dir),
                    "--city-db",
                    str(city_db_path),
                    "--lat",
                    str(lat),
                    "--lon",
                    str(lon),
                    "--heading",
                    str(heading),
                    "--tile-radius",
                    str(tile_radius),
                    "--top-k",
                    str(top_k),
                    "--distance-mode",
                    mode,
                    "--polyline-top-n",
                    str(polyline_top_n),
                ]
            )
            payload = json.loads(result.stdout)
            query_total_ms = float(payload["timing_ms"]["total"])
            city_resolve_ms = float(payload["timing_ms"].get("city_resolve", 0.0))
            maxspeed_totals.append(query_total_ms)
            street_name_totals.append(query_total_ms)
            city_name.append(city_resolve_ms)
            polygon.append(city_resolve_ms)
        out_maxspeed[mode] = summarize(maxspeed_totals)
        out_street_name[mode] = summarize(street_name_totals)
        out_city_name[mode] = summarize(city_name)
        out_polygon[mode] = summarize(polygon)
    return {
        "maxspeed": out_maxspeed,
        "street_name": out_street_name,
        "city_name": out_city_name,
        "polygon_containment": out_polygon,
    }


def benchmark_v3(
    db_path: Path,
    city_db_path: Path,
    lat: float,
    lon: float,
    heading: float,
    repeats: int,
    top_k: int,
    polyline_top_n: int,
    search_radius_m: float,
    max_candidates: int,
) -> Dict[str, Dict[str, Dict[str, float]]]:
    out_maxspeed: Dict[str, Dict[str, float]] = {}
    out_street_name: Dict[str, Dict[str, float]] = {}
    out_city_name: Dict[str, Dict[str, float]] = {}
    out_polygon: Dict[str, Dict[str, float]] = {}
    for mode in ("bbox", "hybrid", "polyline"):
        maxspeed_totals: List[float] = []
        street_name_totals: List[float] = []
        city_name: List[float] = []
        polygon: List[float] = []
        for _ in range(repeats):
            result = run_cmd(
                [
                    sys.executable,
                    str(QUERY_V3),
                    "--db",
                    str(db_path),
                    "--city-db",
                    str(city_db_path),
                    "--lat",
                    str(lat),
                    "--lon",
                    str(lon),
                    "--heading",
                    str(heading),
                    "--top-k",
                    str(top_k),
                    "--distance-mode",
                    mode,
                    "--polyline-top-n",
                    str(polyline_top_n),
                    "--search-radius-m",
                    str(search_radius_m),
                    "--max-candidates",
                    str(max_candidates),
                ]
            )
            payload = json.loads(result.stdout)
            query_total_ms = float(payload["timing_ms"]["total"])
            city_resolve_ms = float(payload["timing_ms"].get("city_resolve", 0.0))
            maxspeed_totals.append(query_total_ms)
            street_name_totals.append(query_total_ms)
            city_name.append(city_resolve_ms)
            polygon.append(city_resolve_ms)
        out_maxspeed[mode] = summarize(maxspeed_totals)
        out_street_name[mode] = summarize(street_name_totals)
        out_city_name[mode] = summarize(city_name)
        out_polygon[mode] = summarize(polygon)
    return {
        "maxspeed": out_maxspeed,
        "street_name": out_street_name,
        "city_name": out_city_name,
        "polygon_containment": out_polygon,
    }


def benchmark_v4(
    db_path: Path,
    lat: float,
    lon: float,
    heading: float,
    repeats: int,
    top_k: int,
    polyline_top_n: int,
    tile_radius: int,
    search_radius_m: float,
    max_candidates: int,
) -> Dict[str, Dict[str, Dict[str, float]]]:
    out_maxspeed: Dict[str, Dict[str, float]] = {}
    out_street_name: Dict[str, Dict[str, float]] = {}
    out_city_name: Dict[str, Dict[str, float]] = {}
    out_polygon: Dict[str, Dict[str, float]] = {}
    for mode in ("bbox", "hybrid", "polyline"):
        maxspeed_totals: List[float] = []
        street_name_totals: List[float] = []
        city_name: List[float] = []
        polygon: List[float] = []
        for _ in range(repeats):
            result = run_cmd(
                [
                    sys.executable,
                    str(QUERY_V4),
                    "--db",
                    str(db_path),
                    "--lat",
                    str(lat),
                    "--lon",
                    str(lon),
                    "--heading",
                    str(heading),
                    "--tile-radius",
                    str(tile_radius),
                    "--top-k",
                    str(top_k),
                    "--distance-mode",
                    mode,
                    "--polyline-top-n",
                    str(polyline_top_n),
                    "--search-radius-m",
                    str(search_radius_m),
                    "--max-candidates",
                    str(max_candidates),
                ]
            )
            payload = json.loads(result.stdout)
            query_total_ms = float(payload["timing_ms"]["total"])
            city_resolve_ms = float(payload["timing_ms"].get("city_resolve", 0.0))
            maxspeed_totals.append(query_total_ms)
            street_name_totals.append(query_total_ms)
            city_name.append(city_resolve_ms)
            polygon.append(city_resolve_ms)
        out_maxspeed[mode] = summarize(maxspeed_totals)
        out_street_name[mode] = summarize(street_name_totals)
        out_city_name[mode] = summarize(city_name)
        out_polygon[mode] = summarize(polygon)
    return {
        "maxspeed": out_maxspeed,
        "street_name": out_street_name,
        "city_name": out_city_name,
        "polygon_containment": out_polygon,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build v1-v4 map assets and benchmark query speed")
    parser.add_argument("--region", required=True, help="Region name (e.g. germany)")
    parser.add_argument("--input-pbf", required=True, help="Path to source PBF")
    parser.add_argument(
        "--v1-dist-dir",
        help="Override v1 dist dir (default: mapdata/dist/<region>)",
    )
    parser.add_argument(
        "--v2-dist-dir",
        help="Override v2 dist dir (default: mapdata/dist-v2/<region>)",
    )
    parser.add_argument(
        "--report-path",
        help="Output benchmark report JSON path (default: <v4-db-dir>/benchmark_report.json)",
    )
    parser.add_argument("--engine", default="pyosmium", choices=("pyosmium", "osmium-cli"))
    parser.add_argument("--max-geom-points", type=int, default=8)
    parser.add_argument("--tile-size-m", type=int, default=4096)
    parser.add_argument("--subgrid", type=int, default=32)
    parser.add_argument("--content-version", type=int, default=1)
    parser.add_argument("--max-area-tiles", type=int, default=1024)
    parser.add_argument(
        "--v3-db-path",
        help="Override v3 db path (default: mapdata/dist-v3/<region>/speeds_v3.sqlite)",
    )
    parser.add_argument(
        "--v4-db-path",
        help="Override v4 db path (default: mapdata/dist-v4/<region>/speeds_v4.sqlite)",
    )
    parser.add_argument("--max-way-tiles", type=int, default=1024)
    parser.add_argument("--lat", type=float, default=52.52)
    parser.add_argument("--lon", type=float, default=13.405)
    parser.add_argument("--heading", type=float, default=90.0)
    parser.add_argument("--repeats", type=int, default=10)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--polyline-top-n", type=int, default=250)
    parser.add_argument("--tile-radius", type=int, default=1)
    parser.add_argument("--search-radius-m", type=float, default=1200.0)
    parser.add_argument("--max-candidates", type=int, default=5000)
    parser.add_argument("--skip-build-v1", action="store_true")
    parser.add_argument("--skip-build-v2", action="store_true")
    parser.add_argument("--skip-build-v3", action="store_true")
    parser.add_argument("--skip-build-v4", action="store_true")
    parser.add_argument(
        "--diff-dir",
        default=str(REPO_ROOT / "mapdata" / "reports" / "deltas" / "daily"),
        help="Directory with daily .osc/.osc.gz files for incremental update analysis",
    )
    parser.add_argument(
        "--skip-update-analysis",
        action="store_true",
        help="Skip maxspeed+boundary incremental update analysis from daily diffs",
    )
    parser.add_argument(
        "--update-report-json",
        help="Override daily diff summary JSON path (default: <v4-db-dir>/daily_diff_analysis_extended.json)",
    )
    parser.add_argument(
        "--update-report-csv",
        help="Override daily diff CSV path (default: <v4-db-dir>/daily_diff_analysis_extended.csv)",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    v1_dist_dir = Path(args.v1_dist_dir) if args.v1_dist_dir else REPO_ROOT / "mapdata" / "dist" / args.region
    v2_dist_dir = Path(args.v2_dist_dir) if args.v2_dist_dir else REPO_ROOT / "mapdata" / "dist-v2" / args.region
    v3_db_path = (
        Path(args.v3_db_path)
        if args.v3_db_path
        else REPO_ROOT / "mapdata" / "dist-v3" / args.region / "speeds_v3.sqlite"
    )
    v4_db_path = (
        Path(args.v4_db_path)
        if args.v4_db_path
        else REPO_ROOT / "mapdata" / "dist-v4" / args.region / "speeds_v4.sqlite"
    )
    report_path = Path(args.report_path) if args.report_path else v4_db_path.parent / "benchmark_report.json"
    update_report_json = (
        Path(args.update_report_json)
        if args.update_report_json
        else v4_db_path.parent / "daily_diff_analysis_extended.json"
    )
    update_report_csv = (
        Path(args.update_report_csv)
        if args.update_report_csv
        else v4_db_path.parent / "daily_diff_analysis_extended.csv"
    )

    executed_steps: List[str] = []

    if not args.skip_build_v1:
        print("Building v1 artifacts...", file=sys.stderr)
        run_cmd(
            [
                str(BUILD_V1),
                "--region",
                args.region,
                "--input",
                args.input_pbf,
                "--engine",
                args.engine,
                "--max-geom-points",
                str(args.max_geom_points),
            ]
        )
        executed_steps.append("build_v1")

    if not args.skip_build_v2:
        print("Building v2 tile assets...", file=sys.stderr)
        run_cmd(
            [
                sys.executable,
                str(BUILD_V2),
                "--v1-dist",
                str(v1_dist_dir),
                "--out-dir",
                str(v2_dist_dir),
                "--region",
                args.region,
                "--tile-size-m",
                str(args.tile_size_m),
                "--subgrid",
                str(args.subgrid),
                "--content-version",
                str(args.content_version),
                "--max-area-tiles",
                str(args.max_area_tiles),
            ]
        )
        executed_steps.append("build_v2")

    if not args.skip_build_v3:
        print("Building v3 spatial DB...", file=sys.stderr)
        v3_db_path.parent.mkdir(parents=True, exist_ok=True)
        run_cmd(
            [
                sys.executable,
                str(BUILD_V3),
                "--v1-dist",
                str(v1_dist_dir),
                "--out-db",
                str(v3_db_path),
                "--input-pbf",
                str(Path(args.input_pbf)),
            ]
        )
        executed_steps.append("build_v3")

    if not args.skip_build_v4:
        print("Building v4 spatial+tile DB...", file=sys.stderr)
        v4_db_path.parent.mkdir(parents=True, exist_ok=True)
        run_cmd(
            [
                sys.executable,
                str(BUILD_V4),
                "--v1-dist",
                str(v1_dist_dir),
                "--out-db",
                str(v4_db_path),
                "--input-pbf",
                str(Path(args.input_pbf)),
                "--tile-size-m",
                str(args.tile_size_m),
                "--max-way-tiles",
                str(args.max_way_tiles),
            ]
        )
        executed_steps.append("build_v4")

    print("Benchmarking v1...", file=sys.stderr)
    v1_bench = benchmark_v1(
        dist_dir=v1_dist_dir,
        city_db_path=v4_db_path,
        lat=args.lat,
        lon=args.lon,
        heading=args.heading,
        repeats=args.repeats,
        top_k=args.top_k,
        polyline_top_n=args.polyline_top_n,
    )
    print("Benchmarking v2...", file=sys.stderr)
    v2_bench = benchmark_v2(
        dist_dir=v2_dist_dir,
        city_db_path=v4_db_path,
        lat=args.lat,
        lon=args.lon,
        heading=args.heading,
        repeats=args.repeats,
        top_k=args.top_k,
        polyline_top_n=args.polyline_top_n,
        tile_radius=args.tile_radius,
    )
    print("Benchmarking v3...", file=sys.stderr)
    v3_bench = benchmark_v3(
        db_path=v3_db_path,
        city_db_path=v4_db_path,
        lat=args.lat,
        lon=args.lon,
        heading=args.heading,
        repeats=args.repeats,
        top_k=args.top_k,
        polyline_top_n=args.polyline_top_n,
        search_radius_m=args.search_radius_m,
        max_candidates=args.max_candidates,
    )
    print("Benchmarking v4...", file=sys.stderr)
    v4_bench = benchmark_v4(
        db_path=v4_db_path,
        lat=args.lat,
        lon=args.lon,
        heading=args.heading,
        repeats=args.repeats,
        top_k=args.top_k,
        polyline_top_n=args.polyline_top_n,
        tile_radius=args.tile_radius,
        search_radius_m=args.search_radius_m,
        max_candidates=args.max_candidates,
    )
    executed_steps.extend(["benchmark_v1", "benchmark_v2", "benchmark_v3", "benchmark_v4"])

    update_analysis_summary = None
    four_tradeoff_update = None
    if not args.skip_update_analysis:
        print("Analyzing incremental updates from daily diffs...", file=sys.stderr)
        run_cmd(
            [
                sys.executable,
                str(ANALYZE_DAILY_DIFF),
                "--diff-dir",
                str(Path(args.diff_dir)),
                "--v3-db",
                str(v3_db_path),
                "--v4-db",
                str(v4_db_path),
                "--v2-tile-size-m",
                str(args.tile_size_m),
                "--v4-max-way-tiles",
                str(args.max_way_tiles),
                "--no-copy-dbs",
                "--csv-out",
                str(update_report_csv),
                "--json-out",
                str(update_report_json),
            ]
        )
        update_analysis_summary = json.loads(update_report_json.read_text(encoding="utf-8"))
        four_tradeoff_update = update_analysis_summary.get("four_tradeoff_update_daily_mean")
        if isinstance(four_tradeoff_update, dict):
            for payload in four_tradeoff_update.values():
                if isinstance(payload, dict) and "boundary_update_workload" in payload:
                    payload["polygon_update_workload"] = payload["boundary_update_workload"]
        executed_steps.append("analyze_daily_diff_impact")

    def metric_speedups(metric_key: str) -> Dict[str, Dict[str, Optional[float]]]:
        out: Dict[str, Dict[str, Optional[float]]] = {}
        for mode in ("bbox", "hybrid", "polyline"):
            v1 = v1_bench[metric_key][mode]["avg_ms"]
            v2 = v2_bench[metric_key][mode]["avg_ms"]
            v3 = v3_bench[metric_key][mode]["avg_ms"]
            v4 = v4_bench[metric_key][mode]["avg_ms"]
            out[mode] = {
                "v2_vs_v1": round(v1 / v2, 2) if v2 > 0 else None,
                "v3_vs_v1": round(v1 / v3, 2) if v3 > 0 else None,
                "v4_vs_v1": round(v1 / v4, 2) if v4 > 0 else None,
                "v4_vs_v2": round(v2 / v4, 2) if v4 > 0 else None,
            }
        return out

    maxspeed_speedups = metric_speedups("maxspeed")
    street_name_speedups = metric_speedups("street_name")
    city_name_speedups = metric_speedups("city_name")
    polygon_speedups = metric_speedups("polygon_containment")

    v2_catalog_path = v2_dist_dir / "catalog.v2.json"
    tile_count = None
    if v2_catalog_path.exists():
        try:
            tile_count = len(json.loads(v2_catalog_path.read_text(encoding="utf-8")).get("tiles", []))
        except Exception:
            tile_count = None

    report = {
        "schema_version": 4,
        "generated_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "region": args.region,
        "input_pbf": str(Path(args.input_pbf)),
        "executed_steps": executed_steps,
        "params": {
            "engine": args.engine,
            "max_geom_points": args.max_geom_points,
            "tile_size_m": args.tile_size_m,
            "subgrid": args.subgrid,
            "content_version": args.content_version,
            "max_area_tiles": args.max_area_tiles,
            "max_way_tiles": args.max_way_tiles,
            "lat": args.lat,
            "lon": args.lon,
            "heading": args.heading,
            "repeats": args.repeats,
            "top_k": args.top_k,
            "polyline_top_n": args.polyline_top_n,
            "tile_radius": args.tile_radius,
            "search_radius_m": args.search_radius_m,
            "max_candidates": args.max_candidates,
        },
        "artifacts": {
            "v1_dist_dir": str(v1_dist_dir),
            "v2_dist_dir": str(v2_dist_dir),
            "v3_db_path": str(v3_db_path),
            "v4_db_path": str(v4_db_path),
            "v1_size_bytes": bytes_recursive(v1_dist_dir),
            "v2_size_bytes": bytes_recursive(v2_dist_dir),
            "v3_size_bytes": bytes_file(v3_db_path),
            "v4_size_bytes": bytes_file(v4_db_path),
            "v2_tile_count": tile_count,
        },
        "benchmark_ms": {
            "maxspeed_retrieval": {
                "v1": v1_bench["maxspeed"],
                "v2": v2_bench["maxspeed"],
                "v3": v3_bench["maxspeed"],
                "v4": v4_bench["maxspeed"],
            },
            "street_name_retrieval": {
                "v1": v1_bench["street_name"],
                "v2": v2_bench["street_name"],
                "v3": v3_bench["street_name"],
                "v4": v4_bench["street_name"],
            },
            "city_name_retrieval": {
                "v1": v1_bench["city_name"],
                "v2": v2_bench["city_name"],
                "v3": v3_bench["city_name"],
                "v4": v4_bench["city_name"],
            },
            "boundary_retrieval": {
                "v1": v1_bench["city_name"],
                "v2": v2_bench["city_name"],
                "v3": v3_bench["city_name"],
                "v4": v4_bench["city_name"],
            },
            "polygon_containment_retrieval": {
                "v1": v1_bench["polygon_containment"],
                "v2": v2_bench["polygon_containment"],
                "v3": v3_bench["polygon_containment"],
                "v4": v4_bench["polygon_containment"],
            },
        },
        "speedup_x_avg": {
            "maxspeed_retrieval": maxspeed_speedups,
            "street_name_retrieval": street_name_speedups,
            "city_name_retrieval": city_name_speedups,
            "boundary_retrieval": city_name_speedups,
            "polygon_containment_retrieval": polygon_speedups,
        },
        "four_tradeoff_retrieval_hybrid_ms": {
            "S1_v1": {
                "maxspeed_retrieval_avg_ms": v1_bench["maxspeed"]["hybrid"]["avg_ms"],
                "street_name_retrieval_avg_ms": v1_bench["street_name"]["hybrid"]["avg_ms"],
                "city_name_retrieval_avg_ms": v1_bench["city_name"]["hybrid"]["avg_ms"],
                "boundary_retrieval_avg_ms": v1_bench["city_name"]["hybrid"]["avg_ms"],
                "polygon_containment_retrieval_avg_ms": v1_bench["polygon_containment"]["hybrid"]["avg_ms"],
            },
            "S2_v2": {
                "maxspeed_retrieval_avg_ms": v2_bench["maxspeed"]["hybrid"]["avg_ms"],
                "street_name_retrieval_avg_ms": v2_bench["street_name"]["hybrid"]["avg_ms"],
                "city_name_retrieval_avg_ms": v2_bench["city_name"]["hybrid"]["avg_ms"],
                "boundary_retrieval_avg_ms": v2_bench["city_name"]["hybrid"]["avg_ms"],
                "polygon_containment_retrieval_avg_ms": v2_bench["polygon_containment"]["hybrid"]["avg_ms"],
            },
            "S3_v3": {
                "maxspeed_retrieval_avg_ms": v3_bench["maxspeed"]["hybrid"]["avg_ms"],
                "street_name_retrieval_avg_ms": v3_bench["street_name"]["hybrid"]["avg_ms"],
                "city_name_retrieval_avg_ms": v3_bench["city_name"]["hybrid"]["avg_ms"],
                "boundary_retrieval_avg_ms": v3_bench["city_name"]["hybrid"]["avg_ms"],
                "polygon_containment_retrieval_avg_ms": v3_bench["polygon_containment"]["hybrid"]["avg_ms"],
            },
            "S4_v4": {
                "maxspeed_retrieval_avg_ms": v4_bench["maxspeed"]["hybrid"]["avg_ms"],
                "street_name_retrieval_avg_ms": v4_bench["street_name"]["hybrid"]["avg_ms"],
                "city_name_retrieval_avg_ms": v4_bench["city_name"]["hybrid"]["avg_ms"],
                "boundary_retrieval_avg_ms": v4_bench["city_name"]["hybrid"]["avg_ms"],
                "polygon_containment_retrieval_avg_ms": v4_bench["polygon_containment"]["hybrid"]["avg_ms"],
            },
        },
        "four_tradeoff_update": four_tradeoff_update,
        "update_analysis": {
            "diff_dir": str(Path(args.diff_dir)),
            "csv_path": str(update_report_csv) if update_analysis_summary is not None else None,
            "json_path": str(update_report_json) if update_analysis_summary is not None else None,
        },
    }

    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(report["speedup_x_avg"], sort_keys=True), file=sys.stderr)
    print(f"Wrote benchmark report: {report_path}", file=sys.stderr)
    print(json.dumps(report, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
