# Lane lighting evaluation — 2026-09-30

Follow-up: [preparation optimization and whole-track validation](LANE_PREPARATION_OPTIMIZATION_2026-09-30.md) retains output-preserving sampling/filter improvements; the separate accuracy gate was rejected.

The offline follow-up to [the research plan](LANE_LIGHTING_RESEARCH_2026-09-30.md)
**does not justify changing the production detector**. Local normalization helps
some sequences but loses existing paint support and admits incorrect roadside
curves. Border qualification suppresses much of that additional evidence but
provides no visible-coverage gain at the primary scoring tolerance. App logs also
show a separate preparation-budget problem worth addressing.

No app detector, model bundle, presentation threshold, evidence lifetime or
speed-limit reference policy was changed. No device installation was performed.

## What was run

Eight frozen native Swift variants each processed **7,663 frames**, comprising
4,172 frames from the latest recording and 3,491 from the earlier recording:
approximately **63 minutes 51 seconds**, sampled at 2 Hz. That is 61,304 frame
executions. Each run used the production temporal tracker, presentation gate,
operation cap and 50 ms preparation deadline. All variants started fresh at each
recording boundary and retained the actual encoded PTS.

The matrix is baseline, A, B and A+B, each with production top-hat5 or raw luma:

- **A:** additional rejected candidates require measured rising/falling borders,
  compatible local border slopes and widths, and corroborating borders at y±3.
  Width is an image-space bound, not a metric calibration. Raw bilateral contrast
  must be at least 26.
- **B:** additional candidates use the smaller raw center-to-shoulder residual,
  divided by the larger shoulder standard deviation with a floor of 6. Minimum
  raw contrast is 12, normalized score 2.5, center at least 40, shoulders at least
  18, and clipped center support is rejected. Strength remains continuous and is
  capped at 60. These are engineering parameters, not probabilities.
- **A+B:** both tests are required. Existing bright scores are preserved before
  suppression; added candidates can still change suppression and grouping.

Qualification always reads original luma, including in the top-hat variants.
The current cap of 24 sampled rows and 12 candidates per row remains. A checks
local width continuity across three neighboring image rows; it does **not** yet
supply width/tangent features to the native inter-row association stage. Experiment
C and learned models were not implemented in this evaluation.

The original 22 annotations are development data. Added **36 frames in six
contiguous sequences** cover dappled shade, worn paint/glare, bright open road,
guardrails, a shade-to-bright transition and a junction/truck shadow. Each sequence
contains six 2 Hz samples, about 2.5 seconds from first to last: only about 15
seconds of newly labelled span. The new labels are partial, with explicit
non-paint polygons; unlabelled detections are never automatically false positives.
Sharp bends and unmarked roads remain represented by the older sparse labels,
not new continuous validation sequences.

Labels were selected from original RGB before inspecting predictions. A visual
label-quality check corrected coarse coordinate errors; solid-stripe points used
RGB-only ridge snapping within nine display pixels of manually selected positions,
followed by visual inspection. Initial drafts and revised hashes are preserved.
The final label revision occurred while replays were running, before their scored
geometry was inspected; parameters were already frozen. These are analyst-reviewed
image-derived labels, not independently double-annotated ground truth. Neither
recording is an untouched drive-level holdout.

## Paint coverage

Values are covered / annotated paint-center pixels, at **three analysis pixels**
tolerance. “Visible” means published PAINT polylines after temporal/presentation
processing, not a raster of the final native Bézier display stroke.

| Variant | Development raw / 2,501 | Development visible / 2,501 | New sequences raw / 2,130 | New sequences visible / 2,130 |
|---|---:|---:|---:|---:|
| Current top-hat baseline | 1,363 | 796 | 1,473 | 733 |
| A + top-hat | 1,363 | 796 | 1,473 | 733 |
| B + top-hat | 1,341 | 802 | 1,481 | 817 |
| A+B + top-hat | 1,338 | 796 | 1,473 | 733 |
| Raw-luma baseline | 829 | 601 | 1,303 | 1,142 |
| A + raw | 829 | 601 | 1,303 | 1,142 |
| B + raw | 1,066 | 622 | 1,346 | 1,127 |
| A+B + raw | 875 | 607 | 1,303 | 1,142 |

The current baseline exactly reproduces the earlier 1,363 raw / 796 visible
covered development pixels. B+top-hat improves new-sequence visible coverage from
34.4% to 38.4%, **+3.94 percentage points**. On the three new shadow/transition
sequences alone it goes from 437/1,040 to 521/1,040, **+8.08 points**, exceeding the
research target in the aggregate but not consistently:

| New shadow sequence | Baseline visible | B+top-hat visible |
|---|---:|---:|
| Dappled shade, `latest-000601…606` | 151/490 | 297/490 |
| Worn paint/glare, `latest-002801…806` | 286/446 | 224/446 |
| Shade-to-bright dashes, `earlier-001401…406` | 0/104 | 0/104 |

A paired sequence bootstrap gives a descriptive 95% delta interval of **−13.9 to
+29.8 points** for those three sequences. With this tiny, reused-drive sample it
is not a population confidence claim. New bright-sequence coverage is unchanged
for B+top-hat; that does not establish bright-scene parity beyond these labels.

At one-pixel tolerance, B's new-sequence visible gain falls to **+1.41 points**
(570→600/2,130), and development coverage regresses (387→369/2,501). At five pixels,
the new-sequence gain is +3.90 points. Conclusions depend on the tolerance, so the
three-pixel score alone should not select a detector.

Raw luma improves the newly sampled solid-stripe sequences but loses **195**
visible covered development pixels versus production. Its stronger aggregate new
score is not sufficient to remove top-hat globally.

## False curves and continuity

Explicit negative polygons contain 120 raw response pixels for the current
baseline and 143 for B+top-hat on the new sequences. Both have zero **visible**
response pixels there. The older negatives have 39 versus 28 raw pixels and zero
visible pixels. These narrow polygons miss real false boundaries elsewhere.

Visual review of `earlier-003120` is decisive: B loses the baseline's visible
center marking and publishes a false PAINT curve along the roadside vegetation.
A+B retains the baseline behavior at that frame. The old `latest-002520` upper-hook
regression was not reintroduced in the inspected B/A+B comparison, but this does
not compensate for the other failure.

An explicitly **post-hoc**, eight-frame review of `earlier-003117…3124` finds
false visible roadside paint in baseline frames 3121–3122 and B frames 3120–3121.
Both span about **0.50 seconds between consecutive positive samples**; trapezoidal
sampled occupancy estimates are 1.016 and 1.000 seconds respectively. Thus this
window demonstrates changed false geometry and lost correct paint, **not an
increase in total false-visible duration**. The baseline itself has a semantic
false-paint problem. This post-hoc review is excluded from the frozen-label scores.

On the six new sequences, counting appearance/disappearance at 50% labelled-paint
coverage yields five transitions for production, three for B+top-hat and six for
raw luma. Only the four solid-stripe sequences support stable identity assessment:
production and B have no observed ID changes, while raw luma has two changes on
reappearance after gaps. Raw-luma gaps reacquire in roughly 0.50–0.53 seconds;
production/B provide no completed loss-and-recovery intervals in these short
windows. Several tails are censored. These measurements cannot establish general
flicker or reacquisition performance, especially between the sampled frames.

The B+top-hat diagnostic counters show 73,819 recovered candidate positions before
suppression, 19,579 after row selection and 5,218 recovered samples in eligible
tracks. A+B reduces these to 14,571, 3,308 and 1,625. These are **not labelled paint
counts** and must not be interpreted as accuracy or proven grouping losses.
Qualification is not sufficient evidence that a candidate represents paint.

## App logs and cost

The saved historical driving-runtime log contains 18,903 unique path-evidence
records; 18,883 have full geometry diagnostics. Those logged camera-analysis
frames are **288×216, 4:3**, unlike the **384×216, 16:9** video replay.

| Installed-app evidence | Historical driving log | Build 10021 stationary checks |
|---|---:|---:|
| Full geometry records | 18,883 | 411 |
| Preparation p50 / p95 | 16.40 / 41.90 ms | 10.49 / 19.63 ms |
| Preparation maximum | 128.58 ms | 77.37 ms |
| Geometry/preparation deadline failures | 640 (3.39%) | 11 (2.68%) |
| Positive live TSR inferences paired with those failures | 268 | 4 |

The 10021 audit deduplicates overlapping snapshots and starts after the cold-start
anchor at 12:55:15 UTC. It contains 413 distinct records, including two without
full geometry diagnostics; all 411 full records have empty boundary arrays.
The driving log spans multiple historical sessions/build states and is not a
controlled thermal test. Among 7,107 explicitly moving records (>1 m/s), 364
(5.12%) hit the geometry deadline; missing motion data remains unknown.

Driving-log sampling p95 is 19.17 ms, top-hat p95 10.43 ms and geometry p95 15.73 ms.
These quantiles must **not be added**: they need not occur on the same frames.
Android's `preprocessingMs` measures sampling separately from `laneFilterMs`;
subtracting the filter would be incorrect. `deadlineExceeded=false` is not proof
of successful lane preparation: `geometryDeadlineExceeded` and
`overlayPublicationSuppressionReason=geometry_budget` carry the relevant failure.

Host replay preparation p95 rises from 1.31 ms for production to approximately
2.01–2.02 ms for the top-hat experiments; raw controls range from 0.37 to 1.15 ms.
A+B/top-hat has one preparation-budget failure (maximum 62.34 ms); all other runs
have zero. The full run is retained, including that failure. These macOS timings
exclude decoding/sampling/camera delivery and do not predict Moto or iPhone costs.
No candidate was qualified on a phone, cold-start sequence or thermal soak.

## Decision and next experiments

1. **Do not promote A, B, A+B or raw-luma replacement from these results.** B's
   local gain is inconsistent and changes false roadside geometry. A/A+B add cost
   without a demonstrated visible gain at the primary tolerance.
2. **Investigate reducing preparation work with equivalent outputs.** The logs
   provide direct evidence for this opportunity. Profile sampling and top-hat on
   actual 4:3 camera inputs; require byte-equivalence for a pure optimization and
   measure complete preparation under TSR contention on both platforms.
3. **Treat semantic rejection/grouping as a separate research problem.** The
   bright guardrail sequence has zero labelled visible paint for every variant,
   and several raw tracks follow rail/vegetation. More contrast cannot distinguish
   those structures. The counters alone do not satisfy the research plan's
   condition that *verified paint* is being lost during grouping, so C was not
   claimed as validated or promoted. A next C trial needs labelled candidate
   correspondence, width/tangent-aware association and the false-verge sequence
   as a development control. A learned mask remains an independent comparison.
4. Before selecting another detector, obtain longer contiguous, independently
   reviewed labels and an untouched drive-level holdout. Include false verge/rail
   geometry, severe bends, dashed/worn paint and unmarked roads. The two already
   researched drives cannot provide that independence retroactively.

## Reproduction and preserved evidence

Private recordings, coordinates, labels, frames and binaries remain in ignored
`inspector/logs/2026-09-30-lane-lighting-evaluation/`. The main artifacts are
`dataset.json`, `annotations-development.json`, `annotations-new-sequences.json`,
`freeze-final.json`, `freeze-label-review.json`, `frozen-sources/`, `runs/`,
`scores-t{1,3,5}/scores.json`, `sequence-evaluation.json`, `log-audit-driving.json`,
`log-audit-build10021.json` and `posthoc-false-verge-review.json`. Original draft
labels and failed/smoke artifacts are retained and excluded from primary results.

Each run preserves source/input hashes and its frozen native executable. A disk
space failure interrupted A/raw; it was rerun from the same executable after
removing only this evaluation's rebuildable compiler caches. Partial output is
archived separately and excluded. Raw variants bypass preprocessing in their
frozen session sources; their inherited `filterIdentifier` constant still names
the production kernel, so use the variant and `experiment.json` input setting to
identify the actual experimental path.

New reusable offline tools:

- `scripts/lanes/make_lighting_experiment.py`: create an isolated native source
  snapshot (`--mode baseline|A|B|AB --input-kind raw|top-hat --output-dir NEW`).
- `scripts/lanes/LightingRecovery.swift`: frozen photometric/geometric hypothesis.
- `scripts/lanes/LightingRecoveryChecks.swift`: 21 synthetic assertions covering
  dim paint, missing borders, dark noise, clipping, diverging borders and budgets.
- `scripts/lanes/evaluate_lighting_sequences.py`: duration, coverage transitions,
  identity and uncertainty from frozen-label scores and native output.
- `scripts/lanes/audit_lane_runtime.py`: snapshot deduplication, explicit timestamp
  cutoff, motion strata, component timings and paired TSR evidence.
- `scripts/lanes/test_lighting_evaluation.py`: duration semantics, missing fields,
  Android timing semantics and fail-closed source-patch checks.

Use the existing [native replay and scoring instructions](../scripts/lanes/RECORDED_PIPELINE_REPLAY.md),
passing the generated directory as `--source-dir`. Repeat scores at tolerances
1, 3 and 5. The existing harness now exports optional `experimentDiagnostics`;
production baseline outputs receive null. Python scoring uses NumPy 2.2.6 and
OpenCV 5.0.0. All 21 native synthetic assertions and four Python evaluation tests
passed. Both production Swift/Kotlin detector files remain unchanged.
