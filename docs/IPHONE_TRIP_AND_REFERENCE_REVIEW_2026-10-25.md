# iPhone drive review and trip/reference repairs — 25 October 2026

The attached iPhone's completed 24 October evidence confirms a saved but
unfinished evening drive, expensive event-derived history rows, and repeated
stale speed-reference episodes despite accurate GPS/map matches. The requested
stop/history repairs and the subsequently explicitly authorized shared policy
1.2.0 are implemented in both clients. The subsequent owner-authorized version
1.5/build 10067 installation is recorded
in [the device deployment receipt](V1_5_DEVICE_INSTALL_10067_2026-10-25.md), including
the owner-confirmed intentional iPhone journal deletion. No road drive was
repeated. No commit, push, merge or publication occurred during this validation.

All drive times below are **Europe/Berlin, 24 October 2026 (CEST, UTC+2)**.

## Collected evidence

The newer session runs from 17:17:35 to 17:32:27 in the match log. The copied
journal passes `PRAGMA quick_check` with its retained WAL. Its later trip starts
17:17:35 and remains `active`, last checkpoint 17:32:20, measured distance
**6,554.366 m**, with neither starting nor ending car-odometer reading. The
previous 4,405.294 m trip is marked interrupted after process recovery. There
are no saved odometer-entry events. These records establish that entry did not
persist; they do not reconstruct the user's exact gestures.

The evening trip contains 758 GPS events and 15,344 total events, with roughly
61.2 MB of event payloads. The old iPhone table synchronously loaded and decoded
each trip's complete event list and derived its names during row rendering,
repeating on refresh. Android's table obtained a snapshot that scanned the
complete event history, counted/grouped payloads, and derived endpoint labels.
Those paths explain unnecessary work when displaying existing recordings.
A host-only measurement of the copied evening trip took about 351 ms to read
and decode events, compared with about 0.005 ms median for its two-row trip
table; these are Mac measurements, not iPhone latency acceptance figures.

The old inline odometer dials were conditional on a repeatedly polled stop
snapshot, exactly-zero displayed speed, and a stationary GPS observation no
older than three seconds. A new unusable/moving fix could remove the editor,
and Save checked the live stop condition again. The new flow separates durable
trip closure from optional car-odometer entry.

## Repeated stale references

The later drive contains **726** published lookup results, **79** non-current
`matched_last_known` outputs across twelve episodes. Only one result lacks a
matched way. Typical affected fixes have approximately 4.75 m GPS accuracy and
selected-way distances of only a few metres. For example:

| Time | Selected map evidence | Published reference |
| --- | --- | --- |
| 17:18:33–17:18:47 | Flachsteichweg, then Bleichweg; map 30 | last-known 30; current state returns at about 17:18:48 |
| 17:19:53–17:20:01 | Ettlinger Straße / L 564; map 50 | last-known 30 |
| 17:28:10–17:28:17 | Neuenbürger Straße / K 4330; map 50 | last-known 30 |
| 17:29:00–17:29:08 | Schmiedgasse; map 30 | last-known 50 |
| 17:29:56–17:30:04 | Neuenbürger Straße / K 4330; map 50 | last-known 30 |

The TSR/reference transition log explicitly records `T06 context_pending`
followed by the confirmed `T08 road_relation_exit` after the shared eight-second
confirmation. Closely spaced changes can restart that confirmation, explaining
the roughly fifteen-second first episode. This is evidence of withheld current
limit authority; it does not establish that GPS or the selected map way was lost
throughout those episodes.

Lookup latency is a separate issue: median 35.85 ms, p95 110.48 ms, maximum
5,157.80 ms. The slowest row attributes 5,146.76 ms to settlement resolution.
The history repair removes event decoding from table presentation; it does not
claim to repair every settlement-query latency outlier.

## Implemented behavior and Android parity

- At zero displayed speed, an enabled active trip with a fresh accurate
  stationary fix exposes **Stop trip**. No fifteen-second wait is required.
  Stop durably ends the trip and stores its distance before opening the
  six-digit car-odometer editor. Later GPS/map updates do not remove the editor
  or reset its digits. Saving an ended trip's odometer needs no new GPS fix.
  Later/dismiss leaves the trip saved with a missing optional reading, which
  can still be entered from history. Recording stays enabled and rearms on
  movement.
- SQLite schema 3 retains `start_place`, `end_place` and a history metadata
  version alongside the incrementally stored distance. Closure resolves names
  once from captured offline place/fix evidence with the existing time,
  distance and gap rules. Legacy completed/interrupted rows receive one
  background backfill. Versioned metadata, including unavailable names, is
  never derived again for history. No geocoding or map lookup is performed
  while showing history. iPhone uses a published table cache; Android's table
  reads only `trips`. Names survive reopen, backup/restore and normal exports;
  masked exports exclude them.
- **Owner-authorized policy 1.2.0:** an ordinary different-road departure can
  confirm after two distinct consecutive qualified fixes on the pending
  road/way/relation. Each has an applicable typed map value, age 0–3 s,
  horizontal accuracy 0–20 m, and distance 0–10 m to the **selected** way, with
  at most three seconds between fixes. Duplicates cannot provide another
  proof. Missing/unusable evidence or a different pending road resets proof.
  Ambiguous departures and direction reversals retain eight seconds. Old
  camera/voice scope is retired before the fresh map value is admitted. Both
  apps consume the same pinned JSON bytes and twelve native adapter cases.
  Published 1.0.0/1.1.0 artifacts remain unchanged.
- Android now carries the producer generation created by its own confirmed
  road change into evaluation of that lookup. A later unrelated generation
  change still rejects publication. This allows the confirming fix itself to
  publish instead of being discarded as an old-generation completion.

A native Swift **road-adapter-only** replay of all 726 evening map results
produced 76 non-current outputs using the ordinary eight-second path and 14
using qualified bundle confirmation. It excludes camera/voice/city events and
map selection, approximates fix age from query time, and uses unknown direction
because recorded course accuracy is unavailable. It demonstrates the adapter
change on the recorded map sequence, not full-drive correctness or road safety
acceptance.

## Validation

- Shared checker: 39 scenarios, 171 steps, all sixteen transitions/five states;
  artifact hashes and both compiled approval-lock pins match. The twelve new
  shared adapter cases execute through both native runtimes.
- Android JVM: **862 tests, zero failures, one skip**. Isolated API 36 emulator:
  thirteen controller/journal/dashboard/table tests pass, including two-fix
  publication, old-camera retirement, turnaround, both dashboard orientations,
  persistent odometer entry and history. Six journal tests subsequently pass
  again after the export-metadata assertions were added. The stand-alone
  six-digit gesture test also passed in the earlier ten-test UI/journal run.
- iPhone simulator: sixteen reference-policy tests, 27 journal tests, and 38
  upcoming/controller tests pass, with four opt-in fixture skips. Two UI tests
  pass for the stop/editor flow and simple table/odometer history. Journal tests
  pass again after normal/masked export assertions. Regressions verify frozen
  distance/names, one-time legacy migration, reopening without event evidence,
  odometer saving after new fixes, and continued recording rearm.
- An initial simulator controller run was blocked by a retained synthetic
  100,000,001-byte startup-review fixture. That exact fixture was moved out of
  the isolated test host and preserved in the evidence folder; the affected
  tests then passed. Neither the driver's app nor its logs were changed.
- Screenshot review verified the iPhone's persistent white odometer sheet.
  No attached Android was available for a new log collection during this
  initial validation. Subsequent physical builds and checks are recorded in
  [the deployment receipt](V1_5_DEVICE_INSTALL_10067_2026-10-25.md). No live road
  validation was performed.

Raw copies, SHA-256 manifest, analysis, native replay, screenshots and test logs
remain outside Git at `/private/tmp/youspeed-log-review-20261025/`. The device
copies include the completed earlier match log, newer match/TSR/GPS logs,
preferences and journal database/WAL/SHM. No personal drive coordinates or raw
logs are committed in this report.
