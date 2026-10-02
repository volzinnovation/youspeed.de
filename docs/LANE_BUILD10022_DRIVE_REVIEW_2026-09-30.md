# Build 10022 drive: lane instability and next improvements

The new drive confirms that reducing preparation cost did not solve lane stability.
The main problems are frequent loss/replacement of visible tracks, repeated switching
to fixed calibration reference lines, and limited motion correspondence between
roughly half-second updates. **Implement persistent ego-lane boundary selection and
calibrated motion prediction before making the detector more permissive.** Road-graph
context is useful as a soft prior, but lane counts are not exposed by the current
mobile lookup result.

This is an analysis and recommendation, not a newly installed implementation.
Production remains commit `a0df46d`, build **10022**. That build was successfully
installed and launched before this drive; the attached device now independently
confirms versionCode 10022. The original video and app data were preserved.

## Transferred evidence and replay

Private evidence is in `inspector/logs/2026-09-30-build10022-drive/`, excluded from Git.

- [Original recording](../inspector/logs/2026-09-30-build10022-drive/drive.mp4):
  **29 min 00.437 s**, 1280×720, **1,802,456,364 bytes**. Its device and local SHA-256
  match: `7b535a3ea3fde0eea8add648b9246e36177c7e88e5335ee45ac42eb64c1c3457`.
- Copied runtime diagnostics, GPS CSV, road-match log, preferences/calibration,
  active bundle identity, and the installed database's first 256 KiB for schema inspection.
- [60-second comparison video](../inspector/logs/2026-09-30-build10022-drive/cadence-review.mp4):
  the same production pipeline at 2 Hz and 10 Hz, with green visible boundaries and
  red other candidates. These are diagnostic polylines, **not a recording of the app UI**.
  Its three sections correspond to original-video 420–435 s, 875–905 s and 1120–1135 s.
- [Contact sheet](../inspector/logs/2026-09-30-build10022-drive/replay-contact.jpg),
  [live stability audit](../inspector/logs/2026-09-30-build10022-drive/stability.json),
  [cadence comparison](../inspector/logs/2026-09-30-build10022-drive/replay-matched-2fps/comparison.json),
  and [motion probe](../inspector/logs/2026-09-30-build10022-drive/motion-probe.json).

The full recording was decoded at 0.5-second intervals and all **3,481** samples
replayed through frozen native Swift production sources. The selected intervals
were additionally decoded/replayed at 0.1-second intervals: **600** samples. A second
run used exactly every fifth sample of each sequence, **120 identical input frames**,
with the same compiled binary. Source/input/output hashes and per-frame results
are preserved in the replay directories. These are engineering replays, not new
labelled accuracy benchmarks.

Live analysis was 1600×1200, rotated 180°, sampled at 288×216. The encoded video is
1280×720, sampled at 384×216. A verified crop/intrinsics transform between the two
streams is unavailable, so the video replay deliberately supplies no transplanted
4:3 calibration or GPS. Live findings come from the live logs; replay findings come
from encoded pixels. They must not be numerically conflated.

Recording callbacks place start/stop at **14:39:45.275–15:08:46.355 UTC**. Progress
callbacks imply UTC minus video PTS of 1790779185.506 s at the median, with a **0.623 s
spread**. This supports finding approximate scenes, not exact frame-to-log overlay
alignment. There is no phone-screen recording establishing exact rendered geometry.

## What failed in the live run

The recording window contains **2,920 unique logged path records**, including
**2,909 with preparation/deadline measurements** and **11 invalidation records**.
Runtime parsing found no malformed rows or duplicated frame IDs.

| Observation | Result | Interpretation |
|---|---:|---|
| Geometry/preparation failures | **124/2,909 = 4.26%** | These remove the current overlay and reset continuity |
| Moving subset, speed >1 m/s | **105/2,445 = 4.29%** | Failures also occur during actual travel |
| Preparation p50 / p95 | **18.25 / 46.14 ms** | The 50 ms cap still has little tail headroom |
| Sampling p50 / p95 | 3.40 / 16.30 ms | Live contention remains substantial |
| Filtering p50 / p95 | 2.74 / 10.52 ms | The optimized filter still has a long live tail |
| Geometry p50 / p95 | 9.94 / 23.17 ms | Tracking/detection is now the largest median component |
| Logged exposure interval p50 / p95 | **0.500 / 1.033 s** | Low cadence and occasional long gaps |
| Intervals longer than 0.75 s | **177/2,919** | Longer than the display freshness window |
| Frames with no published visible boundaries | **1,775/2,920 = 60.8%** | Availability, not accuracy or time-weighted screen occupancy |
| Unique visible track IDs | **706** | **411 (58.2%)** appear in only one logged exposure |
| Visible boundary observations | 1,534 | Only 444 fused and 6 carried/tracked; 1,084 fresh |
| Explicit temporal scope/geometry resets | **61** | The camera geometry ID remained constant throughout this recording |
| Temporal exposure-gap resets | **140** | Reacquisition frequently starts over |
| Direct observed ↔ reference UI transitions | **758** | About **26 per recording minute** |

The old 3.39% figure pooled different historical conditions. This run is not a
paired before/after comparison, so 4.26% does **not** establish a regression from
the optimization. Its output-preserving computation saving remains supported by
the prior paired benchmark; full-app deadline reliability is still unresolved.
All 2,920 records report the separate overall `deadlineExceeded=false`; this does
not cancel the 124 geometry-budget failures. Different deadlines have different
meanings. Component p95 values must not be summed.

### 1. Reference-line switching visibly changes the geometry

There are 1,323 `lane_overlay_presentation` events: 394 observed, 905 calibration
reference, and 24 hidden. These are event counts, not display-time percentages.
The reference events cite `no_confirmed_boundaries` 573 times and `stale_context`
332 times. The implementation immediately substitutes the saved straight reference
lines whenever no mature current boundary is available. On a bend these lines
have different positions/shapes from the detected curves, so their rapid alternation
is a direct mechanism for apparent jumping.

`stale_context` is a broad UI reason: it includes a missing or expired overlay and
geometry/calibration incompatibility. It must not be interpreted as 332 proven map
context errors. The source geometry itself stayed constant in the recorded window.

### 2. Correspondence cannot reliably follow the material points

`RoadBoundaryTemporalTracker` searches up to ±12 pixels horizontally but only
**±2 pixels vertically**, with small raw-luma patches. It then requires multiple
consistent, bidirectionally matched anchors. Only **559/6,311 (8.86%)** raw boundary
observations were fused, and only 12 were carried without a fresh detection.
Fresh detections largely replace rather than update stable tracks.

The GPS hint only expands the horizontal search radius above a heading-rate
threshold. It does **not** use speed × elapsed time to warp the curve, and does
not use the calibration for forward projection. It was active on 413 records;
31 of those report course accuracy worse than 20°, with a worst case of 72.4°.
Such uncertain GNSS heading should not become an authoritative motion transform.

Illustration, not a measured correspondence: using the logged approximate 1.6 m
camera height and normalized fy≈0.979, a road point initially 15 m ahead moves
about **11 vertical analysis pixels** after half a second at the drive's median
speed of 9.69 m/s, under a level, flat-road model. That exceeds the search window.
This is motion of paint texture, not necessarily motion of the continuous lane
curve at a fixed image row.

An independent pyramidal optical-flow probe used the same previous paint anchors
for 0.1 s and 0.5 s intervals in the three selected sequences. It retained 2,261/3,669
anchors at 0.1 s versus 907/3,669 at 0.5 s after texture, patch-error and forward/back
checks. At 0.5 s, **393/907 retained flows (43.3%)** exceeded ±2 pixels vertically.
This supports investigating the search model. Flow is not labelled ground truth,
and the accepted subsets differ between cadences.

### 3. Maturity is not persistent ego-lane selection

The presentation gate associates shapes and waits for repeat observations, but
does not maintain an explicit left/right ego-lane pair. The detector/tracker can
retain up to six boundaries, and the display shows all mature ones. This run had
44 logged exposures with three visible boundaries and four with four.

Even for retained IDs, the maximum displacement across five shared image rows was
over five analysis pixels on **355/828** comparable adjacent steps; p95 was **11.5 px**.
This includes legitimate turning and perspective changes, so it is **not an error
rate**. It demonstrates why identity alone is not sufficient for smooth display.
Bézier fitting smooths each individual curve spatially; it does not supply temporal
motion prediction.

### 4. Camera continuity still depends on TSR context

The lane preparation hook runs on frames admitted by the TSR worker, immediately
before inference. Sampled inference time is 369 ms median and 509 ms p95. Publishing
before inference helps latency—the median capture-to-publication was 106 ms—but
the next lane update still depends on admission of another TSR frame.

The orchestrator also calls `pathInvalidated` on scope changes, and that increments
the overlay epoch used by the lane tracker. The 61 scope/geometry resets despite
one unchanged camera geometry ID are consistent with this coupling; logs do not
identify every reset trigger. Camera lane identity should survive routine map-way
and sign-context changes, while sign-association invalidation remains intact.

## What the video replay adds

The full 2 Hz replay completed without host geometry or overall deadline failures.
It had visible boundaries on 2,079/3,481 samples, but visual review shows unstable
selection around bends, dashed markings, roadside vegetation and a painted junction
area. For example:

- **424.5–426 s:** a right-hand curve; candidate count and visible identities change
  while separate road boundaries remain visible in the original imagery.
- **879.5–881 s:** a nearly straight section with dashed center paint; the published
  set goes from one line to none, then three, then none.
- **897–898.5 s:** a left-hand bend; roadside candidates compete with center/edge
  paint and published identities change rapidly.
- **1125–1126.5 s:** a junction/painted taper; multiple real markings make a global
  “two highest confidence lines” rule particularly ambiguous.

These are encoded-video detections; they are not proof that the live calibrated
app rendered the identical curves. No accuracy annotations were added after
viewing predictions, and no precision/recall improvement is claimed.

| Same production pipeline, selected 60 seconds | 2 Hz | 10 Hz |
|---|---:|---:|
| Input samples | 120 | 600 |
| Fused raw boundaries / all raw boundaries | 43/480 (**9.0%**) | 988/2,467 (**40.0%**) |
| Tracked-only raw boundaries | 0 | 88 |
| Visible output at the **same 120 timestamps** | **92/120** | **83/120** |
| Visible identity-set transitions at those timestamps | 80 | 77 |
| Geometry/overall budget failures on host | 0 / 0 | 0 / 0 |

Higher cadence clearly helps patch correspondence here, but does **not** establish
better accuracy or availability. The current gate can drop a missing identity
after one missed exposure, making its behavior cadence-dependent. Raising the
frame rate alone is therefore not an accepted fix. Its CPU/thermal cost also needs
device measurement.

## Recommended implementation order

1. **Separate lane continuity from TSR admission and reference fallback.** Give
   the small luma tracker its own bounded, latest-frame worker and camera/calibration
   epoch. Start with a measured 10 Hz target; run expensive detection less often if
   needed. Keep the latest immutable lane result available to TSR without changing
   its speed-reference policy. Add explicit invalidation reasons. Replace the rapid
   detected↔reference substitution with time-based hysteresis and a distinct reference
   state; do not make an old observed curve look freshly detected. Preserve/reset
   identity by elapsed time and uncertainty, not by a one-missed-frame count.

2. **Predict in calibrated road coordinates, then correct with image evidence.**
   Unproject supported lower-image lane points onto a local road plane; integrate
   speed over the exposure interval and apply measured yaw/pitch/roll change; project
   them into the current camera. Use that prediction to center a bounded 2D patch
   search and associate fresh segments. A persistent curve state can describe lateral
   offset, heading, curvature and lane width with uncertainty. Weight corrections by
   observed support and motion-compensated residual. Smooth this state, then render
   a Bézier curve; blindly averaging old/new screen points will lag turns.
   Plane-induced image motion is supported by the standard homography model described
   in [OpenCV's camera-motion tutorial](https://docs.opencv.org/4.13.0/d9/dab/tutorial_homography.html).

   The current metric calibration is explicitly an approximate bus mount with
   zero pitch/roll/yaw and a level-camera assumption; the visual profile's horizon
   is y=0.525. They are not yet a verified unified metric calibration. Log effective
   intrinsics, crop/rotation transforms, exposure-time attitude and uncertainties.
   Use gyro/visual rotation for short intervals where GNSS heading is weak. On bumps,
   crests or calibration mismatch, weaken/reset the plane prediction rather than
   treating it as measured paint. Prediction-only drawing needs an age/uncertainty
   bound and visibly decreasing confidence.

3. **Maintain the ego-lane pair, usually at most one boundary on each side.**
   Rank candidate *pairs* by containment of the projected vehicle path, plausible
   width/curvature, independent paint/edge support, temporal residual and sustained
   identity. Add a switching penalty/hysteresis so a marginal new candidate cannot
   replace an established side immediately. Allow zero or one visible side when
   evidence is weak. Keep other candidates internally for turns, splits and lane
   changes. A high heuristic confidence is not a calibrated probability of correctness.
   Do not simply take the two largest confidence scores: both can lie on the same
   side or bound the oncoming lane.

4. **Add road-graph priors after the visual pair tracker is measurable.**
   The installed Baden-Württemberg bundle is version 2026-07-04. Its inspected
   `ways` schema has road class/name/ref/speed/heading/bounds but no lane-count
   columns; `SpeedLookupResult` also exposes no lane count. Extend the shared bundle
   and both mobile clients with optional `lanes`, directional counts, `oneway`,
   turn-lane/junction and width metadata, preserving unknown values. Existing road
   geometry and matching stability can supply a weaker heading/topology prior now.

   `lanes` normally counts motor-vehicle lanes across the road; directional counts
   refer to the OSM way's orientation, not automatically the vehicle's direction.
   Two total lanes on a two-way road commonly mean one each way, not two in our
   direction. See [OSM lanes](https://wiki.openstreetmap.org/wiki/Key:lanes) and
   [directional lane counts](https://wiki.openstreetmap.org/wiki/Key:lanes:forward).
   Lane count also does not equal the number of painted boundaries visible ahead.
   Never create a line solely because the map expects one. Reduce the prior near
   junctions, uncertain matches, temporary markings and missing/stale tags.

   This drive had 756 stable results among 860 logged matched fixes, across 56 ways.
   Logged lookup query time was 1.68 s median / 4.23 s p95: use timestamped cached
   graph priors asynchronously, never put map lookup on the lane-frame path. The
   lane-session out-of-order-location counter rose by 1,484 during recording; the
   rejection protects history, but delivery sources should be diagnosed before
   GNSS is trusted as a high-rate predictor.

## Acceptance plan

Evaluate these as separate ablations: reference hysteresis; independent cadence;
motion-predicted association; persistent ego-pair selection; then map priors.
Keep Android/Swift semantics and fixtures aligned. Do not relax detection or
speed-reference rules to make lines stay on screen.

Use this drive as development evidence, then a new untouched drive for acceptance.
Annotate short consecutive sequences from original imagery: straight dashed lanes,
sharp curves, intersections/tapers, absent paint, shadows, stops and bumps. Measure
motion-compensated boundary residual, side/identity switches per minute, false
visible boundaries, supported visibility, turn lag, reacquisition delay and stale
prediction duration. Compare only common exposures and report missing output.
Record raw luma, exact exposure timestamps, video mapping, accepted/rejected motion
innovations, pair scores and reset causes for a small opt-in test window.

Suggested engineering targets to agree before the next trial: halve measured
side/identity switches and motion-compensated p95 jitter versus build 10022, retain
or improve labelled paint coverage without increasing false lines, and bring live
preparation failures below 1% under concurrent TSR/recording. Treat these as proposed
targets, not achieved results. Include stationary/turning cold starts and a thermal
soak; verify equivalent behavior on an attached iPhone when available.

## Reproduction

`scripts/lanes/audit_drive_stability.py` computes the recording-bounded log audit.
`ExtractRecordedLaneFrames.swift` now accepts an optional start/end interval.
`replay_recorded_pipeline.py` freezes and replays production sources;
`compare_replay_cadence.py` reuses its compiled binary on identical sparse inputs.
`probe_lane_motion.py` produces the exploratory image-flow comparison, and
`render_cadence_review.py` generates the H.264 review video.

Validation: all nine frozen Swift replay source hashes match deployed commit
`a0df46d`; the review video decodes all 600 frames at 10 fps; three new analysis
regressions and four existing evaluation regressions pass. `verification.json`
records these checks. The focused extraction ranges preserve original PTS and
the cadence comparison checks byte-identical common input hashes.

All media and location-bearing artifacts remain local in the ignored evidence
directory. No application source, bundle policy or device setting was changed
during this analysis.

## Implementation follow-up

The first bounded implementation and paired ablations are documented in
[Lane stability implementation — 2026-09-30](LANE_STABILITY_IMPLEMENTATION_2026-09-30.md).
It adds the independent preview, motion-guided image search and persistent side
selection on both platforms. Road-graph priors remain behind the visual acceptance
gate. Replay continuity improved in some measures; visible transitions remain an
unresolved acceptance target.
