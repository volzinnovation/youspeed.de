# Exit-window experiment: avoid a whole-way or full-frame blackout

The proposed **200 m total** window is interpreted here as **100 m before to
100 m after the actual directed exit node**. Starting 100 m before and continuing
200 m after is a **300 m** window. Both were replayed geometrically; neither is
enabled on a phone. A wider −350/+100 m interval is useful for preparing an exit
risk context, not justification for disabling recognition throughout it.

## Concrete geometry findings

| Current public OSM context | Requested interval | Reconstructed coverage | Partial directed edges |
| --- | --- | ---: | ---: |
| A4 Aire de Brouck | −100/+100 m | 200 m | 3 |
| A4 Aire de Brouck | −100/+200 m | 300 m | 3 |
| A4 Aire de Brouck | −350/+100 m | 450 m | 5 |
| A75 exit 13 northbound | −100/+100 m | 200 m | 8 |
| A75 exit 13 northbound | −350/+100 m | 450 m | 11 |
| A75 exit 13 southbound | −100/+100 m | 160.7 m | 3 |

Brouck way `216220089` is **4,593.9 m long**. Its exit node `10532395` lies
3,090.6 m along it, with another 1,503.3 m after the node. Disabling vision for
that entire way would disable it for roughly **23 times** the intended distance.
Conversely, A75 approach ways are only 96.8 m northbound and 60.7 m southbound:
an interval must cross way boundaries. The bounded southbound extract lacks the
preceding mainline way, so the experiment explicitly reports 39.3 m missing
upstream instead of inventing connectivity.

The original Brouck still's recorded location projects to **65.1 m after** the
exit node, 2.4 m laterally from the current mainline centreline. Its reported
location accuracy is 7.6 m. Embedded earlier 70/50 annotations have recorded
coordinates approximately 10.5 m before the node. Thus the narrow window would
cover those *recorded positions*. This is not a false-activation replay: those
annotations are not verified physical matches to the visible 30, their original
fix timestamps are not preserved in the annotation, and current OSM is a
counterfactual. No position is fabricated for the other 49 recorded frames;
46 of their road snapshots remain stale.

Sources: the pinned public OSM extracts in
`shared/tsr/applicability/fixtures/corrected-exit-topology-v1/`; authorized local
photo metadata `inspector/logs/2026-09-28-fr-de-review/android/sample-photos.json`;
the unchanged `fr-exit-failures-20260928-v1.json` recorded fixture. The location
diagnostic projects onto the explicitly recorded mainline way, not whichever
nearby road happens to be closest.

## Candidate suppression beats full-frame blackout in counterexamples

The new **32 passing checks** cover original-node connections, partial edges,
way splits, ramp entry, stale/future/ambiguous context, reverse travel, missing
extract coverage and candidate-level counterexamples. Fourteen candidate cases
are deliberately constructed, not a representative accuracy sample.

Within the interval, a blanket blackout suppresses genuine left/right paired
work-zone signs, an overhead sign and a lone mainline shoulder sign. A selective
gate preserves all four while suppressing three synthetic exit signs with an
independent reviewed gore, separator or supplementary-arrow association.
The gate does **not** suppress an unresolved sign, a sign associated with another
exit, a disconnected service road, or an exit sign visible before the interval.
Those are explicit remaining cases, not claimed successes. Merely being right
of image centre or the driver not slowing down is insufficient evidence.

The visual branch cues here are **external oracle inputs**. The experiment tests
decision wiring and its failure boundaries; it does not implement a reliable
lane detector or measure cue accuracy. Passing a candidate means only leaving
the existing TSR pipeline unchanged, never granting it display or speed-limit
authority. Road proximity alone grants no suppression decision.

Once the matched directed road actually becomes the ramp, the mainline window
ceases to apply. This is important for the photographed A75 positive control:
the same type of exit sign becomes relevant when the camera is on that exit.

## Cheap implementation direction

Compute directed **partial-edge intervals** during preprocessing, preserving
OSM node identity and interior junctions. Query an index by the capture-time
matched directed edge; never scan a 4.6 km way or run routing per camera frame.
Use the interval to request cheap branch evidence and quarantine only candidates
with a verified branch association. Keep left, overhead and unresolved signs
available to the normal pipeline. Fix freshness and candidate capture-time
alignment before using this context; do not refresh timestamps to force a match.

An optional second improvement is to remember a user dismissal for the same
validated exit encounter and branch. That could prevent a newly tracked 50 or
30 from immediately replacing the rejected exit 70. It must still require the
new candidate's branch association and expire on actual ramp entry, changed
traversal, context loss, or departure from the interval. A dismissed right-side
exit sign must not veto a later mainline work-zone sign. This is a design idea;
no shared reference-policy or dismissal semantics were changed here.

The observed windows have 3–11 short edge intervals. Index lookup plus bounded
candidate checks is a small computation compared with recognition, but **no
Android timing is established** by Python tests. The owner's 200 ms budget is for added decision cost. It still needs measured
map/context, visual-feature and gating latency under representative phone load.

Reproduction:

```sh
XONSH_HISTORY_BACKEND=dummy python3 -m pytest tests/tsr/test_exit_window_ablation.py -q
python3 scripts/tsr/applicability/exit_window_ablation.py \
  --topology shared/tsr/applicability/fixtures/corrected-exit-topology-v1/brouck.json \
  --departure-node 10532395 --ramp-way 4683712 --output /tmp/brouck-exit-window.json
```

The compact nine-variant result is
`shared/tsr/applicability/fixtures/exit-window-ablation-v1.report.json`.
