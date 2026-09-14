# Android traffic-sign recognition: 14 September 2026

## Attached-device evidence

Read the existing YouSpeed diagnostic log from the attached Moto g86 5G
(`de.youspeed.android.debug`, version `1.1-debug`, code `10007`, last updated
13 September at 21:59). Recognition, standalone recognition, and other-sign
display were enabled. No settings or app data were changed during collection.

The 08:03–08:28 CEST session contains the following **logged inference
results**, not a ground-truth count of roadside signs:

| Observation | Count / duration |
| --- | ---: |
| Logged inference results | 856 |
| Results with classified detections | 53 |
| Results accepted for the pictogram callback | 41 |
| Provisional speed-recognition results | 9 |
| Confirmed recognition results | 0 |
| Finalized passages | 0 |
| Results with current context and verified bundle | 856 |
| Inference time on frames with classified detections, min / median / max | 1.85 / 2.56 / 3.38 seconds |

`displayAccepted` records an accepted observation offered to the display lane;
it does not prove a pictogram was rendered. Accepted speed signs clear the
other-sign pictogram and appear in the main speed lane only after a finalized
passage. This explains how speed detections can be present in diagnostics
while the displayed limit still comes from the database.

Raw logs remain local under `/private/tmp`; they contain road context and are
not repository fixtures. Regression fixtures use synthetic road context.

## Comparison with the working iPhone implementation

Both bundled packs use the same two-frame, 1,500 ms confirmation window and
the same 1280-pixel detector / 224-pixel classifier input sizes. Both fusion
engines remove evidence and its track identity after that window. Android's
recorded processing times exceed it: repeated `zone:30` and `maxspeed:50`
sightings remain provisional instead of confirming. With neither repeated
confirmation nor a qualifying single sighting, the passage finalizer emits
nothing, so the database limit remains authoritative.

iPhone's `TrafficSignVisionTwoStageCoreMLBackend` requests
`MLComputeUnits.all`. Android's existing engine explicitly used CPU inference
with four XNNPACK threads. Matching model exports and thresholds therefore
did not establish equivalent runtime performance.

A second Android defect affects faster inference and thermal pauses:
`TrafficSignLatestFrameSlot` retained an image when cadence rejected it.
CameraX `KEEP_ONLY_LATEST` waits for that image to close before delivering
another analyzer callback. Production never called the optional `tick()`
that the unit test used to release this cycle. iPhone rejects throttled work
before retaining it. Android now closes cadence-rejected and paused images
immediately; frames waiting behind a running inference retain bounded
ownership.

## Validation boundary

The original device log establishes successful model execution, repeated
provisional speed detections, excessive latency, and zero finalized passages.
The authorized device tests recorded below subsequently verify model-output
parity, processing time, and passage delivery on the Moto. A subsequent road
run is still needed to measure recognition accuracy in motion.

The repair keeps the shared models, input geometry, confidence thresholds,
sighting counts, and speed-override admission rules unchanged. GPU
initialization, execution, and release must run on the same inference worker;
unsupported devices or delegate failures must fall back to the existing CPU
runtime and identify the fallback in diagnostics.

## Requested device timing adaptation

The user requested a known reference image at startup to measure processing
times across Android hardware. Android therefore additionally packages the
existing, attributed Panoramax 70 km/h fixture unchanged. The startup worker
checks its SHA-256, decodes it, and requires the expected class, speed semantic,
and qualifying model scores on a cold run and two warm runs. These calls go
directly to the inference engine, with no live frame, road context, recognition
event, feedback, or persistence callback.

The effective confirmation window is
`max(manifest_window, min(6000 ms, ceil(2 × slowest_warm_inference_ms)))`.
For example, a verified 2.9-second warm inference produces a 5.8-second
allowance. The second inference budget allows scheduling jitter; the six-second
cap prevents indefinite retention. Only elapsed-time allowance changes. The
pack manifest, confidence thresholds, required positive sightings, and
qualified-negative requirements remain intact. Reference failure goes through
the existing visible recognition-unavailable path.

If a profiled runtime later falls back to CPU, successful current live-frame
timings can monotonically widen the allowance using the same formula and cap.
Stale results, failures, unprofiled runtimes, and GPU results cannot trigger
that fallback adjustment. The effective window is included in inference logs.

The phone itself reports `ARM, Mali-G615 MC2, OpenGL ES 3.2`, chipset `MT6878`,
with Mali Vulkan and OpenCL libraries present. The authorized device run below
also verifies actual model acceleration and processing time.

## Panoramax route comparison

The user-authorized public-instance comparison located a visible
[30-zone sign](https://panoramax.woladen.de/?pic=1c8378e2-4752-41a3-a37d-d5a908c287bf&focus=pic)
near the logged Lindenweg stretch and a
[posted 50 sign](https://panoramax.woladen.de/?pic=44f4683d-2a60-4bec-a313-a17f7ab422fd&focus=pic)
near Bleichweg. These photographs date to 4–5 September, not the device session
being diagnosed. They demonstrate nearby sign classes, not exact frame-level
ground truth for today's drive. Road geometry came from a local bundle older
than the installed bundle, so proximity is approximate.

Public automatic annotations also need visual review: an
[Ettlinger Straße board](https://panoramax.woladen.de/?pic=3630822f-8d0d-468e-ba2a-4fb95c44492d&focus=pic)
is labeled `DE:274.1` by the service, while the visible text is “30 / Heilbad”
rather than “ZONE”. It was not adopted as a startup reference or benchmark
ground-truth label. The already-pinned 70 km/h reference avoids changing model
and timing validation inputs based on unreviewed online annotations.

## Local verification of the prepared repair

- All 265 Android JVM tests passed, with no failures or skips. This includes
  the recorded slow-cadence reproduction, startup-derived allowance,
  six-second expiry, GPU-to-CPU fallback, and CameraX ownership regressions.
- Debug APK, release APK, and device-test APK built successfully.
- Debug lint passed with zero errors and 95 warnings. Existing missing
  end-sign translations were supplied in five locales to complete this check.
- Attribution generation check and four attribution tests passed. Both APKs
  include the unchanged reference JPEG and GPU native libraries for all four
  existing supported ABIs.
- Device instrumentation checks CPU/GPU predictions and timings, startup
  isolation, and real model results reaching the passage forwarder after
  qualified negatives. Its subsequent device results are recorded below.

Prepared debug APK SHA-256:
`035fa359581b9b0867b195d31c1a22263a8bd8d5add235ccb01b3aef76e294cd`.

Build evidence is in `/private/tmp/youspeed-tsr-validation-20260914.log` and
`/private/tmp/youspeed-tsr-instrument-build-20260914.log`.

## Authorized installation and actual device validation

After the user authorized commit, push, and phone installation, the repair was
committed as `c59bb80` and pushed to `main`. Installation retained the existing
debug app's maps, preferences, and recordings.

The first device run exposed excessive GPU startup tuning: OpenCL detector
initialization took approximately 175 seconds with `SUSTAINED_SPEED`.
Switching to `FAST_SINGLE_ANSWER` avoided that expensive tuning path. The
subsequent detector and classifier initialized in approximately one second
each, with all 548 detector and 546 classifier graph operations delegated to
the GPU. The corrected runtime was rebuilt and installed in place.

All four recognition instrumented tests passed in 25.452 seconds:

- Same-reference GPU warm inference: 519.91–528.33 ms, median 521.59 ms.
  Forced CPU inference: 1,419.33 ms; GPU was approximately 2.72 times faster.
  Class, semantic, and score-parity assertions passed.
- GPU reference timings retained the 1,500 ms allowance. The forced CPU
  reference produced a 2,849 ms allowance.
- Actual model results reached the production passage forwarder: two 70 km/h
  sightings, captured approximately 751 ms apart, progressed from provisional
  to confirmed. Two genuinely analyzed blank images then produced exactly one
  finalized 70 km/h passage. An additional blank did not duplicate it.
- The reference startup check emitted no live events, pictograms, or passages.

After removing only the temporary test package, YouSpeed was reopened. Normal
startup verified the reference on GPU in 509.62 and 542.55 ms; live-camera
inference continued at approximately 407–421 ms with current road context and
no backend failure. This validates continued CameraX delivery after inference
became faster than its base cadence interval.

Installed debug APK SHA-256, verified against the phone's actual `base.apk`:
`22deab8a34c3b3095ae894caee12459657cb61610e957fd1362f7b63df83bd85`.
The app remains version `1.1-debug`, code `10007`.

Final local unit tests, debug/release builds, and lint also passed. Device
evidence remains local in `/private/tmp/youspeed-moto-tsr-final-tests-20260914.txt`,
`/private/tmp/youspeed-moto-tsr-acceleration-parity-20260914.json`,
`/private/tmp/youspeed-moto-tsr-model-passage-20260914.json`, and
`/private/tmp/youspeed-moto-live-after-install-20260914.ndjson`.
