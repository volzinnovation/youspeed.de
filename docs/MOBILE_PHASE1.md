# Native mobile Phase 1

This work keeps the Swift and Kotlin apps and their existing camera, vision,
offline voice, SQLite bundle, capture, and network-policy implementations.
C++ and .NET/MAUI prototypes belong to Phase 2. The iPhone benchmark target
now consumes the same matcher DTOs as the app instead of a stale duplicate. iPhone remains the behavioral
reference; the governed speed-limit-reference policy and interpreters are
unchanged.

## Bundle lookup lifetime

GPS fixes reuse a retained read-only SQLite connection for the same bundle
instead of opening it for each lookup. Primary lookup, route probes, and city
queries use session-owned resources. Both platforms detect an atomic file
replacement at the same path, invalidate cached schema/geometry information,
and release resources on eviction or session disposal. Bundle removal clears
the iPhone service pool.

| Resource | iPhone | Android |
| --- | --- | --- |
| Connection ownership | Serialized service, recursive session lock | Serialized controller-owned reader pool |
| Pool retention | Four cached services; active callers can temporarily retain evicted services | Four readers maximum, evict before opening |
| File identity | Device, inode, size, modification/change timestamps | File key, size, modification/creation timestamps |
| SQL reuse | 48 cached prepared statements, reset and bindings cleared on release | Android SQLite compiled-statement cache plus cached candidate query shapes |
| Schema | 128 capability entries | Cached table/column/capability discovery |
| Geometry | 512 entries and 4 MiB accounted raw/coordinate payload; separate strict settlement decoding | 2,048 ways / 32,768 vertices and 256 area rings / 16,384 vertices |

Bounds exclude bookkeeping/allocator overhead. Oversized geometries bypass
caching. Only immutable geometry is cached; distance, heading, and other
position-dependent values are recomputed for every fix. Android calculates
polyline distance, endpoint progress, and heading in one traversal.

iPhone coalesces replaceable map requests into one running lookup plus the
newest pending fix. Every fix still reaches speed, capture and recognition
processing. Publication tokens reject superseded or stopped sessions, and
street-name lookup also runs off MainActor with bundle/context checks.

`LookupResourceTests`, `LookupSessionResourcesTests`, and
`LookupResourcesInstrumentedTest` exercise cold/warm reuse, bounded eviction,
concurrency, missing/malformed databases, teardown, and same-path replacement,
including replacement with equal size and modification time. Counters provide
repeatable evidence of avoided work; they are not latency/battery benchmarks.

## Behavior and shared inputs

- Sign suppression uses iPhone's 5 seconds / 30 metres on both platforms,
  measured from the actual commit frame. Known coordinates take precedence
  over reused tracking IDs; clock rollback expires the old record. Last-known
  coordinates survive temporary context loss.
- `shared/tsr/passage/suppression-v1.json` gives both native finalizers the same
  valid-origin time/distance/reused-ID scenarios. Missing recognition origins
  are separately checked through each platform's activation pipeline; Android
  raw evidence emission is not itself a user-visible speed activation.
- `shared/matcher/` defines deterministic capped candidate admission and shared
  history/tunnel decisions. Bounding-box distance orders candidate admission,
  followed by binary lexical way-ID order; full geometry scoring remains
  separate. This fixes iPhone's previously unordered SQL `LIMIT` and makes
  Android's ties deterministic, including IDs above 2^53.
- `shared/Rules/` is the only country-rule JSON source. Both builds preserve
  their existing runtime resource paths. `scripts/check_mobile_rules.py`
  checks source ownership and can compare packaged bytes. CI checks both app
  artifacts. Android now rejects malformed explicit penalty severity like
  Swift, preserving inference when severity is absent/null.
- iPhone bundle validation reads `PRAGMA quick_check` results and requires
  exactly one `ok` row followed by completion. Successful SQL execution alone
  does not prove database integrity.

Android system SQLite can lack the R-tree module. The instrumented suite logs
when fixture creation uses ordinary bounds tables, and separately tests an
unchanged genuine R-tree database through production's fallback. iPhone tests
create real virtual R-trees. See `shared/matcher/README.md` for the precise
admission and fixture contracts.

## Photo persistence and scheduling

Both stores retain the existing batch JSON shape as a checkpoint and append
atomic per-operation JSON records in a neighboring `<batch>.journal/`
directory. The `_queue_checkpoint` field records which operations a snapshot
already contains. Journals contain changed items, removals and header changes;
they do not rewrite every photo record for a one-photo state update.

Compaction is amortized: the operation threshold is the larger of 128 and the
checkpoint item count; the byte threshold is the larger of 256 KiB and twice
the checkpoint size. The new checkpoint is synced and atomically installed
before obsolete journal records are removed. File and directory barriers precede commit
acknowledgment. Restart can safely replay after a checkpoint/prune interruption.
This upgrades existing batch files without migrating image paths or formats;
it does not promise that an older app version can read uncheckpointed journals.

Each root has shared serialization and revision tracking for multiple store
instances, and each instance retains at most four batch snapshots. Corrupt or
gapped committed journals fail closed and preserve media. Temporary files are
not committed operations. Deletion intent stays authoritative; retention does
not silently erase images whose queue records cannot be read.

On iPhone, queue operations and JPEG/EXIF/hash preparation run off MainActor.
On Android, photo storage has a serial worker separate from downloads.
Capture/finalization ordering remains explicit. Stop cancels immediately;
task state remains registered while durable recovery finishes. Returned remote
acceptance is recorded before honoring cancellation, so Stop does not turn a
known accepted upload into an automatic retry.

## Verification

Validated on 27 September 2026, against the local Phase 1 patch on
`codex/8-tsr-applicability` (baseline `1c5f6c380cfd`):

| Check | Result |
| --- | --- |
| Android JVM suite, APK, instrumented compilation | 393 tests passed; debug build passed |
| API 36 emulator native suites | 30 passed across seven lookup/matcher/metadata classes |
| iPhone simulator `SpeedConsumerTests` | 400 selected: 377 passed, 23 skipped, zero failures |
| Actual Swift/Kotlin applicability replay | 56 scenarios agree at numeric tolerance 1e-9 |
| Frozen policy/hash check | 36 scenarios / 156 steps, all 15 transitions / five states |
| Python map generation / TSR contracts | 68 passed |
| Inspector JavaScript contracts | 24 passed |
| Country rules | All 12 shared sources match bytes packaged in both built apps |
| iPhone benchmark target | Simulator build passed; stale duplicate DTOs replaced with unchanged shared app definitions |
| Attribution generation and whitespace | Passed |

The iPhone run explicitly excluded the live-release download test after a
first run was interrupted waiting for that download. Its other 23 skips cover
unavailable map/benchmark fixtures and physical-device or installed-pilot gates.
After extracting unchanged shared matcher DTOs for the benchmark, the consumer
rebuilt and all 15 focused resource/scheduling/passage/matcher tests passed.
No failing local regression remains. The Android emulator lacks R-tree:
production fallback passed against an unchanged real virtual-table database.
The same seven native Android classes now run in CI; hosted CI was not invoked.

Measured eliminated work:

- iPhone concurrent resource test: 100 requests share one open and one prepared
  statement. Warm speed/name queries across M7–M12 add no opens, prepares,
  geometry decodes or capability loads after warmup. Same-path replacement
  reopens and resets cached state.
- Android's 100 repeated fixes plus city probes retain one way decode, one
  ring decode, 22 schema queries and three query shapes from cold to warm;
  cache hits increase to 201 ways / 200 rings. Pool tests turn 400 operations
  into two reader creations and 398 hits.
- For 512 captures plus 512 individual item-state updates, Android writes
  1,565,068 metadata bytes versus 218,275,238 for the former full-record encoder;
  iPhone writes 1,570,680 versus 219,845,026. Both use five checkpoints and
  1,024 journal records, with zero hot snapshot reads: about 99.3% fewer bytes.
  This excludes JPEG payloads; in-memory item copying/diffing remains.

Shared corpora characterize the reviewed behavior; they do
not constitute exhaustive feature parity or on-road accuracy certification.
Physical-phone latency, allocation, camera throughput, battery, and thermal
measurements remain release/device validation rather than claims inferred
from synthetic counters.

Useful commands from the repository root:

```sh
python3 scripts/speed_limit_reference/check.py
python3 scripts/check_mobile_rules.py
python3 scripts/attributions/generate.py --check
python3 -m pytest scripts/map/tests/test_generate_v3_country_bundles.py scripts/map/tests/test_resolve_country_release_plan.py tests/tsr/test_applicability.py tests/tsr/test_contract_schemas.py tests/tsr/test_v2_contracts.py tests/tsr/test_passage_contracts.py -q
./scripts/iphone/generate_xcode_project.sh
```

From `android/`, run:

```sh
./gradlew :app:testDebugUnitTest :app:assembleDebug :app:compileDebugAndroidTestKotlin
```

With a designated emulator, run the
instrumented lookup, matcher, native R-tree fallback, and Panoramax metadata
suites. Run `SpeedConsumerTests` on an available iPhone simulator. No physical
device deployment or publication is needed for these checks.

The local iPhone command was:

```sh
xcodebuild test -project iphone/SpeedDBBench.xcodeproj -scheme SpeedConsumer \
  -destination 'platform=iOS Simulator,id=D2831F96-C73E-4F84-BCB2-6B1B611A5FC8' \
  -derivedDataPath iphone/.derived/SpeedConsumerLookupTest \
  -only-testing:SpeedConsumerTests \
  -skip-testing:SpeedConsumerTests/SpeedConsumerTests/testRealReleaseSyncAssembleAndLookup_whenEnabled
```

Use an available simulator UUID on another Mac. The corresponding Android
instrumentation class list and environment are in `.github/workflows/ci.yml`.
The Xcode project is generated from `iphone/project.yml` and was regenerated.
This was the pre-device validation stage. Subsequent authorized deployment and
physical-device results are recorded in the follow-up below. No Phase 2 port
was implemented.


## Pre-device recheck

The pre-device audit also builds optimized artifacts: Android's unsigned
Release APK with R8/resource shrinking, and the iPhone Release app for generic
iOS hardware with signing disabled. All four Android ABIs remain present, and
all 12 country-rule files match the authoritative shared bytes in both Release
artifacts. These are build/packaging checks, not execution on physical hardware.

The final audit found two additional edge cases: an in-flight lookup could
publish a removed bundle during replacement startup, and Android coarse city
queries could use a country's persisted metadata for a different selected path.

At the product owner's direction, Settings visibility provides the simple
pause boundary for map processing. Opening Settings pauses new map/coarse
lookups and invalidates in-flight publications. Closing Settings resumes with
a fresh fix once any bundle-removal operation started there has finished.
Raw GPS samples needed for recording/photo metadata continue upstream. A small
pending-operation count covers closing Settings while an asynchronous removal
is still running; there is no per-bundle removal generation protocol.

Android country selection uses a coherent path/country snapshot and only
accepts a persisted fallback if its path matches the query database. This
prevents coarse fixes from evicting the correctly configured reader after a
country crossing. Failure cleanup also releases readers for unlinked files
when replacement initialization fails.

The Settings change passed 22 focused iPhone tests (including native frozen
policy tests) and 80 focused Android tests. The subsequent Android full JVM
suite passed 399 tests. Both optimized unsigned Release builds pass; packaged
country rules still match the shared sources, and Android retains all four
ABIs. At this stage, visibility wiring was inspected and compiled; actual
tapping, rotating and dismissing the sheets were subsequently checked on both
attached phones, as recorded below.

GPS samples used by recording and photo metadata continue while Settings is
open. Map-match diagnostic CSV rows normally come from completed lookups and
are therefore absent during this deliberate pause. Matching resumes from a
new fix with cleared continuity history, rather than replaying paused fixes.
An actually removed active bundle sends the existing `bundle_missing` input;
the governed policy may intentionally retain its LAST_KNOWN display.

Validation boundaries at the pre-device stage:

- Real release-bundle download and the fixture-dependent replay/benchmark
  tests were not completed by the local simulator suite.
- Crash tests reconstruct interrupted filesystem states and reopen stores;
  actual force-termination/relaunch during capture/upload still needs an
  integration smoke test. It can begin on an emulator/simulator and then be
  repeated with the physical capture/network lifecycle.
- Tests cover failed commit/checkpoint operations, but not real disk exhaustion
  or every post-rename directory-sync failure. Those are additional fault tests,
  not identified implementation defects.
- Hosted CI had not been triggered. The later physical run covers camera,
  packaged vision models, native offline-speech initialization and capture
  lifecycle checks. Long drives, sustained memory/latency, thermals, battery
  and spoken-command accuracy remain field validation.

Legacy-to-new queue upgrades are covered. Downgrading to a binary that ignores
journal files is not a supported recovery/rollback procedure; it would read
only the most recent checkpoint.


## Physical-device follow-up — 27 September 2026

The user subsequently authorized deployment to both attached phones. The
physical run found and repaired an iPhone photo-queue path-alias coordination
bug and Android shared-camera ownership bugs when recognition is disabled or
fails. The deployed builds retain the native implementations and governed
speed-reference policy. Detailed results, test isolation and field-test
boundaries are recorded in
[MOBILE_PHASE1_DEVICE_VALIDATION_2026-09-27.md](MOBILE_PHASE1_DEVICE_VALIDATION_2026-09-27.md).
