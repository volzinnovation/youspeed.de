The Android recorded-video replay runs an existing dashcam MP4 through the bundled sign detector/classifier, fresh applicability tracking, and the production `RoadPathSession` on a Moto g86. It is headless: it does not create the session controller or start a camera, drive, recording, or upload. The instrumentation test is skipped unless an explicit `replay_run_id` is supplied.

Build the app and test APK from the same source:

```sh
cd android
./gradlew --offline :app:assembleDebug :app:assembleDebugAndroidTest
```

Supply a private JSON manifest reconstructed from the recording diagnostics. Its fields are:

- `videoFile`: basename of an existing file in the app's `files/dashcam/`, and `videoSha256`.
- `sourceManifestSha256`, `country`, `packId`, `detectorSha256`, and `classifierSha256`.
- `estimatedVideoUtcAnchor`: approximate UTC seconds corresponding to encoded video PTS zero.
- `calibration`: `revision`, normalized `fx/fy/cx/cy`, mount `yawDegrees/pitchDegrees/rollDegrees`, `heightMeters`, and `lateralOffsetMeters`. Record calibration assumptions in `limitations`.
- `frames`: chronological recorded context samples with `capturedAtSeconds`, versioned `scope`, and nullable versioned `road` snapshot. These supply only recovered context; sign candidates are newly inferred from decoded pixels.
- `fixes`: `time`, reconstructed `arrivalSeconds`, `latitude`, `longitude`, `course`, `speed`, `accuracy`, and `courseAccuracy`. Only fixes whose recovered availability precedes the replay exposure are admitted.
- `limitations`: explicit descriptions of source timing, calibration, recoverable GNSS, and replay limits.

The first-drive private manifest is kept in ignored reports, not bundled into an APK or committed. It has 1,262 recorded context samples and 557 recoverable pose timestamps. The original raw location callback stream was not logged; this cannot recreate unobserved callbacks or a different first-arriving fix at an equal timestamp.

First run a short smoke segment. From the repository root:

```sh
python3 android/scripts/replay-recorded-road-path.py \
  --serial YOUR_MOTO_SERIAL \
  --input /absolute/path/to/private/input.json \
  --run-id smoke-unique-id --start 70 --end 90 --interval 0.5 --install
```

`--install` updates the two built APKs with `adb install -r`, preserving application data. Without it, installed APK hashes must match the local builds. The runner checks the selected Moto and existing logged capture state, refusing if a recording/photo consumer may be active. It copies only the supplied manifest to test cache and reads the existing movie. It does not erase logs or recordings. Updating/instrumenting the app necessarily replaces its running process; verify that the user has finished capture first.

Inspect the first decoded PNG and the smoke summary before running the full recording:

```sh
python3 android/scripts/replay-recorded-road-path.py \
  --serial YOUR_MOTO_SERIAL \
  --input /absolute/path/to/private/input.json \
  --run-id full-unique-id --start 0 --end 646.6 --interval 0.5
```

Use a new run identifier each time. Runner reports go to the ignored `android/app/build/reports/road-path/recorded-replay/<run-id>/` directory. The initial September 29 run was launched manually and is under `drive-20260929-1143/correction-replay/moto-replay/` instead.

MediaCodec sequentially decodes the MP4 and exposes `BufferInfo.presentationTimeUs`. Sampling selects the first decoded frame at or after each nominal interval. The output records the actual PTS and sampling offset, decoder identity/hardware flag, source/output format, model hashes, GPU/backend outcomes, thermal status, and full per-frame candidates/applicability/path diagnostics. A PNG is saved once, outside frame-stage timing, for color/orientation review. Decoder YUV is converted using the signalled BT.709/BT.601 matrix and full/limited range; unspecified metadata uses BT.601 limited-range defaults.

`addedPathMs` measures the sum of two stages: luma sampling/filter/geometry before TSR, and association/path serialization after TSR. Prepared geometry is reused for the same frame ID and scope. `lanePreparedAtNanos`, `tsrStartedAtNanos` and `lanePreparedBeforeTsr` retain execution-order evidence. The measurement excludes the intervening recorded-frame RGB conversion, model inference and applicability tracker. Separate timing fields retain those costs, all cold samples, and full-run wall time. Asynchronous hardware decode time cannot be isolated by subtracting these fields from elapsed time. The source PTS cadence is an evidence schedule; the replay is unpaced and is not a measurement of live frame admission, preview latency, or camera/encoder interference.

For the first drive, the encoded video is already 1280×720 while the original live analysis used 1600×1200. The recorded-frame calibration assumes a centered 4:3-to-16:9 crop: `fx/cx` remain unchanged, `fy` is divided by 0.75, and `cy` becomes `(cy−0.125)/0.75`. That mapping and the level-camera mount remain approximate. The UTC anchor also comes from recording callbacks; actual exposure-to-GNSS alignment is not independently known. Positive path classifications would therefore require separate accuracy validation. Historical capture-age fields are omitted from replay output because they are not live latency measurements.

The harness supplies `calibration.verified=true` and `captureClockKnown=true` to exercise geometry under those assumptions. These nested diagnostic flags do not establish measured calibration or verified video-to-GNSS alignment; decoded frame PTS is the verified timing information. Poor recovered GNSS also limits the association work exercised, so the measured added-path budget does not qualify the worst case with valid trajectories and dense sign tracks.

The test runs actual model inference and production sidecar tracking/geometry. It does not replay the authoritative speed-reference state machine or publish driving decisions. Compare fresh detections with original logged encounters as coverage evidence, not ground-truth accuracy. Live camera binding, shared viewport/crop correctness, rendered overlay visibility, and sustained recording workload still require the next controlled capture.
