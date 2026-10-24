# Compact mobile map encoding investigation

Date: 23 October 2026. Scope: the actual BW 1.5 lookahead bundle, both native
clients, and established map/binary formats. This is a recommendation and
read-only measurement exercise; the installed bundle format has not changed.

## Recommendation

Use **custom, versioned binary runtime payloads** for road geometry, directed
graph data, relations and physical sign events. Initially store them as compact
blocks inside SQLite, reusing its existing spatial indexes, installation and
country/settlement machinery. Compare the same codec in an immutable sidecar
before committing to a completely custom archive. Keep the full SQLite build
database for generation, inspection, provenance and cross-format verification.

Start with the lookahead graph, then geometry reuse and evidence dictionaries.
This obtains the principal encoding savings while keeping the first migration
smaller. A fully indexed binary archive is a viable later container if its
measured size, I/O or update benefits justify replacing the remaining SQLite
catalog and indexes.

The largest immediate win is changing the representation of repeated graph
records and geometry. Switching container names alone will not deliver it.
Use established components: packed spatial indexes, delta/variable-length
integers, shared dictionaries, schema-defined arrays, independently compressed
blocks and a bounded native block cache.

## What is taking space

| BW artifact | Installed SQLite | Gzip download |
| --- | ---: | ---: |
| Original 1.5 runtime | 2,122,903,552 B | 695,751,651 B |
| New lookahead runtime | 3,099,021,312 B | 974,577,648 B |
| Increase | **976,117,760 B** | **278,825,997 B** |

Actual read-only SQLite page accounting found **zero freelist pages**. A routine
vacuum cannot reclaim a large deleted-page reserve. Page measurements use
[SQLite's `dbstat`](https://www.sqlite.org/dbstat.html), which reports table and
index storage separately.

| Major object | Bytes |
| --- | ---: |
| Settlement segments | 479,592,448 |
| Lookahead successor decisions | 280,993,792 |
| Lookahead directed segments | 271,626,240 |
| Lookahead segment unique index | 161,878,016 |
| Lookahead segment way index | 117,338,112 |
| Lookahead segment entry index | 87,547,904 |
| Road geometry | 169,156,608 |
| Full source sign inventory | 134,279,168 |
| Physical sign associations | 128,356,352 |

The five segment/successor/index objects total **919,384,064 B**. Including
lookahead node/way audit tables brings that subtotal to **959,037,440 B**.
This explains most of the new installed size. The graph has 4,346,282 directed
segments and equally many successor rows, including 4,061,612 explicit stops
and only 284,670 certified continuations. Repeated bounds, identifiers, status
strings and several B-trees are expensive for an immutable, narrowly queried
dataset.

The [measurement checkpoint](../output/map-encoding-investigation-2026-10-23/initial-dbstat-checkpoint.json)
contains exact byte counts. Further codec measurements are in
[the investigation output](../output/map-encoding-investigation-2026-10-23/).

Full category accounting puts topology, including its capability table, at
**959,045,632 B**. SQL B-tree indexes across the entire bundle occupy
795,869,184 B. There are 189,650,364 bytes of unused space inside allocated
B-tree pages; this is separate from the zero-page freelist and is not a promise
that vacuum can recover all of it. See
[storage-summary.json](../output/map-encoding-investigation-2026-10-23/storage-summary.json).

## Encoding measurements

A deterministic, uniform sample of **4,096 road geometries / 24,320 vertices**
used 559,385 bytes of JSON. Packed float64 coordinates used 393,224 bytes;
E7 integer coordinates with zigzag/delta variable-length encoding used
**120,951 bytes**, a **78.4% reduction in the sampled uncompressed bodies**.
All sampled road coordinates round-tripped exactly at E7.

With the same 256-row, zlib-level-6 block setup, JSON occupied 201,986 bytes
and the delta encoding **114,954 bytes**, a **43.1% reduction**. Plain float64
compressed to 306,771 bytes, worse than compressed JSON. Therefore, replacing
JSON with raw doubles alone is not an adequate download-size strategy.

Settlement geometry includes interpolated coordinates. E7 alone changed some
sample values by up to 5e-8 degrees, approximately 5.6 mm. That is a lossy
encoding even though the difference is small. Preserve exact values through
an exception stream or lossless float encoding; do not silently alter chainage,
station ownership or the inclusive 300 m decision. Complete geometry round-trip
validation is required before selecting an encoding.

These are measured **body samples**, excluding spatial indexes, block
directories, attributes and other sections. They are not a measured whole-bundle
size or a promise that the entire bundle will shrink by the same percentage.

A subsequent **lossless** E7-plus-float64-exception prototype preserved every
sampled coordinate value exactly:

| Geometry sample | JSON body | Lossless packed body | JSON in compressed blocks | Packed in compressed blocks |
| --- | ---: | ---: | ---: | ---: |
| Road ways, 4,096 rows | 559,385 B | 128,765 B | 201,986 B | 119,081 B |
| Settlement segments, 4,096 rows | 519,135 B | 134,252 B | 192,055 B | 125,868 B |
| Areas, 3,783 non-null rows | 1,848,214 B | 629,198 B | 576,753 B | 562,355 B |

Lossless compressed road geometry improved by **41.0%** and settlement geometry
by **34.5%** in those samples. Areas improved by only **2.5%**, because exact
floating-point exceptions are frequent. This is why a single advertised
compression ratio would misrepresent the likely whole bundle. Of the sampled
settlement segments, 2,948/4,096 had geometry exactly equal to their complete
road geometry, supporting a geometry-reference/deduplication prototype.
[Lossless sample evidence](../output/map-encoding-investigation-2026-10-23/lossless-geometry-samples.json).

Full-source follow-up confirmed **945,662 settlement rows** have geometry
byte-identical to the corresponding existing road geometry: **119,892,992 B**
of repeated coordinate JSON can be replaced by references without changing a
coordinate. Settlement evidence JSON uses **238,627,922 B** across 1,294,214
rows but contains only **50,595 distinct strings**. Exact string dictionary,
uint32 references and offsets measured **20,761,387 B**; independently compressed
dictionary blocks and references measured **6,942,491 B**, before new container
headers/indexes. This preserves the complete evidence text. Geometry reuse and
evidence deduplication are substantial additional opportunities beyond changing
the coordinate encoding itself.

There is additional full-source metadata duplication: all 1,085,790 admitted
ways have equal start/end keys, length and highway values across the road
endpoint and sign-direction views. Store those canonical fields once and expose
the separate logical views through the reader. A read-only query-plan check
also demonstrated that the segment unique index can serve the current-way
prefix lookup; removing potentially redundant indexes is an incremental option
to validate, not a measured production-safe change yet.
[Metadata duplication](../output/map-encoding-investigation-2026-10-23/road-metadata-duplicates.json),
[index-prefix plans](../output/map-encoding-investigation-2026-10-23/index-prefix-plans.json).

## Complete topology size prototype

The investigation also encoded the **entire** current topology into transient
packed blocks, preserving its existing conservative behavior:

| Representation | Measured bytes |
| --- | ---: |
| Current topology tables and indexes | **959,045,632** |
| Packed per-way bodies | 38,733,665 |
| Packed source-node audit data | 4,568,419 |
| Fixed way directory, 12 bytes per way | 13,029,480 |
| Packed total with audit and way directory | **56,331,564** |
| Independently compressed bodies with the same uncompressed way directory | **48,584,867** |

The uncompressed packed component is **94.1% smaller** than the SQLite
topology component. It stores one physical interval instead of duplicating
its bounds/nodes for both directions, retains both permission values, encodes
proof/status strings as enums, stores source ordinal/node deltas and keeps only
the certified successor payloads. Default stop is explicit in the complete
format semantics. Exact float64 chainage endpoints are retained; there is no
geometry or chainage quantization in this prototype.

All 4,346,282 source rows were processed and their direction-pair, geometry,
node, permission and successor invariants checked. **4,096 ways** were decoded
and checked for exact round-trip equivalence. This is not yet exhaustive
decode verification of every way. The size includes all 1,941,024 source-node
audit records and a directory for 1,085,790 ways; the compressed result uses
independent 64 KiB zlib-level-6 bodies. It excludes the archive header,
compressed-block directory, checksums and implemented native random-access
reader. No binary replacement was installed and no binary-reader latency was
measured. [Prototype evidence](../output/map-encoding-investigation-2026-10-23/topology-lossless-prototype.json).

Replacing just the current topology allocation with the uncompressed packed
component gives a **content-size projection of about 2.20 GB installed**, before
new container overhead or rebuilding the remaining SQLite file. That would
remove about 0.90 GB from the current 3.10 GB, while leaving most of the original
2.12 GB base to optimize. It is not a measured complete output bundle. This
supports doing the topology sidecar first, then geometry/settlement reuse.

## Formats considered

| Format | Useful properties | Fit for YouSpeed |
| --- | --- | --- |
| Custom packed structures in SQLite blocks, then an archive/sidecar if justified | Exact feature-specific fields, compact adjacency, direct station lookup and independently compressed blocks | Recommended staged runtime direction; requires a versioned writer, two compatible readers and a shared conformance suite |
| Valhalla graph tiles | Spatially partitioned road graph, directed edges, restrictions and cached/mapped tile access | Closest existing architectural model; adopting the whole routing stack would also introduce its graph-building and interpretation choices |
| OsmAnd OBF / Organic Maps MWM | Mature mobile binary containers with map, search and routing sections | Useful designs to study; adopting either ecosystem is a larger integration than this app needs and still requires a contract for physical sign stations and proofs |
| PMTiles with MVT, or Mapsforge map files | Compact tiled map distribution and viewport access | Good for a future visual basemap; normal rendering geometry is not sufficient evidence for exact source-node topology and physical sign chainage |
| FlatGeobuf | Lossless feature geometry, optional packed Hilbert R-tree, random spatial reads | A reasonable geometry-section prototype; directed connectivity, relation scope and station/rule indexing still need additional structures |
| OSM PBF | String dictionaries, independently compressed blocks and delta-coded source coordinates/IDs | Excellent source/build input; ordinary PBF does not supply the app's ready-to-query spatial, directed-rule and station indexes |
| Lean SQLite with packed blobs | Retains existing readers/transactions while reducing JSON and repeated keys | Useful intermediate baseline; SQL B-trees and duplicate graph records still need deliberate redesign |

These assessments are design inferences from the formats' published contracts:

- [Valhalla tile structure](https://valhalla.github.io/valhalla/tiles/) and
  [graph reader implementation](https://github.com/valhalla/valhalla/blob/master/src/baldr/graphreader.cc)
  document spatial graph tiles and mapped/cached reading.
- [OsmAnd OBF](https://download.osmand.net/docs/technical/osmand-file-formats/osmand-obf/?current-os=ios)
  describes its sectioned mobile container; [Organic Maps' generator](https://github.com/organicmaps/organicmaps/blob/master/tools/python/maps_generator/README.md)
  describes MWM generation and application/generator version coupling.
- [PMTiles v3](https://github.com/protomaps/PMTiles/blob/main/spec/v3/spec.md)
  specifies a compact tile directory and compressed tile payloads. It can carry
  custom payloads, but the graph semantics would remain our own contract.
  [MVT](https://mapbox.github.io/vector-tile-spec/) uses integer tile-grid
  geometry; [Mapsforge](https://github.com/mapsforge/mapsforge/blob/master/docs/Specification-Binary-Map-File.md)
  uses tiled/zoom-indexed map data and microdegree coordinates. Converting exact
  source geometry to a rendering representation requires explicit precision and
  connectivity handling.
- [FlatGeobuf's specification](https://github.com/flatgeobuf/flatgeobuf)
  defines feature FlatBuffers and an optional packed spatial index. Its internal
  compression is separate; a seekable compression wrapper is possible.
- [OSM PBF](https://wiki.openstreetmap.org/wiki/PBF_Format) documents its string
  table and dense delta-coded records. This is a model for compact source data,
  not a ready-made replacement for the app's runtime queries.
- [SQLite `WITHOUT ROWID`](https://www.sqlite.org/withoutrowid.html) can help
  small composite/string-keyed tables. It is not a universal improvement for
  integer-primary-key tables or large geometry payloads.

## Proposed runtime layout

1. **Header and directory.** Format/capability versions, source snapshots,
   country/coverage, section offsets and lengths, checksums and compatibility
   flags. Use 64-bit archive offsets even if individual blocks use local 32-bit
   indexes. Reject incomplete, incompatible or corrupt capability sections.
2. **Road IDs, attributes and exact geometry.** Retain original 64-bit OSM IDs
   for provenance and logs; use dense local IDs in links. Store each geometry
   once, with reversed travel represented by a direction bit. Encode source-grid
   coordinates exactly and preserve exceptions; dictionary-code names, refs,
   tag values and repeated status enums.
3. **Compact graph and relation arrays.** Store segment breaks once per way,
   directional permission bits and sorted relation memberships. Store certified
   successors sparsely. Absence means stop only inside a verified complete
   capability; it never implies permission. Endpoint identity, restrictions,
   raw relation intersection and all existing conservative stops must survive.
4. **Physical sign event/rule streams.** Sort by dense way ID, direction and
   chainage. Store source/snapshot dictionaries once, preserve sign identity and
   exact applicability, and retain rejected/unknown stations as barriers. Keep
   physical origins separate from propagated rule intervals.
5. **Settlement/context sections.** Store geometry references and typed context
   intervals instead of repeatedly embedding full geometry/evidence JSON.
   Preserve exact chainage and the existing inside/outside/unknown semantics.
6. **Audit and attribution.** Preserve all source evidence in the build archive.
   Classify mobile consumers before moving audit-only records to an optional
   companion package; runtime-required provenance and uncertainty remain local.

[FlatBuffers](https://flatbuffers.dev/) supplies generated Swift and Kotlin
accessors and schema evolution. Its [aligned scalar/vector layout](https://flatbuffers.dev/internals/)
is suitable for typed fixed arrays or block envelopes. Use packed byte streams
for delta-coded geometry; one FlatBuffer table per tiny edge would retain
unnecessary per-object overhead.

Start by comparing uncompressed mapped arrays with independently compressed
64–256 KiB blocks and a bounded decoded-block cache. The block size is a
benchmark parameter, not a chosen final constant.
[Seekable Zstandard](https://github.com/facebook/zstd/blob/dev/contrib/seekable_format/zstd_seekable_compression_format.md)
provides independently decompressible frames and a seek table, allowing installed
data to remain compressed while reading local ranges. Whole-file gzip currently
requires the 3.1 GB decoded database on disk; a different download compressor
alone would not reduce that installed footprint.

## Migration and decision gates

- Prototype compact topology blocks first against the full BW graph. Use a
  small SQLite lookup/catalog layer initially and compare a sidecar using the
  same codec; measure both complete containers rather than assuming the file
  extension determines the saving.
  Compare every permission, source endpoint, certificate, stop and relation
  membership with SQLite. Measure the complete sidecar including indexes and
  headers, not just record bodies. A reasonable first acceptance target is
  **at most 64 MiB for the complete topology section**, based on the 56.3 MB
  uncompressed prototype; that is a proposed target, not a delivered file.
- Build geometry/settlement prototypes with exact round-trip checks, then measure
  the complete installed/archive and transfer sizes. Establish a whole-bundle
  target from those results; no reliable final target is measured yet.
- Run both native readers against the same corpus, generated adversarial graph
  cases and source-backed approach/passage sequences. Compare complete matcher
  outputs and boundary behavior, including missing/corrupt blocks and tile-edge
  crossings. Retain SQLite fallback during migration.
- Repeat full-bundle physical-device profiling with new-connection and warm
  workloads, allocation/cache limits and all suppressed attempts. Existing warm
  preview p95 is about 3.0 ms on iPhone and 2.3 ms on Android, so the primary goal
  is reducing storage without degrading that behavior. Full lookup workloads
  and native-reader boundaries differ between platforms; see
  [the physical validation record](UPCOMING_SPEED_LIMIT_PHYSICAL_VALIDATION_2026-10-23.md).
- Add versioned regional/block delivery and atomic rollback only after format
  parity. The current topology delta gate remains in place. A storage migration
  must not change the governed reference state-machine policy or either
  interpreter's semantics.
