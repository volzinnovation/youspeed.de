# Additive settlement context, version 1

This extension is opt-in for regional and country bundle generation. The existing
SQLite `metadata.schema_version=1` and legacy tables remain available. Consumers
detect `metadata.settlement_context_version=1` before querying these tables.

The **only settlement state attribute is `inside_city`**, a nullable SQLite
integer: `1` means inside, `0` outside, and SQL `NULL` unknown. There is no state
enum or separate unknown flag. Source and confidence describe the evidence, not
an additional city state. Explicit conflicts produce `NULL`.

## Tables

`settlement_segment`:

| Column | Meaning |
| --- | --- |
| `segment_id INTEGER PRIMARY KEY` | Stable within a way: `way_id * 1048576 + segment_index * 4 + direction + 1`. Changes to unrelated ways do not renumber it. |
| `way_id INTEGER NOT NULL` | OSM way ID; indexed by `idx_settlement_segment_way`. |
| `segment_index INTEGER NOT NULL` | Zero-based interval ordered along the original OSM way. |
| `direction INTEGER NOT NULL` | `1` OSM forward, `-1` reverse, `0` both. |
| `inside_city INTEGER` | Nullable boolean, constrained to `0`, `1`, or `NULL`. |
| `source TEXT NOT NULL` | `zone_traffic`, `maxspeed_type`, `source_maxspeed`, `traffic_sign`, `urban_polygon`, `landuse`, `conflict`, or `missing`. |
| `confidence TEXT NOT NULL` | `high`, `low`, or `unknown`. |
| `evidence_json TEXT NOT NULL` | Source observations including tag values, area/sign IDs, and nullable `inside_city`. Bidirectional rows preserve explanations for both directions. |
| `points_json TEXT NOT NULL` | Segment polyline as **`[latitude, longitude]`**, matching `way_geom`. |

The two directions collapse into one direction-0 row only when state, source,
and confidence agree. Otherwise both directed rows are emitted, including an
explicit nullable row for a direction with no evidence. Clients select the
nearest segment on the matched way and its direction, rather than using the
first row or a value applying to the whole way.

`settlement_area` stores `area_id TEXT PRIMARY KEY` (`w:ID` or `r:ID`), `osm_type`,
`osm_id`, `kind`, nullable `inside_city`, `source`, `confidence`, `tags_json`, and
original `min_lon`, `min_lat`, `max_lon`, `max_lat`. `kind` is `urban_polygon` or
`landuse`. Original invalid geometry remains inspectable but is excluded from
classification; its count is in metadata.

`settlement_ring` stores `area_id`, `ring_index`, `outer_index`, `is_hole`, and
`points_json`; its primary key is `(area_id, ring_index)`. Ring coordinates are
**`[longitude, latitude]`**, following the pre-existing area convention. Every
outer component and hole is preserved. Shells and holes are simplified together
with Shapely's topology-preserving metric simplification (default 2 metres).
**Original unsimplified polygons determine road intersection positions and
classification**; simplification affects stored outlines only.

`settlement_sign` stores `sign_id TEXT PRIMARY KEY`, `osm_type`, `osm_id`,
`sign_code`, nullable `inside_city`, `direction`, nullable `way_id`, nullable
`lon`/`lat`, `association`, and full `tags_json`. A node with several interpreted
faces has several stable sign IDs. A safely associated sign at a collinear way
split has one observation per way with a `:w:ID` suffix. Way-tag signs have no
invented position: their coordinates are null and their association is
`way_tag_location_unknown`.

## Evidence and conservative resolution

- Numeric limits, road class, municipal boundaries, and missing landuse never
  establish inside/outside state.
- Country-prefixed `<ISO2>:urban`/`rural` tags are read from `zone:traffic`,
  `maxspeed:type`, and `source:maxspeed`, including `:forward` / `:backward`
  variants. Bare `urban` and `rural` are also accepted in these fields.
  Symbolic `maxspeed=<ISO2>:urban`/`<ISO2>:rural` carries the same typed context
  and uses `maxspeed_type` provenance; numeric maxspeed values never establish
  settlement state.
- Recognized `<ISO2>:310`/`<ISO2>:311` node signs constrain only an explicitly
  associated way and OSM direction. Generic `traffic_sign=city_limit` supports documented
  `city_limit=begin`, `end`, and default/`both`; direction on a double-sided sign
  identifies entering traffic. Undirected/numeric-bearing signs remain raw
  unresolved observations. Direction is never guessed from driving history.
- Exact source-node membership establishes association. A node shared by two
  ways is usable only when it is an endpoint of both, the OSM directions agree
  through it, and their continuation turns by less than 30 degrees. Branches,
  reversed orientations, and ambiguous nodes remain unresolved. There is no
  road-network flooding.
- Explicit country-prefixed polygon `zone:traffic=<ISO2>:urban`/`<ISO2>:rural` and
  `boundary=urban` provide high-confidence polygon evidence.
  `boundary=administrative` is excluded.
- Residential, commercial, retail, and industrial landuse provide low-confidence
  inside context only when the road lies within the original polygon. Parcel
  gaps and roads beside landuse remain unknown: no uncalibrated buffer is used.
- Any contradictory high-confidence observations yield `inside_city=NULL`,
  `source=conflict`. Consistent high evidence outranks landuse; within consistent
  high evidence, typed road context/signs precede polygon provenance.
- No known evidence produces `NULL` / `missing`; consumers must not turn this
  into a country-wide rural default. Low-confidence landuse may support a badge,
  but must not alone activate legal default speeds.
- Every admitted way gets a context row. Zero-length or missing usable geometry
  produces `NULL` with an explanatory reason and metadata counts; an unavailable
  legacy polyline is represented by an empty point array.

## Generation and checks

The opt-in builder requires pyosmium and Shapely >= 2. Existing generation without
the flag does not require Shapely; the legacy packer keeps exact vertices when it
is unavailable instead of applying a vertex-count polygon cap.

The tested versions are pinned in
`scripts/map/requirements-settlement.txt`. Install them in the Python environment
used for packing, generation, and the settlement regression tests:

```sh
python -m pip install -r scripts/map/requirements-settlement.txt
```

```sh
python scripts/map/build_spatialite_v3.py \
  --v1-dist mapdata/dist/<target> \
  --out-db mapdata/dist-v3/<target>/speeds_v3.sqlite \
  --input-pbf mapdata/raw/<target>.osm.pbf \
  --build-settlement-context --country-code <ISO2>

python -m unittest discover -s tests/map -p test_settlement_context.py -v
```

The reproducible synthetic fixtures in `tests/map/test_settlement_context.py`
cover urban 70, rural 30, numeric-only unknown, conflicting evidence, directional
and generic signs, way splits, ambiguity, multipolygon holes, and a deep narrow
notch that vertex-count sampling previously removed. They also exercise the
complete packer-to-v3 CLI path and capability metadata.

Delta generation must preserve the four additive tables and their metadata as a
unit, and equivalence validation must compare them against a full rebuild.

## Consumers and rollout

The iPhone and Android consumers read `inside_city` as `Bool?` / `Boolean?`.
Only high-confidence evidence can select settlement default speeds, invalidate a
camera limit on town entry, or select a settlement-specific penalty variant.
Low-confidence landuse can support the city indicator; unknown uses the existing
unknown-context presentation. Posted numeric limits remain independent.

The product also supplies a road-class fallback of **50 km/h** for `residential`
and `service` ways when speed derivation falls back to road class and no
high-confidence settlement default is available. Explicit numeric/unlimited
limits and high-confidence inside/outside defaults retain precedence. This
fallback does not revive inherited urban/rural tags rejected by the current
settlement decision. It never changes `inside_city`, its evidence/confidence,
penalty locality, or camera town-entry state. Other road classes retain their
existing policy. This consumer rule needs no bundle or schema change.

Camera entry detection alone retains the last high-confidence confirmation for
at most eight seconds and 160 metres from that confirmation. Brief weak/unknown
gaps cannot manufacture a second entry into the same town; expired, invalid or
backward-time fixes and hard lifecycle/bundle changes clear this memory. Weak
fixes do not refresh its bounds. Displayed context, defaults and penalties still
use the current nullable observation, never the retained camera-only history.

Both clients validate manifest schema, minimum app version, and settlement
capability when installing a bundle. Unsupported capability versions fail closed.
Older clients do not enforce these checks, so rollout must install the updated
clients first and then deliver the first extension-enabled bundle in full.
The outer manifest remains `variant=v3`, `schema_version=1`; the pilot sets
`min_app_version=1.1`, matching the current app marketing version. This version
alone cannot distinguish older builds of 1.1 from the updated implementation.

Subsequent deltas require an actual rebuilt target database. Changes to the
settlement capability, table availability, or schema require a full bundle.
Run delta generation with `--target-db` and `--validate-on-copy`; context-only
changes must be included even when the legacy road rows are identical.

`generate_v3_country_bundles.py --build-settlement-context` accepts every selected
target with a two-letter ISO country code. It writes a versioned directory,
preserving the current `latest` bundle. Capability or schema transitions require
a full bundle publication; later context-only changes must be included in rebuilt
target databases. To inspect generated coverage without legacy polygon sampling:

```sh
python scripts/map/audit_city_context.py --settlement-only \
  mapdata/dist-v3/<target>/speeds_v3.sqlite
```

Coverage and evidence consistency are diagnostics, not measured driving accuracy.
Route validation still needs surveyed town entries/exits in both directions,
including parcel-separated carriageways and roads with incomplete sign direction.
