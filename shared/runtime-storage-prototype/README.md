# Runtime storage experiment

The production C++17 entry points are `packed_runtime.h/.cpp`,
`packed_sqlite_vfs.cpp` and `zstd_decoder.c`. They read the versioned context
and exact-text geometry containers described in
`shared/packed-runtime/FORMAT.md`. The core has no SQLite dependency; the VFS
links the same SQLite engine as its consuming connection. Persistent handles
serialize reads and expose actual cache and pread statistics. Context defaults
to a 2 MiB decoded-block cache and geometry to 512 KiB, with a 512 KiB index-page
cache per handle. The shared `ysp_sqlite_cache_kib()` accessor supplies the
1536 KiB SQLite page-cache budget to both clients. Caller results and platform allocations are
measured separately. Every read uses `pread`/`pread64`; no file is mapped.
The private Zstandard wrapper hides its symbols from other native SDKs and
retains the pinned upstream BSD notice/source receipt. Codec 1 remains
compatible; codec 2 checks dictionary-free frames, exact content size, a
256 KiB maximum window, one frame per block, and the original CRC.

The historical `runtime_storage.h/.cpp` query kernel compares
storage and nearby-road lookup, and does not change the matcher, conditional
rule interpreter, camera ordering, network gating or protected speed-reference
policy. Speed codes are a convenience projection; complete raw values and
conditional restrictions remain authoritative source evidence.

## Contract and coverage

`runtime_storage.h` exposes malloc-owned JSON for a query, one source way, or a
benchmark. Call `storage_free()` on every result. Handles are private to each
call. Input CSV **contents** contain `lat,lon,radius_m`, one query per line.
Nearby lookup returns all source ways within the radius after the common
geometry projection, sorted by stable OSM way ID. It returns distance, chainage,
projected coordinate, direction-specific speed codes, and checksums over exact
geometry and the entire per-way semantic record. Speed codes `-32768`, `-32767`
and `-1` mean absent, raw value requiring interpretation, and `none` respectively.

The per-way semantic record retains original typed rows from `ways`, endpoints,
directed permissions, lanes, sign associations and rules, source conditional
tags/compiled rules/interpretation status, settlement segments, topology links,
continuity membership, certified-path segments and motorway approaches. Arrays
use the source column order recorded in `manifest.json` and the SQLite schema
metadata. Source JSON strings, including restriction ASTs and unknown clauses,
are retained verbatim as strings. No rule is weakened into a bare numeric limit.

`source-semantics.zblocks` and its index preserve **every original logical table
and column**, including original global sign inventory, node IDs, conditions,
settlement polygons, explicit successor STOP evidence, capability metadata and
provenance. R-tree virtual rows are retained; their engine-owned `_node`,
`_rowid` and `_parent` shadow tables are excluded. The archive is part of **every
candidate's conservative retention total**. It is an audit-preservation format,
not an optimized native random-access global-event API. Native hot lookup
reads the relevant per-way rows separately.

The optional verified compaction removes that duplication without dropping
source data. `compact_globals.py` independently reconstructs every embedded
table from the native per-way payloads, sorts its original primary keys and
requires its exact original canonical table hash and count. All other tables
remain in `runtime-globals.zblocks`. Its index maps every original table to one
of these two locations. Original geometry JSON lexical spelling remains in
the global data even though the hot geometry is separately lossless. Count
this verified global archive in each runtime candidate; keep the larger
duplicate `source-semantics` archive as external audit evidence. A table with
any source way absent from the native pack stays global. Failed reconstruction
prevents accepting the compact output.

Original OSM generic speed-sign nodes missing from the source SQLite require
the separately extracted node dataset to be included and counted in all three
candidates. A missing source association cannot become a directed runtime
authority merely because a node is nearby. Stable source identities support
the separate `runtime-corrections-prototype` overlay; pack offsets are never
correction identities. Corrections can preserve restrictions and represent
generic/variable/unlimited signs without interpreting unknown restrictions as
unrestricted numeric limits.

## Representations

The packed file uses a 160-byte little-endian header, 72-byte source-ID-sorted
road records, shared geometry, a 32-byte-node Morton-ordered binary bounding
volume hierarchy with 32-road leaves, a 32-bit permutation, a block directory,
and independent zlib semantic blocks. Coordinates are exact E7 signed
delta-varints where lossless, otherwise exact IEEE-754 doubles; vertices are
never simplified or clipped. Source chainage values in event records remain
full-precision doubles; computed projection chainage is only this experiment's
common lookup output, not a replacement for source station values.

Fixed road records contain a stable 64-bit ID, E7 bounds, geometry/semantic
offsets and sizes, point count, typed speed codes and checksums. Semantic blocks
are 256 KiB uncompressed, with a bounded 16-block (4 MiB) LRU cache. The header
and road/spatial/permutation/block-directory sections have CRC32 integrity
checks; each decoded geometry and semantic block/record is checked. Opening
checks section checksums using bounded `pread`, including that cost in init
latency. Its current reader also uses a bounded 512 KiB pread page cache for
road/spatial/index records and direct reads for encoded payloads; no file is
mapped. Historical mapped-reader receipts remain under `results/`. These are
corruption checks, not authenticity signatures. Production distribution would
still require its existing verified-manifest and activation protocol.

The optimized SQLite comparator stores identical binary road records and
geometry, an integer R-tree, and identical compressed semantic blocks in
`WITHOUT ROWID` tables. Its page cache is 8 MiB and SQLite mmap is disabled;
the semantic cache has the same 4 MiB limit. Its optimized representation,
rather than the source's JSON and duplicated evidence, is the baseline.

When compiled with GeoDesk, that comparator uses the complete GOL as a spatial
OSM-ID index and the same optimized SQLite canonical geometry/semantic records
for exact projection and semantic identity. Count the GOL **plus** canonical
SQLite **plus** shared archives/node records. This intentionally exposes the
integration/storage cost; it is not an independent GOL-native implementation
of the YouSpeed matcher, nor a claim that GeoDesk cannot store those records.

## Reproduce

```sh
cmake -S shared/runtime-storage-prototype -B /tmp/ysp-storage-build -DCMAKE_BUILD_TYPE=Release
cmake --build /tmp/ysp-storage-build -j4
python3 scripts/map/runtime_storage/test_storage.py --binary /tmp/ysp-storage-build/rsbench
python3 scripts/map/runtime_storage/build.py --source SOURCE.sqlite --output-dir NEW_OUTPUT
python3 scripts/map/runtime_storage/finalize.py NEW_OUTPUT
python3 scripts/map/runtime_storage/verify.py --source SOURCE.sqlite --output-dir NEW_OUTPUT --result verification.json
python3 scripts/map/runtime_storage/compact_globals.py --source SOURCE.sqlite --output-dir NEW_OUTPUT --full-verification verification.json
python3 scripts/map/runtime_storage/corpus.py --source SOURCE.sqlite --output queries.csv
/tmp/ysp-storage-build/rsbench benchmark packed NEW_OUTPUT/runtime.pack queries.csv 3
/tmp/ysp-storage-build/rsbench benchmark sqlite NEW_OUTPUT/runtime.sqlite queries.csv 3
```

GeoDesk builds additionally set `YSP_WITH_GEODESK=ON`, `GEODESK_SOURCE_DIR` and
`GTL_SOURCE_DIR` as described in its adapter directory. Its path is
`GOL_PATH|SQLITE_PATH`. The Android build must supply a native SQLite library;
the NDK does not expose Android's Java SQLite implementation as a public C API.

The verifier independently re-queries the original source and checks every
way's exact geometry and complete per-way source rows against **both** outputs.
It also re-hashes every archived original table against a fresh source query.
The query corpus adds full-region sampling, conditional rules, physical sign
events, town signs, motorway exits and region extremes. Recorded-drive and
generic-node probes supplement it. Benchmarking reports process-first and
warm p50/p95/p99/max, opening time, RSS/high-water RSS, Apple physical footprint
and incremental RSS. Linux also reports PSS, private clean/dirty resident
pages, shared resident pages and anonymous/file PSS from `smaps_rollup`.
When available, its `Rss` value is also the reported current RSS, keeping RSS
and PSS on the same accounting basis; `statm` is a fallback. Each snapshot
names its RSS source. High-water RSS is the unadjusted kernel `getrusage`
value. Linux kernel accounting can lag a current `smaps_rollup` measurement,
so that high-water value can be lower than current RSS.
Unavailable platform measurements are null. File-backed mapped RSS can be
reclaimable and must not be equated with anonymous dirty memory or Apple's
physical footprint. Process-first does **not** mean an OS-cold filesystem
cache. Process memory includes the harness, result corpus and allocator.

Tests cover exact source restrictions/event station values, both geometry
codecs, signed deltas, spatial leaf borders, missing roads, truncated files,
unsupported versions, corrupt geometry/semantic blocks, invalid offsets and a
cyclic spatial branch. The prototype has no production activation mechanism;
interrupted installation and the existing apps' full matcher remain outside
this benchmark.

Verified full-BW receipts are retained under `results/`: the million-way source
audit, independent query parity, all 50 reconstructed table hashes, complete
component/download-size inventory, and normal/sanitized format checks. Large
local pack/database artifacts stay outside the repository.
