# Visual TSR: lane evidence and causal trajectory experiment

This branch now has a native CPU path-evidence pipeline on Android and iPhone,
with Android device qualification as the first target. It combines observed
boundary polylines, past GNSS motion and physical sign tracks. Its output is an
experimental `current_path / other_path / unknown` **sidecar**, not a new speed
source. It cannot grant or remove sign authority, synthesize sign absence, or
change passage handling. The protected speed-reference policy is unchanged.
The existing visual TSR output remains the state machine's input.

This is an implemented research comparison, not a demonstrated general solution.
The [NVIDIA description](https://blogs.nvidia.com/blog/drive-labs-ai-based-live-perception/)
separates sign detection/classification from path perception and sign-to-path
association. This implementation follows that separation using bounded CPU
geometry instead of assuming NVIDIA's models or hardware are available on a phone.

## Implemented stages

1. After a live TSR frame is recognized, read its still-owned luminance plane.
   Preserve its upright aspect ratio within **384 × 216**; no second full-resolution
   model, GPU inference, camera session, retained image or network request is added.
2. `RoadBoundaryDetector` samples 24 rows using prefix sums. It retains bounded
   piecewise curves, paint/edge cue provenance and confidence, up to six boundaries
   and two unassigned corridor hypotheses. Edges alone do not establish a corridor.
   It does not force every scene into a straight left/right pair. A callback checks
   a **50 ms** geometry deadline inside loops; a deterministic operation cap also
   limits work. Aborted geometry has no partial result.
3. `RoadPathSession` retains bounded past location fixes and per-physical-track
   image observations. Camera exposure timestamps are explicitly mapped to UTC;
   an unspecified Android camera clock cannot grant geometric evidence. Candidate
   callback UTC is logged separately. Motion alignment uses only a preceding fix,
   at most 350 ms of constant-course prediction, and grows uncertainty. It never
   consumes future travel or map/navigation intention.
4. `RoadPathEvidence` projects observed boundary pixels onto the assumed local
   road plane. Independently supported corridors remain unassigned unless recent
   movement uniquely supports the current path. Touching/overlapping corridors
   cannot turn another lane of the same carriageway into an unrelated road.
5. At least three observations, sufficient physical baseline and parallax, positive
   depth, bounded residual and sufficiently small uncertainty are required to
   triangulate a sign. Full camera rays are used: **the elevated sign centre is
   never projected onto the ground**. Left-side and overhead signs are included.
   Competing roadside corridors, missing calibration, stale/poor motion, stopped
   or ambiguous observations yield unknown. Confidence values are heuristic,
   not calibrated probabilities.

The total added path has a **200 ms** cooperative deadline, including preparation,
geometry, association and diagnostic serialization. Late outputs clear the live
geometry and associations. An operating system can deschedule a thread beyond a
cooperative deadline; the benchmark reports such misses instead of claiming a
hard real-time guarantee. The path runs on the existing inference worker and adds
no waiting for a second geometry frame. Its cold acquisition interval and sign
recognition latency are separate from its CPU overhead.

Both native cores use the same bounded arithmetic and mirrored tests. The live
lane overlay reuses this result when TSR is active; it does not run the older lane
estimator a second time. With TSR disabled, the existing optional lane-preview
experiment remains available. The **Show detected lanes** setting controls only
the drawing; path evidence collection follows TSR independently of that setting.

## Test-bus calibration

The owner supplied these installation values on 29 September 2026:

| Parameter | Value / provenance |
| --- | --- |
| Camera lateral position | −0.08 m; vehicle-right-positive |
| Height above road | Approximately 1.60 m |
| Forward yaw | 0°, reported straight ahead using the alignment aid |
| Pitch / roll | Level-camera assumption from the mounting aid, not an exposure-time attitude measurement |
| Intrinsics | Camera metadata mapped into the upright, complete analysis image |

The profile is identified as `test-bus-2026-09-29`. It is **installation-specific**,
not an estimate for other cars. Android prefers Camera2 intrinsic calibration;
when absent it permits a single-focal-length physical-sensor pinhole approximation,
identified in the revision. iPhone requires delivered intrinsic-matrix metadata;
if it is unavailable the association remains unknown. Neither path invents an FOV.
Effective intrinsics, crop/rotation mapping and mounting values are part of the
scope so incompatible rays do not share history.

Height, pitch, banking, road slope, lens distortion and GNSS antenna position
remain sources of systematic error. Location fixes represent the phone's position,
used as an approximate vehicle centre; the small known camera offset does not
remove metre-scale GNSS uncertainty. The core's verified flag means a complete
supplied configuration, not independently measured field accuracy. Do not enable
new sign rejection merely because the synthetic controls pass.

## Logs and dashcam review

Each analyzed frame emits `tsr_path_evidence_v1` using the existing local debug-log
path. On Android its root `evidence` field is a JSON string; on iPhone it appears after
`tsr_path_evidence_v1=`. Enable Debug logging to persist it. No video is burned with
the overlay. The record retains:

- Frame ID, original callback time, mapped exposure time, capture-clock availability,
  capture age, scope and effective image mapping.
- Full effective calibration, installation provenance and uncertainty caveats.
- Sampled causal trajectory and accuracy, local coordinate origin, observation
  histories and original sign boxes linked to physical track/candidate IDs.
- Boundary points, cue/support/confidence; image and ground corridor polygons,
  assigned/unknown roles; sign association reasons, residual/parallax/baseline,
  uncertainty and source-fix timing.
- Preparation, geometry, pre-serialization and total added processing durations,
  geometry/total deadline status; explicit thermal/input-failure skips.

`tsr_path_recording_v1` records the video filename, start/stop callbacks (Android
also records periodic duration anchors), UTC and recorded duration where available.
These anchors are labeled `callback_anchor_estimated`. They are **not exact camera
exposure-to-encoded-PTS synchronization**. Preserve the original video and logs;
confirm video time/crop alignment in Inspector before drawing historical evidence.

Inspector's Dashcam path-evidence import accepts both log envelopes. It uses the
same normalized geometry for its optional overlay, requires explicit timing/crop
confirmation, and clears evidence across stale, mismatched or over-budget frames.
See [Inspector instructions](../inspector/README.md). Live overlays fade and expire
within 750 ms and represent observed boundaries, not a driving instruction.

## Validation and remaining qualification

On 29 September 2026, the Android suite passed **476 tests**, the iPhone app built,
and the shared native replay passed **18 boundary and 21 path cases** with matching
Swift/Kotlin results within `1e-9`. Run the replay with
`python3 scripts/lanes/replay_path.py`; its fixtures exercise actual production
cores, including curves, portrait input, ambiguous corridors and causal timing.
All 59 Inspector import/controller tests pass, covering malformed, stale and
mismatched evidence. A browser check with synthetic video/logs verified the
aligned overlay and readable labels; it is a rendering check, not road accuracy.

The attached Moto g86 component benchmark completed **840 measured samples**,
plus 56 warmup and seven cold samples, without exceeding 200 ms. The worst
measured component sample was **47.3 ms**, and the worst cold sample **75.1 ms**.
See the benchmark report below for exact timing scope and reproducibility details.

Run the native unit tests and the [Moto benchmark](ROAD_PATH_ANDROID_BENCHMARK.md).
The benchmark's direct production-component replay measures preparation,
geometry, history/association, serialization and worker dispatch. Its alternating
baseline isolates the added path. It also exercises fully valid synthetic
triangulation so early unknown results are not the only cost measured.

Component timing alone cannot establish interference with live TSR, CameraX,
recording, photo capture and sustained thermal load. The full 200 ms requirement
needs matched on/off driving workloads and deadline tails on the Moto. Real sign
qualification must preserve the paired main-road 90 and taken-exit 50 while
rejecting the reviewed access-road 30, and cover the unmarked Swiss junction,
curves, left branches, shadows, night, occlusion and same-carriageway signs.
Ground truth must remain separate from all causal features.
