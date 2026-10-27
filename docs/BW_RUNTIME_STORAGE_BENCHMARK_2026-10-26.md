# Full-BW storage prototype — 26 October 2026

Completed on 27 October 2026, including the attached iPhone and Android.

The packed binary prototype, optimized SQLite baseline and native GeoDesk
comparator are built. Full-source verification, all three backends on both
phones, direct cross-phone lookup comparison and restricted amendment checks
pass. Packed is smallest and has the lowest warm lookup latency on both phones.
Its higher mapped RSS and slower opening remain important tradeoffs.

The measurements favor continuing with a packed immutable base and a
small mutable correction layer. Optimized SQLite remains a credible baseline:
most size improvement comes from representation and deduplication, with a smaller
additional saving from the packed container. This is an isolated storage/query
prototype; it does not replace either driving app or change the protected speed
reference policy. It does not establish that a storage change fixes the observed
camera/city-entry/ahead ordering defects.

## Dataset and identical-result checks

The complete active BW source is the 23 October v1.5 journal/conditional bundle:

| Source | Bytes / SHA-256 |
|---|---|
| Original SQLite | 3,185,627,136 bytes; `e973d279de2803b13037b9e87132be72f28a22d8f9c9bbef79d73093772b1849` |
| Original gzip | 989,583,784 bytes |
| Pinned complete BW PBF | `1856f4ac7c18435e17d74c7ba24a7b21b3a1231e60449851890dc0109638ded3` |

Verification reads **all 1,085,790 ways and 6,479,751 points**. Original, packed
and optimized SQLite geometry plus per-way semantic tuples have the identical
SHA-256 `03d96227f0ed96a7784867fd2cd1c29bfdc4a561dac43f3f134c827c0bf7ceea`.
The compact delivery reconstructs all **50 original logical tables** with exact
row counts and canonical table hashes. SQLite implementation-owned R-tree shadow
pages are excluded; logical R-tree rows are included. Conditions, compiled rule
evidence, source tags, topology, sign inventory, settlement evidence, original
event chainage and provenance are retained.

The road corpus has 586 deterministic, stratified full-region queries including
conditional/directional roads, physical events, town signs, motorway cases,
region edges and empty probes. It returns 6,446 road results. All three native
host backends are byte-identical, and independent original-SQL candidate sets
match. An independent Python projection differs by at most 9.1e-13, below the
1e-7 absolute acceptance tolerance. Every Android backend produces the same
road digest `387b12eb0c5aa5e6`; every iPhone backend produces
`4ce9f9d93a352e83`. Exact exports are bound back to each timed run by recomputing
its digest. All 6,446 result IDs, speed codes, geometry and semantic checksums
match exactly across both phones. Native JSON outputs are byte-identical across
backends within each phone. Across phones, latitude/longitude match exactly;
maximum chainage difference is **3.1974e-13 m**, and maximum distance difference
is **2.8422e-14 m**, far below the 1e-7 tolerance. The strict comparator checks
**38,676 road results** across six backend/device runs. Different libm output
formatting explains the differing platform digests; the numerical comparison
is verified rather than inferred from those digests.

The GeoDesk spatial input is filtered directly from the **entire pinned PBF** to
every admitted source road, every generic speed node and all referenced original
way nodes, preserving their real IDs, coordinates and tags. This is full BW
coverage in the same runtime scope, rather than a small regional sample. A full
ID scan finds zero missing roads/nodes, including closed area ways. All original
road bounds also match the GOL projected bounds. Canonical E7 post-filtering and
geometry projection use the common sidecar so no GeoDesk geometry quantization
is silently substituted for source geometry.

Receipts: [full source audit](/Users/raphaelvolz/Github/youspeed.de/shared/runtime-storage-prototype/results/full-source-verification.json),
[all 50 table hashes](/Users/raphaelvolz/Github/youspeed.de/shared/runtime-storage-prototype/results/compact-coverage-verification.json),
[independent road queries](/Users/raphaelvolz/Github/youspeed.de/shared/runtime-storage-prototype/results/query-verification.json),
[phone summary](/Users/raphaelvolz/Github/youspeed.de/benchmarks/runtime-storage/results/phone-summary.json).

## Complete data size

Decimal MB; gzip level 6, summed independent streams. These totals count native
road and node data, the losslessly retained global tables, index and manifest.
They exclude the app/native library and common unchanged rules/pictogram assets.
They add generic OSM node coverage that was absent from the original SQLite.

| Candidate | Installed MB | Gzip MB | Installed saving vs original |
|---|---:|---:|---:|
| Packed | 748.54 | 702.20 | 76.5% |
| Optimized SQLite | 841.57 | 738.89 | 73.6% |
| GeoDesk + canonical SQLite | 936.14 | 802.77 | 70.6% |

The packed road file itself is 450.62 MB versus 542.27 MB for optimized SQLite.
Both share a 292.67 MB global archive retained conservatively for exact original
table reconstruction; its contents are not a native random-access event API.
Packed nodes add 5.07 MB versus 6.45 MB for SQLite nodes.

The fair-scope GOL is 94.56 MB, but the current GeoDesk integration also needs
the 542.27 MB canonical road database and 6.45 MB node sidecar. Its **complete
936.14 MB cost** is the relevant comparison. A separate all-OSM BW GOL is
897.40 MB and includes unrelated buildings, POIs and other roads; that broader
file is retained as supplementary evidence and is not used in the primary
size or phone comparison. A future GOL-native semantic implementation could
change the hybrid cost and requires its own correctness validation.

Packed saves another 11.1% installed / 5.0% gzip versus optimized SQLite. Its
gzip total is 29.0% below the original gzip. Full component bytes and SHA-256:
[size inventory](/Users/raphaelvolz/Github/youspeed.de/shared/runtime-storage-prototype/results/complete-sizes.json).

## Attached Android measurements

Moto g86 5G, Android API 36, arm64-v8a. Release native executable, NDK
30.0.16248370, bundled SQLite 3.51.0. The normal Android app is not replaced.
Every backend starts in a fresh process, runs one process-first pass and three
warm repetitions. Process-first does **not** mean the OS file cache was cleared.
Order is SQLite, GeoDesk, packed. The final thermal-service status was light
(1); these are practical device measurements, not a controlled thermal lab.

Road timings include spatial query, exact source geometry decode/projection and
full per-way semantic record decompression/checksum. They do not run the full
production matcher, conditional interpreter, camera pipeline or ahead-state
reducer. Median speed differences apply to this kernel and corpus.

| Backend | Open ms | Warm p50 ms | p95 ms | p99 ms |
|---|---:|---:|---:|---:|
| Packed | 58.09 | 4.175 | 12.302 | 18.422 |
| Optimized SQLite | 23.79 | 5.365 | 15.548 | 23.191 |
| GeoDesk hybrid | 3.23 | 5.971 | 16.382 | 23.702 |

Packed's warm median is 22.2% lower than optimized SQLite and 30.1% lower than
the measured GeoDesk hybrid. Open includes packed index CRC verification; it
varies with caches and must not be inferred from warm-query performance.
SQLite uses an 8 MiB page cache, mmap disabled, plus the same bounded 4 MiB
semantic-block cache used by packed. Generic-node SQLite uses a 4 MiB page cache.

Memory below is the process snapshot **after the road phase**, before node and
correction probes. MiB = 1,048,576 bytes. RSS and PSS come from the same
`smaps_rollup` read. Anonymous PSS delta compares that snapshot with the
pre-reader baseline. RSS includes clean mapped file pages and is not a measure
of heap allocation; the full raw snapshots are retained.

| Backend | RSS MiB | PSS MiB | Anonymous PSS delta MiB |
|---|---:|---:|---:|
| Packed | 314.64 | 312.07 | 6.11 |
| Optimized SQLite | 20.54 | 17.97 | 15.02 |
| GeoDesk hybrid | 61.81 | 59.21 | 15.16 |

Packed touches many scattered file pages over this regional corpus, so its
resident mapped footprint is materially larger despite lower anonymous memory.
This must be tested in the real long-running app under memory pressure before
adoption. Raw kernel high-water RSS is also recorded; Android's asynchronous
kernel accounting can report a lower high-water value than current smaps RSS.
Apple physical footprint is not available on Android and is recorded as null.

## Attached iPhone measurements

iPhone 14 Pro, iOS 26.6.2, Release native UIKit harness, the same bundled SQLite
3.51.0 and shared kernels. The accepted fresh-process runs took place on
27 October, 09:06:44–09:07:09 Europe/Berlin. Order was SQLite, GeoDesk, packed;
each ran one process-first pass and three warm repetitions. Apple thermal state
stayed **nominal (0)** before and after every run. Earlier interrupted attempts
and the preliminary manually opened SQLite run are excluded from these tables.
Progress markers are written outside the timed phases.

| Backend | Open ms | Warm p50 ms | p95 ms | p99 ms |
|---|---:|---:|---:|---:|
| Packed | 96.00 | 0.980 | 2.870 | 4.318 |
| Optimized SQLite | 2.29 | 1.600 | 4.425 | 6.636 |
| GeoDesk hybrid | 4.47 | 1.445 | 4.189 | 6.252 |

Packed's warm median is **38.8% lower than SQLite** and **32.2% lower than the
GeoDesk hybrid** on iPhone. GeoDesk beats SQLite's road median here, unlike on
Android; conclusions about their relative speed must remain platform-specific.
Packed opening includes its index integrity scan and is materially slower.

The following snapshots are taken after the road phase, matching the Android
measurement boundary. RSS is Mach resident size. Physical footprint is Apple's
separate task-memory ledger counter; it is not interchangeable with Android
anonymous PSS or process RSS. Deltas compare against the same process before
opening the reader. UIKit makes absolute iPhone and Android CLI process
baselines different; compare backends within each platform.

| Backend | RSS MiB | RSS delta MiB | Apple physical footprint MiB | Footprint delta MiB |
|---|---:|---:|---:|---:|
| Packed | 279.58 | 254.47 | 15.00 | 8.55 |
| Optimized SQLite | 43.83 | 19.63 | 25.03 | 18.95 |
| GeoDesk hybrid | 64.83 | 40.58 | 25.34 | 19.23 |

The iPhone confirms that mapped resident pages and physical-footprint accounting
tell different parts of the memory story. Packed has the lowest footprint
counter here, but its **279.58 MiB resident mapped footprint** still matters
under memory pressure. This experiment does not establish long-running app
memory-pressure behavior or a safe production memory ceiling.

## Generic speed-sign nodes and restricted amendments

Extraction preserves 20,141 original nodes with every source tag, exact E7
coordinate and 10,922 explicit way memberships, including original double
chainage and vertex ordinal. There are 12,947 nodes without an admitted-road
membership. Their identity and data remain queryable; no nearby-road assignment
is invented. Qualified maxspeed keys, conditional values, generic/nonnumeric,
unlimited, variable and end-sign data are retained.

All source records compare byte-for-byte and all 20,397 queries (every node
center plus 256 sparse/empty probes) match. Both phones and host node digests are
`f16a6da37efa217d` for all backends. Metadata is decompressed and checked on every
hit, rather than timing a coordinate-only lookup.

| Backend | Android node p50 µs | p95 µs | p99 µs |
|---|---:|---:|---:|
| Packed | 8.923 | 47.692 | 88.385 |
| Optimized SQLite | 19.692 | 76.615 | 137.769 |
| GeoDesk hybrid | 410.538 | 1,018.15 | 1,630.46 |

| Backend | iPhone node p50 µs | p95 µs | p99 µs |
|---|---:|---:|---:|
| Packed | 4.667 | 27.708 | 52.084 |
| Optimized SQLite | 8.000 | 37.167 | 69.916 |
| GeoDesk hybrid | 27.208 | 65.000 | 102.875 |

The current GeoDesk adapter queries all native node candidates, then joins
canonical IDs. A source-complete 42-key GOQL filter preserved correctness but
gave no material host gain and was reverted. This is a limitation of this
adapter, not proof of GeoDesk's best possible node performance.

The separate correction prototype supports stable OSM way/node identities and
new local sign IDs, direction/range, validity windows, restriction ASTs and raw
tags, provenance, expected-revision conflict checks, immutable history and
tombstones. Numeric amendment preserves the condition instead of replacing a
restricted limit with an unrestricted number. Base files stay immutable;
corrections can survive a new pack through source-ID/fingerprint rebasing.
Changed/split targets require review; unmatched or unbound sign nodes remain
unresolved. Generic nodes need a proven directed association and passage before
they may become an applicable event. Camera/map authority remains external.

Every backend on both phones passes 56 correction tests, disk create/amend/tombstone/
reopen checks, and 18 composition checks against actual node **2532969814** on
way **159830790**. That source has `maxspeed=50` and
`maxspeed:hgv:conditional=30 @ (weight>7.5)`. The probe amends only the restricted
clause to 25, keeps cars/HGVs up to 7,500 kg at 50, gives heavier HGVs 25, keeps
unknown weight unresolved, and restores the baseline after tombstoning. Source
tags and exact chainage survive reopen. The source membership stays unverified;
the composition phase explicitly supplies a **hypothetical** forward binding
and passage context and does not claim legal direction from the source.

The correction AST is a prototype data layer, not a replacement for the existing
conditional compiler. Its bounded journal uses a single writer and rename-based
snapshots. Production adoption needs durable fsync/locking, the existing
restriction semantics, activation/recovery and migration integration. A small
transactional SQLite overlay remains compatible with the packed-base design.

## Verification and remaining integration work

Both phones used isolated benchmarks, leaving the driving applications and
their data in place. The iPhone app identifier is
`de.youspeed.StoragePrototypeBenchmark`; Android uses an executable under
`/data/local/tmp/youspeed-storage-prototype`. Neither needs camera or GPS input.
The final summary records `complete_requested_phones=true` and
`cross_phone_parity_verified=true`.

The original Android raw exports were lost from temporary host storage during
the continuation. All three were re-exported from the reattached phone, and
each SHA-256 **exactly matches its prior durable receipt**:
`b62be597a7bbb10501630c124a48c793293166c3e65a935ffcfca42c0878c44a`.
The original Android latency/memory measurements remain unchanged and bound
to those same results. Compressed exact road exports for both platforms are now
retained with the small receipts, allowing offline replay without either phone.

Nine storage format tests, five malformed node-format cases, the correction
suite and actual-source probe pass, including ASan/UBSan. The report validator
also rejects empty-result substitutions under optimized Python. Full phone
builds succeed. Production app matching, camera retention, event ordering,
global archive random access, background memory pressure and incremental
distribution are outside this prototype and remain required integration work.

Build/run and offline verification instructions:
[benchmark README](/Users/raphaelvolz/Github/youspeed.de/benchmarks/runtime-storage/README.md).
Device reports, source/binary hashes, node verification, compressed raw road
exports and the complete phone summary are saved under the benchmark's
`results/`. Large runtime data was staged outside Git and remains in the isolated
device containers. Temporary host build/data caches may require regeneration;
the report does not depend on their continued existence. No commit, publish,
merge or production app deployment was performed.
