# YouSpeed Vision

## Purpose
YouSpeed exists to make intelligent speed assistance practical for the vehicles already on the road, not only for newly manufactured cars. The product goal is an offline-first smartphone assistant that can infer local speed limits with low latency, high availability, and clear provenance of where information came from. The project goal is broader: to prove, with reproducible evidence, that open geospatial data plus careful runtime architecture can deliver safety-relevant functionality at real consumer scale.

This is intentionally a dual effort. One track is scientific and publication-driven, where architecture choices are benchmarked and documented under controlled conditions. The second track is product-driven, where those validated choices are integrated into a robust iPhone app with real update and reliability constraints. The two tracks are separated by design, but they must reinforce each other.

## Strategic Phases
YouSpeed should evolve in explicit phases rather than jumping directly to a fully crowdsourced map network.

1. Phase 1: Open data bootstrap. The system starts from OpenStreetMap and related rule-aware defaults to provide country-scale baseline coverage.
2. Phase 2: Product stabilization. The app focuses on fast offline inference, deterministic updates, and measurable reliability on consumer devices.
3. Phase 3: Community enrichment. Once install base and usage density are high enough, user-observed speed-sign information is added as a second signal layer, similar in spirit to Waze-style network effects.

The key principle is that crowdsourcing does not replace OSM; it augments it. Baseline map truth comes from external open data, while community signals improve freshness and local detail between external snapshot cycles.

## Current Scope vs North-Star (2026)
The architecture has a deliberate split between what is implemented now and what remains the long-term target.

Current scope (implemented baseline):
- Authoritative runtime baseline comes from OSM snapshots/diffs packaged into app bundles.
- Runtime is account-free and device-ID based.
- Runtime can route across multiple downloaded regional bundles using manifest coverage bbox/poly metadata.
- Local corrections are captured and applied locally first; publication is editor-mediated export (`.osc` package for JOSM/Merkaartor), uploaded by the user with their own OSM account.
- No direct app upload to OSM API and no centralized backend publication authority in the critical path.
- Local correction state can be flushed after user-led publication; convergence comes from subsequent OSM daily diffs.

North-star scope (future phase):
- Device-observation corroboration at broad install-base scale.
- Optional internal global cache for cross-device acceleration between OSM refresh cycles.
- Strict quality gates before any promotion of crowd signals beyond local scope.

## Current Naming and Bundle Scheme
The repository now uses region-scoped naming for generated v3 bundle artifacts.

- Manifest: `<region>_manifest.json` (for example `germany_manifest.json`, `karlsruhe-regbez_manifest.json`).
- Database: `<region>_speeds.sqlite` (or `<region>_speeds.sqlite.partNNN` for multipart releases).
- Bundle metadata includes `region` and `country_code`; app rule selection is derived from `country_code`.
- Target countries/regions are defined in `iphone/SpeedConsumerApp/BundleTargets.top10.json` (10 countries with highest maxspeed availability, including Germany).

## Crowdsourced Speed Intelligence
When the product reaches meaningful adoption, YouSpeed should support two acquisition channels while users are driving.

The first channel is on-device computer vision, where the smartphone camera sees the road ahead and detects speed-related traffic signs. The second channel is voice input with speech recognition, where drivers report speed-sign changes, temporary restrictions, or inconsistencies hands-free. Both channels produce candidate observations, not immediate ground truth.

Each observation should update a local user-side traffic-sign layer first. That local layer can immediately improve device behavior in known locations, with confidence flags and decay rules. Promotion beyond the local layer is phase-dependent: currently via editor-mediated OSM contribution and later, if activated, via corroboration-gated shared intelligence.

## Operational Inference Policy
The app must apply a deterministic inference order:

1. User explicit input and approved local override.
2. Way-level speed tags from baseline data (query modes: bbox, hybrid, polyline).
3. Legal rule fallback, which requires city/rural classification.

City/rural classification must combine multiple evidence sources:
- way-type precedence: if `highway` is one of `residential`, `service`, `crossing`, `living_street`, classify as in-city first,
- otherwise residential polygon containment.

Administrative/place context is used for city naming and traceability, not as the primary in-city classifier.
`traffic_sign=DE:310/311` is treated as optional enrichment only (not primary) due sparse tag coverage.

City name and street name resolution are first-class outputs, not debug-only metadata, because they are required for user trust, correction review, and export traceability.

## Tunnel and Multi-Level Road Handling
Current production strategy is intentionally simple and deterministic:

- if the resolved way carries `tunnel=yes`, the app marks tunnel context,
- speed display remains based on resolved way `maxspeed`,
- UI highlights tunnel state with an icon instead of showing current-speed-centric emphasis.

This avoids unstable portal-state transitions while preserving correct speed-limit context on tunnel-tagged segments.

## Parking and Service-Road Policy
Parking and service contexts require explicit treatment to avoid overconfident rule fallback:

- Keep parking-lot polygons and service-road tags in runtime data.
- Reduce confidence for generic service contexts without explicit speed evidence.
- Prefer explicit speed tags or validated local observations over class-based defaults in parking-like areas.
- Preserve auditable source attribution whenever a low-confidence fallback is used.

## Trust Model Without User Accounts
YouSpeed is intended to work without user authentication. Identity is device-based, using pseudonymous device identifiers rather than personal accounts. This choice lowers friction and supports privacy goals, but it also creates data-quality and abuse-resistance challenges that must be solved in architecture, not policy text alone.

Current deployment keeps publication editor-mediated and user-owned (JOSM/Merkaartor upload with personal OSM account), so there is no centralized backend write authority in the operational path.
The future corroboration model still needs explicit safeguards: source scoring per device, temporal/spatial consistency checks, minimum independent confirmations, and conflict handling when local evidence disagrees with external data. A single device report must not overwrite shared truth.

Runtime usage remains account-free. For OSM publication, uploads are attributable to individual contributors via an editor-mediated workflow: the app exports change files, and users upload with their own OSM account in JOSM/Merkaartor.

## Local Correction Lifecycle
Local correction flow is stateful and auditable:

1. Capture while driving (voice, lock-current-speed, or deferred note).
2. Mandatory post-drive review.
3. Local activation as confidence overlay (when evidence is sufficient).
4. Optional export package generation (`changes.osc` + review metadata).
5. User-led upload in JOSM/Merkaartor with individual OSM identity.
6. Optional user-entered changeset reference for traceability.
7. Local contribution flush once expected upstream convergence is accepted.

The flush capability is required operationally because upstream truth is re-ingested from OSM daily diffs, not pushed directly by the app.

## Data Ownership and Feedback Loops
YouSpeed should maintain a layered data model instead of one monolithic database.

- External baseline layer: imported from OSM and related official/open sources.
- Internal global cache layer: confirmed community observations managed by YouSpeed.
- Local device layer: unconfirmed and recently confirmed observations relevant to one user.
- Publication layer: contributions eligible for upstream feedback, including potential write-back to OSM where confidence and policy conditions are met.

This layered model supports two outbound paths for confirmed findings: feed back into YouSpeed's global cache for fast operational use, and optionally contribute to OpenStreetMap through controlled, auditable export processes. Upstream contribution should be deliberate and quality-gated, not automatic fire-and-forget.

## Synchronization as a Core Challenge
The hardest systems problem is synchronization across multiple truth sources with different latency and trust levels: local device observations, globally confirmed internal data, external map updates, and periodic app data bundles. This is not a background detail; it is a primary product requirement.

YouSpeed needs deterministic merge rules, versioned records, conflict precedence, rollback-safe activation, and bandwidth-aware delta sync. It must support offline accumulation, delayed upload, and eventual convergence once connectivity returns. It must also avoid destructive overwrite patterns when external baseline updates arrive after local crowd observations.

## Quantitative Phase Gates
Progression between phases must be controlled by measurable gates.

Core runtime gates (per release):
- On-device end-to-end inference latency (fix -> displayed result) with reported median and p95.
- Joint query budget including maxspeed retrieval and polygon containment.
- Daily-diff update operability (invalidations, patch/apply time, and transfer volume).
- Tunnel-mode correctness metrics (false tunnel activations, missed tunnel segments).
- Correction pipeline metrics: capture success, review completion, export success, and local-overlay retirement after upstream refresh.

Community-enrichment activation gate:
- Multi-device observation density and consistency must exceed a defined threshold before enabling any shared corroboration loop.
- Until that threshold is met, local-first behavior plus editor-mediated OSM contribution remains the default operating model.

## App-Side Integration Challenges
Computer vision and speech recognition are independent technical domains and should be developed as separate subsystems, each with its own quality benchmarks, failure modes, and runtime budgets. Integration into the app should happen through a common observation contract so both channels produce comparable events for local storage, sync, and trust evaluation.

That separation is important for engineering velocity. CV can evolve with model and camera pipeline improvements, while speech can evolve with language handling and noise robustness, without destabilizing core inference and sync logic.

## Driving Corrections Strategy Reference
The implementation strategy for driving-safe local corrections, local-vs-baseline priority rules, local data capture/storage, and multi-user sync/OSM feedback is specified in:

- `paper/share/LOCAL_CORRECTIONS_STRATEGY.md`

## North-Star Outcome
YouSpeed aims to become a trusted open-data ISA retrofit platform: offline-capable, low-latency, and continuously improving through a combination of external map baselines and validated community observations. In that end state, the product is useful day to day, the data pipeline is auditable, and the research claims remain reproducible. The result is not only an app, but a reference architecture for how ITS research, mobile engineering, and crowdsourced map intelligence can work together responsibly.
