import importlib.util
import json
import sqlite3
import tempfile
import subprocess
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("conditional_speed_rules", ROOT / "scripts/map/conditional_speed_rules.py")
rules = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rules)


class ConditionalSpeedRulesTests(unittest.TestCase):
    def test_preserves_all_191_audited_patterns_without_promoting_unsupported_syntax(self):
        patterns = json.loads((ROOT / "docs/CONDITIONAL_MAXSPEED_BW_2026-10-23.inventory.json").read_text())["patterns"]
        self.assertEqual(len(patterns), 191)
        for pattern in patterns:
            compiled = rules.compile_tags({pattern["key"]: pattern["raw_value"]})
            row = compiled["tags"][0]
            self.assertEqual(row["key"], pattern["key"])
            self.assertEqual(row["raw"], pattern["raw_value"])
            self.assertIn(row["status"], ("supported", "unsupported", "malformed", "review_required"))
            if "17:030" in row["raw"] or row.get("lane"):
                self.assertNotEqual(row["status"], "supported")

    def test_ordered_pairs_and_calendar_exclusions_keep_their_structure(self):
        compiled = rules.compile_tags({"maxspeed:conditional": "30 @ (Mo-Fr 07:00-17:00; PH off; SH off); none @ (22:00-06:00)"})
        tag = compiled["tags"][0]
        self.assertEqual(tag["status"], "supported")
        self.assertEqual([c["limit"]["kind"] for c in tag["clauses"]], ["numeric", "unlimited"])
        self.assertEqual(tag["clauses"][0]["condition"]["kind"], "all")
        self.assertEqual(tag["clauses"][1]["condition"]["windows"], [[1320, 360]])

    def test_unsupported_vehicle_lane_and_variable_values_remain_evidence(self):
        compiled = rules.compile_tags({"maxspeed:hgv:conditional": "80 @ (weight>7.5)", "maxspeed:lanes:conditional": "80 @ wet|80 @ wet|", "maxspeed:variable": "yes"})
        self.assertEqual(len(compiled["tags"]), 3)
        self.assertEqual(sum(t["status"] == "unsupported" for t in compiled["tags"]), 2)
        with self.assertRaises(ValueError): rules.limit("30garbage")
        self.assertEqual(rules.limit("5"), {"kind": "numeric", "kmh": 5.0})
        self.assertAlmostEqual(rules.limit("30 mph")["kmh"], 48.28032)

    def test_nonlegal_metadata_and_other_vehicle_profiles_do_not_mask_motorcars(self):
        compiled = rules.compile_tags({"maxspeed:advisory": "30", "maxspeed:practical": "20", "maxspeed:forward:reason": "school", "maxspeed:note": "source description", "maxspeed:bicycle": "15"})
        for row in compiled["tags"]:
            if row["key"] == "maxspeed:bicycle": self.assertEqual(row["vehicle"], "bicycle")
            else: self.assertEqual(row["role"], "metadata")

    def test_database_rebuild_removes_stale_rules_and_retains_64_bit_ids(self):
        with tempfile.TemporaryDirectory() as folder, sqlite3.connect(":memory:") as db:
            path = Path(folder) / "ways.meta"
            path.write_text(json.dumps({"way_id": "9007199254740993", "raw_tags": {"maxspeed": "120", "maxspeed:conditional": "none @ (22:00-06:00)"}}) + "\n")
            report = rules.build(db, path, "snapshot-1")
            self.assertEqual(report["ways"], 1)
            self.assertEqual(db.execute("SELECT way_id FROM road_speed_rule_set").fetchone()[0], 9007199254740993)
            self.assertEqual(db.execute("SELECT source_snapshot FROM road_speed_source_tag LIMIT 1").fetchone()[0], "snapshot-1")
            path.write_text(json.dumps({"way_id": "9007199254740993", "raw_tags": {"maxspeed": "100"}}) + "\n")
            rules.build(db, path, "snapshot-2")
            self.assertEqual(db.execute("SELECT COUNT(*) FROM road_speed_rule_set").fetchone()[0], 0)
            self.assertEqual(db.execute("SELECT raw_value FROM road_speed_source_tag").fetchone()[0], "100")

    def test_static_electronic_marker_cannot_disappear_into_scalar_fallback(self):
        with tempfile.TemporaryDirectory() as folder, sqlite3.connect(":memory:") as db:
            path = Path(folder) / "ways.meta"
            path.write_text(json.dumps({"way_id": "716", "raw_tags": {"maxspeed": "signals"}}) + "\n")
            report = rules.build(db, path)
            self.assertEqual(report["ways"], 1)
            compiled = json.loads(db.execute("SELECT rules_json FROM road_speed_rule_set").fetchone()[0])
            self.assertEqual(compiled["tags"][0]["status"], "unsupported")

    def test_conditional_capability_rejects_heuristic_delta_before_output(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            database = root / "base.sqlite"
            with sqlite3.connect(database) as db:
                db.execute("CREATE TABLE road_speed_capability(version INTEGER)")
                db.execute("INSERT INTO road_speed_capability VALUES(1)")
            diff = root / "diff.osc"
            diff.write_text('<osmChange version="0.6"></osmChange>')
            result = subprocess.run([sys.executable, str(ROOT / "scripts/map/build_v3_delta_pack.py"), "--base-db", str(database), "--diff-file", str(diff), "--out-dir", str(root / "pack"), "--from-version", "old", "--to-version", "new"], text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("Conditional-speed rules require a full bundle", result.stderr)
            self.assertFalse((root / "pack").exists())

    def test_local_packaging_advertises_capability_and_requires_implemented_client(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder); database = root / "source.sqlite"
            with sqlite3.connect(database) as db:
                db.execute("CREATE TABLE road_speed_capability(version INTEGER,grammar TEXT,compiler_sha256 TEXT)")
                db.execute("INSERT INTO road_speed_capability VALUES(1,'youspeed-osm-speed-1',?)", ("a" * 64,))
            result = subprocess.run([sys.executable, str(ROOT / "scripts/map/publish_v3_bundle.py"), "--db", str(database), "--region", "fixture", "--bundle-version", "conditional-v1", "--min-app-version", "1.1", "--out-root", str(root / "bundles")], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            manifest = json.loads((root / "bundles/fixture/conditional-v1/fixture_manifest.json").read_text())
            self.assertEqual(manifest["min_app_version"], "1.5")
            self.assertEqual(manifest["source"]["conditional_speed_rules"]["delivery"], "full_only")


if __name__ == "__main__": unittest.main()
