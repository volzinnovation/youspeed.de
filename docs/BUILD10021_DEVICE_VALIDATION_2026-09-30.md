# Build 10021 device validation — 2026-09-30

With the owner's explicit approval, Android build **10021** was installed on the
attached Moto g86. The corrected app delivered real GPU detector results before
any dashcam recording, during recording, after both movie and recorder-session
stops, and after a fresh cold restart. Every sampled inference in the selected
validation windows paired with an explicit empty lane-boundary list.

This validates the standalone-startup correction described in the
[original review](TSR_STANDALONE_STARTUP_REVIEW_2026-09-30.md). Build 10021 also
contains the cross-platform Bézier display changes and the completed build/unit
checks recorded in the [combined review](LANE_BEZIER_AND_CALIBRATION_REVIEW_2026-09-30.md).
The earlier build 10020 candidate was not installed.

## Full application checks

Times are UTC on 2026-09-30. Recognition and independent recognition were enabled;
automatic photos were disabled. Each count below requires a fresh
`traffic_sign_inference` with `source=live_frame`, positive detector/inference
timings, and a same-frame `tsr_path_evidence_v1` whose `boundaries` is explicitly
`[]`. These are sampled log counts within preserved snapshots, not total camera
frames or sign-recognition successes.

| Phase | First–last positive inference | Count |
|---|---|---:|
| Cold standalone start | 12:55:20.592–12:55:51.691 | 25 |
| Standalone, lane display switched off | 12:57:29.161–12:57:47.287 | 17 |
| Movie recording | 12:57:48.350–12:58:05.488 | 17 |
| After movie finalization | 12:58:24.668–12:58:54.853 | 29 |
| After recorder-session stop | 12:58:56.378–12:59:41.586 | 41 |
| Fresh cold restart | 13:03:53.240–13:04:19.967 | 22 |

The first cold graph bound at **12:55:15.484** with preview and analysis enabled
and both photo/movie outputs absent. The model loaded at **12:55:19.880**; the
first camera callback at **12:55:20.199** had current orientation and matching
actual/expected rotation. Live inference followed **712 ms after model load**,
approximately **5.335 seconds after capture activation**. The initial lane-display
preference remained on, but the preview was hidden and no boundaries were found.
The next standalone window explicitly had lane display off.

Movie recording started at **12:57:47.795** and its stop callback occurred at
**12:58:23.295**, reporting 35.181118 seconds. After movie stop the UI still showed
the active recorder session; after the separate recorder stop at **12:58:55.799**
it offered to start recording again. Both transitions preserved recognition with
no intervening graph bind in their checked windows.

The final cold restart activated capture at **13:03:48.116**, bound a new
preview/analysis-only graph at **13:03:48.332**, and loaded a new model runtime at
**13:03:52.408**. Its first fresh inference arrived **831 ms after model load**,
approximately **5.124 seconds after capture activation**. All selected inference
records used GPU execution and current context; none reported terminal backend
failure. Both cold starts independently passed the bundled `maxspeed:70` startup
reference check.

## Native camera regression and preservation

`DriveCameraGraphInstrumentedTest.coldStandaloneAnalysisAndMovieStopBothDeliverFramesWithoutLaneDetection`
passed on the device: **1 test, 0 failures**. It exercises delayed analyzer
attachment, no-movie standalone delivery, pause/resume, recreation, real movie
encoding/finalization, and delivery after movie stop using the production graph
plan and offscreen drain. Its temporary cache movie was cleaned up.

The full-app test movie was archived locally before removing that exact test
file from the phone. AVFoundation reported **35.214466 seconds** and successfully
decoded eight samples at five-second intervals. Its 39,561,601-byte local copy
matched the device SHA-256:

`4984daac923fef784c1dd0e8f76fbe06116262d73be4df80429c2d273d9ea8f3`

The standalone movie inventory was unchanged. The final inventory also matched
all **eight pre-existing filenames and sizes**, totaling **7,886,941,923 bytes**.
All saved preference keys and values matched before and after validation,
including restoration of lane display. Existing media was preserved.

## Evidence and limits

Private device evidence remains under the ignored directory
`inspector/logs/2026-09-30-build10021-device/`. The independent
[JSON summary](../inspector/logs/2026-09-30-build10021-device/independent-evidence-summary.json)
records exact phase anchors, frame IDs, counts and source hashes. It excludes
older build 10019 rows using the new startup anchors. Runtime files are bounded
tail snapshots; their different starting points do not imply source-log rotation.
`preferences-final.xml` and `movies-final.txt` capture the final restored state;
`validation-movie.mp4` preserves the test clip.

The stationary live scene produced no sign proposals, so these checks establish
camera-to-model execution and independence from recording/lane evidence, not live
sign classification accuracy or improved lane accuracy. The native graph test
explicitly covers pause/resume; the supplied full-app resumed snapshot contains
continued inference but does not independently establish a lifecycle transition.
No model, recognition threshold, or protected speed-limit policy was changed for
this validation.
