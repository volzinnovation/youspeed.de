# OSM Science 2026 Pretalx Submission Fields

Use this file as a field-by-field copy/paste helper for the OSM Science 2026 Pretalx form.

Deadline note checked on 2026-04-27: Pretalx lists submissions as closing on `2026-05-11 23:59 (Europe/Paris)`. The State of the Map call page currently has inconsistent text: the submission-guidelines paragraph still says `27 April 2026`, while the timeline section says `11 May 2026`. Treat the Pretalx form deadline as the actionable deadline and submit before `2026-05-11 23:59 (Europe/Paris)`.

## Step 1: Title

OpenStreetMap as a Runtime Knowledge Base for Offline Smartphone Speed-Limit Assistance: A Reproducible YouSpeed Deployment Study

## Step 2: Submission Type

20 minute talk

## Step 3: Abstract

YouSpeed investigates how OpenStreetMap speed-limit tags, area context, and daily diffs can be transformed into an offline smartphone runtime for intelligent speed assistance. The contribution is a reproducible deployment study showing that a single-file spatial SQLite bundle gives the best measured latency/update trade-off, while route-level replay shows that richer topology is not automatically better under mobile constraints.

## Step 4: Description

Word count: 1,024 words.

Speed-limit information is one of the most policy-relevant, yet operationally difficult, parts of the OpenStreetMap road network. It is essential for intelligent speed assistance, driver warning systems, speed-aware navigation, and public-sector road-safety analysis, but it is not represented by a single complete attribute. In OSM, speed-limit evidence may appear as explicit `maxspeed=*` tags, inherited rule tokens such as `source:maxspeed` or `maxspeed:type`, contextual road classes, traffic-sign tags, or area-dependent legal defaults. It can also be absent, stale, or split across many short ways. For mobile driver assistance this creates a scientific and engineering problem: an application must not only query OSM quickly, but also preserve provenance, infer missing context, update from daily map changes, and remain reproducible enough that claims about performance and completeness can be independently checked.

This study presents YouSpeed, an offline-first smartphone speed-limit runtime built from OSM extracts, as a deployment-oriented investigation of that problem. The aim is not to demonstrate a consumer application in isolation, but to answer a narrower research question: which OSM-derived data structures and update mechanisms make country-scale, low-latency speed-limit inference feasible on commodity smartphones while preserving traceability to the original map objects? The contribution is a reproducible benchmark and artifact pipeline that treats OSM as a mutable runtime knowledge base rather than as a static background map.

The methodology combines four empirical components. First, we scan European Geofabrik country extracts and measure explicit `maxspeed=*` coverage on car-drivable ways, separating direct speed evidence from data that requires rule-aware fallback. Second, using the Germany OSM snapshot dated 2026-02-23, we generate four runtime architectures with identical source semantics: S1, a global index baseline; S2, a spatially tiled content-addressed pack; S3, a single-file SQLite database with RTree spatial indexing; and S4, a SQLite variant with tile-membership prefiltering. The architectures are evaluated with a fixed Berlin probe point `(52.5200, 13.4050)`, heading `90` degrees, `top-k=5`, and three maxspeed query modes plus built-up-area containment. Measurements are taken both on a cloud-like Apple M4 Max host and on a physical iPhone 14 Pro to expose mobile sandbox costs. Third, we analyze 30 consecutive Germany daily OSM diffs from 2026-01-22 to 2026-02-20, quantifying changed ways, speed-tag events, partition invalidations, simulated SQL patch runtimes, and payload sizes. Fourth, we replay the current YouSpeed matcher family on 21 inspector logs covering 42,654 GPS fixes and 29,411 hindsight labels, so that architectural choices can be compared with route-level matching cost rather than lookup latency alone.

The first finding is that explicit speed-limit completeness varies strongly by country and cannot be reduced to extract size. The Netherlands leads the current scan with 921,426 explicit-speed ways out of 1,360,101 car-drivable ways, or 67.75 percent. Germany ranks eighth with 2,637,436 explicit-speed ways out of 7,964,480, or 33.12 percent. France, despite being a major target country for the 2026 conference context, has 1,490,044 explicit-speed ways out of 7,111,322, or 20.95 percent. These figures show why an OSM-based speed assistant needs provenance-aware fallback logic and area-context lookup: in many jurisdictions, the majority of drivable ways do not carry direct numeric speed limits.

The second finding is that physical packaging matters as much as spatial indexing. In the Germany benchmark, S1 occupies 5.51 GB across 7 files, S2 occupies 5.10 GB across 109,333 files, S3 occupies 2.60 GB in one file, and S4 occupies 3.44 GB in one file. On the iPhone device benchmark, S3 is the strongest architecture for the decision-relevant query modes: 24.10 ms for hybrid lookup, 39.16 ms for polyline-refined lookup, and 0.74 ms for built-up-area containment. S2 improves substantially over S1 but remains slower at 61.03 ms and 76.20 ms for the same maxspeed modes, while S4 does not justify its extra prefilter stage under this workload. The global-index S1 baseline remains in the multi-second range and is therefore unsuitable for per-fix mobile inference. This result supports a concrete systems conclusion: for the current OSM speed-limit runtime, a single-file embedded spatial database is the best measured deployment default.

The third finding concerns OSM's update dynamics. Across the 30-day Germany diff window, the pipeline observes 1,829,171 changed ways, or 60,972 per day on average, including 139,999 maxspeed-related tag changes, or 4,667 per day. S3 has a mean simulated maxspeed patch runtime of 1,023.98 ms per day and a mean polygon-update patch runtime of 2.91 ms per day. Under the project transfer model, the combined S3 daily payload proxy is 5.08 MB, compared with 132.25 MB for the tiled S2 pack and 340.64 MB for the global-index S1 refresh proxy. The practical implication is that daily OSM change ingestion is not only a backend concern: update granularity and mobile artifact design determine whether open map freshness can reach offline clients without excessive bandwidth or file-management overhead.

The route-level replay results refine, rather than overturn, the data-layer conclusion. The strongest current lightweight matcher profile, M7, achieves 94.28 percent replay accuracy and 25.09 percent changed-example recall on the 80.7 MiB no-`way_links` Karlsruhe bundle tier, with 8.488 ms query p95. A heavier sequence profile, M12, recovers more changed examples at 26.91 percent but requires a 170.9 MiB bundle and raises query p95 to 10.374 ms. A Valhalla oracle replay provides a useful ceiling check, but does not reveal a large enough hidden reserve to justify replacing the way-keyed YouSpeed artifact contract. This negative result is scientifically useful: richer topology is not automatically better when storage size, updateability, traceability, and mobile latency are measured together.

The study's scientific contribution is therefore threefold. It provides a quantitative view of European OSM speed-limit provenance, a reproducible architecture benchmark for transforming OSM speed and area context into mobile runtime artifacts, and a deployment-facing analysis that links lookup latency, daily diff behavior, and lightweight map matching. The practical benefit for the OSM community is a concrete feedback loop: local observations can be captured on device, reviewed after the drive, exported as editor-oriented `.osc` packages, and later reconciled through normal OSM diffs, rather than uploaded automatically by an opaque app pipeline. The current evidence does not claim end-to-end safety impact or universal matching accuracy. Its more limited, reproducible conclusion is that OSM can support offline speed-limit assistance when speed provenance, jurisdictional fallback, artifact packaging, and update mechanics are evaluated as one system.

## Step 5: Additional Speaker

Leave blank unless a co-author will also attend State of the Map 2026.

## Step 6: Bibliography

Leave blank. The Description field above does not cite numbered literature references. If Pretalx requires text in the field, enter:

No references cited.

## Step 7: Figures

Leave `Figure 1`, `Figure 2`, and `Figure 3` blank for the initial submission. The Description does not reference figures, and figures are optional.

Optional figure candidates if you decide to add figures later:

1. Europe-wide explicit `maxspeed=*` coverage ranking.
2. S1-S4 mobile latency comparison.
3. Germany 30-day daily-diff update workload.

If any figure is added, reference it explicitly in the Description as `Figure 1`, `Figure 2`, or `Figure 3`.

## Step 8: Details Of All Authors

Raphael Volz; Pforzheim University;

## Step 9: Final Checks Before Submit

1. Confirm the Description word count remains between 800 and 1200 words after any edits.
2. Confirm the Bibliography field is empty or says `No references cited.` because the Description has no numbered citations.
3. Confirm figures remain empty unless the Description explicitly references them.
4. Submit before `2026-05-11 23:59 (Europe/Paris)`.
