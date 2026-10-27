# GeoDesk comparator prototype

This adapter supplies real GeoDesk GOL bounding-box lookups to the common native
storage benchmark. It does not change the production map reader or reference
policy. `storage_geodesk_candidates` returns every OSM way whose **bounds** overlap
the projected query bounds. It queries every highway value, rather than
restricting the lookup to an assumed highway vocabulary. Area ways (closed
residential/service squares) are included; GOQL's `w` selector alone omits them.
The benchmark joins IDs to the full
canonical road table and applies its original E7 bounds test, geometry and rules.
Two projected coordinate units of conservative padding protect boundary hits
against GOL's Mercator integer quantization. Consequently the comparator retains
and counts both GOL and the canonical semantic/geometry sidecar. It does not
claim native GOL geometry is byte-identical to the original E7 source.

The C ABI is in `geodesk_adapter.h`. Handles are confined to one thread and remain
open over a benchmark run. The upstream library maps its file; mapped file size
is not resident memory. Allocation and file-mapping latency belong to the common
benchmark's open measurement, and candidate materialization/join belongs to its
lookup measurement.

## Reproduce the host build

```sh
python3 scripts/map/runtime_storage_geodesk/build.py \
  --scratch /private/tmp/youspeed-storage-prototype-20261026/geodesk \
  --openssl-root /opt/homebrew/opt/openssl@3 \
  --pbf mapdata/raw/baden-wuerttemberg-260913.osm.pbf \
  --gol /private/tmp/youspeed-storage-prototype-20261026/geodesk/bw.gol
```

The script verifies every download SHA-256 before extraction. The CMake file
uses local sources, preventing accidental moving-branch downloads during phone
builds. Configure `GEODESK_SOURCE_DIR` and `GTL_SOURCE_DIR`; add this directory
with CMake and link the `storage_geodesk` static target. The reader uses C++20,
independently of the benchmark's C++17 API. GEOS, Python, HTTP and builder sources
are excluded from phone builds. The host-only builder additionally needs zlib,
OpenSSL and a pinned cpp-httplib header. Source licenses remain in each checkout:
libgeodesk LGPL-3.0-only, builder AGPL-3.0-only, gtl Apache-2.0, cpp-httplib MIT.

The initial native import exhausted the available scratch headroom: random OSM
IDs caused its sparse `nodes.idx` alone to allocate over 7 GiB on APFS. That run
was terminated and only its generated partial GOL/work directory removed. The
companion `temporary-index-ram.patch` changes **only host build scratch**: when
`YOUSPEED_GOL_RAM_INDEXES` is set, three temporary indexes use private mappings,
trading RAM for disk. All threads see the same mapping, and indexes are discarded
after sorting. The patch rejects `--updatable`/persistent ID-index builds in this
mode. The helper enables this mode by default on POSIX; `--disk-indexes` restores
upstream scratch behavior. The phone reader and final GOL format are unchanged.

## Immutable snapshot and corrections

The primary benchmark builds the default read-only GOL. Tagged OSM nodes,
including generic speed-limit/sign nodes, retain their OSM IDs and tags; anonymous
untagged way-nodes can omit IDs. A correction anchored to a missing node must
remain explicitly unresolved, never silently discarded or assigned to a nearby
feature. The shared correction overlay supplies stable source identity,
conditional/directional restrictions, revisions and generic node events.

The pinned builder also offers `--updatable`, which enables all way-node IDs and
retains ID indexes for incremental updates. That is a separate storage choice;
its indexes and additional IDs must be counted, and native update behavior needs
its own validation before being used for product updates. The read-only GOL
benchmark does not establish that updates are safe or that the general OSM tag
model implements YouSpeed's restriction semantics.

## Full-source validation, 26 October 2026

The complete pinned BW PBF (`1856f4ac7c18435e17d74c7ba24a7b21b3a1231e60449851890dc0109638ded3`)
produced a **897,398,468-byte** GOL with 305 tiles. The optimized highway query
sees 2,388,796 OSM ways across all highway values, while the source canonical
scope contains 1,085,790 admitted road ways. A complete sorted-ID scan found
**zero missing canonical ways and zero missing generic speed nodes (20,141)**.
The full GOL also retains buildings, POIs, other roads and relations, so its size
cannot be treated as a like-for-like road-only engine comparison. The common
canonical sidecar must be added when reporting its complete runtime bundle.

The full 20,397-query generic-node corpus produced the same
`f16a6da37efa217d` result digest as the packed/SQLite node readers. The raw host
measurements and source-inclusion evidence are in `results/`; phone performance
must be taken from the separate device harness report. Host background builds
were active during this run. The memory report distinguishes clean mapped pages
in RSS from physical footprint, and the first pass is process-first, not OS-cold.

`filter_runtime_pbf.py` builds an optional fairer spatial-index input directly
from the original PBF: every canonical road ID, every generic source node ID and
all referenced way-node IDs, coordinates and tags. It does not roundtrip through
GOL or invent node IDs. App-specific conditional rules, settlement/boundary
evidence and certified adjacency remain in the counted common canonical archive;
the filtered GOL is a spatial comparator rather than an independent replacement
for these semantics. Both filtered and full-source GOLs require full source-ID
and native query-result verification.

The fair-scope BW GOL is **94,564,632 bytes**, compared with **897,398,468 bytes**
for full OSM scope. Its full 1,085,790-way projected-bounds scan matches the
original source bounds exactly (zero coordinate-unit delta), strengthening the
conservative-padding coverage check beyond the representative query corpus.
Its 586-road-query digest and complete 20,397-node-query digest match the other
native backends. The PBF preparation took 191.8 seconds; native GOL compilation
took 7.46 seconds and peaked at 6.28 GB RSS / 6.19 GB physical footprint on the
host, with zero swaps. These are **build** resources, separate from phone runtime
memory. The relatively high build RAM is the explicit tradeoff for avoiding
large sparse temporary indexes on the nearly full Mac disk.

To prepare that exact full-region spatial scope using installed pyosmium:

```sh
python3 scripts/map/runtime_storage_geodesk/filter_runtime_pbf.py \
  --pbf mapdata/raw/baden-wuerttemberg-260913.osm.pbf \
  --source-sqlite /private/tmp/youspeed-storage-prototype-20261026/source/bw.sqlite \
  --source-nodes /private/tmp/youspeed-storage-prototype-20261026/source/generic-speed-nodes.json \
  --output /private/tmp/youspeed-storage-prototype-20261026/geodesk/bw-runtime.osm.pbf
```

Pass that generated PBF to the same `build.py` helper with a distinct `--gol`
path. Verify stable ID coverage with `verify_source.py`; the host-only
`storage_geodesk_verify_bounds` target checks every original source road bound.

A source-complete node-filter experiment inventoried all 42 `maxspeed*` and
`traffic_sign*` keys and ORed their GOQL presence predicates. It preserved all
20,141 node IDs and the complete query digest, and reduced global native node
candidates from 301,066 to 63,475. It gave no material host latency gain: warm
p50 was 43.0 µs for all nodes versus 44.6 µs filtered (three repetitions of
20,397 queries). The final adapter therefore retains the safe all-node query;
this discarded optimization was not measured on phones. Its exact query and
raw measurements are retained in `results/node-prefilter-experiment.json` and
the associated before/after reports. Further node-query optimization remains a
limitation of this adapter rather than an established limit of GeoDesk.

Pinned upstream source links:

- [libgeodesk c59eba63575f94bd484177fe4220b464e4339ffc](https://github.com/clarisma/libgeodesk/tree/c59eba63575f94bd484177fe4220b464e4339ffc)
- [GOL builder 258dde35949e05185fb7615e79ab1a0a6268142a](https://github.com/clarisma/geodesk-gol/tree/258dde35949e05185fb7615e79ab1a0a6268142a)
- [gtl v1.2.0](https://github.com/greg7mdp/gtl/tree/v1.2.0)
- [cpp-httplib v0.18.3](https://github.com/yhirose/cpp-httplib/tree/v0.18.3)
