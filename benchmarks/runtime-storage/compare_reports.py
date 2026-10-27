#!/usr/bin/env python3
"""Validate all phone backends, including numeric cross-platform road parity."""
import argparse
import hashlib
import json
from pathlib import Path

BACKENDS = ("packed", "sqlite", "geodesk")
PLATFORMS = ("android", "iphone")
FLOAT_FIELDS = {"distance_m", "chainage_m", "lat", "lon"}


def load(path):
    return json.loads(path.read_text())


def require(condition, detail="Benchmark acceptance check failed"):
    if not condition:
        raise ValueError(detail)


def native_digest(path):
    """FNV over exact per-query JSON, as emitted and timed by the native kernel."""
    raw = path.read_text()
    decoder = json.JSONDecoder()
    position = 0
    while raw[position].isspace():
        position += 1
    require(raw[position] == "[")
    position += 1
    digest = 14695981039346656037
    while True:
        while raw[position].isspace():
            position += 1
        if raw[position] == "]":
            require(not raw[position + 1:].strip())
            return f"{digest:016x}"
        start = position
        _, position = decoder.raw_decode(raw, position)
        for byte in raw[start:position].encode("utf-8"):
            digest = ((digest ^ byte) * 1099511628211) & ((1 << 64) - 1)
        while raw[position].isspace():
            position += 1
        if raw[position] == ",":
            position += 1
        else:
            require(raw[position] == "]")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reports", type=Path)
    parser.add_argument("sizes", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--tolerance", type=float, default=1e-7)
    parser.add_argument("--platforms", nargs="+", choices=PLATFORMS, default=PLATFORMS)
    args = parser.parse_args()
    require(0 < args.tolerance <= 1e-7)
    summary = {"schema": 1, "numeric_tolerance": args.tolerance, "devices": {},
               "size_totals": load(args.sizes)["complete_candidate_totals"]}
    baseline = None
    largest_error = {field: 0.0 for field in FLOAT_FIELDS}
    checked_results = 0
    result_count = None
    summary["complete_requested_phones"] = set(args.platforms) == set(PLATFORMS)
    for platform in args.platforms:
        device = summary["devices"][platform] = {}
        digests = set()
        for backend in BACKENDS:
            report_path = args.reports / f"{platform}-{backend}-final.json"
            report = load(report_path)
            require(report["overall_success"] is True, str(report_path))
            if platform == "iphone":
                require(report.get("road_results_exported") is True)
            road = report["storage"] if platform == "android" else report
            nodes = report["generic_speed_nodes"]
            require(road["backend"] == nodes["backend"] == backend)
            require(road["ways"] == 1085790 and road["query_count"] == 586)
            require(road["repetitions"] == 3 and road["warm"]["count"] == 1758)
            require(nodes["nodes"] == 20141 and nodes["query_count"] == 20397)
            require(nodes["repetitions"] == 3 and nodes["warm"]["count"] == 61191)
            require(nodes["result_fnv1a64"] == "f16a6da37efa217d")
            require(report["correction_overlay_selftest"]["failed"] == 0)
            require(report["source_amendment_probe"]["failed"] == 0)
            require(report["source_amendment_probe"]["tests"] > 0)
            require(report["source_amendment_probe"]["source_record_fnv1a64"] == "e71e7bbba1cc2d29")
            disk = report["correction_persistence_selftest"]
            require(all(disk[key] is True for key in (
                "created_reopened", "amended_reopened", "tombstoned_reopened", "history_preserved")))
            digests.add(road["result_fnv1a64"])
            results_path = args.reports / f"{platform}-{backend}-roads.json"
            results = load(results_path)
            require(isinstance(results, list) and len(results) == 586)
            require(sum(map(len, results)) == 6446, "Road hit count differs from source verification")
            require(native_digest(results_path) == road["result_fnv1a64"], "Export differs from timed lookup digest")
            if baseline is None:
                baseline = results
                result_count = sum(map(len, results))
            for expected_rows, actual_rows in zip(baseline, results):
                require(len(expected_rows) == len(actual_rows))
                for expected, actual in zip(expected_rows, actual_rows):
                    require(actual.keys() == expected.keys())
                    for key, value in expected.items():
                        if key in FLOAT_FIELDS:
                            error = abs(actual[key] - value)
                            require(error <= args.tolerance, (platform, backend, key, value, actual[key]))
                            largest_error[key] = max(largest_error[key], error)
                        else:
                            require(actual[key] == value, (platform, backend, key))
                    checked_results += 1
            memory = road["memory_after"]
            before = road["memory_before"]
            device[backend] = {
                "road_warm": road["warm"], "node_warm": nodes["warm"],
                "road_init_ms": road["init_ms"], "road_memory_after": memory,
                "road_rss_delta_bytes": memory["rss_bytes"] - before["rss_bytes"],
                "road_anonymous_pss_delta_bytes": (
                    memory["pss_anonymous_bytes"] - before["pss_anonymous_bytes"]
                    if memory["pss_anonymous_bytes"] is not None else None),
                "road_footprint_delta_bytes": (
                    memory["physical_footprint_bytes"] - before["physical_footprint_bytes"]
                    if memory["physical_footprint_bytes"] is not None else None),
                "road_digest": road["result_fnv1a64"], "node_digest": nodes["result_fnv1a64"],
                "report_sha256": hashlib.sha256(report_path.read_bytes()).hexdigest(),
                "road_results_sha256": hashlib.sha256(results_path.read_bytes()).hexdigest(),
                "correction_tests": report["correction_overlay_selftest"]["tests"],
                "source_amendment_probe": report.get("source_amendment_probe"),
            }
        require(len(digests) == 1, f"Backend mismatch on {platform}")
    summary["parity"] = {"success": True, "queries_per_backend": 586,
                         "platforms_verified": list(args.platforms),
                         "cross_phone_parity_verified": set(args.platforms) == set(PLATFORMS),
                         "road_results_per_backend": result_count,
                         "checked_road_results": checked_results,
                         "max_numeric_error": largest_error,
                         "all_non_numeric_fields_exact": True,
                         "all_node_backend_digests_exact": True}
    args.output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n")
    print(json.dumps(summary["parity"], indent=2))


if __name__ == "__main__":
    main()
