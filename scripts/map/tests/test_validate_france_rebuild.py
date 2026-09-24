import importlib.util
from pathlib import Path
import sqlite3

import pytest


spec = importlib.util.spec_from_file_location(
    "validate_france_rebuild", Path(__file__).resolve().parents[1] / "validate_france_rebuild.py"
)
validator = importlib.util.module_from_spec(spec)
spec.loader.exec_module(validator)


@pytest.fixture
def database(tmp_path):
    path = tmp_path / "bundle.sqlite"
    with sqlite3.connect(path) as db:
        db.execute("CREATE TABLE metadata(key TEXT PRIMARY KEY, value TEXT)")
        db.executemany("INSERT INTO metadata VALUES (?, ?)", [
            ("road_geometry_policy", "source_vertices_v1"),
            ("settlement_country_code", "FR"),
            ("settlement_context_version", "test"),
        ])
        for table in ("ways", "ways_rtree", "way_geom", "way_endpoints", "way_links", "settlement_segment"):
            db.execute(f"CREATE TABLE {table}(way_id INTEGER)")
            db.execute(f"INSERT INTO {table} VALUES (1)")
    return path


def test_complete_french_database(database):
    report = validator.validate_database(database)
    assert report["integrity"] == "ok"
    assert report["row_counts"]["ways"] == 1


@pytest.mark.parametrize("key,value", [
    ("road_geometry_policy", "legacy_or_mixed"),
    ("settlement_country_code", "DE"),
    ("settlement_context_version", ""),
])
def test_rejects_incompatible_metadata(database, key, value):
    with sqlite3.connect(database) as db:
        db.execute("UPDATE metadata SET value=? WHERE key=?", (value, key))
    with pytest.raises(ValueError):
        validator.validate_database(database)


@pytest.mark.parametrize("table", ["ways", "ways_rtree", "way_geom", "way_endpoints"])
def test_rejects_missing_road_data(database, table):
    with sqlite3.connect(database) as db:
        db.execute(f"DELETE FROM {table}")
    with pytest.raises(ValueError, match="Missing road geometry"):
        validator.validate_database(database)
