import json
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PUBLISH_V3 = REPO_ROOT / "scripts/map/publish_v3_bundle.py"
BUILD_V3_DELTA = REPO_ROOT / "scripts/map/build_v3_delta_pack.py"
BUILD_V3_DELTA_INDEX = REPO_ROOT / "scripts/map/build_v3_delta_index.py"
ROLL_V3_DELTA_INDEX = REPO_ROOT / "scripts/map/roll_v3_delta_index.py"


def run_cmd(args, *, check=True):
    return subprocess.run(args, check=check, text=True, capture_output=True)


class V3BundlePublishAndDeltaTests(unittest.TestCase):
    def setUp(self):
        self.tmp_ctx = tempfile.TemporaryDirectory()
        self.tmpdir = Path(self.tmp_ctx.name)
        self.base_db = self.tmpdir / "speeds_v3.sqlite"
        self.diff_file = self.tmpdir / "delta.osc"
        self._create_fixture_db(self.base_db)
        self.diff_file.write_text(self._fixture_diff(), encoding="utf-8")

    def tearDown(self):
        self.tmp_ctx.cleanup()

    @staticmethod
    def _create_fixture_db(path: Path) -> None:
        conn = sqlite3.connect(path)
        try:
            conn.executescript(
                """
                CREATE TABLE ways (
                  row_id INTEGER PRIMARY KEY,
                  way_id TEXT NOT NULL UNIQUE,
                  highway TEXT,
                  street_name TEXT,
                  ref TEXT,
                  maxspeed TEXT,
                  maxspeed_type TEXT,
                  source_maxspeed TEXT,
                  zone_maxspeed TEXT,
                  traffic_sign TEXT,
                  approx_heading_deg REAL,
                  min_lon REAL NOT NULL,
                  min_lat REAL NOT NULL,
                  max_lon REAL NOT NULL,
                  max_lat REAL NOT NULL
                );
                CREATE VIRTUAL TABLE ways_rtree USING rtree(
                  row_id,
                  min_lon, max_lon,
                  min_lat, max_lat
                );
                CREATE TABLE way_geom (
                  row_id INTEGER PRIMARY KEY,
                  way_id TEXT NOT NULL UNIQUE,
                  points_json TEXT NOT NULL
                );

                INSERT INTO ways(row_id, way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, min_lon, min_lat, max_lon, max_lat)
                VALUES
                  (1, '100', 'residential', 'Fixture Street', 'L 605', '50', NULL, NULL, NULL, NULL, 90.0, 13.0000, 52.0000, 13.0010, 52.0010),
                  (2, '300', 'service', 'Fixture Service Road', 'K 1', '20', NULL, NULL, NULL, NULL, 0.0, 13.0100, 52.0100, 13.0110, 52.0110);

                INSERT INTO ways_rtree(row_id, min_lon, max_lon, min_lat, max_lat)
                VALUES
                  (1, 13.0000, 13.0010, 52.0000, 52.0010),
                  (2, 13.0100, 13.0110, 52.0100, 52.0110);

                INSERT INTO way_geom(row_id, way_id, points_json)
                VALUES
                  (1, '100', '[[52.0000,13.0000],[52.0010,13.0010]]'),
                  (2, '300', '[[52.0100,13.0100],[52.0110,13.0110]]');
                """
            )
            conn.commit()
        finally:
            conn.close()

    @staticmethod
    def _fixture_diff() -> str:
        return textwrap.dedent(
            """\
            <?xml version='1.0' encoding='UTF-8'?>
            <osmChange version='0.6' generator='tests'>
              <modify>
                <node id='1' lat='52.1000' lon='13.1000'/>
                <node id='2' lat='52.1010' lon='13.1010'/>
                <way id='100'>
                  <nd ref='1'/>
                  <nd ref='2'/>
                  <tag k='highway' v='residential'/>
                  <tag k='name' v='Updated Fixture Street'/>
                  <tag k='ref' v='B 3'/>
                  <tag k='maxspeed' v='30'/>
                </way>
              </modify>
              <create>
                <node id='3' lat='52.2000' lon='13.2000'/>
                <node id='4' lat='52.2010' lon='13.2010'/>
                <way id='200'>
                  <nd ref='3'/>
                  <nd ref='4'/>
                  <tag k='highway' v='service'/>
                  <tag k='ref' v='K 2'/>
                  <tag k='maxspeed' v='20'/>
                </way>
              </create>
              <delete>
                <way id='300'>
                  <nd ref='10'/>
                  <nd ref='11'/>
                </way>
              </delete>
            </osmChange>
            """
        )

    def test_build_v3_delta_pack_and_apply_patch(self):
        out_dir = self.tmpdir / "delta_pack"
        run_cmd(
            [
                sys.executable,
                str(BUILD_V3_DELTA),
                "--base-db",
                str(self.base_db),
                "--diff-file",
                str(self.diff_file),
                "--region",
                "germany",
                "--from-version",
                "2026-02-23",
                "--to-version",
                "2026-02-24",
                "--out-dir",
                str(out_dir),
                "--github-owner",
                "volzinnovation",
                "--github-repo",
                "youspeed.de",
                "--github-release-tag",
                "v3-data-2026-02-24",
                "--github-asset-prefix",
                "germany/2026-02-24",
            ]
        )

        patch_path = out_dir / "v3_patch.sql"
        manifest_path = out_dir / "v3_delta_manifest.json"
        self.assertTrue(patch_path.exists())
        self.assertTrue(manifest_path.exists())

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["format"], "youspeed.v3.delta.manifest")
        self.assertEqual(manifest["from_bundle_version"], "2026-02-23")
        self.assertEqual(manifest["to_bundle_version"], "2026-02-24")
        self.assertIn("github.com/volzinnovation/youspeed.de/releases/download/v3-data-2026-02-24", manifest["patch"]["url"])
        self.assertGreater(manifest["stats"]["delete_way_count"], 0)
        self.assertGreater(manifest["stats"]["insert_way_count"], 0)

        # Apply patch and verify changed data.
        db_copy = self.tmpdir / "applied.sqlite"
        db_copy.write_bytes(self.base_db.read_bytes())
        patch_sql = patch_path.read_text(encoding="utf-8")
        with sqlite3.connect(db_copy) as conn:
            conn.executescript(patch_sql)
            rows = conn.execute("SELECT way_id, maxspeed, street_name, ref FROM ways ORDER BY way_id").fetchall()
            row_map = {r[0]: {"maxspeed": r[1], "street_name": r[2], "ref": r[3]} for r in rows}
            self.assertEqual(row_map.get("100", {}).get("maxspeed"), "30")
            self.assertEqual(row_map.get("100", {}).get("street_name"), "Updated Fixture Street")
            self.assertEqual(row_map.get("100", {}).get("ref"), "B 3")
            self.assertEqual(row_map.get("200", {}).get("maxspeed"), "20")
            self.assertEqual(row_map.get("200", {}).get("ref"), "K 2")
            self.assertNotIn("300", row_map)

    def test_publish_v3_bundle_with_github_release_urls(self):
        delta_index = self.tmpdir / "delta-index.v3.json"
        delta_index.write_text(
            json.dumps(
                {
                    "format": "youspeed.v3.delta.index",
                    "schema_version": 1,
                    "count": 0,
                    "entries": [],
                }
            ),
            encoding="utf-8",
        )
        run_cmd(
            [
                sys.executable,
                str(PUBLISH_V3),
                "--region",
                "germany",
                "--db",
                str(self.base_db),
                "--bundle-version",
                "2026-02-24",
                "--out-root",
                str(self.tmpdir / "bundles"),
                "--delta-index",
                str(delta_index),
                "--github-owner",
                "volzinnovation",
                "--github-repo",
                "youspeed.de",
                "--github-release-tag",
                "v3-data-2026-02-24",
                "--github-asset-prefix",
                "germany/2026-02-24",
            ]
        )
        manifest_path = self.tmpdir / "bundles" / "germany" / "2026-02-24" / "DEU-latest.bundle-manifest.v3.json"
        self.assertTrue(manifest_path.exists())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["format"], "youspeed.v3.bundle.manifest")
        self.assertEqual(manifest["variant"], "v3")
        self.assertEqual(manifest["db"]["file"], "DEU-latest.speeds_v3.sqlite")
        self.assertIn("github.com/volzinnovation/youspeed.de/releases/download/v3-data-2026-02-24", manifest["db"]["url"])
        self.assertIn("DEU-latest.delta-index.v3.json", manifest["delta_index"]["file"])

    def test_publish_v3_bundle_allows_latest_dir_name(self):
        out_root = self.tmpdir / "bundles"
        run_cmd(
            [
                sys.executable,
                str(PUBLISH_V3),
                "--region",
                "germany",
                "--db",
                str(self.base_db),
                "--bundle-version",
                "2026-02-24",
                "--bundle-dir-name",
                "latest",
                "--out-root",
                str(out_root),
            ]
        )
        manifest_path = out_root / "germany" / "latest" / "DEU-latest.bundle-manifest.v3.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["bundle_version"], "2026-02-24")
        self.assertEqual(payload["db"]["file"], "DEU-latest.speeds_v3.sqlite")

    def test_publish_v3_bundle_splits_large_db_into_parts(self):
        out_root = self.tmpdir / "bundles"
        run_cmd(
            [
                sys.executable,
                str(PUBLISH_V3),
                "--region",
                "germany",
                "--db",
                str(self.base_db),
                "--bundle-version",
                "2026-02-24",
                "--bundle-dir-name",
                "latest",
                "--out-root",
                str(out_root),
                "--max-release-asset-bytes",
                "10000",
                "--github-owner",
                "volzinnovation",
                "--github-repo",
                "youspeed.de",
                "--github-release-tag",
                "deu-v3-data-latest",
            ]
        )
        bundle_dir = out_root / "germany" / "latest"
        manifest_path = bundle_dir / "DEU-latest.bundle-manifest.v3.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertIn("db_parts", payload)
        self.assertGreater(len(payload["db_parts"]), 1)
        self.assertIsNone(payload["db"]["url"])
        self.assertEqual(payload["db"]["bytes"], self.base_db.stat().st_size)

        part_files = sorted(bundle_dir.glob("DEU-latest.speeds_v3.sqlite.part*"))
        self.assertEqual(len(part_files), len(payload["db_parts"]))
        self.assertGreater(sum(p.stat().st_size for p in part_files), 0)
        for part in payload["db_parts"]:
            self.assertIn("releases/download/deu-v3-data-latest", str(part.get("url")))

    def test_build_delta_index(self):
        delta_dir = self.tmpdir / "deltas"
        a = delta_dir / "a"
        b = delta_dir / "b"
        a.mkdir(parents=True, exist_ok=True)
        b.mkdir(parents=True, exist_ok=True)
        (a / "v3_delta_manifest.json").write_text(
            json.dumps(
                {
                    "format": "youspeed.v3.delta.manifest",
                    "schema_version": 1,
                    "region": "germany",
                    "from_bundle_version": "2026-02-23",
                    "to_bundle_version": "2026-02-24",
                    "patch": {"file": "v3_patch.sql", "sha256": "0" * 64, "bytes": 10, "url": "https://example/a"},
                    "stats": {},
                }
            ),
            encoding="utf-8",
        )
        (b / "v3_delta_manifest.json").write_text(
            json.dumps(
                {
                    "format": "youspeed.v3.delta.manifest",
                    "schema_version": 1,
                    "region": "germany",
                    "from_bundle_version": "2026-02-24",
                    "to_bundle_version": "2026-02-25",
                    "patch": {"file": "v3_patch.sql", "sha256": "1" * 64, "bytes": 12, "url": "https://example/b"},
                    "stats": {},
                }
            ),
            encoding="utf-8",
        )
        out = self.tmpdir / "delta-index.json"
        run_cmd(
            [
                sys.executable,
                str(BUILD_V3_DELTA_INDEX),
                "--delta-manifest-dir",
                str(delta_dir),
                "--output",
                str(out),
            ]
        )
        payload = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(payload["format"], "youspeed.v3.delta.index")
        self.assertEqual(payload["count"], 2)

    def test_roll_delta_index_retention(self):
        existing = self.tmpdir / "existing-index.json"
        entries = []
        for day in range(1, 41):
            d0 = f"2026-01-{day:02d}" if day <= 31 else f"2026-02-{(day-31):02d}"
            d1 = f"2026-01-{(day+1):02d}" if day + 1 <= 31 else f"2026-02-{(day+1-31):02d}"
            entries.append(
                {
                    "from_bundle_version": d0,
                    "to_bundle_version": d1,
                    "region": "germany",
                    "delta_manifest_file": f"https://example/{d0}_to_{d1}/v3_delta_manifest.json",
                    "patch_file": "v3_patch.sql",
                    "patch_sha256": "0" * 64,
                    "patch_bytes": 123,
                    "patch_url": f"https://example/{d0}_to_{d1}/v3_patch.sql",
                }
            )
        existing.write_text(
            json.dumps(
                {
                    "format": "youspeed.v3.delta.index",
                    "schema_version": 1,
                    "count": len(entries),
                    "entries": entries,
                }
            ),
            encoding="utf-8",
        )

        out = self.tmpdir / "rolled-index.json"
        run_cmd(
            [
                sys.executable,
                str(ROLL_V3_DELTA_INDEX),
                "--existing-index",
                str(existing),
                "--output",
                str(out),
                "--retention-count",
                "30",
            ]
        )
        payload = json.loads(out.read_text(encoding="utf-8"))
        self.assertEqual(payload["format"], "youspeed.v3.delta.index")
        self.assertEqual(payload["retention_count"], 30)
        self.assertEqual(payload["retention_days"], 30)
        self.assertEqual(payload["count"], 30)
        to_versions = [entry["to_bundle_version"] for entry in payload["entries"]]
        self.assertEqual(to_versions[0], "2026-01-12")
        self.assertEqual(to_versions[-1], "2026-02-10")


if __name__ == "__main__":
    unittest.main()
