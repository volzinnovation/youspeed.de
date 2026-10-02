# Lane presentation, calibration fallback and GPS hints — build 10019

This follows the build 10018 drive. Both native implementations now require repeat observations before displaying a boundary. Missing context uses the user's two saved reference lines at 28% opacity, without a horizon or point markers. GPS speed and course feed a small hint into the existing image tracker. TSR models, thresholds, temporal fusion, admission and the speed-limit state machine are unchanged.

## Findings from the two new recordings

Both recordings used the saved visual calibration and enabled lane display. The 1,807 logged processed frames ran at about 2 Hz. The longest gaps were 5.10 and 7.50 seconds and coincided with invalid road context. Tracking supplied only three tracked-only boundaries across both recordings; most output was fresh or fused with a current observation. A 750 ms detected-overlay lifetime cannot bridge those context gaps.

Many geometrically linked contours lasted a single observation. They include both transient clutter and genuine dashed paint, so this count is not a false-positive rate. RGB review selected marked straight roads, a marked curve, cracked pavement, unmarked village roads and parking/context transitions as replay controls. The private audit and original recordings remain in ignored build reports.

The live lane/path work stayed below 200 ms: added-work p95 was 48.32/50.60 ms, maximum 57.64/62.01 ms. The narrower 50 ms preparation deadline aborted 39/40 frames and contributed to disappearing output.

## Display continuity

The small presentation gate matches at most six current boundaries by cue and overlapping image geometry. A new boundary needs at least two fresh/fused exposures spanning 300 ms before display; tracked-only results cannot establish it. A missing observation immediately hides that boundary, while its identity may survive one missing exposure for at most 750 ms. No old points are fabricated to bridge a gap. Duplicate and older exposures do not count or clear history. Capture, geometry, calibration and lifecycle changes reset incompatible identities.

Raw detector geometry remains available to existing processing and diagnostics. Only the display selection is filtered. The TSR-disabled legacy preview uses the same gate on its output without changing its detector. This adds approximately one processed-frame interval to initial display, an intentional tradeoff for hiding brief artifacts.

When no confirmed current boundary is available, the preview draws exactly the two compatible saved calibration lines. They are straight, dashed, bright green at alpha 0.28 and labelled “Calibration reference.” They are display references, never observed lane or sign evidence. A lightweight camera callback records current geometry at 5 Hz without copying pixels, so Android's missing TSR/map admission cannot prevent the reference overlay. Stopped/hidden/background/thermal-paused cameras, stale geometry or incompatible calibration suppress it.

The recorded live source was 1600×1200; the saved calibration is 1920×1440, both 4:3. Encoded dashcam video is 1280×720. The saved reference must not be applied unchanged to those replay pixels. Replay uses actual encoded frames without inventing a crop transform or replacing the phone's calibration.

## GPS input

Reuse the existing accepted GPS fixes. The latest two fixes no later than an exposure provide speed and wrapped course change. A moving turn over 6 degrees/second raises horizontal patch search to its existing 12-pixel maximum. Image contrast, bidirectional correspondence, support tests, operation caps and deadlines remain in force. GPS does not move a line by itself, increase its confidence or reset presentation history. No separate GPS quality/health policy was introduced. Without a usable motion hint, existing search behavior is exact.

Logs preserve raw and displayed boundary counts, stable presentation IDs, maturity/missing states and suppression reasons. GPS diagnostics include the fixes' time separation, heading change/rate, speed and whether the hint was used. Separate bounded preview diagnostics identify observed, calibration-reference and hidden modes with calibration revision and actual source geometry.

## GPS arrow and disagreement assessment

The bundle already supplies the nearest polyline segment's `localTangentDeg` through `TSRMapGeometry`. A GPS-versus-road arrow can therefore reuse existing data: select the tangent or its 180-degree reverse toward current travel, subtract it from GPS course with wrapped angles, and draw one arrow near the calibrated center. The existing applicability geometry already uses that direction-selection operation. Do not reuse Swift's whole-way endpoint travel-direction helper for this local curved-road comparison. This needs neither a model nor another route-graph query and is a small implementation on each platform.

That angle measures GPS/map disagreement. Establishing a north-to-camera transform additionally assumes alignment with the local road; the saved straight-road calibration can provide the mounting reference. An absolute course arrow should not be compared directly to a perspective lane slope. Curves, junctions and a heading-dependent map match complicate that comparison. The current geometric boundaries also include non-lane contours, even after maturity filtering. A sustained visual disagreement diagnostic is inexpensive, but a driver-facing lane-departure warning needs separate replay validation of those cases. No arrow or departure warning is enabled in build 10019.

## Validation

- Android: all 531 unit tests passed; debug app and instrumentation APK built.
- Swift native: 43 detector/session/tracker/presentation/GPS tests and seven fallback tests passed. Generic iPhone build 10019 succeeded.
- Moto g86: installed build 10019, replayed 191 frames across eight windows from the new recordings. All filter hashes matched; no freshness/presentation violations, thermal pauses or 50/200 ms temporal-session deadline misses. Lane/path component p50/p95/max was 16.49/24.11/44.79 ms. This excludes full-resolution camera sampling, TSR inference and live recording contention.
- Display selection reduced 803 raw boundary observations to 161 mature observations. At least one boundary appeared on 105 frames, versus 181 raw-positive frames. Initial confirmation p50/p95 was 434/467 ms. These are presentation counts, not accuracy scores.
- Marked-road controls retained at least one curve on 22/23 and 17/23 frames. This does not establish a correct pair: visual review shows some real paint is suppressed, while persistent vegetation/parked-car contours can still mature. The change quiets the display; semantic lane recognition remains incomplete.
- Independent native Swift replay matched the Moto's 803 raw and 161 mature counts on the same 191 frames. The prior 138-frame set also completed without a gate/geometry budget abort.
- Encoded video PTS is exact, but its UTC alignment to original GPS arrival is not exact enough to claim causal replay. Recorded replay therefore uses no invented GPS input; motion-hint behavior is covered separately by native/unit tests.
- Final on-device preview check: two faint dashed lines, no horizon or point handles, localized calibration-reference label. Runtime logs confirm `reference_line_count=2`, alpha 0.28, source 1600×1200/180°, and hiding at capture stop. The saved calibration revision and enabled lane preference were preserved. The brief standstill validation recording was stopped; original drive recordings remain intact.

The final installed Android APK SHA-256 is `b472d3aa6b42d06681826c31967c8294023ff4eb14e9b32ec1dc79d6232894db`. The recorded replay ran on the preceding build artifact `745475bad3659136f1923fa8c0b1eaf45ff421b69e6abcd5a02b3518a4fbc39a`; the only subsequent production change resets the TSR-disabled legacy presentation gate when a paused snapshot arrives. All 531 Android tests were rerun successfully after that fix. The replayed road-path implementation is unchanged.
