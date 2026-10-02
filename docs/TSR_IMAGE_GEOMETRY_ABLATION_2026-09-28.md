# Offline image geometry ablation — 28 September 2026

This experiment asks whether inexpensive road geometry and verified physical-sign
identity can distinguish motorway signs from signs governing nearby exits and
service entrances. It is an offline reviewed-input experiment. It does not run a
TSR detector, learned lane model, driver-behavior heuristic, native recognition
confirmation, or speed-reference policy. It changes neither mobile app.

**Result:** simple support-point geometry is insufficient on these images. All
12 observations remain unresolved, including the legitimate ego-road control.
Tracking provides no additional resolved assignment. This is a negative finding,
not evidence of successful suppression or a measured field improvement.

## Frozen result

The [hash-bound report](../shared/tsr/applicability/fixtures/image-road-geometry-ablation-20260928-v1.report.json)
contains 12 verified image files, three geographic routes and five source
sequences. There are four development stills from the user's drive and eight
public stills from A10 Orléans and A75 Issoire. Assistant-reviewed labels comprise
ten other-road observations, one ego-road observation, and one unknown.

| Stage | Wrong-road admission | Legitimate rejection | Other-road unresolved | Ego-road unresolved | Not evaluated |
| --- | ---: | ---: | ---: | ---: | ---: |
| Approximate fixed-x guard on eligible stills | 3 | 0 | 0 | 0 | 9 |
| Reviewed support/road geometry | 0 | 0 | 10 | 1 | 0 |
| Same geometry plus causal physical-track carry | 0 | 0 | 10 | 1 | 0 |

The geometry stages also leave the one unknown-label observation unresolved.
Eleven observations have no reliable ground anchor; the remaining visible A10
50-post base is too ambiguous between neighboring roads under the frozen margin.
The corpus has four verified physical tracks spanning seven observations and
five observations without verified track identity. No prior resolved support
assignment exists to carry. This includes real A10 50 → 30 → same-30 imagery;
three frames do not represent three physical signs.

The eight public stills lack historical native guard context; the three A10
images are also equirectangular. The ninth ineligible baseline observation is
the original reverse-face sign with unreadable speed. Consequently the zero
baseline legitimate-rejection count evaluates no legitimate-sign control and
cannot establish its safety. The A75 ego-road control is evaluated by geometry
and remains unresolved.

Supplementary down-right arrow-to-road relations in two A75 annotations are
retained for a possible **manual-cue ceiling**, but are disabled in all reported
predictions. Supplying the associated road ID would already supply the relation
answer; it is not a learned or geometric inference gain.

## Inputs and separation of evidence

The original-drive corpus contains four immutable France stills. Each retains
its capture ID, exact capture timestamp, original SHA-256, dimensions, EXIF
orientation, independently described image road polygons, visible support
features, and a separate expected governing-road label. The label reviewer is
the assistant; independent human adjudication has not occurred. A nearby live
recognition candidate is not the still's detection, box, or physical-sign ID.

The public corpus uses downloaded Panoramax originals/HD derivatives with item
metadata, attribution, source URLs, and hashes. It is separated from the user
drive by route and sequence. Here “held out” means geographically separate from
the four development stills and not used to tune thresholds; these images have
now been reviewed, so this is not a hidden benchmark. No claim about training-set
novelty follows from geographic separation.

Current OSM topology is an independently sourced counterfactual, not the bundle
state at capture time. A current connection cannot establish which sign governs
a road, or what historical lane tags were present. Symbolic visual road IDs in
the image annotations do not become OSM way IDs by implication.

The separate [Brouck structural replay](../shared/tsr/applicability/fixtures/corrected-exit-topology-v1/brouck-replay.report.json)
finds a real graph-construction gap: the actual service-area departure way
`4683712` connects to motorway way `216220089` at interior node `10532395`.
Across 49 retained frames, neither recorded branch lists nor an endpoint-only
counterfactual expose the departure; shared-node identity exposes it in all 49.
The nearby `227886706` service way is tagged emergency access and is not this
entrance. These are structural coverage counts: 46 frames still have stale or
missing context, and the replay neither repairs freshness nor establishes a
current encounter distance or sign-governing road. It is separate from the
image assignment and does not turn unresolved image predictions into rejection.

## Frozen method

`scripts/tsr/applicability/image_geometry_replay.py` assigns a support point to a
reviewed road polygon only when the point and its uncertainty are sufficiently
far from competing roads and boundaries. A post may stand just outside asphalt;
the nearest-edge rule has a fixed normalized-image distance ceiling of 0.025,
minimum separation of 0.015, and explicit support uncertainty. These are frozen
experimental constants, not calibrated metric distances. Polygon membership
does not by itself prove legal applicability.

An elevated sign center is never treated as a ground point. A post terminating
at an occluding guardrail is not a visible ground anchor. Large uncertainty,
overlapping road polygons, an ambiguous nearest road, or missing reliable
support produces `unknown`. A non-ego assignment also needs a directed branch
relation; mere geographic proximity is insufficient.

Physical-track carry uses only a prior resolved assignment for the same verified
sign, route, sequence, split, and current road, within 2.5 seconds of the original
assignment. It never synthesizes observations or confirmation frames. Unknown
or normalized capture cadence disables carry for the entire sequence. Original
ISO timestamps are preserved, including microseconds; distinct IGN timestamps
ten microseconds apart across several meters are ordering metadata, not evidence
of actual temporal sampling. Entering another road changes the track scope.
An intervening frame removes cached assignments when their road disappears,
becomes direction-incompatible, loses the required directed relation, or changes
ego scope, even if the sign is not visible in that frame. Restoring the road or
returning to the previous scope cannot resurrect the expired assignment.

The legacy fixed-x comparison is only a simplified still-box counterfactual. It
requires an explicitly eligible historical-context annotation. Raw
equirectangular panoramas are ineligible: the panorama's center is not the
vehicle's forward optical axis. Unknown guard context and unreadable speed
values are also `not_evaluated`. This comparison must not be reported as native
camera accuracy or actual downstream speed authority.

## Reproduction and integrity

Replay is network-free and requires the pinned image bytes in the ignored local
cache. Missing private originals must be supplied from the authorized evidence
archive; they cannot be recovered automatically from a public URL. JSON metadata
and fixtures are retained in the repository. The report binds the corpus files,
every image, canonical frame annotation, and the runner to SHA-256 hashes.

An explicit, separate download command is provided for public images only:

```sh
python3 scripts/tsr/applicability/fetch_public_image_corpus.py shared/tsr/applicability/fixtures/panoramax-french-exits-v1/corpus.json
python3 scripts/tsr/applicability/image_geometry_replay.py shared/tsr/applicability/fixtures/existing-fr-exit-road-labels-v1.json shared/tsr/applicability/fixtures/panoramax-french-exits-v1/corpus.json --output /tmp/youspeed-image-road-report.json
python3 -m pytest -q tests/tsr/test_image_geometry_replay.py tests/tsr/test_fetch_public_image_corpus.py
```

Python requires `jsonschema` and Pillow for replay, and pytest for tests. The
public fetch command was verified against all eight cached pinned images;
network downloads are opt-in and were not repeated merely to check the helper.

The fetch helper accepts only HTTPS URLs on explicit public-source hosts, follows
only permitted redirects, checks the expected image hash before saving, never
sends credentials, and never replaces an existing cache entry. Changed upstream
bytes fail verification and require renewed review. Passing a private corpus
reports unavailable private originals without requesting them over the network.

Validation rejects duplicate image bytes posing as independent observations,
duplicate immutable frame IDs, non-increasing sequence capture times, route or
sequence leakage between splits, invalid support provenance, and mismatched
image hashes or orientation-adjusted dimensions. Tests also change expected
labels while requiring identical predictions, and verify that temporal carry
cannot consume future geometry, bridge long gaps, or survive a road-scope change.

## Interpretation limits and next experiment

Counts must retain wrong-road admissions, legitimate-sign rejections, unresolved
ego signs, unresolved other-road signs, unknown labels, and ineligible baseline
observations separately. An abstention is not a correct rejection or successful
suppression. Repeated observations of one sign are not independent physical
signs. Reviewed geometry supplies information a deployed app would still have to
estimate; no phone latency, field accuracy, or learned-model gain is measured.

Occluding barriers are likely valuable next-stage visual context. A visible
post behind a barrier separating the ego carriageway from a service entrance
can remain interpretable when its ground foot is invisible. That needs a
separately reviewed separator/occlusion feature and a new frozen experiment;
inventing a ground foot or tuning the current annotations until they pass would
conceal the current method's failure. Supplementary arrows likewise need an
explicit distinction between observed pixels and a manually supplied road
relation. Neither is evidence that a learned model has solved the task.

Behavior remains a separate future ablation. Speed alone cannot discard a low
limit: a driver may brake late or a genuine mainline restriction may require
immediate action. The first useful implementation target is better spatial
context and tracked physical identity, with honest uncertainty, before adding
weak behavioral evidence. See the companion
[primary-source research review](TSR_ROAD_APPLICABILITY_RESEARCH_2026-09-28.md).
