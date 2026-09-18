# City detection review — 14 September 2026 and current status as of 17 September 2026

The 14 September review found that the then-current implementation mixed geographic place names with the traffic-law concept of being inside a built-up area. The generation and consumer changes described below have since been implemented. The apps and the pilot bundle are much improved, but the result is not yet a measured driving-accuracy release.

Reviewed source commit: `219364e3d6b2758945583182d764f34a6a130798`. Scope: default pyosmium → v3 generation, v3 deltas, both consumer implementations, and the local Karlsruhe bundle. The initial investigation is retained as a historical baseline. The subsequent implementation uses a single nullable `inside_city` attribute; see the [additive contract](../mapdata/spec/settlement_context_v1.md) and [Baden-Württemberg pilot results](BADEN_WUERTTEMBERG_SETTLEMENT_PILOT_2026-09-14.md).

## Current status — 17 September 2026

The city/settlement decision is now a bundle-backed, per-road-segment context on both platforms. iPhone and Android share the same nullable contract: `true` means inside, `false` means outside, and `NULL` means that the map evidence is unknown or contradictory. Municipality/place names and posted speed limits remain separate values.

The main issues identified on 14 September are addressed in the settlement-context pilot:

- Administrative boundaries, road class, and low numeric limits no longer assert that a road is inside a city.
- `zone:traffic`, supported urban/rural speed-context tags, town-entry/exit signs, direction, road association, multipolygon relations, holes, and segment splits are retained where usable.
- Conflicting or ambiguous evidence remains unresolved instead of being silently converted to urban or rural. Stored geometry is topology-preserving, exact containment no longer falls back to a bounding box, and duplicate vertices are handled safely.
- Both apps read the same context, use only high-confidence evidence for settlement defaults, penalty variants, and camera-limit invalidation, and retain a confirmed camera context only across bounded short gaps. The approved 50 km/h fallback for missing-speed residential and service roads does not change the nullable city state.

The Baden-Württemberg pilot bundle `2026-09-14-settlement-pilot` was generated, integrity-checked, and installed on the attached moto g86 5G and iPhone 14 Pro in build 10007 (Android `1.1-debug`, iPhone `1.1`). Android passed 4/4 stationary lookups and iPhone passed 16/16 across the Bad Herrenalb examples; the expected ways and 50 km/h result were selected while `inside_city = NULL` was preserved. The installed database hashes matched the bundle manifest on both devices. These checks establish source-to-bundle and app integration, not real-world driving accuracy.

The implementation is therefore suitable for controlled pilot use, but not yet a claim of perfect city detection. In the full pilot, 32.71% of segment records were unknown and only 9.69% had high-confidence context. Of 32,886 sign-association rows, 11,962 lacked usable direction, 2,385 had no associated road, and 665 had ambiguous road membership. Land-use evidence remains low confidence; parcel gaps, roads beside mapped land-use, incomplete sign direction, and numeric or undirected signs remain unknown rather than being guessed.

The displayed municipality or locality name is still a place label, not a legal built-up-area result. It is resolved independently and can remain imperfect even when the settlement state is correctly unknown or outside.

No annotated route set has yet produced false-inside/false-outside rates, entry/exit distance error, or state-change rates. Physical-device validation was stationary, and physical driving has not been exercised in this task. The pilot remains local and has not been published; updated clients must precede delivery of an extension-enabled bundle. The minimum app version `1.1` also cannot distinguish older 1.1 builds from the updated implementation.

## What the state must mean

Keep these independent:

- **Place name:** municipality/locality/district containing or near the road, useful for display.
- **Settlement traffic context:** inside, outside, or unknown relative to the applicable built-up-area rules.
- **Posted speed:** the particular road's limit, which can differ from the settlement default.

For Germany, signs 310 and 311 define the start and end of the built-up area. A municipality polygon does not establish where those signs stand. [StVO, Anlage 3, section 2](https://www.gesetze-im-internet.de/stvo_2013/anlage_3.html).

OSM already distinguishes the concepts. `zone:traffic` describes the road's underlying traffic context and can coexist with a numeric posted limit; its documentation explicitly gives a rural road with a signed 30 km/h limit as a valid example. `maxspeed:type` and `source:maxspeed` can supply additional context when they contain an explicit urban/rural value. [OSM zone:traffic](https://wiki.openstreetmap.org/wiki/Key:zone:traffic), [OSM maxspeed:type](https://wiki.openstreetmap.org/wiki/Key:maxspeed:type).

## Confirmed implementation problems in the pre-pilot implementation

| Problem | Behavior at the review commit and consequence | Source |
|---|---|---|
| Administrative boundaries imply built-up | A containing named level 6, 8 or 9 boundary returns `insideCity=true`. Rural portions of a municipality or county can therefore become urban. | `iphone/SpeedConsumerApp/V3SpeedLimitService.swift:9265` and Android `V3SpeedLimitLookup.kt` polygon resolver |
| Empty residential search changes meaning | No usable residential polygon bounding-box candidate returns unknown and falls back to administrative context; a candidate whose polygon excludes the position returns outside. Crossing the bounding box can therefore change the outcome without crossing a settlement boundary. | `V3SpeedLimitService.swift:1108`, `:9191`, `:9234`; Android lookup `:277` |
| A failed polygon test becomes bounding-box containment | In the legacy areas resolver, even a valid closed polygon that excludes the point falls into `containingAdminBBox`. That fallback can beat a negative result from the dedicated polygon resolver. | `V3SpeedLimitService.swift:9168`, `:9475`; Android equivalent `:6031` |
| Road class and speed override settlement evidence | `service`, `residential`, `living_street` and `crossing` imply inside; German effective limits from 1 to 49 km/h also force inside. Service access and low posted limits are not sufficient evidence. | `V3SpeedLimitService.swift:849`, `:1108`, `:2199`, `:9253`; Android equivalent |
| Explicit urban/rural tags are used only for deriving speed | Numeric `maxspeed` returns before the urban/rural branch. The candidate does not preserve that independent evidence for the city decision. | `V3SpeedLimitService.swift:2219`, `:2517`; Android `:6294` |
| Residential relation polygons are omitted | The packer emits residential closed ways, but `area()` rejects non-administrative areas. Residential multipolygon relations are therefore absent unless their member ways happen to carry independent qualifying tags. | `scripts/map/pack_runtime_artifacts_pyosmium.py:318`, `:358` |
| Polygon simplification has no spatial error bound | Residential rings share the default 24-point road budget and use uniform vertex-index sampling. Dedicated administrative rings default to 96 points with similar sampling. Important bends can disappear regardless of their distance from a road. | packer `:86`, `:104`, `:320`; `scripts/map/build_spatialite_v3.py:1108` |
| Relevant signals are discarded | `zone:traffic` is not retained in way metadata. Node extraction recognizes German codes 310/311 but omits generic city-limit signs and direction/road association. The v3 `areas` schema then drops the extracted node `traffic_sign` field altogether. | packer `:165`, `:269`, `:418`; v3 builder `:1256`, `:1747` |
| City tables are absent from delta equivalence | Delta generation and its target-equivalence check cover roads and areas, but not the dedicated city boundary/ring/place tables. Updated full data and a patched bundle can therefore disagree. | `scripts/map/build_v3_delta_pack.py:565`, `:819`, `:975` |

There is also a shared geometry defect: a zero-length edge from consecutive duplicate vertices passes `pointOnSegment` for any point. The spatial prefilter limits its reach to candidate bounding boxes, but exact containment is still wrong. Source: Swift `:9680`, Kotlin `:6738`. A synthetic triangle reproduced the failure, but no such consecutive duplicates were found in the audited residential or dedicated city rings. Normal first/last ring closure does not trigger it because the clients iterate only the stored adjacent pairs. This defect is not an established cause of errors in this bundle.

These errors affect more than the city label. The state participates in fallback speed selection, penalty context, and invalidation of camera-derived limits on a perceived town entry (`DriveSessionViewModel.swift:2334` and `ConsumerSessionController.kt:3653`).

The core classification rules agree across platforms, but missing-data behavior does not fully agree: Android can collapse unavailable administrative context to false where iPhone retains unknown. Android also uses a shared 512-row area/place candidate query for residential evidence, while iPhone uses a dedicated 1,024-row residential query. These details need shared contract tests.

## Historical local bundle measurements

Audited `mapdata/bundles/v3/karlsruhe-regbez/latest/karlsruhe-regbez_speeds.sqlite`, manifest version `2026-03-15-city-polygons`, SHA-256 `13fc90e9331c165be634b3486f1952d1c0ff5c4a7be26ce9f3205861815edd93`. This is the local bundled snapshot, not a verified copy of the user's currently installed/downloaded dataset.

| Measurement | Result |
|---|---:|
| Stored roads | 242,415 |
| Roads with explicit urban tokens in maxspeed/type/source, deduplicated | 11,465 |
| Roads with explicit rural tokens, deduplicated | 3,887 |
| Stored residential polygons | 3,810 |
| Residential polygons from relations | 0 |
| Maximum residential ring vertex count | 24 |
| Residential rings with exactly 24 vertices | 1,403 |
| Administrative boundaries | 562: 12 level 6, 210 level 8, 340 level 9 |
| Urban-tagged road midpoints outside stored residential polygons | 9,020 / 11,465 (78.7%) |
| Rural-tagged road midpoints inside an administrative polygon | 3,775 / 3,887 (97.1%) |
| Rural-tagged road midpoints inside level 8/9 polygons | 3,502 / 3,887 (90.1%) |
| Rural-tagged roads with explicit numeric maxspeed 30 | 13 |

Sampling uses one distance-weighted midpoint of each retained road polyline, testing stored residential outlines and administrative outer/inner rings. Urban/rural membership uses case-normalized exact `urban`, `DE:urban`, `rural`, or `DE:rural` tokens from the three fields, split on semicolons. These are internal evidence disagreements, **not measured app error rates**: tags can be wrong, geometry is already simplified, and a road can cross a boundary away from its midpoint.

For example, bundled way `19206309` has `highway=trunk_link`, `maxspeed=30`, and `source:maxspeed=DE:rural`; its sampled location is latitude 49.41965345, longitude 8.53744155, administratively Mannheim/Rheinau. It exposes the conflict between low-speed urban inference and existing rural evidence without assuming either tag is surveyed truth.

Reproduce the measurement from the repository root:

```sh
python3 scripts/map/audit_city_context.py \
  mapdata/bundles/v3/karlsruhe-regbez/latest/karlsruhe-regbez_speeds.sqlite
```

At the time of this audit, the source PBF could not be reconstructed from the checkout: the seed manifest required `part000` and `part001`, but only `part001` was present and `mapdata/raw` had no PBF. Therefore this review does not quantify how many source signs, `zone:traffic` tags, or residential relations were lost in this particular historical build. Generator loss was instead reproduced with complete synthetic OSM input. A fresh, checksum-verified Baden-Württemberg snapshot was downloaded for the subsequent pilot; it is not the historical Karlsruhe source.

## Historical reproductions

Small temporary probes exercised the current implementation without modifying it:

1. **OSM area extraction:** osmium assembled both a residential closed way and a residential multipolygon relation. The packer emitted only the closed way.
2. **Lost traffic context:** a fixture with `maxspeed=70`, `maxspeed:type=sign`, `zone:traffic=DE:urban` retained 70 and `sign`, but lost `zone:traffic`.
3. **Polygon distortion:** a 503-vertex synthetic ring with a narrow, 100-metre-deep notch was reduced to 24 vertices. A point outside the original polygon became inside the sampled polygon. This demonstrates lack of a geometric error bound, not a measured error distance in Karlsruhe.
4. **Speed/context coupling:** a Swift harness using extracted current helpers returned `speed=30, source=explicitTag, heuristic_inside=true` for numeric 30 with `DE:rural`. Numeric 70 with `DE:urban` returned explicit speed 70 without preserving urban evidence for settlement classification; its final city result still depends on the other heuristics.
5. **Duplicate vertex:** a point inside a triangle's bounding box but outside the triangle was rejected normally and accepted after adding a consecutive duplicate vertex.

The command-line v3 query tool is not a complete app oracle: it derives its built-up guess from residential containment, whereas both apps also apply the administrative and road/speed fallbacks. Existing CLI pipeline checks can pass while app behavior remains wrong (`scripts/map/query_speed_limit_v3.py:709`).

Several existing consumer tests actively enforce the suspect highway/low-speed rules (`SpeedConsumerTests.swift:11657`, `:11715`, `:11817`; Android `CityContextInstrumentedTest.kt:146`, `V3SpeedLimitLookupTests.kt:73`). Those expectations need to change along with the policy, rather than treating a passing old suite as evidence of geographic correctness.

## Implemented generation and consumer changes

This section records the implementation contract that resulted from the proposal; remaining work is primarily route validation and controlled rollout, with the known sign-association and land-use coverage limits described above.

### 1. Correct the shared decision contract first

Generate an independent settlement context for each road segment, with `inside/outside/unknown`, evidence source, confidence category, and source OSM identifiers. Keep municipality/place naming separate. Retain the road's posted limit independently.

Consumers should use explicit context even when a numeric speed is present. Administrative boundaries, a service-road class, or a low numeric limit must not independently assert urban status. An exact negative geometry test must not be replaced by its bounding box. Missing map evidence should remain unknown rather than become an unsupported rural or urban assertion. Handle duplicate vertices correctly in both geometry implementations.

### 2. Preserve useful OSM evidence in generation

Preserve and normalize country-specific `zone:traffic`, supported urban/rural forms of `maxspeed:type` and `source:maxspeed`, and applicable directional variants. Conflicting explicit evidence should be reported and produce uncertainty rather than silently selecting one tag.

Extract generic `traffic_sign=city_limit`, country-specific town-entry/exit codes, `city_limit`, direction, node IDs, and road membership. Keep separate roadside signs and resolve their road association conservatively. Split road segments at applicable sign positions; entry/exit depends on travel direction. Missing or ambiguous sign orientation must not be guessed from proximity alone. [OSM city-limit signs](https://wiki.openstreetmap.org/wiki/Tag:traffic_sign=city_limit).

Include mapped `boundary=urban` where available and validated for the country: it is intended to describe the sign-delimited urban area. Measure its coverage before relying on it. [OSM boundary=urban](https://wiki.openstreetmap.org/wiki/Tag:boundary=urban).

Use explicit road context and correctly directed sign evidence as the strongest inputs, validated legal urban polygons next, and physical land-use inference last. Report contradictions between strong inputs rather than masking them with a heuristic. Keep existing speed-sign and country-specific limit resolution independent of this evidence ranking.

### 3. Build a better geometric fallback

Assemble multipolygons with all outer rings and holes. Replace fixed point-count sampling with topology-preserving simplification in metric coordinates and an explicit error tolerance. Preserve road/sign boundary intersections and reject or report invalid geometry.

Residential, retail, commercial and industrial land use can support a lower-confidence estimate of developed settlement, but do not by themselves establish the legal boundary. Residential polygons may legitimately stop at the road edge and exclude the carriageway, so raw GPS-in-residential-polygon is insufficient. Evaluate the matched road segment, nearby development and continuity, with measured constraints on bridging gaps. Do not fill entire municipal extents or flood across contradictory rural tags and town-exit signs. [OSM residential land use](https://wiki.openstreetmap.org/wiki/Tag:landuse=residential).

Precomputing this on road segments avoids repeated GPS classification changes at land-use edges. For weak inference, use a validated distance/confidence transition policy; strong, correctly associated boundary evidence should change state at the crossing. An unknown segment must not silently erase the last confirmed state or hold it indefinitely: record uncertainty and define bounded continuity explicitly.

### 4. Make regeneration measurable

Start with Karlsruhe and recorded problem routes. Annotate actual town entries/exits in both directions, including industrial areas, roads between villages, bypasses, rural 30/40 restrictions, service access, polygon holes and incomplete coverage.

Measure false-inside and false-outside rates separately, unknown coverage, entry/exit distance error, and repeated state changes per traversal. Report results by evidence source. Agreement with another OSM tag is a diagnostic, not surveyed ground truth.

Require shared Swift/Kotlin fixtures for the contract and transitions, round-trip preservation checks from OSM to the final bundle, geometry validity/error checks, and full-build versus delta equivalence including all settlement tables. Version the semantic contract so legacy bundles remain identifiable. Publishing a regenerated bundle requires the repository's explicit user approval.

## Remaining validation order

Keep the implementation under pilot observation and validate annotated Karlsruhe/Baden-Württemberg routes in both directions. Measure false-inside and false-outside rates separately, unknown coverage, entry/exit distance error, repeated state changes, and results by evidence source. Then review the remaining sign association and land-use gaps before considering wider publication. More residential data alone cannot establish the legal settlement boundary.
