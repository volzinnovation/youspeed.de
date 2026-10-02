# Standalone TSR startup review — 2026-09-30

This records the initial camera-only candidate, build 10020. The subsequent
[combined build 10021 review](LANE_BEZIER_AND_CALIBRATION_REVIEW_2026-09-30.md)
adds matching Bézier lane rendering on both clients, the calibration/timing
analysis, and final validation. The
[longer recording review](LANE_SHADOW_REVIEW_2026-09-30.md) documents the rejected
lighting experiments. Build 10021 supersedes the candidate artifact described
below. With explicit approval, build 10021 was installed and
[validated on the attached device on 2026-09-30](BUILD10021_DEVICE_VALIDATION_2026-09-30.md);
the initial build 10020 candidate was not installed.

The attached Moto g86's build 10019 log confirms a standalone camera startup failure: TSR reported itself active but produced no analyzed frames until dashcam recording started. Recording was not required after that recovery. Lane evidence is optional context for TSR; missing boundaries must leave recognition available with reduced applicability information.

## Evidence and timeline

This review uses the latest drive, its runtime and match logs, and `dashcam-1790766688367-322dd7c1-3274-4973-acc1-f8b56cecd6de.mp4`. Private inputs and extracted frames remain under the ignored directory `inspector/logs/2026-09-30-tsr-independence/`; no coordinates or private media are included here. Times below are local CEST (UTC+02:00).

| Time / interval | Observed evidence |
|---|---|
| 13:08:25.809 | Driving and application active; `recognitionEnabled=true`, `dashcamEnabled=false`. |
| 13:08:25.851 | Camera runtime reports `active`. |
| 13:08:25.809–13:11:28.231 | No `traffic_sign_inference` or `tsr_path_evidence_v1` events for 182.4 seconds. The match log records approximately 2.21 km of movement and a maximum speed of 72.2 km/h during this interval. |
| 13:11:28.231 / 13:11:28.487 | Dashcam enabled / recording start callback. Recording activation changes the camera graph. |
| 13:11:29.176 | First analyzed path frame: approximately 183.4 seconds after standalone TSR was enabled, and 0.95 seconds after dashcam activation. |
| 13:11:28.231–13:46:14.751 | 4,413 path-analysis events and 1,713 inference log entries during recording. Inference logging is sampled; these are not competing totals of processed frames. |
| 13:46:14.751 | Dashcam disabled while recognition remains enabled. |
| Through 13:51:09.539 | Another 441 path-analysis events and 205 inference log entries occur with recording off. These inference entries all report no recognition; subsequent match samples are stationary. |

Earlier nonrecording intervals in the same log also contain analyzed frames. The evidence therefore supports a startup/rebinding problem, not a universal per-frame dashcam gate. Build 10019 has no first-analysis-callback diagnostic, so the historical log cannot establish the exact internal CameraX or device-sensor failure mechanism.

## Optional lane evidence

| Latest recording | Count / timing |
|---|---:|
| Frames with no boundary list | 511 / 4,413, including six overlay invalidations |
| Frames with zero visible boundaries | 2,573 |
| Frames containing sign candidates but no boundaries | 151 |
| Inference entries with `displayAccepted=true` and no boundaries | 60 |
| Geometry-budget overlay suppressions | 200 (4.5%) |
| Lane preparation median / p95 / maximum | 19.47 / 48.04 / 110.23 ms |
| Overall sidecar deadline exceeded | 0 |

These observations demonstrate that missing lanes already permit TSR processing and observation acceptance. `displayAccepted` is an intermediate diagnostic, not proof that the primary numeric speed display changed.

All 1,082 path associations were `unknown`: 464 for insufficient observations, 562 for invalid trajectory, and 56 for unavailable calibration. No frame produced a corridor. All 2,625 applicability decisions were `UNKNOWN`, predominantly because of unqualified observations or stale road context. Path analysis ran in `shadow` mode. Recognition and camera offers still occurred; these logs do not establish reliable lane-specific sign applicability or lane-detection accuracy.

## Recording review and geometry

AVFoundation decoded 165 selected frames successfully. The encoded duration is 2,086.0272 seconds; the stop callback reports 2,085.993916 seconds. Exact decoded PTS and extraction details are retained in the local `video-review/frame-manifest.json`. Recording callbacks provide only an estimated alignment to runtime UTC; do not infer exact exposure correspondence from the filename or container timestamps.

Visual inspection confirms a physical 70 sign around video 00:12, a 50 around 05:16, physical 30 signs around 21:28 and 21:36, and a 40 around 24:39. Around the two 30 signs, model outputs briefly included provisional 40 and 50. All 12 actual camera offers between 13:32:50 and 13:33:12 were 30, with the resulting state `CAMERA` 30. The first such offer at 13:32:55.947925 replaced `BUNDLE` 50. This is provisional recognition ambiguity, not demonstrated incorrect dashboard speed changes.

The live analysis source was 1600×1200; lane processing used 288×216. The saved calibration was 1920×1440, and TSR consistently used the compatible full-height source crop `[688, 0, 1600, 1200]`. Encoded video is 1280×720; extracted review images are 960×540. The different aspect ratios prevent direct reuse of live calibration, crop coordinates or boxes on video pixels without a verified transform.

## Focused correction

Keep `Preview` and `ImageAnalysis` bound for standalone capture. When no dashboard preview is attached, a private offscreen surface continuously drains the preview stream. Photo and movie outputs remain optional and do not determine whether analysis exists; outputs already bound are retained across consumer toggles. This gives standalone TSR a repeating camera stream while its model worker loads, without requiring a movie to start.

Add graph-bound, analysis-consumer and first-frame diagnostics so a future startup failure can distinguish configured runtime state from actual frame delivery. Preserve the existing behavior in which missing lane evidence reduces applicability information without stopping recognition. Models, thresholds, recognition admission and the protected shared speed-limit reference policy and interpreter semantics are unchanged.

The iPhone reference already starts automatic capture with `dashcamEnabled: false` in `DriveSessionViewModel.reconcileAutomaticCapture`; `PanoramaxRecorder` enables its video-data connection from TSR/calibration demand and starts movie writing only when a movie URL exists. Its lane-preparation fallback continues sign inference when lane data is unavailable. The correction is confined to Android's CameraX startup graph; no iPhone behavior change is required.

## Validation status

Historical log analysis and the selected-frame visual review are complete. All **534 Android unit tests passed** (64 suites; no failures, errors or skips), including three new graph-composition regressions and the existing optional-lane preparation/evaluation, budget and sign-preservation cases. The debug application and instrumentation APK both built successfully with:

```sh
cd android
./gradlew --offline -PyouspeedBuildNumber=10020 \
  :app:testDebugUnitTest :app:assembleDebug :app:assembleDebugAndroidTest
```

The candidate application metadata reports version `1.3-debug`, build **10020**. Its SHA-256 is `9f22e13b9197d5b208b48dabca62b7c6637b872c95466dd4c81ef24d2c3a0dc2`. The instrumentation APK SHA-256 is `c5368d766d8c60cbe600d22623e6112d08ae1ec0ecede96bdad77cdd477792ed`. Source build-number defaults have not been advanced by this local build override.

`DriveCameraGraphInstrumentedTest`, enabled explicitly with `camera_graph_test=true`, uses a debug-only foreground activity and the production graph plan/offscreen provider. It binds preview plus analysis before attaching an analyzer, requires actual delivered frames with no movie, photos or lane consumer, exercises pause/resume and activity recreation, then checks movie encoding/finalization and continuing analysis. Its temporary silent movie is confined to the app cache and cleaned up. At the build 10020 review stage this test had only compiled. It subsequently passed on the attached device with build 10021; the separate full-app checks also verified real GPU inference before recording and after recording stops and a fresh cold restart. See the [device validation](BUILD10021_DEVICE_VALIDATION_2026-09-30.md).

Independent code review found no actionable blocker. Whitespace checks passed, and neither iPhone sources nor the protected shared policy changed in this camera-only candidate. No deployment occurred during the initial build 10020 review. The owner subsequently approved deployment of combined build 10021, which passed the [2026-09-30 device checks](BUILD10021_DEVICE_VALIDATION_2026-09-30.md); the historical build 10020 build/test results above remain unchanged.
