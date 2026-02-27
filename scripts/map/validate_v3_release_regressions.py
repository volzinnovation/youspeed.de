#!/usr/bin/env python3
"""Validate v3 release DB/query regressions before publishing artifacts.

This script enforces contract-level checks aligned with the benchmark dimensions used
in the paper work:
- maxspeed retrieval
- street-name retrieval
- city-name / polygon-containment retrieval
"""

from __future__ import annotations

import argparse
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import Dict, Tuple

NUMERIC_SPEED_RE = re.compile(r"^(\d{1,3})")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Validate v3 release regression checks")
    parser.add_argument("--db", required=True, help="Path to speeds_v3.sqlite")
    parser.add_argument("--probe-way-id", default="17721265", help="Way ID used as query probe anchor")
    parser.add_argument("--expected-maxspeed-kmh", type=int, default=30, help="Expected explicit maxspeed at probe")
    parser.add_argument(
        "--probe-ref-way-id",
        default="",
        help="Optional second probe way ID used to validate exact ref tag value",
    )
    parser.add_argument(
        "--expected-ref",
        default="",
        help="Expected ref value at --probe-ref-way-id (exact string after trim)",
    )
    parser.add_argument(
        "--query-script",
        default="scripts/map/query_speed_limit_v3.py",
        help="Path to v3 query script",
    )
    parser.add_argument(
        "--out-json",
        default="",
        help="Optional output JSON path for regression summary",
    )
    parser.add_argument("--top-k", type=int, default=3)
    parser.add_argument("--polyline-top-n", type=int, default=64)
    return parser.parse_args()


def fail(message: str) -> int:
    print(f"Regression check failed: {message}", file=sys.stderr)
    return 1


def parse_explicit_speed(row: sqlite3.Row) -> int | None:
    for key in ("maxspeed", "zone_maxspeed"):
        raw = row[key]
        if isinstance(raw, str):
            m = NUMERIC_SPEED_RE.match(raw.strip())
            if m:
                return int(m.group(1))
    return None


def inspect_schema_contract(db_path: Path) -> Dict:
    conn = sqlite3.connect(str(db_path))
    try:
        way_columns = {
            str(row[1]) for row in conn.execute("PRAGMA table_info(ways)")
        }
        area_columns = {
            str(row[1]) for row in conn.execute("PRAGMA table_info(areas)")
        }

        if "street_name" not in way_columns:
            raise RuntimeError("schema contract failed: ways.street_name column missing")
        if "ref" not in way_columns:
            raise RuntimeError("schema contract failed: ways.ref column missing")
        for required_way_column in ("service", "tunnel", "bridge", "covered", "location", "layer", "level"):
            if required_way_column not in way_columns:
                raise RuntimeError(f"schema contract failed: ways.{required_way_column} column missing")
        if "name" not in area_columns:
            raise RuntimeError("schema contract failed: areas.name column missing")
        if "residential" not in area_columns:
            raise RuntimeError("schema contract failed: areas.residential column missing")
        if "parking" not in area_columns:
            raise RuntimeError("schema contract failed: areas.parking column missing")
        if "points_json" not in area_columns:
            raise RuntimeError("schema contract failed: areas.points_json column missing")

        ways_with_street_name = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM ways
                WHERE street_name IS NOT NULL
                  AND trim(street_name) <> ''
                """
            ).fetchone()[0]
        )
        areas_with_name = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM areas
                WHERE name IS NOT NULL
                  AND trim(name) <> ''
                """
            ).fetchone()[0]
        )
        ways_with_nonempty_ref = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM ways
                WHERE ref IS NOT NULL
                  AND trim(ref) <> ''
                """
            ).fetchone()[0]
        )
        ways_with_service = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM ways
                WHERE service IS NOT NULL
                  AND trim(service) <> ''
                """
            ).fetchone()[0]
        )
        ways_with_parking_aisle = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM ways
                WHERE lower(trim(service)) = 'parking_aisle'
                """
            ).fetchone()[0]
        )
        ways_with_vertical_context = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM ways
                WHERE (tunnel IS NOT NULL AND trim(tunnel) <> '')
                   OR (bridge IS NOT NULL AND trim(bridge) <> '')
                   OR (covered IS NOT NULL AND trim(covered) <> '')
                   OR (location IS NOT NULL AND trim(location) <> '')
                   OR (layer IS NOT NULL AND trim(layer) <> '')
                   OR (level IS NOT NULL AND trim(level) <> '')
                """
            ).fetchone()[0]
        )
        residential_areas_with_polygons = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM areas
                WHERE residential IS NOT NULL
                  AND trim(residential) <> ''
                  AND points_json IS NOT NULL
                  AND trim(points_json) <> ''
                """
            ).fetchone()[0]
        )
        parking_areas_with_polygons = int(
            conn.execute(
                """
                SELECT COUNT(*)
                FROM areas
                WHERE parking IS NOT NULL
                  AND trim(parking) <> ''
                  AND points_json IS NOT NULL
                  AND trim(points_json) <> ''
                """
            ).fetchone()[0]
        )
    finally:
        conn.close()

    if ways_with_street_name <= 0:
        raise RuntimeError("schema/data contract failed: ways.street_name has no non-empty values")
    if areas_with_name <= 0:
        raise RuntimeError("schema/data contract failed: areas.name has no non-empty values")
    if ways_with_nonempty_ref <= 0:
        raise RuntimeError("schema/data contract failed: ways.ref has no non-empty values")
    if ways_with_service <= 0:
        raise RuntimeError("schema/data contract failed: ways.service has no non-empty values")
    if residential_areas_with_polygons <= 0:
        raise RuntimeError("schema/data contract failed: areas.residential has no polygon rows")

    return {
        "ways_has_street_name_column": True,
        "ways_has_ref_column": True,
        "areas_has_name_column": True,
        "areas_has_residential_column": True,
        "areas_has_parking_column": True,
        "areas_has_points_json_column": True,
        "ways_with_nonempty_street_name": ways_with_street_name,
        "ways_with_nonempty_ref": ways_with_nonempty_ref,
        "ways_with_nonempty_service": ways_with_service,
        "ways_with_service_parking_aisle": ways_with_parking_aisle,
        "ways_with_vertical_context_tags": ways_with_vertical_context,
        "areas_with_nonempty_name": areas_with_name,
        "residential_areas_with_polygons": residential_areas_with_polygons,
        "parking_areas_with_polygons": parking_areas_with_polygons,
    }


def load_probe(db_path: Path, way_id: str) -> Tuple[float, float, sqlite3.Row]:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT way_id, street_name, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed,
                   (min_lat + max_lat) / 2.0 AS probe_lat,
                   (min_lon + max_lon) / 2.0 AS probe_lon
            FROM ways
            WHERE way_id = ?
            LIMIT 1
            """,
            (way_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        raise RuntimeError(f"probe way_id={way_id} not found")

    lat = float(row["probe_lat"])
    lon = float(row["probe_lon"])
    return lat, lon, row


def load_way_ref(db_path: Path, way_id: str) -> str | None:
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT ref
            FROM ways
            WHERE way_id = ?
            LIMIT 1
            """,
            (way_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None:
        raise RuntimeError(f"ref probe way_id={way_id} not found")
    return row["ref"]


def run_query(
    query_script: Path,
    db_path: Path,
    lat: float,
    lon: float,
    mode: str,
    top_k: int,
    polyline_top_n: int,
) -> Dict:
    cmd = [
        sys.executable,
        str(query_script),
        "--db",
        str(db_path),
        "--lat",
        str(lat),
        "--lon",
        str(lon),
        "--distance-mode",
        mode,
        "--top-k",
        str(top_k),
        "--polyline-top-n",
        str(polyline_top_n),
    ]
    cp = subprocess.run(cmd, check=True, capture_output=True, text=True)
    try:
        return json.loads(cp.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"query output was not valid JSON for mode={mode}: {exc}") from exc


def ensure_payload_contract(payload: Dict, mode: str) -> None:
    summary = payload.get("summary")
    if not isinstance(summary, dict):
        raise RuntimeError(f"summary missing for mode={mode}")

    if summary.get("distance_mode_requested") != mode:
        raise RuntimeError(
            f"distance_mode_requested mismatch for mode={mode}: {summary.get('distance_mode_requested')!r}"
        )

    if summary.get("has_street_name_column") is not True:
        raise RuntimeError(f"has_street_name_column is not true for mode={mode}")
    if summary.get("has_ref_column") is not True:
        raise RuntimeError(f"has_ref_column is not true for mode={mode}")
    if summary.get("has_service_column") is not True:
        raise RuntimeError(f"has_service_column is not true for mode={mode}")
    if summary.get("has_tunnel_column") is not True:
        raise RuntimeError(f"has_tunnel_column is not true for mode={mode}")
    if summary.get("has_bridge_column") is not True:
        raise RuntimeError(f"has_bridge_column is not true for mode={mode}")
    if summary.get("has_covered_column") is not True:
        raise RuntimeError(f"has_covered_column is not true for mode={mode}")
    if summary.get("has_location_column") is not True:
        raise RuntimeError(f"has_location_column is not true for mode={mode}")
    if summary.get("has_layer_column") is not True:
        raise RuntimeError(f"has_layer_column is not true for mode={mode}")
    if summary.get("has_level_column") is not True:
        raise RuntimeError(f"has_level_column is not true for mode={mode}")
    if summary.get("residential_mode") != "polygon_containment":
        raise RuntimeError(f"residential_mode is not polygon_containment for mode={mode}")
    if "residential_candidate_polygons" not in summary:
        raise RuntimeError(f"summary.residential_candidate_polygons missing for mode={mode}")
    if "residential_containing_polygons" not in summary:
        raise RuntimeError(f"summary.residential_containing_polygons missing for mode={mode}")

    for required in (
        "city_name",
        "city_source",
        "city_candidate_boundaries",
        "city_containing_boundaries",
        "city_place_candidates",
    ):
        if required not in summary:
            raise RuntimeError(f"summary.{required} missing for mode={mode}")

    top = payload.get("top_candidates")
    if not isinstance(top, list) or not top:
        raise RuntimeError(f"top_candidates empty for mode={mode}")

    first = top[0]
    if not isinstance(first, dict):
        raise RuntimeError(f"top_candidates[0] not an object for mode={mode}")
    if "street_name" not in first:
        raise RuntimeError(f"top_candidates[0].street_name missing for mode={mode}")
    if "ref" not in first:
        raise RuntimeError(f"top_candidates[0].ref missing for mode={mode}")
    for required in ("service", "tunnel", "bridge", "covered", "location", "layer", "level"):
        if required not in first:
            raise RuntimeError(f"top_candidates[0].{required} missing for mode={mode}")

    timing = payload.get("timing_ms")
    if not isinstance(timing, dict):
        raise RuntimeError(f"timing_ms missing for mode={mode}")
    for required in ("load_index", "load_candidates", "city_resolve", "polyline_refine", "score_and_rank", "total"):
        if required not in timing:
            raise RuntimeError(f"timing_ms.{required} missing for mode={mode}")


def main() -> int:
    args = parse_args()
    db_path = Path(args.db)
    if not db_path.exists():
        return fail(f"db not found: {db_path}")

    query_script = Path(args.query_script)
    if not query_script.exists():
        return fail(f"query script not found: {query_script}")

    try:
        schema_contract = inspect_schema_contract(db_path)
    except Exception as exc:
        return fail(str(exc))

    try:
        lat, lon, probe = load_probe(db_path, args.probe_way_id)
    except Exception as exc:
        return fail(str(exc))

    parsed_speed = parse_explicit_speed(probe)
    if parsed_speed != int(args.expected_maxspeed_kmh):
        return fail(
            "explicit speed mismatch at probe "
            f"way_id={args.probe_way_id}: expected={args.expected_maxspeed_kmh}, "
            f"got={parsed_speed}, raw_maxspeed={probe['maxspeed']!r}, zone_maxspeed={probe['zone_maxspeed']!r}"
        )
    probe_street_name = probe["street_name"]
    if not isinstance(probe_street_name, str) or not probe_street_name.strip():
        return fail(f"probe way_id={args.probe_way_id} has empty street_name")

    probe_ref_way_id = str(args.probe_ref_way_id or "").strip()
    expected_ref = str(args.expected_ref or "").strip()
    ref_probe: Dict[str, str | None] | None = None
    if probe_ref_way_id or expected_ref:
        if not probe_ref_way_id:
            return fail("--probe-ref-way-id is required when --expected-ref is provided")
        if not expected_ref:
            return fail("--expected-ref is required when --probe-ref-way-id is provided")
        try:
            ref_value = load_way_ref(db_path, probe_ref_way_id)
        except Exception as exc:
            return fail(str(exc))
        normalized_ref = ref_value.strip() if isinstance(ref_value, str) else ""
        if normalized_ref != expected_ref:
            return fail(
                "ref mismatch at probe "
                f"way_id={probe_ref_way_id}: expected={expected_ref!r}, got={ref_value!r}"
            )
        ref_probe = {
            "probe_ref_way_id": probe_ref_way_id,
            "expected_ref": expected_ref,
            "actual_ref": ref_value,
        }

    report: Dict[str, Dict[str, float | int | str | None]] = {}
    modes = ("bbox", "hybrid", "polyline")
    try:
        for mode in modes:
            payload = run_query(
                query_script=query_script,
                db_path=db_path,
                lat=lat,
                lon=lon,
                mode=mode,
                top_k=args.top_k,
                polyline_top_n=args.polyline_top_n,
            )
            ensure_payload_contract(payload, mode)

            summary = payload["summary"]
            timing = payload["timing_ms"]
            top0 = payload["top_candidates"][0]

            report[mode] = {
                "maxspeed_retrieval_ms": float(timing["total"]),
                "street_name_retrieval_ms": float(timing["total"]),
                "city_name_retrieval_ms": float(timing["city_resolve"]),
                "polygon_containment_retrieval_ms": float(timing["city_resolve"]),
                "effective_speed_kmh": int(summary["effective_speed_kmh"]) if summary.get("effective_speed_kmh") is not None else None,
                "effective_speed_source": summary.get("effective_speed_source"),
                "street_name": top0.get("street_name"),
                "city_name": summary.get("city_name"),
                "city_source": summary.get("city_source"),
            }

            if report[mode]["effective_speed_kmh"] != int(args.expected_maxspeed_kmh):
                raise RuntimeError(
                    f"effective speed mismatch for mode={mode}: "
                    f"expected={args.expected_maxspeed_kmh}, got={report[mode]['effective_speed_kmh']}"
                )
    except subprocess.CalledProcessError as exc:
        stderr = exc.stderr.strip() if isinstance(exc.stderr, str) else ""
        stdout = exc.stdout.strip() if isinstance(exc.stdout, str) else ""
        return fail(
            f"query subprocess failed for mode run (rc={exc.returncode}); stderr={stderr!r}; stdout={stdout[:300]!r}"
        )
    except Exception as exc:
        return fail(str(exc))

    payload = {
        "check": "v3_release_regression",
        "db": str(db_path),
        "probe_way_id": str(args.probe_way_id),
        "probe_lat": lat,
        "probe_lon": lon,
        "expected_maxspeed_kmh": int(args.expected_maxspeed_kmh),
        "schema_contract": schema_contract,
        "paper_benchmark_smoke": report,
    }
    if ref_probe is not None:
        payload["ref_probe"] = ref_probe

    if args.out_json:
        out = Path(args.out_json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
