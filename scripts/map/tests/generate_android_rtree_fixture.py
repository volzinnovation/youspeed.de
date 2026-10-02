#!/usr/bin/env python3
"""Rebuild the tiny native SQLite R-tree fixture; requires host SQLite R-tree support.

Android instrumentation copies these exact bytes, including real virtual tables,
to check lookup on devices whose system SQLite cannot load the R-tree module.
"""
from pathlib import Path
import sqlite3


def main() -> None:
    root = Path(__file__).resolve().parents[3]
    target = root / "android/app/src/androidTest/assets/matcher/candidate-admission-native-rtree-v1.sqlite"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.unlink(missing_ok=True)
    with sqlite3.connect(target) as db:
        db.executescript((root / "shared/matcher/candidate-admission-v1.sql").read_text())
        for table in ("ways_rtree", "surface_way_network_rtree"):
            db.execute(f"CREATE VIRTUAL TABLE {table} USING rtree(way_id,min_lon,max_lon,min_lat,max_lat)")
            db.execute(f"INSERT INTO {table} SELECT way_id,min_lon,max_lon,min_lat,max_lat FROM ways")
        db.commit()
        assert db.execute("PRAGMA integrity_check").fetchone() == ("ok",)
    print(f"Created {target} ({target.stat().st_size} bytes; SQLite {sqlite3.sqlite_version})")


if __name__ == "__main__":
    main()
