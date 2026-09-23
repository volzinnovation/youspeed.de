import json
from pathlib import Path
import sqlite3
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/map"))
from motorway_exit_context import build_motorway_exit_context


def test_directed_exit_lookahead_crosses_way_splits_but_excludes_entrances(tmp_path):
    conn = sqlite3.connect(":memory:")
    conn.executescript("""
      CREATE TABLE metadata(key TEXT PRIMARY KEY,value TEXT);
      CREATE TABLE way_endpoints(way_id INTEGER,highway TEXT,start_node_key TEXT,end_node_key TEXT,way_length_m REAL);
      CREATE TABLE way_geom(way_id INTEGER,points_json TEXT);
    """)
    # 1 -> 2 -> exit 3. Ramp 4 enters the motorway; 5 is nearby but disconnected.
    roads = [(1, "motorway", "a", "b", 100, "yes"),
             (2, "motorway", "b", "c", 120, "yes"),
             (3, "motorway_link", "c", "d", 150, "yes"),
             (4, "motorway_link", "e", "b", 90, "yes"),
             (5, "motorway_link", "f", "g", 70, "yes"),
             (6, "motorway", "c", "h", 400, "yes"),
             (7, "motorway_link", "h", "i", 70, "yes"),
             (8, "motorway_link", "j", "b", 70, "-1"),
             (9, "motorway_link", "b", "k", 70, "reversible")]
    meta = tmp_path / "ways.meta"
    meta.write_text("\n".join(json.dumps({"way_id": way, "highway": road, "raw_tags": {"oneway": direction}})
                              for way, road, _, _, _, direction in roads))
    conn.executemany("INSERT INTO way_endpoints VALUES(?,?,?,?,?)", [row[:5] for row in roads])
    conn.executemany("INSERT INTO way_geom VALUES(?,?)", [(row[0], "[[44,4],[44.001,4.001]]") for row in roads])
    build_motorway_exit_context(conn, meta)
    rows = conn.execute("SELECT exit_way_id,path_distance_m FROM motorway_exit_approach WHERE way_id=1 ORDER BY exit_way_id").fetchall()
    assert rows == [(3, 120.0), (8, 0.0)]
    assert conn.execute("SELECT COUNT(*) FROM motorway_exit_approach WHERE exit_way_id IN (4,5,9)").fetchone()[0] == 0
    # Rebuilding replaces, rather than duplicates, the deterministic index.
    before = list(conn.execute("SELECT * FROM motorway_exit_approach ORDER BY way_id,exit_way_id"))
    build_motorway_exit_context(conn, meta)
    assert list(conn.execute("SELECT * FROM motorway_exit_approach ORDER BY way_id,exit_way_id")) == before
