# v1.5 MobiData BW local test-bundle record

Built 2026-10-21 on `codex/youspeed-v1.5-mobidata-bw`. The
[implementation specification](MOBIDATA_BW_V1_5_SPEC.md) describes the remaining
iPhone/Android work. This is a **disabled data-contract pilot**, not a working
mobile integration or a field-ready driving bundle. No release was published.

## Artifacts

Bundle folder:
`mapdata/bundles/v3/baden-wuerttemberg/2026-10-21-v1.5-mobidata-pilot/`.

| Artifact | Purpose |
| --- | --- |
| `baden-wuerttemberg_manifest.json` | Standard v3 local bundle manifest, schema 1, minimum existing app version 1.1 |
| `baden-wuerttemberg_speeds.sqlite.gz` | Full BW road/settlement/inventory DB plus disabled proposal tables |
| `pilot-manifest.json` | Explicit pilot capabilities, limitations and sidecar checksums |
| `pilot-report.json` | Source/counts/normalization/association diagnostics |
| `validation.json` | Schema and row-hash comparison of all original tables; pilot invariants |
| `structural-validation.json` | Current road-bundle readiness gate result (`ready=false`) |
| `pictogram-audit.json` | All 53 literal source-code mappings and pinned-model limitations |
| `sign-pictograms/` | 43 existing official SVG/PNG pairs, subset source manifest, coverage and notices |
| `review-examples.json` | One actual source record per exact code, with proposal and candidate evidence |
| `synthetic-parameter-fixtures.json` | Explicitly synthetic future grade/mass/dimension parsing examples; not BW records |
| `IMPLEMENTATION_SPEC.md`, `LOCAL_REVIEW.txt` | Offline review instructions and scope |

The materialized query DB is
`mapdata/dist-v3/baden-wuerttemberg-v1.5-mobidata-pilot/speeds_v3.sqlite`.
The uncompressed DB and compressed payload are generated local artifacts ignored
by Git; lightweight manifests, scripts, tests and docs remain reviewable in the
working tree. Standard bundle consumers ignore the artwork/review sidecars and
the proposal tables. The minimum app version is installation compatibility,
not a claim that version 1.1 implements v1.5 behavior.

## Checksums and source

| Material | Bytes | SHA-256 |
| --- | ---: | --- |
| Uncompressed DB | 1,556,500,480 | `8dc18a7939248fd3a15b3a524fb2251d0e3016730fe8a1767dce3e0accef0633` |
| Gzip DB | 519,128,855 | `4b3ecbdc3787de83e0c32764ea9b3da7d9803a10088fe9951c074b31a297217b` |
| Source GeoJSON | 87,275,340 | `cb4c89d3d2b18a06a1d5956b94865310929ff455d7a33005053bccaac66b79c3` |

The fresh source download was byte-identical to the previous import. Source
timestamp is `2026-10-17T22:00:00.013Z`. OSM was **not refreshed**: the road and
settlement data are from the September settlement pilot. The original inventory
base is `mapdata/dist-v3/baden-wuerttemberg-inventory/speeds_v3.sqlite`, SHA-256
`33e635306bb8515f994857628f019bfcc34b71b320556e9195905b2c0e6b2ee5`.

## Contents and interpretation

| Result | Count |
| --- | ---: |
| Source records / exact codes | 163,504 / 53 |
| Disabled rule proposals | 163,504 |
| DE:310/311 boundary proposals, radius 30 m | 23,100 |
| Other proposals, radius 10 m | 140,404 |
| Speed-limit proposals, including one variable-message record | 83,276 |
| Static parsed speed values | 83,275 |
| Speed-end records with no printed value | 9,769 |
| OSM geometric candidate links within 30 m | 586,706 |
| Signs with multiple candidate ways | 135,469 |
| Signs with one candidate, direction unverified | 27,973 |
| Signs with no candidate | 62 |
| Invalid candidate geometry | 0 |

These are geometric candidates, not accepted OSM associations. Distances,
chainage and tangents use the base DB's stored geometry. OpenLR is preserved but
not decoded, and orientation semantics are not validated. Even a single candidate
has unknown travel direction. None of the rows is eligible for a runtime rule.

`traffic_sign_v15_rule` contains exact/normalized code, family, typed numeric
value/unit/status, proposed radius and town-boundary/reset event. It has
`CHECK(enabled=0)`. `traffic_sign_v15_way_candidate` stores the projected segment,
position/distance/chainage/local heading, original OSM speed, candidate ranking,
ambiguity and unknown travel direction; it is also constrained disabled.
`traffic_sign_v15_metadata` contains the proposal-only capability/report. All
original tables, including the old metadata and `inventory_only` source role,
are unchanged.

The 43 packaged artwork pairs are the existing mapped official bytes, with
hashes and licences verified. Six missing artwork codes cover 512 records and
remain explicit in `coverage.json`; missing printed values and source annotations
also remain blocked. No new official artwork or training images were acquired
in this specification/pilot step. The model has no DE:310/311 output, and the
snapshot has no grade/mass/dimension signs. Synthetic parameter examples exercise
the parser without adding invented observations to the database.

## Reproduce the data build

Run from the repository root. Use a new output directory or intentionally replace
your own prior local pilot; do not overwrite the inventory base.

```sh
# Fresh source; compare its SHA-256 with the pinned value above.
python3 scripts/map/traffic_sign_inventory.py download \
  --output /private/tmp/youspeed-v15-signs.geojson

# On this Mac, make a copy-on-write clone of the verified existing inventory DB.
mkdir -p mapdata/dist-v3/baden-wuerttemberg-v1.5-mobidata-pilot
cp -c mapdata/dist-v3/baden-wuerttemberg-inventory/speeds_v3.sqlite \
  mapdata/dist-v3/baden-wuerttemberg-v1.5-mobidata-pilot/speeds_v3.sqlite

# If starting from another road DB, first run the inventory importer against
# that clone with the verified GeoJSON. Never modify the protected policy.
python3 scripts/map/build_mobidata_v1_5_pilot.py \
  --db mapdata/dist-v3/baden-wuerttemberg-v1.5-mobidata-pilot/speeds_v3.sqlite \
  --report mapdata/dist-v3/baden-wuerttemberg-v1.5-mobidata-pilot/pilot-report.json

# This command writes local files only; no release/upload arguments are used.
python3 scripts/map/publish_v3_bundle.py \
  --region baden-wuerttemberg --country-code DEU \
  --db mapdata/dist-v3/baden-wuerttemberg-v1.5-mobidata-pilot/speeds_v3.sqlite \
  --bundle-version 2026-10-21-v1.5-mobidata-pilot \
  --out-root mapdata/bundles/v3 --db-compression gzip --min-app-version 1.1 \
  --coverage-poly mapdata/raw/baden-wuerttemberg-settlement-pilot.poly
python3 scripts/map/package_mobidata_v1_5_artwork.py \
  --bundle-dir mapdata/bundles/v3/baden-wuerttemberg/2026-10-21-v1.5-mobidata-pilot
```

These commands reproduce the DB/enrichment and artwork subset. Review examples,
spec copies, validation receipts and `pilot-manifest.json` describe this specific
local build; the standard manifest creation timestamp is run-specific.

Inspect the proposal join without applying rules:

```sql
SELECT r.literal_code,r.numeric_value,r.unit,r.parameter_status,
       r.display_radius_m,r.association_status,c.way_id,c.distance_m,
       c.chainage_m,c.local_heading_deg,c.osm_maxspeed,c.travel_direction
FROM traffic_sign_v15_rule r
LEFT JOIN traffic_sign_v15_way_candidate c USING(inventory_row_id)
WHERE r.inventory_row_id = :inventory_row_id
ORDER BY c.candidate_rank;
```

## Verification and remaining gate failures

All **52 original tables** have matching schema SQL, row counts and streamed row
hashes. `PRAGMA quick_check` is `ok`; `PRAGMA foreign_key_check` is empty. There is
one disabled proposal for every source record; all candidates are disabled with
unknown direction; radii match 10/30 m; every candidate distance is within 30 m.
The gzip stream materializes to the DB hash above.

Focused checks: 13 pilot tests, 7 existing inventory tests and 4 artwork packager
tests pass. All 111 shared artwork pairs pass offline verification. Shared policy
verification passes 39 scenarios / 171 steps, all 16 transitions and 5 states,
with both app pins unchanged. The additional coordinate guards and explicit SQL
column ordering were tested after enrichment; they do not change valid BW output.

The current structural road-bundle gate exits 1 with the **same ten errors as the
base**, and zero new errors: missing detailed way links, directed motorway-exit
approaches, corridor tables/mode, and source-geometry capabilities/coverage.
These are preserved failures, not waived checks. See `structural-validation.json`.
This step includes no mobile/device validation. The new geofences, controller
boundary integration, confirmation log and capture setting remain implementation
work in the linked specification.
