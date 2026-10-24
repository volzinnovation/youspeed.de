#!/usr/bin/env python3
"""Read-only inventory of source maxspeed tags and their retention in a v3 DB.

Families describe implementation work, not executable rules or parser approval.
The full source is hashed while scanning; SQLite is opened in read-only mode.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3


DAY = r"(?:Mo|Tu|We|Th|Fr|Sa|Su)"
DAYS = rf"{DAY}(?:\s*-\s*{DAY})?(?:\s*,\s*{DAY}(?:\s*-\s*{DAY})?)*"
RANGE = r"\d{1,2}:\d{2}\s*-\s*\d{1,2}:\d{2}"
RANGES = rf"{RANGE}(?:\s*,\s*{RANGE})*"
SCHEDULE = re.compile(rf"(?:(?:{DAYS})\s+)?{RANGES}|{RANGES}\s+AND\s+{DAYS}")


def file_hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def balanced(value: str) -> bool:
    depth = 0
    for char in value:
        depth += (char == "(") - (char == ")")
        if depth < 0:
            return False
    return depth == 0


def describe(key: str, value: str) -> dict:
    """Conservative audit classification; never emits a runtime applicability."""
    flags = []
    if "wet" in value:
        flags.append("wet")
    if re.search(r"\bPH\b", value):
        flags.append("public_holidays")
    if re.search(r"\bSH\b", value):
        flags.append("school_holidays")
    if re.search(r"\b(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\b", value):
        flags.append("calendar_dates")
    if re.search(r"\d{1,2}:\d{2}", value):
        flags.append("clock")
    if re.search(r"\b(?:Mo|Tu|We|Th|Fr|Sa|Su)\b", value):
        flags.append("weekday")
    if re.search(r"\b(?:hgv|bicycle|agricultural|forestry|hazmat|destination|trailor)\b", value) or ":hgv:" in key:
        flags.append("vehicle_or_usage")
    if re.search(r"\b(?:weight|maxweight|maxweightrating)\b", value):
        flags.append("mass_property")
    if "lanes=" in value:
        flags.append("operating_lane_count")
    if value.strip().startswith("none"):
        flags.append("typed_unlimited_value")
    if ":reason:" in key:
        return {"family": "reason_metadata", "features": flags, "issues": []}
    if ":lanes:" in key:
        return {"family": "lane_condition", "features": flags, "issues": ["requires_lane_grammar_and_identity"]}
    issues = []
    if not balanced(value):
        issues.append("unbalanced_parentheses")
    if re.search(r"\bSo\b", value):
        issues.append("nonstandard_weekday_So")
    if re.search(r":\d{3,}", value):
        issues.append("invalid_minute_width")
    if value.count("@") != 1:
        issues.append("expected_one_value_condition_pair")
    limit, _, condition = value.partition("@")
    if not re.fullmatch(r"(?:[1-9]\d{0,2}(?:\s+(?:km/h|mph))?|none)", limit.strip()):
        issues.append("invalid_speed_value")
    if issues:
        return {"family": "malformed_or_nonstandard", "features": flags, "issues": issues}
    if "trailor" in condition:
        return {"family": "review_required", "features": flags, "issues": ["unknown_condition_trailor"]}
    if "operating_lane_count" in flags:
        return {"family": "dynamic_lane_count", "features": flags, "issues": []}
    if "vehicle_or_usage" in flags or "mass_property" in flags:
        return {"family": "vehicle_mass_or_usage", "features": flags, "issues": []}
    if "public_holidays" in flags or "school_holidays" in flags:
        return {"family": "holiday_schedule", "features": flags, "issues": []}
    if "calendar_dates" in flags:
        return {"family": "calendar_range", "features": flags, "issues": []}
    condition = condition.strip()
    if condition.startswith("(") and condition.endswith(")"):
        condition = condition[1:-1].strip()
    if condition == "wet":
        return {"family": "wet_surface", "features": flags, "issues": []}
    if SCHEDULE.fullmatch(condition):
        for start_h, start_m, end_h, end_m in re.findall(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})", condition):
            sh, sm, eh, em = map(int, (start_h, start_m, end_h, end_m))
            if sh > 23 or sm > 59 or eh > 24 or em > 59 or (eh == 24 and em != 0) or (sh, sm) == (eh, em):
                return {"family": "malformed_or_nonstandard", "features": flags, "issues": ["invalid_clock_range"]}
        return {"family": "simple_local_schedule", "features": flags, "issues": []}
    return {"family": "review_required", "features": flags, "issues": ["outside_audit_schedule_subset"]}


def audit(meta: Path, db: Path, manifest: Path, source_manifest: Path) -> dict:
    bundle = json.loads(manifest.read_text())
    source = json.loads(source_manifest.read_text())
    actual_db_hash = file_hash(db)
    if actual_db_hash != bundle["db"]["uncompressed_sha256"]:
        raise ValueError("DB hash does not match the selected bundle manifest")
    connection = sqlite3.connect(db.resolve().as_uri() + "?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    stored = {(int(w), k, v) for w, k, v in connection.execute(
        "SELECT d.way_id,j.key,j.value FROM traffic_sign_way_direction d,json_each(d.lane_tags_json) j "
        "WHERE j.key GLOB 'maxspeed*' AND j.key LIKE '%conditional%'"
    )}
    retained_keys = Counter()
    for k, count in connection.execute(
        "SELECT j.key,count(*) FROM traffic_sign_way_direction d,json_each(d.lane_tags_json) j "
        "WHERE j.key GLOB 'maxspeed*' GROUP BY j.key"
    ):
        retained_keys[k] = count
    groups = defaultdict(list)
    key_counts = Counter()
    value_counts = defaultdict(Counter)
    conditional = set()
    variable_ways, signals_ways, nonconditional_embedded = set(), set(), []
    missing_base = set()
    relevant = {}
    digest = hashlib.sha256()
    total = 0
    with meta.open("rb") as stream:
        for line in stream:
            digest.update(line)
            total += 1
            row = json.loads(line)
            tags = row.get("raw_tags") or {}
            speed = {k: v for k, v in tags.items() if k.startswith(("maxspeed", "source:maxspeed", "zone:maxspeed"))}
            way = int(row["way_id"])
            for key, value in speed.items():
                key_counts[key] += 1
                value_counts[key][value] += 1
                if key.startswith("maxspeed") and "conditional" in key:
                    conditional.add((way, key, value))
                    groups[(key, value)].append(way)
                    relevant[way] = {"way_id": way, "speed_tags": speed, "highway": row.get("highway"),
                                     "name": row.get("street_name"), "ref": row.get("ref"),
                                     "osm_url": f"https://www.openstreetmap.org/way/{way}"}
                    if key == "maxspeed:conditional" and not tags.get("maxspeed"):
                        missing_base.add(way)
                if key.startswith("maxspeed:variable"):
                    variable_ways.add(way)
                if key.startswith("maxspeed") and value == "signals":
                    signals_ways.add(way)
                if key.startswith("maxspeed") and "conditional" not in key and "@" in value:
                    nonconditional_embedded.append({"way_id": way, "key": key, "raw_value": value})
    expected_meta_hash = source["artifacts"]["ways_meta"]["sha256"]
    if digest.hexdigest() != expected_meta_hash:
        raise ValueError("ways.meta hash does not match source manifest")
    patterns, family_rows, family_ways = [], Counter(), defaultdict(set)
    for (key, value), ways in sorted(groups.items()):
        desc = describe(key, value)
        family_rows[desc["family"]] += len(ways)
        family_ways[desc["family"]].update(ways)
        patterns.append({"key": key, "raw_value": value, "way_tag_count": len(ways), **desc,
                         "example_ways": [relevant[w] for w in sorted(ways)[:3]]})
    feature_counts = {}
    for feature in sorted({flag for pattern in patterns for flag in pattern["features"]}):
        matching = {(way, key, value) for way, key, value in conditional if feature in describe(key, value)["features"]}
        feature_counts[feature] = {"way_tags": len(matching), "ways": len({r[0] for r in matching})}
    absent = sorted(conditional - stored)
    extra = sorted(stored - conditional)
    if absent or extra:
        raise ValueError(f"Conditional retention mismatch: {len(absent)} missing, {len(extra)} extra")
    restriction_rows = [r for r in conditional if ":reason:" not in r[1]]
    counts = {
        "source_way_rows": total,
        "db_way_rows": connection.execute("SELECT count(*) FROM ways").fetchone()[0],
        "conditional_maxspeed_namespace_way_tags": len(conditional),
        "conditional_maxspeed_namespace_ways": len({r[0] for r in conditional}),
        "restriction_way_tags_excluding_reason_metadata": len(restriction_rows),
        "unique_key_value_patterns": len(patterns),
        "unique_raw_values": len({r[2] for r in conditional}),
        "generic_conditional_ways_without_generic_base_maxspeed": len(missing_base),
        "ways_with_any_maxspeed_variable_prefix": len(variable_ways),
        "ways_with_any_maxspeed_value_signals": len(signals_ways),
        "nonconditional_speed_keys_containing_at": len(nonconditional_embedded),
    }
    if total != counts["db_way_rows"]:
        raise ValueError("Source and DB way row counts differ")
    return {
        "schema_version": 1,
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "Selected local BW v1.5 runtime bundle; car-drivable ways in ways.meta, not all PBF objects or current live OSM.",
        "classification_note": "Non-executing audit families identify required interpreter work, not runtime approval or evaluated truth. Family counts partition way-tag rows; feature and unique-way counts can overlap.",
        "sources": {"db": str(db), "db_sha256": actual_db_hash, "db_bytes": db.stat().st_size,
                    "bundle_manifest": str(manifest), "bundle_version": bundle["bundle_version"],
                    "ways_meta": str(meta), "ways_meta_sha256": digest.hexdigest(),
                    "source_manifest": str(source_manifest), "pbf_recorded_provenance": source["source"]},
        "hash_and_retention_checks": {"db_manifest_match": True, "meta_manifest_match": True,
                                      "exact_conditional_retention": True, "missing": absent, "extra": extra},
        "counts": counts,
        "source_key_counts": dict(sorted(key_counts.items())),
        "source_value_counts": {key: dict(sorted(values.items())) for key, values in sorted(value_counts.items())},
        "retained_maxspeed_keys_in_optional_direction_table": dict(sorted(retained_keys.items())),
        "family_counts": {key: {"way_tags": count, "ways": len(family_ways[key])} for key, count in sorted(family_rows.items())},
        "feature_counts": feature_counts,
        "inventory_rule_lane_scope_counts": dict(connection.execute("SELECT lane_scope,count(*) FROM traffic_sign_way_rule GROUP BY lane_scope")),
        "nonconditional_embedded_expressions": nonconditional_embedded,
        "patterns": patterns,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ways-meta", type=Path, required=True)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--bundle-manifest", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    args = parser.parse_args()
    result = audit(args.ways_meta, args.db, args.bundle_manifest, args.source_manifest)
    args.out_json.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({"counts": result["counts"], "families": result["family_counts"], "checks": result["hash_and_retention_checks"]}, indent=2))


if __name__ == "__main__":
    main()
