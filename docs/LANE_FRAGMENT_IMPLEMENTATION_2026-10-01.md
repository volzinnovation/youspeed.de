# Lane guide diagnostics and fragment experiment implementation — 2026-10-01

This change adds preview calibration checks and opt-in experiments for search bands, dashed-paint grouping and fragment tracking. It does not establish that the experiments improve driving performance. Recorded-clip evaluation and device acceptance are reported separately.

## Active behavior and experiment controls

Both clients use the same arithmetic and thresholds. `RoadPathSession(previewMode: true)` enables the guide trust policy and diagnostics. The following experiment options remain **off by default**, including in the production preview session:

| Option | Effect when enabled in a preview session |
| --- | --- |
| `RoadBoundaryDetectionOptions.useSearchBands` | Uses two soft search bands, with broad candidate fallback. |
| `RoadBoundaryDetectionOptions.groupFragments` | Groups geometrically consistent paint fragments, retaining their observed support intervals; also enables fragment-aware presentation matching and side selection. |
| `RoadPathSession.fragmentTracking` | Samples actual paint intervals and endpoints for temporal patch matching, with bounded motion uncertainty. |

The four primary detection ablations use baseline, bands only, fragments only, and both, with `fragmentTracking` disabled in each. Tracking is a separate experimental factor. Brightness thresholds are not changed by these options.

Default TSR sidecar sessions force the baseline detector options and disable fragment tracking, even if experimental options are supplied. They retain the existing visual-guide and association behavior. The shared speed-limit policy and its interpreters are not modified.

## Calibration diagnostics and guide trust

Preparation diagnostics record the current exposure's normalized `fx`, `fy`, `cx`, `cy`, calibration revision and stable calibration generation. Small intrinsic changes retain the existing anchored identity: focal lengths may vary by 0.5% and principal points by 0.001 relative to the fixed anchor. Cumulative changes beyond those bounds start a new generation. These tolerances do not freeze the intrinsics used for projection.

`resetComponents` identifies changed scope, camera, geometry, calibration, visual revision, clock availability and lifecycle components. Initial admission and rejected exposure ordering have explicit markers; additional temporal reset reasons are retained. A rejected ordering marker does not mean the prior was reset. Timings separate luma preparation, queue/admission, filtering, prediction, detection, fusion, presentation and total preparation.

Saved guides begin as a **weak prior**. They cannot set the preview horizon, ego centre or motion-plane adjustment until checked against independent fresh paint. On broad audit exposures, the detector receives neither saved nor predicted polylines. The validator compares the nearest independently observed paint border on each side of the image centre with the saved guides over their common observed span. Tracked evidence cannot establish guide trust.

Trust requires both sides to agree on three audit exposures spanning at least 0.2 seconds. Median horizontal residual must be at most 0.055 image widths, and maximum residual at most 0.085. An independently observed residual above 0.10 immediately weakens the guides. Agreement expires after one second without a confirming audit. Weak guides are audited every other admitted exposure; trusted guides every fifth exposure. Audit frequency therefore follows capture cadence rather than a separate timer.

Weak guides can supply supplemental polylines on the other exposures; they do not impose a horizon or calibrated ego centre. Once a conflict is discovered, side selection drops the guide centre on that same exposure. Incompatible geometry disables guide use. The saved calibration is never silently overwritten, and TSR's calibration crop remains unchanged.

Logs distinguish `guidePriorUsed`, which describes the prior admitted for this frame, from `guideTrust`, which includes the result of its fresh evidence check. `motionProjectionEligible` describes the actual projection object supplied to prediction after the admission-time trust check. Eligibility is not proof of a successful paint match. Detector rejection counts and presentation side-selection decisions explain subsequent losses.

## Separate model and paint support

A grouped boundary contains a fitted model and `observedSegments`, the separate painted support intervals. `geometryConfidence` and `paintOccupancy` remain distinct diagnostics. Temporal fusion preserves the current exposure's observed segments instead of replacing them with a continuous fitted curve. Detector rejection counts and the experiment variant survive temporal completion and JSON serialization.

With fragment tracking enabled, at most eight anchors are sampled from up to four painted intervals, prioritizing endpoints before interior points. Fitted gaps are never sampled as observed paint. Forward and reverse patch matches still require image contrast, bounded SAD, distinct horizontal evidence and coherent displacement. Three bounded coarse candidates are refined to avoid a two-pixel sampling-grid failure at moving dash endpoints; the image acceptance thresholds are unchanged.

The model may interpolate across a gap for search guidance. Carried paint support contains only confirmed patch positions, is marked `tracked`, and retains its last-fresh timestamp. Missing fresh evidence cannot survive more than 0.8 seconds. Fragment-aware side selection hides tracked-only boundaries; a prediction cannot appear as newly detected paint. At most one accepted border per side is presented, without requiring all valid fragments to touch one fixed lower image row.

## Uncertainty, budgets and limits

The optional motion search envelope is an **engineering heuristic, not a statistical covariance**. It perturbs speed by ±10% (at least 1 m/s), increases that range with fix age, and perturbs road-plane pitch by ±0.5°. A one-pixel allowance covers small intrinsic variation. Its additional radii are capped at eight horizontal and six vertical pixels; the existing overall horizontal search remains capped at twelve pixels. Actual forward/reverse image matches are still required.

The projection retains its existing calibration, fix-age, course-quality, travel and image-bounds checks. There is no new IMU attitude estimator, learned uncertainty model or road-graph lane-count authority. A broad image-centred guide audit can still confuse adjacent-lane paint, intersections or perspective on sharp curves; the trust thresholds require held-out validation. This policy detects inconsistency rather than computing a replacement mount calibration.

**50 ms remains an engineering target, not a cancellation cutoff.** Input-size and operation caps, stale-frame publication checks, lifecycle invalidation and thermal protection remain in force. Legacy budget field names can still indicate operation exhaustion; they must not be interpreted as a 50 ms timeout.

The default settings preserve the existing tracker, while the experiments remain gated pending measured correctness, unsupported display duration, identity continuity, jitter, reacquisition, latency, memory and thermal results. Passing synthetic tests alone cannot establish road performance, particularly at night.

## Source and regression coverage

- Session integration and diagnostics: [Swift](../iphone/SpeedConsumerApp/RoadPathSession.swift), [Kotlin](../android/app/src/main/java/de/youspeed/android/alpha/RoadPathSession.kt).
- Guide trust: [Swift](../iphone/SpeedConsumerApp/VisualRoadCalibration.swift), [Kotlin](../android/app/src/main/java/de/youspeed/android/alpha/VisualRoadCalibration.kt).
- Detector options and support intervals: [Swift](../iphone/SpeedConsumerApp/RoadBoundaryDetector.swift), [Kotlin](../android/app/src/main/java/de/youspeed/android/alpha/RoadBoundaryDetector.kt).
- Fragment tracking and motion envelope: [Swift tracker](../iphone/SpeedConsumerApp/RoadBoundaryTemporalTracker.swift), [Kotlin tracker](../android/app/src/main/java/de/youspeed/android/alpha/RoadBoundaryTemporalTracker.kt), [Swift motion](../iphone/SpeedConsumerApp/RoadBoundaryMotionHint.swift), [Kotlin motion](../android/app/src/main/java/de/youspeed/android/alpha/RoadBoundaryMotionHint.kt).
- Guide/generation regressions: [Swift tests](../iphone/SpeedConsumerTests/RoadPathSessionTests.swift), [Kotlin tests](../android/app/src/test/java/de/youspeed/android/alpha/RoadPathSessionTests.kt).
- Translated-dash support, metadata preservation, occlusion and evidence age: [Swift tests](../iphone/SpeedConsumerTests/RoadBoundaryTemporalTrackerTests.swift), [Kotlin tests](../android/app/src/test/java/de/youspeed/android/alpha/RoadBoundaryTemporalTrackerTest.kt).
- Motion-envelope bounds: [Swift tests](../iphone/SpeedConsumerTests/RoadBoundaryMotionHintTests.swift), [Kotlin tests](../android/app/src/test/java/de/youspeed/android/alpha/RoadBoundaryMotionHintTest.kt).

## Validation failure: held-out fragment mode

This is a **read-only diagnosis of the frozen held-out runs**, not threshold tuning on the holdout. The comparison covers 400 frames in four day/dawn sequences and 16 previously labelled keyframes containing 27 border instances. Labels are approximate Codex visual annotations, not independent human ground truth. Full-night behavior is not established.

| Stage observation | Baseline | Fragments only |
| --- | ---: | ---: |
| Labelled border instances with any geometrically correct raw hypothesis | 24 / 27 | 17 / 27 |
| Correct visible border instances in labelled keyframes | 9 | 4 |
| Incorrect visible border instances in labelled keyframes | 1 | 3 |
| Frames with any visible border, of 400 | 237 | 152 |
| Geometry budget failures | 0 | 0 |

Three mechanisms explain why fragment mode should remain disabled:

1. **The fragment path also rejects continuous paint.** It applies a global quadratic-model gate to every paint track, including tracks that do not need a gap bridged. The run recorded 823 `fragment_geometry` rejection events in 349 frames, versus only 16 successful `fragments_joined` events. The join stage additionally recorded 2,540 tangent and 1,113 endpoint rejections. These are candidate/pair events, not counts of distinct missed borders. Current `fragment_geometry` diagnostics combine residual, slope and curvature failures, so they cannot establish which condition dominates. The reduction from 24 to 17 correct raw hypotheses at labelled frames shows that presentation changes alone cannot recover all losses.

2. **Intermittent fresh geometry prevents useful tracks from maturing.** In `holdout-dawn-dashed-0053` through `0062`, the baseline's right-border track retains ID 12 and remains visible on all ten exposures. Fragment mode produces a corresponding right-border hypothesis only at `0057` and `0060`; they enter as different tentative IDs 25 and 26. The intervening scan results contain geometry rejections or no corresponding fresh border. At labelled keyframes, 13 correct raw border instances remain hidden in fragment mode; 11 include a `not_mature` match, one is only tracked, and one is held for incumbent reacquisition. This is not a reason to display predictions as fresh paint: it points to preserving model identity while obtaining reliable new paint observations.

3. **Geometrically consistent paint does not establish the ego border.** The fragment result selects a gutter beside the actual right stripe in [ramp frame 0035](../inspector/logs/2026-10-01-lane-fragments/heldout-failure-review/holdout-day-ramp-0035.jpg), the opposite carriageway's outside edge in [dawn frame 0085](../inspector/logs/2026-10-01-lane-fragments/heldout-failure-review/holdout-dawn-dashed-0085.jpg), and guardrail-adjacent clutter in [frame 0060](../inspector/logs/2026-10-01-lane-fragments/heldout-failure-review/holdout-dawn-unmarked-0060.jpg). Their reported geometric confidences are approximately 0.87, 0.79 and 0.58 respectively, and paint occupancy is 0.94, 1.00 and 1.00. Good fitted geometry or dense support is therefore insufficient evidence of the correct ego border. The comparison images show labels in green and displayed output in red.

These runs supplied no GPS, metric calibration or saved visual guides: every guide-trust state is `unavailable`. Consequently, the recorded regression cannot be attributed to the new guide trust/horizon policy, and these runs do not validate calibrated vehicle-motion tracking. The separate fragment-tracking flag was disabled in all four primary arms.

Next research should use development data to (a) preserve an already supported continuous border while testing robust or piecewise fits only where gap grouping is needed; (b) split fit rejection diagnostics into residual, slope and curvature measurements and record which candidate fragments were considered; and (c) evaluate ego-corridor association against outside lane edges, gutters and guardrails. After changing the model, select a new untouched holdout instead of repeatedly optimizing against these scenes. Brightness thresholds and the rule against displaying unsupported predictions should remain unchanged during those experiments.

The reproducible stage aggregation, with replay and label hashes, is saved in [heldout-failure-stages.json](../inspector/logs/2026-10-01-lane-fragments/heldout-failure-stages.json). Full accuracy and continuity reporting remains in the evaluation report; raw image displacement is not motion-corrected jitter.
