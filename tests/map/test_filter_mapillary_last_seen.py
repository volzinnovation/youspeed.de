import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/map"))
from filter_mapillary_last_seen import filter_source, valid_last_seen


class MapillaryLastSeenFilterTests(unittest.TestCase):
    def test_provider_timestamps_and_missing_values(self):
        for value in (1794916800000, "2026-11-17T12:00:00+0000",
                      "2026-11-17T12:00:00+00:00", "2026-11-17T12:00:00.000Z"):
            self.assertTrue(valid_last_seen(value), value)
        for value in (None, True, 0, float("nan"), "", "unknown", "2026-11-17T12:00:00"):
            self.assertFalse(valid_last_seen(value), value)

    def test_rebuild_keeps_dated_raw_properties_and_preserves_original(self):
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "source.sqlite"
            output = Path(directory) / "filtered.sqlite"
            with sqlite3.connect(source) as db:
                db.executescript("""
                    CREATE TABLE traffic_sign_inventory(row_id INTEGER PRIMARY KEY,source_id TEXT,record_key TEXT,raw_properties_json TEXT);
                    CREATE TABLE traffic_sign_inventory_rtree(row_id INTEGER PRIMARY KEY);
                    CREATE TABLE traffic_sign_runtime(sign_id TEXT PRIMARY KEY,source_id TEXT,record_key TEXT,snapshot_sha256 TEXT);
                    CREATE TABLE traffic_sign_association(sign_id TEXT PRIMARY KEY);
                    CREATE TABLE traffic_sign_source(source_id TEXT PRIMARY KEY,snapshot_sha256 TEXT,record_count INTEGER);
                    CREATE TABLE traffic_sign_way_rule(sign_id TEXT);
                    CREATE TABLE traffic_sign_capability(key TEXT PRIMARY KEY,value TEXT);
                    INSERT INTO traffic_sign_source VALUES('mapillary-eval','old',3);
                    INSERT INTO traffic_sign_capability VALUES('mapillary_eval_snapshot','old');
                """)
                for index, value in enumerate(("2026-11-17T12:00:00+0000", None, 1794916800000), 1):
                    db.execute("INSERT INTO traffic_sign_inventory VALUES(?,?,?,?)",
                               (index, "mapillary-eval", str(index), json.dumps({"last_seen_at": value})))
                    db.execute("INSERT INTO traffic_sign_inventory_rtree VALUES(?)", (index,))
                    db.execute("INSERT INTO traffic_sign_runtime VALUES(?,?,?,?)",
                               (f"mapillary-eval:{index}", "mapillary-eval", str(index), "old"))
                    db.execute("INSERT INTO traffic_sign_association VALUES(?)", (f"mapillary-eval:{index}",))
            result = filter_source(source, output)
            self.assertEqual(result["missing_or_invalid_last_seen_removed"], 1)
            self.assertEqual(result["mapillary_retained"], 2)
            with sqlite3.connect(source) as db:
                self.assertEqual(db.execute("SELECT count(*) FROM traffic_sign_inventory").fetchone(), (3,))
            with sqlite3.connect(output) as db:
                self.assertEqual(db.execute("SELECT record_key FROM traffic_sign_inventory ORDER BY row_id").fetchall(),
                                 [("1",), ("3",)])
                self.assertEqual(db.execute("SELECT record_count FROM traffic_sign_source").fetchone(), (2,))
                self.assertEqual(db.execute("SELECT count(*) FROM traffic_sign_association").fetchone(), (2,))
                self.assertEqual(db.execute("SELECT count(*) FROM traffic_sign_inventory_rtree").fetchone(), (2,))
            with self.assertRaises(ValueError):
                filter_source(source, output)


if __name__ == "__main__":
    unittest.main()
