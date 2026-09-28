# Recommended next implementation: selective exit-sign filtering

**Build a map-scoped filter for individual sign candidates, using the main
carriageway boundary and exit separators. Keep the detector's full image.**
Use the 200 ms allowance as an **added decision budget**, as clarified by the
product owner. Start with cached map intervals and existing physical tracks;
add a small visual geometry stage only around relevant exits/service entrances.

The follow-up [camera alignment and path-geometry design](TSR_CAMERA_ALIGNMENT_AND_PATH_GEOMETRY_2026-09-28.md)
identifies reusable lane-runtime code, distinguishes Haar-like stripe detection
from trained cascades, and specifies the three-axis mounting aid. The new unmarked
Swiss junction with simultaneous main-road 50 / side-road 30 extends the evaluation
beyond motorway paint and right-hand exits.

The previous 12-image experiment tested visible signpost feet. Its all-unknown
result rules out relying on that particular cue on these images. It did not test
painted separation areas, supplementary arrows, or sign-centre motion. We have
enough evidence to implement and compare those alternatives without another
France drive. The remaining qualification work determines rollout, not whether
we can start the implementation.

## Decision on the two proposals

| Proposal | Recommendation | Reason from the app and images |
| --- | --- | --- |
| Keep only signs immediately right of the camera's lane | Do not use this crop | Valid motorway signs can stand beyond other mainline lanes, on the left, or overhead. Exit signs also stand immediately beside a drivable road. |
| Use lane markers to identify the whole main carriageway and diverging branch | Implement as a candidate-association feature | Five reviewed false-sign views show a clear painted split. The ramp-positive has the split on the camera's left and a valid 70 on its right: camera-side/path association is essential. |
| Disable all vision from 100 m before to 100 m after an exit | Keep as an offline comparison, not the default | It covers the Brouck still location in a spatial counterfactual with fresh, correct context; the recorded stale context would not activate this guard. It would also hide a genuine mainline limit encountered within the interval, as illustrated by the synthetic controls. It needs immediate release when the vehicle enters the ramp. |
| Apply a selective sign filter in an exact directed exit interval | First implementation | Cheap map math, precise scope, preserves unrelated genuine signs, and avoids a whole-way blackout. |

The 200 m proposal is interpreted as **−100 m to +100 m** around the departure.
Starting 100 m before and continuing 200 m after would instead cover 300 m.
Use the existing roughly 350 m upstream lookahead to prepare/cache visual context;
it is not a reason to suppress signs throughout those 350 m. A sign may be visible
before the smaller interval, so also evaluate candidate visibility and retain a
verified branch track across the interval boundary. Do not assume these distances
are already optimal.

## Concrete first version

1. **Generate precise exit intervals.** Retain original OSM junction-node identity
   and direction, including internal-way departures and motorway service-area
   entrances. Store offsets along each affected mainline way, crossing way splits
   where necessary. Keep entry ramps, emergency access, opposite carriageways and
   nearby unconnected roads separate. In the real Brouck extract the mainline way
   is about **4,594 m** long; marking its entire ID would obscure kilometres rather
   than 200 m. The A75 approach ways can be only 61–97 m long, so a single-way flag
   can also cover too little.
2. **Cache the encounter on location updates.** Supply exit ID, mainline/ramp role,
   signed distance and uncertainty to the camera batch. Keep the original fix time;
   account for progress only with explicit motion/uncertainty, never by silently
   refreshing a stale fix. Correct the observed location cadence/timing defect.
   Release the mainline guard when the actual ramp becomes the current road.
3. **Find separation, not a fixed screen column.** On a low-resolution lower-image
   view, estimate the whole carriageway, diverging line, painted triangle/chevrons
   and separate pavement. Preserve camera pose/projection and confidence. A simple
   white-line/edge/curve estimator is the cheap first candidate; a compact lane or
   road-segmentation model is the separate alternative if it fails on shadows,
   curves, faded paint or night images. A barrier alone is insufficient: the valid
   ramp 70 is also behind a guardrail. A sign centre is not a ground point; do not
   compare its elevated image row directly with a lane boundary at road level.
4. **Associate each sign with the current road or branch.** Combine the separating
   structure, camera-side/path evidence, sign/post observations and existing track
   history. For strong branch evidence while continuing on the mainline, withhold
   that candidate from display, speed override and passage. Preserve the raw
   proposal as observed. A rejected or unprocessed proposal must never become
   artificial visual absence that finalizes a passage. Paired, left and overhead
   mainline signs remain visible and receive their own association; they are not
   swept into the branch mask. Conflicting cues remain unresolved. Two-dimensional
   overlap alone is not a proven legal road assignment.
5. **Make disregard last through the same exit encounter.** The current dismissal
   gate remembers track IDs and a timestamp cutoff. A later physical sign or
   re-created track can still arrive. Retain a rejected branch/encounter relation
   so its later 70→50→30 signs cannot immediately reassert camera authority. Scope
   this to that branch, traversal and bounded interval; genuine mainline signs
   and actual entry into the ramp must still work. This is a proposed producer
   filter improvement; it does not silently revise the locked shared reference
   state machine.

Initially run the new spatial feature beside the current detector and classifier
so missed signs remain observable. After its precision is established, confident
branch-proposal exclusion can run **between detection and classification**. The
Android detector consumes a fixed 1280² tensor: masking pixels does not make that
network smaller. Both clients classify crops sequentially; historical Android
logs show about 116 ms median for one classifier call. Avoiding a demonstrably
unrelated crop could save real work, unlike merely painting the input black.

## Budget and implementation boundary

| Added work | Initial target on the slow Android | Limit mechanism |
| --- | ---: | --- |
| Cached map interval, identity, candidate/track rules | <5 ms | Bounded arrays, no per-frame database scan |
| Optional low-resolution carriageway/separator estimate | <50 ms | One job at a time, bounded cadence, no growing queue |
| Optional supplementary-arrow crop | Within remaining budget | Only relevant sign assemblies; measured separately |
| Total added decision waiting | At most 200 ms | Stop waiting at deadline; ignore late/stale geometry and use the available cheap path |

These are **targets, not measured phone timings**. A timeout prevents the decision
path from waiting; it does not magically cancel a GPU operation. Prefer CPU work
for the first geometry prototype, measure contention if a neural model is used,
and never launch overlapping late jobs. Reuse geometry only within a validated
age/pose envelope. Reuse existing temporal confirmations rather than requiring
an additional fixed delay of several frames. The data and timing definitions are
in the [latency note](TSR_ADDED_DECISION_LATENCY_2026-09-28.md).

## Further cues worth testing, in order

- **Supplementary exit arrows:** two A75 views visibly contain down-right arrows
  beneath the 70. Inspect a slightly enlarged sign crop. Associate the arrow with
  its parent sign and the observed branch; do not equate every arrow or a manually
  assigned road label with automatic proof.
- **Sign-centre motion:** track the centre/bearing across views and estimate lateral
  location using calibrated camera/relative motion. This can work without seeing
  the post foot. A small triangulation/least-squares calculation is cheap, but
  uncertain GPS, camera rotation and nearly parallel views must widen uncertainty.
  Test this separately from lane extraction.
- **Driver behavior:** rapid descending values and continuing mainline motion can
  corroborate a branch hypothesis. Not slowing down cannot by itself veto a real
  limit. Roadworks can also produce a genuine descending sequence. Do not use it
  in the first automatic filter.

This architecture agrees with deployed research directions: NVIDIA describes
separate sign and path perception joined by sign-to-path association, with map
fusion as another input ([official explanation](https://blogs.nvidia.com/blog/drive-labs-ai-based-live-perception/)).
Row-based lane estimation reduces output complexity compared with dense lane
segmentation ([Qin et al., ECCV 2020](https://www.ecva.net/papers/eccv_2020/papers_ECCV/papers/123690273.pdf)).
Its published speed was measured on a GTX 1080 Ti, not this Android. Neither source
establishes the performance or correctness of our proposed mobile filter.

## Immediate engineering deliverable

The next app change should be the **directed encounter + per-candidate guard**,
implemented with matching Swift/Kotlin fixtures. Compare three independent arms:
the literal 200 m blanket blackout, the map-scoped selective rule with reviewed
geometry inputs, and the same rule with automatically extracted visual geometry.
Count lost genuine signs alongside rejected branch signs. Human-provided branch
relations test decision wiring only; they cannot establish automatic perception
accuracy.

Required first controls: the actual A75 ramp-positive; a genuine single and paired
mainline reduction beside an exit; left/overhead signs; a 70→50→30 sequence after
dismissal; ramp entry; stale context; a truck hiding the separator; night/poor
paint; sign first seen before the interval; same coordinates on disconnected
roads. The new [visual evidence ledger](TSR_SEPARATOR_REVIEW_2026-09-28.json)
records which cues are visible in the existing twelve images. It is an assistant
review, not an automatic detector result.

No production filter or mobile model is enabled by this recommendation. The work
now has an implementable first step and a narrow comparison that can falsify it.

The [exit-window prototype and comparison](TSR_EXIT_WINDOW_ABLATION_2026-09-28.md)
now implement directed partial-edge intervals and the blanket/selective decision
arms. Its 32 new tests pass; the combined offline experiment suite passes all
160 tests. The selective arm currently consumes explicitly reviewed/synthetic
branch cues, so these results validate the window and gating logic, not automatic
visual extraction or on-device timing.
