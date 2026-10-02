# Live lane evidence, version 1

This is a dependency-free, classical **prototype for the dashcam overlay**, with equivalent Swift and Kotlin implementations. It does not alter traffic-sign decisions, matched roads or displayed speed limits. It is not a lane departure warning or vehicle-control feature.

## Input and result contract

- Input is an owned, contiguous, upright, full-image 8-bit luminance buffer. Width is 64–640 pixels and height is 64–960 pixels; runtimes normally downsample to 384 pixels across. Invalid dimensions, buffer length or a non-finite capture timestamp produce `unavailable`.
- `LanePoint` uses normalized full-image coordinates, with `(0,0)` at the top left. Points have **not** been transformed into preview coordinates. The runtime must carry image geometry, crop, orientation, mirroring and capture-session identity alongside the result and apply the same visible crop as the camera preview.
- Each boundary has five points spanning only the rows with observed stripe evidence, and a heuristic confidence between 0 and 1. Confidence is a quality score, **not a calibrated probability**. A missing side stays absent. The baseline fits straight segments and never extrapolates a boundary below/above its observed extent.
- `timestampSeconds` means capture time in a monotonic clock. Preprocessing, detector time, callback delay, generation and frame identity belong to the runtime wrapper. Never replace capture time with result-ready time.
- `reliable` requires two geometrically plausible boundaries with individual confidence at least 0.62. A single boundary, weak pair or competing lane candidates is `uncertain`. No retained boundary is `unavailable`.
- `LaneTracker` is owned by one processing worker. It smooths only compatible current observations, with 70% current-frame weight, and requires two compatible reliable pairs before filling a lane. A missing side disappears immediately. An explicit reset, a non-increasing timestamp, or a gap greater than 0.6 seconds restarts confirmation. The preview separately fades/expires its most recent result.

## Bounded algorithm

The detector samples 24–48 rows between normalized `y=0.48` and `0.94`, increasing row density in portrait images. At each row, a narrow center stripe must be brighter than **both** neighboring strips; brightness transitions alone do not qualify. Stripe radii scale with image width. Local suppression and a four-candidate cap per side bound subsequent work.

Pairs of vertically separated candidates seed a line fit. Each sampled row contributes at most one nearby inlier. Support count, vertical coverage, contrast and residual determine confidence. Minimum vertical evidence scales with aspect ratio so a short visible road above a portrait dashboard can still produce observations. Competing separated fits reduce confidence; implausible pairs are rejected. Least-squares refinement produces the displayed polyline within the observed interval.

This baseline will miss poorly marked roads, severe curves, many night/rain scenes, unusual camera mounts and low-contrast/yellow markings. It can confuse other narrow bright road features with paint, and cannot identify the correct lane at every split. These are reasons to keep it optional, show uncertainty and evaluate recorded scenes before using its geometry for road-sign applicability. The detector interface can later accept a learned segmentation backend without changing preview geometry or scheduling.

## Replays and verification

Run `python3 scripts/lanes/replay.py` from the repository root. It compiles the production Swift and Kotlin cores, renders the same fixture pixels once, and compares every boundary coordinate, confidence, state and timestamp over three frames. Absolute/relative tolerance is `1e-9`; final results must also satisfy each fixture's expected sides and state. Swift, the Kotlin CLI and Java must be installed. Build products stay in a temporary directory.

`replay_cases.json` version 1 contains default `width` and `height` and a list of cases. A case may override its dimensions. Each case has `name`, grayscale `background`, ordered `strokes`, and `expected` (`left`, `right`, `state`). A stroke is a polyline of normalized `[x,y]` points, a pixel `width`, and an 8-bit `brightness`. Rasterize pixel centers by Euclidean distance to each segment in pixel coordinates; points map to `(x*(width-1), y*(height-1))`. Paint points within half the stroke width; later strokes overwrite earlier ones.

Fixtures cover solid and dashed markings, a missing side, blank and low-contrast roads, poles, crosswalks, dark shadows, short fragments, incompatible geometry, competing lane candidates, strong curves, occlusion, dashboard edges and a portrait road above the hood. These synthetic checks establish determinism and deliberately chosen failure cases. They do **not** establish real-road accuracy or sustained phone performance. Native unit tests additionally cover tracker confirmation, loss, timestamp regressions, long gaps, explicit resets, invalid input and fit alignment.

Device acceptance still requires labelled real drives and baseline-versus-overlay endurance runs with recording and Panoramax capture, collecting capture-to-overlay age, preprocessing/detector p50/p95, achieved rate, dropped recording frames and thermal states. Host replay timing cannot substitute for those measurements.
