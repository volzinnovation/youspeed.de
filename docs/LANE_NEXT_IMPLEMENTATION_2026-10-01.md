# Lane follow-up implementation — 2026-10-01

The five requested work items have implementation and evaluation support. The corrected Android candidate passed a 600-second real-camera test and build 10027 is installed after a diagnostic-format smoke test. iPhone build 10028 is installed after correcting failed-run diagnostics; sustained validation remains incomplete because both fresh retries entered the background and the camera was interrupted. See [device validation and cleanup](LANE_DEVICE_VALIDATION_2026-10-01.md) for results, backup manifests and limitations. The earlier Android baseline remains failed because normal movie retention removed an owner recording; its verified local backup was restored before the later user-authorized cleanup.

The CameraX ownership correction is active in the Android source. The new image-selection options remain disabled in the normal app because the fresh negative clips showed regressions. The 50 ms preparation target remains telemetry, not a processing cutoff.

## 1. Preserve accepted detector evidence

Fragment grouping now protects every baseline-accepted raw track: its geometry, confidence and output capacity survive an unsuccessful fit. Fitting/joining operates on baseline-rejected sparse fragments with actual gaps and fills only remaining candidate slots. Painted intervals remain separate from the boundary model. Fit rejection counters distinguish invalid inputs, residual, slope and curvature failures.

Both implementations retain the six-candidate bound, existing brightness thresholds and operation safeguards. Regression fixtures cover a valid non-quadratic border, output capacity, dashed paint, arrows, merges, guardrails and unmarked roads. This correction applies when the experimental grouping option is selected; grouping is still off by default.

## 2. Retain tentative identities without inventing observations

The preview-only `retainTentativeIdentity` option carries tentative and confirmed identities through short gaps, expiring them 0.75 seconds after actual observed evidence. Tracked-only predictions cannot initialize or reinforce an identity, extend its lifetime, or appear as freshly detected paint. Reappearance may recover the identity. Diagnostics expose expired IDs separately from current selected IDs.

The default remains false. Separate session regression tests verify that requesting preview experiments cannot change the TSR path-evidence session.

## 3. Evaluate left and right as an ego corridor

The optional joint selector evaluates bounded candidate pairs using image geometry, compatible curvature and trusted visual guides. When current calibration and causal motion qualify for projection, it adds broad metric width and short-range trajectory evidence. A metric mismatch cannot discard both otherwise valid painted candidates; a single-border fallback remains available. Output is always at most one border per side.

Directional lane count has an optional, weak context input, with tests for absent and uncertain data. **The current bundled matcher models do not expose directional lane counts**, so live sessions do not supply an invented count or lane index. Diagnostics explicitly record `directional_lane_count_unavailable`. Extending the map data contract is separate work; this implementation does not alter the protected speed-limit-reference policy.

## 4. Decouple Android camera delivery from TSR ownership

Previously, CameraX's current `ImageProxy` stayed open throughout model inference. A following proxy could also wait in the TSR mailbox. With `KEEP_ONLY_LATEST`, this prevented further analyzer callbacks, including lane callbacks, even though lane preparation itself was quick.

The executing frame now closes its camera proxy immediately after the existing independent bitmap conversion. TSR retains the copied pixels and captured metadata. CameraX submissions arriving while inference is busy close immediately through an atomic source-specific admission path. Other sources keep their existing pending-frame behavior. There is no added full-resolution copy or unbounded frame queue, and TSR's cadence, fusion and thermal policy are unchanged.

Exactly-once release tests cover success, copy failure, busy input, context changes, cadence rejection, thermal pause and closure. Five-second aggregate diagnostics distinguish camera delivery intervals, proxy hold time measured from analyzer entry, source drops, lane delivery/admission/completion/publication intervals and existing processing latency. Windows are bounded to 128 intervals.

The iPhone dispatcher already calls the lane consumer before TSR and copies admitted reduced luminance synchronously. Its bounded AVFoundation pixel-buffer ownership is different from CameraX's close-gated analyzer delivery; it receives equivalent lane timing diagnostics without an unnecessary ownership rewrite.

Lifecycle tests and the physical Android candidate confirm earlier camera-buffer release. In the stationary comparison, lane exposure cadence increased from 3.80 to 7.25 Hz and p95 gaps fell from 433.5 to 233.4 ms. Mean sampled RSS increased by 107 MB; memory did not clearly plateau, so neither an OOM fix nor a thermal improvement is claimed. The 10027 smoke also verifies structured nested cadence telemetry on the device.

## 5. Exercise the actual complete workload

Two opt-in device tests now exercise the normal app owner, real camera, TSR inference, independent lane worker, movie encoder and visible preview. Optional Panoramax capture defaults on and follows actual GPS/capture cadence. They do not inject GPS, speed, road context or recognition results.

- Android: `LaneFullWorkloadInstrumentedTest.sustainedCameraRecognitionLanesMovieAndDisplay`.
- iPhone: `LaneFullWorkloadDeviceTests.testRealCameraTSRLanesRecordingAndDisplay`, in the existing `LaneDetectionRuntimeTests.swift` test source. A DEBUG-only weak owner reference avoids loading a second model or camera.

The tests require real inference and lane processing before starting the timed interval, check continued progress outside thermal pauses, verify a live visible preview and finalized movie duration, and record process RSS, thermal state, processing activity and recording output. Sampled RSS is not an exact peak; stationary real-camera testing does not establish moving-road accuracy or moving-speed TSR load.

Tests wait for storage maintenance, reject active uploads, archive only their newly created photos outside the owner's storage quota and restore preferences. Archival failure fails the test and retains deletion protection. No uploads are started. The first Android baseline exposed a separate hard 10 GB movie quota, unaffected by the photo-storage preference. Its media-preservation assertion correctly failed, but did not prevent retention. Before another run, test movies must use an isolated DEBUG destination and exact-file retention exemption, as implemented for iPhone. Protection must be established before capture, not inferred from a final assertion.

Run at least 600 seconds to exceed the prior approximately 495-second iPhone thermal onset. A 30-second run is only a smoke test. Record device model, build, charge state, display brightness, ambient temperature, capture dimensions, actual speed and enabled modules. Compare the same scene and settings after cooling between repeated runs; an isolated replay or one fixed-order run cannot establish a heat improvement.

Android instrumentation arguments:

```text
-e class de.youspeed.android.alpha.LaneFullWorkloadInstrumentedTest
-e laneFullWorkload true
-e laneFullWorkloadSeconds 600
-e laneFullWorkloadPhotos true
```

Outputs are under the app's `files/lane-evaluation/lane-full-workload-<timestamp>/`, with runtime events, one-second samples, summary and archived test photos. Test dashcam filenames are listed in the summary.

For iPhone, supply `LANE_FULL_WORKLOAD_RUN_ID` to the test host and create `Documents/LaneFullWorkload/config.json` containing the same run ID, `seconds: 600`, and `includePhotos: true`. Run only the full-workload test after building for the physical phone. Outputs are under `Documents/LaneFullWorkload/<runId>/`, including diagnostics, summary, finalized movie and test-photo archive.

There is **no measured thermal improvement from this round**. The existing severe/critical safeguards stay in place. Lowering image quality or changing thermal thresholds without this combined-workload measurement would confound recognition evaluation.

## Evaluation and activation decision

See [the full evaluation](LANE_NEXT_EVALUATION_2026-10-01.md) for the frozen sources, labels, six arms and limitations. The original 2,600 frames are development data; 400 exposure-disjoint frames from the same day/dawn drives form the fresh holdout. Full-night and independent-drive validation are unavailable.

On 16 fresh labelled frames containing 21 true borders, tentative identity retention raises correct displayed borders from 5 to 9 with two false positives in each arm. However, unsupported visible duration on the separately reviewed 10-second unmarked clip rises from 0.2 to 0.8 seconds. The combined option raises it to 2.3 seconds. Joint selection alone provides no labelled improvement. Therefore these options remain experimental, not enabled by default.

The disabled-option pipeline is exactly equivalent to the frozen original on all 2,600 development frames. Swift/Kotlin host replay matches exactly on 600 frame/arm pairs, including 44 frames with identity expiry. These checks validate shared semantics, not physical iPhone performance.

Evidence is stored in `inspector/logs/2026-10-01-lane-next/`. Completed replay outputs were losslessly compressed after SHA-256 verification to relieve host storage pressure; `compression-manifest.json` preserves both compressed and uncompressed hashes. Original videos and labels remain unchanged.

## Validation status

- Native Swift core: 90 tests passed.
- Android: 586 unit tests passed; the real-camera instrumentation source compiled. Final harness corrections are checked in `android-checks-final.log`.
- Host recorded parity: 600/600 exact, maximum numeric difference zero; `host-parity/summary.json`.
- Full iOS SDK arm64 typecheck passed for the production application and runtime/workload XCTest source; `ios-full-workload-typecheck.json` records hashes and reproduction. This does not include linking, signing or device execution.
- Python: 16 tests passed, including lossless archival/scoring equivalence; `python-tests.log`.
- Physical Android baseline 10025: 600.412 seconds, 2,277 lane frames, 3.80 Hz lane exposure cadence, p95 exposure gap 433.5 ms, p95 lane preparation 20.47 ms, sampled RSS maximum 997.6 MB, thermal status 0 throughout. Its media-preservation assertion failed, so this is qualified observational evidence, not a passing full-workload result. Scene luma averaged 2.28/255; no still photos or classifier calls were observed. The photo encoder, moving-road accuracy and sign-classifier load were not validated. Logged inference events are throttled and are not an inference-throughput count.
- Android candidate 10026: 600.919 seconds passed, including preserved original-movie SHA hashes and restored preferences. Lane cadence 7.25 Hz, preparation p95 23.31 ms, sampled RSS maximum 1,106.75 MB, no sampled thermal pause. Final Android 10027 passed a 30.351-second telemetry-format smoke and is installed.
- iPhone 10026 failed before recording due to a test-harness synchronization race. The 10027 run stopped after 144.668 seconds, with a finalized 4K movie, two real photos and no sampled thermal pause. The original cause was masked by a harness error. Build 10028 preserves original failure state and inference totals and is installed. Its first run stopped at 229.187 seconds due to the app entering the background and AVFoundation interrupting the camera, with thermal state 0. It processed 2,282 timed lane frames and 440 completed inferences. Its final retry stopped after 121.210 seconds for the same background session interruption, with 1,202 timed lane frames and 233 completed inferences. No successful sustained physical iPhone or thermal-improvement claim is made.

Android workload validation and verified cleanup of all pre-existing videos/logs are complete. The new iPhone test outputs are archived and verified before movie/log removal. Remaining: obtain an uninterrupted 600-second foreground iPhone run. Moving-road, busy-classifier and actual photo-capture validation remain necessary before claiming crash resolution or changing experimental defaults. Device files are removed only after verified local copies exist.
