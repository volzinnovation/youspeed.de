# Switzerland test preparation — 27 September 2026

The published Swiss bundle is valid but does not contain all current map data
structures. This review compares the actual downloaded SQLite database with the
current iPhone reference implementation and Android consumer. A successful
installation or the unchanged outer `v3` / `schema_version=1` label alone is
insufficient to establish structural freshness.

## Published bundle inspected

- Release: [switzerland](https://github.com/volzinnovation/youspeed.de/releases/tag/switzerland).
- Bundle version `2026-09-15`, published 16 September 2026.
- Compressed download: 365,113,616 bytes; materialized database: 1,103,953,920 bytes.
- Database SHA-256: `09b458e74a77bfc501b0d66433de54c4416ebd5f5e2c30da6c3b276c88441941`.
- Compressed and materialized checksums, polygon and delta-index checksums,
  manifest JSON schema, and SQLite `quick_check` all pass.
- Empty delta index: there is no subsequent incremental update in that release.

| Structure | Published Swiss bundle | Rebuilt local bundle |
| --- | --- | --- |
| Baseline roads, geometry, endpoint and spatial indexes | Present; 887,724 ways | Present; 888,482 ways |
| Surface/tunnel/motorway network split | Present | 873,788 / 6,293 / 8,401 ways |
| Connected route and street-name continuity | Present | 64,810 groups, 348,135 memberships |
| Detailed `way_links` with shared endpoint/ref | Absent; `way_links_mode=none` | 1,303,182 detailed links |
| Directed `motorway_exit_approach` | Absent | 2,292 approaches; capability v1 |
| Original road vertices | Legacy 24-point cap; no source-vertex capability metadata | `source_vertices_v1` for every road |
| Settlement extension v1 | Present, country `CH`; 1,122,891 segments, every way covered | 1,123,717 segments; every way covered |
| Minimum app version | `1.0.0`, despite settlement v1 | `1.1`; field testing should use the current 1.2 build |
| Checksum-pinned Swiss penalty-rule artifact | Absent from manifest | Shared `CHE-rules.json` included and byte-verified |
| Optional corridor precomputation | Absent | Explicit `corridor_progress_mode=none`; no corridor tables required |

The old settlement data has no orphan segments or invalid booleans. It contains
22,235 high-confidence segments, 631,603 low-confidence landuse segments and
469,053 unknown/conflicting segments. These are segment counts, not accuracy
measurements or proportions of driven distance. Unknown and weak settlement
evidence must retain the existing conservative runtime behavior.

A complete scan confirms the published road geometry has at most 24 vertices
per way; 50,042 ways reach that cap. Streaming validation also checked all road,
settlement, area and ring coordinate arrays and R-tree containment, with no
corruption found. The reported gaps are generation/capability freshness issues.

## Prepared local artifact

Full bundle version **`2026-09-27-swiss-test`** is in
`mapdata/bundles/v3/switzerland/2026-09-27-swiss-test/`:

- [Manifest](../mapdata/bundles/v3/switzerland/2026-09-27-swiss-test/switzerland_manifest.json).
- `switzerland_speeds.sqlite.gz`: 416,646,575 bytes;
  SHA-256 `2211b7b8e18eb8cd1ffc17dca56b9a55e3b0acecfe60fd72635ff2baefcaf610`.
- Materialized DB: 1,256,435,712 bytes;
  SHA-256 `44176ac7aee8620c1b1ef8197b28629386c02bb943ca9226dc9570a259614a9b`.
- `CHE-rules.json` and `switzerland.poly`, checksum-pinned by the manifest.

The current-structure gate passes with zero errors or warnings. Road and
settlement coordinate arrays are valid; indexes, references, country metadata,
source-geometry coverage and settlement evidence pass. Every road has settlement
coverage, with no incomplete source ways, zero-length ways or fallback geometry.
The new geometry has up to 1,288 vertices per way, with 46,589 roads exceeding
the old 24-point limit. Manifest schema, all three packaged artifact sizes and
SHA-256 checksums, gzip CRC/decompression, materialized DB checksum, and exact
shared-rules byte identity also pass.
The prepared package has been installed on the attached Android and iPhone
with owner authorization. The public release remains unchanged.

## Fresh source and regression evidence

The replacement uses the checksum-verified
[26 September Geofabrik extract](https://download.geofabrik.de/europe/switzerland-260926.osm.pbf),
547,107,301 bytes, replication timestamp `2026-09-26T20:22:51Z`, sequence `4922`.
Its SHA-256 is
`c4d2a651b14476021edf2705434d4e23899e40aeda7659f16ae876853d0bebb5`;
its MD5 matches the provider's `802031a0812a4f13bb91c1d44492d6d3`.

The selected regression suite passes **165 tests and 42 subtests**. Coverage
includes generation/workflow arguments, release-target resolution, country
discovery, source-to-settlement geometry and direction, motorway exits, v3
pipeline and deltas, bundle packaging, sign contracts/mappings/artwork, and the
new read-only validator. All 12 shared country rules pass the packaging check.
The validator's corruption cases refresh manifest hashes before checking invalid
geometry, spatial bounds, required references and artifact fields, so a digest
failure cannot conceal a structural-validation gap.

A macOS Swift probe compiled the actual current iPhone matcher, lookup resources,
road defaults, applicability and lookup service. With explicit country `CHE`,
four deterministic anchors in the published DB select the expected roads:
urban `4006662` (50, inside), rural `4262122` (80, outside), motorway `4042412`
(120, unknown settlement), and tunnel `3728938` (50, tunnel). This uses preferred
way context; the tunnel probe starts in tunnel mode. It confirms host SQL and
lookup compatibility, not physical-device behavior or surveyed route transitions.

All four anchors also pass against the rebuilt DB. A fifth probe selects motorway
way `4072257` and asserts the new directed-exit capability and expected branch
`204734505`, including its class, direction, heading and distance. The reported
110.618070 m distance matches 70.618015 m beyond the current way endpoint plus
40 m remaining on that way. This exercises lookahead across a mainline way split.
All five probes pass with one database open and 22 prepared statements.

Local evidence is retained under `tmp/switzerland-readiness/`:
`published-validation.json`, `rebuilt-validation.json`,
`artifact-verification.json`, `source-provenance.json`, `regression-tests.log`,
`build.log`, and `fresh-swift-lookup.json` / `fresh-swift-lookup-assertions.txt`.

## Installation on the attached phones

On 27 September the owner authorized installation on both attached devices.
Both retain their existing app version 1.2, build 10015, and now activate Swiss
bundle `2026-09-27-swiss-test`, country `CHE`. The materialized database is
1,256,435,712 bytes on each phone, with the exact SHA-256 recorded above.

- **Android, moto g86 5G:** the production local-bundle installer validated and
  installed the full package. An opt-in instrumentation harness verified the
  active state, installed database digest, Swiss rules and all five lookup
  anchors. Existing maps and preferences were preserved. Only the test APK was
  updated; the installed app APK was unchanged.
- **iPhone 14 Pro:** the database, rules and coverage polygon were copied to a
  separate version directory while the app was stopped, followed by its
  canonical installed manifest and active-state registration. Older maps were
  retained. A temporary signed XCTest bundle ran inside the existing app using
  destination artifacts; the app executable was not replaced. It verified the
  installed digest, downloaded-bundle discovery, Swiss routing and rules, and
  all five lookup anchors. Verification preserved the active-state bytes. The
  manifest, rules and polygon were read back byte-identically. Normal startup
  was observed through QuickTime, with the new active version retained. This
  observation did not establish correct live routing at the French location;
  the subsequent regression below invalidated that readiness assumption.

Both clients select the new bundle for the probe coordinates and return urban
50 km/h / inside, rural 80 km/h / outside, motorway 120 km/h, tunnel 50 km/h and
motorway exit `204734505` at approximately 110.618 m. These deterministic device
checks use preferred-way context and an initialized tunnel state, as in the
host probes; they do not substitute for the route transitions below.

The Android instrumentation run reported individual lookups of approximately
1.1–2.4 seconds; the iPhone run reported 14–48 ms. The harnesses and devices are
not a controlled performance comparison. Android lookup responsiveness remains
an explicit field-test observation, not a passed performance acceptance test.

Installation receipts, active-state backups, test harnesses, diagnostics and
screenshots are retained locally under
`tmp/switzerland-readiness/device-install/android/` and
`tmp/switzerland-readiness/device-install/iphone/`.

## Subsequent Lyon routing regression

The owner reported both apps losing city context at approximately 45.720 N,
5.078 E after Swiss installation. The Rhône-Alpes database is intact: its
materialized SHA-256 is
`b869226cc159493b8a9a04c7f5050d6a3e0764603ce4e3a8348ae293a10a1622`, and its
coverage includes the reported position. Native lookups return
Colombier-Saugnieu (Rhône).

The live routing code admitted the active database even when it did not cover
the GPS fix. With the selected narrow-window matcher, the precise reported
positions could have no road within 10 m in either database. The tie-breaking
logic then retained Switzerland, losing available French city context. The
regional download prompt independently saw installed Rhône-Alpes coverage and
correctly declined to offer another download.

Git identifies the active-database append and incumbent tie behavior in commit
`ad18454e22062136f27b582fae95aa425afe8dc2` (18 September, “Improve cross-platform
traffic sign resolution”). Commit `231ec2f191177819e70030cd2da4698916179594`
(23 September, “Improve subscreen navigation and regional bundle downloads”)
added the separate installed-coverage/download check while preserving fallback.
The Swiss-only installation probes did not cover this live cross-region case.

Restoring Rhône-Alpes as the startup active state is a temporary recovery only;
Switzerland and all other installed maps remain present. The owner explicitly
requires selection per GPS fix, with no fixed bundle or out-of-coverage lookup
fallback. The permanent client correction now restricts live lookups to geographically
covering bundles on every fix, including the Android coarse-city path. With no
coverage it clears map identity/city/way context and preserves the regional
download recommendation. Reader/statement caches and the protected LAST_KNOWN
speed policy remain unchanged. Repeated uncovered fixes do not repeatedly
invalidate source generations. Installed-map inventory remains available for
onboarding and reentry.

Validation passed: 45 focused Android tests and five iOS simulator tests. The
iOS view-model integration test covers persisted Swiss → French no-road M7,
repeated fixes with unchanged opens/prepares, leaving installed coverage, the
download recommendation, reentry to the same cached reader, and France → Swiss
→ France. Full Android controller instrumentation was not run in this pass;
Android has native reproduction evidence, the targeted unit suites, and an
independent source review. Both signed app candidates were built successfully,
but the permanent app update has not been installed on the physical phones.

Android's earlier searching indicator reflected fresh coarse 100 m fixes; later
GPS accuracy improved to approximately 13 m without a settings change. After
temporary recovery both actual phone screens showed Rue d’Espagne,
Colombier-Saugnieu, Rhône, and a 50 km/h map match. The iPhone drive log confirms
way 5068406 and repeated 13–15 ms lookups. Investigation evidence is under
`tmp/switzerland-readiness/device-install/android/bug-diagnosis.md`,
`tmp/switzerland-readiness/lyon-routing-regression/` and
`tmp/rhone-alpes-investigation/`.

## Build and repeat the check

The local generator and GitHub workflow now request detailed links for CH.
The Swiss targets in both apps attach `shared/Rules/CHE-rules.json`. The regional
discovery catalog's target checksum is refreshed; its existing source provenance
and all 51 region geometries are preserved. Swiss settlement remains an explicit
build option. No speed-reference policy or interpreter behavior is changed.

With Python dependencies from `scripts/map/requirements-settlement.txt` available:

```sh
python3 scripts/map/generate_v3_country_bundles.py \
  --bundle-country switzerland \
  --bundle-version 2026-09-27-swiss-test \
  --build-settlement-context \
  --skip-release-urls --execute

python3 scripts/map/validate_v3_testing_bundle.py \
  --db mapdata/dist-v3/switzerland/speeds_v3.sqlite \
  --manifest mapdata/bundles/v3/switzerland/2026-09-27-swiss-test/switzerland_manifest.json \
  --require-settlement \
  --out-json tmp/switzerland-readiness/rebuilt-validation.json
```

The generator command packages files locally; `--skip-release-urls` avoids
claiming those artifacts are already hosted. Use a full bundle for this update.
If publication is later authorized through the release workflow, enable
`build_settlement_context` and `force_publish`; inspect the source snapshot date
first, because the existing `che-pbf-latest` release is also from 16 September.

## Field checks on both apps

1. The prepared full bundle is installed on both attached phones and its
   version, Swiss/CHE routing, rules and hashes are verified. For field testing,
   restart offline and confirm Swiss map/rule selection in the actual GPS flow.
2. Exercise surveyed town entry and exit in both directions, including Swiss
   `4.27/4.28` and `4.29/4.30` pairs. Check typed urban/rural context and locations
   with missing or ambiguous evidence; a numeric speed alone must not establish
   settlement state.
3. Test posted limits, 20/30 zones and restriction ends. Compare map, camera and
   displayed source/state in the logs against the actual signs. Include the
   existing Swiss motorway/default fallback when the classifier has no output.
4. Include motorway exits beside the main carriageway, parallel roads, curved
   approaches, a tunnel entrance/exit and degraded GPS. Confirm connected-road
   and directed-exit evidence is available without changing the shared policy.
5. Exercise CH↔DE or CH↔FR border changes where the corresponding bundles exist;
   confirm country, rules and model selection follow the accepted transition.
6. Exercise offline launch, recording/capture, Settings pause/resume and app
   background/resume. Compare equivalent iPhone and Android behavior and retain
   their diagnostic traces. Use QuickTime for attached iPhone screen inspection.

Physical-device bundle and lookup checks passed as recorded above. Swiss
on-road behavior and camera recognition have not been field-tested by this work.

## Separate camera and rules limitations

The bundled Swiss model remains an uncalibrated evaluation/shadow pack, absent
from the production country registry. Both schema-v1 manifests validate and
their 127 class mappings agree. The classifier has no numeric `120`, 30-zone-end,
or town/motorway-transition output. Artwork aliases cannot add model classes;
these scenarios need explicit field coverage of the existing fallback behavior.
The Swiss parity record still says device execution was not measured.

All 116 Swiss SVG/PNG pairs match the shared artwork manifest. The Swiss iPhone
classifier and both Android model artifacts match their pinned hashes. A
pre-existing issue affects the shared iPhone detector in all five country packs:
the repository's `tree_sha256` method yields
`c9c2d68ad9f91168e5a6cc6c80ca2ff1d35b3bda31636796ad49ff237ae335ff`, while the
manifests pin
`96c782afde62e1ede1d47d9d51b64359102170ed3ab6604838609869fcbd4589`.
This is a provenance discrepancy, not an observed startup failure; detector
bytes and model manifests were not changed in this map preparation.

Swiss penalty-rule contents were checked for structural inclusion and shared
packaging only. Their source-check date remains 4 July 2026. Their urban/rural
schema represents motorway distinctions only in explanatory text; this work
does not constitute a new legal-content review.

Device installation was explicitly authorized and completed. Publication remains
a separate step requiring owner approval under the repository's `AGENTS.md`.
