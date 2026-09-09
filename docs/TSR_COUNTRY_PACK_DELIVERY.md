# National model packs and first-location setup (#5)

## Implemented first slice

Both mobile apps now carry the same offline region catalog before a map bundle
has been installed. After local startup recovery, a fresh installation requests
location permission. The first finite fix with 0–100 m horizontal accuracy and
an age of at most 30 seconds selects a containing Geofabrik extract. A bounding
box is only an initial filter; selection tests every outer polygon and its
holes. Outer boundaries count as covered, hole boundaries do not. Multiple
matches are ordered by bounding-box area, then stable catalog ID, so only one
initial bundle is selected. Multipart islands are preserved.

The selected map uses the existing manifest/hash-verified bundle downloader.
Initial downloads wait for an unmetered connection unless the user enables
mobile data in map settings. iOS applies the choice to URLSession; Android binds
the initial transfer to the selected network to avoid a Wi-Fi-to-cellular
handover. A successful installation records completion. Existing installations
with downloaded maps retain their selection. Failures keep the setup incomplete
and allow up to three attempts per launch, at least 60 seconds apart; the map
settings provide a location retry and the existing individual map controls.
No location coordinates are sent to a country lookup service.

`shared/tsr/country-pack-registry-v1.json` is a **bundled availability inventory**.
It deliberately has no downloadable model manifests. Germany records its
pending leakage, parity, calibration and licensing work; France is the next
country; Belgium and the Netherlands remain explicit follow-ons. First-location
setup presents this model availability alongside the map status.

The additive discovery schema and delivery-envelope schema keep the existing
inference `model-pack.schema.json` unchanged. The envelope describes artifact
files, platform identities, OSM class mappings, notices/provenance and acceptance
report references. It is a contract for the next installer slice, not a release
approval. DE/FR fixtures contain synthetic model/provenance data, but the registry
references the real byte size and SHA-256 of each fixture envelope. No fixture
is a trained model, accepted license, evaluation result or runtime activation.

Swift and Kotlin discovery implementations verify an out-of-band SHA-256 trust
pin before decoding external registry bytes, reject older generations, gate
expired inventories, enforce compatible app/OS/taxonomy/preprocessing versions,
and expose unavailable, withdrawn, shadow, fixture-only and unenrolled-canary
states. The signed app bundle is the separate trust root for the local inventory.
No remote production endpoint or trust pin is enabled. A caller must persist the
highest verified generation when remote retrieval is implemented. Discoverability
never grants permission to override a speed limit.

## Country boundaries and scope

Geofabrik explicitly describes its polygons as **buffered extract coverage**,
not administrative country boundaries. These geometries choose the map download
and suggest a model-pack country. Overlapping country candidates produce an
unresolved country. The portable country selector accepts location/map context
and an explicit override, suspends eligibility immediately during uncertainty,
and requires three fixes over 15 seconds to change an established country.
This slice does not connect that selector to the existing #4 runtime or expose
a model-country override UI. A subsequent activation slice must supply reviewed
administrative/map country context; an unambiguous extract alone is still not
proof of the physical country, particularly outside supported coverage.

## Maintaining regional polygons

`shared/RegionalCoverage/catalog-v1.json` freezes the geometry from the public
Geofabrik `index-v1.json`, which represents the same clipping coverage as its
`.poly` files. It includes every region in the two apps' current bundle-target
configuration (51 at introduction), including the French overseas regions.
It preserves the source index SHA-256, target configuration SHA-256, original
PBF/`.poly` URLs and Geofabrik/OpenStreetMap attribution. It does not download
PBFs. Both apps package this one generated catalog.

To refresh after changing bundle targets or Geofabrik coverage:

```sh
curl --fail --location --max-time 60 --max-filesize 30000000 \
  https://download.geofabrik.de/index-v1.json -o /tmp/youspeed-geofabrik-index-v1.json
python3 scripts/map/build_mobile_region_catalog.py \
  --index /tmp/youspeed-geofabrik-index-v1.json
python3 -m pytest -q tests/tsr/test_country_pack_discovery.py
```

Review geometry/source changes before shipping. The generator fails if a target
is missing or has an unexpected parent. Tests fail when either mobile target
list differs or the catalog no longer matches its pinned target configuration.
Geofabrik's technical source:
<https://download.geofabrik.de/technical.html>. Source geometry is attributed to
Geofabrik GmbH and OpenStreetMap contributors under ODbL 1.0.

## Remaining implementation in #5

- Remote registry retrieval, cached/offline refresh policy, signed rolling
  registry/key rotation and persistent anti-rollback state.
- Verified resumable **model** transfer, safe artifact installation, atomic
  activation, cache deletion, updates, rollback and offline notices presentation.
  First-location setup currently downloads the map and reports the model as
  unavailable; it does not yet transfer a model when the inventory is changed.
- Runtime country selection/override and adjacent-country preload, with
  authoritative country context and integration into both recognizer loaders.
- German leakage-safe field evaluation and separately calibrated Core ML/LiteRT
  exports, plus actual parity and licensing acceptance evidence. The existing
  pinned leakage audit and grouped-split tooling remain the starting points.
- Reviewed French artifacts and taxonomy, followed by Belgian and Dutch packs.
- Cross-reference/byte verification for delivery envelopes and a release gate
  that evaluates report evidence; JSON schema validity alone cannot approve a
  model, dataset split or license. Human review of publication-facing copy.

Proposed delivery layout for the next slice is public HTTPS GitHub release
assets in this repository, named by pack/version and content SHA-256, without
credentials. Artifact URLs and bytes must be immutable; index generations are
separate assets with bounded freshness. Preserve previously verified versions
for rollback; withdrawal is new authenticated metadata, not overwriting or
deleting an artifact. Cache immutable payloads indefinitely and refresh registry
metadata before new activation. This is a design proposal; no hosting or remote
publication is configured here.

#2 retains the broad recognizer/training work; #4 owns passage/fusion into the
effective speed limit. Analytics #126 owns KI-server operations, inference queues
and Panoramax annotation writes. There is no server inference dependency in this
discovery/setup code. This change does not alter the branch's existing bundled
German runtime or its #4 live-evaluation behavior.

## Verification

```sh
python3 -m pytest -q tests/tsr/test_country_pack_discovery.py
swiftc -module-cache-path /tmp/youspeed-swift-module-cache \
  iphone/SpeedConsumerApp/RegionalPackDiscovery.swift \
  iphone/SpeedConsumerApp/TrafficSignCountryPackRegistry.swift \
  scripts/iphone/test_country_pack_discovery.swift -o /tmp/youspeed-test-country-discovery
/tmp/youspeed-test-country-discovery "$PWD"
cd android
./gradlew :app:testDebugUnitTest :app:assembleDebug --offline
```

Swift and Kotlin replay the same real-city region, country-transition and
registry-decision fixtures. Additional checks cover polygon holes/islands,
repeated vertices, invalid fixes, integrity pins, fixture rejection in production,
expiry and generation rollback. These are discovery tests; they do not claim
physical-device GPS, model-transfer or ML parity acceptance.

Verified locally on 2026-09-06: 264 Python TSR tests, 162 Android unit tests,
Android debug assembly, the shared Swift replay (including resources loaded from
the built app), and an iPhone simulator build passed. The visual UI check remains
unverified because Simulator computer-use automation timed out. No physical-device
first-start download or ML inference acceptance run was performed in this slice.
