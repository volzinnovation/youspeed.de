# OSM runtime storage research — 26 October 2026

**Recommendation:** evaluate an immutable, spatially partitioned binary road
graph for the downloaded runtime bundle. Borrow graph organization from
Valhalla, sectioned storage and compression from Organic Maps, and spatial
index/dictionary ideas from GeoDesk. Keep mutable trips, observations and
uploads in their existing transactional stores. PMTiles with MVT or stable MLT
is an optional rendering artifact, not the authoritative road/sign graph.

The comparison must include an optimized SQLite baseline. Our measurements show
large gains from changing representation while retaining SQLite; simply
replacing the database engine does not account for most demonstrated savings.
No application reader, published bundle, policy, or attached device was changed
for this research.

## What Ascend Maps actually does

The user's reference, [styluslabs/maps](https://github.com/styluslabs/maps), is
Ascend Maps. Source inspection was pinned to Maps commit
`bd24e058b29ca0371ba7fc0ed048857d07c38378`, its Tangram NG submodule
`2adb6eb9a1305af558df90ec127e5f9d9bbd8ccb`, and geodesk-tiles
`5b6c94c3fc293c96de46f1538f77cc90898797e4`.

Ascend combines compact vector tiles, an MBTiles SQLite cache and separate
SQLite offline-search indexes. Tangram's cache maps tile coordinates to
compressed blobs, deduplicates tile content and tracks offline ownership.
Search uses `fts1.sqlite`, a POI table and FTS5.
[Tile-cache implementation](https://github.com/styluslabs/tangram-ng/blob/2adb6eb9a1305af558df90ec127e5f9d9bbd8ccb/core/src/data/mbtilesDataSource.cpp#L23-L80),
[search implementation](https://github.com/styluslabs/maps/blob/bd24e058b29ca0371ba7fc0ed048857d07c38378/app/src/mapsearch.cpp#L140-L175).

Its tile generator queries GeoDesk, produces MVT/PBF and compresses individual
tiles with gzip. PMTiles support and integrated offline Valhalla routing are
still listed on the inspected README's roadmap; the included Valhalla plugin
calls a remote service. Ascend demonstrates spatial chunking and separate
indexes, rather than elimination of SQLite.
[Generator](https://github.com/styluslabs/geodesk-tiles/blob/5b6c94c3fc293c96de46f1538f77cc90898797e4/tilebuilder.cpp#L27-L118),
[roadmap](https://github.com/styluslabs/maps/blob/bd24e058b29ca0371ba7fc0ed048857d07c38378/README.md#roadmap),
[routing plugin](https://github.com/styluslabs/maps/blob/bd24e058b29ca0371ba7fc0ed048857d07c38378/assets/plugins/valhalla-osmde.js#L81-L104).

Its stock transportation tiles cannot replace YouSpeed's semantic data. The
inspected generator clips roads, uses a 4096-coordinate extent and simplifies
lower zooms. Its road attributes include plain `maxspeed` but not our complete
directional/conditional rules; `oneway=-1` is a commented TODO. Road features
also lack the source-ID attributes supplied to selected other layers.
[Road attributes](https://github.com/styluslabs/geodesk-tiles/blob/5b6c94c3fc293c96de46f1538f77cc90898797e4/ascendtiles.cpp#L338-L426),
[source IDs](https://github.com/styluslabs/geodesk-tiles/blob/5b6c94c3fc293c96de46f1538f77cc90898797e4/ascendtiles.cpp#L725-L733),
[geometry processing](https://github.com/styluslabs/geodesk-tiles/blob/5b6c94c3fc293c96de46f1538f77cc90898797e4/tilebuilder.cpp#L357-L385).

GeoDesk itself is the more relevant non-SQL alternative behind this pipeline.
Its GOL object library retains OSM nodes, ways and relations, with spatial tiles,
indexes and global coded strings. The pinned C++ implementation uses mapped
storage and page references. It merits a separate runtime/build-side evaluation;
upstream size and speed claims are not YouSpeed measurements or evidence of
ready-made Swift/Kotlin integration.
[GeoDesk design](https://docs.geodesk.com/why-geodesk),
[feature store](https://github.com/clarisma/libgeodesk/blob/a6485b48a3d9d8922f522ad2b32c1b6eec430cf4/include/geodesk/feature/FeatureStore.h#L47-L90),
[mapped storage](https://github.com/clarisma/libgeodesk/blob/a6485b48a3d9d8922f522ad2b32c1b6eec430cf4/src/clarisma/libero/FreeStore.cpp#L14-L157).

## Containers, encodings and graph structures are different choices

| Candidate | Actual purpose | YouSpeed implication |
| --- | --- | --- |
| [MBTiles 1.3](https://github.com/mapbox/mbtiles-spec/blob/master/1.3/spec.md) | SQLite container for tile blobs and metadata | A compact tile payload can live in SQLite. MBTiles is not an alternative database engine or road graph. |
| [PMTiles v3](https://github.com/protomaps/PMTiles/blob/main/spec/v3/spec.md) | Read-only single-file tile archive with compact directories, spatial ordering and content reuse | Useful local/range-addressed archive for display tiles. Repacking/updating a large archive still needs an explicit strategy. |
| [MVT 2.1](https://mapbox.github.io/vector-tile-spec/) | Protobuf feature encoding with tile-local integer geometry and shared attribute tables | Broad rendering compatibility. It does not define road connectivity, physical sign identity or chainage; clipping/simplification belong to the producer. |
| [MLT v1](https://maplibre.org/maplibre-tile-spec/specification/v1/) | Stable column-oriented vector-tile encoding, with typed streams and specialized compression | Useful encoding principles and a display candidate. Its geometry topology is not a navigable directed-road graph. |
| [Mapsforge](https://github.com/mapsforge/mapsforge/blob/master/docs/Specification-Binary-Map-File.md) | Compact mobile rendering file with tile indexes, tag dictionaries and delta-coded geometry | Relevant offline-map precedents; its rendering schema and predominantly Java ecosystem do not directly satisfy our graph and iPhone reader needs. |
| [FlatGeobuf](https://flatgeobuf.org/) | Static feature collection with FlatBuffers and optional packed Hilbert R-tree | Strong candidate for polygon/feature sections or a reference spatial index. Directed connectivity and event/rule relationships still need a model. |
| [GeoDesk GOL](https://docs.geodesk.com/java/libraries) | OSM-native object storage with tiles, relations and spatial queries | Closest existing general OSM datastore candidate; evaluate its dependency/integration cost against a smaller purpose-specific runtime. |

MLT is worth following, but **v2 is currently experimental** and explicitly
permits incompatible layout changes without a version bump. Its new nested
properties and Z/M support must not be assumed available from a reader's v1
support. A durable display experiment should pin a supported format and reader.
[Official v2 status](https://maplibre.org/maplibre-tile-spec/specification/v2/).

Rendering tiles can be extended with custom attributes, but then we still have
to define and validate cross-tile connectivity, canonical IDs, exact geometry,
conditions and event anchoring. A generic MVT/MLT decoder does not solve these
requirements. A tile's feature selection at a display zoom must never decide
which roads or signs the matching/runtime can know about.

## What routing applications provide

**Valhalla:** nodes reference ranges of outgoing directed edges in a
forward-star layout. Fixed node/edge arrays are separated from variable-length
edge information, including shared shape/name data. This is a good model for
nearby-edge matching followed by bounded traversal without repeated SQL joins.
[Node arrays](https://github.com/valhalla/valhalla/blob/master/valhalla/baldr/nodeinfo.h),
[graph tiles](https://github.com/valhalla/valhalla/blob/master/valhalla/baldr/graphtile.h),
[edge information](https://github.com/valhalla/valhalla/blob/master/valhalla/baldr/edgeinfo.h).

**Organic Maps:** its `.mwm` container has separately addressable sections for
geometry, routing and other data. Geometry uses integer/delta/varint encoding.
Its sparse value maps use presence bit vectors, rank/select and Elias–Fano
offsets with block decoding: useful precedents for optional speed/rule/event
data, although simpler sparse arrays may suffice for us.
[Sectioned container](https://github.com/organicmaps/organicmaps/blob/master/libs/coding/files_container.hpp),
[geometry coding](https://github.com/organicmaps/organicmaps/blob/master/libs/coding/geometry_coding.hpp),
[sparse maps](https://github.com/organicmaps/organicmaps/blob/master/libs/coding/map_uint32_to_val.hpp).

**GraphHopper:** sequential node/edge records, a separate geometry store and
memory-mapped `DataAccess` are another established design. Its Java code is
less directly suited to a common native iPhone/Android reader.
[Layout](https://github.com/graphhopper/graphhopper/blob/master/core/src/main/java/com/graphhopper/storage/BaseGraphNodesAndEdges.java),
[mapped access](https://github.com/graphhopper/graphhopper/blob/master/core/src/main/java/com/graphhopper/storage/MMapDataAccess.java).

These are architectural precedents, not a recommendation to ship an entire
routing engine just to obtain its file format. Compact local indexes are also
not stable identities: Valhalla documents that graph IDs index tile arrays.
Keep source/event identity separate and scope compact references to the pack
generation.
[GraphId](https://github.com/valhalla/valhalla/blob/master/valhalla/baldr/graphid.h).

## Measurements on our complete local geometry column

A read-only export used the existing **3.099 GB lookahead predecessor** of the
active conditional bundle. It covered **all 1,085,790 ways and 6,479,751 points**
in `way_geom`. This is a geometry experiment, not a complete region conversion.

The codec uses latitude/longitude integers at 1e-7 degrees, delta encoding and
unsigned varints with ZigZag for signed differences. It tests exact restoration
of the source's decoded floating-point coordinates; a double-precision fallback
exists but **no way required it**. The source and decoded tuple hashes match.
No vertex was simplified, clipped, reordered or dropped.

| Representation | Decimal MB |
| --- | ---: |
| Current allocated SQLite `way_geom` table | **169.16** |
| Actual JSON geometry payload in that table | 149.09 |
| Binary geometry payload only | 33.24 |
| Binary geometry + 64-bit way-ID/offset index | **50.62** |
| Independently compressed binary blocks + indexes | **47.90** |
| Independently compressed original JSON blocks + comparable indexes | **67.37** |

Compression uses zlib level 6 in independent 256 KiB blocks. The two compressed
figures include the measured payload, 16 bytes/way for IDs/offsets and an
allowance of 16 bytes/block plus 64 header bytes. Complete production container
metadata, checksums and readers are not implemented. The files contain the
payloads and way-offset index; block-directory/header overhead is calculated.

The raw binary layout is approximately **70% smaller than this allocated
geometry table**. With block compression, binary remains about **29% smaller
than compressed JSON with comparable indexes**. The latter is a viable
representation improvement even inside SQLite BLOBs. Neither comparison
establishes device latency or a full-bundle reduction of the same percentage.

The earlier successor experiment provides a useful control:

| Same certified successor tuple set | Decimal MB |
| --- | ---: |
| Existing dense table, including explicit STOP rows | 280.99 |
| Sparse SQLite database | **7.68** |
| Sorted flat 64-bit triples | **6.83** |

All **284,670 certified tuples** match in the sparse SQLite and binary exports.
The extra saving from eliminating SQLite here is only about **0.84 MB**; almost
all of the improvement comes from omitting redundant STOP rows and repeated
proof strings. Any new format must still certify completeness and preserve
STOP on missing, uncertain or unsupported successors.

No full geometry/spatial/settlement/sign/rule pack, native reader, mobile memory
profile or cold/warm device benchmark was built. These results justify a
prototype, not a promised final download size.

## Proposed runtime structure

Use one immutable region pack, with a small versioned directory and independently
addressable sections. A tile/cell here is a spatial storage partition, independent
of display zoom.

| Section | Representation | Runtime operation |
| --- | --- | --- |
| Spatial directory | Packed R-tree or measured fixed-grid/Hilbert index over edge bounds | Find every nearby candidate, including long edges and partition borders |
| Roads and directed edges | Dense records with local integer references, typed flags and dictionary IDs | Read speed, legality, road identity and connectivity |
| Shared geometry | Source-precision delta-coded stream referenced by segment ranges and both directions | Project fixes and compute local tangents without JSON decoding |
| Adjacency | Offset/count arrays plus sparse certified continuations and explicit border links | Traverse only proven continuations; stop at ambiguity |
| Road events | Per-directed-edge ranges sorted by chainage | Find the next speed sign or actual town boundary; preserve physical origin |
| Rules | Deduplicated typed conditional expressions plus unknown/raw evidence where required | Reevaluate the existing rule semantics without reparsing repeated strings |
| Settlement | Shared geometry/range references and compact locality evidence | Resolve context without copying complete road shapes into every evidence record |
| Dictionaries/provenance | Shared strings, source/snapshot identities and stable event identities | Keep attribution and callback ownership independent of local array indexes |

Preserve current chainage and rule-station values exactly during the first
conversion; centimetre rounding would be an independent behavior change near
the existing 0.01 m comparisons. Keep source vertices at their verified
precision and avoid deriving canonical chainage from display geometry. Regional
clipping must not turn an omitted neighboring road into proof of no branch.

Map the small indexes and suitable fixed sections into memory; load/decompress
variable blocks through a bounded cache. Compressed blocks require decoding:
memory mapping does not make them automatically zero-copy. Start with ordinary
arrays and dictionaries; add succinct encodings only where measured savings
justify their decoder and validation cost.

Prefer one tested C/C++ reader behind Swift and JNI interfaces if the prototype
proves useful. Keep ownership/lifetime and malformed-file checks in that reader,
and expose typed results to the existing matchers. Shared bytes and semantics
matter more than selecting a particular serialization library. A GeoDesk-backed
implementation should remain an explicit comparator before choosing to own a
custom format.

Mutable trips, observations, upload state and corrections can continue using
SQLite. Their transactions and recovery requirements differ from a compiled,
read-only road snapshot. Offline operation must continue to use installed
verified data; this storage study introduces no automatic network retrieval.

## Decision experiment and migration boundary

Compare these with **identical semantic coverage**:

1. **Optimized SQLite:** sparse successors, binary/compressed geometry BLOBs,
   shared dictionaries and evidence outside the hot runtime where unused.
2. **Packed graph prototype:** arrays, shared geometry, ordered events and
   packed spatial indexes behind the same typed lookup contract.
3. **GeoDesk comparator:** measure actual native integration and whether the
   existing OSM store reduces the custom storage work enough to justify it.

Optional display tests can separately compare MBTiles/PMTiles and MVT/MLT.
Smaller rendering tiles are not an equivalent runtime dataset.

Use the complete BW snapshot and recorded-drive queries, including settlement
lookups, opposite directions, time-restricted limits, road splits, real town
boundaries, turnarounds and region borders. Compare all candidates, selected
roads, projected positions, chainage, speed/rule provenance, successor STOP
decisions and event identity before comparing latency. Measure installed and
compressed bytes, cold/warm p50/p95/p99, resident memory, cache misses and
opening time on both phones. Explicitly test corrupt/truncated blocks,
unsupported versions, interrupted activation and missing border data. A valid
pack should fail closed rather than inventing a rule or continuation.

Keep SQLite readers as the reference during an opt-in shadow comparison. New
storage must not alter the protected speed-reference policy or silently repair
its inputs by changing their meaning. Camera/city events overtaking each other
still require the deterministic encounter/publication design in
[the preceding investigation](IPHONE_EVIDENCE_AND_BUNDLE_REDESIGN_2026-10-26.md).
Storage improvements can make that data smaller and cheaper to query; they do
not solve event ordering by themselves.

For implementation reuse, the inspected projects declare
[Maps GPL-3.0](https://github.com/styluslabs/maps/blob/bd24e058b29ca0371ba7fc0ed048857d07c38378/LICENSE),
[Tangram NG MIT](https://github.com/styluslabs/tangram-ng/blob/2adb6eb9a1305af558df90ec127e5f9d9bbd8ccb/LICENSE),
[libgeodesk LGPL-3.0](https://github.com/clarisma/libgeodesk/blob/a6485b48a3d9d8922f522ad2b32c1b6eec430cf4/LICENSE),
[Valhalla MIT](https://github.com/valhalla/valhalla/blob/master/COPYING), and
[Organic Maps Apache 2.0](https://github.com/organicmaps/organicmaps/blob/master/LICENSE).
Architecture comparison and importing implementation code are separate decisions.

## Reproducible local artifacts

`/private/tmp/youspeed-storage-research-20261026/` contains
`geometry_experiment.py`, full geometry payload/index exports,
`geometry/geometry-results.json`, `certified-successors.bin`,
`successor-results.json`, and a source/artifact receipt. The source database was
opened read-only with `immutable=1`. The earlier SQLite `dbstat` and sparse
successor prototype remain under
`/private/tmp/youspeed-reference-review-20261026/`. No private device data was
needed for these storage experiments.
