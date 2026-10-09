# Live crop review and exit-context implementation — 2026-10-09

This implements the tooling for [#27](https://github.com/volzinnovation/youspeed.de/issues/27)
and [#28](https://github.com/volzinnovation/youspeed.de/issues/28), following the
crop-first priority plan in draft PR #25. **Archive-video replay crops are excluded
from this analysis, review writes and reviewed exports, even if GPS can be recovered.**
Unknown source provenance is counted separately and also withheld. Existing raw
records remain available in a read-only legacy gallery.

The product objective remains deciding whether a visible traffic sign governs the
driver's road, especially when staying on the mainline beside an exit. Class review,
exit proximity and governing-road truth are three independent dimensions.

## Implemented

The Inspector supports Wrong class → Correct class → Save, Confirm correct,
Not a sign, Uncertain, history and append-only undo. Corrections bind the immutable
crop/image and observation to a review revision. The exact class choices come from
544 pinned shared catalog entries for BE, CH, DE, FR and NL. Original predictions
and scores remain unchanged. No automatic sibling propagation is implemented.

A separately authenticated backend service saves reviews; the gallery's database
role remains read-only. The browser holds the review key only in memory. Retries
reuse request identities and stale edits conflict. Saving and export recheck source
hashes, current consent, deletion, expiry and complete fresh controls. The default
live gallery and device list use the same authoritative source predicate before
pagination. Legacy browsing cannot grant review or export eligibility.

The offline worker builds directed motorway/trunk exit candidates from original
OSM node identities and explicit road direction. It distinguishes exits, entrances,
known topology gaps, regional coverage limits and insufficient location/time data.
No live map request is made per crop. Exact crop GPS takes precedence; explicit
null stays unknown. Legacy fallback must still be temporally aligned to this crop.

Derived context is versioned separately as `near_exit`, `no_exit` or `unknown`;
absence of a computed record is `not_computed`. The default radius is 500 m with
bounded GPS uncertainty. A `no_exit` result means no candidate in the pinned map's
qualified search area, not proof that no real-world exit exists. Heading relation
is descriptive: it does not identify the driver's carriageway or the sign's road.

The additive worker path rechecks current sources under the import/deletion lock,
verifies the complete staged result population and hashes, recomputes results, and
inserts immutable context records. Repeated identical input is idempotent. Source
rows, human class reviews, catalogs and credits are not changed.

## Evidence and limits

- Backend regression: **154 passed, 19 skipped**. This includes the new review and
  geographic-context tests using real disposable PostgreSQL for migrations 005/006.
  The SQL-only harness does not qualify older migrations, PostGIS, full archive
  import, production grants or production deployment.
- Inspector: **34 Python tests plus 42 subtests**, and **74 JavaScript tests** passed.
  An additional cross-repository SQL smoke exercised the actual gallery queries as
  the report role: corrected-country filtering, review/context filters, replay
  exclusion, legacy browsing, device counts and stale-control refusal.
- Browser checks used the actual Inspector with synthetic data and the real taxonomy
  and decision validator. Correction/save/reload, undo, confirmation, conflict/reload,
  independent filters, export, key clearing and legacy read-only behavior passed.
  This is separate from the real PostgreSQL durability tests.
- The locally available Baden-Württemberg map extract is dated **2026-09-13**.
  Its pinned PBF, coverage polygon and source manifest are bound together explicitly;
  the association was reviewed by the assistant. Source incompleteness and later
  road changes remain possible. The final detached index build completed in 109
  seconds: 19,679 ways, 100,936 referenced nodes, 1,069 directed exits, 1,154
  entrances and 1,182 topology gaps. The immutable index SHA-256 is
  `8288006df7775f9a7b96b315ea45d3d74cd47cf1622b85c7df1e94dd23c9e2a6`.
  These are map records, not crop/encounter counts. Generated map data stays outside Git.

The backend implementation is committed as
[`441be34`](https://github.com/volzinnovation/Woladen.de-analytics/commit/441be34ea151669b3caef7973210837f885d25b0).
Its rollout instructions are in
[Crop reviews](https://github.com/volzinnovation/Woladen.de-analytics/blob/441be34ea151669b3caef7973210837f885d25b0/docs/youspeed/CROP_REVIEWS.md) and
[Exit context](https://github.com/volzinnovation/Woladen.de-analytics/blob/441be34ea151669b3caef7973210837f885d25b0/docs/youspeed/CROP_EXIT_CONTEXT.md). Apply its reviewed migrations and explicit
role grants as one coordinated backend revision before enabling the live workflow.
See [Inspector setup](../inspector/README.md).

The initial implementation pass could not reach volz-db. After VPN access returned,
a read-only inventory and offline context run completed: **1,801 live crops** remain
after excluding **5,452 archive/replay crops**; **201** are near mapped exits.
See the [live inventory and remaining gates](LIVE_CROP_INVENTORY_2026-10-09.md).
The review/context tables are absent on the inspected database; no migration or
production context write was performed. Class accuracy, wrong-road rejection
improvement and production readiness remain unmeasured. No model training or phone
deployment was performed. Prior ZOD/native comparison evidence remains unchanged.

## Next work, in order

1. The bounded read-only inventory and offline geographic staging are complete.
   Finish administrator attestation of the running containers, then approve the
   coordinated backend/Inspector rollout. A concrete migration, grants, credentials,
   compatibility and rollback plan is prepared privately. Current SSH access cannot
   inspect Docker, and noninteractive sudo requires authentication. Estimated
   remaining operational work: 0.5–1 day after administrator access and rollout
   approval, subject to deployed compatibility. Recheck current consent and source
   equality before any context write.
2. Build the initial **30–50 encounter target** from eligible live captures only.
   This is a target, not a guaranteed available sample. Keep mainline-near-exit,
   taken/untaken exit, simultaneous sign, overhead/supplementary and non-exit
   categories, reporting every shortfall. Allow 1–3 review days after source links
   and surrounding context are available; measure actual review time first.
3. The bounded #15 selection fix and #13 capture-context regression work are
   now implemented and tested: see [native follow-through](TSR_CAPTURE_AND_SELECTION_2026-10-09.md).
   Next qualify actual exposure-aligned context and remaining guard-wide effects. Calibrated yaw is currently unavailable to general applicability;
   assumed mount zero and image guide alignment do not establish it. Keep that
   uncertainty and the 1.5-second freshness gate explicit.
4. Only then compare sign decisions with existing safeguards, native geometry,
   native plus segmentation, and reviewed geometry on identical eligible encounters.
   Reuse the Hough probe with exactly matched grayscale bytes and timestamps;
   prepare the adapter before a new run. Estimate 1–2 days for the adapter and
   2–4 days for the sign-decision comparison once inputs are qualified.

Further lane training is conditional on measurable sign-relevance benefit. If even
reviewed geometry does not improve the decisions, stop expanding lane-based sign
relevance and investigate the map/context/sign-assembly failures. Nighttime
grayscale switching remains deferred without observed failures.

## Encounter ledger contract for the next review

Each proposed encounter must retain an explicit list of crop/image hashes, review
revisions, source session/observation/track identities, source frame times and the
exit-context run/index/configuration identities. A source track is a grouping hint,
not proof of one physical sign. Record linkage to surrounding **live-capture**
frames/video and runtime context with verified hashes and time mapping; unresolved
linkage remains explicit and development-only.

Review class separately from governing road, driver trajectory, visible interval,
and the earliest time at which a causal runtime decision was possible. Future
frames may assist offline truth but never enter the runtime comparison. Freeze
physical-sign/site and drive groups before any split or sampling. Previously
exposed examples remain development data. A crop export currently declares
`training_ready=false`, `acceptance_eligible=false` and `grouping_status=unverified`;
it cannot bypass this gate.

Count wrong-road actionable acceptance, valid-sign exclusion, abstention, decision
delay and taken-exit release per encounter, with class errors separately identified.
Crops are conditioned on a successful detection and cannot establish missed-sign
recall; independently reviewed full-frame windows are necessary for that claim.
No thresholds may be selected from future acceptance drives/sites.
