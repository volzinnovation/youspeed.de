# Packed runtime integration and release gates

Both apps support the V4 immutable packed generation described in
[`FORMAT.md`](../shared/packed-runtime/FORMAT.md). Version 1.6 (10074) opens the
compressed context through a bounded native SQLite VFS, obtains exact original
geometry from its companion, and reads generic sign nodes through a bounded
index. SQLite remains the SQL query engine. No permanent uncompressed base
database is installed. Legacy bundles and their release URLs remain available.

The writable correction database is independent of downloaded generations.
It retains original restriction JSON and raw tags, validity, provenance,
revision history, compare-and-swap updates and tombstones. Existing OSM node
identities remain decimal strings. Newly surveyed signs use
`local-node:<UUIDv4>`, without inventing OSM IDs. Unknown directions and bindings
remain unresolved. Reviewed node amendments still require the existing directed
passage checks. Conditions use the existing evaluator and producer admission;
the protected shared speed-reference policy and both policy pins are unchanged.

Amendment bases use the installed context, geometry and node SHA-256 values,
not the human-readable bundle version shared by different regions. Missing
generation manifests and old version-only bases cannot authorize an override;
stored revisions remain available for explicit rebase. Recognized source-node
and way-rule revision hashes are checked before composition.

The original mapping-based prototype had a large resident footprint. Production
readers use `pread`, fixed reusable decompression slots, a 2 MiB context cache,
512 KiB geometry cache and bounded index pages. SQLite mmap is disabled and its
page cache is limited to 1536 KiB. Decoded geometry caches are reduced on both
platforms, and Android serializes journal-map loads to bound simultaneous owners.
Android uses a privately linked SQLite engine
with a typed JNI cursor; the framework proxy-file experiment failed on the
tested Android release. Writable Android stores retain framework SQLite.

The full BW host workload preserves all 586 query results / 8,163 rows and the
aggregate hash `0d867bc541b01624` against the original SQLite source. The final
reader observed about 7.4 MiB incremental RSS with zero mapped payload bytes.
Eight retained readers observed 49.1 MiB, versus 82.8 MiB for only four readers
with the earlier 8/2/8 MiB budgets. Compression costs latency: final-budget host
warm SQL p50/p95 were approximately 8.6/19.9 ms,
versus 0.071/0.153 ms for raw SQLite with the same SQL cache budget. These are
host storage measurements, not
complete driving-matcher or physical-phone acceptance claims. Receipts are in
[`shared/packed-runtime/results`](../shared/packed-runtime/results/).

Release conversion verifies original logical table counts, original metadata
and every original geometry JSON string. Every transport and installed
companion has an independent SHA-256 and size. Companions activate together in
an immutable generation directory. V4 manifests have no SQL delta index.

The pinned plan contains 55 source releases, representing 54 unique regions
(two historical Karlsruhe sources). The catalog selects the canonical source
for each region. BW uses the newer full local V1.5 dataset rather than the older
published BW snapshot. Its size comparison must distinguish the actual
converted source from that older published download.

The old Karlsruhe alias uses row-ID joins absent from both current clients.
Its new release reuses the canonical Karlsruhe packed bytes with verified
provenance. The old release is preserved. Its comparison separates compression
of the actual canonical input from the content/schema upgrade over the old
80,994,304-byte archive; the latter adds modern settlement data and sign nodes.

| Full BW runtime | Converted source | Packed generation | Change |
|---|---:|---:|---:|
| Installed bytes | 3,185,627,136 | 885,658,829 | −72.2% |
| Download bytes | 989,583,784 | 868,339,526 | −12.3% |

The packed generation includes 73,991 generic sign nodes in addition to the
source context and geometry. The previous published BW download was
481,537,646 bytes and contained an older dataset. The unchanged coverage and
penalty companions were verified against the newer full source. Exact sizes,
hashes and table counts are in the
[`BW result`](../shared/packed-runtime/results/releases/baden-wuerttemberg/result.json).

`packed_refresh` in the existing country workflow builds 54 pinned sources in
parallel and stages verified drafts. Full BW is built locally from its newer
source. The publisher refuses rollout without physical iPhone and Android QA
bound to the exact source commit, runtime source hashes, builder recipe and BW
artifact hashes. Both phones must preserve lookup results and use zero mapped
payload bytes. Single readers must stay below 64 MiB observed incremental RSS;
eight retained readers must stay below 56 MiB to reserve 8 MiB for decoded
geometry and node caches. These are storage acceptance gates, not whole-app
absolute memory limits. The
catalog is published only after every referenced immutable release is public.

Data-builder and accepted client commits are separate pins. Client-only fixes
do not require rebuilding identical immutable data. The QA report hashes each
builder source against its data commit and each runtime source against the
accepted client commit; reused phone storage evidence also records equality of
the native build inputs.

At this checkpoint, platform tests and host checks pass; physical-device
acceptance and publication are pending. No production app has been replaced
and no branch has been merged.
