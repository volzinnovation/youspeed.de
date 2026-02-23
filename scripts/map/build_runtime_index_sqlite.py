#!/usr/bin/env python3
"""Build SQLite runtime index from JSON artifacts for fast per-query lookup."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import tempfile
from pathlib import Path
from typing import Dict, Iterable, Iterator, Tuple


def _load_json(path: Path) -> dict:
    with path.open("r", encoding="utf-8") as f:
        payload = json.load(f)
    if not isinstance(payload, dict):
        raise ValueError(f"{path} must be a JSON object")
    return payload


def _iter_way_cells(cells: Dict[str, list]) -> Iterator[Tuple[str, str]]:
    for cell in sorted(cells.keys()):
        way_ids = cells[cell]
        if not isinstance(way_ids, list):
            continue
        for way_id in way_ids:
            if isinstance(way_id, str):
                yield (cell, way_id)


def _iter_area_cells(cells: Dict[str, list]) -> Iterator[Tuple[str, str]]:
    for cell in sorted(cells.keys()):
        area_ids = cells[cell]
        if not isinstance(area_ids, list):
            continue
        for area_id in area_ids:
            if isinstance(area_id, str):
                yield (cell, area_id)


def _iter_way_offsets(meta_offsets: Dict[str, int], geom_offsets: Dict[str, int]) -> Iterator[Tuple[str, int, int | None]]:
    for way_id in sorted(meta_offsets.keys()):
        raw_meta_offset = meta_offsets[way_id]
        if not isinstance(raw_meta_offset, int):
            continue
        raw_geom_offset = geom_offsets.get(way_id)
        geom_offset = raw_geom_offset if isinstance(raw_geom_offset, int) else None
        yield (way_id, raw_meta_offset, geom_offset)


def _iter_areas(rows: Iterable[dict]) -> Iterator[Tuple[str, float, float, float, float, str | None, str | None, str | None, str | None, str | None]]:
    for row in rows:
        area_id = row.get("area_id")
        if not isinstance(area_id, str):
            continue
        yield (
            area_id,
            float(row.get("min_lon", 0.0)),
            float(row.get("min_lat", 0.0)),
            float(row.get("max_lon", 0.0)),
            float(row.get("max_lat", 0.0)),
            row.get("place"),
            row.get("boundary"),
            row.get("admin_level"),
            row.get("geometry_type"),
            row.get("name"),
        )


def _batched(iterable, batch_size: int):
    batch = []
    for item in iterable:
        batch.append(item)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def _build_db(
    ways_idx_payload: dict,
    areas_idx_payload: dict,
    ways_lookup_payload: dict,
    ways_geom_lookup_payload: dict,
    out_db: Path,
) -> None:
    out_db.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(prefix="runtime_idx_", suffix=".sqlite", delete=False, dir=str(out_db.parent)) as tmp:
        tmp_path = Path(tmp.name)

    try:
        conn = sqlite3.connect(str(tmp_path))
        try:
            conn.execute("PRAGMA journal_mode=OFF")
            conn.execute("PRAGMA synchronous=OFF")
            conn.execute("PRAGMA temp_store=MEMORY")

            conn.executescript(
                """
                CREATE TABLE metadata (
                  key TEXT PRIMARY KEY,
                  value TEXT NOT NULL
                );
                CREATE TABLE way_cell (
                  cell TEXT NOT NULL,
                  way_id TEXT NOT NULL
                );
                CREATE TABLE area_cell (
                  cell TEXT NOT NULL,
                  area_id TEXT NOT NULL
                );
                CREATE TABLE way_offset (
                  way_id TEXT PRIMARY KEY,
                  meta_offset INTEGER NOT NULL,
                  geom_offset INTEGER
                );
                CREATE TABLE area (
                  area_id TEXT PRIMARY KEY,
                  min_lon REAL NOT NULL,
                  min_lat REAL NOT NULL,
                  max_lon REAL NOT NULL,
                  max_lat REAL NOT NULL,
                  place TEXT,
                  boundary TEXT,
                  admin_level TEXT,
                  geometry_type TEXT,
                  name TEXT
                );
                """
            )

            metadata_rows = [
                ("schema_version", str(ways_idx_payload.get("schema_version", ""))),
                ("grid_scale", str(ways_idx_payload.get("grid_scale", ""))),
                ("ways_count", str(ways_idx_payload.get("ways_count", ""))),
                ("areas_count", str(areas_idx_payload.get("areas_count", ""))),
            ]
            conn.executemany("INSERT INTO metadata(key, value) VALUES(?, ?)", metadata_rows)

            ways_cells = ways_idx_payload.get("cells", {})
            if not isinstance(ways_cells, dict):
                raise ValueError("ways.idx cells must be object")
            for batch in _batched(_iter_way_cells(ways_cells), 20000):
                conn.executemany("INSERT INTO way_cell(cell, way_id) VALUES(?, ?)", batch)

            areas_cells = areas_idx_payload.get("cells", {})
            if not isinstance(areas_cells, dict):
                raise ValueError("areas.idx cells must be object")
            for batch in _batched(_iter_area_cells(areas_cells), 20000):
                conn.executemany("INSERT INTO area_cell(cell, area_id) VALUES(?, ?)", batch)

            areas = areas_idx_payload.get("areas", [])
            if not isinstance(areas, list):
                raise ValueError("areas.idx areas must be array")
            for batch in _batched(_iter_areas(areas), 20000):
                conn.executemany(
                    """
                    INSERT INTO area(
                      area_id, min_lon, min_lat, max_lon, max_lat,
                      place, boundary, admin_level, geometry_type, name
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    batch,
                )

            meta_offsets = ways_lookup_payload.get("index", {})
            if not isinstance(meta_offsets, dict):
                raise ValueError("ways.lookup index must be object")
            geom_offsets = ways_geom_lookup_payload.get("index", {})
            if not isinstance(geom_offsets, dict):
                raise ValueError("ways.geom.lookup index must be object")
            for batch in _batched(_iter_way_offsets(meta_offsets, geom_offsets), 20000):
                conn.executemany(
                    "INSERT INTO way_offset(way_id, meta_offset, geom_offset) VALUES(?, ?, ?)",
                    batch,
                )

            conn.executescript(
                """
                CREATE INDEX idx_way_cell_cell ON way_cell(cell);
                CREATE INDEX idx_area_cell_cell ON area_cell(cell);
                """
            )

            conn.commit()
        finally:
            conn.close()

        os.replace(tmp_path, out_db)
    except Exception:
        if tmp_path.exists():
            tmp_path.unlink()
        raise


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build runtime.idx.sqlite from JSON artifacts")
    parser.add_argument("ways_idx", help="Path to ways.idx")
    parser.add_argument("areas_idx", help="Path to areas.idx")
    parser.add_argument("ways_lookup", help="Path to ways.lookup")
    parser.add_argument("ways_geom_lookup", help="Path to ways.geom.lookup")
    parser.add_argument("out_db", help="Path to output runtime.idx.sqlite")
    return parser.parse_args()


def main() -> int:
    args = parse_args()

    ways_idx_payload = _load_json(Path(args.ways_idx))
    areas_idx_payload = _load_json(Path(args.areas_idx))
    ways_lookup_payload = _load_json(Path(args.ways_lookup))
    ways_geom_lookup_payload = _load_json(Path(args.ways_geom_lookup))

    _build_db(
        ways_idx_payload=ways_idx_payload,
        areas_idx_payload=areas_idx_payload,
        ways_lookup_payload=ways_lookup_payload,
        ways_geom_lookup_payload=ways_geom_lookup_payload,
        out_db=Path(args.out_db),
    )
    print(f"Wrote runtime SQLite index: {args.out_db}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
