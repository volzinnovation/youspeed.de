# YouSpeed for Android

The Android app uses the same bundled target configuration and v3 map-bundle contract as the iPhone app. It is part of the public YouSpeed release on 29 August 2026.

## Current scope

- load bundled `BundleTargets.top10.json`
- derive the same Germany shard manifest endpoints as iPhone
- fetch and parse a real shard manifest
- complete one full-bundle bootstrap flow with checksum validation and activation metadata persistence
- replay fixture and bundled-seed matcher regressions on Android emulator/device
- tolerate Android builds where SQLite `rtree` tables exist in the shard DB but the module is not exposed at runtime by falling back to bbox-table queries
- default to the M7 matcher and expose directional hypotheses for camera TSR,
  including displacement-derived heading from the second GPS fix
- accept structurally compatible raw-score model packs during field testing;
  calibration metadata is provenance and does not gate activation
- finalize primary speed-sign passages without supplementary-sign grouping,
  OCR, restrictions, bounding-box-IoU identity, or a low-speed admission gate
- keep one UUID for a physical sign track and show a white eye-shaped marker
  only while a committed camera limit is actually in use
- invalidate camera-derived limits on an explicit bundle transition from outside
  to inside a built-up area
- preserve confirmed TSR annotations, including German Zone 30 (`DE:274.1`),
  in the Panoramax sidecar and repair `Exif.Photo.UserComment` before upload
- request camera permission only when TSR is enabled, bind one rear-camera
  CameraX `ImageAnalysis` stream, and run the pinned two-stage model locally
  through LiteRT
- verify both bundled `.tflite` files against their manifest SHA-256 before
  opening the interpreters; only detector class `sign` enters live inference,
  while `plate` and `face` are explicitly ignored

The normalized-frame orchestration and live-controller bridge now have a real
CameraX/LiteRT producer. The bundled detector and classifier are pinned sibling
exports of the iPhone field-test checkpoints, with fixture parity recorded in
the pack's provenance report. Android still has no Dashcam/Panoramax recorder
lifecycle today; TSR therefore owns its CameraX analysis stream directly and is
already independent of any recording state.

## Local verification

From `android/gradlew`:

```bash
cd android
./gradlew --offline test
./gradlew --offline assembleDebug
```

The Android instrumented suite includes
`AndroidLiteRtTrafficSignInstrumentedTest`, which loads the packaged models and
expects the pinned Panoramax fixture to resolve to `maxspeed:70`. Run it on a
connected Android device with:

```bash
cd android
./gradlew :app:connectedDebugAndroidTest \
  -Pandroid.testInstrumentationRunnerArguments.class=de.youspeed.android.alpha.AndroidLiteRtTrafficSignInstrumentedTest
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
