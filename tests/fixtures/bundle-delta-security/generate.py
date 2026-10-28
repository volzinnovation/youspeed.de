"""Rebuild the synthetic fixture using host SQLite with RTREE enabled."""
from pathlib import Path
import sqlite3


def generate():
    directory = Path(__file__).resolve().parent
    temporary = directory / "source.sqlite.tmp"
    temporary.unlink(missing_ok=True)
    database = sqlite3.connect(temporary)
    try:
        database.executescript((directory / "source.sql").read_text())
        database.commit()
        assert database.execute("PRAGMA quick_check").fetchall() == [("ok",)]
    finally:
        database.close()
    temporary.replace(directory / "source.sqlite")


if __name__ == "__main__":
    generate()
