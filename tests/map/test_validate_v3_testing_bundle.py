"""Regression checks for the read-only, cross-client field-testing gate."""

import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/map"))
from validate_v3_testing_bundle import validate_bundle


SCHEMA = """
CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
CREATE TABLE ways(way_id INTEGER PRIMARY KEY,highway TEXT,street_name TEXT,ref TEXT,maxspeed TEXT,maxspeed_type TEXT,source_maxspeed TEXT,approx_heading_deg REAL,service TEXT,tunnel TEXT,min_lon REAL,min_lat REAL,max_lon REAL,max_lat REAL);
CREATE VIRTUAL TABLE ways_rtree USING rtree(way_id,min_lon,max_lon,min_lat,max_lat);
CREATE TABLE way_geom(way_id INTEGER PRIMARY KEY,points_json TEXT);
CREATE TABLE way_endpoints(way_id INTEGER PRIMARY KEY,ref_norm TEXT,highway TEXT,tunnel_flag INTEGER,start_node_key TEXT,start_lon REAL,start_lat REAL,end_node_key TEXT,end_lon REAL,end_lat REAL,way_length_m REAL);
CREATE TABLE way_links(way_id INTEGER,linked_way_id INTEGER,shared_ref INTEGER,shared_node_key TEXT,PRIMARY KEY(way_id,linked_way_id,shared_node_key));
CREATE TABLE way_continuity_group(continuity_group_id INTEGER PRIMARY KEY,continuity_kind TEXT,source_relation_id INTEGER,ref_norm TEXT,street_name_norm TEXT,member_count INTEGER);
CREATE TABLE way_continuity_membership(way_id INTEGER,continuity_group_id INTEGER,continuity_kind TEXT,PRIMARY KEY(way_id,continuity_group_id));
CREATE TABLE motorway_exit_approach(way_id INTEGER,endpoint_side TEXT,exit_way_id INTEGER,path_distance_m REAL,branch_heading_deg REAL,PRIMARY KEY(way_id,endpoint_side,exit_way_id));
CREATE TABLE areas(row_id INTEGER PRIMARY KEY,area_id TEXT,geometry_type TEXT,name TEXT,place TEXT,boundary TEXT,admin_level TEXT,residential TEXT,points_json TEXT,min_lon REAL,min_lat REAL,max_lon REAL,max_lat REAL);
CREATE VIRTUAL TABLE areas_rtree USING rtree(row_id,min_lon,max_lon,min_lat,max_lat);
CREATE TABLE city_boundary(row_id INTEGER PRIMARY KEY,osm_type TEXT,osm_id INTEGER,admin_level INTEGER,name TEXT,min_lon REAL,min_lat REAL,max_lon REAL,max_lat REAL);
CREATE VIRTUAL TABLE city_boundary_rtree USING rtree(row_id,min_lon,max_lon,min_lat,max_lat);
CREATE TABLE city_ring(boundary_row_id INTEGER,ring_index INTEGER,outer_index INTEGER,is_hole INTEGER,points_json TEXT);
CREATE INDEX city_ring_boundary ON city_ring(boundary_row_id);
CREATE TABLE city_tile(boundary_row_id INTEGER,tile_x INTEGER,tile_y INTEGER);
CREATE INDEX city_tile_boundary ON city_tile(boundary_row_id);
CREATE TABLE city_place(row_id INTEGER PRIMARY KEY,place TEXT,name TEXT,lon REAL,lat REAL);
CREATE VIRTUAL TABLE city_place_rtree USING rtree(row_id,min_lon,max_lon,min_lat,max_lat);
CREATE TABLE settlement_segment(segment_id INTEGER PRIMARY KEY,way_id INTEGER,segment_index INTEGER,direction INTEGER,inside_city INTEGER,source TEXT,confidence TEXT,evidence_json TEXT,points_json TEXT);
CREATE INDEX settlement_way ON settlement_segment(way_id);
CREATE TABLE settlement_area(area_id TEXT PRIMARY KEY,osm_type TEXT,osm_id INTEGER,kind TEXT,inside_city INTEGER,source TEXT,confidence TEXT,tags_json TEXT,min_lon REAL,min_lat REAL,max_lon REAL,max_lat REAL);
CREATE TABLE settlement_ring(area_id TEXT,ring_index INTEGER,outer_index INTEGER,is_hole INTEGER,points_json TEXT,PRIMARY KEY(area_id,ring_index));
CREATE TABLE settlement_sign(sign_id TEXT PRIMARY KEY,osm_type TEXT,osm_id INTEGER,sign_code TEXT,inside_city INTEGER,direction INTEGER,way_id INTEGER,lon REAL,lat REAL,association TEXT,tags_json TEXT);
"""


class TestingBundleTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.path = self.root / "CHE.sqlite"
        self.manifest = self.root / "bundle-manifest.v3.json"
        with sqlite3.connect(self.path) as db:
            db.executescript(SCHEMA)
            for kind in ("surface", "tunnel", "motorway"):
                db.execute(f"CREATE TABLE {kind}_way_network(way_id INTEGER PRIMARY KEY)")
                db.execute(f"CREATE VIRTUAL TABLE {kind}_way_network_rtree USING rtree(way_id,min_lon,max_lon,min_lat,max_lat)")
            metadata = {"schema_version": "1", "country_code": "CH", "way_links_mode": "shared_endpoint_detailed",
                        "way_endpoints_mode": "coord_key_length_v1", "way_network_mode": "surface_tunnel_motorway_split_v1",
                        "road_geometry_policy": "source_vertices_v1", "road_geometry_max_error_m": "0", "road_geometry_source_way_count": "3",
                        "way_continuity_mode": "route_relation_connected+same_street_name_connected",
                        "corridor_progress_mode": "none", "corridor_progress_count": "0", "corridor_pair_count": "0",
                        "motorway_exit_approach_version": "1", "motorway_exit_approach_count": "1",
                        "settlement_context_version": "1", "settlement_country_code": "CH", "settlement_segment_count": "3"}
            db.executemany("INSERT INTO metadata VALUES(?,?)", metadata.items())
            for way_id, highway, network in ((1, "primary", "surface"), (2, "motorway", "motorway"), (3, "motorway_link", "surface")):
                db.execute("INSERT INTO ways VALUES(?,?,NULL,NULL,'80',NULL,NULL,90,NULL,NULL,8,47,8.001,47)", (way_id, highway))
                db.execute("INSERT INTO ways_rtree VALUES(?,8,8.001,47,47)", (way_id,))
                db.execute("INSERT INTO way_geom VALUES(?,'[[47,8],[47,8.001]]')", (way_id,))
                db.execute("INSERT INTO way_endpoints VALUES(?,'',?,0,'a',8,47,'b',8.001,47,100)", (way_id, highway))
                db.execute(f"INSERT INTO {network}_way_network VALUES(?)", (way_id,))
                db.execute(f"INSERT INTO {network}_way_network_rtree VALUES(?,8,8.001,47,47)", (way_id,))
                db.execute("INSERT INTO settlement_segment VALUES(?,?,0,0,NULL,'missing','unknown','[]','[[47,8],[47,8.001]]')", (way_id * 1048576 + 1, way_id))
            db.executescript("""
                INSERT INTO way_links VALUES(2,3,0,'b'),(3,2,0,'b');
                INSERT INTO way_continuity_group VALUES(1,'route_relation_connected',99,'A1','',1);
                INSERT INTO way_continuity_membership VALUES(2,1,'route_relation_connected');
                INSERT INTO motorway_exit_approach VALUES(2,'end',3,0,90);
            """)
        self.write_manifest()

    def write_manifest(self, **overrides):
        contents = self.path.read_bytes()
        payload = {"format": "youspeed.v3.bundle.manifest", "schema_version": 1, "variant": "v3",
                   "region": "switzerland", "country_code": "CHE", "bundle_version": "test",
                   "created_at_utc": "2026-09-27T00:00:00Z", "min_app_version": "1.1",
                   "db": {"file": "CHE.sqlite", "bytes": len(contents), "sha256": hashlib.sha256(contents).hexdigest()}}
        payload.update(overrides)
        self.manifest.write_text(json.dumps(payload))
        return payload

    def change(self, sql):
        with sqlite3.connect(self.path) as db:
            db.executescript(sql)

    def codes(self, report):
        return {issue["code"] for issue in report["errors"]}

    def test_ready_bundle_with_no_corridors_and_unknown_settlement_stays_unchanged(self):
        before = self.path.read_bytes()
        report = validate_bundle(self.path, self.manifest, require_settlement=True)
        self.assertTrue(report["ready"], report["errors"])
        self.assertEqual(report["counts"]["ways"], 3)
        self.assertEqual(report["settlement_evidence_counts"], [{"source": "missing", "confidence": "unknown", "inside_city": None, "count": 3}])
        self.assertEqual(self.path.read_bytes(), before)
        self.assertFalse(Path(str(self.path) + "-journal").exists())

    def test_reports_all_missing_structures_together(self):
        empty = self.root / "empty.sqlite"
        sqlite3.connect(empty).close()
        report = validate_bundle(empty, require_settlement=True)
        missing = {item["message"].split(": ")[-1] for item in report["errors"] if item["code"] == "missing_table"}
        self.assertTrue({"ways", "way_links", "motorway_exit_approach", "settlement_segment", "settlement_sign"}.issubset(missing))
        self.assertIn("settlement_capability_missing", self.codes(report))

    def test_settlement_is_optional_but_partial_or_unadvertised_capability_is_not(self):
        self.change("DELETE FROM metadata WHERE key LIKE 'settlement_%';")
        self.assertIn("settlement_capability_missing", self.codes(validate_bundle(self.path)))
        self.change("DROP TABLE settlement_segment; DROP TABLE settlement_area; DROP TABLE settlement_ring; DROP TABLE settlement_sign;")
        report = validate_bundle(self.path)
        self.assertTrue(report["ready"], report["errors"])
        self.assertIn("settlement_legacy", {issue["code"] for issue in report["warnings"]})
        self.assertFalse(validate_bundle(self.path, require_settlement=True)["ready"])

    def test_old_corridor_schema_fails_even_when_corridor_mode_is_none(self):
        self.change("CREATE TABLE corridor_progress(corridor_kind TEXT,corridor_id INTEGER,side_node_key TEXT,way_id INTEGER,start_depth_m REAL,end_depth_m REAL,corridor_span_m REAL);")
        report = validate_bundle(self.path)
        missing = next(issue for issue in report["errors"] if issue["code"] == "missing_columns")
        self.assertIn("start_depth_nodes", missing["message"])
        self.assertIn("corridor_span_nodes", missing["message"])

    def test_legacy_geometry_cannot_pass_current_testing_readiness(self):
        self.change("DELETE FROM metadata WHERE key LIKE 'road_geometry_%';")
        report = validate_bundle(self.path)
        self.assertIn("source_geometry_coverage", self.codes(report))
        self.assertTrue(any("road_geometry_policy" in issue["message"] for issue in report["errors"]))

    def test_corrupt_references_partition_and_evidence_are_all_reported(self):
        self.change("""
            DELETE FROM way_geom WHERE way_id=1;
            INSERT INTO tunnel_way_network VALUES(1);
            UPDATE motorway_exit_approach SET exit_way_id=999,endpoint_side='sideways';
            UPDATE settlement_segment SET inside_city=2,confidence='high' WHERE way_id=1;
            DELETE FROM settlement_segment WHERE way_id=3;
        """)
        codes = self.codes(validate_bundle(self.path, require_settlement=True))
        self.assertTrue({"incomplete_way_coverage", "way_count_mismatch", "network_partition", "orphan_reference",
                         "invalid_exits", "invalid_settlement_evidence", "metadata_count_mismatch"}.issubset(codes), codes)

    def test_partial_lookup_index_does_not_satisfy_runtime_contract(self):
        self.change("DROP INDEX settlement_way; CREATE INDEX partial_way ON settlement_segment(way_id) WHERE confidence='high';")
        self.assertIn("missing_lookup_index", self.codes(validate_bundle(self.path)))

    def test_gzip_manifest_uses_materialized_digest_and_minimum_version(self):
        original = self.write_manifest()
        self.write_manifest(db={"file": "CHE.sqlite", "compression": "gzip", "bytes": 100,
                                "sha256": "0" * 64, "uncompressed_bytes": original["db"]["bytes"],
                                "uncompressed_sha256": original["db"]["sha256"]})
        self.assertTrue(validate_bundle(self.path, self.manifest)["ready"])
        self.write_manifest(min_app_version="1.0.0", country_code="DEU", settlement_context_version="2")
        codes = self.codes(validate_bundle(self.path, self.manifest))
        self.assertTrue({"settlement_min_app_version", "country_mismatch", "manifest_capability_mismatch"}.issubset(codes))

    def test_manifest_hash_and_size_fail_independently(self):
        self.write_manifest(db={"file": "CHE.sqlite", "bytes": 1, "sha256": "0" * 64})
        codes = self.codes(validate_bundle(self.path, self.manifest))
        self.assertTrue({"manifest_database_size", "manifest_database_hash"}.issubset(codes))

    def test_refreshed_digest_does_not_hide_invalid_coordinate_arrays(self):
        bad_values = ("invalid", "null", "{}", "[]", "[[47]]", "[[47,8],[true,8]]",
                      '[[47,8],["47",8]]', "[[47,8],[91,8]]", "[[47,8],[47,181]]",
                      "[[47,8],[NaN,8]]", "[[47,8],[Infinity,8]]")
        for table in ("way_geom", "settlement_segment"):
            for value in bad_values:
                with self.subTest(table=table, geometry=value):
                    with sqlite3.connect(self.path) as db:
                        db.execute(f"UPDATE {table} SET points_json=? WHERE way_id=1", (value,))
                    self.write_manifest()
                    report = validate_bundle(self.path, self.manifest)
                    self.assertIn("invalid_geometry", self.codes(report))
                    self.assertNotIn("manifest_database_hash", self.codes(report))
                    self.assertEqual(report["geometry_checks"][table]["invalid"], 1)
            self.change(f"UPDATE {table} SET points_json='[[47,8],[47,8.001]]' WHERE way_id=1;")

    def test_documented_unknown_settlement_empty_geometry_remains_valid(self):
        self.change("""UPDATE settlement_segment SET points_json='[]',
            evidence_json='[{"reason":"usable_source_geometry_missing"}]' WHERE way_id=1;""")
        self.write_manifest()
        report = validate_bundle(self.path, self.manifest)
        self.assertTrue(report["ready"], report["errors"])
        self.assertEqual(report["geometry_checks"]["settlement_segment"]["unknown_empty"], 1)
        self.change("UPDATE settlement_segment SET inside_city=1,source='traffic_sign',confidence='high' WHERE way_id=1;")
        self.assertIn("invalid_geometry", self.codes(validate_bundle(self.path)))

    def test_spatial_indexes_must_contain_source_bounds_without_exact_float_equality(self):
        self.change("""
            INSERT INTO areas(row_id,area_id,min_lon,min_lat,max_lon,max_lat) VALUES(1,'w:1',8,47,8.001,47.001);
            INSERT INTO areas_rtree VALUES(1,8,8.001,47,47.001);
            INSERT INTO city_boundary VALUES(1,'r',1,8,'Town',8,47,8.001,47.001);
            INSERT INTO city_boundary_rtree VALUES(1,8,8.001,47,47.001);
            INSERT INTO city_place VALUES(1,'town','Town',8.001,47.001);
            INSERT INTO city_place_rtree VALUES(1,8.001,8.001,47.001,47.001);
        """)
        self.write_manifest()
        with sqlite3.connect(self.path) as db:
            source, rounded = db.execute("SELECT w.max_lon,r.max_lon FROM ways w JOIN ways_rtree r USING(way_id) WHERE way_id=1").fetchone()
        self.assertGreater(rounded, source)
        report = validate_bundle(self.path, self.manifest)
        self.assertTrue(report["ready"], report["errors"])
        for table in ("ways_rtree", "surface_way_network_rtree", "areas_rtree", "city_boundary_rtree", "city_place_rtree"):
            self.change(f"UPDATE {table} SET min_lon=0,max_lon=0,min_lat=0,max_lat=0;")
        self.write_manifest()
        report = validate_bundle(self.path, self.manifest)
        mismatches = [issue for issue in report["errors"] if issue["code"] == "rtree_bounds_mismatch"]
        self.assertEqual(len(mismatches), 5, report["errors"])
        self.assertNotIn("manifest_database_hash", self.codes(report))

    def test_required_null_references_fail_but_unassociated_settlement_sign_is_valid(self):
        self.change("""INSERT INTO settlement_sign VALUES('n:1','n',1,'CH:4.27',1,0,NULL,8,47,'unresolved','{}');""")
        self.write_manifest()
        report = validate_bundle(self.path, self.manifest)
        self.assertTrue(report["ready"], report["errors"])
        self.change("""
            UPDATE way_links SET linked_way_id=NULL WHERE way_id=2;
            UPDATE motorway_exit_approach SET exit_way_id=NULL;
            UPDATE way_continuity_membership SET continuity_group_id=NULL;
        """)
        self.write_manifest()
        report = validate_bundle(self.path, self.manifest)
        failures = [issue for issue in report["errors"] if issue["code"] == "null_reference"]
        self.assertEqual(len(failures), 3, report["errors"])
        self.assertNotIn("manifest_database_hash", self.codes(report))

    def test_compressed_artifact_fields_are_required_even_with_valid_materialized_digest(self):
        original = self.write_manifest()["db"]
        self.write_manifest(db={"compression": "gzip", "bytes": -1, "sha256": "invalid",
                                "uncompressed_bytes": original["bytes"], "uncompressed_sha256": original["sha256"]})
        codes = self.codes(validate_bundle(self.path, self.manifest))
        self.assertTrue({"manifest_database_file", "manifest_artifact_size", "manifest_artifact_hash"}.issubset(codes))
        self.assertNotIn("manifest_database_hash", codes)

    def test_configured_non_swiss_country_normalizes_and_city_schema_is_checked(self):
        self.change("UPDATE metadata SET value='LU' WHERE key IN ('country_code','settlement_country_code');")
        self.write_manifest(country_code="LUX")
        self.assertTrue(validate_bundle(self.path, self.manifest)["ready"])
        self.change("ALTER TABLE city_ring RENAME COLUMN outer_index TO old_outer_index;")
        report = validate_bundle(self.path)
        self.assertTrue(any(issue["code"] == "missing_columns" and "outer_index" in issue["message"] for issue in report["errors"]))

    def test_cli_writes_report_and_returns_failure_for_missing_capabilities(self):
        self.change("DROP TABLE motorway_exit_approach; DROP TABLE way_links;")
        output = self.root / "report.json"
        script = Path(__file__).resolve().parents[2] / "scripts/map/validate_v3_testing_bundle.py"
        result = subprocess.run([sys.executable, str(script), "--db", str(self.path), "--require-settlement", "--out-json", str(output)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 1, result.stderr)
        report = json.loads(output.read_text())
        self.assertEqual(report, json.loads(result.stdout))
        self.assertEqual(sum(issue["code"] == "missing_table" for issue in report["errors"]), 2)


if __name__ == "__main__":
    unittest.main()
