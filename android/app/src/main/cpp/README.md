# Android packed map reader

Packed v4 generations use the shared bounded context VFS, geometry reader and
generic-node reader. The private SQLite 3.51.0 engine executes the existing map
SQL, with RTREE enabled and mmap disabled. Each reader uses the shared context,
geometry and SQLite page-cache budgets exposed by `packed_runtime.h`. User edits,
trip journals and other writable application stores retain Android SQLite.

`RuntimeSqlDatabase` preserves query bindings and Android `Cursor` values. Native
cursors stream one row at a time. The owner closes tracked cursors before SQLite
and geometry. SQLite owns its internal virtual-table statements: never finalize
all `sqlite3_next_stmt` results, since RTREE maintains private cached statements.
The native symbols are hidden except the JNI entry points to avoid collisions
with Android or other bundled libraries.

The attempted public ProxyFD bridge is retained as an ignored architecture test.
On the API36 emulator, SQLite reopening `/proc/self/fd/N` failed with
`SQLITE_CANTOPEN: Permission denied`. Production uses the native VFS directly and
does not inflate a permanent uncompressed SQL image.

Build all four supported ABIs:

```sh
cd android
./gradlew :app:externalNativeBuildDebug :app:compileDebugKotlin
```

Build the separate app ID `de.youspeed.android.testhost` for runtime validation:

```sh
./gradlew :app:assembleDebug :app:assembleDebugAndroidTest \
  -PyouspeedIsolatedTests=true -PyouspeedAbi=arm64-v8a
```

The native fixture/correction suite is `PackedProxyDatabaseInstrumentedTest` and
`MapDataAmendmentStoreInstrumentedTest`. `PackedProductionLookupInstrumentedTest`
additionally requires `packed_pilot_dir`, an explicit isolated app-owned directory
containing `source.sqlite`, exactly one `*.context.yspc`, and its declared geometry
companion. It compares original table counts, every original geometry string and
sampled complete production matcher results, excluding timing fields only.

API36 emulator validation on 2026-10-27 passed 27 required tests across packed/native,
amendment, conditional and upcoming readers (the unavailable optional BW probe
and rejected ProxyFD architecture probe are skipped). The real Monaco pilot
passed all 44 original table counts, 1,232 exact geometry records and 27 complete
matcher results for both codec1 and codec2. Physical-phone acceptance and full-BW
memory/latency gates are recorded separately by the release workflow.

Amendments live in the separate writable `map_data_amendments.sqlite`. Source OSM
IDs stay decimal strings; newly surveyed signs use `local-node:<UUIDv4>` without
inventing an OSM ID. Local nodes need explicit reviewed way/direction/station/scope
and current-drive directed passage. Passage proof survives temporary uncertainty
and station jitter until known scope end/reset; overlapping edits fail closed.
Conditional reevaluation carries the current underlying rule result across clock
changes, with a bounded baseline/fallback chain. No reference-policy priority or
AST truth semantics are changed.

Sources: [SQLite pin](vendor/sqlite/README.md), shared
`shared/packed-runtime/vendor/zstd/SOURCE.json`, and
`shared/packed-runtime/FORMAT.md`.
