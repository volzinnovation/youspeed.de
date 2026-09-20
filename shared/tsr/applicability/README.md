# Sign applicability v1

Implementation for issue #8 and work items #9–#18. The checked-in runtime mode is
**shadow** on both platforms. There is no field-accuracy or rollout approval.

## Contract and timing (#9)

`evidence-v1.schema.json` versions candidate batches, track histories, immutable
road snapshots, decisions, diagnostic envelopes and reviewed encounter truth.
The keys are deliberately camelCase for this new sidecar; existing snake_case
recognition-v1/v2 and passage-v1 payloads are unchanged. Optional absent members
mean unavailable, exactly as JSON null does. A missing sidecar is **not evaluated**;
it cannot authorize a new event in enforcement. Historical corrections keep
existing semantics.

Boxes have a top-left origin in the full orientation-normalized image. Capture
and fix times are UTC epoch milliseconds; all motion deltas use that same clock.
Non-increasing timestamps and repeated frame IDs do not reinforce tracks. Wall
clock discontinuities cause abstention/expiry; they are not passage observations.
Sessions, lifecycle/context generations, traversal, verified bundle hash and
camera geometry form the scope. Scope changes discard association history.

Tracking happens before policy evidence accumulation. Candidate IDs are frame ID
plus the original emitted-candidate index. Assembly IDs and model/preprocessing
identity remain independent. Tracks use deterministic births (`track-1`, …),
one-to-one association with predicted center/scale, semantic disagreement penalties,
explicit assignment ambiguity, up to 24 tracks and 12 samples per track. Histories
and reacquisition are bounded to 2.5 seconds. Near-equal assignments abstain;
semantic flicker does not borrow confirmations. Expiration cancels a passage
track without emitting a negative frame.

`analyzed` is different from `skipped`, `failed`, and `interrupted`. Within an
analyzed batch, `observed`, `absent`, and `uncertain` are distinct track states.
A cap, changed winner, failed frame or applicability rejection cannot create
qualified visual loss. Only actual analyzed absence of the active track can
advance the existing passage reducer. No new pixels are retained.

An eligible, recognition-confirmed sign can update the **immediate camera
preview** without waiting for passage. The required admitted observations and
manifest confidence thresholds remain in force. Durable assertions and database
writes still wait for qualified loss and the frozen first-missing boundary.
Applicability does not turn raw recognition scores into probabilities.

Decisions bind policy version/config hash, frame, physical track, capture scope,
and road snapshot. Display, immediate and passage eligibility are explicit.
Native recognition/passage objects carry an in-memory binding that is excluded
from frozen event serialization. The durable decision sidecar is inserted in
`computer_vision_applicability_v1`, keyed by finalized event ID, in the same
transaction as the existing passage/receipt. The original passage evidence still
binds model lineage, boundary and activation scopes. Ordinary legacy reads do not
invent a binding.

## Corpus and replay (#10)

`golden-vectors-v1.json` contains **synthetic** engineering regressions, generated
by `scripts/tsr/applicability/generate_fixtures.py`. They are not reviewed real
road truth, a measured baseline, or a detector benchmark. The initial gate table
was frozen before fitting; no fitting has been performed. Null approved-inventory,
wrong-way, duplicate and device gates are unresolved.

From the repository root, after Android Gradle has resolved its existing Kotlin
JSON dependencies (Swift, Kotlin CLI, Python jsonschema are required):

```sh
python3 scripts/tsr/applicability/replay.py --output /tmp/tsr-applicability-replay
python3 -m pytest tests/tsr/test_applicability.py -q
node --test tests/inspector/tsr_qa_core.test.js
```

The runner compiles the actual Swift and Kotlin implementations against identical
proposal sequences, validates the input schema, checks exact associations,
visibility, decisions, reasons and eligibility, and permits only a 1e-9 numeric
tolerance. Process wall time includes compiler-independent process startup and
is explicitly **not** a device p50/p95 or per-frame performance measurement.
The emitted report binds corpus, policy and native source hashes.

`scorecard.py CORPUS.json PREDICTIONS.json --output REPORT.json` evaluates separate,
reviewed encounter truth against actual immediate and durable event observations.
Predictions bind a canonical corpus hash and must cover the identical held-out
encounter set. Drive, physical-sign, duplicate and route/geographic leakage is
rejected; grouping reuses `group_splits_v2.py`. Unknown truth is excluded from
precision, never converted to a negative. Zero/unknown-distance clips cannot
supply per-km exposure or numerator. Reports separate false immediate events
from false passages, include precision/recall Wilson intervals, misses, unknowns,
duplicates, direction errors, time/distance percentiles and processing cost (numeric precision requires separate `numericSign` truth),
with scenario/road-class denominators. Paired baseline significance, rate bounds,
full-image model output and sustained-device reviews remain explicit blockers.

## Collection and diagnostics (#11)

Both runtimes retain all emitted primary candidates (up to 32), independent of
which is chosen by the existing presentation lane. Admission status stays separate
from original recognition scores. A proposal cap is conservative uncertainty;
unclassified proposals are never represented as a confirmed empty scene.
Metadata sidecars use the existing local TSR/runtime log path. iPhone log records
contain `tsr_applicability_v1=JSON`; Android runtime log records use event
`tsr_applicability_v1` with an `evidence` JSON string. This adds no frame retention,
automatic upload, Dashcam reuse, Panoramax reuse or training ingestion.
Separately consented Panoramax annotation metadata carries `applicabilityStatus`;
these annotations remain non-authoritative. Old annotations omit that member.

The Inspector TSR workspace has a local applicability import panel. It displays
raw candidates, assignments/history, competing corridors, capability gaps,
reasons and eligibility. Invalid or conflicting identity links fail import.
Reviewed truth is loaded separately and original annotations are never rewritten.
Import does not request maps or inference services.

Extract an existing authorized local metadata log without copying its images:

```sh
python3 scripts/tsr/applicability/import_diagnostics.py DRIVE.log --output proposals.json
python3 scripts/tsr/applicability/replay.py --vectors proposals.json --output /tmp/drive-replay
```

These imported records remain **unreviewed**. A frozen corpus must separately
supply reviewer/provenance, encounter/drive/sign/geography IDs, sign-class
correctness, vehicle-path applicability, visibility interval, passage boundary,
uncertainty and exposure. Capture/annotation instructions are in
`../../../docs/TSR_APPLICABILITY_BELGIUM_PILOT.md`.

## Providers and decision policy (#12–#14)

V3 readers project bounded geometry already loaded on GPS updates; no per-frame
SQL or matcher retuning is introduced. The actual fix timestamp/quality is frozen
with local tangent, road class, alternatives and endpoint branches. Branches use
junction-local incoming/outgoing headings and distance along the selected geometry
to that endpoint. Snapshot age is bounded to 1.5 seconds; alternatives/branches
are capped at eight and truncation is an explicit capability gap. Android now
supports optional `shared_ref` on minimal legacy `way_links` tables like iPhone.

Current topology is symmetric endpoint adjacency. Quantized coordinates are not
OSM node identity, interior junctions may be absent, grade separation is not proven,
and legal oneway/lane metadata is unavailable. Geometry heading is oriented to
observed travel; it is never labeled legal direction. Route membership is not a
navigation intention or lane choice.

The pure policy combines calibrated image bearing, independent approach evidence,
local road geometry, and competing-corridor separation. The image term is soft;
full-frame proposals and left/median/overhead positives remain in the corpus.
Insufficient quality, missing calibration, competing corridors, flicker, stopped
or incoherent approach return UNKNOWN. Growth or a stable road alone cannot grant
eligibility. Lane and opposite-direction labels are reserved; these providers
cannot establish them. Scores are heuristic support, not calibrated probabilities.

**Current live mounts have no reviewed FOV/yaw calibration.** Providers explicitly
leave those values unavailable. Live shadow decisions therefore abstain until
such calibration is supplied by a separately qualified input. Synthetic fixtures
supply clearly labeled calibration for engineering tests. Do not enable enforcement
on the pilot just because those fixtures pass.

## Authority and qualification (#15–#18)

The shared internal build policy supports `shadow`, `enforce`, and disabled
camera authority (any non-shadow/non-enforce mode fails closed). There is no new
user-facing or Android-only setting. Both native constants are pinned to the
shared config hash. Changing this internal policy uses `scripts/tsr/applicability/sync_configuration.py`
to regenerate both clients and the shared hash; `--check` detects drift.

In enforcement, missing/non-ego/unknown evidence is a no-op for authority: it
cannot clear an older valid assertion or trigger end overlays, pictograms, feedback,
actionable passage persistence or correction export. Existing reversal, unrelated
road, lifecycle and bundle invalidation still apply. Checks occur at the preview,
controller, resolver and durable-write boundaries. Independently confirmed raw
recognition remains available exclusively to the existing non-authoritative
Panoramax annotation callback, labeled with applicability status; it cannot enter
the preview, display, passage or correction sinks. Shutdown/camera geometry changes
reset tracks; missing-frame qualification is independent of downstream selection.

Status and conditional investigations:

| Issue | Implementation / outstanding evidence |
| --- | --- |
| #9 | Versioned sidecars, golden contracts, legacy behavior and timing documented |
| #10 | Synthetic/native replay and scorecard implemented; reviewed corpus, actual baseline, full-image lane and empirical statistics pending |
| #11 | Candidate transport, local metadata, importer and Inspector implemented; real-drive import remains to be exercised |
| #12 | Bounded native physical tracker and shared regression vectors implemented; sustained device cost pending |
| #13 | Capture-time V3 snapshots and legacy layout fallback implemented; real-route/provider geometry qualification pending |
| #14 | Conservative unfitted policy implemented; mount calibration, reviewed decision vectors and ablations pending |
| #15 | Authority gates and older-assertion regression tests implemented; complete device enforcement qualification pending |
| #16 | CI and reproducible local checks added; **NO-GO** for rollout pending reviewed holdout, full-image replay, approved device budgets and sustained coexistence testing |
| #17 | **DEFER**: no reviewed development residuals justify a directed bundle extension. Existing capabilities remain explicit; no map migration or bundle generation. If later justified, Belgium is the pilot region |
| #18 | **DEFER**: no independent reviewed sequence corpus exists; no reranker training or artifact is justified |

Parent #8 cannot be closed as field-qualified. These artifacts do not authorize
a branch merge, bundle publication or production enablement. The user separately
authorized pushing the branch and installing its shadow version on the attached
iPhone on 2026-09-21.

## Reproducible engineering validation

The [checked-in parity report](synthetic-parity-report-v1.json) records the exact
policy/config/fixture hashes for 31 synthetic scenarios and the local test results
on 2026-09-20. Swift and Kotlin agree on associations, visibility, decisions,
reasons and eligibility (numeric tolerance 1e-9). iPhone consumer simulator tests
passed (326, including 23 explicit skips); Android unit tests passed (321); shared
contract checks passed (48); Inspector tests passed (24). CI wiring is included;
these counts describe the local runs, not an executed GitHub Actions run.

The broader Python TSR suite has an existing national-sign-set failure: Dutch
PNG hashes disagree with the manifest. The PNG bytes and manifest have the same
mismatch in base revision `3a37fce41c8203391870a3d34c1e0c4059d92e60`; this change
does not modify those assets. Its result was 279 passed and one failed.

No device performance, real inference accuracy, calibrated mount quality or
field improvement is established by these checks. The report is **NO-GO** for
enforcement. Its source hashes should be regenerated after any policy change.
