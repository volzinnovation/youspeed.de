"""Source-verified repairs must preserve the current regional bundle."""

import json
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/map"))
from repair_directional_speed_fields import repair, sha256, source_ways

SOURCE = Path(__file__).parent / "fixtures/baden-wuerttemberg-directional-speeds-20260913.osm"


class DirectionalSpeedRepairTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.folder = Path(self.temporary.name)
        self.base = self.folder / "current-september28.sqlite"
        self.output = self.folder / "local-source-repair.sqlite"
        self.source = source_ways(SOURCE)
        with sqlite3.connect(self.base) as db:
            db.executescript("""
                CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
                INSERT INTO metadata VALUES('bundle_version','2026-09-28-refresh-8177c59');
                CREATE TABLE ways(way_id INTEGER PRIMARY KEY,highway TEXT,street_name TEXT,ref TEXT,maxspeed TEXT,other TEXT);
                CREATE TABLE way_geom(way_id INTEGER PRIMARY KEY,points_json TEXT);
                CREATE TABLE settlement_segment(segment_id INTEGER PRIMARY KEY,way_id INTEGER,inside_city INTEGER,source TEXT,evidence_json TEXT);
                CREATE TABLE way_links(way_id INTEGER,linked_way_id INTEGER);
                CREATE TABLE untouched(payload BLOB);
                INSERT INTO untouched VALUES(X'000102FFFF');
                INSERT INTO ways VALUES(999,'residential','Newer road',NULL,'60','preserve-new-regional-data');
                INSERT INTO way_geom VALUES(999,'[[49,8],[49.1,8.1]]');
                INSERT INTO settlement_segment VALUES(999,999,1,'zone_traffic','newer-context');
                INSERT INTO way_links VALUES(999,1248904506);
            """)
            for way_id, source in self.source.items():
                tags = source["tags"]
                db.execute("INSERT INTO ways VALUES(?,?,?,?,NULL,?)", (way_id, tags["highway"], tags["name"], tags["ref"], "original-data"))
                db.execute("INSERT INTO way_geom VALUES(?,?)", (way_id, json.dumps(source["points"])))
                db.execute("INSERT INTO settlement_segment VALUES(?,?,NULL,'missing','[]')", (way_id, way_id))

    def assert_failure_preserves_base(self, message):
        before = sha256(self.base)
        with self.assertRaisesRegex(ValueError, message):
            repair(self.base, SOURCE, self.output)
        self.assertEqual(sha256(self.base), before)
        self.assertFalse(self.output.exists())
        self.assertFalse(self.output.with_suffix(".repair.json").exists())

    def test_cli_repair_sets_only_three_source_fields_and_preserves_every_original_row(self):
        before_hash = sha256(self.base)
        with sqlite3.connect(self.base) as db:
            unchanged = {table: db.execute(f"SELECT * FROM {table}").fetchall()
                         for table in ("metadata", "way_geom", "settlement_segment", "way_links", "untouched")}
            original_ways = db.execute("SELECT * FROM ways ORDER BY way_id").fetchall()
        subprocess.run([sys.executable, str(ROOT / "scripts/map/repair_directional_speed_fields.py"),
                        "--base-db", str(self.base), "--source-osm", str(SOURCE), "--out-db", str(self.output),
                        "--expected-base-sha256", before_hash], check=True, text=True, capture_output=True)
        self.assertEqual(sha256(self.base), before_hash)
        with sqlite3.connect(self.output) as db:
            for table, expected in unchanged.items():
                self.assertEqual(db.execute(f"SELECT * FROM {table}").fetchall(), expected)
            self.assertEqual(db.execute("SELECT way_id,highway,street_name,ref,maxspeed,other FROM ways ORDER BY way_id").fetchall(), original_ways)
            self.assertEqual(db.execute("SELECT way_id,maxspeed_forward,maxspeed_backward FROM ways WHERE way_id!=999 ORDER BY way_id").fetchall(),
                             [(81302142, "70", "100"), (1248904506, "30", "50"), (1302655171, "100", "70")])
            self.assertEqual(db.execute("SELECT maxspeed_forward,maxspeed_backward FROM ways WHERE way_id=999").fetchone(), (None, None))
        report = json.loads(self.output.with_suffix(".repair.json").read_text())
        self.assertEqual(report["base_sha256"], before_hash)
        self.assertEqual(report["source_sha256"], sha256(SOURCE))
        self.assertEqual(report["output_sha256"], sha256(self.output))
        self.assertEqual(report["table_row_counts_before"], report["table_row_counts_after"])
        self.assertEqual(report["changed_way_ids"], sorted(self.source))

    def test_reversed_source_geometry_is_rejected_without_guessing_direction(self):
        way_id = 81302142
        with sqlite3.connect(self.base) as db:
            db.execute("UPDATE way_geom SET points_json=? WHERE way_id=?", (json.dumps(list(reversed(self.source[way_id]["points"]))), way_id))
        self.assert_failure_preserves_base("Ordered source geometry differs")

    def test_geometry_coordinate_or_vertex_count_changes_are_rejected(self):
        for mode in ("coordinate", "vertex_count"):
            with self.subTest(mode=mode):
                points = [point[:] for point in self.source[81302142]["points"]]
                if mode == "coordinate":
                    points[2][0] += 1e-5
                else:
                    points.pop(2)
                with sqlite3.connect(self.base) as db:
                    db.execute("UPDATE way_geom SET points_json=? WHERE way_id=81302142", (json.dumps(points),))
                self.assert_failure_preserves_base("Ordered source geometry differs")

    def test_existing_directional_values_are_preserved_or_fail_on_conflict(self):
        with sqlite3.connect(self.base) as db:
            db.execute("ALTER TABLE ways ADD COLUMN maxspeed_forward TEXT")
            db.execute("ALTER TABLE ways ADD COLUMN maxspeed_backward TEXT")
            db.execute("UPDATE ways SET maxspeed_forward='70',maxspeed_backward='100' WHERE way_id=81302142")
            db.execute("UPDATE ways SET maxspeed_forward='77',maxspeed_backward='88' WHERE way_id=999")
        repair(self.base, SOURCE, self.output)
        with sqlite3.connect(self.output) as db:
            self.assertEqual(db.execute("SELECT maxspeed_forward,maxspeed_backward FROM ways WHERE way_id=999").fetchone(), ("77", "88"))
        self.output.unlink()
        self.output.with_suffix(".repair.json").unlink()
        with sqlite3.connect(self.base) as db:
            db.execute("UPDATE ways SET maxspeed_backward='90' WHERE way_id=81302142")
        self.assert_failure_preserves_base("Conflicting existing directional value")

    def test_unknown_way_or_existing_generic_limit_is_rejected(self):
        with sqlite3.connect(self.base) as db:
            db.execute("UPDATE ways SET maxspeed='80' WHERE way_id=81302142")
        self.assert_failure_preserves_base("already has a generic speed limit")
        with sqlite3.connect(self.base) as db:
            db.execute("UPDATE ways SET maxspeed=NULL WHERE way_id=81302142")
            db.execute("DELETE FROM ways WHERE way_id=81302142")
        self.assert_failure_preserves_base("Unknown way")

    def test_pinned_hash_and_current_database_cannot_be_overwritten(self):
        with self.assertRaisesRegex(ValueError, "pinned published artifact"):
            repair(self.base, SOURCE, self.output, "0" * 64)
        with self.assertRaisesRegex(ValueError, "never overwritten"):
            repair(self.base, SOURCE, self.base)
        self.output.write_text("preserve this existing output")
        with self.assertRaisesRegex(ValueError, "never overwritten"):
            repair(self.base, SOURCE, self.output)
        self.assertEqual(self.output.read_text(), "preserve this existing output")


if __name__ == "__main__":
    unittest.main()
