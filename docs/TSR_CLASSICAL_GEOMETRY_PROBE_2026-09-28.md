# Classical geometry on saved dashcam video and Panoramax stills

**EDLines was the fastest of the four extractors in this desktop probe. Canny +
probabilistic Hough is a useful baseline. Both recover road-marking/curb pieces,
but neither output is yet a lane or governing-road decision.** Keep ELSED as the
next separately measured challenger: its published older-phone evidence is strong,
but it was not installed or run in this experiment.

## Actual inputs and results

The saved iPhone MOV from 24 September supplied 173 frames at approximately 5 Hz
across three separately identified intervals:

| Scene | Actual presentation-time range | Frames | Role |
| --- | --- | ---: | --- |
| Paired main-road 90 | 550–562 s | 61 | Preserve legitimate main-road evidence |
| Main-road 90, then access-road 30 | 613.97–625.97 s | 61 | Known wrong-road activation in the prior drive review |
| 50 on the roundabout exit taken | 1359.975–1369.976667 s | 51 | Preserve a genuine restriction through a turn |

The original MOV remains untouched. Its preferred 180° transform was applied once.
AVFoundation returned the actual rational presentation timestamp for each sampled
frame; requested times and actual times are both retained. No subsecond capture-UTC
mapping or physical sign track was invented. The 960×540 JPEG derivatives and
their hashes are retained in the ignored local evidence cache.

The still-image run processed 10 rectilinear/perspective images: four original
Android frames, five A75 frames and the new Swiss junction. Three A10 panoramas
were explicitly skipped because their equirectangular projection needs a verified
forward view. All processed images were checked against their corpus hashes.

**Video extractor timings, milliseconds, Apple M4 Max / OpenCV 4.14.0:**

| Extractor | Median | p95 | p99 | Maximum |
| --- | ---: | ---: | ---: | ---: |
| EdgeDrawing / EDLines | 0.78 | 1.17 | 1.26 | 1.42 |
| FastLineDetector | 0.99 | 1.57 | 1.73 | 2.10 |
| Canny + HoughLinesP | 1.71 | 3.21 | 3.56 | 3.78 |
| LSD | 3.38 | 4.33 | 4.64 | 5.04 |

Each method ran three times on each video frame: 519 warm samples per method.
The still run has 30 samples per method; p95 values were respectively 1.10, 1.66,
3.27 and 3.81 ms. Repeated measurements are correlated; these are descriptive
statistics for this probe, not confidence bounds or expected field tail latency.

Analysis preserves aspect ratio within a 384×216 bound, then uses the full-width
lower 65% of that image. A 4:3 source therefore becomes 288×216, not a stretched
384×216. This generous fixed crop is not inferred road geometry. Fixed parameters,
method-order rotation and a fixed OpenCV RNG seed reduce arbitrary comparison
differences; they have not been tuned to governing-road labels.

OpenCV parallel execution and OpenCL were disabled. The GCD build required
`setNumThreads(0)` to report one thread; `setNumThreads(1)` still reported 16.
The final runs check the setting around extraction. Initial runs with the wrong
setting were not used for the table above.

## What the overlays establish

Review of the service-road frame near 620 s shows both Canny/Hough and EDLines
recovering portions of the painted separator and carriageway edges. They also
detect barriers, buildings and vegetation. At the genuine 50 turn, the road edges
appear as several local segments along the bend; a single straight left/right
lane pair would be an inadequate representation.

The Swiss junction similarly contains useful road-edge pieces mixed with fences,
roofs and vegetation. It has no continuous painted ego-lane boundaries. A low
extraction time does not establish which segments describe the current road.
No lane recall, sign suppression success or model superiority is claimed from
these visual inspections or from raw segment counts.

The next comparison should feed the same bounded multi-boundary grouping and
road-association stage with EDLines and Canny/Hough outputs. Preserve curves and
forks, enforce road/pose uncertainty, and keep unknown as a possible result. Add
ELSED and the existing stripe detector as separate extraction arms. Evaluate
false rejection of the paired 90 and taken-exit 50 alongside rejection of the
access-road 30. Driver behaviour remains off.

## Timing boundary and reproducibility

These are **Mac extraction timings**. They exclude original 4K movie decoding,
AVFoundation downscaling and JPEG encoding, file/image preparation, output sorting,
boundary grouping, tracking, road association and mobile scheduling/contention.
The runner records image preparation separately. The 64-segment output cap bounds
the input available to later grouping; it does not cap extractor execution time.
Neither a <200 ms added Android result nor a completed lane detector is claimed.

The [research shortlist](TSR_ROAD_APPLICABILITY_RESEARCH_2026-09-28.md#low-compute-geometry-shortlist)
contains primary sources and the relevant older-Android measurements. The
[camera-alignment design](TSR_CAMERA_ALIGNMENT_AND_PATH_GEOMETRY_2026-09-28.md)
describes pose, calibration and exposure-time requirements for using this evidence.

Reproducible components:

- [Native video extraction](../scripts/tsr/applicability/extract_dashcam_geometry_frames.swift)
  uses macOS AVFoundation and retains actual PTS and hashes.
- [Offline comparison runner](../scripts/tsr/applicability/classical_road_geometry_probe.py)
  accepts image corpora or the extracted-frame manifest. Its direct ffmpeg path
  requires a functioning ffmpeg installation; the native extraction path was used
  because the local Homebrew ffmpeg installation cannot load its x265 library.
- [Pinned optional environment](../scripts/tsr/applicability/requirements-geometry-probe.txt)
  is separate from mobile app dependencies.
- [Portable measurement report](../shared/tsr/applicability/fixtures/classical-geometry-probe-20260928-v1.report.json)
  retains source/runner hashes, settings, frame identities, actual PTS and timings.
- Local full reports: `inspector/logs/2026-09-28-classical-geometry-probe/video-probe.json`
  and `stills-probe.json`; diagnostics are in the adjacent `overlays/` directory.

Example replay after installing the pinned optional requirements:

```sh
python scripts/tsr/applicability/classical_road_geometry_probe.py \
  --frame-manifest inspector/logs/2026-09-28-classical-geometry-probe/video-frames/frame-manifest.json \
  --output inspector/logs/2026-09-28-classical-geometry-probe/video-probe.json \
  --max-edge 384 --max-height 216 --repeats 3
```

No phone was accessed or restarted, and no app, model, bundle or shared
speed-reference policy was changed by this experiment.

Validation: 122 focused tests passed across the probe, Swiss challenger, image
geometry replay, public-image fetcher and offline exit-hypothesis simulation.
These include source-timing, orientation and candidate-isolation checks;
they are not a measured lane-accuracy result. `git diff --check` passed.
