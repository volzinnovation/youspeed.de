#!/usr/bin/env python3
"""Copy a pinned bundle and restore only source-verified directional speed fields.

This local repair preserves the current bundle's roads, geometry, context and
metadata. It does not rebuild the region from an older source extract. Source
OSM must contain exactly the three audited ways and their original ordered nodes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import sqlite3
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path


APPROVED_WAY_IDS = {81302142, 1248904506, 1302655171}
COORDINATE_TOLERANCE_DEGREES = 1e-9
DIRECTIONAL_COLUMNS = ("maxspeed_forward", "maxspeed_backward")


def sha256(path: Path) -> str:
    result = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def quoted(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def source_ways(path: Path) -> dict[int, dict]:
    root = ET.parse(path).getroot()
    nodes = {}
    for node in root.findall("node"):
        node_id = int(node.attrib["id"])
        if node_id in nodes:
            raise ValueError(f"Duplicate source node {node_id}")
        coordinate = [float(node.attrib["lat"]), float(node.attrib["lon"])]
        if not all(math.isfinite(value) for value in coordinate) or not -90 <= coordinate[0] <= 90 or not -180 <= coordinate[1] <= 180:
            raise ValueError(f"Invalid source node {node_id}")
        nodes[node_id] = coordinate
    ways = {}
    for way in root.findall("way"):
        way_id = int(way.attrib["id"])
        if way_id in ways:
            raise ValueError(f"Duplicate source way {way_id}")
        tags = {tag.attrib["k"]: tag.attrib["v"] for tag in way.findall("tag")}
        if tags.get("maxspeed") not in (None, ""):
            raise ValueError(f"Source way {way_id} already has a generic speed limit")
        values = [tags.get("maxspeed:forward"), tags.get("maxspeed:backward")]
        if any(value is None or not value.isdigit() or not 1 <= int(value) <= 300 for value in values):
            raise ValueError(f"Source way {way_id} must have two explicit numeric directional limits")
        refs = [int(node.attrib["ref"]) for node in way.findall("nd")]
        if len(refs) < 2 or any(ref not in nodes for ref in refs):
            raise ValueError(f"Source way {way_id} has incomplete ordered geometry")
        version = int(way.attrib.get("version", "0"))
        if version <= 0:
            raise ValueError(f"Source way {way_id} must retain its OSM version")
        ways[way_id] = {"version": version, "timestamp": way.attrib.get("timestamp"), "tags": tags,
                        "node_ids": refs, "points": [nodes[ref] for ref in refs],
                        "maxspeed_forward": values[0], "maxspeed_backward": values[1]}
    if set(ways) != APPROVED_WAY_IDS:
        raise ValueError("Source must contain exactly the three audited OSM ways")
    return ways


def row_counts(connection: sqlite3.Connection) -> dict[str, int]:
    tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
    return {table: connection.execute(f"SELECT COUNT(*) FROM {quoted(table)}").fetchone()[0] for table in tables}


def repair(base: Path, source: Path, output: Path, expected_base_sha256: str | None = None) -> dict:
    base, source, output = base.resolve(), source.resolve(), output.resolve()
    report_file = output.with_suffix(".repair.json")
    if output == base or output.exists() or report_file.exists():
        raise ValueError("Choose a new output database and report path; the base is never overwritten")
    if any(Path(str(base) + suffix).exists() and Path(str(base) + suffix).stat().st_size > 0 for suffix in ("-wal", "-journal")):
        raise ValueError("Use an offline published database, not an app database with a live journal")
    base_digest = sha256(base)
    if expected_base_sha256 and base_digest != expected_base_sha256.lower():
        raise ValueError("Base database SHA-256 does not match the pinned published artifact")
    source_digest = sha256(source)
    ways = source_ways(source)
    connection = sqlite3.connect(base.as_uri() + "?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        if connection.execute("SELECT name FROM sqlite_master WHERE type='trigger' AND lower(tbl_name)='ways'").fetchone():
            raise ValueError("Ways triggers require a separate preservation review before repair")
        schema = {row[1]: row[2] for row in connection.execute("PRAGMA table_info(ways)")}
        if not {"way_id", "highway", "street_name", "ref", "maxspeed"}.issubset(schema):
            raise ValueError("Base database is missing required v3 way columns")
        for column in DIRECTIONAL_COLUMNS:
            if column in schema and schema[column].upper() != "TEXT":
                raise ValueError(f"Unsupported existing column type for {column}")
        original_rows = {}
        original_geometry = {}
        for way_id, observed in sorted(ways.items()):
            row = connection.execute("SELECT * FROM ways WHERE way_id=?", (way_id,)).fetchone()
            geometry = connection.execute("SELECT points_json FROM way_geom WHERE way_id=?", (way_id,)).fetchone()
            if row is None or geometry is None:
                raise ValueError(f"Unknown way or missing geometry in base database: {way_id}")
            if row["maxspeed"] not in (None, ""):
                raise ValueError(f"Base way {way_id} already has a generic speed limit")
            for field, tag in (("highway", "highway"), ("street_name", "name"), ("ref", "ref")):
                if row[field] != observed["tags"].get(tag):
                    raise ValueError(f"Base way {way_id} source identity differs: {field}")
            points = json.loads(geometry[0])
            if len(points) != len(observed["points"]) or any(
                not isinstance(actual, list) or len(actual) != 2 or any(
                    not isinstance(value, (int, float)) or not math.isfinite(value) or abs(value - expected) > COORDINATE_TOLERANCE_DEGREES
                    for value, expected in zip(actual, wanted))
                for actual, wanted in zip(points, observed["points"])
            ):
                raise ValueError(f"Ordered source geometry differs for way {way_id}; no orientation or shape is guessed")
            for column in DIRECTIONAL_COLUMNS:
                if column in schema and row[column] is not None and row[column] != observed[column]:
                    raise ValueError(f"Conflicting existing directional value on way {way_id}: {column}")
            original_rows[way_id] = dict(row)
            original_geometry[way_id] = geometry[0]
        counts_before = row_counts(connection)
    finally:
        connection.close()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(dir=output.parent, prefix=output.name + ".building-", suffix=".sqlite", delete=False) as stream:
        temporary = Path(stream.name)
    try:
        shutil.copyfile(base, temporary)
        if sha256(temporary) != base_digest:
            raise ValueError("Base database changed while making the offline copy")
        with sqlite3.connect(temporary) as repaired:
            repaired.row_factory = sqlite3.Row
            added_columns = [column for column in DIRECTIONAL_COLUMNS if column not in schema]
            for column in added_columns:
                repaired.execute(f"ALTER TABLE ways ADD COLUMN {column} TEXT")
            for way_id, observed in sorted(ways.items()):
                repaired.execute("UPDATE ways SET maxspeed_forward=?,maxspeed_backward=? WHERE way_id=?",
                                 (observed["maxspeed_forward"], observed["maxspeed_backward"], way_id))
            for way_id, original in original_rows.items():
                current = repaired.execute("SELECT * FROM ways WHERE way_id=?", (way_id,)).fetchone()
                if any(current[column] != value for column, value in original.items() if column not in DIRECTIONAL_COLUMNS):
                    raise ValueError(f"Unrelated original attributes changed on way {way_id}")
                if repaired.execute("SELECT points_json FROM way_geom WHERE way_id=?", (way_id,)).fetchone()[0] != original_geometry[way_id]:
                    raise ValueError(f"Geometry changed on way {way_id}")
            counts_after = row_counts(repaired)
            if counts_after != counts_before:
                raise ValueError("A base table row count changed during repair")
        if output.exists():
            raise ValueError("Output database appeared during repair; it will not be replaced")
        temporary.rename(output)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    report = {"format": "youspeed.directional-speed-source-repair.v1", "base_database": str(base),
              "base_sha256": base_digest, "source_osm": str(source), "source_sha256": source_digest,
              "output_database": str(output), "output_sha256": sha256(output),
              "added_columns": added_columns, "changed_way_ids": sorted(ways),
              "coordinate_tolerance_degrees": COORDINATE_TOLERANCE_DEGREES,
              "table_row_counts_before": counts_before, "table_row_counts_after": counts_after,
              "preservation": "Byte-identical offline base copy; only optional directional columns and the three audited ways' directional fields are written. Geometry, settlement, metadata and all other base fields remain unchanged.",
              "ways": [{"way_id": way_id, "source_version": observed["version"], "source_timestamp": observed["timestamp"],
                        "source_node_ids": observed["node_ids"], "maxspeed_forward": observed["maxspeed_forward"],
                        "maxspeed_backward": observed["maxspeed_backward"]} for way_id, observed in sorted(ways.items())]}
    report_file.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return report


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-db", type=Path, required=True)
    parser.add_argument("--source-osm", type=Path, required=True)
    parser.add_argument("--out-db", type=Path, required=True)
    parser.add_argument("--expected-base-sha256")
    args = parser.parse_args(argv)
    print(json.dumps(repair(args.base_db, args.source_osm, args.out_db, args.expected_base_sha256), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
