# Production packed runtime, version 1

An immutable generation has three verified files: a queryable context pack,
packed way geometry, and generic speed-sign nodes. Corrections are a separate
writable store. This changes storage, not SQL lookup semantics or the protected
speed-reference policy. SQLite remains a query engine; its base page image is
compressed inside the context pack and is never inflated into a permanent raw
database on either phone.

Context and geometry use the same little-endian 128-byte header. All offsets
and products must be checked for overflow and file bounds before reading.

| Offset | Type | Meaning |
|---|---|---|
| 0 | bytes[8] | Context `YSPCTX1\0`; geometry `YSPGEO1\0` |
| 8 | u32 | Version, 1 |
| 12 | u32 | Endian marker, 0x01020304 |
| 16 | u32 | Header bytes, 128 |
| 20 | u32 | Uncompressed block bytes, 262144 |
| 24 | u64 | Logical uncompressed payload bytes |
| 32 | u64 | Block count, ceil(logical bytes / block bytes) |
| 40 | u64 | Absolute block directory offset |
| 48 | u64 | Absolute compressed data offset |
| 56 | u64 | Exact physical file bytes |
| 64 | u64 | Geometry index count, 0 for context |
| 72 | u64 | Absolute geometry index offset, 128 for geometry, 0 for context |
| 80 | u32 | CRC32 of block directory bytes |
| 84 | u32 | CRC32 of geometry index bytes, 0 for context |
| 88 | u32 | CRC32 of header bytes 0 through 87 |
| 92 | u32 | Codec, 1 = zlib (legacy fixtures), 2 = Zstandard (production) |
| 96 | bytes[32] | Original source SQLite SHA-256, binary digest |

Each block directory entry is 24 bytes: relative compressed-data offset u64,
compressed size u32, uncompressed size u32, uncompressed CRC32 u32, reserved u32
(must be zero). Every block is an independent stream/frame in its declared codec.
Production uses Zstandard level 15 without a dictionary; frames declare their
exact content size and use at most a 256 KiB window. Readers reject dictionary
frames, unknown content sizes and oversized windows. Codec 1 remains supported
for compatibility. The final block can
be shorter; all preceding raw sizes equal the configured block size. Empty
context images are rejected. Directory entries are contiguous in logical order
and physical encoded ranges must be nonoverlapping. No mmap is used. A handle's
decompressed block cache is explicitly bounded (context default 2 MiB, geometry
default 512 KiB); index reads use bounded pread pages rather than loading all IDs.

Each geometry index entry is 24 bytes: original positive signed 64-bit OSM way
ID, logical payload offset u64, UTF-8 JSON bytes u32, record CRC32 u32. Entries
are strictly increasing by numeric way ID. Payloads concatenate the exact
original `way_geom.points_json` bytes, preserving source coordinate order,
precision and JSON spelling. This first production version prioritizes exact
lookup behavior and lossless source reconstruction. It can evolve to another
lossless geometry codec under a new format version.

The context logical payload is a complete read-only SQLite page image. Its
original tables, joins, restrictions, indexes and provenance remain queryable.
`way_geom` becomes a view over a small `ysp_geometry_keys` table containing the
original geometry row identities and any non-payload columns. Its `points_json`
column calls `ysp_way_points_json(CAST(way_id AS TEXT))` against the companion
geometry pack. This preserves missing-row join behavior. The scalar must be
registered before validation/queries, and a missing/corrupt companion prevents
activation. Existing table capability checks must admit this view.

Metadata keys are `packed_geometry_version=1`, `packed_geometry_file`,
`packed_geometry_sha256` (installed geometry bytes), and `packed_generation`.
The manifest format is `youspeed.v4.bundle.manifest`, schema version 1, minimum
app version 1.6. Its `db` artifact is the context pack; `packed_base` contains
`version:1`, `roads:BundleArtifact`, and `nodes:BundleArtifact`. Artifact byte
counts and SHA-256 follow the existing installed/download distinction.
V4 catalogs/releases are separate from existing V3 URLs. All dependencies must
verify before generation activation; V3 SQL deltas cannot mutate packed data.

## Native ABI

The shared header is `shared/runtime-storage-prototype/packed_runtime.h`.
Handles are thread-safe for read calls; callers retain them until SQLite/cursor
operations have stopped. Errors are written into caller-owned
buffers. Strings are malloc-owned and freed by `ysp_packed_free`.

```c
void* ysp_context_open(const char* path, uint64_t cache_bytes, char* error, size_t error_size);
uint64_t ysp_context_size(void* handle);
// Returns bytes read, 0 at EOF, -1 on error. Read requests may cross blocks.
int64_t ysp_context_read(void* handle, uint64_t offset, void* output, size_t bytes,
                         char* error, size_t error_size);
void ysp_context_close(void* handle);
void* ysp_geometry_open(const char* path, uint64_t cache_bytes, char* error, size_t error_size);
char* ysp_geometry_json(void* handle, const char* decimal_way_id, char* error, size_t error_size);
void ysp_geometry_close(void* handle);
void ysp_packed_free(void* memory);
// Registers the read-only SQLite VFS name "ysp-packed-v1"; 0 means success.
int ysp_register_context_vfs(void);
// Shared production SQL page-cache budget, 1536 KiB.
int ysp_sqlite_cache_kib(void);
```

On iPhone, open the context with the registered VFS and register the geometry
scalar on that connection. Android uses the same VFS through a privately linked
SQLite engine and a typed JNI cursor. The framework SQLite path cannot open the
proxy file descriptor on the tested Android release. Legacy databases and the
writable correction store retain their platform database implementations.
Explicitly disable SQLite mmap and bound its page cache to 1536 KiB on both
platforms. Android's scalar callback calls the same native geometry reader.
Generic node files retain the
existing source-complete node schema, using the bounded pread reader.

Corrections preserve source IDs, restriction JSON/raw tags, validity, provenance,
revision history and tombstones. Unknown bindings/conditions remain unresolved;
new node events require existing directed-association and passage checks. Use
the existing conditional evaluator and producer admission, not a new priority
or reference-policy rule.

The correction basis is
`ysp-base-v1:<installed context SHA-256>:<installed geometry SHA-256>:<installed node SHA-256 or absent>`.
Digests are lowercase and come from the saved, verified generation manifest.
Read that small manifest once per resource generation; do not hash the full
payload on lookup. A shared display version is insufficient for overlapping
extracts. Missing identity evidence and old version-only records cannot
authorize an override; retain their history for explicit compare-and-swap
rebase. Recognized `node-json-sha256:` and `way-rule-set-sha256:` revisions must
also match the current underlying source bytes.
