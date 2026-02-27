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

## Crowdsourced Speed Intelligence
When the product reaches meaningful adoption, YouSpeed should support two acquisition channels while users are driving.

The first channel is on-device computer vision, where the smartphone camera sees the road ahead and detects speed-related traffic signs. The second channel is voice input with speech recognition, where drivers report speed-sign changes, temporary restrictions, or inconsistencies hands-free. Both channels produce candidate observations, not immediate ground truth.

Each observation should update a local user-side traffic-sign layer first. That local layer can immediately improve device behavior in known locations, with confidence flags and decay rules. The same observations then enter a global confirmation pipeline, where third-party corroboration determines whether a claim is promoted to shared data.

## Trust Model Without User Accounts
YouSpeed is intended to work without user authentication. Identity is device-based, using pseudonymous device identifiers rather than personal accounts. This choice lowers friction and supports privacy goals, but it also creates data-quality and abuse-resistance challenges that must be solved in architecture, not policy text alone.

The trust model therefore needs explicit safeguards: source scoring per device, temporal and spatial consistency checks, minimum independent confirmations, and conflict handling when local evidence disagrees with external data. A single device report should never overwrite shared truth. Promotion to global data should require corroboration by independent devices and consistency with map geometry and legal plausibility constraints.

Runtime usage remains account-free. For OSM publication, uploads are attributable to individual contributors via an editor-mediated workflow: the app exports change files, and users upload with their own OSM account in JOSM/Merkaartor.

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

## App-Side Integration Challenges
Computer vision and speech recognition are independent technical domains and should be developed as separate subsystems, each with its own quality benchmarks, failure modes, and runtime budgets. Integration into the app should happen through a common observation contract so both channels produce comparable events for local storage, sync, and trust evaluation.

That separation is important for engineering velocity. CV can evolve with model and camera pipeline improvements, while speech can evolve with language handling and noise robustness, without destabilizing core inference and sync logic.

## Driving Corrections Strategy Reference
The implementation strategy for driving-safe local corrections, local-vs-baseline priority rules, local data capture/storage, and multi-user sync/OSM feedback is specified in:

- `paper/share/LOCAL_CORRECTIONS_STRATEGY.md`

## North-Star Outcome
YouSpeed aims to become a trusted open-data ISA retrofit platform: offline-capable, low-latency, and continuously improving through a combination of external map baselines and validated community observations. In that end state, the product is useful day to day, the data pipeline is auditable, and the research claims remain reproducible. The result is not only an app, but a reference architecture for how ITS research, mobile engineering, and crowdsourced map intelligence can work together responsibly.
