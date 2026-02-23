# Migration Plan: Current Artifacts -> Tile/Segment v2

Date: 2026-02-23
Status: Execution plan

Reference contracts:
- `mapdata/spec/catalog.v2.schema.json`
- `mapdata/spec/tile_manifest.v2.schema.json`
- validation CLI: `scripts/map/check_tile_assets_v2.py`

## Objective

Migrate from current region-wide artifacts (`ways.meta`, `ways.idx`, `ways.lookup`, `ways.geom`, `areas.idx`) to tile/segment assets (`catalog.v2`, `tile_manifest.v2`, `tilepack`) with independent update delivery.

## Phase 0: Contract Freeze

- Finalize `v2` metadata contracts and binary chunk names.
- Add validators for catalog/tile-manifest correctness.
- Define runtime compatibility integer (`data_runtime_version`).

Exit criteria:
- Spec approved and validation tooling green in CI.

## Phase 1: Build Pipeline Extension (Offline)

- Add tile slicing stage from PBF output into `x/y` buckets.
- Convert ways to segments and generate segment graph adjacency.
- Emit per-tile `tile_manifest.v2.json` and `tilepack`.
- Emit `catalog.v2.json` for channel publication.

Exit criteria:
- Deterministic tile outputs for fixed input and build version.

## Phase 2: Runtime Loader (iOS)

- Implement tile resolver (`lat/lon -> tile_id`).
- Implement tile window cache + prefetch (3x3, heading-aware extension).
- Implement tilepack reader for chunk access.
- Keep current v1 artifact reader as fallback behind feature flag.

Exit criteria:
- Drive replay tests produce equivalent or better effective-limit decisions.

## Phase 3: Incremental Matcher

- Add stateful tracking of prior segment and adjacency continuation.
- Use local candidate search first; broad fallback only on uncertainty.
- Support distance modes (`bbox`, `hybrid`, `polyline`) on segment geometry.

Exit criteria:
- Measurable query-latency reduction >= 10x vs current Germany-wide lookup path.

## Phase 4: Independent Update Delivery

- Publish signed `catalog.v2.json` + tile manifests on CDN.
- Implement client updater (download changed tiles only, atomic replace).
- Add rollback and stale-cache safety behavior.

Exit criteria:
- Map updates can ship without app release, with verified integrity and rollback path.

## Phase 5: Controlled Rollout

- Canary channel for internal users.
- Telemetry: query time p50/p95, tile cache hit rate, fallback rate.
- Promote to stable after metrics pass thresholds.

Exit criteria:
- Stable rollout complete and old v1 path disabled by default.

## Data Mapping (v1 -> v2)

- `ways.meta` -> `segment_geom` + `speed_rules` chunks
- `ways.idx` -> `segment_index` chunk
- `ways.lookup` -> removed (superseded by chunk-local index structures)
- `ways.geom`/`ways.geom.lookup` -> `segment_geom` chunk payload
- `areas.idx` -> `area_index` chunk
- `manifest.json` -> split into `catalog.v2` + per-tile `tile_manifest.v2`

## Operational Notes

- Keep v1 generation scripts available until v2 is production proven.
- During migration, publish both v1 and v2 outputs from the same build to compare behavior.
- Pin app-side runtime parser by `data_runtime_version` and reject incompatible catalogs.
