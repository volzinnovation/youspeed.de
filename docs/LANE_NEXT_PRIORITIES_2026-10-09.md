# Next TSR and lane priorities — 2026-10-09

This order supersedes the forward-looking priorities in earlier experiment reports;
their measured results and frozen evidence remain unchanged. The objective is to
retain driver-relevant traffic signs while rejecting visible signs for other roads,
especially exits the driver does not take.

The first work is **reviewable encounters from the existing crop database**. More
lane training and grayscale nighttime TSR are lower priorities. This is a work
plan, not a new experiment result or an authorization to deploy.

## What the paper adds

[Bargeton et al. (2010)](https://arxiv.org/pdf/1010.3867) describes sign/map fusion,
Hough on a gradient image, and grayscale shape-based sign detection. It is useful
historical precedent, not a replacement design for the more elaborate native
tracking, calibration and uncertainty handling already implemented here. Its
nighttime statement is not a controlled result for our learned RGB detector; it
does not propose a device-clock switch.

Hough is already implemented in the [classical geometry probe](TSR_CLASSICAL_GEOMETRY_PROBE_2026-09-28.md):
173 video frames plus ten stills were inspected. That established extraction and
Mac timing, not lane or sign-relevance accuracy. Reuse that extractor for the
missing candidate comparison rather than rebuilding it.

## Ordered work

| Order | Work and completion gate | Engineering estimate |
| --- | --- | --- |
| 1, in parallel | [#27](https://github.com/volzinnovation/youspeed.de/issues/27): add durable crop class review to Inspector; [#28](https://github.com/volzinnovation/youspeed.de/issues/28): audit location/source linkage and prepare a reproducible near-exit queue. Preserve raw predictions and unknown geography. | Review UI/API/schema: 2–4 days. Geography inventory: 0.5–1 day; located-subset batch/filter: another 1–2 days. |
| 2 | #10: review an initial 30–50 physical-sign encounters, recovering surrounding video where needed. Include mainline signs near exits, untaken/taken exits, simultaneous signs, overhead/supplementary signs and non-exit controls. | 1–3 days after tools and usable source links, then revise from measured review time. |
| 3, parallel with review | #13/#15: verify calibrated capture-time context and the Android filtered-top-candidate fallback against iPhone; add the simultaneous exit/mainline fixture before any enforcement change. | 1–2 days for targeted audit and fixtures; any broader correction is separately estimated. |
| 4 | #21: compare existing native proposals, fixed Hough and their union on exact common frame bytes, missing-boundary cases and negatives. Separately compare current safeguards, native association, native + semantic evidence and reviewed geometry on the encounter ledger. | Hough adapter/audit: 1–2 days. Shared shadow sign-decision comparison: 2–4 days once inputs are qualified. |
| 5, conditional | #22/#23: address only the demonstrated bottleneck: candidate recovery, calibrated association, temporal support or negative supervision. A positive ranking bonus cannot create missing geometry. | Typically 2–4 days for a justified candidate adapter/replay, or 2–5 days for one bounded supervision experiment; not both by default. |
| 6, conditional | #16/#24: untouched acceptance drives/sites, both-platform sustained workload and an explicit adoption decision. | 2–4 engineering days plus collection/review/device time; field qualification is additional. |

These are planning estimates, not expected accuracy gains or a sum of sequential
calendar days. Replay GPS recovery needs a separate estimate after inventory;
missing source logs may make it impossible. Inspector/backend implementation must
use their current branches. The lane research worktree predates newer crop work.
Concurrent #26 lane annotation work is independent; full Bézier editing is not a
prerequisite for crop review, geographic triage or encounter truth.

## Crop database and review contract

Use the volz-db crop gallery as the initial queue. Current source at app
[`cf411ef`](https://github.com/volzinnovation/youspeed.de/tree/cf411effdf823a61ba101f698ba1a6a5812dd07e)
exposes immutable crop/sighting identities, frame metadata and optional crop GPS.
The gallery has no durable class-review write workflow. Backend source at
[`e378973`](https://github.com/volzinnovation/Woladen.de-analytics/tree/e378973ea03cb61fbae96f1d80a38e60cf8ddbd6)
already defines client correction claims and catalog decisions; those are not
Inspector review records. Deployed database schema/API state was not inspected
for this plan.

Reuse the class vocabulary and validation, but add dedicated crop-bound review
records rather than overwriting model output or triggering catalog publication.
The minimum interface is **Wrong class → Correct class → Save**, with Confirm
correct, Not a sign and Uncertain alternatives. Persist corrected canonical
class/country/value, taxonomy revision, reviewer/time and revision history against
crop ID, image hash and observation identity. A wrong class with unknown
replacement remains unresolved. Original prediction/scores stay visible. Explicit
application to sibling crops records a fixed membership list; no automatic
propagation based on a class or tracker ID.

Keep the current report database role read-only. A narrowly authorized review
service handles idempotent saves and revision conflicts. Existing withdrawal,
deletion and expiry rules apply to derived annotations and exports. Reviewed
training exports freeze source, review and taxonomy revisions and exclude
unresolved replacements. A class correction is not permission to alter runtime
speed-reference policy or publish a model/catalog.

Three independent dimensions must remain distinguishable:

| Dimension | Example | How established |
| --- | --- | --- |
| Sign class | The crop shows 60, while the classifier recorded 80. | Review of sufficient sign pixels and assembly context. |
| Exit proximity | The capture was near a candidate exit. | Versioned geographic enrichment with location/map uncertainty. |
| Driver relevance | This 60 governs the exit, and the driver stayed on the mainline. | Reviewed encounter context and scope, with an interval and earliest causal decision time. |

## Geographic enrichment before full map matching

First report how many eligible crops have usable exact-frame GPS, only older
sighting GPS, missing GPS, uncertain timing and recoverable video links. Explicit
null crop GPS stays unknown; only legacy manifests lacking that field can use a
clearly marked sighting-level fallback. Camera position is not sign position,
and GPS course is not camera yaw.

The [existing archive replay](https://github.com/volzinnovation/youspeed.de/blob/cf411effdf823a61ba101f698ba1a6a5812dd07e/docs/SIGN_COLLECTION_REPEAT_CROPS_2026-10-06.md)
records source-video hash/media time but deliberately leaves GPS/road context
unknown and estimates wall-clock time. Link those crops back to verified video/log
sources before reconstructing geography. Do not align solely by estimated UTC or
fill immutable raw fields with a guessed fix. Preserve derived alignment and its
uncertainty separately.

For located crops, run an indexed batch against pinned local OSM/bundle data.
[OSM motorway junction nodes](https://wiki.openstreetmap.org/wiki/Tag:highway%3Dmotorway_junction)
identify exit points; combine available topology/direction with departure links,
including service/rest-area branches. Audit bundle capabilities rather than
assuming endpoint adjacency proves a connection or distinguishes entry/exit ramps.
Existing offline topology extraction under #17 is reusable without a mobile
bundle migration.

Start with proximity triage and visible uncertainty; directed road matching can
follow. Retain distance and its Euclidean/along-road definition, candidate IDs,
position quality, map version/hash, method/config and run revision. Distinguish
near-exit candidate, no candidate within covered search radius, ambiguous,
location missing, map coverage missing and alignment unresolved. Keep previous
runs and make retries idempotent. Current OSM is retrospective context, not proof
of what the historical bundle knew.

Inspector should filter these results separately from reviewed class and
applicability. Include sampled non-exit controls and inspect opposite carriageways,
parallel roads, bridges/tunnels and entrance-only ramps. **Near an exit never
means that the observed sign applies to that exit.**

## Encounter and experiment gates

Sibling crops improve class review, but a tight crop usually lacks road context.
Restore only required surrounding video/full frames and associated logs. An
uploaded sighting is not necessarily a complete physical encounter; classification
changes can split tracks, and repeated journeys see the same physical sign.
Record unresolved links. Group splits by drive and physical site/route; adjacent
crops from one encounter cannot be independent samples.

Crops are conditioned on successful detection and capture. They cannot measure
missed-sign recall by themselves. Add full-video reviewed windows, including
signs with no saved crop, for detector-recall claims. The initial 30–50-encounter
ledger is development evidence, not adequate production acceptance by itself.
Its size/categories depend on available context; report shortfalls rather than
filling gaps with guesses. Freeze grouping before sampling/export; relabeling
previously exposed crops does not make them fresh acceptance data. Unresolved
source/physical-sign linkage remains developmental.
Future frames can assist offline labeling; runtime comparisons use only current
and past evidence. Human review establishes governing scope separately from the
vehicle's eventual turn, which alone does not prove scope.

Use the same signs, tracks, contexts and decision policy across current safeguards,
native geometry association, native + segmentation and reviewed-geometry arms.
Keep classification errors and wrong-road assignments separately attributable.
Report wrong-road actionable acceptance, valid-sign exclusion, uncertainty,
decision delay and taken-exit release per encounter. Freeze decision criteria
before fresh evaluation; abstaining on everything is not a successful system.

For Hough, reuse its fixed extractor with the exact grayscale bytes and timestamps
used by the native arm. The earlier Hough probe used different resize/grayscale
preparation, so its outputs cannot be treated as a matched comparator unchanged.
Compare recovered supported candidates and false geometry, including before/after
segment caps; preserve finite spans, curves and unsupported gaps. Hough edges do
not automatically count as paint or additional temporal confirmations. Only
useful recovery warrants a dual-platform adapter, with existing maturity and
causal evidence gates preserved. EDLines can remain a subsequent control rather
than expanding the first matrix.

If reviewed geometry cannot materially improve sign decisions, stop expanding
the lane-driven relevance approach and examine map/sign-assembly/context failures.
If it helps while native geometry fails, target the measured extraction or temporal
gap. If native geometry helps and segmentation adds no benefit, keep the simpler
approach. A geometry diagnostic alone cannot justify live sign suppression.

## Deferred work

- **Further ZOD scale-up or backbone changes:** wait for the sign-relevance gate
  and a specific supervision failure to address. Earlier paint metrics do not
  establish benefit to the driver.
- **Clock-triggered grayscale TSR:** defer. The user reports nighttime detection
  is largely reliable. The paper's handcrafted shape detector does not establish
  a gain from grayscale input to our trained color models. If real night failures
  emerge, collect them and test a paired ablation with day/night controls. Local
  time alone misses tunnels, weather and illumination; image exposure/luminance
  and optional time/location context would be hypotheses to test, not a reason
  to add a hard night mode now.
- **More generic lane contrast experiments:** existing [lighting trials](LANE_LIGHTING_EVALUATION_2026-09-30.md)
  already use grayscale and did not justify a production detector change. They
  are separate from TSR nighttime recognition and cannot prove its performance.

No training, inference, database write/migration, application change or deployment
was performed for this reprioritization. Completed experiment evidence and the
paused preservation monitor remain unchanged.
