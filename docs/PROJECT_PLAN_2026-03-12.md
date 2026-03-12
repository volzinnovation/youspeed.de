# YouSpeed Project Plan

Date: 2026-03-12

Purpose: turn the original bootstrap vision into a concrete execution plan for the next months.

Visual timeline:
- [PROJECT_GANTT_2026-03-12.md](./PROJECT_GANTT_2026-03-12.md)

This plan is based on:
- `RESEARCH_IMPLEMENTATION_PLAN.md` (`2026-02-22`)
- `paper/share/VISION.md`
- `sprint_review.md`
- `docs/KARLSRUHE_INCREMENTAL_SEED_ROLLOUT.md`
- `iphone/SpeedConsumerApp/README.md`
- `docs/STANDUP_2026-03-06.md`

## 1) Strategic decision order

The project sequence must stay strict. We should not blur phases just because partial code exists.

1. iPhone first, Karlsruhe seed first.
2. Only after Karlsruhe seed is stable do we expand to more regions with full bundles.
3. Only after multi-region full-bundle delivery is stable do we operationalize incremental updates across regions.
4. Only after the iPhone product and data contract are stable do we port to Android.
5. Only after iPhone and Android are both real deliverables do we expose public store links on the website.
6. Papers must be aligned with the actually validated system state, not the aspirational architecture.

This means:
- the current website is still ahead of the product and must not drive scope,
- GitHub release manifests/assets remain the primary update transport for now,
- "website-based incremental update" is not a separate phase-1 protocol; it is a later packaging/distribution decision on top of the validated bundle contract.

## 2) Current state on 2026-03-12

### Already in place

- `v3` is the selected runtime format.
- The iPhone consumer app exists and uses a bundled Karlsruhe seed DB.
- The app already contains manifest sync, full-bundle download, and delta-patch application code paths.
- Karlsruhe PBF maintenance and incremental bundle workflows exist in CI.
- Matching quality improved materially with continuity scoring, tunnel gating, and `way_links`.
- The architecture/pipeline paper track already exists (`ITSC` draft + tech report).

### Not yet done in a release-grade sense

- no freshly regenerated Karlsruhe seed bundle has been treated as the locked product baseline,
- no full end-to-end public-quality validation of seed -> manifest -> delta patch -> active DB has been completed on device,
- no multi-region release set has been stabilized,
- no cross-region incremental update operation has been proven over time,
- no Android consumer app exists,
- no real App Store / Google Play release exists,
- the website still contains placeholder download CTAs and therefore must stay non-public or be reduced to non-store messaging.

## 3) Phase gates

We should use explicit gates and stop advancing until each gate is met.

### Gate A: Karlsruhe seed product gate

Required before any regional scale-out:
- generate a fresh Karlsruhe full bundle from the current pipeline,
- embed the corresponding seed DB in the iPhone app,
- validate startup, driving, recovery, and route continuity on device,
- fix any legal fallback or route-matching defects found during field drives,
- freeze one Karlsruhe seed baseline for downstream work.

### Gate B: Karlsruhe incremental-update gate

Required before multi-region incrementals:
- produce at least one real seed -> dated-version delta chain from the maintained Karlsruhe snapshot,
- validate on-device full sync and delta sync against real release assets,
- verify fallback from invalid/old delta chain to full bundle,
- verify retention, checksum, resume/retry, and background download behavior.

### Gate C: Multi-region full-bundle gate

Required before multi-region incrementals:
- publish a small supported region set with full bundles only,
- verify bundle discovery/selection/routing between regions,
- verify operational costs: build time, artifact size, release time, device storage.

### Gate D: Multi-region incremental gate

Required before Android and public release:
- prove daily or frequent update operation across the supported region set,
- verify per-region state handling, stale-chain fallback, and asset retention,
- demonstrate stable operations for at least two weeks without manual repair.

### Gate E: Product parity gate

Required before public store release:
- Android app reaches functional parity with the validated iPhone bundle/update contract,
- both apps pass the supported-region smoke matrix,
- store/legal/support assets are ready.

## 4) Milestone plan and timing

Dates below are internal target windows, not guarantees. They are chosen to enforce sequence.

| Milestone | Window | Goal | Exit criteria |
|---|---|---|---|
| `M0` Baseline lock | 2026-03-12 to 2026-03-16 | Freeze scope and stop pretending the website or Android are current deliverables | this plan accepted; website/store scope deferred; Karlsruhe seed becomes top priority |
| `M1` Karlsruhe seed RC | 2026-03-12 to 2026-03-23 | Fresh Karlsruhe full bundle and iPhone seed baseline | regenerated bundle published, bundled seed rebuilt, device smoke passes, first real drives logged |
| `M2` Karlsruhe incremental validation | 2026-03-24 to 2026-04-05 | Prove real seed -> delta update on device | delta chain generated from maintained snapshot, app applies it correctly, full-bundle fallback works |
| `M3` Supported-region expansion | 2026-04-06 to 2026-04-26 | Add first non-Karlsruhe regions with full bundles only | 3-5 supported regions/countries published and usable on device |
| `M4` Cross-region incremental operations | 2026-04-27 to 2026-05-31 | Make incremental delivery reliable across the supported set | multi-region delta flow stable for 2 weeks, release retention and recovery verified |
| `M5` Android parity | 2026-06-01 to 2026-07-12 | Port the validated iPhone product/data contract to Android | Android runs Karlsruhe seed first, then supported-region set, with equivalent sync behavior |
| `M6` Public release prep | 2026-07-13 to 2026-08-16 | Stores, legal copy, release QA, website correction | real App Store / Play assets exist, website CTAs point to real stores only |
| `M7` Public launch window | 2026-08-17 to 2026-08-31 | Public release if prior gates hold | stores live, website updated, support/docs aligned |

## 5) Detailed work items by milestone

### `M1` Karlsruhe seed release candidate

Primary objective: get one iPhone seed product baseline that we trust.

Work items:
- regenerate Karlsruhe bundle artifacts from the current map pipeline and schema,
- rebuild the bundled seed DB in `SpeedConsumerApp` from that exact artifact lineage,
- run device tests and seed-specific regression tests,
- perform repeated real-drive validation:
  - urban transitions,
  - motorway / Autobahn,
  - tunnel-adjacent segments,
  - difficult continuity cases already represented in Karlsruhe traces,
- close high-risk runtime issues before further scope:
  - legal fallback inconsistencies,
  - startup/sync recovery edge cases,
  - seed-only UX issues.

Deliverables:
- one published Karlsruhe full bundle,
- one matching bundled seed in the iPhone app,
- a short validation note with the accepted baseline version.

### `M2` Karlsruhe incremental update validation

Primary objective: prove that the update story works in reality, not just in tests and workflows.

Work items:
- generate at least one new Karlsruhe dated full bundle and one real delta chain,
- test seed -> delta and dated-version -> dated-version upgrades on device,
- verify failure paths:
  - checksum failure,
  - missing delta asset,
  - stale chain,
  - interrupted download,
  - background resume,
- verify that the app can recover cleanly to a valid active DB,
- decide the production transport contract:
  - GitHub releases remain the source of truth first,
  - website/CDN mirroring is optional later and must not fork the update protocol.

Deliverables:
- validated Karlsruhe incremental sync path,
- release-operations checklist for bundle + delta publishing,
- explicit decision on whether website distribution is still needed after GitHub validation.

### `M3` Supported-region expansion

Primary objective: expand only after the seed flow is solid.

Recommended order:
1. Baden-Württemberg and one adjacent German region relevant to real driving.
2. One or two compact single-country targets from `BundleTargets.top10.json` for artifact simplicity.
3. Only then broaden to the rest of the first supported set.

Work items:
- generate fresh full bundles for the first supported regions,
- validate region selection/routing in app,
- measure bundle sizes, first-download time, and on-device storage impact,
- test bundle switching and routing at region boundaries,
- keep incrementals disabled outside Karlsruhe until the full-bundle set is stable.

Deliverables:
- first supported public region list,
- full-bundle-only regional release set,
- device validation across region boundaries.

### `M4` Cross-region incremental operations

Primary objective: move from "one region can update" to "the product has a reliable update system."

Work items:
- enable per-region incremental generation for the supported set,
- verify retention policy and stale-chain reset behavior,
- monitor artifact growth and patch-apply time by region,
- verify recovery after missing assets or invalid state,
- decide whether a website or CDN front door adds value beyond GitHub assets.

Deliverables:
- operating incremental update service for supported regions,
- documented recovery policy,
- stable asset naming and retention policy.

### `M5` Android parity

Primary objective: port the validated product contract, not the current moving target.

Work items:
- define Android app architecture around the same `v3` bundle manifest and delta contract,
- port bundle manager, active DB handling, and update flow,
- port speed-limit runtime and field-test the same Karlsruhe seed baseline first,
- add parity tests against shared seed/incremental fixtures,
- only after Karlsruhe parity add supported-region parity.

Deliverables:
- Android seed build,
- Android supported-region build,
- parity checklist against iPhone behavior.

### `M6` Public release prep

Primary objective: release what exists, not mock it.

Work items:
- privacy/legal/store metadata,
- screenshots and store listings,
- crash and startup QA,
- internal beta / TestFlight / Play testing,
- remove placeholder CTAs from the website and replace them with real links only after store availability,
- if Android slips, decide explicitly whether launch is dual-platform or iPhone-first public beta.

Deliverables:
- real store submissions,
- corrected website,
- support and release notes.

## 6) Research and publication track

The paper track must follow the validated product milestones, but not every paper needs the same system maturity.

### Paper A: Matching approach paper

Current working folder:
- `paper/personalized_matching_arxiv`

Internal intent:
- explain the matcher as a lightweight sequence-aware mobile matcher,
- evaluate route continuity and difficult transitions,
- keep the claims narrower than the architecture paper.

Important date anchor checked on 2026-03-12:
- `ICITT 2026` full-paper deadline: 2026-04-05
- acceptance notification: 2026-05-05
- camera-ready: 2026-05-20

Implication:
- if we target `ICITT 2026`, the matching paper must be scoped to Karlsruhe/iPhone-seed evidence and written during `M1` and `M2`,
- it cannot wait for multi-region incremental maturity,
- if `M1` slips badly, we should explicitly defer venue submission instead of forcing weak evidence into the paper.

Suggested plan:
- 2026-03-12 to 2026-03-22: freeze method section and refresh experimental artifact generation from current logs,
- 2026-03-23 to 2026-03-29: add route-level evaluation from real drives and regression corpora,
- 2026-03-30 to 2026-04-04: write, trim claims, submit or consciously defer.

### Paper B: State of the Map application/system paper or talk

Target:
- `State of the Map 2026`, Paris, 2026-08-28 to 2026-08-30

Planning note:
- the conference date is confirmed,
- the public site links to the call pages, but the submission deadline was not extracted during this planning pass,
- therefore we should work with an internal readiness deadline rather than wait for the call to surprise us.

Intended story:
- offline-first smartphone ISA with OSM baseline,
- seed-first rollout,
- update architecture,
- local correction/export path,
- lessons from turning OSM speed data into a consumer app.

Suggested plan:
- draft abstract outline during `M3`,
- freeze talk/paper story during `M4`,
- target internal submission readiness by 2026-05-31,
- submit as soon as the official SotM call deadline is confirmed.

### Existing architecture paper track

Status:
- the main architecture paper already exists in the ITSC/tech-report track.

Needed follow-up:
- keep it aligned with the product claims,
- use the scientific review feedback,
- do not overclaim safety or end-to-end ISA impact from storage microbenchmarks alone.

## 7) Workstream orientation

To keep day-to-day work aligned, every task should be filed into one of these workstreams.

### `W1` Seed data and bundle generation

- Karlsruhe full bundle regeneration
- seed DB embedding
- manifest and asset verification

### `W2` iPhone runtime quality

- matcher correctness
- legal fallback correctness
- startup and recovery
- seed-only and active-bundle UX

### `W3` Incremental update system

- PBF maintenance
- delta pack generation
- delta index correctness
- on-device patch apply and fallback

### `W4` Regional scale-out

- supported-region selection
- region bundle generation
- bundle-routing validation
- operational cost tracking

### `W5` Distribution and release

- GitHub release operations
- optional website/CDN front door
- store metadata
- release website

### `W6` Android

- runtime parity
- update parity
- validation parity

### `W7` Publications

- matching paper
- SotM application/system paper or talk
- architecture paper maintenance

## 8) Immediate next actions

These are the highest-priority tasks right now.

1. Generate a new Karlsruhe full bundle and lock the seed baseline.
2. Rebuild the bundled iPhone seed DB from that exact bundle.
3. Run device validation and real-drive logging on the fresh seed.
4. Fix any seed-breaking runtime or legal-fallback defects.
5. Generate and validate the first real Karlsruhe incremental update chain.
6. Keep Android, store links, and public website CTAs out of the critical path until steps 1-5 are done.

## 9) Explicit non-goals until the gates are cleared

- No public Android download promise before an Android app exists.
- No public App Store / Play Store CTAs before store artifacts exist.
- No multi-region incremental rollout before Karlsruhe incremental sync is proven.
- No website-specific update protocol before the GitHub-based bundle contract is stable.
- No broad scientific claims before route-level evidence supports them.
