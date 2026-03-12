#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import shutil
from pathlib import Path

WALKING_LOG_NAME = "20260312_000427_801_drive_match_log.ndjson"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build compact replay trace bundle for Android instrumented matcher regressions.")
    parser.add_argument("--logs-root", required=True, help="Path to inspector/logs root.")
    parser.add_argument("--output-dir", required=True, help="Directory where compact replay traces should be written.")
    return parser.parse_args()


def iter_drive_match_logs(directory: Path) -> list[Path]:
    if not directory.exists():
        raise SystemExit(f"Missing logs directory: {directory}")
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix == ".ndjson" and "drive_match_log" in path.name
    )


def iter_geom_drive_match_logs(directory: Path) -> list[Path]:
    if not directory.exists():
        return []
    return sorted(
        path
        for path in directory.iterdir()
        if path.is_file() and path.suffix == ".ndjson" and "drive_match_log" in path.name
    )


def slugify(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name).strip("_")


def compact_candidate_trace(candidate: dict) -> dict:
    return {
        "rank": int(candidate.get("rank") or 0),
        "way_id": candidate.get("wayID"),
        "score": candidate.get("score"),
        "distance_m": candidate.get("distanceM"),
        "geometry_score": candidate.get("geometryScore"),
        "endpoint_proximity_m": candidate.get("endpointProximityM"),
        "continuity_class": candidate.get("continuityClass"),
        "highway": candidate.get("highway"),
        "service": candidate.get("service"),
        "street_name": candidate.get("streetName"),
        "street_ref": candidate.get("streetRef"),
        "tunnel": candidate.get("tunnel"),
        "tunnel_selectable": bool(candidate.get("tunnelSelectable", False)),
        "corridor_selectable": bool(candidate.get("corridorSelectable", False)),
        "portal_eligible": bool(candidate.get("portalEligible", False)),
        "is_selected": bool(candidate.get("isSelected", False)),
    }


def compact_result(result: dict | None) -> dict | None:
    if not result:
        return None
    return {
        "way_id": result.get("wayID"),
        "highway": result.get("highway"),
        "street_ref": result.get("streetRef"),
        "is_tunnel_segment": bool(result.get("isTunnelSegment", False)),
        "nearby_tunnel_candidate_way_ids": [
            str(value).strip()
            for value in (result.get("nearbyTunnelCandidateWayIDs") or [])
            if str(value).strip()
        ],
        "nearby_tunnel_candidate_refs": [
            str(value).strip()
            for value in (result.get("nearbyTunnelCandidateRefs") or [])
            if str(value).strip()
        ],
        "matched_endpoint_proximity_m": result.get("matchedEndpointProximityM"),
        "candidate_traces": [
            compact_candidate_trace(candidate)
            for candidate in (result.get("candidateTraces") or [])
        ],
    }


def compact_entry(payload: dict) -> dict:
    return {
        "fix_id": int(payload["fixID"]),
        "timestamp_utc": payload["timestampUTC"],
        "lat": float(payload["lat"]),
        "lon": float(payload["lon"]),
        "speed_kmh": float(payload["speedKmh"]),
        "horizontal_acc_m": float(payload["horizontalAccM"]),
        "course_deg": float(payload.get("courseDeg", -1.0)),
        "gps_signal_bars": int(payload.get("gpsSignalBars", 0)),
        "status": payload.get("status", "unknown"),
        "result": compact_result(payload.get("result")),
    }


def write_compact_log(source: Path, destination: Path) -> int:
    entry_count = 0
    with source.open() as input_handle, destination.open("w") as output_handle:
        for raw_line in input_handle:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            payload = json.loads(raw_line)
            output_handle.write(json.dumps(compact_entry(payload), sort_keys=True) + "\n")
            entry_count += 1
    return entry_count


def emit_group(paths: list[Path], output_dir: Path, prefix: str) -> list[dict]:
    emitted: list[dict] = []
    for source in paths:
        file_name = f"{prefix}__{slugify(source.name)}.jsonl"
        destination = output_dir / file_name
        entry_count = write_compact_log(source, destination)
        emitted.append(
            {
                "name": source.name,
                "file": file_name,
                "entry_count": entry_count,
            }
        )
    return emitted


def main() -> None:
    args = parse_args()
    logs_root = Path(args.logs_root).resolve()
    output_dir = Path(args.output_dir).resolve()
    field_logs = iter_drive_match_logs(logs_root)
    geom_logs = iter_geom_drive_match_logs(logs_root / "geom")
    if not field_logs:
        raise SystemExit(f"No drive_match_log ndjson files found in {logs_root}")

    if output_dir.exists():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    manifest = {
        "field_logs": emit_group(field_logs, output_dir, "field"),
        "geom_logs": emit_group(geom_logs, output_dir, "geom"),
        "walking_log": None,
    }
    for entry in manifest["field_logs"]:
        if entry["name"] == WALKING_LOG_NAME:
            manifest["walking_log"] = entry
            break

    (output_dir / "manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    print(
        "built replay trace bundle",
        f"output={output_dir}",
        f"field_logs={len(manifest['field_logs'])}",
        f"geom_logs={len(manifest['geom_logs'])}",
        f"walking={'yes' if manifest['walking_log'] else 'no'}",
    )


if __name__ == "__main__":
    main()
