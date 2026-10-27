#!/usr/bin/env python3
"""Lossless production context/geometry containers; see shared/packed-runtime/FORMAT.md."""
from collections import OrderedDict
from collections import deque
from concurrent.futures import ThreadPoolExecutor
import ctypes
import ctypes.util
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import struct
import tempfile
import zlib

HEADER = 128
BLOCK = 262144
DIRECTORY = struct.Struct('<QIIII')
GEOMETRY = struct.Struct('<qQII')
_ZSTD = None


def zstd_library():
    global _ZSTD
    if _ZSTD is None:
        name = os.environ.get('YOUSPEED_ZSTD_LIBRARY') or ctypes.util.find_library('zstd')
        if not name and Path('/opt/homebrew/lib/libzstd.dylib').exists():
            name = '/opt/homebrew/lib/libzstd.dylib'
        require(name, 'Install the official libzstd build dependency')
        library = ctypes.CDLL(name)
        library.ZSTD_compressBound.argtypes = [ctypes.c_size_t]
        library.ZSTD_compressBound.restype = ctypes.c_size_t
        library.ZSTD_compress.argtypes = [ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_size_t,ctypes.c_int]
        library.ZSTD_compress.restype = ctypes.c_size_t
        library.ZSTD_decompress.argtypes = [ctypes.c_void_p,ctypes.c_size_t,ctypes.c_void_p,ctypes.c_size_t]
        library.ZSTD_decompress.restype = ctypes.c_size_t
        library.ZSTD_isError.argtypes = [ctypes.c_size_t]
        library.ZSTD_isError.restype = ctypes.c_uint
        library.ZSTD_versionString.restype = ctypes.c_char_p
        _ZSTD = library
    return _ZSTD


def encode_block(raw, codec):
    if codec == 1:
        encoded = zlib.compress(raw, 6)
    else:
        library = zstd_library()
        buffer = ctypes.create_string_buffer(library.ZSTD_compressBound(len(raw)))
        count = library.ZSTD_compress(buffer,len(buffer),raw,len(raw),15)
        require(not library.ZSTD_isError(count), 'Zstandard compression failed')
        encoded = buffer.raw[:count]
    return encoded, len(raw), zlib.crc32(raw)


def require(condition, reason):
    if not condition:
        raise ValueError(reason)


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 * 1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def quote(name):
    return '"' + name.replace('"', '""') + '"'


def pack_chunks(chunks, output, source_sha256, *, index_path=None, index_count=0, codec=2):
    output = Path(output)
    require(not output.exists(), f'Refusing to overwrite {output}')
    require(len(bytes.fromhex(source_sha256)) == 32, 'Invalid source SHA-256')
    require(codec in (1,2), 'Unsupported output codec')
    if codec == 2:
        zstd_library()
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='pack-', dir=output.parent) as temporary:
        temporary = Path(temporary)
        encoded_path = temporary / 'encoded'
        entries, pending, logical, encoded_size = [], bytearray(), 0, 0
        workers = min(8,max(1,int(os.environ.get('YOUSPEED_PACKED_COMPRESSION_THREADS','4'))))
        with encoded_path.open('wb') as encoded, ThreadPoolExecutor(max_workers=workers) as executor:
            futures = deque()
            def write_block(result):
                nonlocal logical, encoded_size
                compressed, raw_size, crc = result
                entries.append(DIRECTORY.pack(encoded_size, len(compressed), raw_size, crc, 0))
                encoded.write(compressed)
                logical += raw_size
                encoded_size += len(compressed)
            for chunk in chunks:
                view = memoryview(chunk)
                position = 0
                while position < len(view):
                    count = min(BLOCK - len(pending), len(view) - position)
                    pending.extend(view[position:position + count])
                    position += count
                    if len(pending) == BLOCK:
                        futures.append(executor.submit(encode_block,bytes(pending),codec))
                        pending.clear()
                        if len(futures) >= workers*2:
                            write_block(futures.popleft().result())
            if pending:
                futures.append(executor.submit(encode_block,bytes(pending),codec))
            while futures:
                write_block(futures.popleft().result())
        geometry = index_path is not None
        index_bytes = index_count * GEOMETRY.size if geometry else 0
        require(not geometry or Path(index_path).stat().st_size == index_bytes, 'Geometry index size mismatch')
        directory = b''.join(entries)
        directory_offset = HEADER + index_bytes
        data_offset = directory_offset + len(directory)
        file_bytes = data_offset + encoded_size
        header = bytearray(HEADER)
        struct.pack_into('<8sIIIIQQQQQQQ', header, 0, b'YSPGEO1\0' if geometry else b'YSPCTX1\0',
                         1, 0x01020304, HEADER, BLOCK, logical, len(entries), directory_offset,
                         data_offset, file_bytes, index_count, HEADER if geometry else 0)
        index_crc = 0
        if geometry:
            with Path(index_path).open('rb') as stream:
                for chunk in iter(lambda: stream.read(1024 * 1024), b''):
                    index_crc = zlib.crc32(chunk, index_crc)
        struct.pack_into('<II', header, 80, zlib.crc32(directory), index_crc)
        struct.pack_into('<I', header, 88, zlib.crc32(header[:88]))
        struct.pack_into('<I', header, 92, codec)
        header[96:128] = bytes.fromhex(source_sha256)
        complete = temporary / 'complete'
        with complete.open('wb') as target:
            target.write(header)
            if geometry:
                with Path(index_path).open('rb') as source:
                    shutil.copyfileobj(source, target, 1024 * 1024)
            target.write(directory)
            with encoded_path.open('rb') as source:
                shutil.copyfileobj(source, target, 1024 * 1024)
        require(complete.stat().st_size == file_bytes, 'Container size mismatch')
        complete.rename(output)
    return {'file': output.name, 'bytes': file_bytes, 'logical_bytes': logical,
            'sha256': digest(output), 'blocks': len(entries), 'geometry_records': index_count}


def pack_file(source, output, source_sha256):
    with Path(source).open('rb') as stream:
        return pack_chunks(iter(lambda: stream.read(BLOCK), b''), output, source_sha256)


class Reader:
    """Independent bounded Python decoder for build verification, not app runtime."""
    def __init__(self, path, cache_bytes=8 * 1024 * 1024):
        self.file = Path(path).open('rb')
        header = self.file.read(HEADER)
        require(len(header) == HEADER and header[:8] in (b'YSPCTX1\0', b'YSPGEO1\0'), 'Invalid packed header')
        fields = struct.unpack_from('<8sIIIIQQQQQQQ', header)
        _, version, endian, size, self.block, self.logical, count, directory, self.data, physical, self.index_count, self.index = fields
        require((version, endian, size, self.block) == (1, 0x01020304, HEADER, BLOCK), 'Unsupported packed format')
        require(zlib.crc32(header[:88]) == struct.unpack_from('<I', header, 88)[0], 'Header CRC mismatch')
        require(physical == Path(path).stat().st_size and directory + count * DIRECTORY.size == self.data <= physical, 'Packed section bounds')
        self.codec = struct.unpack_from('<I',header,92)[0]
        require(self.codec in (1,2), 'Unsupported compression')
        self.file.seek(directory)
        raw_directory = self.file.read(count * DIRECTORY.size)
        require(zlib.crc32(raw_directory) == struct.unpack_from('<I', header, 80)[0], 'Directory CRC mismatch')
        self.entries = list(DIRECTORY.iter_unpack(raw_directory))
        self.cache, self.cache_limit = OrderedDict(), max(1, cache_bytes // BLOCK)

    def close(self):
        self.file.close()

    def read(self, offset, count):
        require(0 <= offset <= self.logical and count >= 0, 'Invalid logical read')
        count = min(count, self.logical - offset)
        result = bytearray()
        while count:
            number, within = divmod(offset, BLOCK)
            if number not in self.cache:
                encoded, size, raw_size, crc, flags = self.entries[number]
                require(flags == 0 and 0 < raw_size <= BLOCK, 'Invalid block')
                self.file.seek(self.data + encoded)
                encoded_bytes = self.file.read(size)
                if self.codec == 1:
                    value = zlib.decompress(encoded_bytes)
                else:
                    library = zstd_library()
                    target = ctypes.create_string_buffer(raw_size)
                    decoded_size = library.ZSTD_decompress(target,raw_size,encoded_bytes,len(encoded_bytes))
                    require(not library.ZSTD_isError(decoded_size), 'Zstandard decompression failed')
                    value = target.raw[:decoded_size]
                require(len(value) == raw_size and zlib.crc32(value) == crc, 'Block CRC mismatch')
                self.cache[number] = value
                while len(self.cache) > self.cache_limit:
                    self.cache.popitem(last=False)
            self.cache.move_to_end(number)
            value = self.cache[number]
            size = min(count, len(value) - within)
            require(size > 0, 'Truncated logical block')
            result.extend(value[within:within + size])
            offset += size
            count -= size
        return bytes(result)

    def geometry(self, way_id):
        low, high = 0, self.index_count
        while low < high:
            middle = (low + high) // 2
            self.file.seek(self.index + middle * GEOMETRY.size)
            row = GEOMETRY.unpack(self.file.read(GEOMETRY.size))
            if row[0] < int(way_id):
                low = middle + 1
            else:
                high = middle
        if low == self.index_count:
            return None
        self.file.seek(self.index + low * GEOMETRY.size)
        key, offset, size, crc = GEOMETRY.unpack(self.file.read(GEOMETRY.size))
        if key != int(way_id):
            return None
        value = self.read(offset, size)
        require(zlib.crc32(value) == crc, 'Geometry CRC mismatch')
        return value.decode('utf-8')


def build_geometry(source, output, source_sha256):
    with tempfile.TemporaryDirectory(prefix='geometry-', dir=Path(output).parent) as temporary:
        temporary = Path(temporary)
        index = temporary / 'index'
        count, logical, last = 0, 0, 0
        # Source INTEGER IDs already have the required source-ID ordering.
        rows = source.execute('SELECT way_id,points_json FROM way_geom ORDER BY CAST(way_id AS INTEGER)')
        with index.open('wb') as directory:
            def chunks():
                nonlocal count, logical, last
                for key, text in rows:
                    key = int(key)
                    require(last < key < 2**63, 'Duplicate, unordered or invalid geometry way ID')
                    require(isinstance(text, str), 'Geometry JSON must be source text')
                    raw = text.encode('utf-8')
                    require(0 < len(raw) <= 16 * 1024 * 1024, 'Oversized geometry record')
                    directory.write(GEOMETRY.pack(key, logical, len(raw), zlib.crc32(raw)))
                    last, logical, count = key, logical + len(raw), count + 1
                    yield raw
                directory.flush()
            # pack_chunks needs a complete index before final assembly, so spool
            # only the exact geometry text once; memory remains bounded.
            payload = temporary / 'payload'
            with payload.open('wb') as stream:
                for raw in chunks():
                    stream.write(raw)
        with payload.open('rb') as stream:
            result = pack_chunks(iter(lambda: stream.read(BLOCK), b''), output, source_sha256,
                                 index_path=index, index_count=count)
    return result


def build_context(source_path, geometry_path, output, source_sha256, generation):
    """Clone original SQL semantics; move only geometry payload into its companion."""
    output = Path(output)
    with tempfile.TemporaryDirectory(prefix='context-', dir=output.parent) as temporary:
        temporary = Path(temporary)
        database = temporary / 'context.sqlite'
        source = sqlite3.connect('file:' + str(Path(source_path).resolve()) + '?mode=ro&immutable=1', uri=True)
        target = sqlite3.connect(database)
        source.backup(target, pages=4096)
        source.close()
        # Zero deleted geometry pages so the container can compress them cheaply.
        # Avoid VACUUM: implicit rowids in unrelated source tables must survive.
        target.execute('PRAGMA secure_delete=ON')
        columns = target.execute('PRAGMA table_info(way_geom)').fetchall()
        names = [row[1] for row in columns]
        require('way_id' in names and 'points_json' in names, 'Missing original geometry schema')
        keep = [name for name in names if name != 'points_json']
        target.execute('CREATE TABLE ysp_geometry_keys AS SELECT ' + ','.join(map(quote, keep)) + ' FROM way_geom')
        target.execute('CREATE UNIQUE INDEX ysp_geometry_key_id ON ysp_geometry_keys(way_id)')
        target.execute('DROP TABLE way_geom')
        projection = ["ysp_way_points_json(CAST(way_id AS TEXT)) AS points_json" if name == 'points_json' else quote(name) for name in names]
        target.execute('CREATE VIEW way_geom AS SELECT ' + ','.join(projection) + ' FROM ysp_geometry_keys')
        values = {'packed_geometry_version':'1', 'packed_geometry_file':Path(geometry_path).name,
                  'packed_geometry_sha256':digest(geometry_path), 'packed_generation':generation}
        target.executemany('INSERT OR REPLACE INTO metadata(key,value) VALUES(?,?)', values.items())
        target.commit()
        geometry = Reader(geometry_path)
        target.create_function('ysp_way_points_json', 1, geometry.geometry)
        require(target.execute('PRAGMA quick_check').fetchone() == ('ok',), 'Context quick_check failed')
        count = target.execute('SELECT COUNT(*) FROM way_geom').fetchone()[0]
        require(count == geometry.index_count, 'Geometry identity mismatch')
        target.close()
        geometry.close()
        logical_sha = digest(database)
        result = pack_file(database, output, source_sha256)
        result['logical_sha256'] = logical_sha
        reader = Reader(output)
        check = hashlib.sha256()
        for offset in range(0, reader.logical, BLOCK):
            check.update(reader.read(offset, BLOCK))
        reader.close()
        require(check.hexdigest() == logical_sha, 'Packed context differs from exact SQL image')
        result['geometry_rows'] = count
    return result
