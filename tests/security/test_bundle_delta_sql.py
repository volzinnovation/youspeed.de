"""Run the shared delta executor against system and Android-vendored SQLite.

Set TMPDIR to retain all native build/test artifacts in a chosen evidence root.
No network, app installation, or private device data is used.
"""
import ctypes
import importlib
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class BundleDeltaSQLTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.build = tempfile.TemporaryDirectory(prefix="bundle-delta-engines-")
        build = Path(cls.build.name)
        bridge = build / "delta.cpp"
        bridge.write_text('#define YSP_BUNDLE_DELTA_SQL_IMPLEMENTATION\n#include "bundle_delta_sql.h"\n')
        common = ["-std=c++17", "-fPIC", "-I", str(ROOT / "shared/runtime-storage-prototype")]
        cls.engines = {}
        for engine in ("system", "android-vendored"):
            output = build / (engine + ".dylib")
            objects = ["-lsqlite3"]
            if engine == "android-vendored":
                vendor = ROOT / "android/app/src/main/cpp/vendor/sqlite"
                obj = build / "sqlite3.o"
                subprocess.run(["clang", "-fPIC", "-DSQLITE_ENABLE_RTREE=1", "-DSQLITE_OMIT_LOAD_EXTENSION=1",
                    "-c", str(vendor / "sqlite3.c"), "-o", str(obj)], check=True)
                objects = [str(obj)]
                includes = ["-I", str(vendor)]
            else:
                includes = []
            subprocess.run(["clang++", *common, *includes, "-shared", str(bridge), *objects, "-o", str(output)], check=True)
            library = ctypes.CDLL(str(output))
            execute = library.ysp_apply_bundle_delta
            execute.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_size_t, ctypes.c_char_p, ctypes.c_size_t]
            execute.restype = ctypes.c_int
            cls.engines[engine] = (library, execute)
        sys.path.insert(0, str(ROOT / "scripts/map"))
        cls.generator = importlib.import_module("build_v3_delta_pack")
        cls.context = importlib.import_module("v3_context_delta")

    @classmethod
    def tearDownClass(cls):
        cls.build.cleanup()

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="bundle-delta-fixture-")
        self.directory = Path(self.temporary.name)
        self.base = self.directory / "active.sqlite"
        with sqlite3.connect(self.base) as db:
            columns = ",".join('"' + name + '" TEXT' for name in self.generator.WAY_COLS)
            db.executescript(f"CREATE TABLE ways({columns}); CREATE TABLE way_geom(way_id TEXT,points_json TEXT);")
            for name in ("ways_rtree", "city_boundary_rtree", "surface_way_network_rtree"):
                key = "row_id" if name == "city_boundary_rtree" else "way_id"
                db.execute(f"CREATE VIRTUAL TABLE {name} USING rtree({key},min_lon,max_lon,min_lat,max_lat)")
            db.executescript("""CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
                INSERT INTO metadata VALUES('schema_version','3');
                CREATE TABLE city_boundary(row_id INTEGER PRIMARY KEY,label TEXT);
                CREATE TABLE settlement_segment(segment_id TEXT PRIMARY KEY,evidence TEXT);
                CREATE TABLE events(value TEXT); INSERT INTO events VALUES('private sentinel');""")
            db.execute("INSERT INTO ways(way_id,street_name,maxspeed) VALUES('1','Before','50')")
            db.execute("INSERT INTO ways_rtree VALUES(1,8,8.1,48,48.1)")
        self.journal = self.directory / "journal.sqlite"
        with sqlite3.connect(self.journal) as db:
            db.executescript("CREATE TABLE events(value TEXT); INSERT INTO events VALUES('private sentinel')")

    def tearDown(self):
        self.temporary.cleanup()

    def apply(self, engine, sql, path=None):
        if path is None:
            path = self.directory / (engine + "-staged.sqlite")
            shutil.copyfile(self.base, path)
        raw = sql.encode("utf-8")
        error = ctypes.create_string_buffer(1024)
        code = self.engines[engine][1](os.fsencode(path), raw, len(raw), error, len(error))
        return code, error.value.decode("utf-8"), path

    def test_real_generator_patch_updates_maps_context_metadata_and_rtrees(self):
        target = self.directory / "target.sqlite"
        shutil.copyfile(self.base, target)
        with sqlite3.connect(target) as db:
            db.execute("INSERT INTO city_boundary VALUES(7,'Town')")
            db.execute("INSERT INTO city_boundary_rtree VALUES(7,8,8.1,48,48.1)")
            db.execute("INSERT INTO surface_way_network_rtree VALUES(1,8,8.1,48,48.1)")
            db.execute("INSERT INTO settlement_segment VALUES('segment-7','Église; quoted '' evidence')")
            db.execute("INSERT OR REPLACE INTO metadata VALUES('city_count','1')")
        context, _ = self.context.build_context_delta(self.base, target)
        insert = dict(way_id="1", street_name="Rue de l'Église; south", maxspeed="30", min_lon=8,
            max_lon=8.1, min_lat=48, max_lat=48.1, points_json="[[48,8],[48.1,8.1]]")
        sql = self.generator._build_sql_patch(["1"], [insert], [], [], [], [], from_version="2026-09-01",
            to_version="2026-09-02", diff_file=Path("synthetic.osc"), generation_mode="exact",
            context_statements=context)
        for engine in self.engines:
            with self.subTest(engine=engine):
                code, error, result = self.apply(engine, sql)
                self.assertEqual(code, 0, error)
                with sqlite3.connect(result) as db:
                    self.assertEqual(db.execute("SELECT street_name,maxspeed FROM ways").fetchone(), (insert["street_name"], "30"))
                    self.assertEqual(db.execute("SELECT count(*) FROM ways_rtree").fetchone()[0], 1)
                    self.assertEqual(db.execute("SELECT label FROM city_boundary").fetchone()[0], "Town")
                    self.assertEqual(db.execute("SELECT value FROM metadata WHERE key='city_count'").fetchone()[0], "1")
                    self.assertEqual(db.execute("PRAGMA quick_check").fetchall(), [("ok",)])
                wal = Path(str(result) + "-wal")
                self.assertFalse(wal.exists() and wal.stat().st_size > 0)

    def test_engine_rejects_private_database_access_and_other_capabilities(self):
        quoted = str(self.journal).replace("'", "''")
        export = self.directory / "export.sqlite"
        attacks = [
            f"/* comment */ ATTACH DATABASE '{quoted}' AS private; DELETE FROM private.events;",
            f"VACUUM INTO '{export}';",
            "PRAGMA writable_schema=ON;", "PRAGMA journal_mode=OFF;", "PRAGMA foreign_keys=ON;",
            "PRAGMA temp_store_directory='/tmp';", "CREATE TABLE escaped(value);",
            "CREATE TEMP TABLE escaped(value);", "CREATE VIEW escaped AS SELECT * FROM ways;",
            "CREATE TRIGGER escaped AFTER DELETE ON ways BEGIN DELETE FROM events; END;",
            "CREATE VIRTUAL TABLE escaped USING rtree(id,x0,x1);", "DROP TABLE ways;",
            "ALTER TABLE ways ADD COLUMN escaped;", "DELETE FROM events;",
            "UPDATE sqlite_master SET sql='';", "SELECT abs(-1);",
            "SELECT load_extension('escaped');", "SELECT * FROM pragma_database_list();",
            "SELECT 1;\0DELETE FROM ways;",
        ]
        before = self.journal.read_bytes()
        for engine in self.engines:
            for attack in attacks:
                with self.subTest(engine=engine, attack=attack):
                    code, error, _ = self.apply(engine, attack)
                    self.assertNotEqual(code, 0, (attack, error))
                    self.assertEqual(self.journal.read_bytes(), before)
                    self.assertFalse(export.exists())
        with sqlite3.connect(self.base) as db:
            self.assertEqual(db.execute("SELECT street_name FROM ways").fetchone()[0], "Before")

    def test_existing_trigger_view_or_unapproved_virtual_module_is_rejected(self):
        schemas = [
            ("CREATE TRIGGER hidden AFTER UPDATE ON ways BEGIN DELETE FROM events; END;", "UPDATE ways SET maxspeed='30';"),
            ("DROP TABLE way_geom; CREATE VIEW way_geom AS SELECT * FROM events;", "SELECT * FROM way_geom;"),
            ("DROP TABLE metadata; CREATE VIRTUAL TABLE metadata USING rtree(id,x0,x1);", "DELETE FROM metadata;"),
        ]
        for index, (schema, patch) in enumerate(schemas):
            fixture = self.directory / f"schema-{index}.sqlite"
            shutil.copyfile(self.base, fixture)
            with sqlite3.connect(fixture) as db:
                db.executescript(schema)
            for engine in self.engines:
                with self.subTest(engine=engine, schema=schema):
                    code, _, _ = self.apply(engine, "BEGIN; " + patch + " COMMIT;", fixture)
                    self.assertNotEqual(code, 0)
                    with sqlite3.connect(fixture) as db:
                        self.assertEqual(db.execute("SELECT value FROM events").fetchall(), [("private sentinel",)])

    def test_unfinished_transaction_rolls_back_and_wal_is_checkpointed(self):
        for engine in self.engines:
            with self.subTest(engine=engine):
                code, _, result = self.apply(engine, "BEGIN; UPDATE ways SET maxspeed='30';")
                self.assertNotEqual(code, 0)
                with sqlite3.connect(result) as db:
                    self.assertEqual(db.execute("SELECT maxspeed FROM ways").fetchone()[0], "50")
                    db.execute("PRAGMA journal_mode=WAL")
                code, error, _ = self.apply(engine, "BEGIN; UPDATE ways SET maxspeed='30'; COMMIT;", result)
                self.assertEqual(code, 0, error)
                wal = Path(str(result) + "-wal")
                self.assertFalse(wal.exists() and wal.stat().st_size > 0)

    def test_android_packaged_fixture_is_real_rtree_and_exercises_both_native_engines(self):
        fixture = ROOT / "tests/fixtures/bundle-delta-security/source.sqlite"
        with sqlite3.connect(fixture) as db:
            self.assertIn("USING rtree", db.execute("SELECT sql FROM sqlite_master WHERE name='ways_rtree'").fetchone()[0])
            self.assertEqual(db.execute("SELECT way_id,street_name,maxspeed FROM ways").fetchall(), [(1, "Before", "50")])
            self.assertEqual(db.execute("PRAGMA quick_check").fetchall(), [("ok",)])
        for engine in self.engines:
            with self.subTest(engine=engine):
                staged = self.directory / (engine + "-android-asset.sqlite")
                shutil.copyfile(fixture, staged)
                code, error, _ = self.apply(engine, "PRAGMA foreign_keys=OFF; BEGIN IMMEDIATE; "
                    "UPDATE ways SET maxspeed='30'; DELETE FROM ways_rtree WHERE way_id=1; "
                    "INSERT INTO ways_rtree VALUES(1,8,8.1,48,48.1); COMMIT;", staged)
                self.assertEqual(code, 0, error)
                with sqlite3.connect(staged) as db:
                    self.assertEqual(db.execute("SELECT maxspeed FROM ways").fetchone()[0], "30")
                    self.assertEqual(db.execute("SELECT count(*) FROM ways_rtree").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
