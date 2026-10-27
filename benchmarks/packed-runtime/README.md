# Bounded packed-runtime verification

This is a new isolated harness. Historical measurements and source receipts
under `benchmarks/runtime-storage/` remain untouched. It never changes the
driving apps, their settings, recording, or speed-reference policy.

The `legacy-packed` and `legacy-sqlite` modes repeat the original complete
prototype storage query using the new fd-only reader. The `context-packed`
mode executes a real SQL road-candidate query, including exact source geometry
through the production SQLite VFS and geometry scalar. `source-sqlite` executes
the same query against the original unmodified source database on the host.
Per-query typed-row hashes, row counts and aggregate hashes must match. This
workload is deliberately identified as storage SQL, not the complete driving
matcher or conditional-policy interpreter.

Each mode runs in a fresh process. The gate requires measured incremental RSS
below 64 MiB across the reported snapshots, and actual cache resident/peak bytes
within their configured limits. The report includes first-pass and warm
p50/p95/p99/max, initialization, platform RSS/physical footprint or PSS, kernel
highwater, and pread/cache counters. It does not call process-first I/O
OS-cold, equate file-backed RSS with anonymous memory, or claim a process peak
from sparse snapshots. Native files are never mapped. SQLite mmap is disabled
and its page cache is 1536 KiB; the context native block cache is 2 MiB, geometry
512 KiB, with a 512 KiB pread index cache per handle. These budgets come from
the shared native header/accessor. Caller and SQLite allocations
are included in measurements rather than assumed away.

The `pool-context-packed` mode retains independent context SQLite
connections and geometry readers after filling each with the complete corpus.
Its final numeric CLI argument is the reader count; both device drivers use
eight by default (`--pool-readers` can override it).
It reports memory after each fill and every handle's cache statistics. The
single-connection result does not bound the driving app's whole service pool.
This native stress excludes the platform's decoded-geometry cache and other
driving-app allocations, which require production integration measurements.

```sh
cmake -S benchmarks/packed-runtime -B /tmp/packed-bench -DCMAKE_BUILD_TYPE=Release
cmake --build /tmp/packed-bench -j4
/tmp/packed-bench/packed-runtime-bench context-packed CONTEXT.yspc WAYS.yspg queries.csv 3
/tmp/packed-bench/packed-runtime-bench source-sqlite ORIGINAL.sqlite - queries.csv 3
```

Android uses the same CMake target with the NDK toolchain and
`SQLITE_AMALGAMATION_DIR` pointing to pinned official SQLite 3.51.0. The source
archive is `https://www.sqlite.org/2025/sqlite-amalgamation-3510000.zip`, SHA-256
`1caf7116f2910600d04473ad69d37ec538fa62fa36adccd37b5e0e43647c98be`.
The production Android application's actual native cursor/VFS path is tested
separately by its instrumentation suite.

`build_iphone.py` builds and signs only. `run_iphone.py` is an explicit device
operation and must run after coordinating device availability. It reuses the
historical isolated app identifier, retains existing benchmark data, uses a
fresh nonce, and stores new local receipts separately. The app writes
`packed-runtime-progress.json` early and `packed-runtime-report.json` even on
configuration/native failures. No raw 3 GiB source baseline needs to be copied
or inflated onto either phone; original-source comparison runs on the host.

The production format and pinned decoder sources are documented in
`shared/packed-runtime/FORMAT.md`. Codec 1 remains zlib-compatible; codec 2 uses
the official BSD-licensed Zstandard 1.5.7 decompressor, with one independent
frame per block, no dictionary, exact declared raw size, and at most 256 KiB
frame windows. Node packs remain zlib.

The iPhone-only `nodes-packed` mode reads every full sign-node record through
the committed native node reader and compares its count and complete semantic
digest against the host `nodebench roundtrip packed` result. Run it separately
after timing measurements; it has no RSS or latency acceptance claim. Its
optional harness addition does not modify production runtime sources.
