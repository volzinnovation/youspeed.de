# YouSpeed for Android

The Android app uses the same bundled target configuration and v3 map-bundle contract as the iPhone app. It is part of the public YouSpeed release on 29 August 2026.

## Release ABIs and version codes

Release builds intentionally support only `armeabi-v7a`, `arm64-v8a`, `x86`,
and `x86_64`, because those are the ABIs for which the Vosk dependency contains
its native speech-recognition library. A normal release uses the source version
code. Passing `-PyouspeedAbi=<abi>` creates one F-Droid-compatible APK and maps
the source version code to `sourceVersionCode * 10 + ABI number`, in this order:

1. `armeabi-v7a`
2. `arm64-v8a`
3. `x86`
4. `x86_64`

For a signed release, export the four `YOUSPEED_ANDROID_RELEASE_*` variables
described by `app/build.gradle.kts`, then run:

```shell
./scripts/build-signed-abi-apks.sh
```

The script writes stable, versioned APK filenames to `android/dist/`. The
keystore and its passwords must remain outside the source repository.

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

That script builds a plain-table replay DB from `karlsruhe-regbez_speeds.sqlite.zlib`, pushes it into app-internal storage, and runs `V3ReplayInstrumentedTest`. The public test suite uses synthetic GPX/KML fixtures. Optional local trace diagnostics run only when replay files are supplied under app-internal `files/replay/`; personal traces must not be committed.

For a deliberate live Germany shard bootstrap on a connected emulator/device:

```bash
cd android
./gradlew :app:connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=de.youspeed.android.alpha.LiveBundleBootstrapInstrumentedTest \
  -Pandroid.testInstrumentationRunnerArguments.run_live_bootstrap=1
```

That test fetches `baden-wuerttemberg_manifest.json` from the public GitHub release path, streams the real shard DB asset to app-internal storage, validates size/SHA-256, and verifies bundle activation in an isolated test root.
