#!/usr/bin/env python3
"""Settlement coverage restricted to roads without pre-existing speed evidence.

Reads original tags retained in ways.meta, then joins distinct eligible way IDs
to a read-only v3 database. This is a conservative no-tag cohort, not a claim
that every excluded tag yields a usable passenger-car speed limit.
"""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import sqlite3


SPEED_FAMILIES = ("maxspeed", "source:maxspeed", "zone:maxspeed", "max:speed")
INDEPENDENT_CLASSES = {"motorway", "motorway_link", "living_street"}
SPEED_SIGN = re.compile(r"^(?:274|278|282)(?=[^0-9]|$)")
WAY_GROUP_SQL = """
WITH per_way AS (
 SELECT f.way_id,
   sum(s.inside_city IS NULL) AS unknown_count,
   sum(s.inside_city=1) AS inside_count,
   sum(s.inside_city=0) AS outside_count,
   sum(s.confidence='low') AS low_count,
   count(*) AS segments
 FROM evidence_filter f JOIN settlement_segment s USING(way_id)
 WHERE f.eligible=1 GROUP BY f.way_id
), classified AS (
 SELECT CASE
  WHEN unknown_count=segments THEN 'unknown_everywhere'
  WHEN unknown_count>0 THEN 'partly_unknown'
  WHEN inside_count>0 AND outside_count>0 THEN 'inside_and_outside'
  WHEN inside_count>0 AND low_count>0 THEN 'inside_with_low_confidence'
  WHEN inside_count>0 THEN 'inside_high'
  ELSE 'outside_high' END AS category
 FROM per_way
)
SELECT category,count(*) AS ways FROM classified GROUP BY category ORDER BY category
"""
SEGMENT_SQL = """
SELECT s.inside_city,s.confidence,s.source,count(*) AS segments
FROM settlement_segment s JOIN evidence_filter f USING(way_id)
WHERE f.eligible=1
GROUP BY s.inside_city,s.confidence,s.source
ORDER BY s.inside_city,s.confidence,s.source
"""


def speed_sign_evidence(raw):
    if raw.strip().lower() == "maxspeed":
        return True
    jurisdiction = None
    for token in re.split(r"[;,|\s]+", raw):
        prefix = re.match(r"^([A-Za-z]{2}):(.*)$", token)
        if prefix:
            jurisdiction, token = prefix[1].upper(), prefix[2]
        if jurisdiction == "DE" and SPEED_SIGN.match(token):
            return True
    return False


def evidence_reasons(tags):
    reasons = set()
    for key, value in tags.items():
        if value is None or not str(value).strip():
            continue
        if any(key == family or key.startswith(family + ":") for family in SPEED_FAMILIES):
            reasons.add("speed_tag:" + key)
        if key == "zone:traffic" or key.startswith("zone:traffic:"):
            reasons.add("traffic_context_tag:" + key)
        if (key == "traffic_sign" or key.startswith("traffic_sign:")) and speed_sign_evidence(str(value)):
            reasons.add("speed_sign_tag:" + key)
    return reasons


def sha256_file(path):
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1048576), b""):
            h.update(chunk)
    return h.hexdigest()


def audit(database, ways_meta):
    conn = sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA temp_store=MEMORY")
    conn.execute("CREATE TEMP TABLE evidence_filter(way_id INTEGER PRIMARY KEY,eligible INTEGER NOT NULL)")
    reasons, highway_exclusions, no_tag_highway_counts, excluded_tag_values = Counter(), Counter(), Counter(), Counter()
    excluded_evidence = no_evidence = no_tag_class_exclusions = total = 0
    batch = []
    meta_hash = hashlib.sha256()
    with ways_meta.open("rb") as handle:
        for line in handle:
            meta_hash.update(line)
            row = json.loads(line)
            tags = row.get("raw_tags")
            if not isinstance(tags, dict):
                raise ValueError("Complete raw_tags required; legacy summary fields cannot establish absence of evidence")
            found = evidence_reasons(tags)
            highway = str(tags.get("highway") or "").strip().lower()
            independent_class = highway in INDEPENDENT_CLASSES
            eligible = not found and not independent_class
            total += 1
            if found:
                excluded_evidence += 1
                reasons.update(found)
                for reason in found:
                    key = reason.split(":", 1)[1]
                    excluded_tag_values[(key, str(tags[key]))] += 1
            else:
                no_evidence += 1
                no_tag_highway_counts[highway] += 1
                if independent_class:
                    no_tag_class_exclusions += 1
                    highway_exclusions[highway] += 1
            batch.append((int(row["way_id"]), int(eligible)))
            if len(batch) >= 10000:
                conn.executemany("INSERT INTO evidence_filter VALUES(?,?)", batch)
                batch.clear()
    conn.executemany("INSERT INTO evidence_filter VALUES(?,?)", batch)
    scalar = lambda sql: conn.execute(sql).fetchone()[0]
    checks = {
        "database_ways": scalar("SELECT count(*) FROM ways"),
        "raw_tag_ways": total,
        "raw_ways_missing_in_bundle": scalar("SELECT count(*) FROM evidence_filter f LEFT JOIN ways w USING(way_id) WHERE w.way_id IS NULL"),
        "bundle_ways_missing_raw_tags": scalar("SELECT count(*) FROM ways w LEFT JOIN evidence_filter f USING(way_id) WHERE f.way_id IS NULL"),
        "eligible_ways_without_segments": scalar("SELECT count(*) FROM evidence_filter f WHERE eligible=1 AND NOT EXISTS(SELECT 1 FROM settlement_segment s WHERE s.way_id=f.way_id)"),
    }
    assert checks["database_ways"] == total
    assert all(checks[k] == 0 for k in ("raw_ways_missing_in_bundle", "bundle_ways_missing_raw_tags", "eligible_ways_without_segments"))
    grouped = [dict(row) for row in conn.execute(SEGMENT_SQL)]
    for row in grouped:
        row["inside_city"] = None if row["inside_city"] is None else bool(row["inside_city"])
    way_groups = dict(conn.execute(WAY_GROUP_SQL))
    eligible_ways = scalar("SELECT count(*) FROM evidence_filter WHERE eligible=1")
    assert sum(way_groups.values()) == eligible_ways
    result = {
        "executed_at_utc": datetime.now(timezone.utc).isoformat(),
        "database": str(database.resolve()), "database_sha256": sha256_file(database),
        "ways_meta": str(ways_meta.resolve()), "ways_meta_sha256": meta_hash.hexdigest(),
        "definition": "Whole OSM ways with no nonempty speed-family, traffic-context, or recognized speed-sign tag in either direction, excluding motorway/motorway_link/living_street independent class rules. New settlement decisions are the outcome, not an exclusion.",
        "caveats": [
            "Conservative tag-absence filter: provenance-only, advisory, vehicle-specific, variable or malformed speed values still exclude the road; tagged is not synonymous with usable passenger-car speed.",
            "A speed tag for one direction excludes the complete OSM way.",
            "Town-limit signs and polygon-based settlement evidence remain in the evaluated outcome to avoid circular filtering.",
            "OSM ways are map pieces, not unique street names. Segment records may split ways and directions; percentages by records are not distance-weighted.",
            "This evaluates the September 13 source snapshot and generated coverage, not surveyed driving accuracy or live camera evidence.",
        ],
        "checks": checks,
        "filter_counts": {
            "all_ways": total, "excluded_recorded_speed_evidence": excluded_evidence,
            "ways_without_recorded_speed_tags": no_evidence,
            "excluded_independent_class_after_tag_filter": no_tag_class_exclusions,
            "eligible_ways": eligible_ways,
        },
        "excluded_evidence_reasons_overlapping": dict(sorted(reasons.items())),
        "excluded_independent_classes": dict(sorted(highway_exclusions.items())),
        "eligible_highways": {k: v for k, v in sorted(no_tag_highway_counts.items()) if k not in INDEPENDENT_CLASSES},
        "excluded_tag_values": [{"key": k, "value": v, "ways": n} for (k, v), n in sorted(excluded_tag_values.items())],
        "segments": sum(row["segments"] for row in grouped),
        "segment_results": grouped, "way_results": way_groups,
        "sql": {"segment_results": SEGMENT_SQL.strip(), "way_results": WAY_GROUP_SQL.strip()},
    }
    conn.close()
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("ways_meta", type=Path)
    args = parser.parse_args()
    print(json.dumps(audit(args.database, args.ways_meta), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
