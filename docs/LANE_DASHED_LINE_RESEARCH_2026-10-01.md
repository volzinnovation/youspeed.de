# Dashed lane detection and calibrated search zones — 2026-10-01

## Recommendation

Test **two calibrated, curved search bands plus fragment-aware boundary tracking**. The current preview already selects at most one border per side; limiting the output again will not recover missing dashes. The substantive change is to preserve short painted fragments, associate compatible fragments across gaps, and score boundary geometry separately from the fraction of road that is painted.

This is a research and code review, not a production change or a measured improvement on the new drive. The user's better night/low-light result is an observation to validate separately against the transferred recordings and logs. The earlier [lighting evaluation](LANE_LIGHTING_EVALUATION_2026-09-30.md) rejected broad threshold/filter changes, so those should remain controls rather than be repeated as presumed fixes.

## Why the current implementation disfavors dashed markings

The Swift reference and Kotlin counterpart have the same relevant restrictions:

| Stage | Current behavior | Consequence for dashed paint |
|---|---|---|
| Sampling | At most 24 rows between the horizon region and normalized y=0.94 | Short or distant dashes may intersect few sampled rows. |
| Association | Retires a track when more than four sampled-row steps separate observations | A real blank interval can split one boundary into short rejected fragments. |
| Admission | Requires at least eight observations and usually 0.16 vertical extent | A correctly detected individual dash can never become a raw boundary. |
| Confidence | Multiplies strength/span by observed-row density | Normal blank road between dashes lowers confidence even when all painted pieces agree geometrically. |
| Maturity | Requires at least 0.12 overlapping vertical extent to associate identities, then two fresh observations spanning 0.30 s | Successive short fragments can repeatedly start new tentative identities. |
| Selection | Requires the observed curve to cross an anchor at y=0.78–0.83 | A genuine dash above or below that row is excluded from the preview. |

Code references: [sampling](../iphone/SpeedConsumerApp/RoadBoundaryDetector.swift#L80), [gap termination](../iphone/SpeedConsumerApp/RoadBoundaryDetector.swift#L223), [support and confidence](../iphone/SpeedConsumerApp/RoadBoundaryDetector.swift#L265), [identity association](../iphone/SpeedConsumerApp/RoadBoundaryPresentationGate.swift#L119), [side selection](../iphone/SpeedConsumerApp/RoadBoundaryPresentationGate.swift#L148). Kotlin equivalents are in [RoadBoundaryDetector.kt](../android/app/src/main/java/de/youspeed/android/alpha/RoadBoundaryDetector.kt) and [RoadBoundaryPresentationGate.kt](../android/app/src/main/java/de/youspeed/android/alpha/RoadBoundaryPresentationGate.kt).

The temporal tracker also samples anchors along an interpolated curve, rather than retaining which intervals contain paint. It requires four coherent patch correspondences over at least 0.12 vertical extent; anchors falling in an actual dash gap have little distinctive texture to match. See [RoadBoundaryTemporalTracker.swift](../iphone/SpeedConsumerApp/RoadBoundaryTemporalTracker.swift#L67). These are concrete code-level explanations, not yet a count of how many new-drive failures each causes.

## Controlled synthetic confirmation

Ran 26 deterministic fixtures through frozen, unmodified production `LaneDetection.swift` and `RoadBoundaryDetector.swift`, compiled with `swiftc -O`. Every fixture is 384×216, with the same two converging five-pixel-wide borders and background luma 55. Only the paint/gap mask and documented paint luminance differ. The production top-hat preprocessing runs before detection. There is no temporal tracker, display gate or elapsed-time cancellation in this probe; the normal 250,000-operation cap remains enabled.

The masks explicitly align to the detector's 24 sampled rows. In the table, `6+3` means six painted scan bands followed by three blank bands, repeated across the image. These are controlled image-coordinate patterns, not photorealistic roads or claims about metric dash lengths.

| Paint/gap pattern | Painted scan rows per border | Raw boundaries, bright paint 230 | Confidence per boundary | Interpretation |
|---|---:|---:|---|---|
| Solid | 24 | 2 | 1.000 | Positive control. |
| 6+2 | 18 | 2 | 0.818 | Gaps reduce density/confidence. |
| 6+3 | 18 | 2 | 0.750 | Three blank rows still associate. |
| 6+4 | 16 | 0 | — | Four blank rows put the next observation five steps away; fragments retire before joining. |
| 8+4 | 16 | 0 | — | Eight-row fragments still fail the 0.16 span condition. |
| 10+4 | 20 | 4 | 0.538 | Two fragments of each physical border become separate boundaries. |
| 1+2 | 8 | 2 | 0.364 | Minimum observation count can pass when spread over enough image height. |
| 1+3 | 6 | 0 | — | Insufficient observations. |

A single near-field fragment of seven, eight or nine rows produces no boundary; ten rows produces two boundaries with span 0.1721 each. At the lower paint luminance 105, the solid control still returns two boundaries with confidence 0.514–0.517. The `1+2` pattern now returns none, consistent with the confidence-density penalty; `2+3` returns two with confidence 0.233–0.236, below the preview selector's separate 0.25 threshold. There were **zero operation-budget failures in all 26 fixtures**. This establishes structural dashed-line sensitivity in the current detector, without establishing live recall or suggesting threshold relaxation as the fix.

Reproducible evidence: [probe directory](../inspector/logs/2026-10-01-drive-review/dash-probe/), including `Probe.swift`, `run.py`, frozen sources and SHA-256 hashes in `metadata.json`, all raw fixture bytes, complete point/confidence/support results in `results.json`, and `summary.txt`. The temporary Swift module cache is removed after compilation. No production source changed.

## What primary research supports

- [Aly, *Real time Detection of Lane Markers in Urban Streets*](https://arxiv.org/pdf/1411.7113), sections II-B–E, retains nonbinary stripe responses, obtains coarse line hypotheses, and fits/refines Bézier curves robustly. This supports grouping separated evidence before fitting a boundary. Its flat-road/camera assumptions and near-parallel preference limit direct transfer to crests and tight curves; its published desktop throughput is not a phone benchmark.
- [Borkar, Hayes and Smith, *A Novel Lane Detection System With Efficient Ground Truth Generation*](https://people-ece.vse.gmu.edu/~hayes/papers/IEEE_Trans_ITS.pdf), DOI [10.1109/TITS.2011.2173196](https://doi.org/10.1109/TITS.2011.2173196), uses temporal image averaging specifically to connect dashed markers, then IPM, RANSAC and Kalman tracking. The primary paper's indexed preprocessing excerpt was accessible; direct PDF retrieval failed. Averaging unaligned frames is unsuitable as our default: turning and pitching can merge different geometry. A bounded history of motion-aligned observations is the safer experiment.
- [Lim et al., *River Flow Lane Detection and Kalman Filtering-Based B-Spline Lane Tracking*](https://onlinelibrary.wiley.com/doi/10.1155/2012/465819), section 3, predicts spline control points and restricts subsequent edge search around the model; the experiments include dashed highway markings. This supports prediction-guided search, but does not establish that prediction alone is fresh paint evidence or prove our mobile performance.
- [Ozgunalp et al., *Robust Lane Marking Detection Algorithm Using Drivable Area Segmentation and Extended SLT*](https://arxiv.org/html/1911.09054v1), sections II-D–G, qualifies opposite stripe borders, finds left/right hypotheses, then robustly fits curves within ROIs. It explicitly discusses arrows, high curvature and saturation as difficulties. Its stereo road mask is unavailable in this monocular app; only the bounded feature/ROI ideas transfer directly.
- [Yu et al., *Detecting Lane and Road Markings at A Distance with Perspective Transformer Layers*](https://arxiv.org/abs/2003.08550), warns that IPM interpolation can damage distant markings. Prefer projecting sparse observed features or sampling narrow original-image bands first; a large resampled bird's-eye bitmap is not necessary to test this idea.

No paper above establishes a measured gain for YouSpeed. The proposed combination is an engineering inference from those methods and the current rejection rules.

## How the two zones should work

**Calibration mismatch found in the current device review:** the saved compatible profile has left bottom `(0, 0.785)`, left top `(0.425, 0.535)`, right bottom `(0.63, 1)`, and right top `(0.48, 0.535)`. The current selector therefore places its center at approximately **x=0.284 at y=0.78**, far left of image center. Manual inspection of the [calibration overlay at 121.3, 353.8 and 440.9 seconds](../inspector/logs/2026-10-01-drive-review/calibration-contact.jpg) shows the saved left guide along the neighboring lane/guardrail and the right guide inside the ego lane. Its calculated center lies at or left of the true left dashed border instead of inside the ego lane. A dash near x=0.30 and an edge near x=0.65 at the anchor row would both be assigned to the right side. The impact on actual detection/selection still needs an ablation; the visual mismatch itself is clear. Compatibility of crop/orientation does not prove correct road geometry. Audit what the calibration handles mean and correct/validate the guides before restricting detection to their zones. Detect persistent mismatch and widen/reacquire rather than reinforcing a bad prior.

1. Use compatible calibration and the recent accepted left/right curves to define row-dependent search bands. Give both sides candidate capacity so many strong candidates on one side cannot crowd the other out of the current global top-12 row limit. Reuse one luma image and one preprocessing pass.
2. Treat calibration as a soft prior. Start broad, narrow after consistent observations, and widen or reacquire after loss. Keep a bounded broad-search fallback. A fixed vertical image split fails when both distant boundaries bend into the same image half; a narrow static trapezoid can miss lane changes, camera motion and road crests.
3. Retain several internal hypotheses briefly at forks/merges, while displaying at most one accepted border per side. Zero or one visible border remains valid. The strongest stripe is not necessarily the ego boundary: rank image support together with side, direction, width consistency and temporal association.
4. Preserve fragment endpoints, widths, tangents and actual supported intervals. Associate disconnected fragments with capped robust fitting or a small graph/beam search. Accept a gap only when the fragments agree; reject lateral jumps, arrows, zebra crossings and inconsistent widths. Do not hard-code one national dash length or paint-to-gap ratio.
5. Track the boundary model and its uncertainty separately from paint occupancy. Use speed/calibration/heading to predict where a known fragment should move; match texture on observed paint or endpoints, not evenly spaced points in blank gaps. Keep age, uncertainty and reacquisition limits explicit. A missing dash is not automatically a disappeared lane, but a model-only prediction must not be logged or drawn as fresh detected paint.

For an initial preview experiment, render the currently supported pieces of the one selected boundary, preserving gaps. If a continuous estimated border is later wanted, distinguish its inferred intervals visually and in diagnostics from observed paint and the calibration reference. This avoids silently changing what the overlay claims to have detected.

## Night behavior and validation order

Dry road markings can return headlight illumination strongly through retroreflective beads; wet conditions can substantially weaken that effect. [FHWA's field evaluation](https://www.fhwa.dot.gov/hfl/partnerships/all_weather_pavement/hif13004/chap01.cfm) describes this mechanism. It plausibly explains higher paint/background contrast at night for the existing bright-ridge detector, but it does not prove the cause of this drive's improvement. Check wet glare, oncoming headlights, road studs and guardrails as negative controls.

The newly transferred iPhone clip is daylight footage. It can test dashed-line behavior, but cannot confirm the user's reported night improvement; a night recording remains needed for that comparison.

1. Add offline rejection counters and label consecutive new-drive clips: solid/dashed, day/night, straight/bend, junction/unmarked. Measure candidate response, fragment loss, maturity loss and selector loss separately.
2. Compare baseline, balanced soft ROIs alone, fragment grouping alone, and their combination. Then evaluate motion-aware fragment tracking. Keep brightness thresholds unchanged initially so grouping gains are attributable.
3. Score boundary accuracy separately from painted-pixel recall; otherwise legitimate gaps contaminate the metric. Report unsupported visible duration, identity switches, reacquisition delay, side changes and jitter in comparable calibrated coordinates. Use untouched contiguous clips for acceptance.
4. Measure p95 preparation latency, budget misses, peak memory, queue depth and sustained thermal behavior on both devices. Two bands should share buffers; two full-frame pipelines would defeat their resource benefit. Search zones are not an established fix for the reported Android crash; its termination evidence must determine that cause.

Keep these experiments preview-only and preserve Swift/Kotlin parity. Road-graph lane counts remain optional weak context, not evidence of a visible line or permission to force a missing side. No speed-limit reference policy, deployment or app behavior was changed by this review.
