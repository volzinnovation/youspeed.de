# StreetShots Survey AI strategy and reference benchmark

Status: proposed engineering protocol, 12 November 2026. The product owner specified **all StreetShots inventory objects** as the benchmark scope and supplied seven routing-engine GPX reference tracks, including outbound and return routes for autobahn coverage and a short test loop. **Begin model evaluation and improvement on R07, the test loop**, then expand successful candidates to the six longer routes. Traffic signs, supplementary plates and readable sign text retain dedicated evaluation tasks within that broader scope. StreetShots Survey is the current product name used here; the earlier product concept uses OpenSignMap.

**Build a trusted, repeatable survey benchmark before selecting another model architecture.** Keep the current detector plus classifier as the traffic-sign baseline, compare a small number of challengers, and judge the complete survey by correctly inventoried physical objects and correctly identified street changes. The standard comparison layer is an immutable collection of recordings, reviewed labels and evaluation rules. Repeated drives extend the evidence about operating conditions and change over time.

The product has two distinct promises: a first survey creates a reviewed inventory; an updating survey finds supported additions, removals and changes. A detection missing from a later run is insufficient evidence of removal. An object newly found by a better model is not necessarily newly installed.

This protocol adds survey and evaluation contracts. It does not change YouSpeed's governed speed-limit reference state machine or the apps' marketing version 1.5.

## Starting point

The current bundled German pack is `de-youspeed-reviewed142-v1`, with the SGBlur detector and reviewed 142-output classifier. The November 11 device trial separately activates a YOLO26n detector, left/right input windows, merged proposals and an SGBlur fallback. These are different pipeline configurations even when they share the classifier and app build. Record the active detector and fallback events, not just the bundled pack name. [Current model and device evidence](DE142_REVIEWED_CLASSIFIER_2026-11-11.md).

Existing native benchmarks already pin image bytes, output order, model hashes, compute policy and numerical parity. They are useful component tests. The recent one-image phone timings do not establish sustained route throughput, thermal behavior or survey accuracy. The September model-selection registry and M0 shadow design are historical planning material, not a sufficient description of the current deployed baseline. [Android harness](../../scripts/android/classifier-benchmark/README.md), [iPhone harness](../../iphone/ClassifierBenchmark/README.md), [historical registry](../../shared/tsr/model-selection-v1.json).

The survey concept already separates observations, model predictions, review revisions, physical-sign hypotheses and road assertions. Preserve this separation. Current Inspector groups can help reviewers, but their identities depend on observations and class-based grouping; they are not yet durable physical-asset IDs. [Evidence model](../OPENSIGNMAP_CONCEPT_2026-11-04.md#evidence-and-the-speed-sign-database), [current grouping](../../scripts/tsr/collection/panoramax_sequence_bridge.py), [group identity](https://github.com/volzinnovation/streetshots-inspector/blob/main/scripts/inspector/build_place_sign_review.py).

## Full inventory scope

Define a versioned inventory object catalogue before claiming benchmark completeness. The current StreetShots implementation provides traffic-sign recognition, supplementary OCR and generic survey imagery/observations; a complete authoritative catalogue of other inventory object types has not yet been identified. Generic storage and image capture do not establish recognition support for every object type.

For every catalogue type, specify a stable semantic code, physical unit of identity, required attributes, persistence/change semantics, annotation geometry and observability criteria. Distinguish fixed inventory assets from transient scene objects. Record whether each pipeline can detect, classify, read attributes and associate that type. Unsupported types remain in the target coverage report rather than disappearing from the score. The current sign pipeline is one specialist baseline within this scope.

Use a shared capture, tracking, inventory and change-evidence layer, with type-specific perception and attribute readers. Evaluate a general object detector alongside specialist sign detection/classification/OCR where the catalogue calls for it. Keep per-type results and a preregistered macro aggregation so frequent signs cannot conceal missing capabilities for other types. Object types absent from the seven routes require separately identified reference examples; zero examples establish no recall. The initial catalogue and its exact supported/unsupported capability matrix are implementation deliverables, not inferred existing capabilities.

## Seven reference routes

| Stable route ID | Direction and required waypoint | Revision 1 distance |
| --- | --- | --- |
| `ss-r01` | Bad Herrenalb → Gernsbach → Caracalla Therme | Approximately 24 km |
| `ss-r02` | Caracalla Therme → Ottenau → Bad Herrenalb | Approximately 23 km |
| `ss-r03` | Bad Herrenalb → Pforzheim | Approximately 31 km |
| `ss-r04` | Pforzheim → Bad Herrenalb | Approximately 31 km |
| `ss-r05` | Caracalla Therme → Pforzheim, with autobahn coverage intent | Approximately 65 km |
| `ss-r06` | Pforzheim → Caracalla Therme, autobahn return | Approximately 65 km |
| `ss-r07` | Short test loop in supplied point order; first route for model iterations | Approximately 1.7 km |

The seven planned geometries are registered in **route-set revision 4**, with each individual route at `route_revision = 1`. The private reference route set under `shared/survey/reference-routes/` contains the original GPX, source metadata, hash manifest and normalized GeoJSON. Revisions 1–3 retain the earlier snapshots; R01–R06 are unchanged by the addition of R07. R05 and R06 use exact shared directed vertices to align their Pforzheim approaches. R07 preserves all supplied points, including revisits, without adding a closing segment. Intermediate place labels come from the route description; the GPX files do not embed named waypoints.

These are routing-engine plans, not recorded drives. GPX metadata times are export metadata; no points have observation timestamps. Actual captures retain their own measured trajectories and media. Start/end gate radii, corridor tolerance and checkpoint rules remain to be defined in the benchmark protocol. A permanent routing change creates a new revision. A detour is recorded as a deviation, with only its eligible common segments used in the primary comparison. Preserve skipped distance and objects in coverage reporting. Attach route distance and segment/direction IDs so captures with different speeds can be aligned spatially.

Shared road sections and shared physical objects have common identities across routes. Outbound and return drives are different observation opportunities, but are not independent geographic test sets. A front-facing rig also does not establish complete coverage of all inventory objects or sign faces on both sides of a road; report coverage for the intended field of view and directions.

R05 and R06 add the intended autobahn operating condition in both directions. Annotate motorway entry/exit chainages and road classes against a pinned road-data snapshot before producing road-class scores; the supplied GPX has no such labels. Keep motorway segments separate from urban and other approaches, and do not treat whole route lengths as motorway coverage. Evaluate actual viewing-window duration, detection before leaving view, real-time deadlines and skipped-frame losses, with overhead/multiple/lane-specific signs where present. Use observed capture speeds, not assumed motorway speeds. Road class becomes a diagnostic slice alongside weather, object type and visibility; overlapping slices still follow the fixed weighting rules below.

## Begin with the short test loop

R07 is the development entry point for fast iterations. First capture both phones on the loop, review all observable inventory objects and visibility windows, and freeze the media/labels as the initial loop benchmark. Run the baseline and each candidate on those identical recordings, then validate promising changes on a fresh live traversal. Keep fixed-media quality changes separate from capture/weather changes. `ITERATION_WORKFLOW.md` in the private route set defines capture records, scorecards and progression.

Prioritize missed observable objects, false positives, wrong class/value/text, duplicate or incorrectly merged objects, processing gaps and end-to-end timing. Track fixed errors and newly introduced regressions by physical-object and image IDs. Pin all model/pipeline settings for each result. No model-quality result exists from the GPX alone; recordings, reviewed labels and baseline predictions remain to be established.

Assign a distinct traversal ID to each lap, preserving the same physical-object IDs across laps. Record whether a lap starts a fresh session or follows a previous lap with persistent state. Use ordered route progress and timestamps to distinguish loop completion from merely returning near its start. The short loop cannot cover every catalogue type or establish sustained thermal/motorway performance; report missing coverage and progress to R01–R06 after local checks.

R07 shares sections with R01/R02. Its sites are development-exposed once used for iteration, including when encountered on another route. They cannot also serve as an independent holdout. All components share the same exposure ledger; qualification on separate protected geography remains necessary.

## The standard benchmark layer

Create one versioned evidence collection with four evaluation lanes. Each lane answers a different question; retain separate results rather than combining them into one unexplained accuracy number.

| Lane | Fixed inputs | What it establishes |
| --- | --- | --- |
| Component and export | Canonical RGB tensors, reviewed crops, checkpoint and native exports | Classifier quality, detector diagnostics and numerical agreement between runtimes |
| Full pipeline replay | Identical full frames/clips, timestamps and relevant sensor context | Detection, classification, OCR, tracking and assembly quality under reproducible inputs |
| Paired live capture | Simultaneous Android/iPhone recordings of the same drive | Actual capture coverage, scheduling, sensor differences, sustained latency, thermal and energy behavior |
| Longitudinal survey | Reviewed physical inventory of all catalogue types and before/after captures | Correct asset association, inventory completeness and true changes across dates |

For full pipeline replay run both an offline mode that processes every prescribed input and a real-time mode that respects recorded timestamps, deadlines and each runtime's scheduling. Report skipped/late frames and resulting missed encounters. An offline pipeline that eventually finds every sign may still fail on a moving phone.

Use the following processing matrix on both Android-origin and iPhone-origin recordings:

| Capture source | Android runtime | iPhone runtime | Pinned server pipeline |
| --- | --- | --- | --- |
| Frozen Android frames | Replay | Replay | Replay |
| Frozen iPhone frames | Replay | Replay | Replay |

The matrix isolates source-image quality from processing differences. Export parity additionally uses identical canonical tensors to isolate preprocessing. Each row must contain the same source bytes; decoding, resize, color conversion, orientation, crop/window selection, precision and thresholds belong to the pipeline identity. Native-camera runs remain a separate product comparison.

Treat **Panoramax server processing as a named, pinned pipeline**, with instance, software/container revision, detector/classifier hashes, configuration and input representation. Its public annotation service is also an operational lane: record upload completion, resizing or blurring, processing state, queue delay, inference time and output retrieval. An unfinished or failed job is missing processing, not an empty scene. If the production instance does not expose enough provenance to reproduce a run, label it an observational service snapshot, not a reproducible model baseline.

Panoramax supports detection/classification model qualifiers on annotations; retain them along with item/annotation IDs, retrieval time and a hashed response snapshot. Tags alone need not identify the exact weights. Public machine annotations are predictions, and later human edits must be distinguished from those predictions. [Panoramax semantics documentation](https://docs.panoramax.fr/backend/install/deep_dive/semantics/).

Compare full target-catalogue coverage as well as a clearly labelled common-class subset. Unsupported classes remain visible in the end-to-end scorecard; silently excluding them can make a weaker pipeline appear better. Larger offline server models can have a different compute budget, but their latency and resource cost must be reported alongside quality.

## Captures and ground truth

Retain continuous or sufficiently dense regularly sampled full-scene evidence independently of detector success. Detection-triggered crops alone cannot reveal what the detector missed or establish that a former sign location was empty. Keep original media outside the source tree in a durable, access-controlled evidence store; manifests, hashes and contracts can live in Git. Preserve explicit missing-media and processing states.

Each capture session records route/revision, UTC exposure timestamps and local timezone, clock alignment and uncertainty, track/pose accuracy, camera/lens/resolution/frame rate/orientation, mounting geometry, app/core build, active pipeline, enabled streams, charging, thermal state and gaps. Align both phones to a shared visible/time event and retain measured clock offsets. Alternate mount positions across suitable repeat sessions to assess position bias.

For the initial reference inventory, reviewers inspect full scenes from multiple useful passes, including objects absent from all model predictions. Annotate every in-scope object type and its required attributes, with explicit unknown/unreadable cases. The traffic-sign task additionally labels primary signs, plates, their associations, numeric values and readable text. Retain all-sign evidence before YouSpeed's road-applicability filtering. Opposite-side and side-road signs can matter to a survey even when they must not influence the driver's speed reference.

Ground truth needs three linked levels:

1. **Frame truth:** box/polygon or other type-specific geometry, object class/attributes, visibility, occlusion, pixel size and annotation completeness. Exhaustively annotate scored scenes; mark partially annotated regions as such. Known-box recall on partial labels cannot establish precision or mAP.
2. **Encounter truth:** the frames in which one physical inventory object can be observed during a drive, including the expected observation window and reasons it is unreadable or unavailable. For traffic signs the unit is the sign face/panel.
3. **Inventory and change truth:** reviewed asset identity, position with uncertainty, orientation, assembly/plate relationships and state at each surveyed date, with supporting before/after media.

Assign permanent UUIDs to physical inventory objects, with component/support/assembly relationships where needed. Traffic signs retain separate face/panel identities. Identity must not encode the current predicted class, model version, rounded GPS point or first detection. Preserve merge/split/replacement lineage and reviewer revisions. Keep camera position, estimated object position and applicable road distinct. Current heuristic roadside placement is a proposal, not surveyed ground truth. [Positioning implementation](https://github.com/volzinnovation/streetshots-inspector/blob/main/scripts/inspector/two_sighting_road_pose.py).

Use a second reviewer to adjudicate uncertain identities, disputed labels and every benchmark change event. Keep reference labels independent of the candidate being scored; prelabel the corpus before evaluating challengers. If a later audit finds a label error, issue a new annotation/benchmark revision and rescore every contender.

Separate algorithm inputs from evaluator truth. First-survey inference receives no reference asset catalogue. Update-survey inference may use only a pinned reviewed inventory and observations available before the later capture. Later adjudicated identities, visibility labels and change decisions are evaluator-only data. Bind the input inventory snapshot, prior-observation cutoff and association-policy revision in every update evaluation; do not let retrospective review leak into the algorithm's inputs.

## Weather and time comparability

Do not attempt to remove weather variation with an arbitrary correction factor. Freeze a reference panel containing recorded examples of relevant conditions, then run every model on that same panel. Continue collecting live drives to measure changes outside that panel. Research on traffic-sign video benchmarks confirms that condition type, severity and sign size affect performance; it does not supply a correction factor for these routes. [CURE-TSD study](https://arxiv.org/abs/1902.06857).

Tag conditions at segment/encounter level where they change: daylight/twilight/night, direct sun/backlight/shadow, dry/wet/rain/fog/snow, seasonal foliage, traffic occlusion, motion blur and lens/windscreen obstruction. Keep sign pixel size and visibility separate from weather. Begin with clear daylight, wet/overcast and low-sun/twilight captures on each direction; collect night or rarer weather when they are part of the intended operating scope. Repeat condition cells on different days. This is a collection starting point, not a statistically sufficient sample guarantee.

Report per-route and per-condition results with their eligible counts and coverage. For a headline reference score, freeze mutually exclusive scoring cells and their weights, or an explicit per-encounter weighting formula, before comparing candidates. Keep overlapping weather/visibility tags for diagnostic slices; do not count an encounter multiple times merely because several tags apply. Specify treatment of sparse cells and repeated assets across routes. A required condition absent from a candidate run remains missing and prevents a complete headline comparison; it does not silently get zero weight. Also retain an unweighted count-based result so the score is interpretable.

Use paired candidate-versus-baseline comparisons on the same encounters. Estimate uncertainty by resampling independent trips and physical sites/connected segments, accounting for repeated sightings of the same object; do not count adjacent frames as independent samples. With few trips, report the limited support and refrain from a decisive ranking.

R07 is the **development iteration loop**, followed by R01–R06 as the broader **operational regression suite**. Once examples guide tuning, they no longer provide an untouched generalization test. Maintain one shared exposure/split ledger across detector, classifier, OCR and any change model. Group physical sites, overlapping routes, sequences and near-duplicate images together. Reserve separate geography for generalization and future dates for temporal robustness; future dates at known sites do not constitute unseen geography. Unknown upstream training exposure must be disclosed. The prior detector experiment demonstrates why component-specific holdouts are insufficient. [Split contamination record](CITY_DETECTOR_EXPERIMENT_2026-11-10.md).

## Model improvement strategy

Keep one accepted baseline and a small, explicit challenger queue per task. Use the common error ledger to determine the next experiment: unsupported object type, no proposal, wrong class, unreadable attributes, wrong component/plate association, identity failure, capture gap or false change. More classifier training cannot recover an object excluded by the camera window or detector.

| Candidate | Question | Controlled comparison |
| --- | --- | --- |
| Current two-stage pipeline | What is today's reliable baseline? | Separate bundled SGBlur and active town-trial configurations |
| General inventory detection with specialist readers | Which catalogue types can we recover beyond the sign baseline? | Full target catalogue, per-type observability and explicit unsupported coverage |
| Detector or input-coverage change | Can we recover small/distant/edge signs? | Fixed classifier; measure proposal recall, extra proposals and sustained cost |
| Classifier and unknown rejection | Can we reduce wrong labels and false positives? | Fixed proposals plus reviewed crops; class-balanced metrics and rejection coverage |
| Compact joint detector/classifier | Does a single model improve whole-scene quality or mobile cost? | Same target semantics and complete frames, with native export checks |
| Larger offline server pipeline | How much inventory/review quality can extra compute buy? | Same recordings; separately report cost, turnaround and coverage |

Run oracle-crop classification and detector recall diagnostics alongside end-to-end scoring to identify the bottleneck. Measure small signs by source pixel size. Any tiling or resolution experiment includes the cost of additional proposals, classification and tracking. Optimize Android precision or model size only with checkpoint-bound export checks and end-to-end task results; numerical parity and ground-truth accuracy are different tests.

Treat plates and text as a separate visible capability: detection, primary/plate association, OCR and optional structured interpretation. The current live recognition contract is primary-sign oriented with a separate OCR lane; a good primary-class score does not establish complete supplementary-sign inventory. Unknown and unreadable should remain explicit outcomes. [Current recognition boundary](../../shared/tsr/README.md).

Use larger vision-language models initially for annotation suggestions, ambiguous-case review and training-data triage. Their outputs need evidence and adjudication; model agreement is not ground truth, especially when candidates share training data. Multi-view tracking and identity association deserve their own experiments because they directly affect inventory quality. Prolix provides a reusable comparison approach for deduplication and position hypotheses, not an authoritative inventory. [Prolix analyzer](https://gitlab.com/panoramax/clients/prolix/-/raw/main/docs/Analyzer_trafficsign.md).

## Versioning scheme

Use an immutable **pipeline release** as the unit users benchmark, with independently identifiable components. Human-readable names aid communication; full hashes and manifests establish reproducibility. Preserve existing pack IDs as aliases with their exact provenance rather than renaming historical evidence.

| Object | Illustrative identity | Required binding |
| --- | --- | --- |
| Inventory taxonomy | `ss-inventory-taxonomy@1.0.0` | Full object catalogue, identity units, required attributes, change semantics and type mappings |
| Specialist sign taxonomy | `ss-signs-de@1.0.0` | Semantic sign codes, output order, unknown classes, mapping hash |
| Training data | `ss-train-de@1.0.0` | Raw/annotation hashes, split and exposure ledger, sources |
| Detector and classifier | `ss-det@1.1.0`, `ss-cls-de@1.0.0` | Architecture, training code/config/seed, initialization and selected checkpoint |
| Native artifact | `ss-det@1.1.0/coreml-fp16` | Exact bytes/tree hash, exporter and settings, source checkpoint, parity evidence |
| Pipeline | `ss-survey@1.0.0` | Supported object tasks, specialist components, preprocessing, windows, NMS, thresholds, calibration, OCR, tracking, association and fallback policy |
| Benchmark | `ss-commute@1.0.0` | Route revisions, frozen media, truth, splits, scoring/matching/visibility rules, condition weights and evaluator commit |
| Capture session | UUID | Route/revision, device/camera profile, times, conditions and source-media manifest |
| Evaluation run | UUID | Pipeline + benchmark + exact device/runtime/software + outputs and logs |
| Inventory snapshot | `ss-inventory@0001` | Asset/review revisions, observation dates, evidence and delta-policy revision |

These names are examples, not issued releases. Apply semantic versioning to contracts and pipeline releases: **major** for incompatible semantic/schema changes; **minor** for compatible capability or prediction changes, including new weights, thresholds, crop policy, quantization or association behavior; **patch** for metadata/packaging fixes with no intended prediction change, supported by equivalence checks. Every rebuilt artifact gets its own hash even if intended behavior is unchanged. Never reuse an output index for a different meaning.

For benchmarks, major means changed task, matching or aggregation semantics; minor means added/replaced evidence; patch means a label/metadata correction within the same task. All revisions are immutable. Compare models within the exact same benchmark revision; a patch can change scores and therefore still requires rescoring. Training runs are unique even when their configurations match.

A run's identity is the tuple:

`pipeline release + native artifact hashes + benchmark release + capture/input hashes + runtime/device configuration + evaluator revision`

The manifest also pins the app/core commit, detector activation/fallback trace, survey review policy and any input inventory snapshot with its prior-observation cutoff. Separate app release, model release, dataset revision and inventory time. An app build, class count or mutable `latest` URL is insufficient. A policy change that affects survey deltas requires a new pipeline/policy revision even with identical neural weights.

Build on existing model-pack and evaluation provenance; add a top-level benchmark/run manifest referencing those contracts. Do not pretend the current evaluation schema already describes all survey/delta entities. Keep a small authoritative release index linking manifests and qualification status (`candidate`, `benchmark-qualified`, `retired`); status changes do not mutate the underlying release bytes. [Pack contract](../../shared/tsr/model-pack.schema.json), [evaluation contract](../../shared/tsr/model-evaluation.schema.json).

## First inventory and update surveys

First survey flow: capture → detect/read → assemble encounters → associate physical assets → review → create inventory snapshot. Preserve unknown object candidates and unresolved identity instead of discarding them. Saved survey evidence needs durable retention and acknowledged synchronization; the existing best-effort training contribution stream cannot serve as the inventory ledger. [Contribution contract](../../shared/tsr/collection-upload-v2.md).

For each expected asset in an update survey, record whether it was observed unchanged, observed with different attributes, adequately observable but not found, occluded/unreadable/outside view, unavailable because of capture/processing failure, or ambiguously associated. Define benchmark observability from reference geometry and inspectable images, independently of whether a detector succeeded. It requires the correct side/facing direction, useful pixels/exposure and adequate pose/timing. Processing completion is a separate state: skipped, timed-out or failed inference on an otherwise observable encounter remains a miss in real-time/end-to-end scoring. It cannot support a physical-removal claim. A processed-only diagnostic may be reported with its own clearly named denominator.

| Evidence | Survey meaning |
| --- | --- |
| Previously uncatalogued object, without a suitable earlier view | Newly discovered; installation date unknown |
| Object present now, with reviewed earlier absence at the same location | Candidate addition within a bounded time interval |
| Prior object, no later model detection | Unresolved until visibility and identity are checked |
| Clear later view of the prior location shows absence | Candidate removal; inspect and corroborate |
| Same asset, corrected model class or better estimated position | Inventory correction, not street change |
| Same site, visibly different panel/value/plate | Candidate replacement or attribute change, with lineage |
| Occlusion, glare, unreadable image or processing gap | Unknown; schedule a suitable revisit |

Start with human confirmation of additions, removals and replacements. Require inspectable before/after evidence and preferably a second independent visit or field check for removal. Two misses alone are not proof: systematic errors, foliage and occlusion can persist. Adjacent frames or two related models do not count as independent corroboration. Keep `candidate → needs evidence/review → confirmed/rejected` decisions with reasons and evidence; retain removed-asset tombstones and the interval between last confirmed presence and first confirmed absence. Distinguish temporary absence/covering where evidence supports it.

When the model changes, reprocess both survey dates with the same pipeline. For diagnosis, compute the full matrix:

| | Earlier recording | Later recording |
| --- | --- | --- |
| Previous pipeline | A | B |
| Candidate pipeline | C | D |

A versus C and B versus D expose model-induced differences on fixed imagery. A versus B and C versus D still contain both possible street changes and capture-condition changes, so they require visibility checks and review. **Comparing A directly with D must never be the sole basis for a physical delta.** If old evidence is unavailable, mark a model-era discontinuity and re-establish reviewed state; do not infer a change.

## Scorecard and qualification

| Outcome | Required measures |
| --- | --- |
| Frame/model diagnosis | Detector recall by pixel size, precision/mAP only on exhaustive labels, classifier macro/per-class metrics, confusion and unknown/rejection rate |
| First inventory | Precision/recall per physical object and catalogue type, correct attributes/component association, duplicate assets, incorrect merges and geometry error with reference uncertainty; sign faces/plates remain a specialist breakdown |
| Observation coverage | Target/supported/observed object types, traversed distance, usable imagery, processed encounters, readable attributes, unresolved opportunities and gaps by cause |
| Update survey | Addition/removal/replacement precision and recall separately; false change candidates per 100 reviewed unchanged observable assets and per eligible route-km |
| Review workflow | Candidate count, adjudicated count, confirmed changes, review minutes, visits/time to confirmation and unresolved backlog |
| Runtime | End-to-end p50/p95 latency, analyzed/skipped frames, usable encounters, sustained thermal state, memory, energy per route-hour and actual/reported fallback |

Report automatic candidate accuracy separately from the final reviewed inventory. Also report recall and abstention: emitting no changes must not appear as perfect precision. Zero predicted changes makes precision undefined; a benchmark containing no real removals cannot establish removal recall. Exclude unresolved truth from precision/recall only with its count and selection reason reported.

Inventory recall needs both the fraction of reference assets with an adequate observation opportunity and recognition recall within those opportunities. Show total route inventory recovery as well, so a narrow camera view cannot hide behind a high conditional score. Attribute correctness and physical identity remain distinct from object detection. Report change metrics per object type and apply its defined persistence/change semantics; do not interpret movement of a transient scene object as removal of a fixed inventory asset.

Freeze matching tolerances, confidence/abstention settings, condition weights and candidate promotion criteria using development data before opening the qualification results. Choose tolerances from measured pose/annotation uncertainty; avoid an arbitrary GPS-radius match that merges adjacent signs. Use one-to-one reference matching and report ambiguous cases. Never tune gates on the protected test.

Initially, a release qualifies only when provenance is complete, required platform/export checks pass, both native implementations preserve shared behavior, route/condition coverage is reported, and no unresolved critical regression remains. Quantitative improvement and non-inferiority margins must be registered after the first baseline establishes sample support, before comparing challengers. Until genuine additions/removals have enough independent reviewed examples, advertise inventory/regression results and keep delta decisions under review; synthetic changes only test mechanics.

## Implementation order

1. **Pin the loop baseline and catalogue.** Seven planned routes are registered in route-set revision 4, each at route revision 1. Start with R07. Define/version the full inventory object catalogue and per-pipeline capability matrix, retaining unsupported/absent categories explicitly; register bundled and active-trial sign pipelines separately, and specify capture profiles, lap/gate rules and evaluator requirements. Deliverable: baseline manifests and loop capture protocol.
2. **Build the loop reference evidence and physical inventory.** Capture both phones together, retain full scenes, annotate object identities and visibility, and adjudicate the initial loop catalogue. Deliverable: immutable loop development benchmark with explicit missing coverage and common exposure ledger.
3. **Compare baseline and candidates on the loop.** Extend existing native component harnesses to full-frame/time-aware replay and add a pinned server adapter. Prioritize the largest measured failure source, change one component at a time where practical, and check fresh live laps after replay. Deliverable: paired same-recording scorecards, fixed errors/new regressions, runtime evidence and reproducible artifacts.
4. **Expand successful candidates to R01–R06.** Complete the wider inventory, road-class annotations and condition coverage; run longer capture/replay and motorway checks. Deliverable: broader regression results, sustained runtime reports and separate protected-geography qualification.
5. **Add reviewed update surveys.** Associate later passes to the asset registry, replay both dates with a fixed pipeline, and review candidate changes. Deliverable: longitudinal examples, false-alert/recall/coverage reporting and revisit queue.

The first milestone is a trustworthy baseline and a repeatable improvement cycle on R07. The longer routes then establish whether loop improvements hold across the wider operating conditions and support reliable StreetShots Survey inventories and updates.
