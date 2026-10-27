#!/usr/bin/env python3
"""Compare every native geometry result with the unmodified source SQLite."""
import argparse
import ctypes
import hashlib
import json
from pathlib import Path
import sqlite3
import struct
import time


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--library', type=Path, required=True)
    parser.add_argument('--source', type=Path, required=True)
    parser.add_argument('--geometry', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    api = ctypes.CDLL(str(args.library.resolve()))
    api.ysp_geometry_open.argtypes = [ctypes.c_char_p, ctypes.c_uint64,
                                     ctypes.c_void_p, ctypes.c_size_t]
    api.ysp_geometry_open.restype = ctypes.c_void_p
    api.ysp_geometry_json.argtypes = [ctypes.c_void_p, ctypes.c_char_p,
                                     ctypes.c_void_p, ctypes.c_size_t]
    api.ysp_geometry_json.restype = ctypes.c_void_p
    api.ysp_geometry_stats_json.argtypes = [ctypes.c_void_p]
    api.ysp_geometry_stats_json.restype = ctypes.c_void_p
    api.ysp_geometry_close.argtypes = [ctypes.c_void_p]
    api.ysp_packed_free.argtypes = [ctypes.c_void_p]
    error = ctypes.create_string_buffer(512)
    started = time.monotonic()
    handle = api.ysp_geometry_open(str(args.geometry.resolve()).encode(), 0,
                                   error, len(error))
    if not handle:
        raise RuntimeError(error.value.decode())
    count = 0
    original_hash = hashlib.sha256()
    native_hash = hashlib.sha256()
    try:
        with sqlite3.connect(args.source.resolve().as_uri() + '?mode=ro',
                             uri=True) as database:
            for way_id, original in database.execute(
                    'SELECT way_id,points_json FROM way_geom ORDER BY way_id'):
                pointer = api.ysp_geometry_json(handle, str(way_id).encode(),
                                                error, len(error))
                if not pointer:
                    raise RuntimeError(f'way {way_id}: {error.value.decode()}')
                try:
                    actual = ctypes.string_at(pointer)
                finally:
                    api.ysp_packed_free(pointer)
                expected = original.encode('utf-8')
                if actual != expected:
                    raise RuntimeError(f'exact geometry mismatch: way {way_id}')
                prefix = struct.pack('<qQ', way_id, len(expected))
                original_hash.update(prefix)
                original_hash.update(expected)
                native_hash.update(prefix)
                native_hash.update(actual)
                count += 1
        pointer = api.ysp_geometry_stats_json(handle)
        if not pointer:
            raise RuntimeError('native statistics unavailable')
        try:
            stats = json.loads(ctypes.string_at(pointer))
        finally:
            api.ysp_packed_free(pointer)
        report = {
            'schema': 1, 'overall_success': True,
            'verification': 'Every source way_geom row compared byte for byte '
                            'with the persistent native production reader; '
                            'Int64 ID and exact UTF-8 JSON retained.',
            'record_hash_encoding': 'Ascending signed Int64 way ID, <qQ> '
                                    'little-endian ID and UTF-8 byte length, '
                                    'then exact UTF-8 points_json bytes.',
            'geometry_count': count,
            'source_records_sha256': original_hash.hexdigest(),
            'native_records_sha256': native_hash.hexdigest(),
            'elapsed_seconds': time.monotonic() - started,
            'native_io_stats': stats,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(report, indent=2) + '\n')
    finally:
        api.ysp_geometry_close(handle)


if __name__ == '__main__':
    main()
