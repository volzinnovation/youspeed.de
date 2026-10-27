# Full-source generic speed/sign node lookup prototype

The production API is `packed_nodes.h`: persistent `ysp_nodes_open`, complete
source `ysp_nodes_json` and `ysp_nodes_query_json`, cache statistics, close/free.
Read calls serialize safely. The default 512 KiB index-page cache uses bounded
`pread`/`pread64`; payloads are read into validated temporary buffers and no
file is mapped. Empty packs are valid mandatory artifacts. Build production
with `YSP_NODES_PACKED_ONLY=1` to exclude SQLite/GeoDesk comparison dependencies.
Production extraction retains any `maxspeed*` or `traffic_sign*` key across
countries, preserving unknown sign codes as unresolved source data. The
existing direction/association, conditional and passage gates still apply.

This separate index makes every source speed/sign node queryable. It preserves
the full canonical JSON record, all tags, original E7 coordinates, explicit way
membership and the original double chainage; it does not infer directed legal
applicability from membership or proximity.

The historical speed-node-only BW extraction contains 20,141 nodes and 10,922
explicit memberships; these counts describe the original benchmark snapshot.
The packed index sorts fixed-width records by latitude and has an additional
sorted 64-bit ID index. Query uses latitude binary search followed by longitude
and exact spherical-distance filters. Full canonical metadata is compressed per
record, with CRC32 and FNV-1a checks on every returned record. Optimized SQLite
stores the same compressed bytes with an `rtree_i32` spatial index. GeoDesk uses
the genuine GOL node spatial index and the canonical sidecar for original
coordinate precision and identical application-specific metadata.

Build and verify:

```sh
python3 scripts/map/runtime_storage_nodes/build.py SOURCE.json OUTPUT_DIRECTORY
python3 scripts/map/runtime_storage_nodes/verify.py SOURCE.json OUTPUT_DIRECTORY
clang++ -std=c++17 -O2 \
  shared/runtime-sign-nodes-prototype/runtime_sign_nodes.cpp \
  shared/runtime-sign-nodes-prototype/main.cpp -lsqlite3 -lz -o nodebench
nodebench compare packed OUTPUT_DIRECTORY/nodes.yspn \
  sqlite OUTPUT_DIRECTORY/nodes.sqlite OUTPUT_DIRECTORY/queries.csv
nodebench benchmark packed OUTPUT_DIRECTORY/nodes.yspn \
  OUTPUT_DIRECTORY/queries.csv 3
```

The comparison opens both readers once, compares all source records byte for
byte, then compares every query result byte for byte. The independent Python
verifier additionally compares every compiled record with the original full-PBF
extraction, including all original chainage doubles. The generated 20,397-query
corpus covers every source node center and 256 deterministic sparse probes.

For GeoDesk, compile with `YSP_WITH_GEODESK`, link
`shared/runtime-storage-geodesk/geodesk_adapter.cpp` and its upstream GeoDesk
dependencies, and use `GOL_PATH|NODES_SQLITE_PATH` as the path. Account for both
the GOL and sidecar sizes when reporting that backend.

The C API is in `runtime_sign_nodes.h`. Returned strings are malloc-owned and
must be released with `storage_nodes_free()`. The CSV argument contains the CSV
text itself, with `lat,lon,radius_m` columns. `storage_node_json()` returns a full
source record; `storage_nodes_roundtrip_json()` reads and verifies every record.
Benchmark latency includes metadata decompression and both integrity checks.
Process-first timing does not clear the OS filesystem cache. RSS and highwater
include the host harness, result buffers and allocator.

Node corrections and restrictions are stored independently by the executable
`shared/runtime-corrections-prototype/` overlay. Both modules leave the production
iPhone/Android behavior and approved reference policy unchanged.
