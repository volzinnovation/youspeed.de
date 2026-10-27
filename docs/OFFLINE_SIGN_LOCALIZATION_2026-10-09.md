# Offline sign positions, road context and identity proposals

Issue #10 now has a separate offline enrichment pipeline. It combines successive
live sign crops and their recorded positions/directions, estimates candidate sign
positions, projects them onto nearby road segments, and prepares versioned database
results. This work has no real-time deadline and does not change either app's
recognition, lane logic or speed-reference policy. A future online relevance
experiment must measure its own accuracy and <0.5 s processing budget.

## What is calculated

A road's local direction comes from the **closest consecutive-node segment** of
its polyline. The calculation retains the projection point, segment index, local
tangent, distance, signed lateral offset and along-way position. Selecting the two
individually nearest nodes would be incorrect at some bends and junctions because
they need not be consecutive. Equal-distance bend tangents remain ambiguous.
Original OSM node IDs support descriptive adjacency to the estimated travelled
way. Nearest road, legal road direction, observed travel direction and sign
applicability are distinct fields; proximity alone does not establish ownership.

The user confirmed a fixed, approximately forward-facing mount. Historical crops
include frame dimensions, normalized sign boxes, GPS course and fix time, but no
camera intrinsics or saved calibrated camera orientation. The pilot therefore
uses explicit camera hypotheses: horizontal FOV 45/60/75/90 degrees crossed with
mount yaw -15/0/+15 degrees. The nominal case is 60 degrees and zero yaw. These
settings were frozen before position results were inspected.

Crop-centre offsets produce assumed optical rays using a level pinhole model.
GPS-fix course is held constant until capture; turns between fix and capture are
not measured. Camera, heading, GPS and acceleration envelopes are declared
sensitivity assumptions, not verified physical error bounds or confidence
intervals. Future recorded GPS fixes can bracket capture positions offline; raw
fixes with a motion envelope remain the fallback. Repeated fix/frame identities
do not provide independent ray votes. This conservative pilot keeps one ray per
original GPS fix even when later interpolation could separate two capture times.
A future joint trajectory/landmark fit could reuse those images while explicitly
modelling their shared GPS error; this pilot does not exhaust that information.

The solver handles weak baseline/parallax, behind-camera intersections,
inconsistent rays and ambiguity explicitly. Its polygon is conditional on the
camera/association assumptions and inlier set; max-range clipping remains visible.
The map has no attested positional error bound, so the pipeline retains nominal
nearest-road hypotheses without declaring exhaustive or certain ownership.

## Frozen live pilot

All 1,801 previously selected live crops were rechecked as active, authorized,
unexpired and unchanged at **2026-10-09 19:08:24.902066 UTC**. The initial archive
population contained 5,452 replay crops; all remain excluded. The live population
contains 1,112 source observation groups, including 266 multi-crop groups. These
are producer associations, not verified physical-sign identities or proof of
user display.

Of the 266 multi-crop groups, 227 retain at least two course-qualified samples;
after duplicate-fix/frame and timing checks, **194 groups have at least two usable
rays**. The other 918 groups remain represented as underconstrained records.
The fixed 12 scenarios therefore produce 2,328 attempted triangulations.

| Nominal-camera outcome | Observation groups |
| --- | ---: |
| Conditional position estimate | 48 |
| Intersection behind camera | 74 |
| Degenerate geometry | 58 |
| Inconsistent rays | 14 |
| Fewer than two usable rays | 918 |
| Total | 1,112 |

These counts measure whether the assumed geometry could be fitted, **not location
accuracy or sign relevance**. Only 2 groups yield an estimate in every camera
scenario; neither has bounded feasible regions and a stable nearest-road
hypothesis across all scenarios. Consequently the pilot proposes **zero identity
merges**, independently of the missing canonical classifications. Of the 48 nominal estimates, 26 have supplied nearby map geometry and
22 have no supplied road in the regional extraction. Absence is not a negative
relevance label. The pinned map covers Baden-Wuerttemberg, not the complete live
collection geography. All 26 nominal nearest roads also occur in the inferred
nearest-geometry travelled path; this is not independent evidence of relevance.
Of the 48 nominal feasible regions, 47 hit the artificial range limit; the single
unclipped region still has a diameter of 432 m. The archive therefore does not
support automatic location corrections or confident road ownership in this pilot.

The full batch completed in 101.6 seconds on the Mac as a detached, bounded
process. This is an offline batch observation, not a phone latency benchmark.
Every group, including failures, was retained. Full private road results were
saved separately; database summaries explicitly retain the five nearest nominal
projections, omitted-record counts and the complete evidence hashes. This is
presentation compaction, not a change to the candidate search or a completeness
claim.

## Database and identity handling

The companion backend adds migration 007 and a worker for immutable enrichment
runs, results and source membership. Results retain candidate positions, all
camera scenarios, nearest-road hypotheses and identity proposals. Original crop
manifests, observations and classifications are preserved.

Every contributing crop is a lifecycle dependency, including crops from other
observations used only for GPS interpolation. Such support crops are **not**
identity members. This pilot has 114 groups with external trajectory support,
comprising 449 support memberships. Source update/deletion invalidates the entire
dependent result; report reads also recheck consent, expiry and review revision.
Persistence rechecks the complete source population and refuses a stale run.

Cross-observation identity proposals use deterministic complete-link clustering,
so a chain of nearby candidates cannot silently merge distant signs. Eligibility
requires all camera scenarios to succeed, bounded regions, a small union of all
feasible polygons, compatible canonical class, and a stable nearest-road
hypothesis. Groups sharing a source frame cannot merge. All historical crop
classifications currently have a null canonical code; model-label text is not
silently substituted. Identity proposals remain conditional and unreviewed, with
training and acceptance eligibility false.

Production migration/application is a separate rollout step. The offline worker
can stage a concrete validated bundle using report access alone; applying it
requires the existing worker role and migrations/grants. Adding this code does
not deploy it or change production records.

## Next work, in order

1. Apply the reviewed database migration/grants and staged batch with a fresh
   lifecycle check. Inspect the conditional results and unresolved cases in the
   analysis workflow; do not overwrite raw observations.
2. Add a versioned mapping from historical model labels to canonical classes,
   retaining unknown/ambiguous classes and review overrides. This is an offline
   enrichment task and does not require manually annotating every crop.
3. Extend the map extraction to the actual collection regions. Preserve exact
   source/version provenance, road topology and explicit direction uncertainty.
4. Improve capture geometry for new observations: save camera intrinsics/FOV,
   orientation and capture-aligned pose, together with the phone's exact matched
   OSM way ID. A separate calibrated experiment should test whether localization
   and physical identity become stable across sightings.
5. Evaluate driver-versus-exit sign relevance separately, using independently
   checked sign/road cases and real phone timing. The present batch does not
   establish that lane segmentation helps this decision.

## Reproducibility and evidence

Pure modules are in `scripts/tsr/collection/`: `triangulate_sign_position.py`,
`sign_road_association.py`, `extract_candidate_road_graph.py`,
`localize_live_signs.py`, `sign_identity_proposals.py`, and
`localized_sign_identities.py`. Tests use synthetic data; CI runs the offline
geometry and identity suites independently of mobile test jobs. All 156 focused
Python tests and lint checks passed locally. No private crop,
trajectory, derived road footprint or model weight is committed.

- Frozen protocol SHA-256: `e3d158a0c05fa85a068b7a87f71ba09a4fb29a43025bb0b0c9f9478c6ea82bf5`.
- Qualified input SHA-256: `057bc6549a1452b499d63a36a678cdc30963df7900afc12b0d76836b11b87b50`.
- PBF source SHA-256: `1856f4ac7c18435e17d74c7ba24a7b21b3a1231e60449851890dc0109638ded3`.
- Extracted graph SHA-256: `192864cb8713ea95a77db0c8622ffc81ee524e7753c6f59a1935dc97c7e88407`.
- Compact report SHA-256: `99379e5244d2f62d3b95a567e917d8fe10b6862feeb8183a2fadcebf245ccfe0`.

Independent readback reconciled all 1,112 full group files, compact summaries,
2,328 scenarios and 1,801 source members. A receipt correction preserves the
original operational record: its hardcoded descriptive source time was wrong;
the authoritative lifecycle receipt epoch gives the time printed above. Input
bytes and results are unaffected. A separate addendum binds the backend source
validators; the initial pilot receipt did not include their hashes.

The preceding full mobile CI at `079463e` passed Android unit/emulator checks and
the iPhone app build, but iOS simulator tests failed (lane callback assertions,
startup cancellation and an orientation UI assertion); dependent applicability
comparison was skipped. This remains a draft-PR limitation, separate from the
offline geometry tests. Earlier missing DCO sign-offs also remain unresolved.
