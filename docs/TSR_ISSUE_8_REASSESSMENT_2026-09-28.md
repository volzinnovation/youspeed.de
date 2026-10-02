# Issue #8 reassessment — 28 September 2026

**What to implement next:** a directed exit-encounter filter for individual signs,
using the whole main carriageway and painted separation cues. Keep full-frame
detection; compare the proposed 200 m blanket blackout offline. Target <5 ms for
the cached map/track rule and <50 ms for optional low-resolution geometry within
the owner's **200 ms added-decision budget**; these timings still need measurement.
The [concrete recommendation](TSR_EXIT_FILTER_NEXT_STEP_2026-09-28.md) explains the
algorithm, safeguards and first test cases. The earlier all-unknown result applies
to visible-post-foot geometry, not to every possible visual method.

**Parent #8 remains open. Production enforcement is NO-GO.** The engineering
contract, candidate diagnostics, native tracker and replay infrastructure exist;
the September France drive shows that exit-sign suppression is still inadequate.
Passing synthetic parity is not field qualification. The general applicability
policy remains in shadow mode; the older narrow exit/access-road guards also
operate in shadow mode and must be distinguished from general enforcement.

The complete annotated research review is attached to
[#8](https://github.com/volzinnovation/youspeed.de/issues/8#issuecomment-5877087063).
This assessment follows the actual acceptance criteria of children #9–#18.
The [GitHub status update](https://github.com/volzinnovation/youspeed.de/issues/8#issuecomment-5877572246)
is posted; all eleven issue bodies/states were read back and verified. #9 and
#11 are closed as engineering-complete. #18 is closed using its explicit
completed-defer acceptance path, with reopening prerequisites documented.
The new corpus, offline runners and reports described here are local working-tree
artifacts; no commit, branch push, bundle publication or device installation was
performed for this experiment.

## What the cheapest experiment establishes

1. Four original failure stills now have separate assistant-reviewed governing-road
   labels: three other-road signs and one unknown. The 15:43 still shows an
   unreadable sign back; it cannot confirm the logged 70. Sparse stills do not
   establish physical identity for every live recognition candidate.
2. Eight real public Panoramax images add A10 Orléans-Gidy and A75 Issoire exit 13:
   seven other-road observations and one real ego-road 70 viewed from the ramp.
   The exact image/sequence IDs do not occur in the reviewed local baseline.
   This is exploratory geographic separation, not a hidden final holdout or a
   claim of independence from classifier training. OSM France was unreachable;
   federation sources on MathiasBas and IGN supplied the images.
3. Geometry alone and geometry plus verified physical-track carry both leave
   **12/12 observations unresolved**. Eleven post bases are obscured; one visible
   base is ambiguous between nearby roads. The real positive control also remains
   unresolved. Abstaining on every case is not successful suppression. Driver
   behavior, learned geometry and manually supplied arrow-to-road relations are
   disabled. The latter would otherwise supply the relation answer as an input.
4. A separate structural replay of all 49 Brouck frames compares the selected way
   against current OSM connectivity: recorded branches 0/49; endpoint-only
   counterfactual departure coverage 0/49; original-node/interior-junction
   counterfactual coverage 49/49. **46/49 contexts remain stale.** This measures
   available connections, not proximity, sign assignment or corrected native
   authority. Current OSM cannot be relabeled as the as-driven bundle.

At Brouck, A4 way `216220089` meets the real Aire departure `4683712` at internal
node `10532395`. The nearby logged alternative `227886706` is emergency access.
These are different road roles. A75 also has lane-specific speed tags; applying
one lane's value or masking the right image across the whole motorway way would
be too coarse. Historical imagery and current OSM can disagree without either
being a recognition error.

The A75 source timestamps advance by microseconds while positions move metres;
the replay preserves their ordering but disables temporal carry. Raw A10
equirectangular images are not comparable to the phone's fixed-x rule. A simplified
fixed-x comparison is evaluated only on three readable original stills with
recorded-context annotations; all three are false admissions in that approximate
comparison. It is not an end-to-end native or field accuracy measure.

See the [image experiment](TSR_IMAGE_GEOMETRY_ABLATION_2026-09-28.md),
[public corpus](../shared/tsr/applicability/fixtures/panoramax-french-exits-v1/README.md),
[image report](../shared/tsr/applicability/fixtures/image-road-geometry-ablation-20260928-v1.report.json),
and [structural replay](../shared/tsr/applicability/fixtures/corrected-exit-topology-v1/brouck-replay.report.json).

## Subissue assessment

| Issue | Assessment | Remaining work or closure boundary |
| --- | --- | --- |
| #9 — contracts | Closed: engineering-complete | Versioned sidecars, legacy/malformed cases, exact native semantic parity and preview/passage timing. Contract enforcement is distinct from enabling it on a phone. |
| #10 — corpus and scorecard | Open | Recorded baseline and new reviewed-input experiment are reproducible. Independent human adjudication, complete scenario coverage, full-image inference, paired authority outputs and exposure/confidence gates remain missing. |
| #11 — diagnostics | Closed: engineering-complete | Real Android diagnostic imports now exercised; original candidates and rejected evidence remain available. This does not qualify the downstream filter. |
| #12 — physical tracker | Open | Golden identity/reset/parity regressions pass. Dense independently verified field tracks, passage integration qualification and sustained phone CPU/cadence evidence remain outstanding. Public stills cannot supply them. |
| #13 — road snapshots | Open | Both providers and legacy layout fallback exist. Capture-time freshness, geometric corner-case parity and sustained lookup cost still need qualification. Interior-node loss is now a concrete gap. |
| #14 — decision policy | Open | Pure deterministic abstention/parity exists. Live calibration, reviewed positive/negative vectors and causal measured ablations remain incomplete. Support-point geometry is insufficient on the new images. |
| #15 — authority boundaries | Open | Shadow/enforce/disabled paths and regression tests exist. Qualify complete immediate display, warning, end-sign, passage and export behavior on both apps. General shadow decisions do not currently block all unknowns. |
| #16 — qualification | Open; NO-GO | CI/commands exist. Required independent exposure, recall/false-activation gates, untouched final evaluation, device budgets and sustained co-consumer tests have not passed. |
| #17 — directed metadata | Targeted investigation justified; open | Replaces the earlier no-evidence defer. Prototype original-node/internal-junction context and synchronized capture; quantify benefit before production schema work. Full/delta compatibility, both readers, size/cost and fresh evaluation remain required. |
| #18 — learned reranker | Closed: completed defer decision | Insufficient independent data and missing spatial/timing inputs. No model trained or installed. A learned lane/occlusion feature experiment is separate from reranker promotion. Revisit after the corrected-input baseline and independently reviewed residuals. |

## Scenario coverage gaps for #10

The existing 56 native golden scenarios and 58 hypothesis simulations are
synthetic engineering checks, not reviewed driving coverage. The four recorded
clips retain original proposals/times but are not densely adjudicated ground truth.

| Required slice | Reviewed real evidence and blocker |
| --- | --- |
| Motorway exits and service areas | Original failures plus A10/A75 stills; sparse, assistant-reviewed only. Need dense same-camera tracks, independent review and a genuine mainline positive. |
| Actual exit/turn | One A75 ramp-positive still; no continuous approach/turn/passage or authoritative output sequence. |
| Parallel carriageways | Competing roads visible in some stills; no separately adjudicated parallel-road event/exposure slice. |
| Side-road Yield and ego-road Yield | Missing reviewed real positive/negative pair. |
| Opposite-direction signs | One unreadable sign back is unknown; missing reviewed readable positive/negative sequence. |
| True left/median/overhead signs | Missing reviewed real coverage; cannot infer recall from the right-side ramp control. |
| Curves, legitimate lane splits and junction choices | Some exit geometry is visible; no full reviewed curve/lane/junction-choice sequence with camera calibration. |
| Repeated equal-value signs and class flicker | Repeated views of two A75 posts and one A10 post; no causal native identity truth through a full traversal. |
| Stationary/slow travel and negative no-sign stretches | Missing reviewed sequences and meaningful time/distance exposure. |
| Poor GPS, missing maps and delayed context | Recorded stale-context examples exist; no paired, densely reviewed applicability and actual authority outputs. Missing-map and low-GPS-quality real cases remain unqualified. |
| Remount/rotation, interruption and low cadence | Synthetic coverage; public timing metadata is not verified vehicle cadence. Missing controlled real-device sequence. |
| Occlusion and detector dropout | Occlusion visible in stills; no synchronized image-inference outputs to score detector dropout or reacquisition. |

All field precision/recall, false activations per km/hour and confidence gates
remain pending. Unknown truth is not a negative. Neither zero wrong-road outputs
from an all-unknown method nor repeated pictures of one post establish success.

## Ordered follow-up

1. Preserve this baseline. Independently adjudicate governing-road labels, then
   collect/review synchronized same-camera sequences with original timestamps,
   calibrated projection, actual road snapshots and verified physical tracks.
2. Evaluate corrected internal-node/directed context and capture freshness with
   behavior off. Keep old snapshot age intact in the baseline. At occluded posts,
   test a separately reviewed separator/occlusion cue and supplementary-arrow
   geometry rather than inventing a ground foot.
3. Add driver behavior as its own ablation. A driver who has not yet braked is
   not evidence that a legitimate low limit can be ignored. Fast 90/70/50/30
   changes need physical-sign identity to distinguish separate signs from flicker.
4. Add a learned lane/road/occlusion estimator independently, with missingness,
   projection and target-device cost measured. Only then assess whether a learned
   applicability reranker resolves an identified residual. Once examples have
   informed design, use new independent data for final qualification.

## Validation performed

- 128 experiment/corpus/topology/simulation tests passed, including the supplied
  real native baseline and five new cached-track invalidation regressions.
- 50 contract/applicability tests and 24 Inspector tests passed.
- Actual Swift/Kotlin golden replay passed exact parity for 56 scenarios.
- The 12-image replay verified original image hashes and reproduced the frozen
  report; all public image provenance and metadata hashes were checked.
- `git diff --check` passed. No field/device performance or deployment claim.

Reproduce the structural experiment:

```sh
python3 scripts/tsr/applicability/topology_gap_replay.py --recorded shared/tsr/applicability/fixtures/fr-exit-failures-20260928-v1.json --topology shared/tsr/applicability/fixtures/corrected-exit-topology-v1/brouck.json --scenario clip-143435 --output /tmp/brouck-replay.report.json
python3 -m pytest tests/tsr/test_exit_topology_experiment.py -q
```

Image acquisition/replay commands and source limitations are in the companion
image experiment. These artifacts add no image upload, mobile state-machine
change, bundle migration or model change.
