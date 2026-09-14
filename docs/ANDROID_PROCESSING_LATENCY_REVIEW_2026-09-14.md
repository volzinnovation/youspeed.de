# Android processing latency review — 14 September 2026

The reconnected Moto reproduces preview degradation when GPU recognition is
enabled. Fresh driving logs also establish proposal-dependent inference cost,
confirmed speed signs, and long gaps between successful road-context updates.
The subsequent implementation improves GPU execution, preview composition,
primary-sign delivery, and road-context freshness while retaining full-frame
recognition. Implementation and device-validation results follow the original
analysis below.

## Follow-up with the reconnected Moto

Collected the current app logs, camera state, thermal state, UI frame statistics,
and two 12-second scheduling/rendering traces. The installed debug app reports
version 1.1-debug, code 10007, updated at 09:14:24 CEST. No runtime code or APK
was changed during this initial measurement phase.

### Preview slowdown reproduced

Opened a short recorder session with the visible preview, dashcam, recognition,
and the user's existing Panoramax setting enabled. Compared recognition on and
off while keeping the recorder and preview active. Restored recognition to
enabled, then stopped the diagnostic recording; the final UI again offers
"Fahrtaufzeichnung starten". The resulting short recording was retained.

| Measurement | Recognition on | Recognition off |
| --- | ---: | ---: |
| Trace duration | 12.000 s | 12.000 s |
| App draw cadence while preview visible | 20.5 FPS | 28.5 FPS |
| 95th-percentile interval between app draws | 164 ms | 62 ms |
| Longest interval between app draws | 210 ms | 81 ms |
| RenderThread buffer-swap duration, p95 | 159 ms | 3.3 ms |
| CameraX GL thread buffer-swap duration, p95 | 64 ms | 3.0 ms |
| Main-thread wait for rendering, p95 | 79 ms | 3.8 ms |

Draw cadence is an app-rendering measurement while the preview is visible,
not a count of independently verified unique camera images on the panel.
The separate 120-frame `gfxinfo` presentation windows corroborate this:
approximately 20.5–22.0 presented FPS with TSR on versus 30.5–30.8 with it off.
Short presentation windows can exceed the camera's source cadence and do not
establish that every presented buffer contains a different camera image.
Both recorder camera snapshots report approximately 30 FPS sensor timing.
The three physical outputs are a 4096 × 3072 JPEG stream, 1600 × 1200 YUV
analysis, and a 1600 × 1200 SurfaceTexture stream shared for preview/video.

This controlled comparison strongly implicates recognition-related GPU
contention in the preview slowdown. It affects both UI rendering and the
CameraX GL path. Therefore changing only the UI preview surface may help but
cannot be assumed to remove all contention: the shared video/preview GL path
also stalls. These are short sequential samples from the current indoor scene,
not a sustained thermal or road benchmark.

The RenderThread spent approximately 6.15 seconds waiting on fences during
the TSR-on trace versus 4.5 ms with TSR off. Actual UI display-list recording
remained about 2.15 ms at p95 in both traces. This makes GPU/fence waits a
stronger explanation for the reproduced stalls than expensive UI composition
on the main thread. Percentiles are approximate empirical sample values.

Before opening the recorder, standalone analysis used 1920 × 1440 YUV and a
100 ms exposure/frame duration, approximately 10 FPS. That dim-scene exposure
limit did **not** persist in the recorder comparison: recording selected a
30 FPS target and approximately 33.35 ms frame duration. Do not conflate these
two camera states. The thermal snapshot showed a cached LIGHT skin status,
current CPU/GPU readings around 49 °C with status NONE, and GPU cooling-device
state zero; it does not establish thermal conditions during the drive.

Evidence: `/private/tmp/youspeed-preview-tsr-{on,off}-trace-20260914.txt`,
the corresponding `*-camera-20260914.txt` and `*-gfx-20260914.txt` captures,
and the locally derived `*-trace-summary-20260914.json` files. Trace slice
durations include nested work/waits and must not be summed as exclusive costs.

### Fresh driving recognition performance

The 09:16–09:55 CEST log contains 1,133 sampled inference results. All use GPU;
there is no sampled CPU fallback or terminal failure. Most sign activity is
between 09:31 and 09:36.

| Classifier calls per frame | Logged samples | Median inference |
| ---: | ---: | ---: |
| 0 | 1,026 | 428 ms |
| 1 | 54 | 549 ms |
| 2 | 26 | 647 ms |
| 3 | 12 | 760 ms |
| 4 | 7 | 843 ms |
| 5 | 5 | 978 ms |
| 6 | 3 | 1,044 ms |

Sign-present samples have median 631 ms, p95 978 ms, and maximum 1,056 ms.
On these samples, detector execution accounts for approximately 62% and
classifier execution for 29% of measured inference. Classification costs
approximately 93 ms per crop. Detector preprocessing has median 20 ms and
p95 24 ms, with an isolated 153 ms spike. Prioritize detector/GPU and classifier
work over expecting small preprocessing savings alone to resolve this.

There are 11 sampled confirmed and five provisional recognition states. One
30 sign was logged provisional at 09:34:03.698, confirmed at 09:34:05.252,
and finalized at 09:34:07.742: approximately 2.49 seconds from the first
logged confirmation to passage finalization, despite individual model passes
around 650–700 ms. Unknown/non-speed observations are neutral in both clients'
passage logic and can extend the wait until qualified primary-sign absence.

Because diagnostics are throttled, sampled confirmation/display/passage flags
are not complete event counts. They also do not timestamp actual speed-state
application or painting. The 76 accepted-display samples do not mean 76
user-visible speed changes; numeric speed signs use the finalized speed lane.

### Road lookup can leave recognition using an old context

The successful road-match log has 57-second, 33-second, and 48-second gaps
during the sign stretch while GPS fix numbers advance. At the first logged
40-sign confirmation, the last successful matched-fix timestamp is 39–42
seconds older. These are gaps in successful context refresh, not measured
database queue waits or exact display delays.

Source inspection explains a starvation mechanism: each GPS fix advances
`lookupToken` (`ConsumerSessionController.kt:3175`), queues work on the shared
executor, and discards its completed result if a newer fix arrived (`:3328`).
There are additional token guards during evaluation and UI publication.
Camera context coordinates are rebuilt only from successful lookup results
(`:4134`) and later copied into each frame (`:1904`). Thus the logged
`contextIsCurrent=true` scope/session check does not establish fresh position.

Use a dedicated lookup worker with one in-flight lookup and a replaceable latest
pending fix. Accept useful completed results within bounded age/displacement,
preserving monotonic committed-fix order and session/bundle invalidation. Keep
latest GPS and matched-road timestamps separately. Update capture position only
while compatible with the trusted road identity; otherwise mark context pending
until a new match. Never relabel an arbitrarily old road as current.

iPhone explicitly marks frame context pending during lookup and separates its
utility lookup from primary publication. It also rejects superseded fixes, so
the proposed anti-starvation acceptance policy needs a deliberate parity check;
it must not be described as an already-existing iPhone policy.

Fresh evidence: `/private/tmp/youspeed-current-runtime-20260914.ndjson`,
`/private/tmp/youspeed-current-drive-20260914.ndjson`, and
`/private/tmp/youspeed-current-logcat-20260914.txt`. Location-bearing logs remain
local and are not repository fixtures.

### Updated implementation priorities

1. Give primary speed publication its own short serialized path; keep lookup,
   diagnostics, photo annotations, and persistence off that path. Fix sparse
   road-context refresh and explicitly represent context freshness.
2. Reduce recognition's GPU occupancy and sequential classifier workload.
   Benchmark reduced precision/full-frame inference and safe primary-first
   scheduling. Deferred/unprocessed work must never count as sign disappearance.
3. Reduce preview GPU composition with the supported SurfaceView path, and
   unnecessary CameraX work. When Panoramax is off at session start, still
   capture can be omitted: its enable setting is locked during recording.
   Retain video/analysis use cases needed by live toggles, but investigate
   deactivating the analyzer when TSR is off without rebinding the movie.
4. Add the missing capture-to-presentation timestamps to verify each change.
   Keep full-frame coverage while testing these optimizations.

## Initial review and earlier benchmark context

Reviewed source at `e33f51c`, including the corresponding iPhone implementation.
During the initial source review, the device was disconnected and the saved
log ended at 09:16 CEST. The reconnected-device results above supersede that
limitation. The following records retain the earlier benchmark context and
explain the implementation opportunities in more detail.

The saved Moto g86 5G measurements establish that its Mali-G615 MC2 GPU works
with both models. The reference fixture had these warm timings:

| Stage | Earlier measured duration |
| --- | ---: |
| Detector preprocessing | 19.6–21.2 ms |
| GPU detector | 363–372 ms |
| One GPU classifier invocation | 98.8–102 ms |
| Total inference, one reference sign | 520–528 ms |
| Same reference, forced CPU total | 1,419 ms |

The last saved normal live session, 09:16:01–09:16:12 CEST, contains 11 logged
GPU results at 397–421 ms, with **zero detector proposals in every frame**.
Consequently, it does not validate current driving performance in scenes with
signs. The log is throttled to approximately one entry per second; its entry
frequency is not analysis FPS or preview FPS.

For comparison, the earlier CPU driving slice from 08:03:24 through 08:28:59
contains 869 logged results: 815 with zero classifier calls, 26 with one, 16
with two, nine with three, and three with four. Median inference rose from
1,613 ms with no classifier calls to 2,172 ms with one and 2,926 ms with four.
These are different scenes on the earlier runtime, not controlled measurements
of the incremental classifier cost and not evidence of a current GPU failure.

The saved log also contains historical `lane_preview_performance` events,
ending at 08:07:28. Their processed-frame rate is not the camera-preview frame
rate. The reviewed source has no separate lane-detection analyzer, and the
current preview update callback records no FPS.

Raw evidence remains local in `/private/tmp/youspeed-moto-live-after-install-20260914.ndjson`
and `/private/tmp/youspeed-moto-tsr-acceleration-parity-20260914.json`.

## Processing chain and priority

The Android path is:

1. CameraX delivers a YUV image; the orchestrator snapshots driving context and
   applies admission/cadence rules.
2. The inference worker converts the full image to an RGB bitmap and allocates
   a second full-resolution bitmap for rotation when required.
3. It resizes/letterboxes to 1280 × 1280, runs the detector, decodes proposals,
   and computes diagnostic statistics.
4. It classifies up to 12 proposals sequentially at 224 × 224.
5. It selects the primary detection and updates confirmation/passage state.
6. Its observer writes diagnostics synchronously, then forwards recognition,
   passage, and pictogram callbacks.
7. A finalized passage waits on the controller's shared background executor,
   resolves its effect, and posts the speed-state change to the main thread.

`inferenceMs` covers only the model-engine portion. It excludes full-image
conversion/rotation, admission delay, observer/logging cost, controller queue
wait, and main-thread presentation. Startup reference timing also bypasses
the live camera and these queues. It helps choose a confirmation allowance but
does not measure the whole processing chain.

Source: `AndroidTrafficSignRuntime.kt` (`CameraXTrafficSignFrame`,
`recognizeAllWithDiagnostics`, `AndroidLiteRtTrafficSignBackend`),
`TrafficSignLiveRuntimeBridge.kt` (`TrafficSignFinalizedPassageForwarder`), and
`ConsumerSessionController.kt` (`submitFinalizedTrafficSignPassage`).

### First: remove unrelated work from primary delivery

- Deliver recognition/passages before diagnostic file work, and move bounded
  logging to an independent worker. The current forwarder calls diagnostics
  first, and the controller uses synchronous file append operations.
- Give speed resolution and publication a short, serialized path independent
  of map lookup, photo processing, exports, and storage maintenance. Android
  currently queues all of these on the same single-thread executor. iPhone
  commits/publishes the finalized passage in its main callback, then persists
  asynchronously (`DriveSessionViewModel.swift`).
- Remove file/database I/O from locks needed by camera admission or main-thread
  delivery. The main recognition callback takes `captureLock`, while background
  photo annotation holds it across batch listing and writes. Similarly,
  `trafficSignStateLock` protects both camera-context snapshots and observation
  database operations. Preserve generation/session checks and write permits
  while separating immutable snapshots from I/O.
- Coalesce unchanged debug/UI state. Even cadence-rejected submissions request
  a debug clear; state normalization can perform map-file existence/size checks
  on the main thread. This is avoidable work, but its severity is unmeasured.

These dependencies are confirmed in source. Their contribution to the latest
reported delay requires tracing; no measured speedup is claimed.

### Second: prioritize primary inference and reduce model cost

All proposals currently finish classification before any primary result is
delivered. At the earlier reference cost, three additional classifier calls
would add roughly 300 ms; 12 total calls could consume roughly 1.2 seconds in
classification alone. Those are estimates from one fixture. The earlier CPU
driving slice observed at most four calls, not twelve.

Prioritize candidates overlapping an active primary track, and investigate
emitting a proven primary result before completing secondary pictogram work.
The detector finds generic signs, so position alone cannot tell whether an
unclassified proposal is a speed sign. An early-selection implementation must
prove that remaining candidates cannot outrank the selected primary, preserve
frame identity, and prevent unfinished classification from becoming negative
passage evidence. Simply returning the first classified sign or dropping all
other candidates would change recognition behavior.

Further bounded experiments:

- Fuse rotation into detector resize and classifier crop transforms, avoiding
  the second full-resolution rotated bitmap. Preserve orientation, letterbox,
  bounding-box coordinates, and the existing extended classifier crop. CameraX
  1.4.2 `toBitmap()` uses native YUV conversion; there is no JPEG round trip to
  remove. iPhone supplies the pixel buffer and orientation directly to Vision.
- Use primitive accumulators for diagnostic score maxima and avoid expensive
  per-frame diagnostics when no sample will be logged. Current scans visit
  approximately 269,000 score values with nullable `Double` accumulators.
- Benchmark GPU reduced precision. Android explicitly sets
  `setPrecisionLossAllowed(false)`; the iPhone model exports use `half=true`.
  This targets the dominant detector cost, but requires representative class,
  score, threshold-boundary, and sustained-preview checks before adoption.
- Inspect actual negotiated analysis size/aspect ratio. The last saved frame
  was 1440 × 1920 despite the 1920 × 1080 resolution request. Specify a deliberate
  resolution/aspect-ratio policy and benchmark conversion savings without
  sacrificing small or distant signs. A smaller camera buffer alone does not
  reduce the fixed model's detector operations.

### Passage semantics also contribute latency

Both clients normally require two successfully analyzed missing frames after
a repeatedly observed sign disappears. Strong pass geometry can reduce this
to one; a qualifying single-sighting track requires three. Throttled, failed,
or unprocessed frames do not count.

Thus a three-second completed-analysis interval can add approximately six
seconds for the normal two-frame loss debounce. Faster processing reduces
this delay. Increasing the confirmation allowance only prevents track expiry;
it does not accelerate display. Primary scheduling must retain these passage
rules, rather than treating skipped secondary work as proof of disappearance.

Source: `TrafficSignPassage.kt`, `TrafficSignPassageConfiguration` and
`observeMissing`, checked against the iPhone passage implementation.

## Dashcam preview

Preview is a separate CameraX use case feeding a `TextureView`; it is not
redrawn only when TSR completes. The analyzer already uses nonblocking
`KEEP_ONLY_LATEST`, which lets other camera consumers continue while analysis
is busy. Slow inference therefore does not by itself establish that analyzer
backpressure causes the reported preview stutter.
[CameraX analysis behavior](https://developer.android.com/media/camera/camerax/analyze).

Two priority experiments are warranted:

1. Replace the custom `TextureView` path with CameraX `PreviewView` in
   `PERFORMANCE` mode where supported. Its `SurfaceView` path can use hardware
   overlays and avoid GPU composition, potentially reducing contention with
   GPU inference. Hardware overlay use is not guaranteed. Verify clipping,
   orientation, visibility transitions, and overlaid controls.
   [CameraX preview guidance](https://developer.android.com/media/camera/camerax/preview).
2. Inspect camera hardware level, negotiated stream sizes/FPS, and stream
   sharing. Recorder mode always binds preview, video, still capture, and
   analysis, including unused still capture when Panoramax is disabled.
   CameraX documents additional processing demands from stream sharing on some
   hardware. Omit unused outputs at safe session boundaries where beneficial;
   preserve module toggles and uninterrupted active recording. Merely removing
   still capture does not guarantee stream sharing disappears.
   [CameraX architecture](https://developer.android.com/media/camera/camerax/architecture).

iPhone uses `AVCaptureVideoPreviewLayer` and conditionally adds the photo
output during initial setup. Neither comparison proves the Moto's current
preview bottleneck without measurement.

Keep CameraX frame freshness intact: closing the active `ImageProxy` earlier
without redesigning the application's pending-frame policy can retain the
next image for the duration of the previous inference. That would reduce
freshness rather than improve end-to-end latency.

## Right-side recognition

A right-side crop passed to the same 1280 × 1280 model still runs the same
detector graph and produces the same 33,600 proposal positions. It can enlarge
signs and reduce the number of classifier candidates, but it does not halve
the detector's approximately 370 ms reference cost. It also removes left-side
and overhead signs from coverage.

Prefer scheduling likely roadside/active-track candidates earlier while
retaining full-frame coverage. A smaller detector export could reduce actual
detector computation, but it needs small-sign recall and cross-platform
behavior validation. Restricting coverage should follow these code and model
experiments, not precede them.

## Remaining measurements for implementation validation

Current runtime logs, logcat, camera/thermal snapshots, and preview A/B traces
have now been collected without clearing the original logs. Additional app
instrumentation is needed to measure the complete primary-delivery path.

Instrument bounded, correlated timing samples for:

- sensor timestamp → analyzer delivery (verify camera timestamp clock source),
  admission/context-lock wait, and worker queue wait;
- YUV conversion/rotation, preprocessing, detector and each classifier;
- observer/logging duration, finalized-passage queue wait, resolver time, and
  main-thread state application;
- camera capture FPS, visible preview updates/frame gaps, and recorded video
  cadence separately; UI jank metrics alone do not measure camera FPS.

Compare the same scene and thermal state with preview alone, preview + TSR,
preview + recording, preview + TSR + recording, and then Panoramax capture
added. Distinguish cold startup from sustained operation. Repeat with a real
primary sign and a scene containing multiple signs; a blank view or one startup
reference cannot validate primary-priority scheduling under load.

Acceptance should include prompt primary publication without waiting for
storage work, unchanged confirmation/passage results, smooth preview during
inference, and no recording or photo-output regression.

## Implemented improvements and device validation

The following changes were implemented after the measurements above and
validated on the attached Moto g86 5G. iPhone remains the behavioral reference:
confirmation thresholds, qualified missing-frame passage rules, sign classes,
full-frame coverage, capture outputs, and module controls remain aligned.

### Inference and camera work

- Allow reduced-precision GPU execution, retaining `FAST_SINGLE_ANSWER`.
  Verify the existing startup reference before enabling live recognition;
  retry full-precision execution if reduced-precision startup verification
  throws, with the existing CPU fallback retained. Log the selected precision
  alongside startup timing. The Moto has an ARM Mali-G615 MC2 GPU and all
  benchmark cases actually used it without CPU fallback.
- Reuse the oriented bitmap/Canvas between frames. Replace boxed tensor
  diagnostics with primitive iteration. Preserve ImageProxy ownership and
  `KEEP_ONLY_LATEST` frame freshness.
- Suspend analysis when recognition is disabled or unavailable. Omit the
  still-capture output when Panoramax is disabled at recorder-session setup;
  retain active recording and capture outputs across module transitions.
- Use CameraX `PreviewView` in `PERFORMANCE` mode, which selected a SurfaceView
  on this Moto. Preserve rounded clipping, portrait orientation, overlaid
  controls, and the same native surface while hiding/showing the preview.

The precision comparison runs three measured passes per scene using the
bundled model and two existing iPhone/Panoramax sign photographs, a city-entry
fixture, a dimmed sign fixture, and a blank frame:

| Scene | Full-precision median | Reduced-precision median | Reduction |
| --- | ---: | ---: | ---: |
| Reference 70 sign | 486.71 ms | 345.42 ms | 29.0% |
| More distant 70 sign | 477.81 ms | 363.15 ms | 24.0% |
| City-entry fixture | 490.14 ms | 334.15 ms | 31.8% |
| Dimmed 70 sign | 496.40 ms | 356.96 ms | 28.1% |
| Blank frame | 396.95 ms | 296.83 ms | 25.2% |

Tests require the same proposal and classification counts, winning classes,
semantic/display decisions, and threshold outcomes. Detector score differences
must be at most 0.05 and classifier score differences at most 0.02. Each box
edge must move no more than one detector-input pixel and IoU must remain at
least 0.90. A preliminary fixed 0.95 IoU test rejected a distant sign at 0.94555
despite subpixel edge movement; the final test accounts explicitly for small
box sensitivity while retaining class, score, and decision checks. These five
fixtures do not establish accuracy across all road scenes or Android GPUs.

Normal optimized startup verified the reference on GPU in approximately
303–309 ms. The existing device-calibrated confirmation window remained
1,500 ms; increasing timing allowances alone was not used to claim a speedup.

### Primary-sign delivery and fresh road context

- Deliver finalized primary passages before secondary annotations and
  diagnostics, using a dedicated serial delivery executor. Publish speed
  state before queued storage and diagnostic writes.
- Keep file operations out of the camera context lock and main thread.
  Immutable write-gate snapshots let camera work continue during persistence
  while preserving session invalidation and durable-write ordering.
- Give GPS matching one running lookup and one replaceable pending fix.
  A newer GPS fix no longer invalidates every in-flight lookup; lifecycle
  changes still do. Reject out-of-order commits.
- Validate the matched position before reusing road identity: at most six
  seconds old, at most 250 metres displacement, and no heading change beyond
  45 degrees while both positions are moving. Refresh current position fields
  without pretending an old road match was newly resolved. Stale context is
  unavailable to primary admission. Resolver revisions prevent delayed lookup
  publication from overwriting a newer camera-derived speed state.
- Add backend queue, conversion, camera-receipt-to-result, primary-delivery,
  and speed-state application timings. Camera receipt uses `System.nanoTime`
  consistently; sensor-to-receipt latency is not inferred by mixing clocks.

The optimized indoor live session logged 57 successful road updates with a
median three-second gap and maximum 4.02-second gap. Query duration was median
928 ms and maximum 1,330 ms. This validates continued commits while newer fixes
arrive; it is not a repeat of the earlier driven route or its map transitions.

### Optimized preview and live timings

With recording, recognition, and the existing Panoramax setting enabled,
the optimized SurfaceView produced 127 unique presentation timestamps over
4.533 seconds: **27.79 FPS**. Median presentation interval was 33.33 ms,
p95 50.07 ms, and maximum 183.39 ms; five of 126 intervals exceeded 100 ms.
Occasional preview stalls therefore remain.

The earlier TextureView measurements indicated roughly 20–22 app presentations
per second with recognition active. That comparison is directional: the old
measurement follows app rendering, the new one follows the SurfaceView, and
the windows differ. SurfaceView presents independently of app redraws; the
optimized trace's approximately 4.75 app redraws per second are not camera FPS.
The more comparable 12-second trace measurements show substantially less
contention in the shared graphics path:

| Measurement | Earlier recognition on | Optimized |
| --- | ---: | ---: |
| CameraX GL buffer-swap duration, p95 | 65.54 ms | 8.01 ms |
| CameraX GL fence waits, total | 4.89 s | 1.89 s |
| GPU-completion waits, total | 9.74 s | 5.25 s |
| Main-thread graphics wait, p95 | 85.88 ms | 1.86 ms |

This table uses linearly interpolated percentiles, explaining small differences
from the empirical percentiles in the original table. Traces measure the
combined changes and do not isolate the individual contribution of SurfaceView
or reduced precision. Nested waits must not be summed as exclusive costs.

Across 68 sampled live frames in the current indoor scene, median inference
was 293.82 ms, conversion 38.95 ms, backend queue wait 0.22 ms, and
camera-receipt-to-result time 339.67 ms (maximum 500.81 ms). This was not a
multi-sign road scene, so it does not measure driving recognition recall or
the final primary-sign appearance-to-display delay.

### Checks and deployment

- All 281 JVM tests passed, including lookup coalescing, context expiry,
  session invalidation, nonblocking camera snapshots during persistence, and
  primary delivery before blocked diagnostics.
- All seven native tests passed: precision/rotation checks, real-model
  recognition and passage transitions, startup isolation and CPU/GPU behavior,
  and recording/photo-session continuity through module and preview changes.
  Rotation checks compare exact pixels at 0/90/180/270 degrees and verify reuse.
- Debug, instrumentation, and release builds succeeded. Android lint reported
  zero errors (103 warnings, two informational findings). Attribution
  regeneration checks and four attribution tests passed; the CameraX view
  dependency and its transitive artifacts are included in bundled notices.
- Installed the final debug APK with an in-place update preserving app data.
  Removed only the temporary instrumentation-test package and reopened the
  app. The installed APK checksum matches the build below. Its startup
  reference passed on GPU at 10:34:44 CEST (308.71/302.97 ms); subsequent live
  frames continued on GPU without terminal backend failures. Recognition
  remains enabled and the diagnostic recording is stopped.

Final debug APK SHA-256:
`308a66c2b59c0b9d8bb47da109af3a6bd2a67b716f1cda0fccc82ffa890542ec`.

Evidence remains local in `/private/tmp/youspeed-optimization-*20260914*`
and `/private/tmp/youspeed-optimized-*20260914*`, including the precision JSON,
native-test results, runtime log, SurfaceFlinger timestamps, trace, and an
independently parsed trace summary. Raw location logs and recordings are not
committed.

The next validation is a representative drive with single and multiple primary
signs, turns, long-running recording, and warmer device conditions. Use the new
delivery timings to distinguish model, passage-confirmation, road-context, and
UI delay. Reduced precision still needs broader accuracy checks across Android
devices; the startup probe provides an initial device-specific verification,
not proof of full road-scene parity.
