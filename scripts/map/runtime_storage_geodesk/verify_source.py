#!/usr/bin/env python3
"""Verify every canonical source way and generic speed node exists in real GOL.

This establishes stable-ID inclusion, separate from the benchmark's spatial,
geometry and rule-result checks. No reduced sample is used.
"""
import argparse
import array
import bisect
import ctypes
import hashlib
import json
from pathlib import Path
import sqlite3
import struct


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--library", required=True)
    ap.add_argument("--gol", type=Path, required=True)
    ap.add_argument("--source-sqlite", type=Path, required=True)
    ap.add_argument("--source-nodes", type=Path, required=True)
    ap.add_argument("--output", type=Path, required=True)
    args = ap.parse_args()
    native = ctypes.CDLL(args.library)
    native.storage_geodesk_open.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_size_t]
    native.storage_geodesk_open.restype = ctypes.c_void_p
    native.storage_geodesk_close.argtypes = [ctypes.c_void_p]
    native.storage_geodesk_free_ids.argtypes = [ctypes.POINTER(ctypes.c_int64)]
    err = ctypes.create_string_buffer(1024)
    handle = native.storage_geodesk_open(str(args.gol).encode(), err, len(err))
    if not handle:
        raise RuntimeError(err.value.decode())

    def ids_for(symbol):
        func = getattr(native, symbol)
        func.argtypes = [ctypes.c_void_p, ctypes.c_double, ctypes.c_double,
                         ctypes.c_double, ctypes.c_double,
                         ctypes.POINTER(ctypes.POINTER(ctypes.c_int64)),
                         ctypes.POINTER(ctypes.c_size_t)]
        func.restype = ctypes.c_int
        ids = ctypes.POINTER(ctypes.c_int64)()
        count = ctypes.c_size_t()
        rc = func(handle, -179.999, -85.0, 179.999, 85.0,
                  ctypes.byref(ids), ctypes.byref(count))
        if rc:
            raise RuntimeError(f"{symbol}: {rc}")
        result = array.array("q")
        if count.value:
            result.frombytes(ctypes.string_at(ids, count.value * 8))
        native.storage_geodesk_free_ids(ids)
        return result

    def verify(source, gol_ids):
        missing = []
        digest = hashlib.sha256()
        count = 0
        for key in source:
            count += 1
            digest.update(struct.pack("<q", key))
            index = bisect.bisect_left(gol_ids, key)
            if index == len(gol_ids) or gol_ids[index] != key:
                missing.append(key)
        return {"source_count": count, "gol_feature_count": len(gol_ids),
                "source_sorted_id_sha256_le_i64": digest.hexdigest(),
                "missing_count": len(missing), "missing_ids": missing}

    try:
        connection = sqlite3.connect("file:" + str(args.source_sqlite.resolve()) + "?mode=ro", uri=True)
        roads = verify((row[0] for row in connection.execute(
            "SELECT way_id FROM way_geom ORDER BY way_id")),
            ids_for("storage_geodesk_candidates"))
        nodes_json = json.loads(args.source_nodes.read_text())
        nodes = verify(sorted(node["osm_node_id"] for node in nodes_json["nodes"]),
                       ids_for("storage_geodesk_node_candidates"))
    finally:
        native.storage_geodesk_close(handle)
    gol_digest = hashlib.sha256()
    with args.gol.open("rb") as gol_file:
        for block in iter(lambda: gol_file.read(1024 * 1024), b""):
            gol_digest.update(block)
    gol_hash = gol_digest.hexdigest()
    report = {"schema": "youspeed.geodesk-full-source-inclusion.v1",
              "gol_bytes": args.gol.stat().st_size, "gol_sha256": gol_hash,
              "source_pbf_sha256": nodes_json["source_pbf_sha256"],
              "ways": roads, "generic_speed_nodes": nodes,
              "all_source_ids_present": roads["missing_count"] == 0 and nodes["missing_count"] == 0}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    if not report["all_source_ids_present"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
