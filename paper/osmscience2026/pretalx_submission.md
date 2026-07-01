# OSM Science 2026 Pretalx Submission Fields

Use this file as a field-by-field copy/paste helper for the OSM Science 2026 Pretalx form.

Historical deadline note checked on 2026-04-27: Pretalx listed submissions as closing on `2026-05-11 23:59 (Europe/Paris)`. This file is now the post-review copy/paste helper, so use the checklist at the end for final-version cleanup.

## Step 1: Title

OpenStreetMap as a Runtime Knowledge Base for Offline Smartphone Speed-Limit Assistance: An Artifact-Aware YouSpeed Deployment Study

## Step 2: Submission Type

20 minute talk

## Step 3: Abstract

YouSpeed investigates whether OpenStreetMap can be transformed from heterogeneous speed-limit tags and daily diffs into a fresh, provenance-preserving offline smartphone runtime. The contribution is a deployment benchmark, not just an app demo: it links explicit speed-tag coverage, rule-aware fallback, artifact packaging, update granularity, and route-level way-selection replay.

## Step 4: Description

Word count: 1,003 words.

Speed-limit information is one of the most policy-relevant, yet operationally difficult, parts of the OpenStreetMap road network. It matters for intelligent speed assistance, driver warnings, speed-aware routing, and road-safety analysis, but it is not represented by a single complete attribute. Evidence may appear as explicit `maxspeed=*` tags, inherited rule tokens such as `source:maxspeed` or `maxspeed:type`, contextual road classes, traffic-sign tags, or area-dependent legal defaults. Existing OSM quality tools can describe tag coverage, and routing engines can match trajectories to roads, but neither alone answers the deployment question studied here: can OSM be transformed into a fresh, provenance-preserving, offline runtime knowledge base for real-time smartphone speed-limit assistance?

This study presents YouSpeed, an offline-first smartphone speed-limit runtime built from OSM extracts, as a deployment-oriented investigation of that question. The aim is not to evaluate a consumer app in isolation. The generalizable contribution is a benchmark method for comparing OSM-derived runtime artifacts under the constraints that matter on phones: storage layout, spatial lookup latency, update granularity, traceability to OSM way IDs, and route-level matching behavior. The German-language application webpage is therefore only a demonstrator; the scientific object is the data pipeline and benchmark.

The methodology combines four empirical components. First, we scan European Geofabrik country extracts and report explicit `maxspeed=*` coverage on car-drivable ways. This scan deliberately measures only direct numeric speed tags because they are comparable across countries. The runtime itself uses a wider evidence model: explicit speeds, `source:maxspeed` and `maxspeed:type` tokens, country rules, road-class defaults, residential or built-up-area context, and tunnel or service-road tags. Second, using the Germany OSM snapshot dated 2026-02-23, we generate four runtime architectures with identical source semantics: S1, a global index baseline; S2, a spatially tiled content-addressed pack; S3, a single-file SQLite database with RTree spatial indexing; and S4, a SQLite variant with tile-membership prefiltering. They are evaluated with a fixed Berlin probe, three road-query modes, and built-up-area containment on an Apple M4 Max host and a physical iPhone 14 Pro. Third, we analyze 30 Germany daily OSM diffs from 2026-01-22 to 2026-02-20. Fourth, we replay the current matcher family on 21 inspector logs covering 42,654 GPS fixes and 29,411 hindsight labels.

The first finding is that explicit speed-limit completeness varies strongly by country and cannot be reduced to extract size. The Netherlands leads the scan with 921,426 explicit-speed ways out of 1,360,101 car-drivable ways, or 67.75 percent. Germany ranks eighth with 2,637,436 explicit-speed ways out of 7,964,480, or 33.12 percent. France has 1,490,044 explicit-speed ways out of 7,111,322, or 20.95 percent. These figures explain why an OSM-based speed assistant cannot rely only on direct numeric tags. In many jurisdictions, most drivable ways need rule-aware fallback and area-context lookup.

The second finding is that physical packaging matters as much as spatial indexing. In the Germany benchmark, S1 occupies 5.51 GB across 7 files, S2 occupies 5.10 GB across 109,333 files, S3 occupies 2.60 GB in one file, and S4 occupies 3.44 GB in one file. On the iPhone device benchmark, S3 is the strongest architecture for decision-relevant query modes: 24.10 ms for hybrid lookup, 39.16 ms for polyline-refined lookup, and 0.74 ms for built-up-area containment. S2 improves substantially over S1 but remains slower at 61.03 ms and 76.20 ms for the same road-query modes, while S4 does not justify its extra prefilter stage under this workload. The global-index S1 baseline remains in the multi-second range. The practical conclusion is that, for this OSM speed-limit runtime, a single-file embedded spatial database is the best measured deployment default.

The third finding concerns OSM update dynamics. Across the 30-day Germany diff window, the pipeline observes 1,829,171 changed ways, or 60,972 per day on average, including 139,999 maxspeed-related tag changes, or 4,667 per day. The database-centered S3 path has a mean simulated maxspeed patch runtime of 1,023.98 ms per day and a mean polygon-update patch runtime of 2.91 ms per day. Under the project transfer model, the combined S3 daily payload proxy is 5.08 MB, compared with 132.25 MB for S2 tiled replacement and 340.64 MB for the S1 refresh proxy. These numbers make the update result more than a backend detail: the representation chosen for mobile lookup also determines whether daily OSM changes can be delivered to offline clients without excessive bandwidth, file churn, or failure-recovery complexity.

The route-level replay results refine, rather than overturn, the data-layer conclusion. Replay accuracy here is a way-selection metric: it measures whether the matcher selects the same OSM way ID as a future-stable hindsight pseudo-label already visible in the candidate set. It is not a direct claim of speed-limit label accuracy or safety impact. The strongest current lightweight matcher profile, M7, achieves 94.28 percent way-selection replay accuracy and 25.09 percent changed-example recall on the 80.7 MiB no-`way_links` Karlsruhe bundle tier, with 8.488 ms query p95. A heavier sequence profile, M12, recovers more changed examples at 26.91 percent but requires a 170.9 MiB bundle and raises query p95 to 10.374 ms. A Valhalla oracle replay provides a useful ceiling check, but does not reveal a large enough hidden reserve to justify replacing the way-keyed YouSpeed artifact contract. Richer topology is therefore not automatically better once storage size, updateability, traceability, and mobile latency are measured together.

The study's contribution is threefold: a quantitative view of European explicit speed-tag provenance, a reproducible architecture benchmark for transforming OSM speed and area context into mobile runtime artifacts, and a deployment-facing analysis that links lookup latency, daily diff behavior, and lightweight map matching. The benefit for the OSM community is a concrete feedback loop: local observations can be captured on device, reviewed after the drive, exported as editor-oriented `.osc` packages, and reconciled through normal OSM diffs instead of uploaded automatically by an opaque app pipeline. The current repository URL used during development is not publicly reachable; a public AGPL-3.0 reproducibility package, English README, benchmark commands, and data-manifest hashes should be published before presentation. The limited conclusion is that OSM can support offline speed-limit assistance when speed provenance, jurisdictional fallback, artifact packaging, and update mechanics are evaluated as one system.

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

## Step 9: Post-Review Checks Before Final Version

1. Confirm the Description word count remains between 800 and 1200 words after any edits.
2. Replace the dead/private GitHub URL with a public artifact URL before the final public version.
3. Add an English README or landing page for reviewers who cannot use the German app webpage.
4. Keep the replay-accuracy wording as way-selection accuracy, not speed-limit label accuracy.
5. Confirm the Bibliography field is empty or says `No references cited.` because the Description has no numbered citations.
6. Confirm figures remain empty unless the Description explicitly references them.
