# iPhone build 10023: lane failure diagnosis — 2026-09-30

**The failure is confirmed. All 744 recorded preview evaluations exhausted the 50 ms preparation budget; none produced a visible boundary.** Later, thermal protection disabled lane analysis. The recordings contain clearly visible lane markings, and their files decode correctly.

The deployed iPhone build was unoptimized Swift Debug (`-Onone`). Earlier host evaluation used `-O`. Installation/startup and optimized host tests did not validate the actual deployed performance. This was a validation gap in the previous deployment.

A separate, reproduced continuity defect would remain after the performance fix: the lane session includes every floating-point intrinsic value in its tracking identity, so tiny per-frame camera-metadata changes discard track history.

## Preserved evidence

Exported from the attached iPhone 14 Pro, app `de.youspeed.SpeedConsumer`:

- Latest TSR/lane diagnostic log: 22,330,286 bytes.
- Matching drive log and saved preferences/calibration.
- Three complete dashcam MOV files: 734,238,820 bytes total, about 3 minutes 51 seconds.
- All **6,940 video frames** decoded successfully. Local file byte counts match the device inventory; local SHA-256 hashes are in `video-inventory.json`. Device-side cryptographic hashes were not available.
- Original device files were retained. App code/settings and installation were not changed during this investigation.

All local evidence is under `inspector/logs/2026-09-30-iphone10023-drive/`. The local second clip's short filename is `drive-164815.mov`; its actual start is **16:48:56 UTC**, as established by the recording callback below. Use the logged anchors, not the short filename, for alignment.

| Recording start, Germany/CEST | Duration | Frames | Observed lane state |
|---|---:|---:|---|
| 18:47:45 | 30.368 s | 911 | Every evaluated preview frame exceeded its budget; no saved visual calibration yet |
| 18:48:56 | 65.070 s | 1,952 | Budget failures, then `thermal_paused` from 18:49:40.726 |
| 18:51:16 | 135.912 s | 4,077 | Saved calibration present; display remained `thermal_paused` |

Recording anchors are callback estimates, not a precision UTC-to-encoded-frame synchronization contract. The 41-second gap between preview episodes corresponds to separate recording/visibility episodes, not a 41-second worker stall.

The first two recordings show clear center dashes and road-edge markings in daylight. The last recording is mostly an urban street with less explicit paint, where zero or one observed boundary can legitimately be appropriate. `video-contact.jpg` documents sampled scenes. MOV rotation metadata is 180 degrees and was honored during inspection/replay extraction.

## 1. Preparation never reaches useful detection

Preview diagnostics:

- **744/744 `geometry_budget` failures**; 0/744 frames with visible lines.
- Preparation median **50.209 ms**, p95 **50.478 ms**, maximum **91.029 ms**.
- Median exposure interval **100.007 ms**: preview admission did run at approximately 10 Hz while allowed.

The simultaneous TSR path provides stage detail that the preview log currently lacks: median luma copying **12.810 ms**, filtering **37.200 ms**, and geometry work **0.033 ms**. The budget is effectively spent before boundary detection. These are *simultaneous TSR stage measurements*, not attributed measurements of individual preview stages.

The camera delivers **3840×2160** frames. Preview and TSR prepare separate low-resolution luma/filter inputs. The deployed Debug configuration uses `SWIFT_OPTIMIZATION_LEVEL = "-Onone"` in `iphone/SpeedDBBench.xcodeproj/project.pbxproj`; the earlier replay executable used `-O`.

### Controlled recorded-image optimization comparison

Replayed 150 identical decoded frames, three five-second intervals at about 10 Hz, through the same production Swift source. Source and input-manifest hashes match across builds; only optimization changes.

| Mac host replay | Budget failures | Frames with raw evidence | Frames with visible evidence | Median preparation |
|---|---:|---:|---:|---:|
| `-Onone` | **150/150** | 0 | 0 | **50.033 ms** |
| `-O` | **0/150** | 147 | 66 | **0.823 ms** |

This reproduces the failure mechanism and supports optimized code generation as the first fix. It does **not** establish optimized iPhone latency, thermal sustainability, or lane accuracy. Encoded images were auto-rotated, converted from decoded BGR to grayscale and sampled at pixel centers; they are not bit-exact live camera Y planes. No GPS or saved calibration was transplanted into the replay.

## 2. Camera intrinsics are incorrectly part of track identity

`RoadPathSession.swift` uses the full `String(describing: frame.calibration)` in both `scopeKey` and `temporalKey`. The Kotlin counterpart also includes the entire calibration object. This treats ordinary numeric metadata changes as a new camera/mount configuration.

Within the simultaneous iPhone sample, **343/343 consecutive calibrated pairs** with unchanged image geometry and calibration revision had different intrinsic values. Median changes were approximately 0.000018 in normalized `fx`, 0.000032 in `fy`, 0.000018 in `cx` and 0.000021 in `cy`.

A separate synthetic probe removes performance and image changes as explanations:

- Identical painted images, stable intrinsics: raw evidence on 10/10 exposures; visible output on **7/10** after maturity.
- Identical images, only `cx += 0.00001` each exposure: raw evidence on 10/10; **0/10** visible; `scope_or_geometry` resets on all nine subsequent frames.

This is a confirmed independent defect. It was masked by the live preparation failures, so it is not counted as the cause of those 744 budget rejections. Simply deploying an optimized build would leave it unresolved.

## 3. Thermal pause and missing reference lines explain the later blank view

The display log first switches to `thermal_paused` at **18:49:40.726 CEST**. At that point, the 744th and final preview evaluation is still in flight. No later preview evaluation is recorded. The next recording, starting at 18:51:16, reports thermal pause throughout its sampled display events.

Visual calibration was saved at **18:51:07.503 CEST**, after thermal pause had already begun. Before that, `calibration_unavailable` explains why no fallback reference guides appeared when detection failed. Missing visual calibration does not prevent the image detector itself from running.

The app reported a serious/critical thermal gate, not a measured temperature; the exact heat contribution of 4K capture, TSR, preview work, display and other system activity cannot be separated from these logs. Do not disable thermal protection or raise the 50 ms limit to conceal this failure. Most `preview_hidden` events occur outside the visible recording episodes; their count alone is not evidence of a visibility bug.

## Fix order before another drive

1. **Use optimized code for device performance tests.** Add a reproducible optimized, development-signed configuration or deployment option; record configuration and compiler optimization in diagnostic headers. Retain diagnostics. Verify the actual installed artifact on the iPhone, including sampling/filtering/queue time, rather than relying on host timing.
2. **Separate calibration identity from per-frame measurements on both platforms.** A camera/mount/rotation/crop revision establishes identity. Continue using current intrinsics for projection; reset only for meaningful calibration changes, with a tolerance/stateful threshold rather than string equality or unstable rounding bins. Keep preview changes isolated from the protected speed-reference policy and separately validate TSR evidence semantics.
3. **Recheck thermal load with the optimized code.** Add preview stage/queue timings and explicit thermal-state transitions. Measure sustained 4K recording with TSR and preview together. Reduce duplicated preparation or analysis demand if necessary; do not weaken thermal safeguards.
4. **Then repeat the visible-lane acceptance test.** Start with the clear painted sections, confirm the saved calibration is compatible, and measure actual visible continuity and correctness. Smoothness/pair thresholds and map priors should wait until frames can finish and identities survive.

At the time of this diagnosis, no new production fix had been deployed. The subsequent iPhone build 10024 fix and installation are recorded in [the follow-up](LANE_IPHONE_BUILD10024_FIX_2026-09-30.md).

## Reproduction and artifacts

- `scripts/lanes/audit_iphone_lane_failure.py`: read-only log audit; output `audit.json`.
- `scripts/lanes/replay_recorded_pipeline.py`: now records/accepts `--swift-optimization=-Onone` for controlled build-mode comparison; its default remains `-O`.
- `scripts/lanes/ProbeCalibrationContinuity.swift`: compile with the same nine production source files used by the replay harness; prints the stable/drifting-intrinsics comparison.
- Evidence: `replay-input.json`, `replay-debug/`, `replay-optimized/`, `CalibrationChurnProbe.swift`, `calibration-probe.json`, `video-inventory.json`, `video-decode-verification.json`, `video-contact.jpg`.
