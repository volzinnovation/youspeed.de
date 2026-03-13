# Track E: Android Internal Alpha

Window: `2026-03-12` to `2026-05-22`

Status: active

## Goal

Start Android immediately as a real internal-alpha track using the same manifest and target contract as iPhone, without turning Android into a May 22 release gate.

## Now

- `android/` scaffold exists with a real Compose parity shell and Gradle wrapper
- Android mirrors the iPhone `BundleTargets.top10.json` and v3 bundle manifest contract
- full-bundle bootstrap logic now handles both single-file `db` and multipart `db_parts`
- Android now bundles and bootstraps the Karlsruhe seed on first launch
- live Android runtime spine is in place:
  - location permission flow and GPS updates
  - v3 SQLite lookup loop with way/city/basic speed-limit inference
  - deeper matcher continuity with same-ref/link promotion, same-ref bounce suppression, tunnel portal continuity, and corridor-state carryover modeled after iPhone `V3SpeedLimitService`
  - spoken overspeed and driving-ban warnings
  - speech-driven local speed capture with bundled offline Vosk recognition (`vosk-android` + `vosk-model-small-de-0.15`)
  - microphone permission flow with app-bundled German offline model preparation at startup instead of Google speech-model handoff
  - road-corridor continuation for captured local corrections, including `walk` / `Fussgaengerzone` export support
  - SQLite-backed local observation capture/review/export flow with approval, discard, single-export package generation, and bulk OSC export
  - debug log export/share and OSM browser handoff
- shared contract notes live in `docs/ANDROID_ALPHA_CONTRACT.md`
- live Germany shard manifest fetch confirmed against `baden-wuerttemberg_manifest.json`
- real Germany shard bootstrap now passes on emulator/device via `LiveBundleBootstrapInstrumentedTest` against the live `baden-wuerttemberg` release
- bundled country penalty-rule assets are mirrored from iPhone
- emulator-first verification is now wired:
  - reusable runner: `android/scripts/run_emulator_consumer.sh`
  - green smoke suite: `./gradlew :app:connectedDebugAndroidTest`
  - parity regression coverage for matcher continuity/tunnel fixtures and SQLite review/export flows is green on emulator
  - replay regression harness now exists for Android via `android/scripts/run_replay_regressions.sh`, including GPX/KML fixture replay, bundled Karlsruhe windows for the three-way gate and disconnected Loffenau hop, plus longer field/geom/walking trace replays built from `inspector/logs`
  - live release bootstrap is now covered by `LiveBundleBootstrapInstrumentedTest` when `run_live_bootstrap=1` is supplied
  - runtime lookup now falls back from `ways_rtree` / `areas_rtree` to bbox-table queries on Android builds where SQLite exposes the data tables but not the `rtree` module
  - simulator screenshots captured for default welcome/seed launch, warning-state main UI, settings sheet, and debug sheet

## Next

- verify the same live bootstrap path on an actual phone, not just the emulator
- check actual-phone permissions and behavior: location, microphone, background handling, and TTS volume
- run the short controlled route with logs enabled and feed the captured traces back into replay tuning
- use the longer replay harness to tune continuity/tunnel thresholds against real trace aggregates and add any missing recorded traces that expose remaining edge cases

## Human touchpoints

- confirm Android stack choices only if a blocking tooling decision appears
- keep Android scope from mutating shared contracts late in the iPhone launch path

## Blocked

- no repo-level blocker
- no actual phone is attached right now, so tonight’s permission/background/TTS verification is still limited to emulator and instrumentation coverage
- true `1:1` parity still needs longer-duration runtime validation, but the former matcher-depth and local-observation persistence gaps are now closed on Android and covered by emulator regression tests

## Outputs

- Android scaffold and alpha implementation
- shared contract notes in `docs/`
- fixture references shared with iPhone tests

## Exit criteria

- Android can parse the shared target config
- Android can fetch at least one real Germany shard manifest
- Android can complete one full-bundle bootstrap path internally

## Timing Reassessment

- `2026-03-12` status:
  - alpha shell parity, emulator automation, smoke tests, screenshot evidence, seed bootstrap, and first live runtime layers are in place
  - speech-driven capture is now implemented on Android with a bundled Vosk-based German offline recognizer and no Google speech-model dependency
  - deeper matcher continuity/tunnel behavior and the SQLite review/export observation model are now implemented and emulator-tested
  - Android now also has a host-generated replay DB path and compact replay trace bundle for emulator/device regression without depending on `rtree` support inside the test process
  - live GitHub release bootstrap against the real `baden-wuerttemberg` shard now passes on emulator/device under instrumentation, and the large-file path no longer OOMs because DB assets stream to disk with chunked SHA validation
  - runtime seed/shard lookup no longer hard-fails on Android builds where SQLite lacks live `rtree` module support
- revised internal pacing:
  - by `2026-03-19`: keep emulator/device regression green while hardening seed/runtime behavior, long-session continuity, and live bundle bootstrap
  - by `2026-04-10`: validate the parity heuristics against longer route traces and real shard/device runs, then tighten any remaining behavior deltas
  - by `2026-04-24`: complete parity audit against iPhone on simulator/device, then schedule limited manual field testing
- implication:
  - Android remains viable as an internal-alpha track inside the existing window, and the critical parity risk has shifted from missing subsystems to runtime calibration and real-world validation
