# Upcoming lower speed limits — implementation record

Date: 23 October 2026. Target: iPhone and Android 1.5 with the local BW test bundle.
Product contract: [specification](UPCOMING_SPEED_LIMIT_SPEC.md).

The product owner replaced the original 300 m ceiling with a 30-second
speed-dependent window on 23 October 2026. The current working-tree change and
its new validation are recorded in
[the adaptive-horizon update](UPCOMING_SPEED_LIMIT_ADAPTIVE_HORIZON_2026-10-23.md).
The build 10059 results below remain the historical validation of the original
300 m behavior; installed copies do not acquire this change automatically.

Implemented in the working tree on `codex/youspeed-v1.5-mobidata-bw`.
Both native builds were validated as **1.5 (10059)**. The local bundle is
**2026-10-23-v1.5-lookahead**. The machine-readable receipt is
[UPCOMING_SPEED_LIMIT_VALIDATION_2026-10-23.json](UPCOMING_SPEED_LIMIT_VALIDATION_2026-10-23.json).

The app shows the nearest eligible lower numeric sign with positive along-road
distance within `max(300, observed_speed_kmh / 3.6 * 30)` metres. It sits at the safe lower-left edge in landscape and
below-left of the current sign in portrait. Distance rounds upward to 10 m;
distances below 10 m have a separate caption. German, English, French and Dutch
captions and accessibility descriptions are included on both platforms.

The preview clears on passage, relation departure, direction loss, capture
entry, unreliable matching or location expiry. It compares against the final
effective main limit, including camera/voice changes without movement. A real
three-second expiry timer also works when no new fix arrives. Passed-sign memory
survives temporary hiding and GPS jitter. There is no new control or audio alert.

## Data and runtime boundary

The preview reads physical, directed sign associations and their unique numeric
post-station rule. It does not use propagated interval entries as new signs.
All positioned event statuses are read so a conflicting, conditional or unknown
primary event can stop prediction. Eligibility uses the final effective current
limit and unrounded positive along-road distance within that lookup's adaptive
window. Missing or invalid driving speed retains the 300 m minimum.

The additive `upcoming_path` capability preserves original source-node incidence
and certifies only ordinary unbranched, unmerged continuations with known access
and no unresolved restriction involvement. It is pinned to the BW road snapshot.
The previous BW runtime test database remains unchanged; the enriched database
and packaged bundle receive a separate version.

The shared speed-reference policy, approval lock and source precedence remain
unchanged. Passing a preview clears its presentation and lets the ordinary
bundle resolver offer the new current value. Existing camera/voice authority
continues to apply.

Cross-way retention requires both a certified directed path and intersection
with the frozen raw road-relation memberships. A shared relation ID alone is
insufficient. With no verified relation, supported physical signs on the same
way remain eligible. Missing/unknown topology never permits a cross-way guess;
an explicit topology stop cannot fall back to a longer same-way prediction.

The native implementation is in
[`UpcomingSpeedLimit.swift`](../iphone/SpeedConsumerApp/UpcomingSpeedLimit.swift),
[`UpcomingSpeedLimit.kt`](../android/app/src/main/java/de/youspeed/android/alpha/UpcomingSpeedLimit.kt)
and [`UpcomingSpeedLimitReader.kt`](../android/app/src/main/java/de/youspeed/android/alpha/UpcomingSpeedLimitReader.kt).
It is connected to the existing lookup resources, session controllers and main
dashboard on each platform. The protected reference policy and its artifact
remain unchanged; the Android interpreter exposes only an existing context-pending
state for preview suppression.

## Bundle and topology

The [local manifest](../mapdata/bundles/v3/baden-wuerttemberg/2026-10-23-v1.5-lookahead/baden-wuerttemberg_manifest.json)
requires app 1.5 and advertises optional `upcoming_path.version=1`. The
[bundle handoff](../mapdata/bundles/v3/baden-wuerttemberg/2026-10-23-v1.5-lookahead/README.md)
contains the checksums, attribution and validation reports. No remote download
URL or release catalog was changed.

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| New materialized SQLite | 3,099,021,312 | `34b31aac1dc5a6abacce959afb8ec44043146f5aa4f1ea488c07cb4a68efe09c` |
| Packaged SQLite gzip | 974,577,648 | `d07ce7bd06481d5ff915206bbbec1d2cd990a607bbc1a0b385cdf8f23b99ed3f` |
| Preserved original runtime SQLite | 2,122,903,552 | `e1a36e56cc4809cc69d2d5161b993eff21a1c08264e8d9300e79ec7546ccd00b` |

The enriched database is
`mapdata/dist-v3/baden-wuerttemberg-v1.5-lookahead/speeds_v3.sqlite`.
The preserved original is
`mapdata/dist-v3/baden-wuerttemberg-v1.5-runtime/speeds_v3.sqlite`.
The complete compressed stream, CRC, decoded size/hash and original hash were
verified after packaging. Existing shared sign artwork and attribution were
packaged using the existing 49-pair BW subset.

The source PBF SHA-256 is
`1856f4ac7c18435e17d74c7ba24a7b21b3a1231e60449851890dc0109638ded3`.
This is the pinned September road snapshot used by the existing 1.5 runtime,
not a road-data refresh. The builder checked all **1,085,790 admitted ways**
against their original source geometry. Complete source incidence includes
**2,388,797 highway ways**, **12,936,372 nodes** and **24,152 restrictions**,
including roads omitted from the runtime bundle.

The capability has **4,346,282 directed segments** and the same number of
successor decisions: **284,670 certified continuations** and **4,061,612 stops**.
These are directed segment decisions, not a count of whole-road routes.
Segments split at interior junctions, restriction nodes and access/barrier nodes.
Only an ordinary unbranched, unmerged permitted continuation is certified;
restriction-involved ways, uncertain access, loops, merges and forks stop.

The [schema contract](../mapdata/spec/upcoming_path_v1.md) and
[SQL schema](../mapdata/spec/upcoming_path_v1.sql) document source identity,
chainage, proof and capability validation. The existing v3 builder has an opt-in
`--build-upcoming-path` stage. Exact and heuristic delta creation reject a base
or target containing this capability: deliver the full bundle until a delta can
reproduce all topology, physical-event and source-capability changes together.

## Query cost and limits

Lookups run on the existing serialized database worker and geometry cache.
Physical events use the full `(way_id, direction, station_chainage_m, sign_id)`
index, including rejected/conflicting stations; successor reads use the integer
primary key. Query-plan inspection confirmed these indexed range/key lookups.
There is no whole-relation scan or route search on location updates.

Both clients cap work at the speed-dependent distance, 32 directed segments
and a 25 ms traversal budget, with bounded physical-event reads. The original
10059 measurements below used the previous 300 m distance ceiling. Exceeding a cap suppresses targets
beyond established evidence. A SQLite operation already in progress can exceed
the traversal deadline; this is not a hard database cancellation guarantee.

Both native readers passed five forward/reverse approaches extracted from the
actual new BW database, preserving sign IDs, limits and distances across way
splits. Android measured 0.35–1.73 ms for those warm queries; iPhone's 145 warm
samples had p95 0.112 ms and maximum 0.192 ms. These measurements use a 196,608-byte
extracted fixture on an emulator/simulator. They establish query correctness
and bounded access, **not full 3.1 GB bundle latency on physical hardware**.

## Shared validation

[`shared/upcoming-speed-limit/scenarios-v1.json`](../shared/upcoming-speed-limit/scenarios-v1.json)
now contains 42 synthetic scenarios and 59 steps consumed by both native test
suites. The original 10059 results below used 22 scenarios and 34 steps.
Each platform also tests its SQLite reader and app integration. Coverage includes
exactly 300 m, reverse chainage, nearest-lower selection, camera/voice authority,
pending context, stale/future fixes, timer expiry, passage while hidden, jitter,
bundle changes, first-fix certified continuation, source conflicts, propagated
intervals, zero-length origin handoff and conservative topology stops.

| Check | Result |
| --- | --- |
| iPhone native | 33 passed: 19 feature/integration and 14 existing reference tests |
| iPhone dashboard | One UI test passed all six mount/camera combinations with plate and secondary sign |
| Android JVM | 77 passed: 6 preview, 56 inventory and 15 reference tests |
| Android emulator | Seven reader/controller/layout/BW tests passed; final layout and expiry rerun also passed |
| Android dashboard | All 12 mount/camera/text-scale combinations passed circle-separation and plate-overlap checks |
| Topology/runtime Python regression group | 66 passed, one existing optional Shapely settlement test skipped |
| Publisher regression file | 10 passed, including optional-capability advertisement and source preservation |
| Protected reference checker | 39 scenarios, 171 steps, 16 transitions and five states passed; artifact and both pins unchanged |
| Full BW topology validator | Ready; all seven invariant checks have zero failed rows |
| Full BW sign-runtime validator | Ready; all 14 invariant checks have zero failed rows |
| Full BW structural validator | Ready; SQLite quick-check OK; all admitted way geometry checked; no errors or warnings |
| Packaged bytes | Compressed/decoded sizes and hashes, gzip stream and original preservation passed |

Python groups overlap; their counts should not be added as unique tests.
Native logs, result bundles and screenshot paths are listed in the receipt.
The Android layout suite explicitly checks the preview circle against the main
circle at enlarged text size; the corrected landscape screenshots were also
visually reviewed. Both test devices were shut down with their results retained.

## Reproduction

Start from a fresh copy of the original runtime SQLite, preserving the original.
The following commands use the already materialized lookahead directory; choose
a new directory for a clean rebuild. Dependencies are the existing pinned map
runtime dependencies, including `osmium==4.3.0`.

```sh
python3 scripts/map/build_upcoming_path.py \
  --db mapdata/dist-v3/baden-wuerttemberg-v1.5-lookahead/speeds_v3.sqlite \
  --input-pbf mapdata/raw/baden-wuerttemberg-260913.osm.pbf \
  --report mapdata/dist-v3/baden-wuerttemberg-v1.5-lookahead/upcoming-path-build.json
python3 scripts/map/validate_upcoming_path.py --require \
  --db mapdata/dist-v3/baden-wuerttemberg-v1.5-lookahead/speeds_v3.sqlite \
  --report mapdata/dist-v3/baden-wuerttemberg-v1.5-lookahead/upcoming-path-validation.json
python3 scripts/map/validate_v3_testing_bundle.py --require-settlement \
  --db mapdata/dist-v3/baden-wuerttemberg-v1.5-lookahead/speeds_v3.sqlite \
  --out-json mapdata/dist-v3/baden-wuerttemberg-v1.5-lookahead/structural-validation.json
python3 scripts/map/export_upcoming_speed_limit_probe.py \
  --db mapdata/dist-v3/baden-wuerttemberg-v1.5-lookahead/speeds_v3.sqlite \
  --out-dir output/upcoming-speed-limit-bw-probe-new --count 5
```

The exporter refuses to overwrite an existing probe. Its small database is a
native test fixture, not a globally complete/installable BW bundle. Tests use
the shared corpus and that source-backed fixture; the full database validators
run separately. Packaging uses the existing `publish_v3_bundle.py` local-output
path with `--bundle-version 2026-10-23-v1.5-lookahead --db-compression gzip
--min-app-version 1.5`, followed by `package_mobidata_v1_5_artwork.py`.

No physical-device installation, external release publication or merge is part
of the original implementation validation above. The subsequent user-authorized
installation and full-bundle measurements on both attached phones, plus the
first-drive visibility investigation, are recorded in
[UPCOMING_SPEED_LIMIT_PHYSICAL_VALIDATION_2026-10-23.md](UPCOMING_SPEED_LIMIT_PHYSICAL_VALIDATION_2026-10-23.md).
Actual drive diagnostics await the phones' return. Project-wide release version
defaults were retained; validation builds explicitly used version 1.5 and build
10059. The separate
[encoding investigation](MAP_RUNTIME_ENCODING_INVESTIGATION_2026-10-23.md)
measures a compact topology representation and recommends a staged runtime
archive migration.

## Accepted town-entry preview (2026-10-24)

Both native readers also preview the implied German town-entry limit of 50 km/h
from an accepted, directed `DE:310` physical station. The existing
`traffic_sign_way_rule` must have `inside_city=1`, no numeric speed, `lane_scope=all`,
and a unique immediately applicable interval after the station. A zero-length
origin at a certified split needs the same source's verified continuing rule.
The preview retains the boundary's sign ID, publisher, snapshot and physical
origin; it uses the existing numeric preview UI and does not change current
speed authority.

A freshly posted numeric limit at the same station takes precedence over the
implied default. Missing/ambiguous associations, unresolved lanes, conflicting
post-station rules and `DE:311` remain stopping events. An OSM town entry on a
conditional OSM road is withheld instead of flattening its conditions into 50;
an independently accepted government boundary keeps its existing higher source
priority. BW-only MobiData filtering remains in force. No bundle rebuild or
schema change is required for the installed v1.5 bundle.

Native reader regressions cover forward/reverse entry, exit and unresolved
locality, co-station explicit 30 and conditional scope, government/OSM priority,
and certified reverse-child continuation. Shared tracker cases cover showing
50, hiding it under a usable current 30, and suppressing it after passage/jitter.
