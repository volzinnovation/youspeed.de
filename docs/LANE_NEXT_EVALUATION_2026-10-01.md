# Lane follow-up evaluation — 2026-10-01

**Keep additive grouping, tentative-identity retention, joint corridor selection and combined fragment tracking disabled in the normal app.** The new tentative-identity path improves correctness on the fresh labelled sample, but also increases unsupported output on the densely reviewed unmarked road. Combining the changes increases false output further. The independent capture-ownership and cadence changes require their own validation; these image-pipeline results do not establish their device behavior.

The prior [fragment evaluation](LANE_FRAGMENT_EVALUATION_2026-10-01.md) is development evidence for this round. Implementation is tracked in [the implementation report](LANE_NEXT_IMPLEMENTATION_2026-10-01.md); later physical results and verified-backup cleanup are in [the device validation record](LANE_DEVICE_VALIDATION_2026-10-01.md). Android's stationary cadence improvement does not change the experimental image-selection activation decision below.

[Six-arm comparison video](../inspector/logs/2026-10-01-lane-next/heldout-review.mp4) · [Fresh annotations](../inspector/logs/2026-10-01-lane-next/corpus/heldout-manual-labels.jpg) · [Full metrics](../inspector/logs/2026-10-01-lane-next/ablation-comparison.json).

## Freeze and data separation

The prechange Swift/Kotlin sources were frozen before implementation under `inspector/logs/2026-10-01-lane-next/baseline-{swift,kotlin}`. After detector, gate and session tests passed, the evaluation compiled one new optimized Swift executable and reused that exact executable for every new arm and split. No threshold tuning followed fresh held-out results.

**P0 equivalence is exact on all 2,600 development frames.** The frozen prechange pipeline and the new pipeline with every new option disabled have zero differences in raw boundaries, visible boundaries including paint fragments, track IDs, selected indices, temporal resets, corridors, operation counts and geometry-budget state. Timing and added diagnostic fields are excluded from this semantic comparison. [Equivalence evidence](../inspector/logs/2026-10-01-lane-next/p0-equivalence.json).

The old 2,600 exposures, including the previously reviewed 400 held-out exposures, are now **development data**. Their 30 manual labels contain 47 border instances. We retained the original grayscale files by reference rather than duplicating videos or frames.

A fresh **400-frame, 40-second** set was selected and frozen before viewing new model output:

| Source | Fresh interval | Inspected scene |
| --- | ---: | --- |
| iPhone, day | 10–20 s | Unmarked parking/access road, curbs, paving and wipers |
| iPhone, day | 180–190 s | Dashed left separator and solid right border |
| Android, dawn | 240–250 s | Dashed/solid dividers through sharp bends; directional arrows |
| Android, dawn | 480–490 s | Worn paint, center-unmarked sections, entrance and guardrail |

These intervals are disjoint from every earlier corpus interval. They remain from the same two recordings, mounts and routes, so this is an **exposure-level holdout, not an independent-drive test**. Android illumination is dawn/twilight; no full-night footage is available. The `fresh-dawn-village` sequence name was assigned before inspection; the actual scene is a country road and entrance.

All exposures retain actual encoded timestamps and input SHA-256 hashes. Nominal sampling is 10 Hz, but recorded Android gaps produce irregular intervals. iPhone MOV orientation is honored before center-sampling 384×216 grayscale. This is decoded BGR-to-gray, not original camera Y. No GPS, metric intrinsics, invented lane counts or visual calibration profiles enter these six arms.

[Corpus configuration and exclusions](../inspector/logs/2026-10-01-lane-next/corpus-config.json), [provenance](../inspector/logs/2026-10-01-lane-next/corpus/provenance.json), [unique-frame and split checks](../inspector/logs/2026-10-01-lane-next/corpus/validation.json).

## Manual truth and its limits

The fresh set has **16 manually inspected color keyframes with 21 labelled border instances**. These are visual annotations by Codex, audited by the root agent, not independent human ground truth. Coordinates are approximate. Geometry and actual painted intervals are separate; arrows, opposite road edges, asphalt repairs, guardrails, paving and curbs are not labelled as painted ego borders.

Before any fresh replay, the annotation audit questioned the worn right edges at 481 and 483.5 seconds. Native 1280×720 crops decoded at the exact recorded PTS confirmed short white paint fragments. Their painted intervals were trimmed to y=0.615–0.750 and y=0.633–0.757; the ambiguous faded lower edges were marked ignored. An ambiguous potential center marking at 486 seconds is also ignored. These corrections preceded model-output review. [Native recheck timestamps](../inspector/logs/2026-10-01-lane-next/corpus/annotation-images/native-recheck.json), [first crop](../inspector/logs/2026-10-01-lane-next/corpus/annotation-images/fresh-dawn-village-0010-right-crop.png), [second crop](../inspector/logs/2026-10-01-lane-next/corpus/annotation-images/fresh-dawn-village-0035-right-crop.png).

Fresh label SHA-256: `6decf0bd170cf17229d0fdc32fbb1533ac334dfc91b6589c23e9f2eec16c532e`. [Frozen labels](../inspector/logs/2026-10-01-lane-next/corpus/heldout-labels.json).

All **100 exposures from day 10–20 seconds** were additionally inspected in five dense sheets at native analysis resolution, with color keyframes for context. This full interval contains no painted ego borders in the scored road region. Wipers and paving remain negative cases. [Dense negative labels and per-input hashes](../inspector/logs/2026-10-01-lane-next/corpus/heldout-negative-labels.json).

The same scoring rules as the first evaluation are retained: one-to-one border matching, mean horizontal error ≤0.035 normalized image width across shared vertical span ≥0.08; actual drawn-paint length sampled within y=0.58–0.95, with horizontal tolerance 0.025 and endpoint tolerance 0.015. No fixed lower row is required. Paint metrics follow the renderer: nonempty `observedSegments` are drawn separately; otherwise legacy polyline points are drawn. Sparse labels are not interpolated through time.

## Arms

Brightness/preprocessing thresholds, input bytes, timestamps and compiler settings are fixed. Search bands remain disabled in every arm.

| Arm | Enabled changes |
| --- | --- |
| P0 | All experimental options off |
| Group | Corrected additive fragment grouping only |
| Tentative | Tentative-identity retention only |
| Joint | Joint corridor selection only |
| Combined | Group + tentative + joint |
| Tracking | Combined + fragment-aware tracking |

The standalone joint arm tests the image-only fallback because no trusted camera/motion metadata or directional lane count is supplied. Its result does not validate a fully calibrated road-graph prior.

## Border and painted-support correctness

Counts below are border instances in the labelled images, not counts of distinct physical roads or statistically independent examples. Unsupported length is the fraction of drawn paint length unsupported by those labels; it is **not duration**.

| Development: 30 frames, 47 border instances | Correct | Incorrect | Missed | Unsupported drawn length |
| --- | ---: | ---: | ---: | ---: |
| P0 | 19 | 3 | 28 | 26.9% |
| Group | 20 | 1 | 27 | 19.3% |
| Tentative | 20 | 4 | 27 | 28.8% |
| Joint | 19 | 4 | 28 | 30.4% |
| Combined | 21 | 5 | 26 | 32.8% |
| Tracking | 23 | 5 | 24 | 29.0% |

| Fresh held-out: 16 frames, 21 border instances | Correct | Incorrect | Missed | Unsupported drawn length |
| --- | ---: | ---: | ---: | ---: |
| P0 | 5 | 2 | 16 | 33.2% |
| Group | 5 | 3 | 16 | 42.5% |
| Tentative | 9 | 2 | 12 | 29.6% |
| Joint | 5 | 2 | 16 | 33.2% |
| Combined | 9 | 3 | 12 | 34.1% |
| Tracking | 8 | 2 | 13 | 28.0% |

Tentative retention improves the fresh sample's precision from 5/7 to 9/11 and recall from 5/21 to 9/21. This promising result is insufficient for promotion because the dense negative interval exposes additional unsupported output that sparse labels alone miss. Grouping's development improvement does not generalize to the fresh sample. Joint selection provides no fresh labelled gain and adds one incorrect development border.

## Unsupported duration on dense negatives

Each result is held only until the next reviewed replay exposure, capped at 200 ms. This estimates rendered replay duration; it does not claim knowledge of every intervening sensor exposure. The old development negative interval is approximately 17 seconds; the fresh negative interval is 10 seconds. Comparisons are within each interval.

| Arm | Development unsupported duration | Fresh unsupported duration | Fresh longest continuous run |
| --- | ---: | ---: | ---: |
| P0 | 0.60 s | 0.20 s | 0.10 s |
| Group | 1.00 s | 1.20 s | 0.40 s |
| Tentative | 1.30 s | 0.80 s | 0.10 s |
| Joint | 0.60 s | 0.20 s | 0.10 s |
| Combined | 2.60 s | 2.30 s | 0.70 s |
| Tracking | 2.50 s | 2.10 s | 0.40 s |

The combined path increases unsupported fresh output by 2.1 seconds and extends its longest continuous run from 0.1 to 0.7 seconds. Keeping a track identity cannot be treated as evidence that the underlying paint is valid.

## Continuity and host cost

Track IDs are scoped by sequence. Identity-set changes include appearance/disappearance; they are not exclusively identity switches between continuously visible true borders. Every arm retained the two-visible-border limit.

| Development: 2,600 frames | Frames with output | Visible IDs | Identity-set changes | Host p95 preparation |
| --- | ---: | ---: | ---: | ---: |
| P0 | 1,494 | 127 | 710 | 0.73 ms |
| Group | 1,534 | 135 | 799 | 0.79 ms |
| Tentative | 1,669 | 257 | 946 | 0.73 ms |
| Joint | 1,485 | 128 | 753 | 0.74 ms |
| Combined | 1,743 | 311 | 1,072 | 0.78 ms |
| Tracking | 1,700 | 327 | 1,136 | 0.83 ms |

| Fresh held-out: 400 frames | Frames with output | Visible IDs | Identity-set changes | Host p95 preparation |
| --- | ---: | ---: | ---: | ---: |
| P0 | 202 | 23 | 121 | 0.72 ms |
| Group | 215 | 30 | 137 | 0.79 ms |
| Tentative | 228 | 44 | 158 | 0.72 ms |
| Joint | 198 | 25 | 131 | 0.70 ms |
| Combined | 248 | 52 | 182 | 0.81 ms |
| Tracking | 234 | 58 | 182 | 0.81 ms |

Greater output availability comes with more visible identities and appearance/disappearance changes. This does not establish smoother lane output.

Fresh p95 same-ID horizontal displacement is 3.76 / 3.90 / 3.53 / 3.76 / 3.95 / 3.90 analysis pixels in arm order. This includes real vehicle/road movement and different surviving track populations; **it is not motion-corrected jitter**. Same-ID reappearance gaps are also recorded, but sparse truth cannot establish actual paint-loss/return times, so they are not ground-truth reacquisition latency.

The host runs use optimized Swift and exclude decoding, original luma sampling, camera queues, TSR inference, recording and screen rendering. They cannot validate on-device p95, memory peaks or thermal pause time. **50 ms is an engineering target, not a cutoff for discarding current evidence.** Operation limits, evidence age and thermal guards remain independent.

## Acceptance decision and missing measurements

Keep all six-arm experimental options off in the normal app. The existing baseline behavior is preserved exactly when those options are disabled. The labels support further investigation of tentative retention, but its additional unsupported duration must be addressed before activation. No parameters were changed in response to this fresh holdout; it is now reviewed development evidence for any future tuning.

| Requested measurement | Evidence / remaining limitation |
| --- | --- |
| Border correctness | 30 development and 16 fresh manually labelled keyframes; approximate visual truth |
| Unsupported visible duration | Dense old 17-second and fresh 10-second negative intervals |
| Identity changes | All 3,000 replay exposures, scoped by sequence |
| Jitter | Raw displacement proxy only; motion-corrected truth unavailable |
| Reacquisition | Same-ID gap proxy only; labelled loss/return latency unavailable |
| p95 latency | Optimized host core only; device/camera workload separately required |
| Peak memory and thermal pauses | Not measured by this image-only host replay |
| Full-night acceptance | Unavailable; current low-light footage is dawn/twilight |
| Calibrated speed/road-graph narrowing | No metric/GPS/count metadata in these arms; no counts invented |
| Swift/Kotlin runtime parity | Exact agreement on 600 host-replayed frame/arm pairs; device performance remains separate |
| Sustained devices | Android candidate passed 600.919 seconds; iPhone 10028 remains incomplete after foreground/background camera interruptions. See the device validation report. |

## Evidence and reproduction

The final shared build is `inspector/logs/2026-10-01-lane-next/dev-p0/`; each `dev-*` and `heldout-*` directory contains source snapshots, input/byte hashes, metadata, archived NDJSON output, summary and evaluation JSON. [Frozen build metadata](../inspector/logs/2026-10-01-lane-next/dev-p0/metadata.json).

Swift/macOS and Kotlin/JVM agree exactly on **600 recorded frame/arm pairs**, 100 per arm from five development sequences. Comparison includes raw and selected geometry, actual painted segments, IDs, expired identities, selection decisions, calibration/rejection diagnostics and operation counts. Maximum numeric delta is zero. This validates bounded core semantics, not physical-device performance or recognition accuracy. [Recorded parity evidence](../inspector/logs/2026-10-01-lane-next/host-parity/summary.json).

Completed replay outputs are stored as `frames.ndjson.gz`. All 13 archives were decompressed and checked against their original SHA-256 before removing the redundant uncompressed file, reclaiming 245,671,945 bytes. The [compression manifest](../inspector/logs/2026-10-01-lane-next/compression-manifest.json) retains both content and archive hashes. Scoring and rendering accept either format; `replaySha256` always refers to uncompressed NDJSON bytes. Original recordings, labels, input frames and frozen sources are unchanged.

Key frozen SHA-256 values:

- Detector: `4f9f84ee241f12ea38e992c0d4b8e47965d67a882d8c1c25f525382013e5ca51`.
- Gate/selector: `85d1366e463c3764d018a753303c0ed404189b5936a73f2e53626dadcada1fdc`.
- Session: `02697cf432a5ec83424cd5812bf3bca58e9159e08595e685f0ef07ed066f5b3a`.
- Replay runner: `f12ecd455bdab5962eed584153a52cfaf029c12a5a846007860abe359df7109a`.

Example, using a new output directory:

```sh
python3 scripts/lanes/replay_recorded_pipeline.py \
  --manifest inspector/logs/2026-10-01-lane-next/corpus/heldout.json \
  --source-dir inspector/logs/2026-10-01-lane-next/dev-p0/sources \
  --reuse-build-dir inspector/logs/2026-10-01-lane-next/dev-p0 \
  --output-dir /private/tmp/lane-next-repeat \
  --preview-mode --retain-tentative-identity --variant tentative
```

Use no experiment flags for P0; `--group-fragments` for grouping; `--joint-selection` for joint selection; all three for Combined; add `--fragment-tracking` for Tracking. Reuse is rejected when the source/compiler hashes differ.

```sh
/opt/homebrew/bin/python3.9 scripts/lanes/evaluate_fragment_replay.py \
  --labels inspector/logs/2026-10-01-lane-next/corpus/heldout-labels.json \
  --negative-intervals inspector/logs/2026-10-01-lane-next/corpus/heldout-negative-labels.json \
  --frames /private/tmp/lane-next-repeat/frames.ndjson \
  --output /private/tmp/lane-next-repeat/evaluation.json
```

To rescore an existing archive, pass `--frames inspector/logs/2026-10-01-lane-next/heldout-p0/frames.ndjson.gz` instead. Rescoring that archive with the original Python 3.9 runtime reproduced its saved evaluation exactly, including the content hash. [Archive rescore verification](../inspector/logs/2026-10-01-lane-next/archive-rescore-verification.json).

Sixteen Python regression tests passed with `/opt/homebrew/bin/python3.9 -m unittest discover -s scripts/lanes -p 'test_*.py'`; [saved test log](../inspector/logs/2026-10-01-lane-next/python-tests.log). Offline extraction and rendering used the existing OpenCV/NumPy installation without duplicating or deleting source recordings. Subsequent user-authorized device cleanup is documented separately and preserves verified local originals.
