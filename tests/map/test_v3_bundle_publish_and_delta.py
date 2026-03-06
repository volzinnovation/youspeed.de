import json
import sqlite3
import subprocess
import sys
import tempfile
import textwrap
import unittest
import zlib
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
        self.rules_json = self.tmpdir / "NLD-rules.json"
        self.diff_file = self.tmpdir / "delta.osc"
        self._create_fixture_db(self.base_db)
        self.rules_json.write_text(
            json.dumps(
                {
                    "format": "youspeed.penalty.rules",
                    "schema_version": 1,
                    "country_code": "NLD",
                    "country_name": "Netherlands",
                    "currency_code": "EUR",
                    "bands": [],
                }
            ),
            encoding="utf-8",
        )
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
                  way_id INTEGER PRIMARY KEY,
                  highway TEXT,
                  street_name TEXT,
                  ref TEXT,
                  maxspeed TEXT,
                  maxspeed_type TEXT,
                  source_maxspeed TEXT,
                  zone_maxspeed TEXT,
                  traffic_sign TEXT,
                  approx_heading_deg REAL,
                  service TEXT,
                  tunnel TEXT,
                  min_lon REAL NOT NULL,
                  min_lat REAL NOT NULL,
                  max_lon REAL NOT NULL,
                  max_lat REAL NOT NULL
                );
                CREATE VIRTUAL TABLE ways_rtree USING rtree(
                  way_id,
                  min_lon, max_lon,
                  min_lat, max_lat
                );
                CREATE TABLE way_geom (
                  way_id INTEGER PRIMARY KEY,
                  points_json TEXT NOT NULL
                );

                CREATE TABLE areas (
                  row_id INTEGER PRIMARY KEY,
                  area_id TEXT NOT NULL UNIQUE,
                  geometry_type TEXT,
                  name TEXT,
                  place TEXT,
                  boundary TEXT,
                  admin_level TEXT,
                  residential TEXT,
                  points_json TEXT,
                  min_lon REAL NOT NULL,
                  min_lat REAL NOT NULL,
                  max_lon REAL NOT NULL,
                  max_lat REAL NOT NULL
                );

                CREATE VIRTUAL TABLE areas_rtree USING rtree(
                  row_id,
                  min_lon, max_lon,
                  min_lat, max_lat
                );

                INSERT INTO ways(way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed, zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel, min_lon, min_lat, max_lon, max_lat)
                VALUES
                  (100, 'residential', 'Fixture Street', 'L 605', '50', NULL, NULL, NULL, NULL, 90.0, 'main', NULL, 13.0000, 52.0000, 13.0010, 52.0010),
                  (300, 'service', 'Fixture Service Road', 'K 1', '20', NULL, NULL, NULL, NULL, 0.0, 'service', NULL, 13.0100, 52.0100, 13.0110, 52.0110);

                INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
                VALUES
                  (100, 13.0000, 13.0010, 52.0000, 52.0010),
                  (300, 13.0100, 13.0110, 52.0100, 52.0110);

                INSERT INTO way_geom(way_id, points_json)
                VALUES
                  (100, '[[52.0000,13.0000],[52.0010,13.0010]]'),
                  (300, '[[52.0100,13.0100],[52.0110,13.0110]]');

                INSERT INTO areas(row_id, area_id, geometry_type, name, place, boundary, admin_level, residential, points_json, min_lon, min_lat, max_lon, max_lat)
                VALUES
                  (1, 'a:1', 'Polygon', 'Fixture City', 'city', NULL, '8', NULL, '[[13.0000,52.0000],[13.0020,52.0000],[13.0020,52.0020],[13.0000,52.0020],[13.0000,52.0000]]', 13.0000, 52.0000, 13.0020, 52.0020),
                  (2, 'a:2', 'Polygon', NULL, NULL, NULL, NULL, 'landuse', '[[13.0100,52.0100],[13.0110,52.0100],[13.0110,52.0110],[13.0100,52.0110],[13.0100,52.0100]]', 13.0100, 52.0100, 13.0110, 52.0110);

                INSERT INTO areas_rtree(row_id, min_lon, max_lon, min_lat, max_lat)
                VALUES
                  (1, 13.0000, 13.0020, 52.0000, 52.0020),
                  (2, 13.0100, 13.0110, 52.0100, 52.0110);
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

        patch_path = out_dir / "v3_patch.sql.zlib"
        manifest_path = out_dir / "v3_delta_manifest.json"
        self.assertTrue(patch_path.exists())
        self.assertTrue(manifest_path.exists())

        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["format"], "youspeed.v3.delta.manifest")
        self.assertEqual(manifest["from_bundle_version"], "2026-02-23")
        self.assertEqual(manifest["to_bundle_version"], "2026-02-24")
        self.assertEqual(manifest["patch"]["compression"], "zlib")
        self.assertIn("github.com/volzinnovation/youspeed.de/releases/download/v3-data-2026-02-24", manifest["patch"]["url"])
        self.assertGreater(manifest["stats"]["delete_way_count"], 0)
        self.assertGreater(manifest["stats"]["insert_way_count"], 0)

        # Apply patch and verify changed data.
        db_copy = self.tmpdir / "applied.sqlite"
        db_copy.write_bytes(self.base_db.read_bytes())
        patch_sql = zlib.decompress(patch_path.read_bytes()).decode("utf-8")
        with sqlite3.connect(db_copy) as conn:
            conn.executescript(patch_sql)
            rows = conn.execute("SELECT way_id, maxspeed, street_name, ref FROM ways ORDER BY way_id").fetchall()
            row_map = {r[0]: {"maxspeed": r[1], "street_name": r[2], "ref": r[3]} for r in rows}
            self.assertEqual(row_map.get(100, {}).get("maxspeed"), "30")
            self.assertEqual(row_map.get(100, {}).get("street_name"), "Updated Fixture Street")
            self.assertEqual(row_map.get(100, {}).get("ref"), "B 3")
            self.assertEqual(row_map.get(200, {}).get("maxspeed"), "20")
            self.assertEqual(row_map.get(200, {}).get("ref"), "K 2")
            self.assertNotIn(300, row_map)

    def test_build_v3_delta_pack_exact_target_db_no_drift(self):
        target_db = self.tmpdir / "target.sqlite"
        target_db.write_bytes(self.base_db.read_bytes())

        with sqlite3.connect(target_db) as conn:
            conn.executescript(
                """
                UPDATE ways
                SET maxspeed='40', street_name='Exact Updated Street', ref='B 7'
                WHERE way_id=100;

                DELETE FROM way_geom WHERE way_id=300;
                DELETE FROM ways_rtree WHERE way_id=300;
                DELETE FROM ways WHERE way_id=300;

                INSERT INTO ways(
                  way_id, highway, street_name, ref, maxspeed, maxspeed_type, source_maxspeed,
                  zone_maxspeed, traffic_sign, approx_heading_deg, service, tunnel,
                  min_lon, min_lat, max_lon, max_lat
                ) VALUES(
                  400, 'secondary', 'Target Added Road', 'L 9', '70', NULL, NULL,
                  NULL, NULL, 45.0, NULL, 'yes',
                  13.2000, 52.2000, 13.2010, 52.2010
                );
                INSERT INTO ways_rtree(way_id, min_lon, max_lon, min_lat, max_lat)
                VALUES(400, 13.2000, 13.2010, 52.2000, 52.2010);
                INSERT INTO way_geom(way_id, points_json)
                VALUES(400, '[[52.2000,13.2000],[52.2010,13.2010]]');

                UPDATE areas
                SET points_json='[[13.0000,52.0000],[13.0030,52.0000],[13.0030,52.0030],[13.0000,52.0030],[13.0000,52.0000]]',
                    max_lon=13.0030,
                    max_lat=52.0030
                WHERE area_id='a:1';
                DELETE FROM areas_rtree WHERE row_id=2;
                DELETE FROM areas WHERE area_id='a:2';
                INSERT INTO areas(
                  row_id, area_id, geometry_type, name, place, boundary, admin_level, residential,
                  points_json, min_lon, min_lat, max_lon, max_lat
                ) VALUES(
                  3, 'a:3', 'Polygon', NULL, NULL, NULL, NULL, 'landuse',
                  '[[13.3000,52.3000],[13.3010,52.3000],[13.3010,52.3010],[13.3000,52.3010],[13.3000,52.3000]]',
                  13.3000, 52.3000, 13.3010, 52.3010
                );
                INSERT INTO areas_rtree(row_id, min_lon, max_lon, min_lat, max_lat)
                VALUES(3, 13.3000, 13.3010, 52.3000, 52.3010);
                """
            )
            conn.commit()

        out_dir = self.tmpdir / "delta_pack_exact"
        run_cmd(
            [
                sys.executable,
                str(BUILD_V3_DELTA),
                "--base-db",
                str(self.base_db),
                "--target-db",
                str(target_db),
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
                "--validate-on-copy",
            ]
        )

        patch_path = out_dir / "v3_patch.sql.zlib"
        patch_sql = zlib.decompress(patch_path.read_bytes()).decode("utf-8")

        db_copy = self.tmpdir / "applied_exact.sqlite"
        db_copy.write_bytes(self.base_db.read_bytes())
        with sqlite3.connect(db_copy) as conn:
            conn.executescript(patch_sql)
            conn.execute("PRAGMA quick_check")

        with sqlite3.connect(":memory:") as conn:
            conn.execute("ATTACH DATABASE ? AS applied", (str(db_copy),))
            conn.execute("ATTACH DATABASE ? AS target", (str(target_db),))

            way_extra = conn.execute(
                "SELECT COUNT(*) FROM applied.ways aw LEFT JOIN target.ways tw USING(way_id) WHERE tw.way_id IS NULL"
            ).fetchone()[0]
            way_missing = conn.execute(
                "SELECT COUNT(*) FROM target.ways tw LEFT JOIN applied.ways aw USING(way_id) WHERE aw.way_id IS NULL"
            ).fetchone()[0]
            way_attr_diff = conn.execute(
                """
                SELECT COUNT(*)
                FROM applied.ways aw JOIN target.ways tw USING(way_id)
                WHERE
                  COALESCE(aw.highway,'') != COALESCE(tw.highway,'') OR
                  COALESCE(aw.street_name,'') != COALESCE(tw.street_name,'') OR
                  COALESCE(aw.ref,'') != COALESCE(tw.ref,'') OR
                  COALESCE(aw.maxspeed,'') != COALESCE(tw.maxspeed,'') OR
                  COALESCE(aw.maxspeed_type,'') != COALESCE(tw.maxspeed_type,'') OR
                  COALESCE(aw.source_maxspeed,'') != COALESCE(tw.source_maxspeed,'') OR
                  COALESCE(aw.service,'') != COALESCE(tw.service,'') OR
                  COALESCE(aw.tunnel,'') != COALESCE(tw.tunnel,'') OR
                  ABS(aw.min_lon - tw.min_lon) > 1e-12 OR
                  ABS(aw.min_lat - tw.min_lat) > 1e-12 OR
                  ABS(aw.max_lon - tw.max_lon) > 1e-12 OR
                  ABS(aw.max_lat - tw.max_lat) > 1e-12
                """
            ).fetchone()[0]
            geom_diff = conn.execute(
                """
                SELECT COUNT(*)
                FROM applied.way_geom ag JOIN target.way_geom tg USING(way_id)
                WHERE COALESCE(ag.points_json,'') != COALESCE(tg.points_json,'')
                """
            ).fetchone()[0]

            self.assertEqual(way_extra, 0)
            self.assertEqual(way_missing, 0)
            self.assertEqual(way_attr_diff, 0)
            self.assertEqual(geom_diff, 0)

            area_extra = conn.execute(
                "SELECT COUNT(*) FROM applied.areas aa LEFT JOIN target.areas ta ON aa.area_id=ta.area_id WHERE ta.area_id IS NULL"
            ).fetchone()[0]
            area_missing = conn.execute(
                "SELECT COUNT(*) FROM target.areas ta LEFT JOIN applied.areas aa ON ta.area_id=aa.area_id WHERE aa.area_id IS NULL"
            ).fetchone()[0]
            area_attr_diff = conn.execute(
                """
                SELECT COUNT(*)
                FROM applied.areas aa JOIN target.areas ta ON aa.area_id=ta.area_id
                WHERE
                  COALESCE(aa.geometry_type,'') != COALESCE(ta.geometry_type,'') OR
                  COALESCE(aa.name,'') != COALESCE(ta.name,'') OR
                  COALESCE(aa.place,'') != COALESCE(ta.place,'') OR
                  COALESCE(aa.boundary,'') != COALESCE(ta.boundary,'') OR
                  COALESCE(aa.admin_level,'') != COALESCE(ta.admin_level,'') OR
                  COALESCE(aa.residential,'') != COALESCE(ta.residential,'') OR
                  COALESCE(aa.points_json,'') != COALESCE(ta.points_json,'') OR
                  ABS(aa.min_lon - ta.min_lon) > 1e-12 OR
                  ABS(aa.min_lat - ta.min_lat) > 1e-12 OR
                  ABS(aa.max_lon - ta.max_lon) > 1e-12 OR
                  ABS(aa.max_lat - ta.max_lat) > 1e-12
                """
            ).fetchone()[0]

            self.assertEqual(area_extra, 0)
            self.assertEqual(area_missing, 0)
            self.assertEqual(area_attr_diff, 0)

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
                "--country-code",
                "NLD",
                "--penalty-rules",
                str(self.rules_json),
            ]
        )
        manifest_path = self.tmpdir / "bundles" / "germany" / "2026-02-24" / "germany_manifest.json"
        self.assertTrue(manifest_path.exists())
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(manifest["format"], "youspeed.v3.bundle.manifest")
        self.assertEqual(manifest["variant"], "v3")
        self.assertEqual(manifest["country_code"], "NLD")
        self.assertEqual(manifest["db"]["file"], "germany_speeds.sqlite")
        self.assertIn("github.com/volzinnovation/youspeed.de/releases/download/v3-data-2026-02-24", manifest["db"]["url"])
        self.assertIn("germany_delta_index.json", manifest["delta_index"]["file"])
        self.assertEqual(manifest["penalty_rules"]["file"], "NLD-rules.json")
        self.assertIn(
            "github.com/volzinnovation/youspeed.de/releases/download/v3-data-2026-02-24",
            manifest["penalty_rules"]["url"],
        )

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
        manifest_path = out_root / "germany" / "latest" / "germany_manifest.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(payload["bundle_version"], "2026-02-24")
        self.assertEqual(payload["db"]["file"], "germany_speeds.sqlite")

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
        manifest_path = bundle_dir / "germany_manifest.json"
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertIn("db_parts", payload)
        self.assertGreater(len(payload["db_parts"]), 1)
        self.assertIsNone(payload["db"]["url"])
        self.assertEqual(payload["db"]["bytes"], self.base_db.stat().st_size)

        part_files = sorted(bundle_dir.glob("germany_speeds.sqlite.part*"))
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
