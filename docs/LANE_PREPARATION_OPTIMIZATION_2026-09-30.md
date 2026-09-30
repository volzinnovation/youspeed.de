# Lane preparation optimization — 2026-09-30

The sampling and filtering optimizations are implemented for Android and iPhone
in the working tree. They preserve the tested lane outputs and reduce preparation
cost in a paired Moto benchmark. **They have not been installed in either app.**
A separate whole-track paint-verification experiment regressed accuracy and remains
offline only.

This follows the [lighting evaluation](LANE_LIGHTING_EVALUATION_2026-09-30.md).
The historical 3.39% preparation-failure rate has **not** been remeasured with the
optimized live app; the component benchmark cannot establish its new value.

## Retained implementation

**Sample source coordinates once per camera geometry.** Both clients cache one
immutable plan containing a source offset for each output column and row. The
inner sampling loop performs integer offset addition and a byte read, preserving
the original pixel-center formula. The key includes source/output dimensions,
rotation, row stride and pixel stride. Android adds the current ByteBuffer position
on every call; Swift uses the currently locked pixel-buffer pointer. Neither cache
retains a camera buffer. Concurrent callers retain their own immutable plan even
if another call replaces the cached plan.

**Enhance only rows read by detection.** A shared row-selection helper supplies the
same calibrated sample centers to the detector and top-hat filter. At most 24
centers need three neighboring rows each: at most 72 of 216 rows rather than all
216. Overlapping support rows are computed once. The five-pixel horizontal opening,
1.5× saturated enhancement, rounding and borders are unchanged.

Sampled raw luma is byte-identical. Filtered pixels on every detector support row
are byte-identical; unused filtered rows are explicitly zero and must not be used
as a general-purpose enhanced image. The original full-image filter API remains
available for tests and offline controls. Temporal tracking continues to receive
original luma, never the sparse filtered buffer. No detector threshold, association
rule, presentation gate, operation cap, preparation deadline or speed-reference
policy was relaxed.

Production paths changed:

- Android: `LaneDetectionRuntime.kt`, `RoadPathLaneFilter.kt`,
  `RoadBoundaryDetector.kt`, `RoadPathSession.kt`.
- iPhone: `RoadBoundaryDetector.swift`, `RoadPathSession.swift`.

## Correctness and build checks

- **7,663 recorded frames match exactly** against the pre-change production
  baseline: raw/visible boundaries, confidence/support/provenance, corridors,
  operation counts, temporal diagnostics, presentation IDs/states, publication
  decisions and deadline flags. Inputs and output files are hashed.
- **26 boundary and 21 path fixtures** retain Swift/Kotlin parity within 1e-9.
- Both platforms test **72 sampler cases** covering all four rotations, odd and
  even source dimensions, pixel stride 1/2, padded row strides, changed buffer
  starting positions, and repeated cached use.
- Both platforms test **28 sparse-filter cases** spanning different image sizes,
  absent/invalid/clamped/calibrated horizons, exact support-row bytes and complete
  detector output equality. Cancellation remains covered.
- **44 focused Android unit tests** passed: sampler/runtime, preparation, detector
  and path-session tests. **46 Swift host tests** passed, including detector,
  sampler, session, temporal tracker, presentation and motion controls.
- The **iOS device-target Debug build succeeded**, with signing disabled and no
  installation. The physical iPhone was unavailable through CoreDevice, so no
  iPhone performance claim is made.

The native video replay measures filtering onward, not camera sampling. Its host
preparation p50/p95 changes from 1.02/1.31 ms to 0.61/0.91 ms, with zero preparation
failures in both runs. Wall-clock maxima are noisy; the optimized host maximum was
7.55 ms versus 1.56 ms in the earlier baseline run. These separate host runs are
correctness evidence and indicative cost measurements, not a paired latency trial.

## Paired Moto benchmark

A standalone ART executable ran the pre-change and optimized preparation pipelines
in the same process on the attached **Moto g86 5G**, alternating their execution
order. It ran for 60 seconds and produced **7,149 measured samples per variant**,
plus 30 warm-up samples each. It used two original decoded 1280×720 luma fixtures
and a synthetic 1920×1440, rotation-180 fixture sampled at the live 288×216 geometry.
The images repeat; this is not a replay of a continuous drive.

Before timing, twelve paired exposures asserted exact luma, geometry and
presentation equality using fixed clocks. Timed runs use the real 50 ms deadline
and include luma-output allocation/copy, filtering, detection, temporal tracking
and presentation preparation. They exclude camera delivery/metadata retrieval,
TSR inference, recording, GNSS, app UI and post-TSR association. The standalone
Kotlin/D8 build is not the installed application's optimized APK.

| Measured warm preparation | Baseline | Optimized |
|---|---:|---:|
| Median wall time | 5.04 ms | **2.95 ms** |
| p95 wall time | 6.14 ms | **3.88 ms** |
| Maximum wall time | 18.26 ms | 16.99 ms |
| Median thread CPU time | 4.99 ms | 2.92 ms |
| Median sampling time | 1.52 ms | 0.89 ms |
| Median filter time | 2.16 ms | 0.77 ms |
| Preparation-budget failures | 0/7,149 | 0/7,149 |

Median preparation is **41.5% lower**, and p95 is **36.8% lower** in this controlled
run. Component quantiles should not be added. The similar CPU-time reduction
supports a computation saving rather than merely a favorable scheduling interval.
Android thermal status was 1 (light throttling) both before and after; a one-minute
run does not establish sustained thermal behavior under the full app workload.
The VM was warmed by correctness checks before timing, so the first timing samples
are session-cold, **not application/process cold starts**.

Both versions had ample headroom here. This proves a local cost reduction, not
elimination of the historical failures under camera/model/recording contention.
No installed app or saved preferences/media were changed. Temporary benchmark
files were removed from the phone after preserving them and all results locally.

## Rejected accuracy experiment

The separate hypothesis checked **every completed PAINT track**, including existing
bright detections, against original luma. It reused the previous bilateral contrast
and measured border tests, requiring at least four supported rows and 40% of a
track's observations to pass. Passing tracks kept their existing confidence;
failing tracks were rejected before final boundary selection. Parameters were
frozen before scoring. No normalization-recovery candidate was added.

The experiment used the pre-optimization baseline source to isolate the accuracy
change. All 7,663 frames were replayed with zero geometry/sidecar deadline failures.
All 58 annotation frames are now reused development evidence; none constitutes an
untouched holdout.

| Partial paint coverage, three-pixel tolerance | Baseline | Whole-track verifier |
|---|---:|---:|
| Older 22 labels: raw | 1,363/2,501 | 542/2,501 |
| Older 22 labels: visible | 796/2,501 | **330/2,501** |
| Newer 36 labels: raw | 1,473/2,130 | 863/2,130 |
| Newer 36 labels: visible | 733/2,130 | **377/2,130** |

Raw response in explicit non-paint regions fell from 159 pixels to zero, but the
loss of genuine labelled paint is unacceptable. Visible response in those limited
negative regions was already zero for the baseline. The result shows that this
border-consensus rule cannot yet separate paint from background reliably enough
for a hard track gate. It is retained only as a reproducible rejected experiment;
thresholds were not softened to fit these labels.

## Remaining validation

The next release/device-installation step needs a paired **full-app** test with
actual live 4:3 inputs, TSR enabled, movie start/stop, cold starts and a longer
thermal run. Measure preparation deadline failures and reacquisition, not just
median component time. The iPhone needs to be connected for equivalent device
measurements. No installation, publishing, merge or branch deletion occurred.

Further accuracy work should investigate candidate correspondence/grouping or an
independent learned paint mask. This experiment does not support using the current
border score as a hard semantic veto. Raw/enhanced agreement as a grouping feature
has not been tested in this follow-up.

## Reproduction and local evidence

Ignored private evidence is under
`inspector/logs/2026-09-30-lane-preparation-optimization/`:

- `baseline/`: pre-change source snapshots and hashes.
- `replay/`, `exact-replay-comparison.json`, `native-parity.json`: frozen optimized
  Swift replay and exact comparison to the earlier baseline.
- `android-tests.log`, `swift-tests.log`, `iphone-build.log`: validation logs.
- `moto-benchmark-v2/`, `moto-inputs/`, `moto-paired.ndjson`, `moto-summary.json`,
  `moto-thermal-{before,after}.txt`: native benchmark sources/binaries, hashed input
  fixtures, paired timings and device thermal snapshots.
- `track-verifier-sources/`, `track-verifier-replay/`, `track-verifier-scores/`:
  frozen rejected accuracy trial.

The benchmark is built with `scripts/lanes/build_preparation_benchmark.py` and
`scripts/lanes/PreparationBenchmark.kt`. The builder requires a saved pre-change
Android source directory, an output directory and an Android SDK path; it performs
no deployment. Its run needs a manifest of raw camera-plane files and a bounded
duration, and produces timing NDJSON. The actual tested frozen source snapshots
remain authoritative if the build helper later evolves.

`scripts/lanes/make_track_verification_experiment.py` builds the offline verifier
snapshot from a supplied pre-optimization Swift source directory. Run it with the
existing native replay/scoring tools. `make_lighting_experiment.py` now recognizes
both the original full-image and new row-selective preprocessing call, failing
closed on an unknown or ambiguous source version.
