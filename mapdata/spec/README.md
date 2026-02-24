# mapdata/spec

Machine-readable contracts for map runtime assets.

Files:
- `catalog.v2.schema.json`: top-level per-region catalog contract.
- `tile_manifest.v2.schema.json`: per-tile metadata contract.
- `v3_bundle_manifest.schema.json`: v3 consumer full-bundle contract.
  - supports optional `db_parts` array for multi-part DB delivery when single-file assets exceed host limits.
- `v3_delta_manifest.schema.json`: v3 incremental patch contract.
- `examples/catalog.v2.example.json`: concrete catalog example.
- `examples/tile_manifest.v2.example.json`: concrete tile-manifest example.

Validator:
- `python3 ../../scripts/map/check_tile_assets_v2.py --catalog examples/catalog.v2.example.json --tile-manifest examples/tile_manifest.v2.example.json`

Notes:
- The validator enforces semantic rules beyond basic schema shape:
  - tile ID format and SHA-256 format
  - chunk ordering and non-overlap
  - required chunk presence (`segment_index`, `segment_geom`, `speed_rules`, `area_index`)
  - runtime compatibility and channel constraints
