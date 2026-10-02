# Phase 1 physical-device validation — 27 September 2026

The user authorized deployment to the attached Moto g86 5G (Android 16) and
iPhone 14 Pro (iOS 26.6.2). The current native Debug apps were installed as
updates. Neither app was uninstalled and neither app's storage was cleared.
Deletion and journal tests use isolated fixtures; no photo upload was requested.
The iPhone display was inspected through QuickTime's wired screen preview.

## Issue found and repaired on hardware

The first iPhone run passed 25 of 27 tests. One failure exposed an actual
photo-journal coordination defect: Foundation can leave a path alias unresolved
when its final directory does not yet exist. The first queue store registered
its shared lock, cache revisions and deletion tombstones before creating that
directory. A later store could register a different shared state for the same
physical queue. Concurrent peer-store mutations could then overwrite one
another, and a stale snapshot could reinsert a deleted item.

`PanoramaxQueueStore` now creates its queue directories before resolving the
canonical root and registering shared state. Stored relative paths, journal
format, backup exclusion and file protection remain unchanged. A deterministic
missing-directory symlink regression checks peer updates and deletion
tombstones. The originally failing 64-operation concurrent test also remains.
Both pass on the physical iPhone after the fix.

The second failure was an outdated Core ML test expectation. Commit `2abb2568`
on 5 September intentionally made live recognition primary-sign-only and moved
supplementary-plate interpretation to offline review. The physical test still
expected the removed live plate output. Both packaged images already produced
their expected 70 km/h sign. The test now checks the existing primary-only
contract while retaining the speed and confidence assertions; production vision
behavior was not changed.

## Native checks completed

The corrected iPhone native selection passes **31 tests, zero failures/skips**:

- Nine SQLite resource tests: persistent connections/statements, bounded caches,
  concurrent access, missing/malformed files, same-path replacement and M7–M12.
- Four lookup scheduling tests: latest pending fix, cancellation, Settings
  pause and overlapping bundle removals.
- Four shared-corpus tests for candidate admission, matcher history/tunnels
  and sign-passage behavior.
- Fourteen integrity, photo-journal, path-alias, off-main image preparation and
  bundled Core ML tests.

For 512 captures plus 512 state updates on the physical iPhone, the journal
writes 1,570,680 metadata bytes versus 219,845,026 for the former full-record
encoder, with five checkpoints, 1,024 journal records and zero hot snapshot
reads. These are metadata counters; JPEG payloads are excluded.

The first Android native selection passes **35 tests, zero failures/skips**:
30 SQLite/matcher/photo conformance tests, four packaged LiteRT tests and one
Vosk native-runtime test. The measured warm GPU inference was 339–377 ms,
compared with a 1,444 ms CPU sample on this phone. This is fixture-specific
timing, not an on-road latency or accuracy guarantee. Vosk's native test uses
synthetic silence; it does not establish spoken-command accuracy.

## iPhone live UI and camera

After the user enabled XCTest UI automation directly on the phone, the live
Settings test passed. It uses the normal app and installed map, cycles portrait
and both landscape mounts, restores the original mount, repeatedly closes and
reopens Settings, backgrounds/reactivates the app with Settings open, enters
nested Debug and dismisses the whole sheet. It does not delete an installed map.
The first attempt timed out at the system passcode prompt; this was a test-runner
setup issue, separate from the passing native tests.

A separate real-camera test passed with three decoded JPEGs in one capture
session before, during and after the production map worker's Settings pause.
The Core Location anchor reported neither software simulation nor an external
accessory. Subsequent movement/speed are deliberately synthetic so a stationary
phone satisfies the photo cadence. Queue GPS metadata, decoded JPEGs, session
continuity, stale-result rejection and fresh-fix resume are asserted.

The initial camera harness competed with the normal app's automatic recognition
session and was interrupted after two photos. The final harness uses the
existing screenshot host to prevent that second camera session, while the
independent production camera coordinator and map worker remain real. Its
temporary audio-alert setting is restored from an exact pre-launch snapshot and
was independently checked after the run. Only temporary test photos are removed.
This is component integration coverage, not an end-to-end GPS-driven UI test.

The iPhone total is **33 distinct passing physical tests, zero final failures or
skips**. The normal app was relaunched afterward. The optimized unsigned Release
build also passes after the queue fix, and all 12 packaged country-rule files
match the shared source.

## Android capture ownership

Hardware capture testing found that disabling TSR marked the shared camera
`DISABLED` even while photos/video retained its CameraX graph. Since graph reuse
emits no new `ACTIVE` callback, automatic photo capture stopped. The controller
now lets shared-camera reconciliation own that state. Disabling recognition
still invalidates its inference generation and stops its consumer.

Independent review found the corresponding failure callback also stopped the
camera when video was off, without checking automatic photos. It now stops the
camera only when neither recording nor photos require it. These changes retain
the iPhone behavior and do not alter governed speed-reference semantics.

The isolated Android controller test measures one open/live reader after
warmup; three additional fixes increase cache hits from one to four without
opening another reader. Three Settings fixes and a fix during queued removal
advance the raw GPS counter from four to eight while reader opens/hits remain
unchanged. Removal invalidates that reader, leaving zero live readers; a new
post-dismissal fix advances the GPS counter to nine without restoring the
removed road. An explicit missing-directory symlink test also confirms that
Android's canonical-path resolution keeps peer photo stores coordinated.

Android's live Settings test covers nested Debug, both landscape mounts,
activity recreation with Settings retained, and Back dismissal. Previously
stale test assumptions were corrected: pictogram geometry includes the existing
5 dp artwork padding, photo worker disposal tests now block/drain the dedicated
photo executor, and movie checks wait for actual encoder output before taking
a filename snapshot. These are test-harness changes, not layout or recording
policy changes.

The final Android lifecycle/capture suite passes **17 tests, zero
failures/skips**, giving **52 distinct passing physical tests** together with
the 35 native conformance/model tests. The CameraX test saves a real photo while
the actual Settings screen is open and map matching is paused, verifies its GPS
and altitude metadata, then exercises recording finalization and recognition
toggles. Temporary moving fixes are delivered to the test controller; no OS
mock-location provider is installed. Existing photo/movie files are checked
against a pre-test filename/size snapshot and only newly created test media are
removed. Test preferences and bundle selection are restored.

A final camera-only repeat also passes with deterministic advancing coordinates,
so capture cadence no longer depends on real GPS fixes interleaving with the
fixture. All 3,643 pre-existing JPEG/MP4 files retain their original names and
sizes. The installed Debug APK matches the built artifact, and the normal app
was relaunched with the original preferences restored.

After both camera ownership fixes, the full Android JVM suite passes **399
tests, zero failures/skips**, and the optimized Release APK builds successfully.
Final Android/iPhone Release packaging still contains the 12 authoritative
country-rule files byte-for-byte. The frozen policy check passes all 36
scenarios, 156 steps, 15 transitions and five states.

## Boundaries

Bench tests with simulated movement do not replace a drive. Long-run battery,
thermal behavior, road-scene recognition and microphone command accuracy remain
field checks. No remote upload acceptance or production account mutation is
part of this run. The governed speed-reference policy is unchanged.

Raw build/test evidence is retained locally under the current review artifact's
`phase1-validation/on-device-2026-09-27/` directory. Device identifiers, precise
locations, private media and raw device diagnostics are not included here.
