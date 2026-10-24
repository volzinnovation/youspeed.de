"""Preserve real OSM directional limits without inventing settlement context."""

import hashlib
import json
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts/map"
FIXTURE = Path(__file__).parent / "fixtures/baden-wuerttemberg-directional-speeds-20260913.osm"
EXPECTED = [(81302142, None, "70", "100"), (1248904506, None, "30", "50"),
            (1302655171, None, "100", "70")]

try:
    import osmium  # noqa: F401
    import shapely
    AVAILABLE = int(shapely.__version__.split(".")[0]) >= 2
except ImportError:
    AVAILABLE = False


def run(*args, check=True):
    return subprocess.run([sys.executable, *map(str, args)], check=check, capture_output=True, text=True)


@unittest.skipUnless(AVAILABLE, "requires pyosmium and Shapely >= 2")
class DirectionalSpeedPipelineTests(unittest.TestCase):
    def setUp(self):
        self.context = tempfile.TemporaryDirectory()
        self.addCleanup(self.context.cleanup)
        self.folder = Path(self.context.name)
        outputs = [self.folder / name for name in ("ways.idx", "ways.meta", "areas.idx", "ways.lookup", "ways.geom", "ways.geom.lookup")]
        run(SCRIPTS / "pack_runtime_artifacts_pyosmium.py", FIXTURE, *outputs)
        self.db = self.build("source.sqlite")

    def build(self, name):
        db = self.folder / name
        run(SCRIPTS / "build_spatialite_v3.py", "--v1-dist", self.folder, "--out-db", db,
            "--input-pbf", FIXTURE, "--build-settlement-context", "--country-code", "DE")
        return db

    def assert_source_limits(self, database):
        with sqlite3.connect(database) as conn:
            self.assertEqual(conn.execute("SELECT way_id,maxspeed,maxspeed_forward,maxspeed_backward FROM ways ORDER BY way_id").fetchall(), EXPECTED)
            self.assertEqual(conn.execute("SELECT way_id,inside_city,source,confidence FROM settlement_segment ORDER BY way_id").fetchall(),
                             [(way, None, "missing", "unknown") for way, *_ in EXPECTED])
            self.assertEqual(conn.execute("SELECT value FROM metadata WHERE key='schema_version'").fetchone(), ("1",))

    def test_original_osm_tags_survive_pack_and_sqlite_roundtrip(self):
        provenance = json.loads(FIXTURE.with_suffix(".source.json").read_text())
        self.assertEqual(hashlib.sha256(FIXTURE.read_bytes()).hexdigest(), provenance["fixture_sha256"])
        source = ET.parse(FIXTURE).getroot()
        self.assertEqual(len(source.findall("node")), 13)
        self.assertTrue(all(int(way.attrib["version"]) > 0 for way in source.findall("way")))
        metadata = [json.loads(line) for line in (self.folder / "ways.meta").read_text().splitlines()]
        self.assertEqual(sorted((int(row["way_id"]), row["maxspeed"], row["maxspeed_forward"], row["maxspeed_backward"]) for row in metadata), EXPECTED)
        self.assert_source_limits(self.db)

    def test_existing_prepared_metadata_recovers_directions_from_original_raw_tags(self):
        path = self.folder / "ways.meta"
        metadata = [json.loads(line) for line in path.read_text().splitlines()]
        for row in metadata:
            del row["maxspeed_forward"]
            del row["maxspeed_backward"]
        path.write_text("".join(json.dumps(row) + "\n" for row in metadata))
        self.assert_source_limits(self.build("backfilled.sqlite"))

    @unittest.skipUnless(shutil.which("jq"), "requires jq for the shell packer's metadata stage")
    def test_shell_packer_metadata_preserves_the_same_source_directions(self):
        # Run the shell packer's actual jq stage on the source fixture's GeoJSON
        # representation, without requiring the separate osmium-tool binary.
        shell = (SCRIPTS / "pack_runtime_artifacts.sh").read_text()
        program = re.search(r"# Way metadata[\s\S]*?jq -c '([\s\S]+?)' \"\$roads_geojsonseq\"", shell).group(1)
        source = ET.parse(FIXTURE).getroot()
        nodes = {node.attrib["id"]: [float(node.attrib["lon"]), float(node.attrib["lat"])] for node in source.findall("node")}
        features = [{"type": "Feature", "id": "way/" + way.attrib["id"],
                     "properties": {tag.attrib["k"]: tag.attrib["v"] for tag in way.findall("tag")},
                     "geometry": {"type": "LineString", "coordinates": [nodes[node.attrib["ref"]] for node in way.findall("nd")]}}
                    for way in source.findall("way")]
        result = subprocess.run(["jq", "-c", program], input="".join(json.dumps(feature) + "\n" for feature in features),
                                text=True, capture_output=True, check=True)
        rows = [json.loads(line) for line in result.stdout.splitlines()]
        self.assertEqual(sorted((int(row["way_id"]), row["maxspeed"], row["maxspeed_forward"], row["maxspeed_backward"]) for row in rows), EXPECTED)

    def delta(self, base, target, *, check=True):
        diff = self.folder / "empty.osc"
        diff.write_text('<osmChange version="0.6"/>')
        return run(SCRIPTS / "build_v3_delta_pack.py", "--base-db", base, "--target-db", target,
                   "--diff-file", diff, "--from-version", "base", "--to-version", "target",
                   "--out-dir", self.folder / "delta", "--validate-on-copy", check=check)

    def legacy_delta_source(self):
        # New bundles advertise conditional rules and require full delivery.
        # Keep these delta regressions scoped to the pre-capability schema.
        legacy = self.folder / "legacy-delta-source.sqlite"
        shutil.copy2(self.db, legacy)
        with sqlite3.connect(legacy) as conn:
            for table in ("road_speed_capability", "road_speed_source_tag", "road_speed_rule_set",
                          "road_speed_rule", "road_speed_condition", "road_speed_interpretation"):
                conn.execute("DROP TABLE " + table)
        return legacy

    def test_direction_only_updates_and_removals_are_lossless_in_legacy_exact_delta(self):
        base = self.legacy_delta_source()
        target = self.folder / "target.sqlite"
        shutil.copy2(base, target)
        with sqlite3.connect(target) as conn:
            conn.execute("UPDATE ways SET maxspeed_forward='60' WHERE way_id=81302142")
            conn.execute("UPDATE ways SET maxspeed_backward=NULL WHERE way_id=1302655171")
        self.delta(base, target)
        patch = zlib.decompress((self.folder / "delta/v3_patch.sql.zlib").read_bytes()).decode()
        with sqlite3.connect(base) as conn:
            conn.executescript(patch)
            self.assertEqual(conn.execute("SELECT maxspeed_forward,maxspeed_backward FROM ways WHERE way_id=81302142").fetchone(), ("60", "100"))
            self.assertEqual(conn.execute("SELECT maxspeed_forward,maxspeed_backward FROM ways WHERE way_id=1302655171").fetchone(), ("100", None))
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM settlement_segment WHERE inside_city IS NOT NULL").fetchone(), (0,))

    def test_legacy_column_transition_requires_full_bundle(self):
        target = self.legacy_delta_source()
        legacy = self.folder / "legacy.sqlite"
        shutil.copy2(target, legacy)
        with sqlite3.connect(legacy) as conn:
            conn.execute("ALTER TABLE ways DROP COLUMN maxspeed_forward")
            conn.execute("ALTER TABLE ways DROP COLUMN maxspeed_backward")
        result = self.delta(legacy, target, check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("deliver a full rebuilt bundle", result.stderr)
        self.assertFalse((self.folder / "delta/v3_patch.sql.zlib").exists())

    def test_shared_phone_fixture_builder_emits_source_cases_and_matching_database_hash(self):
        output = self.folder / "phones"
        run(SCRIPTS / "build_directional_speed_fixture.py", "--output-dir", output)
        database = output / "speeds_v3.sqlite"
        self.assert_source_limits(database)
        cases = json.loads((output / "cases.json").read_text())
        self.assertEqual(cases["databaseSHA256"], hashlib.sha256(database.read_bytes()).hexdigest())
        self.assertEqual([(int(case["wayId"]), None, str(case["expectedForwardKmh"]), str(case["expectedBackwardKmh"]))
                          for case in cases["cases"]], EXPECTED)
        self.assertTrue(all(0 <= case["forwardHeadingDeg"] < 360 for case in cases["cases"]))


if __name__ == "__main__":
    unittest.main()
