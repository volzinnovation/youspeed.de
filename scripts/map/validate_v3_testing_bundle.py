#!/usr/bin/env python3
"""Read-only structural readiness check for current iPhone/Android v3 bundles.

This deliberately checks more than the apps' minimum install contract. Passing
does not establish map freshness, legal correctness, or measured driving accuracy.
Only stdlib is required; no SQLite extension is loaded and no database is changed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import time


BOUNDS = "min_lon min_lat max_lon max_lat"
TABLES = {
    "metadata": "key value",
    "ways": "way_id highway street_name ref maxspeed maxspeed_type source_maxspeed approx_heading_deg service tunnel " + BOUNDS,
    "ways_rtree": "way_id " + BOUNDS,
    "way_geom": "way_id points_json",
    "way_endpoints": "way_id ref_norm highway tunnel_flag start_node_key start_lon start_lat end_node_key end_lon end_lat way_length_m",
    "way_links": "way_id linked_way_id shared_ref shared_node_key",
    "way_continuity_group": "continuity_group_id continuity_kind source_relation_id ref_norm street_name_norm member_count",
    "way_continuity_membership": "way_id continuity_group_id continuity_kind",
    "motorway_exit_approach": "way_id endpoint_side exit_way_id path_distance_m branch_heading_deg",
    "areas": "row_id area_id geometry_type name place boundary admin_level residential points_json " + BOUNDS,
    "areas_rtree": "row_id " + BOUNDS,
    "city_boundary": "row_id osm_type osm_id admin_level name " + BOUNDS,
    "city_boundary_rtree": "row_id " + BOUNDS,
    "city_ring": "boundary_row_id ring_index outer_index is_hole points_json",
    "city_tile": "boundary_row_id tile_x tile_y",
    "city_place": "row_id place name lon lat",
    "city_place_rtree": "row_id " + BOUNDS,
}
for _kind in ("surface", "tunnel", "motorway"):
    TABLES[f"{_kind}_way_network"] = "way_id"
    TABLES[f"{_kind}_way_network_rtree"] = "way_id " + BOUNDS

CORRIDORS = {
    "corridor_progress": "corridor_kind corridor_id side_node_key way_id start_depth_m end_depth_m start_depth_nodes end_depth_nodes corridor_span_m corridor_span_nodes",
    "corridor_pairs": "corridor_kind corridor_id side_node_key paired_kind paired_corridor_id",
}
SETTLEMENT = {
    "settlement_segment": "segment_id way_id segment_index direction inside_city source confidence evidence_json points_json",
    "settlement_area": "area_id osm_type osm_id kind inside_city source confidence tags_json " + BOUNDS,
    "settlement_ring": "area_id ring_index outer_index is_hole points_json",
    "settlement_sign": "sign_id osm_type osm_id sign_code inside_city direction way_id lon lat association tags_json",
}
# Every country configured in the bundled country target list.
COUNTRIES = {"CHE": "CH", "DEU": "DE", "FRA": "FR", "BEL": "BE", "NLD": "NL",
             "ROU": "RO", "LUX": "LU", "SWE": "SE", "LIE": "LI", "ISL": "IS", "MCO": "MC"}


def identifier(value):
    return '"' + value.replace('"', '""') + '"'


def country(value):
    value = str(value or "").strip().upper()
    return COUNTRIES.get(value, value)


class Audit:
    def __init__(self, connection, report):
        self.db = connection
        self.report = report
        self.tables = dict(connection.execute("SELECT name,sql FROM sqlite_master WHERE type='table'"))
        self.columns = {}
        self.complete = set()
        self.indexes = {}

    def issue(self, code, message, *, warning=False):
        self.report["warnings" if warning else "errors"].append({"code": code, "message": message})

    def schemas(self, requirements, *, required=True):
        for table, fields in requirements.items():
            if table not in self.tables:
                if required:
                    self.issue("missing_table", f"Missing table: {table}")
                continue
            info = list(self.db.execute(f"PRAGMA table_info({identifier(table)})"))
            self.columns[table] = {row[1] for row in info}
            missing = sorted(set(fields.split()) - self.columns[table])
            if missing:
                self.issue("missing_columns", f"{table}: missing {', '.join(missing)}")
            else:
                self.complete.add(table)
            # A rowid INTEGER PRIMARY KEY also provides an indexed lookup.
            keys = tuple(row[1] for row in sorted(info, key=lambda row: row[5]) if row[5])
            indexes = [keys] if keys else []
            for row in self.db.execute(f"PRAGMA index_list({identifier(table)})"):
                if row[4]:  # Partial indexes cannot serve all runtime queries.
                    continue
                indexes.append(tuple(entry[2] for entry in self.db.execute(f"PRAGMA index_info({identifier(row[1])})")))
            self.indexes[table] = indexes
            if table.endswith("_rtree"):
                if not re.search(r"\bUSING\s+rtree\s*\(", self.tables[table] or "", re.I):
                    self.issue("not_rtree", f"{table} is not a SQLite R-tree")
                else:
                    self.indexes[table].append((info[0][1],))

    def indexed(self, table, field):
        return any(index and index[0] == field for index in self.indexes.get(table, []))

    def require_index(self, table, field):
        if table in self.complete and not self.indexed(table, field):
            self.issue("missing_lookup_index", f"{table} needs an index beginning with {field}")

    def query(self, code, sql, message, requires):
        if not set(requires).issubset(self.complete):
            return
        try:
            if self.db.execute(sql).fetchone() is not None:
                self.issue(code, message)
        except sqlite3.Error as exc:
            self.issue("query_failed", f"{code}: {exc}")

    def references(self, child, field, parent="ways", parent_field="way_id", *, nullable=False):
        if not nullable:
            self.query("null_reference", f"SELECT 1 FROM {identifier(child)} WHERE {identifier(field)} IS NULL LIMIT 1",
                       f"{child}.{field} must not be NULL", (child,))
        # Skip potentially quadratic joins in an already-invalid schema.
        if not self.indexed(parent, parent_field):
            return
        self.query("orphan_reference", f"SELECT 1 FROM {identifier(child)} c LEFT JOIN {identifier(parent)} p "
                   f"ON p.{identifier(parent_field)}=c.{identifier(field)} WHERE c.{identifier(field)} IS NOT NULL "
                   f"AND p.{identifier(parent_field)} IS NULL LIMIT 1",
                   f"{child}.{field} references an absent {parent}.{parent_field}", (child, parent))

    def coverage(self, child, field="way_id"):
        if not self.indexed(child, field):
            return
        self.query("incomplete_way_coverage", f"SELECT 1 FROM ways w WHERE NOT EXISTS "
                   f"(SELECT 1 FROM {identifier(child)} c WHERE c.{identifier(field)}=w.way_id) LIMIT 1",
                   f"Some ways have no {child} row", ("ways", child))

    def rtree_bounds(self, rtree, source, key, *, point=False):
        if not self.indexed(source, key):
            return
        fields = ("lon", "lat", "lon", "lat") if point else BOUNDS.split()
        # R-tree coordinates are outward-rounded float32 values. Containment,
        # rather than equality or an arbitrary epsilon, accepts that rounding.
        terms = [f"typeof(s.{field}) NOT IN ('integer','real')" for field in fields]
        terms += [f"r.{bound}{op}s.{field}" for bound, op, field in
                  zip(BOUNDS.split(), (">", ">", "<", "<"), fields)]
        self.query("rtree_bounds_mismatch", f"SELECT 1 FROM {identifier(rtree)} r JOIN {identifier(source)} s "
                   f"ON r.{identifier(key)}=s.{identifier(key)} WHERE {' OR '.join(terms)} LIMIT 1",
                   f"{rtree} bounds must contain the corresponding {source} bounds", (rtree, source))

    def geometry(self, table, key, *, lon_lat=False, nullable=False, settlement=False):
        if table not in self.complete:
            return
        extras = ",inside_city,source,confidence,evidence_json" if settlement else ""
        stats = {"checked": 0, "invalid": 0, "unknown_empty": 0, "nullable_missing": 0}
        examples = []
        limits = (180, 90) if lon_lat else (90, 180)
        # Stream one JSON value at a time; do not materialize country geometry.
        for row in self.db.execute(f"SELECT {identifier(key)},points_json{extras} FROM {identifier(table)}"):
            stats["checked"] += 1
            valid = False
            try:
                if row[1] is None and nullable:
                    stats["nullable_missing"] += 1
                    continue
                points = json.loads(row[1])
                empty_unknown = False
                if settlement and points == [] and row[2:5] == (None, "missing", "unknown"):
                    evidence = json.loads(row[5])
                    empty_unknown = isinstance(evidence, list) and any(
                        isinstance(item, dict) and item.get("reason") == "usable_source_geometry_missing" for item in evidence)
                valid = isinstance(points, list) and (len(points) >= (1 if lon_lat else 2) or empty_unknown)
                if valid:
                    valid = all(isinstance(pair, list) and len(pair) == 2 and all(
                        type(value) in (int, float) and -limit <= value <= limit
                        for value, limit in zip(pair, limits)) for pair in points)
                if valid and empty_unknown:
                    stats["unknown_empty"] += 1
            except (ValueError, TypeError, OverflowError, RecursionError):
                pass
            if not valid:
                stats["invalid"] += 1
                if len(examples) < 5:
                    examples.append(str(row[0]))
        self.report.setdefault("geometry_checks", {})[table] = stats
        if stats["invalid"]:
            self.issue("invalid_geometry", f"{table}: {stats['invalid']} invalid coordinate arrays; example {key}: {', '.join(examples)}")


def validate_bundle(db_path, manifest_path=None, require_settlement=False):
    started = time.monotonic()
    path = Path(db_path).resolve()
    report = {"format": "youspeed.v3.testing-readiness", "db": str(path), "ready": False,
              "require_settlement": require_settlement, "errors": [], "warnings": [],
              "counts": {}, "metadata": {}, "scope": "Structural readiness only; not driving accuracy or source-data freshness."}
    if not path.is_file():
        report["errors"].append({"code": "database_missing", "message": f"Database not found: {path}"})
        return report
    try:
        # mode=ro avoids creating/modifying database files. query_only also blocks writes.
        with sqlite3.connect(path.as_uri() + "?mode=ro", uri=True) as db:
            db.execute("PRAGMA query_only=ON")
            audit = Audit(db, report)
            audit.schemas(TABLES)
            if "metadata" in audit.complete:
                report["metadata"] = dict(db.execute("SELECT key,value FROM metadata"))
            meta = report["metadata"]
            if meta.get("schema_version") not in ("1", "2"):
                audit.issue("database_schema_version", f"Unsupported or missing database schema_version: {meta.get('schema_version')!r}")
            for key, expected in (("way_links_mode", "shared_endpoint_detailed"),
                                  ("way_endpoints_mode", "coord_key_length_v1"),
                                  ("way_network_mode", "surface_tunnel_motorway_split_v1"),
                                  ("road_geometry_policy", "source_vertices_v1"),
                                  ("road_geometry_max_error_m", "0"),
                                  ("motorway_exit_approach_version", "1")):
                if meta.get(key) != expected:
                    audit.issue("capability_metadata", f"{key}: expected {expected!r}, found {meta.get(key)!r}")
            if "route_relation_connected" not in str(meta.get("way_continuity_mode", "")).split("+"):
                audit.issue("route_continuity_unavailable", "way_continuity_mode does not advertise route_relation_connected")
            corridor_mode = meta.get("corridor_progress_mode")
            if corridor_mode not in ("none", "paired_portal_chain_v1"):
                audit.issue("corridor_mode", f"Unknown or missing corridor_progress_mode: {corridor_mode!r}")
            audit.schemas(CORRIDORS, required=corridor_mode != "none")
            version = meta.get("settlement_context_version")
            has_settlement = any(table in audit.tables for table in SETTLEMENT)
            if version is None:
                if require_settlement or has_settlement:
                    audit.issue("settlement_capability_missing", "settlement_context_version=1 is required but not advertised")
                else:
                    audit.issue("settlement_legacy", "No settlement capability; clients use legacy settlement fallbacks", warning=True)
            elif version != "1":
                audit.issue("settlement_version", f"Unsupported settlement_context_version: {version!r}")
            if require_settlement or version is not None or has_settlement:
                audit.schemas(SETTLEMENT)
            integrity = [row[0] for row in db.execute("PRAGMA quick_check")]
            report["quick_check"] = integrity
            if integrity != ["ok"]:
                audit.issue("integrity", "PRAGMA quick_check did not return a single ok result")
            for table in sorted(audit.complete - {"metadata"}):
                report["counts"][table] = db.execute(f"SELECT COUNT(*) FROM {identifier(table)}").fetchone()[0]
            counts = report["counts"]
            if counts.get("ways") == 0:
                audit.issue("empty_ways", "The bundle contains no ways")
            if "ways" in counts and str(meta.get("road_geometry_source_way_count")) != str(counts["ways"]):
                audit.issue("source_geometry_coverage", "road_geometry_source_way_count must cover every admitted way")
            if corridor_mode == "none":
                for table in CORRIDORS:
                    if counts.get(table, 0):
                        audit.issue("corridor_mode_mismatch", f"{table} is populated although corridor_progress_mode=none")
            for table, field in (("ways", "way_id"), ("way_geom", "way_id"), ("way_endpoints", "way_id"),
                                 ("way_links", "way_id"), ("way_continuity_group", "continuity_group_id"),
                                 ("way_continuity_membership", "way_id"), ("corridor_progress", "way_id"),
                                 ("motorway_exit_approach", "way_id"), ("settlement_segment", "way_id"),
                                 ("settlement_area", "area_id"), ("areas", "row_id"), ("city_boundary", "row_id"),
                                 ("city_ring", "boundary_row_id"), ("city_tile", "boundary_row_id"), ("city_place", "row_id")):
                audit.require_index(table, field)
            for table in ("ways_rtree", "way_geom", "way_endpoints"):
                audit.references(table, "way_id")
                audit.coverage(table)
                if "ways" in counts and table in counts and counts[table] != counts["ways"]:
                    audit.issue("way_count_mismatch", f"{table} count {counts[table]} differs from ways count {counts['ways']}")
            audit.rtree_bounds("ways_rtree", "ways", "way_id")
            for table in ("areas", "city_boundary", "city_place"):
                audit.references(table + "_rtree", "row_id", table, "row_id")
                audit.references(table, "row_id", table + "_rtree", "row_id")
                audit.rtree_bounds(table + "_rtree", table, "row_id", point=table == "city_place")
            for table in ("city_ring", "city_tile"):
                audit.references(table, "boundary_row_id", "city_boundary", "row_id")
            for kind in ("surface", "tunnel", "motorway"):
                table = f"{kind}_way_network"
                rtree = table + "_rtree"
                audit.require_index(table, "way_id")
                audit.references(table, "way_id")
                audit.references(rtree, "way_id", table)
                audit.references(table, "way_id", rtree)
                audit.rtree_bounds(rtree, "ways", "way_id")
            networks = [f"{kind}_way_network" for kind in ("surface", "tunnel", "motorway")]
            if all(audit.indexed(table, "way_id") for table in networks):
                terms = [f"EXISTS(SELECT 1 FROM {table} n WHERE n.way_id=w.way_id)" for table in networks]
                audit.query("network_partition", f"SELECT 1 FROM ways w WHERE ({' + '.join(terms)}) != 1 LIMIT 1",
                            "Each way must belong to exactly one surface/tunnel/motorway network", ("ways", *networks))
            audit.query("invalid_bounds", "SELECT 1 FROM ways WHERE min_lon IS NULL OR min_lat IS NULL OR max_lon IS NULL OR max_lat IS NULL OR min_lon>max_lon OR min_lat>max_lat OR min_lon < -180 OR max_lon > 180 OR min_lat < -90 OR max_lat > 90 LIMIT 1",
                        "ways contains invalid geographic bounds", ("ways",))
            audit.query("invalid_endpoints", "SELECT 1 FROM way_endpoints WHERE start_node_key IS NULL OR start_node_key='' OR end_node_key IS NULL OR end_node_key='' OR way_length_m IS NULL OR way_length_m<0 LIMIT 1",
                        "way_endpoints contains missing endpoint keys or invalid lengths", ("way_endpoints",))
            for table, fields in (("way_links", ("way_id", "linked_way_id")),
                                  ("way_continuity_membership", ("way_id",)),
                                  ("corridor_progress", ("way_id",)),
                                  ("motorway_exit_approach", ("way_id", "exit_way_id")),
                                  ("settlement_segment", ("way_id",)), ("settlement_sign", ("way_id",))):
                for field in fields:
                    audit.references(table, field, nullable=table == "settlement_sign")
            audit.references("way_continuity_membership", "continuity_group_id", "way_continuity_group", "continuity_group_id")
            audit.references("settlement_ring", "area_id", "settlement_area", "area_id")
            for table, fields in (("way_continuity_group", ("continuity_group_id",)),
                                  ("corridor_progress", ("corridor_id",)),
                                  ("corridor_pairs", ("corridor_id", "paired_corridor_id")),
                                  ("settlement_segment", ("segment_id",)), ("settlement_area", ("area_id",)),
                                  ("settlement_sign", ("sign_id",))):
                for field in fields:
                    audit.query("null_id", f"SELECT 1 FROM {identifier(table)} WHERE {identifier(field)} IS NULL LIMIT 1",
                                f"{table}.{field} must not be NULL", (table,))
            audit.query("invalid_links", "SELECT 1 FROM way_links WHERE way_id=linked_way_id OR shared_ref IS NULL OR shared_ref NOT IN (0,1) OR shared_node_key IS NULL OR shared_node_key='' LIMIT 1",
                        "Detailed way_links contains invalid edges/evidence", ("way_links",))
            audit.query("invalid_exits", "SELECT 1 FROM motorway_exit_approach WHERE endpoint_side IS NULL OR endpoint_side NOT IN ('start','end') OR path_distance_m IS NULL OR path_distance_m<0 OR path_distance_m>350 OR branch_heading_deg IS NULL OR branch_heading_deg<0 OR branch_heading_deg>=360 LIMIT 1",
                        "motorway_exit_approach contains invalid side, distance, or heading", ("motorway_exit_approach",))
            audit.query("exit_road_classes", "SELECT 1 FROM motorway_exit_approach e JOIN ways w ON w.way_id=e.way_id JOIN ways x ON x.way_id=e.exit_way_id WHERE w.highway IS NULL OR w.highway!='motorway' OR x.highway IS NULL OR x.highway!='motorway_link' LIMIT 1",
                        "Exit approaches must connect motorway ways to motorway_link ways", ("motorway_exit_approach", "ways"))
            audit.query("continuity_kind_mismatch", "SELECT 1 FROM way_continuity_membership m JOIN way_continuity_group g USING(continuity_group_id) WHERE m.continuity_kind IS NULL OR m.continuity_kind!=g.continuity_kind LIMIT 1",
                        "Continuity membership kind differs from its group", ("way_continuity_membership", "way_continuity_group"))
            if "settlement_segment" in audit.complete:
                audit.coverage("settlement_segment")
                audit.query("invalid_settlement_evidence", """SELECT 1 FROM settlement_segment WHERE direction IS NULL OR direction NOT IN (-1,0,1)
                    OR (inside_city IS NOT NULL AND (typeof(inside_city)!='integer' OR inside_city NOT IN (0,1)))
                    OR source IS NULL OR source NOT IN ('zone_traffic','maxspeed_type','source_maxspeed','traffic_sign','urban_polygon','landuse','conflict','missing')
                    OR confidence IS NULL OR confidence NOT IN ('high','low','unknown')
                    OR (inside_city IS NULL AND confidence!='unknown') OR (inside_city IS NOT NULL AND confidence='unknown') LIMIT 1""",
                            "Settlement evidence would fail Android activation validation", ("settlement_segment",))
                report["settlement_evidence_counts"] = [dict(zip(("source", "confidence", "inside_city", "count"), row))
                    for row in db.execute("SELECT source,confidence,inside_city,COUNT(*) FROM settlement_segment GROUP BY source,confidence,inside_city")]
            audit.geometry("way_geom", "way_id")
            audit.geometry("settlement_segment", "segment_id", settlement=True)
            audit.geometry("areas", "row_id", lon_lat=True, nullable=True)
            audit.geometry("city_ring", "boundary_row_id", lon_lat=True)
            audit.geometry("settlement_ring", "area_id", lon_lat=True)
            metadata_counts = {"way_links_count": "way_links", "way_continuity_group_count": "way_continuity_group",
                               "way_continuity_membership_count": "way_continuity_membership", "corridor_progress_count": "corridor_progress",
                               "corridor_pair_count": "corridor_pairs", "motorway_exit_approach_count": "motorway_exit_approach",
                               "settlement_segment_count": "settlement_segment"}
            metadata_counts.update({f"{kind}_way_network_count": f"{kind}_way_network" for kind in ("surface", "tunnel", "motorway")})
            for key, table in metadata_counts.items():
                if key in meta and (table in counts or table in CORRIDORS and corridor_mode == "none"):
                    if str(counts.get(table, 0)) != str(meta[key]):
                        audit.issue("metadata_count_mismatch", f"{key}={meta[key]!r}, actual {table} count={counts.get(table, 0)}")
            if manifest_path:
                _validate_manifest(audit, path, Path(manifest_path))
            if country(meta.get("country_code")) and country(meta.get("settlement_country_code")) and country(meta["country_code"]) != country(meta["settlement_country_code"]):
                audit.issue("country_mismatch", "DB country_code differs from settlement_country_code")
    except (sqlite3.Error, OSError) as exc:
        report["errors"].append({"code": "database_read_failed", "message": str(exc)})
    report["ready"] = not report["errors"]
    report["elapsed_seconds"] = round(time.monotonic() - started, 3)
    return report


def _validate_manifest(audit, db_path, manifest_path):
    try:
        manifest = json.loads(manifest_path.read_text())
        if not isinstance(manifest, dict):
            raise ValueError("Manifest must be an object")
    except (OSError, ValueError) as exc:
        audit.issue("manifest_read_failed", str(exc))
        return
    audit.report["manifest"] = {"path": str(manifest_path.resolve()), **{key: manifest.get(key) for key in
                                ("region", "country_code", "bundle_version", "created_at_utc", "min_app_version")}}
    for key, expected in (("format", "youspeed.v3.bundle.manifest"), ("variant", "v3"), ("schema_version", 1)):
        if manifest.get(key) != expected:
            audit.issue("manifest_contract", f"Manifest {key}: expected {expected!r}, found {manifest.get(key)!r}")
    for key in ("region", "bundle_version", "created_at_utc", "min_app_version"):
        if not isinstance(manifest.get(key), str) or not manifest[key].strip():
            audit.issue("manifest_contract", f"Manifest {key} must be a nonempty string")
    manifest_country = country(manifest.get("country_code"))
    if not manifest_country:
        audit.issue("country_identity", "Manifest lacks country_code; explicit country identity is required for field testing")
    for key in ("country_code", "settlement_country_code"):
        db_country = country(audit.report["metadata"].get(key))
        if manifest_country and db_country and manifest_country != db_country:
            audit.issue("country_mismatch", f"Manifest country differs from DB {key}")
    # Standard manifests currently expose settlement via min_app_version + DB
    # metadata, not a mandatory capability field. Check optional declarations too.
    for key in ("settlement_context_version", "motorway_exit_approach_version"):
        if key in manifest and str(manifest[key]) != str(audit.report["metadata"].get(key)):
            audit.issue("manifest_capability_mismatch", f"Manifest and database disagree on {key}")
    if audit.report["metadata"].get("settlement_context_version") == "1":
        minimum = str(manifest.get("min_app_version", ""))
        match = re.fullmatch(r"(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?", minimum)
        core = tuple(int(value or 0) for value in match.groups()[:3]) if match else ()
        if not match or core < (1, 1, 0) or core == (1, 1, 0) and match.group(4):
            audit.issue("settlement_min_app_version", "Settlement-v1 bundle must declare min_app_version >= 1.1")
    artifact = manifest.get("db")
    if not isinstance(artifact, dict):
        audit.issue("manifest_database", "Manifest db must be an artifact object")
        return
    if not isinstance(artifact.get("file"), str) or not artifact["file"].strip():
        audit.issue("manifest_database_file", "Manifest db.file must be a nonempty string")
    if type(artifact.get("bytes")) is not int or artifact["bytes"] <= 0:
        audit.issue("manifest_artifact_size", "Manifest db.bytes must be a positive integer")
    if not isinstance(artifact.get("sha256"), str) or not re.fullmatch(r"[a-fA-F0-9]{64}", artifact["sha256"]):
        audit.issue("manifest_artifact_hash", "Manifest db.sha256 must be a 64-character hexadecimal digest")
    compression = str(artifact.get("compression") or "").lower()
    if compression not in ("", "none", "gzip"):
        audit.issue("manifest_compression", f"Unsupported DB compression: {compression}")
    prefix = "uncompressed_" if compression == "gzip" else ""
    expected_bytes, expected_sha = artifact.get(prefix + "bytes"), artifact.get(prefix + "sha256")
    if type(expected_bytes) is not int or expected_bytes <= 0:
        audit.issue("manifest_database_size", f"Invalid or missing db.{prefix}bytes")
    elif db_path.stat().st_size != expected_bytes:
        audit.issue("manifest_database_size", f"Materialized database size {db_path.stat().st_size} differs from manifest {expected_bytes}")
    if not isinstance(expected_sha, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", expected_sha):
        audit.issue("manifest_database_hash", f"Invalid or missing db.{prefix}sha256")
    else:
        digest = hashlib.sha256()
        with db_path.open("rb") as source:
            for chunk in iter(lambda: source.read(4 * 1024 * 1024), b""):
                digest.update(chunk)
        audit.report["sha256"] = digest.hexdigest()
        if digest.hexdigest() != expected_sha.lower():
            audit.issue("manifest_database_hash", "Materialized database SHA256 differs from manifest")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", required=True, type=Path)
    parser.add_argument("--manifest", type=Path, help="Also validate materialized bytes and manifest capability/country declarations")
    parser.add_argument("--require-settlement", action="store_true")
    parser.add_argument("--out-json", type=Path)
    args = parser.parse_args(argv)
    report = validate_bundle(args.db, args.manifest, args.require_settlement)
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    if args.out_json:
        if args.out_json.resolve() in {args.db.resolve(), args.manifest.resolve() if args.manifest else None}:
            parser.error("--out-json must not overwrite the database or manifest")
        args.out_json.parent.mkdir(parents=True, exist_ok=True)
        args.out_json.write_text(payload)
    print(payload, end="")
    return 0 if report["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
