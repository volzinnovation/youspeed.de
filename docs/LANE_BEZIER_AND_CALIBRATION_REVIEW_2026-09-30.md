# Lane presentation and calibration review — 2026-09-30

## Presentation change

Both clients now fit the published lane boundary points with bounded cubic Bézier
curves, replacing the earlier midpoint quadratic rendering and removing the large
sample dots. The native helpers use the same arithmetic. Endpoints are retained;
the maximum horizontal departure from the original polyline is `2/383` of the
image width (two pixels at the maximum 384-pixel lane-analysis width). Curves split
at invalid points, non-increasing image y, and gaps greater than 0.16 of image
height. They do not join separate boundaries or extrapolate beyond observations.
Sharp splits preserve positional continuity; shared tangents are not forced when
that would violate the geometry bound.

This changes display geometry only. The detector, temporal tracker, confidence,
presentation maturity and expiry, calibration guides, and TSR evidence consume
the original points. The protected speed-limit reference policy is unchanged.

The recorded-boundary parity check covers 2,637 boundaries: 28,090 original line
segments become 6,293 cubic segments, with identical Swift/Kotlin topology and a
maximum coordinate difference of `1.67e-16`. Five geometry tests pass in each
language, including whole-polyline error bounds, bends, discontinuities and
invalid input. The unsigned iPhone application build also passed.

Reproduction:

```sh
python3 scripts/lanes/verify_lane_curves.py \
  --input android/app/build/reports/road-path/drive-20260930-second/recording-1-path-frames.ndjson \
  --output-dir /absolute/path/to/new-evidence-directory
```

Private evidence remains in the ignored
`inspector/logs/2026-09-30-lane-shadow-review/bezier-native-parity/` directory.
`bezier-before-after.png` beside it compares both renderers over the same published
boundaries at video 14:00 and 21:00. It is an offline overlay comparison, not an
on-device screenshot or an accuracy improvement claim.

## Saved calibration is active

The latest drive used visual calibration revision
`a3537673-5303-40a3-beb0-af918dea136c`, with horizon y = 0.525 and upper-left
x = 0.43. Its 1920×1440 reference is compatible with the 1600×1200 live source
because orientation and aspect ratio match. The recorded TSR input region is
`[688, 0, 1600, 1200]`: a 912×1200 crop retaining the full image height.

The visual horizon determines the lane scan rows. The two drawn guides rank
already observed candidates with a bounded 15% preference; they cannot create
paint evidence. Detection still searches all image columns. For the TSR crop,
only the upper-left x coordinate is used. Sign boxes are mapped back into the
full image after inference. Both native implementations follow this behavior.

This visual mounting reference is separate from metric calibration. Camera
intrinsics plus the approximate mount profile are used for ground projection and
trajectory-based sign association in the shadow analysis. A saved visual profile
does not establish an accurate metric camera pose or a valid trajectory; all
1,082 associations in the reviewed recording remained unknown. See the
[startup review](TSR_STANDALONE_STARTUP_REVIEW_2026-09-30.md).

## Calibration and recognition cost

The TSR detector receives a fixed 1280×1280 tensor after letterboxing the crop.
It performs the same model computation despite the smaller source region.
The Android pipeline also converts the full camera image before cropping, so
this crop does not avoid full-frame conversion. Calibration focuses the image
region and changes the apparent scale of signs; it is not a proportional
reduction in detector computation.

Classification receives one fixed 224×224 crop per retained proposal. The region
can change the number of proposals, so total classification time may change in
either direction; per-invocation model work is unchanged. No matched calibration
enabled/disabled performance experiment was performed.

During the latest recorded drive, 1,713 sampled GPU inference diagnostics report:

| Stage | Median | p95 |
|---|---:|---:|
| Detector inference | 272.53 ms | 322.77 ms |
| Detector preprocessing | 23.74 ms | 37.65 ms |
| Full-frame conversion | 20.15 ms | 35.17 ms |
| Total recognition call | 330.01 ms | 473.17 ms |
| Classification per invocation, for 395 entries invoking it | 63.46 ms | 73.51 ms |

The classification row divides each entry's summed classifier inference time by
its invocation count. It is not a distribution of separately timed individual
calls. Total recognition timing excludes earlier frame conversion, and stage
medians must not be added to reconstruct another median. These are observations
with calibration enabled, not measured speedups caused by calibration.

The 16:9 encoded recordings used for the longer lane replay cannot safely reuse
the 4:3 live calibration without a verified transform. Offline replay therefore
supplies no visual/metric calibration or invented GPS and is explicitly separate
from evidence that the live app is using its saved calibration.

## Combined candidate validation

Build **10021** combines the standalone TSR camera-graph correction with the
Bézier display changes. The detector retains its baseline behavior after the
two unsuccessful lighting experiments; see the
[longer recording review](LANE_SHADOW_REVIEW_2026-09-30.md).

All **540 Android unit tests in 65 suites passed**, with zero failures, errors
or skips. Both debug APKs built successfully:

```sh
cd android
./gradlew --offline -PyouspeedBuildNumber=10021 \
  :app:testDebugUnitTest :app:assembleDebug :app:assembleDebugAndroidTest
```

The final unsigned iPhone application also built successfully with:

```sh
xcodebuild -project iphone/SpeedDBBench.xcodeproj -scheme SpeedConsumer \
  -configuration Debug -destination 'generic/platform=iOS' \
  -derivedDataPath /private/tmp/youspeed-lane-bezier-ios \
  CODE_SIGNING_ALLOWED=NO -hideShellScriptEnvironment build
```

Additional validation passed: 11 native Swift detector/preprocessor tests,
five native Swift Bézier tests, 26 shared boundary and 21 shared path fixtures
with Swift/Kotlin parity, Python tool compilation, and `git diff --check`.

APK SHA-256 values:

- App: `adb40f771e414449da5491261ff536fa98d94d5fb4e6fa1f6470e271fc732c45`
- Instrumentation: `48be59375b0ce6090853b3701bdef90b0a27c9e68c7562ecb588232a3161f9ec`

No application was installed or launched as part of these builds. The owner
subsequently approved installing build 10021, which passed the attached-device
camera-graph test and full-app standalone TSR, recording-stop and fresh-restart
checks on 2026-09-30. See the [device validation report](BUILD10021_DEVICE_VALIDATION_2026-09-30.md)
for timestamps, preserved media/preferences and limitations. This does not
establish improved lane accuracy or a mobile performance improvement.
