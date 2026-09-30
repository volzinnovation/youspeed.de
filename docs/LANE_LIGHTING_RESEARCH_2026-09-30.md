# Lane lighting research — 2026-09-30

Follow-up: [the recorded-video and app-log evaluation](LANE_LIGHTING_EVALUATION_2026-09-30.md) tested the eight A/B/input ablations. No candidate qualified for production; the results and remaining validation gaps supersede the hypotheses below.

## Recommendation

The next useful experiment is **local grayscale contrast normalization with
measured stripe-border geometry**, followed by a separate grouping experiment.
Another brightness boost alone is not justified by the recordings. A small
segmentation model is worth keeping as an independent comparison, after testing
the cheaper changes. These are research hypotheses, not demonstrated gains or
changes included in build 10021.

## What normalized grayscale means

The current Android and iPhone lane paths already sample the camera's Y/luma
plane into an aspect-preserving image no larger than 384×216. The reviewed live
recording used 288×216. `RoadPathLaneFilter` then applies horizontal top-hat5
enhancement. The lane detector does not operate on an RGB tensor; TSR has its
own separate image/model input.

There are materially different meanings of normalization:

| Operation | Expected effect | Relevance here |
|---|---|---|
| Convert RGB to grayscale / use camera Y | Discard chroma and retain brightness | Already done for lanes; shadows remain in brightness. |
| Divide 0–255 by 255, or map to −1…1 | Change numerical units | With matching threshold scaling, the decisions are unchanged. |
| Normalize an entire frame by range, mean/variance or a response percentile | Adapt to some global exposure changes | One transform cannot independently equalize adjacent sunlit and shaded road patches. |
| Normalize against local background brightness/variation | Compare paint with nearby asphalt | Worth testing, with signal floors and geometric qualification to avoid amplifying texture. |

The enhancement currently computes `gray + 1.5 × (gray − opening5x1)`, clipped
to 255. It strengthens narrow bright structures but retains absolute brightness
dependence. The detector still requires a center intensity of at least 95 and
bilateral contrast of at least 26. A shadowed stripe can retain useful relative
contrast yet fail the first threshold. Removing that threshold without stronger
qualification has already caused regressions.

The user's remembered lecture may be associated with Sebastian Thrun/Udacity;
the exact source has not been identified. The official
[Udacity advanced-lane project](https://github.com/udacity/CarND-Advanced-Lane-Lines)
describes camera calibration, color transforms/gradients, perspective mapping and
lane fitting. It does not establish that normalized grayscale alone solves
shadow robustness. No exact lecture or quotation is attributed here.

## Evidence that constrains new work

The [earlier filter experiments](LANE_FILTER_EXPERIMENTS_2026-09-29.md) already
tested CLAHE, paired Sobel/Scharr edges, alternative sampling and dense quadratic
fits. CLAHE produced 12.4% held-out paint coverage versus raw 13.1% and top-hat5
25.7% on the small partial-label corpus. A Scharr paired-edge binary adapter
reached 63.7% but introduced 69 false-paint pixels in labelled negative regions.
Those trials do not justify repeating the same filters as new improvements.

The [longer shadow review](LANE_SHADOW_REVIEW_2026-09-30.md) covers 7,663 frames
from 63 minutes 51 seconds of encoded video. Dim-response admission reduced
visible labelled coverage from 796/2,501 to 721/2,501 pixels. Its extra candidates
altered row suppression/association and sometimes created an unsupported hook
above a correct centerline. A conservative recovery variant restored those
examples but demonstrated no gain. A previous brightness-normalized temporal
matcher also carried an incorrect curve. More persistence is not an established
solution.

## Experiment A: qualify dim stripes before admitting them

Use the two observed paint borders, rather than only a bright center. Require
opposite gradient polarity, compatible border tangents and a plausible measured
width that changes smoothly across supported rows. Apply qualification before
recovered dim samples enter suppression and track association. Keep bright and
recovered evidence separately diagnosable.

This borrows the border-orientation idea from
[extended symmetrical local thresholding, section II-D](https://arxiv.org/html/1911.09054v1#S2.SS4).
That paper adds border-direction agreement to the dark–light–dark test. Its full
system also uses stereo road segmentation and bird's-eye projection; those
components and reported accuracy do not transfer to our monocular app.

Our implementation hypothesis is a small gradient/width check around sampled
candidates, using image-space scale bands or same-frame observed paint widths.
The new information is joint border geometry; the earlier binary edge adapter
did not supply it. Avoid assuming a metric stripe width from the current
approximate mount calibration. One missing/worn border should allow abstention.
Arrows, guardrails and parallel shadow strips remain explicit negative controls.

## Experiment B: local normalization of qualified paint contrast

Compare the center with separate left/right asphalt windows, normalized by
bounded local variation. Preserve a minimum raw contrast/noise floor, reject
clipped or unsupported regions, and retain the original image for verification.
A conceptual score is the smaller of the two center-to-shoulder residuals divided
by a guarded local standard deviation. This is a proposed score, not a calibrated
probability.

[Bradley and Roth's adaptive-threshold paper](https://people.scs.carleton.ca/~roth/iit-publications-iti/docs/gerh-50002.pdf)
provides the local-statistics/integral-image foundation. It is not a lane paper
and does not validate our proposed bilateral variance-normalized score. Row
prefix sums and squared sums could reuse the current sampled-row organization
without another RGB conversion or full-frame histogram pass.

Test A alone, B alone, and A+B against the exact current baseline. Compare raw
luma and existing top-hat input separately before stacking enhancements. A
noise floor matters because near-uniform dark patches otherwise obtain large
normalized scores. A shadow crossing one shoulder can also corrupt the local
reference. This differs from the rejected inverse-center-brightness gain, but
its value must still be measured.

## Experiment C: improve grouping, keeping measured strengths

The previous dense-response audit found substantially more paint response than
survived into final boundaries. Once observations have border orientation and
width, compare bounded association using these features against today's greedy
row linking. Preserve continuous response strength, observed fragments and gaps.

[Aly's original lane-marker method](https://arxiv.org/pdf/1411.7113) combines
width-selective separable filtering, a high response quantile that retains
nonbinary strengths, robust fitting and observed-point refinement. Its
perspective mapping assumes a flat road and camera parameters. We can test
image-space response/grouping ideas without asserting those assumptions hold.
This is distinct from the accepted display Bézier helper: display smoothing
does not change detection evidence.

At 24 rows and at most 12 candidates per row, a capped association experiment
can retain a fixed work budget. Penalizing unsupported tangent/width changes
might prevent the observed upper hooks, but could also reject genuine tight
curves. Do not force one ego lane, fill dashed gaps or extend a curve beyond
current support to improve appearance.

## Learned and temporal comparison methods

**TwinLiteNet+ Small** is the strongest first learned comparison identified in
this review. The authors provide pretrained models in an MIT-licensed
[official repository](https://github.com/chequanghuy/TwinLiteNetPlus). It predicts
lane-marking and drivable-area masks rather than a fixed number of lane curves.
My inference is that this is a closer representation for variable visible paint
and forks, although pretrained category semantics still need inspection.

The Small variant uses 640×384 input, approximately 0.12M parameters and 1.40
GFLOPs; its reported BDD100K lane IoU is 29.3%. The
[paper](https://arxiv.org/html/2403.16958v2) reports FP16 TensorRT inference of
12.86 ms on Jetson Xavier and 33.82 ms on TX2. These are not Android/iPhone or
complete-pipeline timings. Nano is a lower-cost, lower-accuracy fallback.
RGB preprocessing, conversion/export compatibility, upsampling and competition
with TSR for compute must be measured. No model was downloaded or run here.

[UFLDv2](https://github.com/cfzd/Ultra-Fast-Lane-Detection-v2) is a useful second
model comparison. Its official CULane ResNet-18 configuration has 1600×320 input
and four lane slots; CurveLanes uses 1600×800 and ten slots. Those structured
outputs and contextual completion are less directly equivalent to currently
observed paint. Desktop throughput and lane-instance F1 cannot be used as phone
latency or compared directly with segmentation IoU.

For temporal association, OpenCV's
[RLOF parameters](https://docs.opencv.org/4.13.0/d4/d91/classcv_1_1optflow_1_1RLOFOpticalFlowParameter.html)
include multiplicative/additive illumination compensation. A bounded sparse
correspondence experiment with forward/backward checks could complement fresh
detection. It cannot establish paint semantics, and the existing low analysis
cadence can make displacement too large. The earlier incorrect carried curve
must remain a regression control; do not relax evidence expiry.

## Approaches to defer

CLAHE is a control, not the leading new experiment: it already underperformed
locally. Its tile-local contrast limiting reduces but does not eliminate noise
amplification, as described in the
[OpenCV documentation](https://docs.opencv.org/4.13.0/d5/daf/tutorial_py_histogram_equalization.html).
Retinex or global histogram normalization alone likewise supplies no paint
semantics. Lost detail in clipped highlights cannot be recovered by rescaling.

Replacing luma with a shadow-invariant RGB chromaticity image is also a poor
first step. [Finlayson et al.](https://www2.cs.sfu.ca/~mark/ftp/Pami06/asprinted.pdf)
explicitly discuss the loss of distinctions between surfaces differing only in
intensity. White paint and gray asphalt can depend on exactly that distinction.
If color-based shadow information is tested later, retain luminance as a
separate source of evidence.

## Acceptance and implementation order

1. Implement A and B only in the offline replay path first, as separately
   switchable, bounded experiments. Freeze parameters before evaluation. Proceed
   to C if verified paint candidates are still being lost during grouping.
2. Use the current 22 annotations as development data. Add independently
   labelled contiguous sequences with bright/shadow transitions, sharp bends,
   worn/dashed paint, intersections and unmarked roads. Freeze an untouched
   drive-level holdout, preferably from a separate recording, before predictions.
3. Score raw and displayed paint separately. Add false visible duration on
   annotated non-paint, lost bright support, false hooks, reacquisition delay,
   flicker and identity changes. Candidate/boundary count is not accuracy. Never
   treat all unlabelled pixels as negative ground truth.
4. A proposed promotion target is at least five percentage points better
   displayed-paint coverage in shadow sequences, no material bright-scene loss,
   and no increased sustained false boundaries. This is an engineering target,
   not an existing product policy or statistical proof; report sequence counts
   and uncertainty rather than optimizing against a few frames.
5. Measure full preparation time and deadline misses on the Moto and iPhone,
   including cold starts and sustained thermal load. The existing **50 ms lane
   preparation budget** covers the whole path. Replace work where possible;
   don't add a model's published inference time to a nearly exhausted budget.
   Lane failure/absence must continue to permit TSR with reduced applicability.

The live camera and encoded videos have different aspect ratios. Offline
16:9 success does not validate the 4:3 live mapping or its calibration. Final
native parity and camera tests must use the actual live geometry. No speed-limit
reference policy, model bundle or production detector was changed by this review.
