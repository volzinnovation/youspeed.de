# Lane fragments and search bands — offline evaluation, 2026-10-01

**Keep the experimental search-band, fragment-grouping and fragment-tracking flags disabled by default.** Fragment-aware rendering reduces unsupported paint on the development keyframes, but the held-out clips reject promotion: the baseline finds 9 correct borders with 1 incorrect border; grouping finds 4 correct with 3 incorrect; grouping plus fragment tracking finds 6 correct with 2 incorrect. This is a small, manually inspected engineering sample, not a population accuracy estimate.

The calibration diagnostic works as intended on the actual saved iPhone profile: all 800 replayed exposures keep that profile weak, and 60 explicitly report a conflict with independently detected paint. The tests do not justify replacing the user's saved coordinates automatically.

[Four-arm held-out comparison video](../inspector/logs/2026-10-01-lane-fragments/heldout-ablation-review.mp4) · [Concrete wrong-side selection](../inspector/logs/2026-10-01-lane-fragments/heldout-comparison/holdout-dawn-dashed-0085.jpg) · [Machine-readable comparison](../inspector/logs/2026-10-01-lane-fragments/ablation-comparison.json).

## Inputs, separation and annotations

The corpus contains **2,200 development exposures and 400 held-out exposures**, sampled at a nominal 10 Hz and decoded to 384×216 grayscale. The actual encoded presentation timestamp is retained; some Android capture gaps make the cadence irregular. There are no duplicate exposure intervals between these sets. The original 800 previously reviewed day frames are development data, never held-out data.

| Source / split | Encoded intervals, seconds | Purpose |
| --- | --- | --- |
| Day / development | 25–45, 110–130, 145–165, 230–250, 285–305, 340–360, 430–450 | Unmarked access road, arrows/junction, dashed/solid paint, merge/chevrons, trucks |
| Dawn / development | 0–20, 110–130, 335–355, 550–570 | Curves, dashed paint, oncoming headlights, guardrail, village curbs, worn paint over repair seams |
| Day / held-out | 165–175, 310–320 | Post-junction separator and curved ramp/merge |
| Dawn / held-out | 200–210, 600–610 | Dashed border through bends, center-unmarked road with right-edge paint, guardrails/seams |

The clips come from two existing drives and mounts; these are exposure-level holdouts, **not independent drives**. The Android recording is dawn/twilight. **Full-night footage is unavailable, so night acceptance is incomplete.** The earlier “unmarked” sequence names are identifiers: closer inspection revealed worn center paint at 550–570 seconds and right-edge paint at 600–610 seconds. The labels reflect the visible paint, not the original names.

The iPhone source is 3840×2160 with its 180-degree MOV orientation honored. Its SHA-256 is `db92ae8297b5ea86753d7c15cff633207755428f65706dff383b99bf4793cfa7`. The Android source is 1280×720; SHA-256 `556e0ed4392e87638bd7f3b9e5cc55a55554c88c291d59d886fdeefd30de3486`. Both original files were preserved. [Corpus provenance and intervals](../inspector/logs/2026-10-01-lane-fragments/corpus/provenance.json).

**30 color keyframes were manually annotated by Codex through visual inspection:** 14 development frames containing 20 identifiable ego borders, and 16 held-out frames containing 27. Coordinates and paint intervals were finalized before inspecting experimental outputs; they are approximate visual labels, not independent human ground truth. The root agent also inspected the held-out annotation sheet. Model geometry and actual painted vertical intervals are labelled separately. Opposite road edges, arrows, chevrons, asphalt repairs and guardrails are excluded from ego-border truth. One ambiguous worn right edge has an explicit ignore region.

[Manual labels](../inspector/logs/2026-10-01-lane-fragments/corpus/manual-labels.json), [development annotation sheet](../inspector/logs/2026-10-01-lane-fragments/corpus/development-manual-labels.jpg), [held-out annotation sheet](../inspector/logs/2026-10-01-lane-fragments/corpus/heldout-manual-labels.jpg). Manual-label SHA-256: `bd59f83781f99a0ecce1d0dace70377cc382a5204a69ec789d018ea63f3f6638`.

An additional dense negative review inspected **all 200 exposures** from day 25–45 seconds at native analysis resolution, alongside color keyframes. The scored negative interval is conservatively **25–42 seconds, 170 frames, 16.998 seconds**. The final three seconds are excluded because junction paint starts entering the view. [Dense review sheets and exact scored input hashes](../inspector/logs/2026-10-01-lane-fragments/corpus/dense-negative-labels.json).

## Controlled comparison

The four primary arms use one frozen optimized Swift executable, the same preprocessor/brightness thresholds, the same pixels and timestamps, and the same calibration-diagnostic policy. Only `useSearchBands` and `groupFragments` change. All four have `fragmentTracking=false`. These image-only runs supply **no invented intrinsics, GPS, camera attitude or visual guides**. Thus they evaluate the implemented generic/temporal band behavior, not an accurately calibrated vehicle installation.

The fifth arm enables fragment-aware tracking with grouping on and bands off. It uses a later frozen build containing the endpoint-search fix. Its tracking-off control was compared against the primary grouping arm on all **2,200 development frames**: raw geometry, visible geometry, painted segments, IDs, presentation, reset reasons and work counts are exactly equal. [Control equivalence](../inspector/logs/2026-10-01-lane-fragments/tracking-control-equivalence.json).

Interim `dev-*` and `final-dev-baseline` outputs are superseded. Final four-arm outputs are `ablation-{dev,heldout}-{baseline,bands,fragments,both}`. Before this freeze, we repaired two evaluation problems: temporal fusion discarded painted-segment metadata; the replay paired visible track IDs using presentation-item order instead of the actual selected-boundary order. Both were corrected before the reported metrics. Final fifth-arm outputs are `tracking-{dev,heldout}-fragments`.

### Manually labelled border and paint correctness

A model matches at most one labelled border when mean horizontal error is ≤0.035 image width across a common vertical span ≥0.08. Matching is one-to-one. Painted-support scoring samples actual drawn segments by pixel arc length within y=0.58–0.95, with x tolerance 0.025 and paint-endpoint tolerance 0.015. It does not assume paint at one lower row. Legacy output draws the whole polyline; fragment output draws only `observedSegments`. The same contract is implemented by both renderers.

| Development: 14 frames, 20 true borders | Correct / incorrect / missed borders | Unsupported drawn paint length |
| --- | ---: | ---: |
| Baseline | 10 / 2 / 10 | 27.9% |
| Bands only | 9 / 2 / 11 | 29.5% |
| Fragments only | 10 / 1 / 10 | 15.8% |
| Bands + fragments | 9 / 1 / 11 | 17.3% |
| Fragments + fragment tracking | 10 / 1 / 10 | 15.8% |

| Held-out: 16 frames, 27 true borders | Correct / incorrect / missed borders | Unsupported drawn paint length |
| --- | ---: | ---: |
| Baseline | 9 / 1 / 18 | 25.6% |
| Bands only | 9 / 2 / 18 | 23.7% |
| Fragments only | 4 / 3 / 23 | 42.7% |
| Bands + fragments | 3 / 3 / 24 | 49.8% |
| Fragments + fragment tracking | 6 / 2 / 21 | 38.8% |

These fractions describe the length of output in labelled images; **they are not unsupported duration**. Sparse keyframes are not interpolated into unobserved truth. In the held-out day subset, baseline/grouping/tracking produce 5/2/2 correct borders; in dawn they produce 4/2/4. The small count cannot establish a general lighting effect.

The false positives are not merely annotation noise: [this held-out bend](../inspector/logs/2026-10-01-lane-fragments/heldout-comparison/holdout-dawn-dashed-0085.jpg) shows the grouped modes selecting the opposite road edge as an ego border. [This development example](../inspector/logs/2026-10-01-lane-fragments/dev-comparison/dawn-unmarked-guardrail-0030.jpg) shows a similar side error while the real right border is dropped. Green is manually labelled paint and red is the actual visible output.

### Unsupported duration on the densely reviewed negative interval

Any visible segment in the reviewed road region lacks painted ego-border support in this interval. Visibility is held only until the next sampled exposure, capped at 200 ms. This is a replay-duration estimate, not an assertion about every intervening sensor exposure or proof that an unpainted road edge is geometrically nonexistent.

| Arm | Frames showing unsupported paint / 170 | Unsupported visible duration | Longest continuous run |
| --- | ---: | ---: | ---: |
| Baseline | 6 | 0.60 s | 0.10 s |
| Bands only | 11 | 1.10 s | 0.30 s |
| Fragments only | 6 | 0.60 s | 0.30 s |
| Bands + fragments | 8 | 0.80 s | 0.30 s |
| Fragments + fragment tracking | 7 | 0.70 s | 0.30 s |

### Continuity and host performance

Identity counts use `(sequenceId, trackId)`; IDs cannot continue across deliberately separated clips. All arms render at most two borders. Identity-set changes include appearance/disappearance, so fewer unique IDs alone is not evidence of improved smoothness.

| Development, 2,200 frames | Frames with output | Visible IDs | Identity-set changes | p95 preparation, host |
| --- | ---: | ---: | ---: | ---: |
| Baseline | 1,257 | 99 | 562 | 0.74 ms |
| Bands only | 1,223 | 91 | 551 | 0.73 ms |
| Fragments only | 1,116 | 68 | 795 | 0.80 ms |
| Bands + fragments | 1,059 | 67 | 756 | 0.80 ms |
| Fragments + fragment tracking | 1,117 | 57 | 841 | 0.83 ms |

| Held-out, 400 frames | Frames with output | Visible IDs | Identity-set changes | p95 preparation, host |
| --- | ---: | ---: | ---: | ---: |
| Baseline | 237 | 28 | 148 | 0.73 ms |
| Bands only | 236 | 29 | 147 | 0.78 ms |
| Fragments only | 152 | 17 | 145 | 0.84 ms |
| Bands + fragments | 153 | 15 | 139 | 0.86 ms |
| Fragments + fragment tracking | 140 | 18 | 140 | 0.81 ms |

The p95 adjacent same-ID displacement on held-out frames is 3.75 / 3.89 / 2.67 / 3.18 / 2.73 analysis pixels in the table's arm order. **This is a proxy, not motion-corrected jitter:** it includes actual road/vehicle movement and changes which trajectories survive. True jitter requires dense geometric truth or independently validated motion compensation. Likewise, same-ID reappearance gaps are available in the JSON, but are not labelled border reacquisition latency. Sparse labels do not establish paint loss/return times; true reacquisition remains unmeasured.

The native host replay excludes camera, video decoding, sensor-luma sampling, encoding and screen work. Host timings do not establish device p95, memory or thermal acceptance. **50 ms remains an engineering target, never a result-discarding cutoff.** Bounded operation, evidence-age and thermal safeguards remain separate concerns.

## Actual saved-guide diagnostic

The separate 800-frame iPhone experiment supplies the exact saved visual profile, image size 3840×2160 and orientation `rear:exif:3`. Its revision `3497D603-7590-4575-A6BC-3A58D2249761` matches every one of the 4,953 logged live preview events. This establishes profile identity for the drive without inventing per-exposure intrinsics or GPS.

The latest diagnostic build reports:

- Weak guide state: **800 / 800**.
- Independent paint contradicts the guide: **60** exposures (`observed_border_conflict`).
- Not enough independent paint to verify it: **740** (`insufficient_independent_paint`).
- **400** independent broad audits without the guide and **400** exposures with a weak polyline prior only.

The previously reviewed left-shifted guide is therefore not admitted as a trusted ego divider. Insufficient evidence is not misreported as verified consistency. No saved coordinates were overwritten; an actual mount-specific calibration correction still requires a clear view and user calibration flow. [Guide summary](../inspector/logs/2026-10-01-lane-fragments/saved-guide-summary.json), [supplied profile and provenance](../inspector/logs/2026-10-01-lane-fragments/corpus/saved-guide-diagnostic.json).

## Platform parity and remaining acceptance

Eight recorded development images across all four detector configurations give **32 exactly equal Swift/Kotlin outputs**, including preprocessed pixel hashes, model geometry, paint fragments, confidence, rejection reasons, corridors and operation counts. Maximum numeric delta is zero. [Recorded detector parity report](../inspector/logs/2026-10-01-lane-fragments/detector-platform-parity/summary.json). This establishes detector parity for those cases, not full application/session parity on every frame.

| Requested measure | Current evidence |
| --- | --- |
| Manually labelled border correctness | 30 visually labelled keyframes; development and held-out reported separately |
| Unsupported visible duration | Dense 170-frame negative interval only; sparse-keyframe paint-length error separately |
| Identity changes | All 2,600 replay exposures, scoped by sequence |
| Jitter | Raw same-ID displacement proxy only; motion-corrected truth unavailable |
| Reacquisition | Same-ID gap proxy only; labelled paint-loss/return latency unavailable |
| p95 latency | Optimized macOS replay; sustained device results must be reported separately |
| Peak memory / thermal pause time | Not measurable from this host image-only replay; see device section below |
| Day/night acceptance | Day plus dawn/twilight; no full-night clip |
| Calibrated motion prediction | No metric intrinsics/GPS in these ablations; state/uncertainty unit checks do not replace drive acceptance |
| Shared speed-limit policy | No change required by this evaluation |

## Sustained devices

**Android completed; physical iPhone acceptance is still pending.** Both signed/debug test builds compile and build **10025** was installed on the attached Moto g86 5G and iPhone 14 Pro. The experimental flags remain disabled in normal app use; only the opt-in harness activates them.

On the Moto g86 5G (Android SDK 36), the harness ran **540 seconds / 5,399 frames**, in three sequential 180-second arms at a nominal 10 Hz. Each arm repeats the same 400 held-out exposures, resetting at sequence boundaries and loops. It measures luma copy, filtering, detection, tracking and presentation; file loading, integrity hashing and JSON writing are outside the processing timer. It does not start camera capture, TSR, dashcam recording or rendering, and it does not inject reconstructed GPS. Input-manifest SHA-256: `d7a4206c6b63345f1b31c979d2296b5b6d5749d4e5e3671902d5338d7dac97c7`.

| Android arm | Processed frames | p95 component processing | Maximum | Peak sampled process RSS | Frames above 50 ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| Baseline | 1,799 | 17.81 ms | 136.22 ms | 271.7 MiB | 2 |
| Fragments | 1,800 | 15.89 ms | 24.05 ms | 246.9 MiB | 0 |
| Fragments + tracking | 1,800 | 16.31 ms | 43.04 ms | 247.4 MiB | 0 |

There were **zero crashes, invalid selected indices, operation-budget failures or thermal pauses** in this run; all sampled thermal statuses were `NONE`. No frame selected more than two borders. The two baseline target misses were the first two exposures (136.22 and 86.90 ms); both retained four raw boundaries rather than being discarded at 50 ms. This is consistent with the target-only behavior. Arm order was fixed, without randomized warm-up, so lower later-arm latency or memory must not be presented as a controlled performance improvement.

RSS was sampled once per second (180 samples per arm): these are sampled whole-process peaks, not exact allocation peaks, an Android memory limit or evidence about concurrent camera/model/video memory. The full workload that previously reached thermal pause still needs a separate drive test.

The first **400 exposures in each arm, 1,200 total**, match the native Swift replay exactly: model geometry, actual paint segments, confidence, evidence ages, selected indices/IDs/sides, guide/calibration diagnostics and detector/temporal operation counts all have zero mismatches and zero numeric delta. There were no missing or paused first-cycle exposures. This allows the held-out image correctness results above to be applied to these identical Android outputs. It is **native macOS Swift versus physical Android**, not a completed physical iPhone run.

The iPhone test build and the same corpus were installed/transferred successfully, but Xcode reported `Unlock iPhone ... to Continue` and never launched the test. After waiting while Android completed, the queued launch was cancelled so it cannot start unexpectedly later. The test artifacts and private inputs are retained for an unlocked run. **No iPhone device latency, memory or thermal result is claimed.**

Validation also passed **570 Android unit tests**, **80 native Swift core tests**, both app/test builds, and the recorded detector comparisons. The Android test fixed a real endpoint-search defect: fragment tracking now refines three coarse patch candidates; the baseline still refines one. Brightness thresholds, patch acceptance and work caps were retained.

Evidence: [Android summary](../inspector/logs/2026-10-01-lane-fragments/android-device/lane_fragments_20261001.json), [Android per-frame data](../inspector/logs/2026-10-01-lane-fragments/android-device/lane_fragments_20261001.ndjson), [device/native semantic parity](../inspector/logs/2026-10-01-lane-fragments/android-native-parity.json), [build/source hashes](../inspector/logs/2026-10-01-lane-fragments/device-build-hashes.json), [iPhone access status](../inspector/logs/2026-10-01-lane-fragments/iphone-device-status.json).

See the [failure-mechanism analysis](LANE_FRAGMENT_IMPLEMENTATION_2026-10-01.md#validation-failure-held-out-fragment-mode) for the next detector experiment: preserve supported continuous borders, apply robust/piecewise fitting only to gap candidates, and distinguish ego borders from opposite road edges, gutters and guardrails. These reviewed holdouts must not become a repeatedly tuned acceptance set. Full-night clips, dense motion-corrected jitter/reacquisition labels, the unlocked iPhone run and sustained combined camera/TSR/recording tests remain open acceptance items.

## Frozen evidence and reproduction

All final outputs retain source snapshots, compiler settings, normalized input hashes and NDJSON results. Primary-arm [source manifest](../inspector/logs/2026-10-01-lane-fragments/ablation-dev-baseline/metadata.json), fifth-arm [source manifest](../inspector/logs/2026-10-01-lane-fragments/tracking-dev-control/metadata.json). The primary frozen detector SHA-256 is `dd4b7d25b6ae693705a29d30b7f85317ee91273258dedfa4d449ffb4d0f70298`; frozen replay runner SHA-256 is `18756221d6f2c6256cf46ecd5e0dbf8410e12fa812e37a019b292804ce04a597`. Full hashes, including the session and tracker, are in those manifests. The completed held-out video contains 400 frames, all decoded again successfully.

Example replay using the frozen four-arm build; choose a new output directory:

```sh
python3 scripts/lanes/replay_recorded_pipeline.py \
  --manifest inspector/logs/2026-10-01-lane-fragments/corpus/heldout.json \
  --source-dir inspector/logs/2026-10-01-lane-fragments/ablation-dev-baseline/sources \
  --reuse-build-dir inspector/logs/2026-10-01-lane-fragments/ablation-dev-baseline \
  --output-dir /private/tmp/lane-fragments-repeat \
  --preview-mode --group-fragments --variant fragments
```

Omit both experiment flags for baseline; add `--use-search-bands` for bands; combine both for the combined arm. Reusing a build fails if frozen source/compiler hashes differ. The fifth arm uses `tracking-dev-control` as its source/build directory and adds `--fragment-tracking`.

```sh
python3 scripts/lanes/evaluate_fragment_replay.py \
  --labels inspector/logs/2026-10-01-lane-fragments/corpus/manual-labels.json \
  --frames /private/tmp/lane-fragments-repeat/frames.ndjson \
  --output /private/tmp/lane-fragments-repeat/evaluation.json
```

For a development replay, also supply `--negative-intervals inspector/logs/2026-10-01-lane-fragments/corpus/dense-negative-labels.json`. The corpus extractor requires OpenCV/NumPy; evaluation is standard-library Python. Python scoring and parity regression tests pass, including separation of model geometry from paint support, one-to-one matching, no geometry extrapolation, causal metadata validation and hash-checked negative-duration scoring.

Retain diagnostics and the weak-guide safeguard. Keep experiments opt-in while investigating opposite-edge selection and losses introduced by fragment-aware admission. The held-out outputs now constitute reviewed development evidence for any subsequent tuning; obtain new unseen clips before the next acceptance decision.
