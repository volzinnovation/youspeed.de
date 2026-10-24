# Fahrtenbuch implementation status

23 October 2026. Extended working-tree implementation for iPhone and Android.
The subsequent authorized [build 10060 device installation](V1_5_DEVICE_INSTALL_10060_2026-10-23.md)
is recorded separately; no store release was performed. Existing unrelated work
is preserved.

The subsequent [table and Settings revision](FAHRTENBUCH_TABLE_UI_2026-10-23.md)
records the owner's revised layout, white/X dialogs, saved-trip ending readings,
native validation and build 10061 test updates. The owner's subsequent simplicity
correction is tracked in [the build 10062 revision](FAHRTENBUCH_SIMPLE_UI_2026-10-23.md),
which supersedes the earlier history-screen composition.

## Current implementation

- Fahrten uses the existing dashboard button appearance and is second from the
  right, immediately left of Settings. Recording consent/preferences are directly
  in normal Settings; history no longer contains a second settings screen or
  opens automatically for first-use consent. Face-up desk posture within 10°
  keeps navigation and Settings available at any reported speed. Dashcam
  finalization and native permission gates remain.
- Independent private SQLite recording retains GPS, raw TSR, broad sign evidence,
  coverage gaps and capture identities. Journal recording starts before map/model
  readiness using the already authorized location path. Declining track history
  preserves minimal app counters without storing/backfilling a private route.
- Start/stop intent, repeated callbacks, 300-second foreground recovery, process
  restart, bounded late-sign finalization and mid-camera-session journal enabling
  are handled explicitly. Deletion cannot be reversed by late callbacks.
- History opens directly to five aligned columns: date/time, start location,
  end location, distance in localized kilometres to one decimal, and ending car
  odometer. Share/Delete sit in each row; selecting a row opens the compact
  optional ending-odometer input. Both dialogs have white backgrounds and X close
  controls. Charts, counters, totals, filters, search, help, Details links and data
  management are absent from this flow. Backup, restore and clear-all are collapsed
  inside normal Settings. A previously missing ending reading may be added once
  without changing trip or aggregate measurements.
- Retained detail/export implementation provides geographic route context, explicit gaps, linked selection,
  timeline, replay/speed chart, original GPS/TSR logs, sign discoveries and grouped
  photo/video sessions. It is not exposed from the simple history/odometer flow.
- Recorder sidecars retain UTC/monotonic origins, segment duration and timing
  quality; matching available segments can be sought from a selected moment.
  Native callback anchors are explicitly estimated (up to 2 s); clock-uncertain or
  out-of-interval media has no seek action. Exact frame/presentation alignment is
  not claimed for these callback anchors.
- Explicit offline exports include GPX, GeoJSON, CSV/JSON/NDJSON logs, discovery
  and media indices, PDF overview, counters, portable ZIP and SHA-256 manifests.
  `journal.json` is the common portable envelope in
  [`export-v1.schema.json`](../shared/trip-journal/export-v1.schema.json).
- Private sharing masks endpoint/home areas across route and sign evidence,
  excludes unstructured raw logs/videos/remote links, and only includes selected
  safely located photos re-encoded without GPS metadata. Unknown photo positions
  are omitted. Original records/counters remain unchanged.
- Password-encrypted AES-256-GCM/PBKDF2 backups restore the entire journal/counter
  epoch transactionally without adding imported distance or usage. Wrong passwords
  and invalid references fail before replacement. Reset-all and eligible local
  media deletion use explicit native confirmation and report protected items.
- UI/disclosure/export copy covers German, English, French and Dutch. Private
  journal identifiers never enter contribution or public-upload payloads.

The versioned measurement/media/backup contract is in
[`shared/trip-journal/`](../shared/trip-journal/README.md). SQLite REAL counters
remain unchanged; representation optimization and integer-unit migration are
separate work as requested by the owner.

## Validation and practical limits

The consolidated native/backend/build evidence is recorded in
[`V1_5_IMPLEMENTATION_CONTINUATION_2026-10-23.md`](V1_5_IMPLEMENTATION_CONTINUATION_2026-10-23.md).
Tests cover storage setup/retry, duplicate/out-of-order fixes, opt-out without
backfill, foreground recovery, stop/finalizer timing, mid-camera association,
backup replacement/idempotence, masking/leak prevention, GPX interleaving,
media clocks, deletion and lifetime-counter preservation. Simulator/emulator UI
captures verify native navigation. Compact iPhone portrait/both landscapes and
Android's 12 layout states plus narrow/larger-text portrait verify the existing
button style, unclipped control bounds and Fahrten immediately before Settings.

Physical installation was subsequently requested and performed as build 10060;
see the separate installation record above. No real-road drive was performed.
Sustained low-storage/reboot/real-road acceptance remains
an external validation gate. Background-continuous tracking, cloud sync and
formal tax-compliance guarantees remain outside the specified initial release.

The protected speed-limit-reference policy was not changed.

## Optional setup choice and disabled status — 24 October 2026

Build 10064 adds automatic Fahrtenbuch recording as an optional choice within
the existing setup. A missing preference still means off, existing choices and
completed setup remain intact, and no drive is reconstructed from old logs.
When recording is off, the simple white/X history table shows that status and a
shortcut to the Fahrtenbuch section of normal Settings. There is no separate
recording-settings screen.

The combined build also fixes upcoming 50 km/h previews for accepted directed
German town-entry signs and includes the completed conditional-rule handling.
Both phones have version 1.5/build 10064 and the conditional BW bundle installed.
See [the combined verification record](V1_5_BUILD_10064_2026-10-24.md) for tests,
physical checks, source priority, log handling and remaining field-test limits.

## Database setup crash fix — 23 October 2026

The reported Android `no such table: trips` error was reproduced on an API 36
emulator with two fresh/incomplete-database regressions before the fix. Setup
used `execSQL` for `PRAGMA secure_delete=ON`, which returns a row and aborts that
Android initialization path before table creation. Subsequent writes then
reported missing tables instead of the original setup failure.

Android now consumes that PRAGMA through a cursor, initializes/reconciles all
tables in one transaction, and publishes its connection only after commit.
Every queued operation checks initialization; a failed setup closes its handle
and can retry without deleting the database, resetting counters or changing
recording preferences. Active trip identity is assigned only after insertion
succeeds. The history poll catches both summary and selected-trip log failures
and displays an error instead of letting the coroutine failure crash the screen.

The equivalent iPhone regression first failed with the false setup error
`another row available`. Its SQLite helper now drains returned PRAGMA rows
before evaluating execution success.

Validation after the fix:

- Android API 36 emulator: **4 instrumentation tests passed** — fresh setup,
  recording/reopen; repair with existing counter preservation; retry after an
  unavailable directory; selected-trip query failure without history crash.
- iPhone simulator: **4 tests passed** — fresh setup without false errors,
  persistence/export/deletion/stale-callback protection, and measurement gates.
- Used an isolated Android test-host package on an emulator. No physical phone
  installation, publication, or user-data clearing was performed.
