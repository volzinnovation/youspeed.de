#!/usr/bin/env python3
import json
import math
import pathlib
import sqlite3
import sys
import zlib


SQLITE_MAGIC = b"SQLite format 3\x00"


def _coord_key(lon: float, lat: float) -> str:
    return f"{round(lon * 10_000_000)}:{round(lat * 10_000_000)}"


def _haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    earth_radius_m = 6_371_000.0
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    return earth_radius_m * (2.0 * math.atan2(math.sqrt(a), math.sqrt(max(0.0, 1.0 - a))))


def _points_length_m(points: list[tuple[float, float]]) -> float:
    total = 0.0
    for (lat1, lon1), (lat2, lon2) in zip(points, points[1:]):
        total += _haversine_m(lat1, lon1, lat2, lon2)
    return total


def _table_exists(conn: sqlite3.Connection, name: str) -> bool:
    row = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=? LIMIT 1",
        (name,),
    ).fetchone()
    return row is not None


def _ensure_way_endpoints(path: pathlib.Path) -> None:
    conn = sqlite3.connect(path)
    try:
        if _table_exists(conn, "way_endpoints"):
            return
        if not _table_exists(conn, "ways") or not _table_exists(conn, "way_geom"):
            return

        conn.executescript(
            """
            CREATE TABLE way_endpoints (
              way_id INTEGER PRIMARY KEY,
              ref_norm TEXT,
              highway TEXT,
              tunnel_flag INTEGER NOT NULL DEFAULT 0,
              start_node_key TEXT NOT NULL,
              start_lon REAL NOT NULL,
              start_lat REAL NOT NULL,
              end_node_key TEXT NOT NULL,
              end_lon REAL NOT NULL,
              end_lat REAL NOT NULL,
              way_length_m REAL NOT NULL
            );

            CREATE INDEX idx_way_endpoints_start_node_key ON way_endpoints(start_node_key);
            CREATE INDEX idx_way_endpoints_end_node_key ON way_endpoints(end_node_key);
            """
        )

        rows = conn.execute(
            """
            SELECT w.way_id, w.ref, w.highway, w.tunnel, g.points_json
            FROM ways w
            JOIN way_geom g ON g.way_id = w.way_id
            """
        )
        batch: list[tuple[object, str, object, int, str, float, float, str, float, float, float]] = []
        for way_id, ref_value, highway, tunnel, points_raw in rows:
            if not points_raw:
                continue
            try:
                parsed = json.loads(points_raw)
            except json.JSONDecodeError:
                continue
            if not isinstance(parsed, list) or len(parsed) < 2:
                continue

            points: list[tuple[float, float]] = []
            for point in parsed:
                if (
                    not isinstance(point, list)
                    or len(point) != 2
                    or not isinstance(point[0], (int, float))
                    or not isinstance(point[1], (int, float))
                ):
                    points = []
                    break
                points.append((float(point[0]), float(point[1])))
            if len(points) < 2:
                continue

            start_lat, start_lon = points[0]
            end_lat, end_lon = points[-1]
            ref_norm = (ref_value or "").replace(" ", "").upper()
            batch.append(
                (
                    way_id,
                    ref_norm,
                    highway,
                    1 if str(tunnel or "").strip().lower() in {"yes", "true", "1"} else 0,
                    _coord_key(start_lon, start_lat),
                    start_lon,
                    start_lat,
                    _coord_key(end_lon, end_lat),
                    end_lon,
                    end_lat,
                    _points_length_m(points),
                )
            )
            if len(batch) >= 5000:
                conn.executemany(
                    """
                    INSERT INTO way_endpoints(
                      way_id, ref_norm, highway, tunnel_flag,
                      start_node_key, start_lon, start_lat,
                      end_node_key, end_lon, end_lat, way_length_m
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    batch,
                )
                conn.commit()
                batch.clear()

        if batch:
            conn.executemany(
                """
                INSERT INTO way_endpoints(
                  way_id, ref_norm, highway, tunnel_flag,
                  start_node_key, start_lon, start_lat,
                  end_node_key, end_lon, end_lat, way_length_m
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                batch,
            )
        try:
            count = conn.execute("SELECT COUNT(*) FROM way_endpoints").fetchone()[0]
            conn.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)",
                ("way_endpoints_count", str(count)),
            )
            conn.execute(
                "INSERT OR REPLACE INTO metadata(key, value) VALUES(?, ?)",
                ("way_endpoints_mode", "coord_key_length_v1"),
            )
        except sqlite3.DatabaseError:
            pass
        conn.commit()
    finally:
        conn.close()


def main() -> int:
    if len(sys.argv) != 3:
        raise SystemExit("usage: inflate_bundled_seed.py <input.zlib> <output.sqlite>")

    source = pathlib.Path(sys.argv[1])
    target = pathlib.Path(sys.argv[2])
    target.parent.mkdir(parents=True, exist_ok=True)

    if target.exists():
        try:
            if target.stat().st_mtime >= source.stat().st_mtime:
                with target.open("rb") as handle:
                    if handle.read(len(SQLITE_MAGIC)) == SQLITE_MAGIC:
                        _ensure_way_endpoints(target)
                        return 0
        except OSError:
            pass

    inflated = zlib.decompress(source.read_bytes())
    if not inflated.startswith(SQLITE_MAGIC):
        raise SystemExit("inflated seed does not start with SQLite header")

    tmp = target.with_suffix(f"{target.suffix}.tmp")
    tmp.write_bytes(inflated)
    tmp.replace(target)
    _ensure_way_endpoints(target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
