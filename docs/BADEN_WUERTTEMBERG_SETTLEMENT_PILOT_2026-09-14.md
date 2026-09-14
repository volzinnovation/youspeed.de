# Baden-Württemberg settlement-context pilot

Implementation date: 14 September 2026. This pilot implements the additive
contract described in [settlement_context_v1.md](../mapdata/spec/settlement_context_v1.md).
The initial investigation remains in [the city-detection review](CITY_DETECTION_REVIEW_2026-09-14.md).

## Delivered behavior

The single settlement-state attribute is nullable `inside_city`: SQLite `1`, `0`,
or `NULL`, read as `Bool?` on iPhone and `Boolean?` on Android. There is no separate
state enum or unknown flag. Evidence source and confidence remain independent.

1. Both consumers separate municipality names and posted speeds from settlement
   context. Administrative membership, residential/service road class, and low
   numeric limits no longer establish city status. Weak landuse evidence may
   support the city indicator; only high confidence selects settlement defaults,
   settlement penalty variants, or town-entry camera invalidation.
2. Generation preserves typed road context and directional town-entry/exit signs.
   It splits matched roads at usable sign positions and polygon intersections.
   Conflicting explicit evidence and unresolved direction remain unknown.
3. Geometry retains multipolygon components and holes. Stored outlines use a
   two-metre, topology-preserving simplification; classification and road splits
   use original geometry. The apps handle duplicate vertices and do not replace
   a failed exact containment test with a bounding box.

Camera entry detection preserves the last confirmed context through gaps of at
most eight seconds and 160 metres. A brief unknown/low-confidence interval cannot
manufacture another entry into the same town and discard a valid camera limit.
This memory never supplies the displayed city state, defaults or penalties.

After reviewing the Bad Herrenalb examples, the approved consumer policy retains
a **50 km/h road-class fallback for residential and service ways** when speed
evidence is missing and settlement context is weak or unknown. Explicit speeds,
unlimited tags and high-confidence settlement defaults take precedence. This
fallback leaves the nullable city state, confidence, penalties and town-entry
handling unchanged. The existing pilot bundle already has the required road
classes; this adjustment requires no regeneration or schema change.

The manifest remains v3/schema 1. The database gains four additive tables and
`metadata.settlement_context_version=1`. Lookup uses the matched way's indexed
segment rows. The first delivery requires a full bundle; later deltas compare
the rebuilt target, including settlement, naming and derived matcher tables.

## Source and reproduction

Source: [Geofabrik Baden-Württemberg](https://download.geofabrik.de/europe/germany/baden-wuerttemberg.html),
dated PBF `baden-wuerttemberg-260913.osm.pbf`; source data timestamp
`2026-09-13T20:21:20Z`. Download size: 647,326,315 bytes. Verified upstream MD5:
`ce50bb515641808835a7e3c1430ae5de`. SHA-256:
`1856f4ac7c18435e17d74c7ba24a7b21b3a1231e60449851890dc0109638ded3`.

Local generation used pyosmium 4.3.0 and Shapely 2.1.2 (pinned in
`scripts/map/requirements-settlement.txt`) in
`/tmp/youspeed-settlement-venv`. From the repository root:

```sh
env PATH="/tmp/youspeed-settlement-venv/bin:$PATH" \
  bash scripts/map/build_region_artifacts.sh \
  --region baden-wuerttemberg-settlement-pilot \
  --input mapdata/raw/baden-wuerttemberg-260913.osm.pbf

/tmp/youspeed-settlement-venv/bin/python scripts/map/build_spatialite_v3.py \
  --v1-dist mapdata/dist/baden-wuerttemberg-settlement-pilot \
  --out-db mapdata/dist-v3/baden-wuerttemberg-settlement-pilot/speeds_v3.sqlite \
  --input-pbf mapdata/raw/baden-wuerttemberg-260913.osm.pbf \
  --build-settlement-context --country-code DE --corridor-mode none

python3 scripts/map/audit_city_context.py --settlement-only \
  mapdata/dist-v3/baden-wuerttemberg-settlement-pilot/speeds_v3.sqlite

python3 scripts/map/publish_v3_bundle.py \
  --region baden-wuerttemberg --country-code DEU \
  --db mapdata/dist-v3/baden-wuerttemberg-settlement-pilot/speeds_v3.sqlite \
  --bundle-version 2026-09-14-settlement-pilot \
  --bundle-dir-name 2026-09-14-settlement-pilot \
  --out-root mapdata/bundles/v3 --db-compression gzip --min-app-version 1.1 \
  --coverage-poly mapdata/raw/baden-wuerttemberg-settlement-pilot.poly \
  --coverage-poly-file-name baden-wuerttemberg.poly
```

Preprocessing admitted 1,085,790 roads and 144,334 legacy context areas. During
the run, the packer restored its old exclusion of unnamed administrative-only
areas. The completed artifact was normalized by removing exactly 12 such rows
and their cell references, then regenerating its checksum manifest. These areas
never contribute to the new settlement classification. Running the final packer
above applies this filter directly.

The first full-region settlement pass exposed an avoidable cost: converting every
OSM node's tags to a dictionary. A one-second process profile attributed most
sampled CPU time to that conversion. Generation now checks the three relevant
traffic-sign keys first. A regression verifies irrelevant nodes never access
location or iterate tags. The completed legacy database was checkpointed and
checked, then only settlement extraction resumed with this optimization.

## Validation

The full pilot passed SQLite integrity and foreign-key checks. All 1,085,790
admitted roads have settlement records; no segment or associated sign refers to
a missing road. Nullable values, JSON, geometry lengths, segment IDs and interval
keys passed the contract checks. Lookup uses `idx_settlement_segment_way`.

The [machine-readable report](baden-wuerttemberg-settlement-pilot-2026-09-14.json)
contains complete counts, checks, source hashes and examples.

A [separate filtered recheck](BADEN_WUERTTEMBERG_NO_SPEED_EVIDENCE_2026-09-14.md)
examines only roads without recorded explicit or implicit speed evidence.
The following counts describe the complete pilot, before that filter.

| `inside_city` | Confidence | Segment records | Share of records |
| --- | --- | ---: | ---: |
| `true` | high | 86,448 | 6.68% |
| `true` | low, landuse | 745,551 | 57.61% |
| `false` | high | 38,929 | 3.01% |
| `NULL` | unknown | 423,270 | 32.71% |

These 1,294,198 records include split intervals and separate directions where
needed; their percentages are not percentages of roads or distance. Of the
unknown records, 528 preserve contradictory explicit evidence and 422,742 lack
usable evidence. High-confidence coverage totals 9.69% of records.

The extension retains 40,188 areas: 39,955 landuse and 233 explicit urban/traffic
polygons. They include 1,868 OSM relations, 44,226 rings and 3,748 holes, with no
invalid extracted polygon geometry. The 20,143 source sign observations produce
32,886 association rows because a sign can apply to both sides of a safe way
split. Of those association rows, 11,962 still lack usable direction, 2,385 lack
an associated road, and 665 have ambiguous road membership.

The original Mannheim/Rheinau probe, way `19206309`, retains its posted `30`
while resolving `inside_city=false` from current `zone:traffic` evidence. Current
source tagging differs from the historical Karlsruhe snapshot. The report also
includes urban 70 and rural 30 examples, and explicit tag/sign contradictions
that now resolve to `NULL`.

The uncompressed database is 1,273,720,832 bytes (about 1.27 GB), including all
legacy tables. Its SHA-256 is
`1938df90ffa6b9ff0f5dfb2b4f09c622f4208cb03102fc5fb2c2f5ebc531a183`.

Local package: [manifest](../mapdata/bundles/v3/baden-wuerttemberg/2026-09-14-settlement-pilot/baden-wuerttemberg_manifest.json)
and [compressed database](../mapdata/bundles/v3/baden-wuerttemberg/2026-09-14-settlement-pilot/baden-wuerttemberg_speeds.sqlite.gz).
The download is 419,711,862 bytes (about 420 MB). Compressed and decompressed
hashes, decompressed byte count, gzip integrity and coverage polygon checksum
were verified against the manifest. Packaging writes these local files only;
it has not uploaded a release.

Synthetic generation fixtures cover urban 70, rural 30, numeric-only unknown,
conflicting evidence, symbolic and directional speed tags, generic and DE signs,
collinear way splits, ambiguous intersections, polygon holes, and narrow notches.
They exercise the full source-to-database command path. Separate delta tests
check nullable values, exact geometry/RTree coordinates, context-only changes,
and rejection of capability/schema changes requiring full delivery.

iPhone simulator checks cover the nullable contract, geometry, legacy bundles,
camera transitions, penalties, manifest versions, download, delta, integrity and
recovery. Android JVM and emulator checks cover the corresponding behavior.
Physical-device driving has not been exercised in this task.

Completed test runs:

| Check | Result |
| --- | --- |
| Source-to-settlement regressions | 17 passed |
| Existing v3/v4 pipeline suite | 13 passed |
| Existing legacy map pipeline suite | 23 passed |
| Context/matcher delta regressions | 9 passed |
| Existing bundle/delta suite | 9 passed |
| Regional generation orchestration | 13 passed |
| Android JVM suite, including five camera-gap regressions | 302 passed |
| Android emulator: settlement, naming, matching, delta | 26 passed, no skips; before the final camera-gap-only change |
| iPhone simulator: settlement/geometry/legacy/camera | 22 passed |
| iPhone simulator: existing download/delta/integrity/recovery | 5 passed |
| iPhone final confidence/version and warning-order runs | 3 and 4 passed; these include reruns of selected cases |
| iPhone camera-gap and actual camera-limit retention | 6 passed; four new cases plus two related regressions |

Android debug and instrumentation APKs and the iPhone app/test targets built
successfully. Local logs include `/tmp/youspeed-android-settlement-tests.txt`,
`/tmp/youspeed-settlement-ios-final-tests.log`,
`/tmp/youspeed-settlement-ios-install-tests.log`, and
`/tmp/youspeed-settlement-ios-final-audit-tests.log`.

The residential/service fallback follow-up passed 15 focused Android JVM tests
and all 13 settlement instrumentation tests on the API 36 emulator, including
actual SQLite lookups in both corridor and M7 matching modes. iPhone simulator
runs passed 11 distinct focused tests across overlapping runs; the final three
affected tests passed again against the exact final code. These cover missing
and weak context, explicit/unlimited and high-confidence default precedence,
nullable-state preservation, legacy-tag safeguards, other road classes, and
camera/penalty behavior. The final iPhone log is
`/tmp/youspeed-ios-residential-service-default-parity-tests.log`.

Independent complete CLI roundtrips also passed. A context-only change propagated
signs, polygon holes and names despite unchanged legacy roads. A second fixture
changed three roads, shared-node links, corridor geometry, continuity and tunnel
membership: the patched result exactly matched the full rebuild in all 27
logical tables and 38 relevant metadata keys. Reproduction scripts are
`/tmp/youspeed-settlement-delta-e2e/reproduce.py` and
`/tmp/youspeed-settlement-delta-topology-e2e/reproduce.py`.

## Deployment to attached devices

On 2026-09-14, the updated development apps and this pilot were installed on the
attached moto g86 5G and iPhone 14 Pro, following explicit deployment approval.
Both apps are build `10007` (Android `1.1-debug`, iPhone `1.1`). Existing app data
and the previous Baden-Württemberg `2026-07-04` bundle were retained. Android
preferences were also compared before and after installation and were unchanged.

Both devices activated `2026-09-14-settlement-pilot`. The installed databases
were independently hashed on each device and matched the manifest's SHA-256
and 1,273,720,832-byte size. Android exercised the production bundle installer
with locally staged artifacts. iPhone received the complete versioned bundle
directory before activation, followed by the app's compatibility, routing and
database checks against that installed directory.

| Physical-device check | Result |
| --- | --- |
| Android: Im Kloster and Bahnhofsplatz, corridor and M7 matchers | 4/4 lookups passed |
| iPhone: all eight mapped Bad Herrenalb examples, connected and corridor matchers | 16/16 lookups passed |

Every lookup selected its expected OSM way, returned `50` km/h, and preserved
`inside_city = NULL` with `settlement:missing:unknown`. The iPhone test also
verified that normal local routing selects the pilot and leaves activation
metadata unchanged. Both deployment helpers are explicitly opt-in tests.
These are stationary lookup checks, not a driving accuracy assessment; Android
cold lookups took approximately 2.23–2.29 seconds in this test.

Both apps were reopened after verification. Android settings visibly showed the
pilot version; the iPhone main display was inspected through QuickTime's attached
screen preview. Local evidence is saved in
`/tmp/youspeed-android-bw-pilot-deployment-report.json`,
`/tmp/youspeed-iphone-bw-pilot-device-report.json`, and
`/tmp/youspeed-iphone-bw-pilot-device.xcresult`.

## Limits and next validation

Counts in the generated report describe data coverage and evidence consistency;
they are not false-positive or false-negative rates. Actual accuracy still needs
annotated routes through surveyed town entries/exits in both directions.

Landuse parcels often exclude carriageways. Those gaps remain unknown unless
stronger road/sign evidence exists. This pilot adds no uncalibrated proximity
buffer or unlimited propagation along the road network. Numeric-bearing,
undirected and ambiguously associated town signs remain preserved but unresolved.
Municipal name geometry retains the existing builder's sampling behavior; names
do not determine `inside_city`.

The pilot is local and versioned. Updated clients must be installed before the
first full bundle. Minimum app version `1.1` cannot distinguish older builds with
the same marketing version, and older clients do not enforce the new checks.
Deployment to the two attached devices is complete. Publishing and other
regional bundle regeneration remain pending the pilot review.
