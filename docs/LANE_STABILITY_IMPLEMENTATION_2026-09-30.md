# Lane stability implementation — 2026-09-30

Development candidate following [the build 10022 drive review](LANE_BUILD10022_DRIVE_REVIEW_2026-09-30.md). Implemented in matching Kotlin/Swift code. **Deployed as build 10023 to both attached devices; not field-qualified.** Road-graph priors remain behind the review's visual-tracker validation gate.

## iPhone field-test result

Build 10023 failed the subsequent iPhone test: 744/744 preview preparations exceeded their budget, followed by thermal pause. Unoptimized deployment and intrinsic-value identity resets were reproduced independently. See [the iPhone failure diagnosis](LANE_IPHONE_BUILD10023_FAILURE_2026-09-30.md). The earlier host results below are engineering evidence, not successful iPhone validation.

## What changed, in order

### 1. Independent preview and elapsed-time continuity

Both apps now use a separate `RoadPathSession(previewMode: true)` through the existing bounded lane worker. Preview admission targets 100 ms between exposures, including while traffic-sign recognition is active. It retains one running and one latest pending downsampled image, copies pixels before returning the camera buffer, and checks current camera/activity/thermal scope before publishing. Preview geometry is bounded to 384×216 with the existing 50 ms preparation budget. Camera and calibration changes reset continuity; map/sign-context turnover no longer determines preview admission.

The default TSR sidecar remains separate. Sharing its geometry with the preview would make this larger change affect sign evidence; the initial implementation deliberately pays for separate preparation. The next device run must measure this extra CPU cost, thermal behavior, recording continuity and TSR latency. Ten Hz is an admission target, not a measured Moto throughput claim.

Preview identities survive multiple missed exposures for up to the existing 0.75-second time window. Missing coordinates are never republished. A calibration reference initially waits one second and waits two seconds after an observed line disappears before returning. References stay faint and dashed. This addresses rapid reference/detection substitution without holding stale paint on screen.

### 2. Bounded motion prediction with image correction

The preview can unproject supported points through upright camera intrinsics onto an approximate road plane. It integrates held causal speed and GNSS heading rate over the frame interval, including constant-turn translation, then projects into the new view. A compatible visual horizon adjusts the effective plane pitch. Static mount pitch/roll/yaw and lateral offset are included.

This prediction centers a bounded two-dimensional patch search. Forward/backward patch agreement and coherent residuals still determine whether evidence survives. Prediction alone cannot produce a displayed line; blank-image tests cover that constraint. Invalid/unverified calibration, stale or imprecise heading, excessive turn rate/travel, points above the ground plane or points leaving the image are rejected. With no usable motion model the original search remains unchanged.

This is the first bounded motion-association implementation, **not** a full world-coordinate curve filter or IMU attitude estimator. The saved bus mount is approximate. Exposure-time gyro/pitch/roll, calibrated uncertainty, hill/crest handling and speed integration over multiple fixes remain follow-up work. Do not interpret the `motionProjectionEligible` diagnostic as proof that any particular patch was successfully tracked.

### 3. Persistent selection of the two sides

After the existing maturity gate, the preview ranks current candidates on each side of the calibrated visual center (image center when calibration is unavailable). It considers evidence confidence, paint versus edge support, extent and distance. A lower-image anchor avoids discarding short, near-field boundaries. Candidate pairs must remain ordered, bracket the expected path and have plausible image width over their supported lower overlap.

The output has at most one left and one right boundary. An established visible side requires a score advantage sustained for 0.35 seconds before switching. A missing incumbent may be replaced immediately by a nearby already-mature curve; an unrelated candidate waits briefly. Zero or one side is valid. All other candidates remain internal, and the default TSR evidence retains them.

This is a conservative image-space selector, not a semantic guarantee that paint bounds the ego lane. Opposing-lane edges, ambiguous junctions and large calibration errors still need labeled evaluation. Heuristic confidence is not calibrated accuracy.

Both platforms log independent preview frames with exposure timestamps, preparation time, source geometry, selected lines/IDs and motion eligibility/context. Capture-configuration logs identify `independent_preview` as the source.

## Replay results and rejected variants

Source: the preserved build 10022 dashcam and diagnostic export. Three consecutive clips (turn, forest, junction), 600 exposures at approximately 10 Hz, 59.73 seconds observed span. Baseline and candidate use identical bytes and timestamps. Each clip starts with an empty tracker. No GPS, camera calibration or visual calibration is invented for the encoded-video crop.

| Replay | Visible identities | Median visible identity span | Blank frames | Frames with more than two lines | Identity-set transitions |
|---|---:|---:|---:|---:|---:|
| Build 10022 core at 10 Hz | 97 | 0.30 s | 172/600 | 42 | 216 |
| Time-based identity retention only | 69 | 0.70 s | 118/600 | 76 | 267 |
| Final bounded preview | 49 | 0.70 s | 148/600 | 0 | 216 |

The final candidate displays some boundary in 452/600 frames versus 428/600 for baseline. Raw detector/tracker output remains identical in this replay because no motion calibration is supplied: 2,467 raw boundaries, including 988 fused and 88 tracked. Selection and maturity account for the output change.

Identity count fell 49.5%, but appearance/disappearance transitions did **not** improve. These counts do not establish accuracy, motion-compensated jitter reduction or device performance. Fewer identities can also reflect suppressed candidates. This drive was used to develop the candidate; acceptance requires an untouched drive and labeled consecutive frames.

Two exploratory changes were rejected:

- Unconditionally widening patch search without a valid motion model reduced fused evidence from 988 to 862. Wider search is now restricted to eligible motion projection.
- Raising fusion weight/correction distance and an overly restrictive selector produced 230 blank frames. Visual checks found lost genuine near-field boundaries. Original fusion limits were restored; lower-image selection and nearby mature replacement reduced blank frames to 148.

Host replay produced no budget/deadline failures. Those timings exclude camera copying/decoding and do not establish phone performance. The full 3,481-frame replay with default preview mode **off** matched baseline raw geometry, visible IDs, maturity, corridor hypotheses, temporal work counts and budget results exactly. TSR/speed-reference behavior was not changed.

## Verification

- Android: **552 unit tests passed**, zero failures/errors/skips; debug APK assembled.
- Swift shared lane core/presentation: **61 native XCTest tests passed**.
- Python: **7 replay/evaluation tests passed** in the OpenCV environment; all **600** comparison-video frames decoded successfully.
- iPhone: generic-device Debug build succeeded with signing disabled.
- New coverage: forward motion and turn direction; stale/unverified/uncertain model rejection; no tracking through blank imagery; multi-miss expiry; side cardinality, crossing and switching; reference hysteresis; ten-Hz worker admission, bounded replacement and stale scope/thermal rejection.
- Android/iPhone tests exercise the same geometry and selector scenarios. The deployment follow-up verified installation/startup on the attached Moto g86 5G and iPhone 14 Pro; road behavior remains unvalidated.

Reproduce host checks (Python requires the existing OpenCV/NumPy environment):

```sh
bash scripts/lanes/test_preview_native.sh
(cd android && ./gradlew --offline :app:testDebugUnitTest :app:assembleDebug)
python3 -m unittest discover -s scripts/lanes -p 'test_*.py'
```

Use `scripts/lanes/replay_recorded_pipeline.py --preview-mode` with a new output directory. `compare_preview_replays.py` requires matching input hashes/order/timestamps; `--require-unchanged` additionally checks the default sidecar geometry and identity contract. Frozen sources and their hashes are saved with each replay.

Local ignored evidence directory: `inspector/logs/2026-09-30-lane-stability-implementation/`:

- `final-replay/`: final 600-frame candidate and source manifest.
- `final-comparison.json`: paired baseline/candidate metrics.
- `sidecar-final-comparison.json`: full-drive default-sidecar regression.
- `ablation.json`: exploratory variants, including rejected versions.
- `preview-comparison.mp4`: 60-second paired offline polylines, not a recording of live app UI.
- `android-tests.log`, `swift-tests.log`, `iphone-final.log`: build/test evidence.

## Next gate, then road-graph priors

Before implementing step 4, test this visual candidate on the attached Android with an untouched recording. Check both TSR on/off, stop/restart, camera rotation, calibration save, preview visibility and thermal pause. Measure actual cadence and preparation failures, frame loss, reference switches, stationary false lines, motion-compensated residual and correct-side availability. Compare CPU/thermal load and TSR inference latency against build 10022. Manually label consecutive straight, curved, unmarked, shadowed, intersection and bump sequences. The current replay's unchanged transition count is a reason to keep this gate.

The installed map has no lane-count fields. Do not infer lane counts from road class or force two lines. After the visual gate, extend the shared map export and both readers with optional raw/normalized `lanes`, `lanes:forward`, `lanes:backward`, `lanes:both_ways`, `oneway`, directional turn-lane, junction and width values. Missing/invalid values remain unknown; old bundles must behave identically. Validate OSM-way direction against travel direction rather than dividing every total count by two. Deliver timestamped, stable matched-way hints from the existing asynchronous lookup worker; never query SQLite on the camera worker. Use topology/width/count only as weak ranking constraints, attenuated near junctions, stale matches and contradictory visual evidence. Road geometry must never manufacture painted lines.

No bundle schema/model, protected speed-reference policy, server artifact, commit or push was changed by this implementation pass.

## Deployment follow-up

At the user’s request, build **10023 / 1.3** was installed and launched on the attached Moto g86 5G (Android debug) and iPhone 14 Pro (signed Debug). Installed version numbers were verified on both devices. Existing app data was retained; Android’s startup log-size prompt was dismissed with **Keep logs and continue**. Android testing comes first, followed by iPhone. Installation evidence and APK hash are in `deployment10023.json` beside the replay logs.
