# Lane detection and dashcam visualization

The optional lane overlay estimates visible painted boundaries from the existing
rear-camera stream. The first implementation is a display-only prototype for
evaluating geometry and sustained device cost. It does not change the speed
limit, confirm sign applicability, upload imagery, or modify recorded video.

## Product behavior

- **Show detected lanes** defaults off on both platforms.
- Lane analysis runs while an enabled dashcam preview is visible and active,
  independently of traffic-sign recognition. Hiding the preview pauses this
  display-only analysis.
- The camera and preview stay attached when the overlay is toggled. No second
  camera session is created.
- Visible boundary evidence is drawn as thin paths. A faint fill is permitted
  only when both observed boundaries form a plausible, reliable lane.
- Missing boundaries remain unknown. Results fade with capture age and expire;
  a camera restart, geometry change, disabled setting or thermal pause clears
  the overlay.
- Serious or critical thermal pressure pauses lane processing. Recording and
  photo capture retain their own lifecycle.

## Processing and coordinates

The initial target is a 384-pixel-wide upright grayscale image at 5 Hz. These
are scheduling settings, not claims about achieved device throughput.

The camera callback admits work before copying/downsampling luminance. It must
respect each plane's row/pixel stride and release platform image ownership
promptly. Lane processing has one active job and bounded latest-frame pending
work; it cannot accumulate an image backlog behind sign inference.

The Swift and Kotlin estimator implementations use the same deterministic
algorithm and replay cases in `shared/lanes`. The estimator finds narrow bright
stripes, fits plausible road boundaries, and filters their temporal consistency.
It has no downloaded model or new third-party vision runtime.

This baseline fits locally straight, converging markings in the lower image.
It renders only their observed extent and requires two compatible frames before
showing a reliable pair. It does not yet model curved lanes, lane changes,
intersections or arbitrary camera mounting. The synthetic portrait case checks
a short visible road above the hood; it is not camera calibration.

Results carry image-relative boundary points and confidence. The runtime also
associates capture time, capture/geometry generation and preprocessing geometry.
Projection into the preview must account for analysis-to-sensor mapping,
orientation, mirroring, crop and aspect-fill scaling. Normalized image points
alone are insufficient when analysis and preview have different fields of view.

Sensor/presentation timestamps and elapsed-time measurements must share a known
monotonic clock mapping. Callback arrival time alone cannot measure the full
age of a camera image. Do not subtract timestamps from unrelated clock domains.
On iPhone, presentation time is converted from the capture session's
synchronization clock to the host clock. Android uses the camera's realtime
timestamp source when available. An Android camera with an unspecified clock
origin uses a per-session offset estimate, explicitly marked
`capture_age_estimated` in diagnostics. That estimate cannot recover the initial
camera queue delay; its age measurements require separate device validation.

The main implementation points are:

| Responsibility | iPhone | Android |
| --- | --- | --- |
| Pure estimator and temporal confirmation | `LaneDetection.swift` | `LaneDetection.kt` |
| Admission, small luminance buffers, worker, expiry and timings | `LaneDetectionRuntime.swift` | `LaneDetectionRuntime.kt` |
| Existing camera fan-out | `PanoramaxRecorder.swift` | `AndroidTrafficSignRuntime.kt` |
| Setting and runtime lifecycle | `DriveSessionViewModel.swift` | `ConsumerSessionController.kt` |
| Live preview and overlay | `PanoramaxRecorder.swift`, `MainView.swift` | `ConsumerParityUi.kt` |

Paths in this table are under `iphone/SpeedConsumerApp` and
`android/app/src/main/java/de/youspeed/android/alpha`, respectively.

## Verification

Deterministic tests cover boundary geometry, absent/ambiguous markings,
temporal stabilization and expiry. Platform tests cover stride handling,
coordinate transforms, cancellation and enablement independently of TSR.
Cross-platform replay compares states, boundary presence, geometry and confidence.

Run the replay from the repository root with Swift, Kotlin CLI and Java on PATH:

```sh
python3 scripts/lanes/replay.py --output /tmp/youspeed-lane-parity.json
```

It compiles both production estimators, renders the same fixture pixels, processes
three frames per case, checks the expected final states/boundaries, and compares
every frame's coordinates and confidence to a tolerance of `1e-9`. Build products
and raw fixtures are temporary. Unit tests are `LaneDetectionTests` and
`LaneDetectionRuntimeTests` in each client. The iPhone tests are included in the
`SpeedConsumerTests` target through `iphone/project.yml`.

Runtime diagnostics retain bounded 128-sample timing windows. iPhone uses the
`lanes` OSLog category; Android emits `lane_preview_performance` diagnostic
events. These measurements describe lane work, not total camera/encoder cost.
Use platform profiling and existing recorder/TSR diagnostics for the remaining
pipeline costs and actual recording drops.

Initial implementation verification on 2026-09-13:

- Cross-platform replay: 16 cases / 48 frames passed, including timestamps and
  the corridor polygon as well as boundaries and confidence.
- iPhone simulator: app build, 15 lane tests and 7 recorder/preview regression
  tests passed.
- Android: debug build and 62 relevant lane/recorder/TSR regression tests passed.
  Lint reports an existing `MissingTranslation` error for
  `ui_camera_speed_limit_end` in `res/values/consumer_ui.xml` (sv/pt/it/pl/es);
  that resource is unchanged by this feature.
- A smoke check on the two existing Panoramax portrait stills produced a single
  right boundary with an uncertain state. These are unlabelled still images,
  not an accuracy or temporal evaluation.

Physical-camera overlay alignment, real driving sequences and endurance runs
remain to be verified.

Synthetic fixtures establish deterministic behavior; they do not establish
on-road accuracy. Evaluation on real driving sequences must include:

| Scenario | Required observation |
| --- | --- |
| Straight roads and gentle curves | Boundaries follow observed markings without jumping between lanes. |
| Exits, intersections and lane splits | Ambiguity lowers confidence; the overlay does not invent a reliable corridor. |
| Single/worn/absent markings | Missing boundaries stay absent. |
| Shadows, guardrails, hood/dashboard and pavement seams | Distractors do not produce a reliable lane pair. |
| Rain, darkness, glare and occlusion | Unusable evidence expires promptly. |
| Portrait/landscape, resized preview and alternate resolutions | Paths stay aligned after the full preview transform. |
| TSR off, overlay off, hidden preview, restart and thermal pause | Correct independent lifecycle and no stale callback publication. |

For each supported phone, compare the same route/configuration with lane
visualization off and on for at least 30 minutes. Enable the normal dashcam,
TSR and Panoramax photo workloads. Record the hardware/OS/build identity and
settings alongside:

- Preprocessing and detector p50/p95, capture-to-result and capture-to-overlay age.
- Achieved lane and TSR update rates, intentional cadence skips, replaced work
  and actual camera/encoder drops as separate counters.
- Peak memory, thermal transitions and time spent throttled/paused.
- Recording continuity and responsiveness of speed lookup and warnings.
- Boundary errors, recovery time and time spent with a reliable pair.

Simulator and host timings are useful regression evidence, but do not replace
these physical-device runs. Field-drive and thermal conclusions remain pending
until measured; a successful build is not evidence of spare realtime capacity.

## Follow-on work

Road-sign applicability is a separate consumer of validated lane evidence. It
requires physical tracks for multiple simultaneous signs, alternative-road
geometry and an explicit `our road / other road / uncertain` decision before
actionable-sign selection. Roadside signs are often outside lane boundaries;
the lane polygon must not become a hard sign-detection crop or acceptance mask.
Measure both wrong-road activations and missed valid signs before allowing this
decision to affect displayed limits.

Recorded playback can later use timestamped lane metadata alongside the
original video. Permanently embedded overlays require a separate video
compositor/export path.
