# Android ANR repair and iPhone concurrency review — 28 October 2026

The two reported Android failures are the same controller-state/write-permit
deadlock. The fix is installed on the attached Moto g86 5G as **1.5-debug,
build 10078**, after JVM, emulator and isolated physical-device tests passed.
The iPhone remains on 1.5 build 10077. No backend deployment or live-source
activation was performed.

## Observed failures

Times in this report use Europe/Berlin, **CET (UTC+1)**. Photo EXIF timestamps
were correlated with Android process-exit history, DropBox ANR thread dumps,
GPS/matcher diagnostics and the attached iPhone's logs. Exact photo coordinates,
raw logs and private app data remain outside Git.

| Evidence | First failure | Second failure |
| --- | --- | --- |
| Photo | IMG_4877, 13:59:44 | IMG_4879, 17:28:12 |
| Android ANR trace | 14:00:02 | 17:29:25 |
| Process termination | 14:00:08 | 17:29:27 |
| Last retained runtime processing | 13:48:08 | 17:12:22 |
| Installed failing Android build | 10076 | 10076 |

Both system reports describe input-dispatch timeouts of approximately ten
seconds. They are ANRs rather than Java exceptions. The retained processing
records stop earlier than the photos; both tails include a city-exit transition.
The photos therefore do not establish the exact location or instant where the
deadlock first formed. They also show why an old displayed road/limit could
remain visible after processing had stopped.

Both ANR dumps prove the same cycle:

1. The road-lookup worker holds `trafficSignStateLock` and the lookup mutation
   gate while trying to advance `TrafficSignWriteGate` at a road-context boundary.
2. The observation writer holds that write gate around a SQLite transaction.
   Its `writePermitted` callback tries to read OCR authority under
   `trafficSignStateLock`.
3. Each worker waits for the other. The main thread subsequently blocks entering
   Settings in the first trace and offering a camera reference in the second.

This is supported by the captured thread monitors and their owners, not an
inference from geographic proximity or a slow individual map query.

## Repair

`LocalObservationStore.recordComputerVisionPassageIfNeeded` retains its serialized,
rollback-capable SQLite transaction, but performs SQL begin/read/write/physical
commit outside the controller and generation locks. Preliminary eligibility
checks remain.

Immediately before marking the transaction successful, the controller rechecks
generation, recognition, driving/session identity and both relevant OCR parent
IDs. Admission consistently acquires controller state before the short generation
permit. The only operation under that permit is SQLite's in-memory success
marker. Duplicate-receipt and equivalent-value branches use the same admission.
Rejected admission rolls back tentative observations, receipts and sidecars.

An admitted transaction is logically ordered before a later invalidation; its
physical commit may finish afterward without making the UI wait for disk I/O.
The gate documentation now states this boundary explicitly. No speed-reference
policy file, threshold or interpreter semantics changed.

Production files:

- [`ConsumerSessionController.kt`](../android/app/src/main/java/de/youspeed/android/alpha/ConsumerSessionController.kt)
- [`LocalObservationStore.kt`](../android/app/src/main/java/de/youspeed/android/alpha/LocalObservationStore.kt)
- [`TrafficSignPassage.kt`](../android/app/src/main/java/de/youspeed/android/alpha/TrafficSignPassage.kt)

The corresponding Swift persistence uses the `LocalObservationStore` actor and
does not call back into controller state inside its write permit. The observed
Android lock inversion is not present in that corresponding path.

## Validation

- Complete Android JVM suite: **913 discovered, 912 passed, one skipped**, zero
  failures/errors. The existing skip is the unavailable private dashcam fixture
  in `SignCollectionRepeatCropTests.recordedDashcamTraceMatchesSwiftCropSelection`.
- **29 selected instrumented tests passed on API 36 emulator**.
- **The same 29 passed on the physical Moto**, in the separate
  `de.youspeed.android.testhost` package before updating the normal app.
- The six new concurrency cases exercise the real controller/store paths:
  forced lock ordering, generation invalidation, OCR rejection, duplicate and
  equivalent receipts, valid admission, and UI responsiveness while physical
  transaction completion is paused. They use synthetic coordinates, bounded
  waits and a strict isolated-testhost guard.
- Existing durable observation/export cases, conditional OCR/controller cases
  and advisory lifecycle/cache cases were included in both instrumented runs.

New regression source:
[`TrafficSignObservationConcurrencyInstrumentedTest.kt`](../android/app/src/androidTest/java/de/youspeed/android/alpha/TrafficSignObservationConcurrencyInstrumentedTest.kt).
The real ANR dumps establish the pre-fix failure; the new tests were executed on
the fixed build. A separate historical APK red-control was not run.

## Installation and data preservation

After tests passed, the normal app was stopped for a consistent private backup
of settings, active-map metadata, trip journal and observations. The verified
archive is 598,401,024 bytes. Installation used `adb install -r`; no uninstall,
data clear, map replacement, photo deletion or diagnostic-log deletion occurred.

All **14 backed-up files matched byte-for-byte after installation, before first
launch**. Normal preferences and the active-map pointer also remain identical
after launch. The large-log startup prompt was explicitly answered **Logs
behalten und fortfahren**. All three original diagnostic logs remain and grew
normally. The installed APK checksum matches the built APK:

`1e9b9d79a0a8ee1183e8d4b4852b4f92f7d02388222b8c9957bcc1a64c63d872`

Normal-app smoke checks opened Settings, closed it and returned to the dashboard.
The new process log has no fatal exception, and process-exit history has no new
ANR after the update. These are stationary checks; no new road drive was run.

## Attached iPhone findings

The iPhone 14 Pro has no ordinary YouSpeed crash report dated 28 October in the
collected inventory. Its first-photo location has continuing matching/recognition
logs, including a match about eight seconds before the photo. For the second
photo, the iPhone had explicitly backgrounded approximately four minutes earlier,
so it provides no diagnostics at Android's later ANR time.

A separate iPhone CPU-resource report covers 18:20–18:23 and states **Action
taken: none**. It is not a crash and is outside the two Android incidents.
The historical 24 October watchdog report is also a different event, from build
10066. No iPhone app or settings were changed for this repair.


## iPhone concurrency follow-up

The follow-up inspected sign persistence, generation and processing gates,
AVFoundation configuration/stop, supplementary OCR, road-path preparation and
trip-journal UI/lifecycle calls. No Android-style circular wait was found in
these inspected iPhone paths. That is a scoped code review, not a proof that all
possible app deadlocks are absent. The store actor does not call back into
MainActor while holding its permit; camera callbacks return asynchronously.

Three related storage waits were repaired locally:

- **Passage persistence:** SQLite preparation, writes and physical COMMIT no
  longer hold the generation lock used by MainActor. Initial and terminal permit
  checks reject stale generations; terminal rejection rolls back tentative
  observations, exactly-once receipts and applicability sidecars. A successful
  final admission orders the transaction before a subsequent invalidation, while
  physical commit can finish afterward. Existing duplicate/equivalent branches
  use the same terminal check. No speed-reference policy changed.
- **Optional shadow diagnostics:** JPEG/QA writes run after processing admission
  on the same serial inference queue. Fusion, passage and applicability mutations
  remain inside the processing gate. Already-stale work skips diagnostics, and
  a diagnostic completion whose source frame has become stale cannot publish
  primary results. Previously admitted diagnostic files may finish after an
  invalidation; immutable source-frame identity/time and ordering are retained.
- **Trip journal:** the end-odometer sheet reads published history values and
  saves asynchronously, with duplicate input disabled while saving. Media
  deletion awaits a media-only query. The debug-only detail view awaits a cached
  projection; replay no longer rescans all events every 400 ms. Display reads do
  not checkpoint SQLite. The historical build-10066 watchdog stack passed through
  synchronous history rendering; that exact history-row path was already cached
  before this follow-up. These remaining changes are preventive, not attribution
  of today's CPU report to the journal.

The separate **debug-logging preference barrier remains**: turning logging off
synchronously waits for an admitted diagnostic write under
`DebugLogPersistence`. Slow storage can still delay that toggle. No reverse
MainActor dependency was found there; this is a storage wait, not a demonstrated
lock cycle. Its opt-out ordering was left intact. Bounded admitted core frame
processing also remains serialized with generation updates.

Final isolated iOS 26.5 Simulator validation discovered **125 tests: 124 passed,
one physical-iPhone-only test skipped, zero failures**. Six new test methods
cover stale-write rollback/gate responsiveness, duplicate/equivalent receipts,
blocked QA with fresh-generation delivery, and async journal projections. The
persistence regression was also run against the original method: it failed as
expected, with blocked generation updates and stale rows persisting.

Two earlier runs reached an unrelated fixture failure: the existing persisted
camera-limit test waited for startup while over 100 MB of retained Simulator
logs required a user review choice. It now uses the existing ready-state test
fixture after initialization, without deleting logs or changing production
startup behavior. The final complete selection passed. Result-bundle/log hashes
and source hashes are recorded in the receipt below. The iPhone changes are
local source changes only: the attached iPhone remains on **1.5 build 10077**;
no iPhone installation, backend deployment or source activation was performed.

## Evidence

Private originals, photo metadata, thread dumps, backup, screenshots, build/test
logs and preservation receipts are at `/private/tmp/youspeed-crash-20261028/`.
The [validation receipt](ANDROID_ANR_REPAIR_2026-10-28.validation.json) records
public source/APK hashes and summarized checks. Raw private data is not committed.
