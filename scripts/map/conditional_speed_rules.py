#!/usr/bin/env python3
"""Versioned, conservative OSM speed-rule compiler. No build-time clock decisions.

Unsupported syntax is retained and blocks only its applicable scope. The native
clients evaluate the same declarative AST; bundles cannot provide executable code.
"""
from __future__ import annotations

import argparse
import calendar
import hashlib
import json
import re
import sqlite3
from pathlib import Path

VERSION = 1
GRAMMAR = "youspeed-osm-speed-1"
DAYS = {v: i + 1 for i, v in enumerate(("Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"))}
MONTHS = {v: i for i, v in enumerate(calendar.month_abbr) if v}
MODES = {"vehicle": 1, "motor_vehicle": 2, "motorcar": 3, "hgv": 3, "bus": 3,
         "motorcycle": 3, "hazmat": 4, "bicycle": 3, "agricultural": 3,
         "emergency": 3, "taxi": 3, "psv": 3, "foot": 3, "train": 3, "tilting": 3}


def canonical(value):
    return json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def split_outer(text, separator=";"):
    """Split only outside parentheses/quotes; reject damaged assemblies."""
    parts, start, depth, quote = [], 0, 0, False
    for i, char in enumerate(text):
        if char == '"':
            quote = not quote
        if quote:
            continue
        if char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                raise ValueError("unbalanced_parenthesis")
        if depth == 0 and text.startswith(separator, i):
            parts.append(text[start:i].strip())
            start = i + len(separator)
    if depth or quote:
        raise ValueError("unbalanced_parenthesis_or_quote")
    parts.append(text[start:].strip())
    if any(not p for p in parts):
        raise ValueError("empty_clause")
    return parts


def limit(raw):
    raw = raw.strip()
    if raw == "none":
        return {"kind": "unlimited"}
    match = re.fullmatch(r"(\d+(?:\.\d+)?)\s*(km/h|kmh|kph|mph)?", raw)
    if not match:
        raise ValueError("unsupported_limit")
    kmh = float(match[1]) * (1.609344 if match[2] == "mph" else 1)
    if not 0 < kmh <= 400:
        raise ValueError("invalid_limit")
    return {"kind": "numeric", "kmh": kmh}


def _clock(raw):
    hour, minute = map(int, raw.split(":"))
    if hour > 24 or minute > 59 or (hour == 24 and minute):
        raise ValueError("invalid_clock")
    return hour * 60 + minute


def condition(raw, depth=0):
    if depth > 12 or len(raw) > 4096:
        raise ValueError("condition_limit")
    raw = raw.strip()
    if not raw:
        raise ValueError("empty_condition")
    if re.search(r"\d:\d{3}", raw):
        raise ValueError("invalid_clock")
    # Remove an enclosing pair only when it spans the whole expression.
    if raw.startswith("(") and raw.endswith(")"):
        level = 0
        enclosing = True
        for i, char in enumerate(raw):
            level += (char == "(") - (char == ")")
            if level == 0 and i < len(raw) - 1:
                enclosing = False
        if enclosing:
            return condition(raw[1:-1], depth + 1)
    for separator, kind in ((" OR ", "any"), (" AND ", "all")):
        parts = split_outer(raw, separator)
        if len(parts) > 1:
            items = [condition(p, depth + 1) for p in parts]
            if kind == "all":
                clocks = []
                for item in items:
                    if item.get("kind") == "schedule" and item.get("windows"):
                        clocks.append({minute for minute in range(1440) if any(
                            start <= minute < end if start < end else minute >= start or minute < end
                            for start, end in item["windows"])})
                if clocks and not set.intersection(*clocks):
                    raise ValueError("contradictory_clock_windows_review_required")
            return {"kind": kind, "items": items}
    if raw in ("wet", "snow", "ice"):
        return {"kind": "context", "field": "road_surface_" + raw}
    if raw == "24/7":
        return {"kind": "true"}
    # Opening-hours off rules are ordered exclusions, not a union with holidays.
    parts = split_outer(raw)
    if len(parts) > 1:
        items = [condition(parts[0], depth + 1)]
        for part in parts[1:]:
            if not part.endswith(" off"):
                raise ValueError("unsupported_calendar_sequence")
            items.append({"kind": "not", "item": condition(part[:-4], depth + 1)})
        return {"kind": "all", "items": items}
    schedule = {"kind": "schedule", "weekdays": [], "holidays": [], "windows": []}
    text = raw
    month_pattern = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
    dates = re.match(rf"^({month_pattern})(?:\s+(\d{{1,2}}))?\s*-\s*({month_pattern})(?:\s+(\d{{1,2}}))?(?:\s+|$)", text)
    if dates:
        start_month, end_month = MONTHS[dates[1]], MONTHS[dates[3]]
        start_day = int(dates[2] or 1)
        end_day = int(dates[4] or calendar.monthrange(2000, end_month)[1])
        if start_day > calendar.monthrange(2000, start_month)[1] or not 1 <= start_day or not 1 <= end_day <= calendar.monthrange(2000, end_month)[1]:
            raise ValueError("invalid_annual_date")
        schedule["annual_start"] = start_month * 100 + start_day
        schedule["annual_end"] = end_month * 100 + end_day
        text = text[dates.end():].strip()
    days = re.match(r"^((?:(?:Mo|Tu|We|Th|Fr|Sa|Su)(?:-(?:Mo|Tu|We|Th|Fr|Sa|Su))?|PH|SH)(?:,(?:(?:Mo|Tu|We|Th|Fr|Sa|Su)(?:-(?:Mo|Tu|We|Th|Fr|Sa|Su))?|PH|SH))*)(?:\s+|$)", text)
    if days:
        for part in days[1].split(","):
            if part in ("PH", "SH"):
                schedule["holidays"].append(part)
            elif "-" in part:
                a, b = (DAYS[p] for p in part.split("-"))
                schedule["weekdays"].extend(i for i in range(1, 8) if (a <= i <= b if a <= b else i >= a or i <= b))
            else:
                schedule["weekdays"].append(DAYS[part])
        text = text[days.end():].strip()
    if text:
        for part in text.split(","):
            match = re.fullmatch(r"(\d{1,2}:\d{2})\s*-\s*(\d{1,2}:\d{2})", part.strip())
            if not match:
                raise ValueError("unsupported_condition")
            start, end = _clock(match[1]), _clock(match[2])
            if start == 1440 or start == end:
                raise ValueError("invalid_clock_window")
            schedule["windows"].append([start, end])
    if not days and not dates and not schedule["windows"]:
        raise ValueError("unsupported_condition")
    return schedule


def key_scope(key):
    # Descriptive/recommended-speed namespaces cannot create or mask a legal
    # maximum, including when their role follows a direction/profile suffix.
    metadata = {"reason", "type", "source", "note", "check_date", "signed", "advisory", "advised", "practical"}
    if key.startswith("source:") or metadata.intersection(key.split(":")[1:]):
        return {"role": "metadata"}
    if not key.startswith("maxspeed"):
        return {"role": "metadata"}
    parts = key.split(":")[1:]
    if parts and parts[0] == "variable":
        return {"role": "variable"}
    result = {"role": "speed", "vehicle": "all", "direction": 0, "lane": False, "conditional": False}
    expected = 0
    for part in parts:
        if part in MODES and expected <= 0:
            result["vehicle"], expected = part, 1
        elif part in ("forward", "backward") and expected <= 1:
            result["direction"], expected = (1 if part == "forward" else -1), 2
        elif part == "lanes" and expected <= 2:
            result["lane"], expected = True, 3
        elif part == "conditional" and expected <= 3:
            result["conditional"], expected = True, 4
        else:
            result["invalid_scope"] = True
    result["priority"] = MODES.get(result["vehicle"], 0) * 10 + (1 if result["direction"] else 0)
    return result


def compile_tags(tags):
    rows = []
    for key, raw in sorted(tags.items()):
        if not (key.startswith("maxspeed") or key.startswith("source:maxspeed")):
            continue
        row = {"key": key, "raw": str(raw), **key_scope(key), "status": "supported", "clauses": []}
        try:
            if row["role"] == "speed":
                if row.get("invalid_scope") or row["lane"]:
                    raise ValueError("unsupported_scope")
                if row["conditional"]:
                    source_cursor = 0
                    for i, clause in enumerate(split_outer(str(raw))):
                        pairs = split_outer(clause, "@")
                        if len(pairs) != 2:
                            raise ValueError("invalid_conditional_pair")
                        start = str(raw).find(clause, source_cursor)
                        source_cursor = start + len(clause)
                        row["clauses"].append({"index": i, "limit": limit(pairs[0]), "condition": condition(pairs[1]), "source_span": [start, source_cursor]})
                else:
                    row["clauses"] = [{"index": 0, "limit": limit(str(raw)), "condition": {"kind": "true"}, "source_span": [0, len(str(raw))]}]
        except ValueError as error:
            issue = str(error)
            row["status"] = "review_required" if issue.endswith("review_required") else "malformed" if issue.startswith(("invalid_", "unbalanced_", "empty_")) else "unsupported"
            row["issue"] = issue
        rows.append(row)
    return {"version": VERSION, "grammar": GRAMMAR, "tags": rows}


SCHEMA = """
CREATE TABLE IF NOT EXISTS road_speed_capability(version INTEGER NOT NULL, grammar TEXT NOT NULL, compiler_sha256 TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS road_speed_source_tag(way_id INTEGER NOT NULL,key TEXT NOT NULL,raw_value TEXT NOT NULL,source_snapshot TEXT,PRIMARY KEY(way_id,key));
CREATE TABLE IF NOT EXISTS road_speed_rule_set(way_id INTEGER PRIMARY KEY,rules_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS road_speed_rule(rule_id TEXT PRIMARY KEY,way_id INTEGER NOT NULL,source_key TEXT NOT NULL,clause_index INTEGER NOT NULL,priority INTEGER NOT NULL,limit_json TEXT NOT NULL,condition_id TEXT NOT NULL,source_start INTEGER NOT NULL,source_end INTEGER NOT NULL);
CREATE INDEX IF NOT EXISTS road_speed_rule_way ON road_speed_rule(way_id,priority,clause_index);
CREATE TABLE IF NOT EXISTS road_speed_condition(condition_id TEXT PRIMARY KEY,ast_json TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS road_speed_interpretation(way_id INTEGER NOT NULL,source_key TEXT NOT NULL,status TEXT NOT NULL,issue TEXT,PRIMARY KEY(way_id,source_key));
"""


def build(db, ways_meta, source_snapshot=""):
    # Caller owns transaction. No implicit commit: malformed input rolls back.
    for statement in SCHEMA.split(";"):
        if statement.strip():
            db.execute(statement)
    for table in ("road_speed_capability", "road_speed_source_tag", "road_speed_rule_set", "road_speed_rule", "road_speed_condition", "road_speed_interpretation"):
        db.execute("DELETE FROM " + table)
    compiler_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    db.execute("INSERT INTO road_speed_capability VALUES(?,?,?)", (VERSION, GRAMMAR, compiler_hash))
    counts = {"ways": 0, "tags": 0, "unsupported": 0, "rules": 0}
    with Path(ways_meta).open() as source:
        for line in source:
            if not line.strip():
                continue
            way = json.loads(line)
            tags = way.get("raw_tags", way.get("tags", {}))
            # Static-only rules already use the scalar native path. Keep exact
            # source tags for every road, compile all non-scalar speed scopes.
            relevant = {k: str(v) for k, v in tags.items() if k.startswith(("maxspeed", "source:maxspeed"))}
            if not relevant:
                continue
            way_id = int(way.get("way_id", way.get("id")))
            for key, raw in relevant.items():
                db.execute("INSERT INTO road_speed_source_tag VALUES(?,?,?,?)", (way_id, key, raw, source_snapshot))
            electronic_or_embedded = any(k in ("maxspeed", "maxspeed:forward", "maxspeed:backward") and
                (v.strip().lower() in ("signals", "variable", "dynamic") or "@" in v) for k, v in relevant.items())
            if not electronic_or_embedded and not any(k not in ("maxspeed", "maxspeed:forward", "maxspeed:backward", "source:maxspeed", "maxspeed:type", "maxspeed:reason") for k in relevant):
                continue
            compiled = compile_tags(relevant)
            db.execute("INSERT INTO road_speed_rule_set VALUES(?,?)", (way_id, canonical(compiled)))
            counts["ways"] += 1
            for tag in compiled["tags"]:
                counts["tags"] += 1
                counts["unsupported"] += tag["status"] != "supported"
                db.execute("INSERT INTO road_speed_interpretation VALUES(?,?,?,?)", (way_id, tag["key"], tag["status"], tag.get("issue")))
                for clause in tag["clauses"]:
                    condition_json = canonical(clause["condition"])
                    cid = hashlib.sha256(condition_json.encode()).hexdigest()
                    rid = hashlib.sha256(f"{way_id}:{tag['key']}:{clause['index']}".encode()).hexdigest()
                    db.execute("INSERT OR IGNORE INTO road_speed_condition VALUES(?,?)", (cid, condition_json))
                    db.execute("INSERT INTO road_speed_rule VALUES(?,?,?,?,?,?,?,?,?)", (rid, way_id, tag["key"], clause["index"], tag.get("priority", 0), canonical(clause["limit"]), cid, *clause["source_span"]))
                    counts["rules"] += 1
    return counts


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--ways-meta", type=Path, required=True)
    parser.add_argument("--source-snapshot", default="")
    args = parser.parse_args()
    with sqlite3.connect(args.db) as db:
        print(canonical(build(db, args.ways_meta, args.source_snapshot)))


if __name__ == "__main__":
    main()
