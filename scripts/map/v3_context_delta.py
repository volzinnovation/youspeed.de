"""Exact row deltas for settlement, geographic naming, and matcher tables.

Capability/schema transitions require a full bundle. Within one capability version,
all context tables and their metadata are compared, including geometry and indexes.
"""

from pathlib import Path
import sqlite3


CONTEXT_TABLE_KEYS = {
    "city_boundary": ("row_id",),
    "city_boundary_rtree": ("row_id",),
    "city_ring": ("boundary_row_id", "ring_index"),
    "city_tile": ("boundary_row_id", "tile_x", "tile_y"),
    "city_place": ("row_id",),
    "city_place_rtree": ("row_id",),
    "settlement_area": ("area_id",),
    "settlement_ring": ("area_id", "ring_index"),
    "settlement_sign": ("sign_id",),
    "settlement_segment": ("segment_id",),
}


# These are derived alongside ways. A geometry/tag change can affect neighbors,
# network membership, or complete corridors even when those ways stay unchanged.
# way_links has shipped with both minimal and detailed schemas; use its declared
# primary key, including shared_node_key when present.
MATCHER_TABLE_KEYS = {
    "way_links": None,
    "way_endpoints": ("way_id",),
    "way_tile": ("way_id", "tile_x", "tile_y"),
    "surface_way_network": ("way_id",),
    "surface_way_network_rtree": ("way_id",),
    "tunnel_way_network": ("way_id",),
    "tunnel_way_network_rtree": ("way_id",),
    "motorway_way_network": ("way_id",),
    "motorway_way_network_rtree": ("way_id",),
    "way_continuity_group": ("continuity_group_id",),
    "way_continuity_membership": ("way_id", "continuity_group_id"),
    "corridor_progress": ("corridor_kind", "corridor_id", "side_node_key", "way_id"),
    "corridor_pairs": ("corridor_kind", "corridor_id", "side_node_key", "paired_kind", "paired_corridor_id"),
}


def _identifier(value):
    return '"' + value.replace('"', '""') + '"'


def _literal(value):
    if value is None:
        return "NULL"
    if isinstance(value, float):
        # SQLite's decimal parser can move a float32 RTree bound by one double
        # ULP. Reinserting it then expands the RTree by a full float32 ULP.
        # A ratio of powers of two preserves the exact binary coordinate.
        numerator, denominator = value.as_integer_ratio()
        return f"({numerator}.0/{denominator}.0)"
    if isinstance(value, int):
        return repr(value)
    if isinstance(value, bytes):
        return "X'" + value.hex() + "'"
    return "'" + str(value).replace("'", "''") + "'"


def _exists(connection, alias, table):
    return connection.execute(
        f"SELECT 1 FROM {alias}.sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone() is not None


def context_metadata(connection, alias):
    if not _exists(connection, alias, "metadata"):
        return {}
    return dict(connection.execute(
        f"SELECT key,value FROM {alias}.metadata "
        "WHERE key GLOB 'settlement_*' OR key GLOB 'city_*' OR key GLOB 'max_city_*' "
        "OR key GLOB 'way_*' OR key GLOB 'corridor_*' OR key='schema_version' "
        "OR key='tile_size_m' OR key GLOB '*_way_network_count'"
    ))


def _compatible_tables(connection, base, target):
    before, after = context_metadata(connection, base), context_metadata(connection, target)
    for key in ("schema_version", "settlement_context_version"):
        if (key in before) != (key in after) or before.get(key) != after.get(key):
            raise SystemExit(f"Context schema/capability {key} changed; deliver a full bundle")
    base_version = before.get("settlement_context_version")
    target_version = after.get("settlement_context_version")
    if "settlement_context_version" in after and target_version is None:
        raise SystemExit("Invalid NULL settlement capability; deliver a full bundle")
    if base_version != target_version or target_version not in (None, "1"):
        raise SystemExit("Settlement capability changed or unsupported; deliver a full bundle")
    present = []
    for table, keys in {**CONTEXT_TABLE_KEYS, **MATCHER_TABLE_KEYS}.items():
        has_base = _exists(connection, base, table)
        has_target = _exists(connection, target, table)
        if has_base != has_target:
            raise SystemExit(f"Context table {table} changed availability; deliver a full bundle")
        if not has_base:
            if target_version == "1" and table.startswith("settlement_"):
                raise SystemExit(f"Incomplete settlement capability: missing {table}")
            continue
        # Names are fixed here, never supplied as SQL by a manifest.
        base_schema = [tuple(row) for row in connection.execute(f"PRAGMA {base}.table_info({_identifier(table)})")]
        target_schema = [tuple(row) for row in connection.execute(f"PRAGMA {target}.table_info({_identifier(table)})")]
        if base_schema != target_schema:
            raise SystemExit(f"Context table {table} changed schema; deliver a full bundle")
        def indexes(alias):
            return connection.execute(
                f"SELECT name,sql FROM {alias}.sqlite_master WHERE type='index' AND tbl_name=? ORDER BY name",
                (table,),
            ).fetchall()
        if indexes(base) != indexes(target):
            raise SystemExit(f"Context table {table} changed indexes; deliver a full bundle")
        columns = [row[1] for row in base_schema]
        if keys is None:
            primary_key = [row[1] for row in sorted(base_schema, key=lambda row: row[5]) if row[5]]
            # Historical fixtures without a declared PK are compared by the
            # entire edge. Never collapse two detailed edges sharing way IDs.
            keys = tuple(primary_key or columns)
        if not set(keys).issubset(columns):
            raise SystemExit(f"Invalid context keys in {table}")
        present.append((table, keys, columns))
    return present


def _difference(connection, left, right, table, columns):
    names = ",".join(map(_identifier, columns))
    query = (
        f"SELECT {names} FROM {left}.{_identifier(table)} EXCEPT "
        f"SELECT {names} FROM {right}.{_identifier(table)} ORDER BY {names}"
    )
    return connection.execute(query)


def build_context_delta(base_db: Path, target_db: Path):
    connection = sqlite3.connect(":memory:", uri=True)
    try:
        connection.execute("ATTACH DATABASE ? AS b", (base_db.resolve().as_uri() + "?mode=ro",))
        connection.execute("ATTACH DATABASE ? AS t", (target_db.resolve().as_uri() + "?mode=ro",))
        tables = _compatible_tables(connection, "b", "t")
        deletions, insertions, counts = {}, {}, {}
        for table, keys, columns in tables:
            deletions[table], insertions[table] = [], []
            key_indices = [columns.index(key) for key in keys]
            for row in _difference(connection, "b", "t", table, columns):
                predicate = " AND ".join(
                    f"{_identifier(key)} IS {_literal(row[index])}"
                    for key, index in zip(keys, key_indices)
                )
                deletions[table].append(f"DELETE FROM {_identifier(table)} WHERE {predicate};")
            names = ",".join(map(_identifier, columns))
            for row in _difference(connection, "t", "b", table, columns):
                insertions[table].append(
                    f"INSERT INTO {_identifier(table)}({names}) VALUES({','.join(map(_literal, row))});"
                )
            counts[table] = {"deleted": len(deletions[table]), "inserted": len(insertions[table])}
        statements = [statement for table, _, _ in reversed(tables) for statement in deletions[table]]
        statements.extend(statement for table, _, _ in tables for statement in insertions[table])
        before, after = context_metadata(connection, "b"), context_metadata(connection, "t")
        for key in sorted(before.keys() - after.keys()):
            statements.append(f"DELETE FROM metadata WHERE key={_literal(key)};")
        for key in sorted(after):
            if before.get(key) != after[key]:
                statements.append(
                    f"INSERT OR REPLACE INTO metadata(key,value) VALUES({_literal(key)},{_literal(after[key])});"
                )
        return statements, counts
    finally:
        connection.close()


def assert_context_equivalence(connection, patched="p", target="t"):
    for table, _, columns in _compatible_tables(connection, patched, target):
        for left, right in ((patched, target), (target, patched)):
            if _difference(connection, left, right, table, columns).fetchone() is not None:
                raise SystemExit(f"Patch drift against target DB (context table {table})")
        counts = [connection.execute(f"SELECT count(*) FROM {alias}.{_identifier(table)}").fetchone()[0]
                  for alias in (patched, target)]
        if counts[0] != counts[1]:
            raise SystemExit(f"Patch drift against target DB (duplicate context rows in {table})")
    if context_metadata(connection, patched) != context_metadata(connection, target):
        raise SystemExit("Patch drift against target DB (context metadata)")
