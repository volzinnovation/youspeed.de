# Scientific Review Report: YouSpeed Runtime Architecture

Date: 2026-03-06 (updated 2026-03-12)

Reviewed materials:
- `paper/share/VISION.md`
- `paper/share/TECHNICAL_ARCHITECTURE.md`
- `paper/techreport/main.tex`
- `iphone/SpeedConsumerApp/V3SpeedLimitService.swift`
- `iphone/SpeedConsumerApp/V3BundleManager.swift`
- `iphone/SpeedConsumerApp/DriveSessionViewModel.swift`
- `scripts/map/query_speed_limit_v3.py`
- `scripts/map/query_speed_limit_v4.py`
- `iphone/SpeedConsumerApp/SpeedConsumerTests.swift`
- `paper/share/references.bib`

External retrieval covered:
- foundational map-matching surveys and HMM papers,
- smartphone-specific and low-latency map-matching literature,
- current production-engine map-matching documentation,
- current single-file tile/archive formats as deployment comparators.

PDF verification status:
- `paper/techreport/main.pdf` was rendered with `pdftoppm` and cross-checked with `pypdf` text extraction.
- Rendered pages 1, 8, 12, and 17 were visually inspected. No obvious clipping, broken figures, unreadable tables, reference corruption, or layout defects were observed on those pages.
- The rendered PDF does not materially change the scientific review relative to the TeX source. In particular, the overclaim in the abstract is present in the rendered document as well.

Residual limitation:
- This was a targeted rendered-page inspection, not a page-by-page manual audit of all 17 pages.

## Track A refresh (2026-03-12)

This report now also covers the `2026-03-12` Track A evidence refresh for the current manuscript pair:
- `paper/itsc2026/main.tex`
- `paper/personalized_matching_arxiv/main.tex`
- `paper/personalized_matching_arxiv/data/*.tex`
- `tmp/hindsight_match_summary.json`
- `tmp/hindsight_training_summary.json`
- `tmp/hindsight_model_benchmark.json`
- `tmp/current_matcher_metrics.json`
- `scripts/iphone/collect_current_matcher_metrics.swift`

### Refreshed corpus inventory

1. Offline hindsight benchmark:
   - 7 retained non-subset inspector logs,
   - 9,636 matched fixes,
   - 2,417 selected-way runs,
   - 2,408 transitions,
   - 5,513 hindsight pseudo-label examples,
   - 381 switch-positive examples.
   - 3 additional logs are dropped from the train/validation/test split as strict subsets or duplicates.

2. Closed-loop replay corpus:
   - all 10 available inspector logs,
   - 11,351 replayed fixes,
   - 6,529 hindsight-labeled replay examples.

3. Geometry regression corpus:
   - 2 dedicated geom logs,
   - 2,598 replayed fixes,
   - 1,410 hindsight-labeled examples.

### Refreshed route-level findings

1. The retained offline benchmark no longer supports the earlier winner narrative.
   - The current final matcher remains maximally conservative at `90.66%` accuracy, `0.00%` switch recall, and `100.00%` keep-current accuracy.
   - The best offline result is now the three-way fixed-lag smoother at `94.20%` accuracy, `55.34%` switch recall, and `98.20%` keep-current accuracy.
   - The lowest-distance baseline remains a strong non-learned comparator at `90.75%` accuracy and `54.37%` switch recall.

2. The closed-loop replay is materially broader and stronger than the stale manuscript macros.
   - Replaying all 10 inspector logs yields `95.99%` overall accuracy, `72.19%` switch recall, and `97.76%` keep-current accuracy.
   - The deployed three-way gate activates `3,118` times in that replay.

3. The dedicated geometry replay is useful but not yet a full stability closure.
   - On 2 geom logs, replay reaches `96.60%` accuracy and `76.77%` switch recall.
   - The same corridor profile still shows `89` way-ABA oscillations and `49` same-ref-ABA oscillations, so route-level stability remains an active issue rather than a solved one.

4. The refreshed profile comparison weakens blanket corridor-preference claims.
   - Under the current common-score weighting used in `tmp/current_matcher_metrics.json`, the baseline profile scores `88.23` versus `87.73` for the corridor profile.
   - Corridor still wins on raw replay accuracy and switch recall, but it is larger and slower, so the combined profile ranking is now a tradeoff rather than a one-direction result.

### Track A decision

Decision: defer the external submission package for `paper/itsc2026/` in its current cycle.

Reasoning:
1. The architecture paper remains a benchmark-scoped microstudy over one fixed probe and heterogeneous update proxies, not an end-to-end ISA validation.
2. The refreshed route-level evidence belongs mainly to the matcher paper and does not close the external-validity gap for the architecture paper.
3. The updated profile comparison replaces the earlier simple corridor-wins narrative with a baseline-versus-corridor tradeoff, which needs more careful framing before submission.

Priority if only one manuscript receives further effort:
1. Prioritize `paper/personalized_matching_arxiv/` as the living evidence vehicle, because it now reflects the refreshed offline and replay data.
2. Keep `paper/itsc2026/` deferred until route-level accuracy, benchmark scope, and claim support are aligned in one package.

## Executive verdict

The project is technically coherent as an offline-first runtime-data architecture effort for open-data speed-limit inference. The strongest part is the storage, update, and bundle-routing design: immutable regional bundles, local routing by coverage metadata, and actual delta-application support in the iPhone runtime are all defensible engineering choices.

The paper is not yet strong enough to support its broader scientific claims about practical ISA impact or safety relevance. The current evaluation is a narrow microbenchmark, not an end-to-end ISA validation. Several implementation-text mismatches also need correction before the paper can be read as a rigorous account of the current system.

## Pass 1: Critical Review Of The Local Technical Approach

### 1. What is already strong

1. The vision and the implementation are aligned on the high-level operating model.
   - The vision explicitly separates current scope from the north-star architecture and keeps the critical path offline-first, local-first, and editor-mediated for OSM publication.
   - The paper reflects that separation in the technical vision section (`paper/techreport/main.tex:64-155`).

2. The bundle architecture is the strongest part of the system.
   - The app implements coverage-aware regional bundle routing with bbox prefiltering and optional polygon checks (`iphone/SpeedConsumerApp/V3BundleManager.swift:305-350`, `iphone/SpeedConsumerApp/V3BundleManager.swift:1442-1466`).
   - The app also implements actual delta-chain selection and SQL-patch application instead of treating updates as a purely conceptual future feature (`iphone/SpeedConsumerApp/V3BundleManager.swift:696-819`).
   - This is consistent with the paper's argument that the main contribution is a runtime-data architecture rather than a novel map-matching algorithm (`paper/techreport/main.tex:58-62`, `paper/techreport/main.tex:377-407`).

3. The current matcher is materially more mature than a naive nearest-way lookup.
   - The runtime uses heading-aware geometric scoring, continuity preservation, tunnel gating, and a small beam over recent hypotheses (`iphone/SpeedConsumerApp/V3SpeedLimitService.swift:260-349`, `iphone/SpeedConsumerApp/V3SpeedLimitService.swift:411-495`, `iphone/SpeedConsumerApp/V3SpeedLimitService.swift:860-1040`).
   - That makes the current implementation a credible "lightweight sequence-aware" matcher, even if it is not a full route-level HMM.

4. The local-override path is real and sits above the map lookup, which is the right precedence for the current product phase.
   - `DriveSessionViewModel` applies active local speed corrections before publishing the displayed speed limit (`iphone/SpeedConsumerApp/DriveSessionViewModel.swift:2446-2470`).

### 2. High-priority scientific weaknesses

1. The paper overclaims what the evaluation demonstrates.
   - The abstract moves from runtime microbenchmarking to "strongly support the EU traffic safety vision of reduced crash severity" (`paper/techreport/main.tex:32-34`).
   - Nothing in the current evaluation measures speed-limit correctness, warning quality, driver behavior, or crash-related outcomes. The present evidence supports an architecture-selection claim, not a safety-effect claim.

2. The evaluation protocol is too narrow for the strength of the conclusion.
   - The benchmark uses one fixed Berlin probe point with a fixed heading and top-k setting (`paper/techreport/main.tex:422-445`).
   - The reported on-device execution note describes only one executed country-scale run (`paper/techreport/main.tex:424`).
   - The final scenario ranking is then generalized into a preferred operating point (`paper/techreport/main.tex:525`, `paper/techreport/main.tex:561-575`).
   - This is acceptable as a microbenchmark but not as a general deployment conclusion.

3. The benchmark harness is not the same as the current app runtime.
   - The paper documents the current iPhone runtime as continuity-aware and sequence-aware (`paper/techreport/main.tex:121-145`).
   - The benchmark scripts are simpler: they score candidate rows, optionally do polyline refinement, and then choose explicit speed or urban/rural default without local overrides, tunnel gating, or mini-HMM selection (`scripts/map/query_speed_limit_v3.py:649-725`).
   - That does not invalidate the storage benchmark, but it does mean the paper should clearly separate "architecture microbenchmark harness" from "production app inference path."

4. The paper misstates what the built-up-area benchmark is actually measuring.
   - The paper says the Berlin probe resolves inside-city "via explicit administrative polygon containment" (`paper/techreport/main.tex:527`).
   - The current app derives `insideCity` from highway-class precedence first, then residential polygon containment, while administrative polygons are used for city labels and traceability (`iphone/SpeedConsumerApp/V3SpeedLimitService.swift:421-439`, `iphone/SpeedConsumerApp/V3SpeedLimitService.swift:1287-1525`).
   - The benchmark scripts likewise compute the built-up guess from residential polygons (`scripts/map/query_speed_limit_v3.py:677-720`; same structure in `query_speed_limit_v4.py`).
   - Administrative polygons matter in the app, but not in the way the evaluation sentence currently claims.

5. The final ranking mixes incomparable update proxies.
   - S1/S2 use invalidated cell/tile counts, while S3/S4 use simulated patch runtime (`paper/techreport/main.tex:543-550`).
   - Those heterogeneous proxies are then normalized into one 50/50 decision rule (`paper/techreport/main.tex:561-562`).
   - This ranking may still be directionally useful, but it is not a clean apples-to-apples optimization result.

6. The "speed envelope" table is not operationally meaningful in its current form.
   - The paper derives theoretical maxima up to `1449.3 km/h` and `808.8 km/h` for S3 (`paper/techreport/main.tex:463-468`).
   - The footnote correctly notes that location cadence, not query runtime, is the dominant real-world bound (`paper/techreport/main.tex:455`).
   - The table should be reframed as a query-throughput microbenchmark, not as an operational vehicle-speed envelope.

### 3. Local contradictions between vision, paper, and code

1. The paper understates the current matcher sophistication.
   - The related-work section says the implementation uses "lightweight continuity heuristics" rather than a multi-step probabilistic model (`paper/techreport/main.tex:60`).
   - The actual runtime already contains a beam-limited hypothesis tracker with transition penalties and decayed history (`iphone/SpeedConsumerApp/V3SpeedLimitService.swift:344-419`, `iphone/SpeedConsumerApp/V3SpeedLimitService.swift:860-1040`).
   - The accurate description is not "full HMM," but also not just static heuristics.

2. The current service-road policy conflicts with the vision text.
   - The vision says generic service-road contexts should receive reduced confidence and explicit caution (`paper/share/VISION.md:73-79`).
   - The current runtime hard-codes `service` into the in-city class set and assigns a `50 km/h` highway-class fallback (`iphone/SpeedConsumerApp/V3SpeedLimitService.swift:123-129`, `iphone/SpeedConsumerApp/V3SpeedLimitService.swift:609-618`).
   - That is an overconfident fallback in exactly the area where the vision argues for caution.

3. The Germany motorway fallback is legally inconsistent.
   - The methodology correctly states that Autobahn for passenger cars has a recommended `130 km/h` speed, not a universal mandatory maximum (`paper/techreport/main.tex:243-247`).
   - The current lookup code derives `130` from `motorway` or inherited `motorway` tags (`iphone/SpeedConsumerApp/V3SpeedLimitService.swift:598-612`).
   - If `insideCity` is known, the runtime then overrides any highway-class fallback to `100`, including motorway (`iphone/SpeedConsumerApp/V3SpeedLimitService.swift:444-455`).
   - So the current logic can yield either an implied legal `130` or an implied legal `100`, both of which are inconsistent with German law for unsigned Autobahn segments.
   - This is the most important implementation issue to fix before making broader ISA claims.

4. The tests encode part of the motorway assumption but do not close the end-to-end gap.
   - There is a unit test asserting `motorway -> 130` at the derivation helper level (`iphone/SpeedConsumerApp/SpeedConsumerTests.swift:13-19`).
   - There is no corresponding end-to-end test showing correct legal behavior for unsigned Autobahn segments after `insideCity` fallback is applied.

## Pass 2: Related Work Retrieval And Validation

### 1. Core literature signal

1. The classic literature consistently treats sequence context as central to robust map matching.
   - Quddus et al. survey geometric, topological, probabilistic, and advanced map-matching families, and explicitly frame the problem around uncertainty, road topology, and transport use cases.
   - Newson and Krumm's HMM formulation became the canonical baseline for noisy and sparse GPS traces.
   - Hunter et al.'s Path Inference Filter then sharpened that direction toward low-latency route inference.

2. Smartphone-specific work evaluates accuracy on trajectories, not only pointwise latency.
   - Bierlaire et al. report a probabilistic smartphone-GPS map-matching method with `98.9%` link identification accuracy and evaluation over `25` traces.
   - That is the right scale of evidence for claims about practical on-road inference quality.

3. Production systems expose uncertainty and transition controls as first-class API concepts.
   - OSRM exposes per-point `radiuses` and returns a `confidence` score for matchings.
   - Mapbox exposes the same operational ideas in its Map Matching API.
   - Valhalla Meili explicitly describes map matching as a combination of candidate search, route search, and measurement matching, with HMM-style transition reasoning.

4. The literature and current production practice both suggest that storage and inference must be separated analytically.
   - Your paper is correct to isolate the runtime-data layer as a meaningful systems problem.
   - But related work also shows that map-matching quality is usually judged on sequence continuity and route accuracy, not only candidate-retrieval speed.

### 2. Second-order citation trails followed

1. `Quddus 2007 -> Newson and Krumm 2009 -> Bierlaire 2013`
   - This trail validates that the field moved from taxonomic overview to HMM-style probabilistic matching and then to smartphone-specific validation.
   - It strengthens the conclusion that the paper needs route-level accuracy evaluation before making broader practical claims.

2. `Newson and Krumm 2009 -> later production/fast variants (Valhalla Meili, FMM family)`
   - This trail validates that modern systems continue to use candidate search plus transition reasoning, but optimize it for runtime constraints.
   - It supports the current YouSpeed strategy of staying lightweight on device, while also showing that sequence context remains scientifically important.

### 3. Deployment comparators for bundle packaging

1. Single-file, read-only tile/container formats are now well established.
   - MBTiles packages tiled data into a single SQLite-based archive.
   - PMTiles packages tiled data into a single read-only archive designed for low-request remote access.

2. This matters for the S2/S3 comparison.
   - The current S2 design is many-file and content-addressed (`paper/techreport/main.tex:386-389`, `paper/techreport/main.tex:424`).
   - Modern deployment formats suggest that "tiled" and "many small files" are no longer synonymous.
   - That does not weaken S3. If anything, it strengthens the paper's conclusion that single-file delivery deserves serious weight. It also suggests that a future S2 variant should be benchmarked as a single-archive tiled format, not only as a high-file-count directory layout.

## Pass 3: Synthesis And Resolved Conclusions

### 1. What conclusion survives the literature check

This conclusion is well supported:

> A single-file, spatially indexed embedded database is a credible default runtime packaging choice for the current YouSpeed phase, because it fits the offline-first mobile constraint set, keeps update/application logic manageable, and compares favorably to the currently implemented high-file-count tile-pack alternative.

This conclusion is not yet supported:

> The current paper demonstrates practical ISA effectiveness or safety impact beyond architecture-level runtime suitability.

### 2. How the apparent contradictions resolve

1. The storage result and the map-matching literature are not in conflict.
   - The literature says sequence context matters for accuracy.
   - Your paper mostly measures data packaging and query cost.
   - Those are complementary questions, but they must be written as separate layers of evidence.

2. The app is ahead of the paper text in some areas.
   - The current matcher is already a local sequence-aware design.
   - The paper should describe it as such, instead of contrasting it too sharply with probabilistic methods.

3. The paper is ahead of the implementation in other areas.
   - The policy around parking/service contexts is more careful in the vision than in the current fallback logic.
   - The legal treatment of German motorway defaults is more careful in the paper than in the current runtime code.

### 3. Publication-readiness assessment

Architecture contribution: promising.

Implementation maturity: moderate to strong for bundle delivery and routing; moderate for legal fallback semantics; still early for accuracy validation.

Scientific rigor: currently insufficient for broad practical claims because the main experiment is a narrow microbenchmark and the concluding language is too strong.

Claim alignment: partial. The paper and code are close enough that this is fixable, but not yet tight enough for a strong scientific review.

## Recommended next actions

1. Narrow the paper's main claim.
   - Reframe it explicitly as a runtime-data architecture benchmark and deployment study.
   - Remove or substantially soften language implying demonstrated crash-severity or practical ISA effect.

2. Separate the benchmark harness from the production runtime in the paper.
   - Keep the microbenchmark for S1-S4.
   - State clearly that the benchmark isolates storage/query architecture and does not reproduce the full iPhone matching stack.

3. Correct the built-up-area description.
   - Distinguish:
     - built-up classifier: highway-class precedence plus residential polygon containment,
     - city labeling: administrative/place context.
   - Update the sentence around `polycontainment` accordingly.

4. Fix the Germany motorway fallback before stronger deployment claims.
   - Do not encode a mandatory `130 km/h` legal limit for unsigned Autobahn.
   - Do not let the generic outside-city fallback collapse motorway behavior to `100 km/h`.
   - Add end-to-end tests for unsigned motorway, signed motorway, and motorway transitions.

5. Bring service-road handling back into alignment with the vision.
   - Reduce confidence for `service` and parking-like contexts unless explicit speed evidence exists.
   - Expose this as a source/confidence distinction in the runtime output.

6. Upgrade the experiment from microbenchmark to systems evaluation.
   - Use route corpora spanning urban, rural, motorway, tunnel, border, and bundle-switch scenarios.
   - Report route-level accuracy, continuity errors, tunnel false positives/false negatives, and end-to-end latency distributions.
   - Repeat measurements across multiple probes and times, not one fixed Berlin point.

7. Normalize update comparison metrics across all scenarios.
   - Compare actual transferred bytes, apply time, validation time, storage footprint, and failure/recovery behavior for S1-S4 under one common protocol.

8. Add one more architecture comparator if S2 remains strategically important.
   - Benchmark a single-archive tile format inspired by MBTiles/PMTiles-style delivery instead of only the current many-file tile-pack realization.

## Stop condition

More searching is unlikely to change the conclusion. The foundational literature, smartphone-specific validation work, production-engine documentation, and current archive-format comparators all converge on the same synthesis:

- the YouSpeed storage/update architecture is promising and the S3 preference is plausible,
- sequence-aware accuracy evaluation is still required,
- the current paper overstates what its experiment proves,
- and a small number of local code/paper mismatches should be corrected before stronger scientific claims are made.

## External sources used

Foundational and smartphone map matching:
- Quddus et al., "Current map-matching algorithms for transport applications" (2007): https://www.sciencedirect.com/science/article/pii/S0968090X07000470
- Newson and Krumm, "Hidden Markov map matching through noise and sparseness" (2009): https://www.microsoft.com/en-us/research/publication/hidden-markov-map-matching-noise-sparseness/
- Hunter et al., "The Path Inference Filter" (2014): https://ieeexplore.ieee.org/document/6620935
- Bierlaire et al., "A probabilistic map matching method for smartphone GPS data" (2013): https://infoscience.epfl.ch/entities/publication/e9196c1f-a165-4815-b3d2-67fd4b5616c6

Production-engine documentation:
- OSRM Match service: https://project-osrm.org/docs/v5.24.0/api/#match-service
- Valhalla Meili overview and algorithms: https://valhalla.github.io/valhalla/meili/
- Mapbox Map Matching API: https://docs.mapbox.com/api/navigation/map-matching/

Archive and packaging comparators:
- MBTiles specification: https://github.com/mapbox/mbtiles-spec
- PMTiles concepts: https://docs.protomaps.com/pmtiles/
