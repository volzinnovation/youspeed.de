# Aggressive Germany Launch Plan

Date: 2026-03-12

Public goal: YouSpeed is live in the German App Store by `2026-05-22`.

Visual timeline:
- [PROJECT_GANTT_2026-03-12.html](./PROJECT_GANTT_2026-03-12.html)
- [PROJECT_GANTT_2026-03-12.md](./PROJECT_GANTT_2026-03-12.md)

Execution threads:
- [launch_threads/README.md](./launch_threads/README.md)
- [launch_threads/TRACK_A_PAPER.md](./launch_threads/TRACK_A_PAPER.md)
- [launch_threads/TRACK_B_SEED_AND_MATCHER.md](./launch_threads/TRACK_B_SEED_AND_MATCHER.md)
- [launch_threads/TRACK_C_GERMANY_PIPELINE.md](./launch_threads/TRACK_C_GERMANY_PIPELINE.md)
- [launch_threads/TRACK_D_IPHONE_LAUNCH.md](./launch_threads/TRACK_D_IPHONE_LAUNCH.md)
- [launch_threads/TRACK_E_ANDROID_ALPHA.md](./launch_threads/TRACK_E_ANDROID_ALPHA.md)
- [launch_threads/TRACK_F_RELEASE_SURFACE.md](./launch_threads/TRACK_F_RELEASE_SURFACE.md)

This plan is grounded in:
- `RESEARCH_IMPLEMENTATION_PLAN.md`
- `paper/share/VISION.md`
- `docs/KARLSRUHE_INCREMENTAL_SEED_ROLLOUT.md`
- `iphone/SpeedConsumerApp/README.md`
- `iphone/SpeedConsumerApp/BundleTargets.top10.json`
- `docs/STANDUP_2026-03-06.md`

## Summary

Launch assumptions:
- public App Store launch on `2026-05-22`, not TestFlight or private beta
- Germany-wide launch using the existing regional-shard architecture
- full bundles only at launch across Germany; incremental updates are not a launch requirement
- paper deadline outranks noncritical launch polish if the two compete
- Android runs in parallel now as an internal-alpha track, but Android release parity does not block May 22

Launch contract:
- Germany launch uses the shard model already defined in `BundleTargets.top10.json`
- launch-day data promise is full-bundle download support for every Germany shard
- `delta_index` remains optional in launch manifests; its absence must not block download, activation, or routing
- the iPhone app must stop behaving like a Karlsruhe-only product; Karlsruhe remains the seed and validation baseline, not the public coverage boundary
- website launch copy must be Germany-only and iPhone-only; no Android public CTA before Android release parity exists

Existing interfaces to keep:
- keep `V3BundleManifest`, `V3BundleTargetsConfig`, `BundleArtifact`, and current coverage metadata as the launch contract
- do not introduce a new wire format before launch
- keep `YouSpeedV3ManifestURL` as a dev override only; launch behavior must prefer bundled Germany endpoint discovery
- Android alpha must consume the same manifest and target contract as iPhone

## Tracks

### Track A: Paper-critical evidence

Window: `2026-03-12` to `2026-04-05`

Objectives:
- refresh route-level evaluation from real drives and regression corpora
- freeze claims to what the evidence supports
- produce submit/defer decision by `2026-04-05`

Deliverables:
- paper artifact refresh completed
- route-level metrics tied to the current matcher implementation
- explicit submit or defer outcome

### Track B: Karlsruhe seed and matcher hardening

Window: `2026-03-12` to `2026-03-23`

Objectives:
- regenerate Karlsruhe full bundle and seed baseline
- rebuild bundled seed DB
- run seed-specific regression and real-drive validation
- fix legal fallback, startup recovery, and route-continuity defects

Deliverables:
- accepted Karlsruhe seed baseline
- bundled seed DB rebuilt from that exact artifact lineage
- launch-critical matcher defects fixed or triaged out of scope

### Track C: Germany shard data pipeline

Window: `2026-03-12` to `2026-04-20`

Objectives:
- generate and publish full-bundle assets for all Germany shards
- validate manifest correctness, coverage metadata, multipart handling, and release naming
- keep all non-Germany country work out of scope before launch
- keep shard incrementals out of the launch requirement

Deliverables:
- Germany shard full-bundle release set
- validated shard manifests and coverage metadata
- launch decision that Germany support is nationwide via shards

### Track D: iPhone Germany launch path

Window: `2026-03-20` to `2026-05-01`

Objectives:
- switch app behavior from Karlsruhe-first to Germany-shard-first discovery
- validate bundle picker, expected size display, activation, coverage routing, and first-run UX
- ensure launch-time install/update succeeds without `delta_index`
- produce a launch candidate by `2026-05-01`

Deliverables:
- iPhone launch candidate
- Germany shard discovery working from bundled targets
- full-bundle-only launch path validated

### Track E: Android internal alpha

Window: `2026-03-12` to `2026-05-22`

Objectives:
- build Android shell, shared manifest parser, target loader, seed/bootstrap flow, and one-shard full-bundle sync prototype
- reuse shared fixtures where possible
- reach a real internal alpha by `2026-05-22`, without turning Android into a public launch gate

Deliverables:
- Android app shell in active use
- manifest and target parsing against the same contract as iPhone
- one-shard full-bundle bootstrap path proven end to end

### Track F: App Store, website, and release surface

Window: `2026-04-21` to `2026-05-22`

Objectives:
- prepare App Store package, screenshots, support text, and FAQ
- correct website to iPhone-only Germany launch wording
- remove or hide Android public download path
- submit by `2026-05-08` to leave review and fix buffer before `2026-05-22`

Deliverables:
- App Store submission completed
- Germany-only, iPhone-only launch copy
- release FAQ and support copy ready

## Timeline

### Phase 1: now to `2026-03-23`

- lock May 22 as public Germany App Store launch
- lock Germany-wide shard scope and full-bundles-only launch policy
- freeze Karlsruhe seed baseline
- start Android alpha foundation immediately
- start paper artifact refresh immediately

### Phase 2: `2026-03-24` to `2026-04-05`

- finish paper evidence and submit/defer decision
- validate Karlsruhe full-bundle sync and active-DB recovery on device
- begin Germany shard publish runs and app-side multi-shard integration

### Phase 3: `2026-04-06` to `2026-04-20`

- publish and validate all Germany shard full bundles
- freeze Germany launch shard set as all Germany shards supported
- retain Karlsruhe seed only as baseline and safety fallback
- finish border-crossing and coverage-routing tests
- freeze app-side Germany launch behavior

### Phase 4: `2026-04-21` to `2026-05-01`

- produce iPhone launch candidate
- finish launch screenshots, support copy, FAQ, and website rewrite
- keep Android alpha moving, but do not allow Android churn to destabilize the iPhone/runtime contract

### Phase 5: `2026-05-02` to `2026-05-22`

- submit iPhone build by `2026-05-08`
- use `2026-05-09` to `2026-05-22` for App Store review fixes, release polish, and staged go-live preparation
- preferred go-live window: `2026-05-15` to `2026-05-16`
- hard go-live deadline: `2026-05-22`

## Milestones

| Milestone | Window | Goal | Exit criteria |
|---|---|---|---|
| `M0` Launch contract locked | `2026-03-12` to `2026-03-14` | Lock public Germany App Store launch assumptions | Germany-wide shards, full bundles only, paper priority, Android internal alpha accepted |
| `M1` Karlsruhe seed baseline frozen | `2026-03-12` to `2026-03-23` | Fresh Karlsruhe seed baseline accepted | regenerated bundle published, bundled seed rebuilt, seed regressions and real-drive validation completed |
| `M2` Paper submit or defer | `2026-03-12` to `2026-04-05` | Fit the paper deadline | route-level evidence collected and explicit submit/defer decision made |
| `M3` Karlsruhe full-bundle recovery validated | `2026-03-24` to `2026-04-05` | Prove launch-safe bundle recovery on device | full-bundle sync and active-DB recovery validated without requiring `delta_index` |
| `M4` Germany shard release set validated | `2026-04-06` to `2026-04-20` | Freeze Germany-wide launch coverage | all Germany shards published and validated with manifest correctness and coverage routing |
| `M5` iPhone launch candidate | `2026-04-21` to `2026-05-01` | Produce launch candidate | candidate stable, Germany discovery and routing frozen, launch-facing UX ready |
| `M6` App Store submission | `2026-05-02` to `2026-05-08` | Submit launch package | App Store package submitted and website copy aligned to actual scope |
| `M7` Preferred go-live | `2026-05-15` to `2026-05-16` | Preferred live window | app approved and ready for public Germany launch |
| `M7b` Hard go-live deadline | `2026-05-22` | Last acceptable launch date | public Germany App Store launch live by this date |
| `M8` Android internal alpha checkpoint | `2026-05-22` | Confirm Android parallel work is real | Android shell, manifest/target parsing, and one-shard bootstrap prototype working |

## Test Plan

### Launch-critical iPhone scenarios

- seed bootstrap from bundled Karlsruhe DB succeeds on clean install
- Germany shard discovery loads the full Germany shard set from bundled targets
- full-bundle download works for every Germany shard, including multipart DB assets where needed
- app activates a downloaded shard without requiring `delta_index`
- coverage routing works across at least three German state-border scenarios
- recovery works after interrupted full-bundle download
- recovery works after invalid manifest, missing asset, or checksum mismatch
- app continues to function when only the seed bundle is available
- website and app copy expose only Germany and iPhone launch promises

### Paper-critical scenarios

- route-level evaluation covers Karlsruhe plus difficult continuity, tunnel, and motorway transitions
- metrics are regenerated from current logs and tied to the actual matcher implementation
- final manuscript makes no unsupported claim about broader deployment or safety impact

### Android alpha scenarios

- Android parses the same bundled target config as iPhone
- Android fetches at least one real Germany shard manifest
- Android completes one full-bundle bootstrap path end to end
- Android stores enough artifact metadata to align later with iPhone release parity

## Assumptions and defaults

- launch country is Germany only
- launch platform is iPhone only
- Germany launch is nationwide via shards, not Baden-Wuerttemberg-only
- launch-day update promise is full bundles only
- incremental updates are a post-launch expansion, not a public May 22 promise
- Android is a parallel internal alpha by May 22, not a store launch
- paper deadline outranks noncritical launch polish if the two conflict
- weekends and long-day execution are assumed available, so the schedule intentionally maximizes parallel tracks instead of protecting a narrow single critical path
