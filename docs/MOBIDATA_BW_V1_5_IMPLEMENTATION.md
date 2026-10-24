# BW v1.5 runtime implementation and local acceptance

Implemented on `codex/youspeed-v1.5-mobidata-bw`, 2026-10-21. This is the active
runtime implementation, distinct from the earlier disabled data-contract pilot.
The machine-readable receipt is
[MOBIDATA_BW_V1_5_IMPLEMENTATION.validation.json](MOBIDATA_BW_V1_5_IMPLEMENTATION.validation.json).

The 23 October upcoming-limit extension is recorded separately in
[UPCOMING_SPEED_LIMIT_IMPLEMENTATION.md](UPCOMING_SPEED_LIMIT_IMPLEMENTATION.md).
It adds the directed lookahead topology and a new local bundle version; the
original runtime bundle and the historical acceptance receipts below are preserved.

The local test manifest is
[`baden-wuerttemberg_manifest.json`](../mapdata/bundles/v3/baden-wuerttemberg/2026-10-21-v1.5-runtime/baden-wuerttemberg_manifest.json).
It requires app version 1.5 and remains an ordinary v3 bundle with additive,
optional sign capability version 1. No release upload, merge or physical-device
deployment has been performed.

## Implemented data and behavior

- The rebuilt road base has exact source vertices, full raw OSM tags, detailed
  way links, paired corridors, motorway-exit approaches and complete settlement
  segments. The ten original BW readiness errors were repaired in the actual
  data. [Road-base receipt](MOBIDATA_BW_V1_5_ROAD_READINESS.md).
- All 163,504 MobiData source records retain their snapshot, raw properties and
  attribution. Runtime records have typed numeric value/unit/status, official
  artwork mapping and exact classifier coverage. Original OSM speeds are intact.
- OpenLR two-LRP point references are decoded and dereferenced against this
  bundle's directed road graph. Source confidence, distance, local bearings,
  path length, point offset, motorcar access and competing candidates are checked.
  Ambiguous, low-confidence, unsupported/dynamic or missing references remain
  diagnostic records and cannot become an active speed rule by proximity.
- Speed rules apply to a specific OSM way, travel direction and chainage interval.
  Unbranched continuations of the same road are explicit, bounded and retain
  their directed path proof. Junctions, merges, changed explicit OSM speeds,
  conditional speed uncertainty and lane conflicts stop continuation. A child
  interval is never another physical sign event.
- Directional lane counts and known lane rows are retained without inventing a
  lane split or the vehicle's lane. Conflicting lane speeds and conditional speed
  rules are inactive. Separate carriageways remain separate OSM ways.
- Trusted directed OSM town stations fill gaps under separate ODbL attribution.
  Existing generic `city_limit:begin/end` records use their already-resolved
  Germany inside/outside semantics and retain the original code in evidence.
  Physical signs duplicated by a collinear OSM way split are represented once,
  on the uniquely proven downstream way. Original source keys and suppressed
  station keys remain in evidence.
- Ordinary inventory secondary signs trigger at measured distance **≤10 m**; town signs
  DE:310/311 use **≤30 m**. Following the drive-review clarification, secondary
  cards persist until an applicable newer sign/context replaces or invalidates
  them. Capture still requires the live geofence. Known opposing secondary faces
  are rejected using accepted source heading and qualified actual vehicle course;
  an exact same-way association is not invented for secondary warnings.
  The same secondary-sign surface and shared official
  bytes are used on both platforms. Numeric posted speed uses the existing
  schematic main speed display and directed rule resolver.
- Town station passage sets the inside/outside penalty context and invalidates
  all prior map, camera, zone/pedestrian and local/voice references through the
  existing full boundary reset. It masks an old same-way OSM speed and obtains a
  fresh context/default offer. A fresh posted restriction at the same station
  follows the boundary deterministically. Town context persists across unsigned
  ways until an actual new boundary; derived settlement estimates cannot undo it.
- DE:278/282 use the existing typed speed-end semantics, retaining independently
  observed enclosing zones/pedestrian context. A specified ended value must match.
  Null-speed intervals prevent an old OSM posted value from reappearing at an
  ordinary way split. The protected shared policy and approval lock are unchanged.
- The existing road/camera/settlement behavior remains the fallback for old
  bundles, other regions and missing/unknown/malformed optional capability.
  No migration is required for a region with no sign inventory.

The contract and schema are
[`traffic_sign_runtime_v1.md`](../mapdata/spec/traffic_sign_runtime_v1.md) and
[`traffic_sign_runtime_v1.sql`](../mapdata/spec/traffic_sign_runtime_v1.sql).

The generated bundle contains 172,304 runtime signs (including 8,800 OSM gap
stations), 118,400 directed intervals and 37,807 continuation proofs. Of those
intervals, 116,446 have all-lane scope, 1,943 are conditional and 11 have unresolved
lane limits. All 1,085,790 admitted ways have direction metadata; 211,353 explicit
lane rows are retained. There are 110,639 accepted physical associations across
all sign kinds, including 54,331 posted-speed associations. Rejections and
conflicts remain queryable rather than being replaced with nearest-road guesses.
The bundle's `runtime-diagnostics.json` includes per-kind counts and four nearby
Karlsruhe-area source-backed inspection targets.

## Camera confirmation, logs and capture

The camera must already be active. Inventory proximity never activates it and
never claims a visual detection. Position fixes must be fresh (3 s), have
accuracy ≤25 m, and have a stable matched way and accepted direction for numeric
speed/town actions. Heading and heading accuracy use the same 35° gates on both
platforms. The physical display radii are never enlarged by GPS uncertainty.

Exact confirmation requires two distinct real processed frames spanning at least
100 ms, confidence ≥0.90, overlap ≥0.30, consistent model/pack identity, unique
class/value association and correct bundle/way/direction. High-frame-rate evidence
keeps the original supporting frame; a final confirmation is logged once.
Unsupported classes, wrong faces, ambiguity, camera off/unavailable, mismatches
and completed unobserved attempts have distinct outcomes. Unverified annotations,
dynamic state and invalid source values cannot qualify, even when an exact label
exists in the classifier vocabulary. Confirmation is only claimed after the
durable append succeeds. Invalid fixes cannot re-arm a
consumed town sign or bridge a passage; actual exit/re-entry, reversal and bundle
changes have explicit lifecycle handling.

Both apps provide a separate local append-only NDJSON encounter log containing
source and bundle identity, encounter UUID, fix/heading accuracy, directed match,
model/checkpoint, supporting frame identities and capture/result links. Late
capture callbacks retain the original encounter and position even after re-entry.
Logs can be shared from Diagnostics without silently uploading them:

- iPhone: `Library/Application Support/InventorySignEncounters/events.ndjson`.
- Android: `files/inventory-signs/encounters.ndjson`.

The new inventory/bundle-sign-only Panoramax capture setting is mutually exclusive
with recognized-sign-only capture. Cadence preferences and existing defaults are
preserved. Captures inside the 10/30 m geofence use `captureReason=inventory_sign`
and encounter UUIDs, coalesce simultaneous encounters, respect existing camera,
motion, consent, storage, privacy and rate gates, and retry failed commits.
A proximity capture remains distinct from camera confirmation.

## Pictograms and parameter coverage

All six formerly missing artworks are included as official-source SVG plus
transparent PNG: DE:101-15, 156-10, 223.1-50, 325.1, 325.2 and 460-20. The full
shared set has 117 pairs with pinned source/license/hash provenance. Both app
packages use those shared bytes. The bundle includes its 49-pair mapped subset,
audit and notices. [Complete source-code audit](MOBIDATA_BW_PICTOGRAM_AUDIT_V1_5.md).

Typed parsing/storage and supplementary text presentation support incline/decline
percent, total/axle mass in tonnes and width/height/length in metres. This source
snapshot contains **zero** DE:108/110 or DE:262–266 records and no independent
printed restriction field, so the BW bundle cannot demonstrate observed values
for those families. Such values must come from an attributed source record;
generic classifier labels never manufacture them. Unknown artwork is shown as
code/value text rather than substitute artwork.

Artwork does not extend the classifier. The current DE model has no DE:310/311
or numeric 90 output; other absent/family-only entries are listed in the audit.
Their encounters log `unsupported_model_class`. New attributed training imagery,
model training, calibration and measured per-class visual recall are outstanding;
no new classifier capability is claimed.

## Reproduction and installation

Use the pinned map/sign dependencies, including `openlr==1.0.1`,
`osmium==4.3.0`, `Shapely==2.1.2` and `NumPy==2.2.6`. The source PBF is
`mapdata/raw/baden-wuerttemberg-260913.osm.pbf` with replication timestamp
`2026-09-13T20:21:20Z`, SHA-256
`1856f4ac7c18435e17d74c7ba24a7b21b3a1231e60449851890dc0109638ded3`.
The MobiData snapshot timestamp is `2026-10-17T22:00:00.013Z`, SHA-256
`cb4c89d3d2b18a06a1d5956b94865310929ff455d7a33005053bccaac66b79c3`.
The pinned download is retained at `mapdata/raw/mobidata-bw-signs-20261021.geojson`.
This is a complete rebuild from pinned September roads, not an October OSM refresh.

```sh
python3 scripts/map/rebuild_bw_v15_roads.py \
  --input-pbf mapdata/raw/baden-wuerttemberg-260913.osm.pbf \
  --geojson mapdata/raw/mobidata-bw-signs-20261021.geojson --execute
mkdir -p mapdata/dist-v3/baden-wuerttemberg-v1.5-runtime
cp -c mapdata/dist-v3/baden-wuerttemberg-v1.5-roads/speeds_v3.sqlite \
  mapdata/dist-v3/baden-wuerttemberg-v1.5-runtime/speeds_v3.sqlite
python3 scripts/map/build_traffic_sign_runtime.py \
  --db mapdata/dist-v3/baden-wuerttemberg-v1.5-runtime/speeds_v3.sqlite \
  --ways-meta mapdata/dist/baden-wuerttemberg-v1.5-roads/ways.meta \
  --report mapdata/dist-v3/baden-wuerttemberg-v1.5-runtime/runtime-report.json
python3 scripts/map/validate_traffic_sign_runtime.py --require \
  --db mapdata/dist-v3/baden-wuerttemberg-v1.5-runtime/speeds_v3.sqlite \
  --out-json mapdata/dist-v3/baden-wuerttemberg-v1.5-runtime/runtime-validation.json
python3 scripts/map/validate_v3_testing_bundle.py --require-settlement \
  --db mapdata/dist-v3/baden-wuerttemberg-v1.5-runtime/speeds_v3.sqlite \
  --out-json mapdata/dist-v3/baden-wuerttemberg-v1.5-runtime/structural-validation.json
python3 scripts/map/publish_v3_bundle.py --region baden-wuerttemberg --country-code DEU \
  --db mapdata/dist-v3/baden-wuerttemberg-v1.5-runtime/speeds_v3.sqlite \
  --bundle-version 2026-10-21-v1.5-runtime --out-root mapdata/bundles/v3 \
  --db-compression gzip --min-app-version 1.5 \
  --coverage-poly mapdata/raw/baden-wuerttemberg-settlement-pilot.poly
python3 scripts/map/package_mobidata_v1_5_artwork.py \
  --bundle-dir mapdata/bundles/v3/baden-wuerttemberg/2026-10-21-v1.5-runtime
```

The road helper refuses to replace an existing output unless `--replace-output`
is explicit. `cp -c` uses an APFS clone on this Mac; use a normal copy on another
filesystem. The script named `publish_v3_bundle.py` only writes local artifacts
with the arguments above. No release destination is configured.

Android emulator build, normal bundle-loader installation, SHA verification and
full-database instrumentation commands are in
[android/README.md](../android/README.md#local-v15-traffic-sign-bundle-test-emulator).
The isolated application is `de.youspeed.android.testhost`, version 1.5/10057.

The isolated iPhone simulator app is `de.youspeed.SpeedConsumer.TestHost`, built
with `YOUSPEED_TEST_BUNDLE_SUFFIX=.TestHost MARKETING_VERSION=1.5`
`CURRENT_PROJECT_VERSION=10057`. In its data container, place the materialized
DB, `bundle-manifest.v3.json` and the coverage poly in
`Library/Application Support/SpeedConsumer/bundles/baden-wuerttemberg-2026-10-21-v1.5-runtime/`.
The `SpeedConsumer/active_bundle.json` record has `region`, `bundle_version`,
`db_file_name`, `db_sha256` (the uncompressed SHA) and `activated_at_utc` fields.
Startup discovers and validates this through the existing bundle loader. Test
build overrides preserve the unrelated pending 1.4 release work/defaults.

## Validation scope

Final local acceptance passed: **131 distinct iPhone tests** (130 selected
regressions plus the separate full-BW loader/service/controller probe),
**152 Android unit tests** and **17 Android emulator tests**. Both platforms
loaded the corrected materialized DB with SHA-256
`e1a36e56cc4809cc69d2d5161b993eff21a1c08264e8d9300e79ec7546ccd00b`.
Both structural readiness and the optional sign-runtime gate report zero errors;
the structural gate also has zero warnings. Platform receipts are
[iPhone](MOBIDATA_BW_V1_5_IPHONE_ACCEPTANCE.json) and
[Android](MOBIDATA_BW_V1_5_ANDROID_ACCEPTANCE.json).

The receipt records final DB/artifact hashes, counts and gate results. Automated
fixtures cover directed/reverse/parallel roads, lane conflicts, continuation and
physical-event separation, co-located town/fresh-speed ordering, end masks,
source attribution, exact radii, town latch/reset lifecycle, camera states,
confidence/frame/model consistency, durable log/capture retry and old/no-data
bundles. Shared protected-policy scenarios remain unchanged.

Simulator/emulator acceptance checks actual mobile SQLite loading and runtime
behavior. These checks do not establish surveyed physical sign accuracy or a
live-camera drive.

## Attached-device test installation

The user authorized installation of version 1.5/build 10057 and the final BW
bundle on the attached iPhone and Android phone, with camera-based TSR disabled.
The physical installation receipts are separate from the earlier isolated test
receipts: [iPhone](MOBIDATA_BW_V1_5_IPHONE_DEVICE_INSTALL.json) and
[Android](MOBIDATA_BW_V1_5_ANDROID_DEVICE_INSTALL.json). Their status fields record
the completed installation and readiness checks. The packaged bundle and its
acceptance snapshot remain unchanged.

Both test configurations enable secondary-sign display and ordinary photo
capture with **inventory signs only**, disable **recognized signs only**, and
disable both recording-dependent and independent camera recognition. Other
existing preferences, downloaded maps and media are retained. The installed
uncompressed databases are checked against SHA-256
`e1a36e56cc4809cc69d2d5161b993eff21a1c08264e8d9300e79ec7546ccd00b`.

Before the drive, start the normal drive-recording session with photo capture
enabled. Inventory geofences, directed speed rules and town-boundary resets
remain active while TSR is off. Inventory photos still require the existing
movement, GPS-quality, foreground, storage and camera-readiness gates. Encounters
are logged as `camera_off`; a captured photo does not become a visual
confirmation. Export the offline-sign encounter log through **Settings → Debug →
Debug information → Logs → Share offline-sign encounter log** (German:
**Offline-Zeichen-Sichtungslog teilen**). No synthetic GPS or real-drive acceptance result
is claimed by the installation receipts.

The first Android attached-device dashboard, photo-camera readiness and TSR-off
UI checks passed. The first iPhone installation was verified before its final UI
check was interrupted by disconnection. Both phones were subsequently reconnected
for the real-drive log review. The later installation receipts and
[drive review](MOBIDATA_BW_V1_5_DRIVE_REVIEW_2026-10-21.md) distinguish those stages.
