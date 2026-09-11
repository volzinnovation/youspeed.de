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

## Cross-platform behavior

iPhone is the behavioral reference. Android now provides the recorder, recognition,
photo contribution, settings, and map-update behavior covered by the September
2026 parity review. See [the implementation and validation matrix](../docs/ANDROID_FEATURE_PARITY.md).

- Shared bundle targets, country rules, regional discovery, catalog, and v3 schema.
- Default M7 tunnel/junction matching, M10 node headings, M11 particle matching,
  and M12 graph/Viterbi matching; SQLite bbox fallback when R-tree is unavailable.
- Full map downloads and eligible raw/zlib SQL delta chains, validated before
  atomic activation; current-country endpoint processing follows iPhone.
- One shared rear-camera session with live video/recognition controls, optional
  preview, elapsed time, and independent photo capture while video is off.
- Recognition is opt-in, standalone recognition defaults off, and feedback
  defaults to sound. Stationary frames cannot activate speed-limit passages.
  Inference uses the verified local LiteRT models, candidate bursts, thermal
  caps, and visible terminal failure states.
- Photos default to distance mode, 25 m, 5 s, and a 1 GB quota. JPEGs and sidecars
  retain GPS, altitude/course when available, and confirmed sign annotations.
- Panoramax account connection and explicit post-drive review/upload, progress,
  cancellation/resume, favorites, original viewing, bulk deletion, queue repair,
  and optional cleanup after remote processing completes. No automatic uploads.
- Full local movie library with playback/share/delete, 5 GB movie files and
  10 GB library retention.
- Voice corrections start listening after preparation, use a four-second
  window, and commit only completed transcripts. Android uses bundled Vosk.

The packaged detector/classifier are sibling exports of the iPhone checkpoints.
Model provenance does not establish accuracy on all road scenes; town-entry
recognition remains limited on both platforms.

## Local verification

From `android/gradlew`:

```bash
cd android
./gradlew --offline :app:test :app:assembleDebug :app:assembleRelease :app:lintDebug
```

The Android instrumented suite includes
`AndroidLiteRtTrafficSignInstrumentedTest`, which loads the packaged models and
expects the pinned Panoramax fixture to resolve to `maxspeed:70`, and
`VoskNativeRuntimeInstrumentedTest`, which checks JNA initialization and both
speech recognizer paths using synthetic silence. Run these on an Android
emulator or connected device with:

```bash
cd android
./gradlew :app:connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=de.youspeed.android.alpha.AndroidLiteRtTrafficSignInstrumentedTest,de.youspeed.android.alpha.VoskNativeRuntimeInstrumentedTest
```

The wrapper targets Gradle `8.7`, which is already present in the local cache on this machine.

The default connected suite also checks replay lookup correctness and latency
against a synthetic SQLite fixture. Optional field-trace and external-database
benchmarks skip when their inputs are absent.

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
