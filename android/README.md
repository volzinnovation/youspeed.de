# Android Alpha

Internal alpha scaffold for Track E. This app consumes the same bundled target config and v3 bundle manifest contract as the iPhone app, but it is not part of the public May 22 release gate.

## Current scope

- load bundled `BundleTargets.top10.json`
- derive the same Germany shard manifest endpoints as iPhone
- fetch and parse a real shard manifest
- complete one full-bundle bootstrap flow with checksum validation and activation metadata persistence
- replay fixture and bundled-seed matcher regressions on Android emulator/device
- tolerate Android builds where SQLite `rtree` tables exist in the shard DB but the module is not exposed at runtime by falling back to bbox-table queries

## Local verification

From `android/gradlew`:

```bash
cd android
./gradlew --offline test
./gradlew --offline assembleDebug
```

The wrapper targets Gradle `8.7`, which is already present in the local cache on this machine.

For replay regressions against the Karlsruhe seed subset on a connected emulator/device:

```bash
cd android
./scripts/run_replay_regressions.sh
```

That script builds a plain-table replay DB from `karlsruhe-regbez_speeds.sqlite.zlib` using the recorded `inspector/logs` windows, emits a compact replay trace bundle, pushes both into app-internal storage, and runs `V3ReplayInstrumentedTest`. The replay suite now covers GPX/KML fixtures, bundled Karlsruhe window regressions, and longer field/geom/walking trace replays. The general `./gradlew :app:connectedDebugAndroidTest` suite stays green without a replay DB, but it only runs the longer trace diagnostics when replay files are present under app-internal `files/replay/`.

For a deliberate live Germany shard bootstrap on a connected emulator/device:

```bash
cd android
export YOUSPEED_RELEASE_READ_TOKEN="$(gh auth token)"
./gradlew :app:connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=de.youspeed.android.alpha.LiveBundleBootstrapInstrumentedTest \
  -Pandroid.testInstrumentationRunnerArguments.run_live_bootstrap=1
```

That test fetches `baden-wuerttemberg_manifest.json` from the live GitHub release path, streams the real shard DB asset to app-internal storage, validates size/SHA-256, and verifies bundle activation in an isolated test root.
