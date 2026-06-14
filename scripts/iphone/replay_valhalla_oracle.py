#!/usr/bin/env python3
"""Replay drive-match logs through Valhalla as an offline oracle benchmark."""

from __future__ import annotations

import argparse
import json
import math
import statistics
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from valhalla import Actor


REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REFERENCE_ARTIFACT = REPO_ROOT / "tmp" / "m12_continuity_native_benchmark.json"
DEFAULT_OUTPUT_JSON = REPO_ROOT / "tmp" / "valhalla_oracle_benchmark.json"
DEFAULT_OUTPUT_CSV = REPO_ROOT / "tmp" / "valhalla_oracle_benchmark.csv"
DEFAULT_OUTPUT_DIFF_CSV = REPO_ROOT / "tmp" / "valhalla_oracle_benchmark.diff.csv"
DEFAULT_MAX_POINTS = 250
DEFAULT_OVERLAP = 30
DEFAULT_BREAKAGE_DISTANCE_M = 2000.0
DEFAULT_MAX_TIME_GAP_S = 120.0
DEFAULT_MAX_DISTANCE_GAP_M = 1500.0
DEFAULT_SEARCH_RADIUS_M = 100.0


@dataclass
class ReplayMetrics:
    replayed_fix_count: int = 0
    predicted_fix_count: int = 0
    unmatched_fix_count: int = 0
    pseudo_label_example_count: int = 0
    correct_pseudo_label_count: int = 0
    changed_example_count: int = 0
    changed_correct_count: int = 0
    unchanged_example_count: int = 0
    unchanged_correct_count: int = 0
    logged_agreement_count: int = 0
    logged_comparable_count: int = 0
    recovered_examples: int = 0
    regressed_examples: int = 0
    trace_window_count: int = 0
    failed_trace_window_count: int = 0
    locate_fallback_count: int = 0
    locate_fallback_time_ms: float = 0.0

    @property
    def accuracy(self) -> float:
        if self.pseudo_label_example_count == 0:
            return 0.0
        return self.correct_pseudo_label_count / self.pseudo_label_example_count

    @property
    def changed_recall(self) -> float:
        if self.changed_example_count == 0:
            return 0.0
        return self.changed_correct_count / self.changed_example_count

    @property
    def unchanged_accuracy(self) -> float:
        if self.unchanged_example_count == 0:
            return 0.0
        return self.unchanged_correct_count / self.unchanged_example_count

    @property
    def logged_agreement(self) -> float:
        if self.logged_comparable_count == 0:
            return 0.0
        return self.logged_agreement_count / self.logged_comparable_count

    @property
    def net_corrections(self) -> int:
        return self.recovered_examples - self.regressed_examples

    @property
    def coverage(self) -> float:
        if self.replayed_fix_count == 0:
            return 0.0
        return self.predicted_fix_count / self.replayed_fix_count


@dataclass
class TraceWindowStats:
    log_name: str
    start_index: int
    end_index: int
    point_count: int
    query_time_ms: float
    gps_accuracy_m: float
    search_radius_m: float
    used_timestamps: bool
    matched_point_count: int
    matched_fraction: float
    error: str | None = None


@dataclass
class FixPrediction:
    way_id: str | None
    street_name: str | None
    matched_type: str | None
    distance_along_edge: float | None
    edge_index: int | None
    window_start_index: int
    window_end_index: int
    boundary_margin: int


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--config",
        type=Path,
        required=True,
        help="Path to a Valhalla JSON config whose tile_dir/tile_extract is already built.",
    )
    parser.add_argument(
        "log_paths",
        nargs="*",
        type=Path,
        help="Input drive-match logs. Defaults to the reference benchmark artifact corpus.",
    )
    parser.add_argument(
        "--reference-artifact",
        type=Path,
        default=DEFAULT_REFERENCE_ARTIFACT,
        help="Artifact whose logPaths should be reused when log paths are omitted.",
    )
    parser.add_argument("--output-json", type=Path, default=DEFAULT_OUTPUT_JSON)
    parser.add_argument("--output-csv", type=Path, default=DEFAULT_OUTPUT_CSV)
    parser.add_argument("--output-diff-csv", type=Path, default=DEFAULT_OUTPUT_DIFF_CSV)
    parser.add_argument("--max-points", type=int, default=DEFAULT_MAX_POINTS)
    parser.add_argument("--overlap", type=int, default=DEFAULT_OVERLAP)
    parser.add_argument("--breakage-distance-m", type=float, default=DEFAULT_BREAKAGE_DISTANCE_M)
    parser.add_argument("--max-time-gap-s", type=float, default=DEFAULT_MAX_TIME_GAP_S)
    parser.add_argument("--max-distance-gap-m", type=float, default=DEFAULT_MAX_DISTANCE_GAP_M)
    return parser.parse_args()


def ensure_parent_directory(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def load_reference_log_paths(path: Path) -> list[Path]:
    payload = json.loads(path.read_text())
    return [Path(raw_path) for raw_path in payload.get("logPaths", [])]


def default_log_paths(reference_artifact: Path) -> list[Path]:
    if reference_artifact.is_file():
        return load_reference_log_paths(reference_artifact)
    return sorted((REPO_ROOT / "inspector" / "logs").glob("*.ndjson"))


def load_drive_match_log_entries(path: Path) -> list[dict[str, Any]]:
    entries: list[dict[str, Any]] = []
    with path.open() as handle:
        for raw_line in handle:
            raw_line = raw_line.strip()
            if not raw_line:
                continue
            payload = json.loads(raw_line)
            if "fixID" in payload:
                entries.append(payload)
    return entries


def parse_timestamp_utc(value: str) -> float:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    radius_m = 6371008.8
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
    return 2 * radius_m * math.asin(math.sqrt(a))


def hindsight_pseudo_label_way_id(
    entries: list[dict[str, Any]],
    index: int,
    future_window: int = 5,
    min_future_run_length: int = 5,
    min_agreement_ratio: float = 0.8,
) -> str | None:
    if index < 0 or index >= len(entries):
        return None
    row_result = entries[index].get("result")
    if not isinstance(row_result, dict):
        return None
    candidate_way_ids = [
        str(trace["wayID"])
        for trace in row_result.get("candidateTraces", [])
        if isinstance(trace, dict) and trace.get("wayID") is not None
    ]
    if not candidate_way_ids:
        return None

    upper_bound = index + 1 + future_window
    if upper_bound > len(entries):
        return None
    future_way_ids = []
    for entry in entries[index + 1 : upper_bound]:
        result = entry.get("result")
        if not isinstance(result, dict) or result.get("wayID") is None:
            return None
        future_way_ids.append(str(result["wayID"]))

    agreement_threshold = math.ceil(future_window * min_agreement_ratio)
    counts: dict[str, int] = {}
    for way_id in future_way_ids:
        counts[way_id] = counts.get(way_id, 0) + 1
    if not counts:
        return None
    def majority_sort_key(item: tuple[str, int]) -> tuple[int, str]:
        way_id, count = item
        if way_id.isdigit():
            return (count, f"{int(way_id):020d}")
        return (count, way_id)

    majority_way_id = max(counts.items(), key=majority_sort_key)[0]
    agreement_count = counts[majority_way_id]
    if agreement_count < agreement_threshold or majority_way_id not in candidate_way_ids:
        return None

    future_run_length = 0
    for way_id in future_way_ids:
        if way_id != majority_way_id:
            break
        future_run_length += 1
    if future_run_length < min_future_run_length:
        return None
    return majority_way_id


def candidate_rank(way_id: str | None, result: dict[str, Any] | None) -> int | None:
    if way_id is None or not isinstance(result, dict):
        return None
    for trace in result.get("candidateTraces", []):
        if isinstance(trace, dict) and trace.get("wayID") is not None and str(trace["wayID"]) == way_id:
            rank = trace.get("rank")
            return int(rank) if rank is not None else None
    return None


def candidate_trace(way_id: str | None, result: dict[str, Any] | None) -> dict[str, Any] | None:
    if way_id is None or not isinstance(result, dict):
        return None
    for trace in result.get("candidateTraces", []):
        if isinstance(trace, dict) and trace.get("wayID") is not None and str(trace["wayID"]) == way_id:
            return trace
    return None


def logged_simple_reason(entry: dict[str, Any]) -> str | None:
    result = entry.get("result")
    if not isinstance(result, dict):
        return None
    for step in result.get("selectionTrace", []):
        if not isinstance(step, dict) or step.get("step") != "simple_speed_ref_heuristic":
            continue
        detail = step.get("detail")
        if not isinstance(detail, str):
            return None
        marker = "reason="
        if marker not in detail:
            return None
        remainder = detail.split(marker, 1)[1]
        return remainder.split(" ", 1)[0]
    return None


def percentile(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    if len(values) == 1:
        return values[0]
    values = sorted(values)
    rank = (len(values) - 1) * p
    lower = math.floor(rank)
    upper = math.ceil(rank)
    if lower == upper:
        return values[lower]
    weight = rank - lower
    return values[lower] * (1.0 - weight) + values[upper] * weight


def make_trace_request(entries: list[dict[str, Any]], breakage_distance_m: float) -> tuple[dict[str, Any], float, float]:
    accuracies = [
        float(entry["horizontalAccM"])
        for entry in entries
        if isinstance(entry.get("horizontalAccM"), (int, float)) and math.isfinite(entry["horizontalAccM"]) and entry["horizontalAccM"] > 0
    ]
    gps_accuracy_m = min(50.0, max(5.0, statistics.median(accuracies) if accuracies else 10.0))
    search_radius_m = min(
        DEFAULT_SEARCH_RADIUS_M,
        max(15.0, percentile(accuracies, 0.9) * 2.0 if accuracies else gps_accuracy_m * 2.0),
    )
    shape = [
        {
            "lat": float(entry["lat"]),
            "lon": float(entry["lon"]),
            "time": int(parse_timestamp_utc(entry["timestampUTC"])),
        }
        for entry in entries
    ]
    request = {
        "shape": shape,
        "costing": "auto",
        "shape_match": "map_snap",
        "use_timestamps": True,
        "trace_options": {
            "gps_accuracy": gps_accuracy_m,
            "search_radius": search_radius_m,
            "breakage_distance": breakage_distance_m,
            "interpolation_distance": 1,
        },
        "filters": {
            "attributes": [
                "edge.way_id",
                "edge.id",
                "edge.names",
                "matched.point",
                "matched.edge_index",
                "matched.type",
                "matched.distance_along_edge",
            ],
            "action": "include",
        },
    }
    return request, gps_accuracy_m, search_radius_m


def split_windows(
    entries: list[dict[str, Any]],
    max_points: int,
    overlap: int,
    max_time_gap_s: float,
    max_distance_gap_m: float,
) -> list[tuple[int, int]]:
    if not entries:
        return []

    segments: list[tuple[int, int]] = []
    segment_start = 0
    for index in range(1, len(entries)):
        previous = entries[index - 1]
        current = entries[index]
        time_gap_s = parse_timestamp_utc(current["timestampUTC"]) - parse_timestamp_utc(previous["timestampUTC"])
        distance_gap_m = haversine_m(previous["lat"], previous["lon"], current["lat"], current["lon"])
        if time_gap_s > max_time_gap_s or distance_gap_m > max_distance_gap_m:
            segments.append((segment_start, index))
            segment_start = index
    segments.append((segment_start, len(entries)))

    windows: list[tuple[int, int]] = []
    effective_overlap = min(overlap, max_points - 1)
    step = max(1, max_points - effective_overlap)
    for segment_start, segment_end in segments:
        start = segment_start
        while start < segment_end:
            end = min(start + max_points, segment_end)
            windows.append((start, end))
            if end >= segment_end:
                break
            start += step
    return windows


def trace_entries(
    actor: Actor,
    log_name: str,
    entries: list[dict[str, Any]],
    start_index: int,
    end_index: int,
    breakage_distance_m: float,
) -> tuple[dict[int, FixPrediction], TraceWindowStats]:
    window_entries = entries[start_index:end_index]
    request, gps_accuracy_m, search_radius_m = make_trace_request(window_entries, breakage_distance_m)

    t0 = time.perf_counter()
    used_timestamps = True
    try:
        response = actor.trace_attributes(request)
    except Exception:
        request["use_timestamps"] = False
        used_timestamps = False
        response = actor.trace_attributes(request)
    query_time_ms = (time.perf_counter() - t0) * 1000.0

    edges = response.get("edges", [])
    matched_points = response.get("matched_points", [])
    predictions: dict[int, FixPrediction] = {}
    for local_index, matched_point in enumerate(matched_points):
        if not isinstance(matched_point, dict):
            continue
        edge_index = matched_point.get("edge_index")
        if not isinstance(edge_index, int) or edge_index < 0 or edge_index >= len(edges):
            continue
        edge = edges[edge_index]
        way_id = edge.get("way_id")
        if way_id is None:
            continue
        names = edge.get("names") or []
        street_name = names[0] if names else None
        global_index = start_index + local_index
        predictions[global_index] = FixPrediction(
            way_id=str(way_id),
            street_name=street_name,
            matched_type=matched_point.get("type"),
            distance_along_edge=matched_point.get("distance_along_edge"),
            edge_index=edge_index,
            window_start_index=start_index,
            window_end_index=end_index,
            boundary_margin=min(local_index, len(window_entries) - 1 - local_index),
        )

    stats = TraceWindowStats(
        log_name=log_name,
        start_index=start_index,
        end_index=end_index,
        point_count=len(window_entries),
        query_time_ms=query_time_ms,
        gps_accuracy_m=gps_accuracy_m,
        search_radius_m=search_radius_m,
        used_timestamps=used_timestamps,
        matched_point_count=len(predictions),
        matched_fraction=len(predictions) / len(window_entries) if window_entries else 0.0,
    )
    return predictions, stats


def load_predictions_for_log(
    actor: Actor,
    log_name: str,
    entries: list[dict[str, Any]],
    max_points: int,
    overlap: int,
    breakage_distance_m: float,
    max_time_gap_s: float,
    max_distance_gap_m: float,
) -> tuple[dict[int, FixPrediction], list[TraceWindowStats]]:
    best_predictions: dict[int, FixPrediction] = {}
    window_stats: list[TraceWindowStats] = []
    windows = split_windows(entries, max_points, overlap, max_time_gap_s, max_distance_gap_m)
    for start_index, end_index in windows:
        try:
            predictions, stats = trace_entries(
                actor=actor,
                log_name=log_name,
                entries=entries,
                start_index=start_index,
                end_index=end_index,
                breakage_distance_m=breakage_distance_m,
            )
        except Exception as exc:
            window_stats.append(
                TraceWindowStats(
                    log_name=log_name,
                    start_index=start_index,
                    end_index=end_index,
                    point_count=end_index - start_index,
                    query_time_ms=0.0,
                    gps_accuracy_m=0.0,
                    search_radius_m=0.0,
                    used_timestamps=False,
                    matched_point_count=0,
                    matched_fraction=0.0,
                    error=str(exc),
                )
            )
            continue
        window_stats.append(stats)
        for index, prediction in predictions.items():
            current = best_predictions.get(index)
            if current is None or prediction.boundary_margin > current.boundary_margin:
                best_predictions[index] = prediction
    return best_predictions, window_stats


def locate_fallback_prediction(actor: Actor, entry: dict[str, Any], index: int) -> tuple[FixPrediction | None, float]:
    location = {
        "lat": float(entry["lat"]),
        "lon": float(entry["lon"]),
    }
    heading = entry.get("courseDeg")
    if isinstance(heading, (int, float)) and heading >= 0.0:
        location["heading"] = float(heading)

    horizontal_accuracy_m = entry.get("horizontalAccM")
    if isinstance(horizontal_accuracy_m, (int, float)) and math.isfinite(horizontal_accuracy_m) and horizontal_accuracy_m > 0:
        radius_m = max(15.0, min(100.0, float(horizontal_accuracy_m) * 3.0))
    else:
        radius_m = 30.0

    request = {
        "locations": [location],
        "costing": "auto",
        "verbose": True,
        "radius": radius_m,
    }

    t0 = time.perf_counter()
    try:
        response = actor.locate(request)
    except Exception:
        return None, (time.perf_counter() - t0) * 1000.0
    elapsed_ms = (time.perf_counter() - t0) * 1000.0

    if not isinstance(response, list) or not response:
        return None, elapsed_ms
    edges = response[0].get("edges") or []
    if not edges:
        return None, elapsed_ms
    edge = edges[0]
    edge_info = edge.get("edge_info") or {}
    way_id = edge_info.get("way_id")
    if way_id is None:
        return None, elapsed_ms
    names = edge_info.get("names") or []
    return (
        FixPrediction(
            way_id=str(way_id),
            street_name=names[0] if names else None,
            matched_type="locate_fallback",
            distance_along_edge=edge.get("percent_along"),
            edge_index=None,
            window_start_index=index,
            window_end_index=index + 1,
            boundary_margin=0,
        ),
        elapsed_ms,
    )


def csv_escape(value: str) -> str:
    if any(char in value for char in [",", "\"", "\n"]):
        return "\"" + value.replace("\"", "\"\"") + "\""
    return value


def csv_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    return csv_escape(str(value))


def summarize_query_times(window_stats: list[TraceWindowStats]) -> dict[str, float]:
    successful = [item.query_time_ms for item in window_stats if item.error is None]
    if not successful:
        return {
            "windowP50Ms": 0.0,
            "windowP95Ms": 0.0,
            "windowMeanMs": 0.0,
            "totalTraceTimeMs": 0.0,
        }
    return {
        "windowP50Ms": percentile(successful, 0.5),
        "windowP95Ms": percentile(successful, 0.95),
        "windowMeanMs": sum(successful) / len(successful),
        "totalTraceTimeMs": sum(successful),
    }


def main() -> None:
    args = parse_args()
    log_paths = args.log_paths or default_log_paths(args.reference_artifact)
    log_paths = [path.resolve() for path in log_paths if path.is_file()]

    actor = Actor(args.config.resolve())
    entries_by_log: dict[str, list[dict[str, Any]]] = {}
    for log_path in log_paths:
        entries_by_log[log_path.name] = load_drive_match_log_entries(log_path)

    aggregate = ReplayMetrics()
    per_log: list[dict[str, Any]] = []
    fix_rows: list[dict[str, Any]] = []
    window_stats_all: list[TraceWindowStats] = []

    for log_path in log_paths:
        log_name = log_path.name
        entries = entries_by_log[log_name]
        predictions, window_stats = load_predictions_for_log(
            actor=actor,
            log_name=log_name,
            entries=entries,
            max_points=args.max_points,
            overlap=args.overlap,
            breakage_distance_m=args.breakage_distance_m,
            max_time_gap_s=args.max_time_gap_s,
            max_distance_gap_m=args.max_distance_gap_m,
        )
        window_stats_all.extend(window_stats)

        metrics = ReplayMetrics(
            replayed_fix_count=len(entries),
            predicted_fix_count=len(predictions),
            unmatched_fix_count=max(0, len(entries) - len(predictions)),
            trace_window_count=len(window_stats),
            failed_trace_window_count=sum(1 for item in window_stats if item.error is not None),
        )

        for index, entry in enumerate(entries):
            if index in predictions:
                continue
            fallback_prediction, elapsed_ms = locate_fallback_prediction(actor, entry, index)
            metrics.locate_fallback_time_ms += elapsed_ms
            if fallback_prediction is None:
                continue
            predictions[index] = fallback_prediction
            metrics.locate_fallback_count += 1

        metrics.predicted_fix_count = len(predictions)
        metrics.unmatched_fix_count = max(0, len(entries) - len(predictions))

        for index, entry in enumerate(entries):
            prediction = predictions.get(index)
            result = entry.get("result") or {}
            logged_way_id = str(result["wayID"]) if result.get("wayID") is not None else None
            pseudo_label_way_id = hindsight_pseudo_label_way_id(entries, index)
            pseudo_trace = candidate_trace(pseudo_label_way_id, result)
            predicted_way_id = prediction.way_id if prediction else None

            if logged_way_id is not None:
                metrics.logged_comparable_count += 1
                metrics.logged_agreement_count += int(predicted_way_id == logged_way_id and prediction is not None)

            if pseudo_label_way_id is not None:
                predicted_matches = predicted_way_id == pseudo_label_way_id and prediction is not None
                logged_correct = logged_way_id == pseudo_label_way_id
                is_changed_example = logged_way_id != pseudo_label_way_id
                metrics.pseudo_label_example_count += 1
                metrics.correct_pseudo_label_count += int(predicted_matches)
                if is_changed_example:
                    metrics.changed_example_count += 1
                    metrics.changed_correct_count += int(predicted_matches)
                else:
                    metrics.unchanged_example_count += 1
                    metrics.unchanged_correct_count += int(predicted_matches)
                if not logged_correct and predicted_matches:
                    metrics.recovered_examples += 1
                elif logged_correct and not predicted_matches:
                    metrics.regressed_examples += 1

            fix_rows.append(
                {
                    "logName": log_name,
                    "logIndex": index,
                    "fixID": entry["fixID"],
                    "timestampUTC": entry["timestampUTC"],
                    "lat": entry["lat"],
                    "lon": entry["lon"],
                    "speedKmh": entry.get("speedKmh"),
                    "horizontalAccM": entry.get("horizontalAccM"),
                    "courseDeg": entry.get("courseDeg"),
                    "gpsSignalBars": entry.get("gpsSignalBars"),
                    "status": entry.get("status"),
                    "loggedWayID": logged_way_id,
                    "loggedStreetName": result.get("streetName"),
                    "loggedStreetRef": result.get("streetRef"),
                    "loggedSimpleReason": logged_simple_reason(entry),
                    "pseudoLabelWayID": pseudo_label_way_id,
                    "pseudoLabelStreetName": pseudo_trace.get("streetName") if isinstance(pseudo_trace, dict) else None,
                    "pseudoLabelStreetRef": pseudo_trace.get("streetRef") if isinstance(pseudo_trace, dict) else None,
                    "loggedMatchesPseudoLabel": None if pseudo_label_way_id is None else logged_way_id == pseudo_label_way_id,
                    "loggedPseudoLabelCandidateRank": candidate_rank(pseudo_label_way_id, result),
                    "isChangedExample": None if pseudo_label_way_id is None else logged_way_id != pseudo_label_way_id,
                    "oracleWayID": predicted_way_id,
                    "oracleStreetName": prediction.street_name if prediction else None,
                    "oracleMatchedType": prediction.matched_type if prediction else None,
                    "oracleEdgeIndex": prediction.edge_index if prediction else None,
                    "oracleDistanceAlongEdge": prediction.distance_along_edge if prediction else None,
                    "oracleMatchesPseudoLabel": None if pseudo_label_way_id is None or prediction is None else predicted_way_id == pseudo_label_way_id,
                    "oracleAgreesWithLogged": None if prediction is None or logged_way_id is None else predicted_way_id == logged_way_id,
                    "oracleBoundaryMargin": prediction.boundary_margin if prediction else None,
                    "oracleWindowStartIndex": prediction.window_start_index if prediction else None,
                    "oracleWindowEndIndex": prediction.window_end_index if prediction else None,
                }
            )

        aggregate.replayed_fix_count += metrics.replayed_fix_count
        aggregate.predicted_fix_count += metrics.predicted_fix_count
        aggregate.unmatched_fix_count += metrics.unmatched_fix_count
        aggregate.pseudo_label_example_count += metrics.pseudo_label_example_count
        aggregate.correct_pseudo_label_count += metrics.correct_pseudo_label_count
        aggregate.changed_example_count += metrics.changed_example_count
        aggregate.changed_correct_count += metrics.changed_correct_count
        aggregate.unchanged_example_count += metrics.unchanged_example_count
        aggregate.unchanged_correct_count += metrics.unchanged_correct_count
        aggregate.logged_agreement_count += metrics.logged_agreement_count
        aggregate.logged_comparable_count += metrics.logged_comparable_count
        aggregate.recovered_examples += metrics.recovered_examples
        aggregate.regressed_examples += metrics.regressed_examples
        aggregate.trace_window_count += metrics.trace_window_count
        aggregate.failed_trace_window_count += metrics.failed_trace_window_count
        aggregate.locate_fallback_count += metrics.locate_fallback_count
        aggregate.locate_fallback_time_ms += metrics.locate_fallback_time_ms

        timing = summarize_query_times(window_stats)
        per_log.append(
            {
                "logName": log_name,
                "replayedFixCount": metrics.replayed_fix_count,
                "predictedFixCount": metrics.predicted_fix_count,
                "coverage": metrics.coverage,
                "pseudoLabelExampleCount": metrics.pseudo_label_example_count,
                "changedExampleCount": metrics.changed_example_count,
                "accuracy": metrics.accuracy,
                "changedRecall": metrics.changed_recall,
                "unchangedAccuracy": metrics.unchanged_accuracy,
                "loggedAgreement": metrics.logged_agreement,
                "recoveredExamples": metrics.recovered_examples,
                "regressedExamples": metrics.regressed_examples,
                "netCorrections": metrics.net_corrections,
                "traceWindowCount": metrics.trace_window_count,
                "failedTraceWindowCount": metrics.failed_trace_window_count,
                "locateFallbackCount": metrics.locate_fallback_count,
                "locateFallbackTimeMs": metrics.locate_fallback_time_ms,
                "totalOracleTimeMs": timing["totalTraceTimeMs"] + metrics.locate_fallback_time_ms,
                **timing,
            }
        )

    aggregate_timing = summarize_query_times(window_stats_all)
    summary = {
        "generatedAtUTC": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "repoRoot": str(REPO_ROOT),
        "configPath": str(args.config.resolve()),
        "logPaths": [str(path) for path in log_paths],
        "summary": {
            **asdict(aggregate),
            "accuracy": aggregate.accuracy,
            "changedRecall": aggregate.changed_recall,
            "unchangedAccuracy": aggregate.unchanged_accuracy,
            "loggedAgreement": aggregate.logged_agreement,
            "netCorrections": aggregate.net_corrections,
            "coverage": aggregate.coverage,
            "totalOracleTimeMs": aggregate_timing["totalTraceTimeMs"] + aggregate.locate_fallback_time_ms,
            **aggregate_timing,
        },
        "perLog": per_log,
        "traceWindows": [asdict(item) for item in window_stats_all],
        "fixRows": fix_rows,
    }

    ensure_parent_directory(args.output_json)
    args.output_json.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")

    ensure_parent_directory(args.output_csv)
    header = [
        "log_name",
        "log_index",
        "fix_id",
        "timestamp_utc",
        "lat",
        "lon",
        "speed_kmh",
        "horizontal_acc_m",
        "course_deg",
        "gps_signal_bars",
        "status",
        "logged_way_id",
        "logged_street_name",
        "logged_street_ref",
        "logged_simple_reason",
        "pseudo_label_way_id",
        "pseudo_label_street_name",
        "pseudo_label_street_ref",
        "logged_matches_pseudo_label",
        "logged_pseudo_label_candidate_rank",
        "is_changed_example",
        "oracle_way_id",
        "oracle_street_name",
        "oracle_matched_type",
        "oracle_edge_index",
        "oracle_distance_along_edge",
        "oracle_matches_pseudo_label",
        "oracle_agrees_with_logged",
        "oracle_boundary_margin",
        "oracle_window_start_index",
        "oracle_window_end_index",
    ]
    csv_lines = [",".join(header)]
    diff_lines = [",".join(header)]
    for row in fix_rows:
        columns = [
            csv_value(row["logName"]),
            csv_value(row["logIndex"]),
            csv_value(row["fixID"]),
            csv_value(row["timestampUTC"]),
            csv_value(row["lat"]),
            csv_value(row["lon"]),
            csv_value(row["speedKmh"]),
            csv_value(row["horizontalAccM"]),
            csv_value(row["courseDeg"]),
            csv_value(row["gpsSignalBars"]),
            csv_value(row["status"]),
            csv_value(row["loggedWayID"]),
            csv_value(row["loggedStreetName"]),
            csv_value(row["loggedStreetRef"]),
            csv_value(row["loggedSimpleReason"]),
            csv_value(row["pseudoLabelWayID"]),
            csv_value(row["pseudoLabelStreetName"]),
            csv_value(row["pseudoLabelStreetRef"]),
            csv_value(row["loggedMatchesPseudoLabel"]),
            csv_value(row["loggedPseudoLabelCandidateRank"]),
            csv_value(row["isChangedExample"]),
            csv_value(row["oracleWayID"]),
            csv_value(row["oracleStreetName"]),
            csv_value(row["oracleMatchedType"]),
            csv_value(row["oracleEdgeIndex"]),
            csv_value(row["oracleDistanceAlongEdge"]),
            csv_value(row["oracleMatchesPseudoLabel"]),
            csv_value(row["oracleAgreesWithLogged"]),
            csv_value(row["oracleBoundaryMargin"]),
            csv_value(row["oracleWindowStartIndex"]),
            csv_value(row["oracleWindowEndIndex"]),
        ]
        line = ",".join(columns)
        csv_lines.append(line)
        if row["oracleWayID"] != row["loggedWayID"]:
            diff_lines.append(line)

    args.output_csv.write_text("\n".join(csv_lines) + "\n")
    ensure_parent_directory(args.output_diff_csv)
    args.output_diff_csv.write_text("\n".join(diff_lines) + "\n")

    print(f"Wrote JSON: {args.output_json}")
    print(f"Wrote CSV: {args.output_csv}")
    print(f"Wrote diff CSV: {args.output_diff_csv}")


if __name__ == "__main__":
    main()
