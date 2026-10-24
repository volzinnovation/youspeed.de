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
- Installed maps open offline. Android verifies database integrity at installation,
  then uses the saved metadata without rehashing the database at startup or during
  location lookups.
- One shared rear-camera session with live video/recognition controls, optional
  preview, elapsed time, and independent photo capture while video is off.
- Recognition is opt-in, standalone recognition defaults off, and feedback
  defaults to sound. Stationary frames cannot activate speed-limit passages.
  Inference uses the verified local LiteRT models, supported GPU acceleration
  with CPU fallback, candidate bursts, thermal caps, and visible terminal
  failure states. A bundled 70 km/h reference image verifies the runtime at
  recognition startup and measures two warm inferences. Its measured timing
  sets a bounded 1.5–6 second confirmation allowance for this model pack;
  confidence thresholds and sighting counts remain unchanged. The reference
  never enters the live speed, feedback, or observation-store paths.
  The optional “Speed and other traffic signs” feedback mode also speaks short,
  reviewed phrases for displayed secondary signs while moving. Other-sign display
  remains opt-in; missing translations stay silent. Secondary speech never queues,
  yields to speed feedback and voice capture, and suppresses repeated sightings.
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

See the [14 September device diagnosis](../docs/ANDROID_TSR_DEVICE_DIAGNOSIS_2026-09-14.md)
for the slow-inference failure, iPhone comparison, and validation boundary.

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

For a full suite on a phone that contains personal maps or recordings, use a separate test installation:

```bash
ANDROID_SERIAL=<device-serial> ./gradlew :app:connectedDebugAndroidTest -PyouspeedIsolatedTests=true
```

This installs `de.youspeed.android.testhost`; the normal debug application remains `de.youspeed.android.debug`. Build and install the normal application again after testing, without the property. Optional installed-map checks require an explicitly selected installation with the relevant map. GPU benchmarks require a supported physical GPU and skip on emulators that fall back to CPU. The road-path wall-time acceptance budget is also measured only on physical hardware; emulator replay correctness still runs.

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

## Startup log retention

Startup preserves diagnostic logs. Before preparing the main screen, the app
checks the combined size of its saved logs, including retained sessions. Above
100 MB (100,000,000 bytes), the user chooses whether to clear the logs or keep
them and continue. Checking and cleanup run off the UI thread. Failures offer a
retry or continuing with the remaining logs. Maps, observations, photos and
videos are outside this cleanup.

The **Debug logging** toggle at the bottom of Settings, above the debug-info
link, defaults to on and is saved across launches. Turning it off stops new
app log files and log writes, including queued diagnostics and crash logs.
Existing logs remain available until explicitly cleared.

## Native app-store review requests

Both clients count normal cold app launches and become eligible from launch ten.
Requests use StoreKit on iPhone and Google Play In-App Review on Android, with
no custom pre-prompt or automatic store-link fallback. Startup, bundle loading,
onboarding, screenshot fixtures and foreground resumes never trigger a request.

After at least 60 seconds in the session, the dashboard must remain unobstructed
and safe for five continuous seconds. Buttons must be visible, the app must be
foregrounded, GPS must confirm exactly zero speed with a stationary observation
no older than three seconds, and tunnel mode must be inactive. Settings, galleries,
calibration, speed capture, save progress/errors and other panels defer the request.
Losing any condition resets the quiet-period timer. Android rechecks all conditions
again after asynchronous Play review preparation, immediately before presentation.
Once a native prompt is presented, the store owns its UI and dismissal.

Requests are limited to once per app version, once per launch and no more often
than every 180 days across versions. Native dismissal does not cause a prompt at
the next launch. Attempt metadata persists across updates; clearing data or
reinstalling may reset it. The stores decide whether to show the prompt and do
not reveal whether a user rated or dismissed it, so completion never marks a
user as rated. The old explicit rated opt-out is honored if already saved.
Google Play preparation failures are silent, with no retry during the same launch;
without a working Play Store, the Android app continues normally.

Preferences: `youspeed.review.launch_count`,
`youspeed.review.user_confirmed_rated`, `youspeed.review.last_requested_version`,
and `youspeed.review.last_requested_at`. The store localizes the native UI.

References: [Apple review guidance](https://developer.apple.com/documentation/storekit/requesting-app-store-reviews)
and [Google Play review guidance](https://developer.android.com/guide/playcore/in-app-review).

## Local v1.5 traffic-sign bundle test (emulator)

The optional `traffic_sign_capability.version=1` tables enable BW inventory signs.
Databases without that capability retain the existing road, settlement and camera
flows. The isolated v1.5 build uses its own application ID and keeps the production
app's files and settings separate.

```sh
# From the repository root. Use an existing API 34+ emulator.
./android/gradlew -p android :app:assembleDebug :app:assembleDebugAndroidTest \
  -PyouspeedVersionName=1.5 -PyouspeedBuildNumber=10057 -PyouspeedIsolatedTests=true
adb -s emulator-5554 install -r android/app/build/outputs/apk/debug/app-debug.apk
adb -s emulator-5554 install -r android/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk
adb -s emulator-5554 shell am instrument -w \
  -e class de.youspeed.android.alpha.InventorySignDatabaseInstrumentedTest \
  de.youspeed.android.testhost.test/androidx.test.runner.AndroidJUnitRunner

# After the local runtime bundle has been generated:
python3 android/scripts/install-local-v3-test-bundle.py --serial emulator-5554 \
  --manifest mapdata/bundles/v3/baden-wuerttemberg/2026-10-21-v1.5-runtime/baden-wuerttemberg_manifest.json
# Verify real Android SQLite readiness, local routing, and a directed speed rule offline:
adb -s emulator-5554 shell am instrument -w -e localInventoryBundle true \
  -e class de.youspeed.android.alpha.LocalInventoryBundleInstrumentedTest \
  de.youspeed.android.testhost.test/androidx.test.runner.AndroidJUnitRunner
adb -s emulator-5554 shell pm grant de.youspeed.android.testhost android.permission.ACCESS_FINE_LOCATION
adb -s emulator-5554 shell pm grant de.youspeed.android.testhost android.permission.ACCESS_COARSE_LOCATION
adb -s emulator-5554 shell am force-stop de.youspeed.android.testhost
adb -s emulator-5554 shell am start -n de.youspeed.android.testhost/de.youspeed.android.alpha.MainActivity
# Longitude comes first. Use accepted directed signs from the generated build report.
adb -s emulator-5554 emu geo fix 8.4 49.0
```

The installer defaults to an explicit emulator serial and a debuggable testhost
or debug package. After explicit authorization for a physical phone, use its
exact serial with `--allow-physical-device --package de.youspeed.android.debug`;
update that existing debug app with `adb install -r` and omit
`-PyouspeedIsolatedTests=true` when building it. Never uninstall or clear the
driver app to install this test bundle. It checks the compressed artifact, materialized bytes and the
on-emulator database hash before activating the ordinary regional bundle layout.
It keeps other regional downloads and a copy of the former active-bundle record.
The APK's normal coverage routing selects BW after a precise location fix; map
installation alone does not fabricate a GPS bearing, camera frame or confirmation.
Use emulator route playback with bearing accuracy, or the controller fixtures, to
exercise directional speed limits and town passage. Readiness validation measures
bundle structure, not the existence or accuracy of the source's real signs.

Enable **Show other traffic signs** for geofenced secondary signs. In Panoramax
settings, **Capture bundle traffic signs only** selects the new trigger; it is
mutually exclusive with recognized-sign capture and preserves saved distance/time
settings. The camera, motion, storage and existing review/consent gates still apply.
Captures have `captureReason=inventory_sign` and optional encounter UUID links;
proximity does not constitute visual confirmation. The map-sign encounter journal
is local NDJSON at `files/inventory-signs/encounters.ndjson`, shareable in
**Diagnostics → Logs → Share map-sign log**. Unsupported town-sign model outputs
are recorded explicitly rather than treated as camera confirmations.

Build 10058 keeps an admitted secondary sign after leaving its geofence, until
an applicable replacement or boundary invalidates it. GPS, camera and foreground
gaps preserve the card; a new drive, bundle or country clears it. The 10 m/30 m
radii still gate new inventory encounters and photos. Accepted source headings
reject known opposite-facing secondary signs when an accurate vehicle heading
is available; unknown faces retain proximity behavior and are logged explicitly.

The speed-source caption distinguishes OSM tags, inventory signs, road defaults,
camera evidence and local corrections. A selected TSR switch now reports when
recognition is paused at night independently of the photo camera. Diagnostic
events separate inventory selection, SQLite/overlay/publication latency and
Compose presentation intervals. Compose events measure UI composition, not
compositor paint or a physical camera sighting. Build 10057 did not record
secondary presentation counts, so encounter counts cannot establish how many
cards were displayed on historical drives.
