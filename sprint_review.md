# Sprint Review

Date: 2026-02-23

## Scope completed
- Implemented and benchmarked four runtime approaches for OSM speed-limit lookup:
  - `v1`: global JSON artifacts
  - `v2`: physical tile packs
  - `v3`: single SQLite/Spatialite-style runtime DB (RTree)
  - `v4`: SQLite RTree + tile prefilter table
- Extended query modes across all variants:
  - `bbox`
  - `hybrid` (bbox prefilter + polyline refinement)
  - `polyline` (segment-distance scoring)
- Added stronger tests:
  - negative tests
  - inside-city vs outside-city behavior
  - non-car-way filtering
  - multiple road/type conditions
- Implemented iPhone benchmark harness and executed physical-device runs with country-scale Germany artifacts.
- Added Geofabrik diff update runner:
  - `scripts/map/update_from_geofabrik_diffs.sh`
  - JSON state/report output for automation
- Added change tracking CSV generation for daily deltas.

## Key results

### Runtime performance (country-scale)
- `v3` is currently the best default runtime for on-device usage overall (best hybrid/polyline profile and smaller monolithic DB than `v4`).
- `v4` currently shows a bbox regression on the latest iPhone country-scale run and needs further profiling.

### Device benchmark matrix (latest run)
- Country DB size: `3,001,716,736` bytes
- Averages (ms):
  - `bbox`: `v1=3970.84`, `v2=194.49`, `v3=37.12`, `v4=757.01`
  - `hybrid`: `v1=2535.44`, `v2=45.76`, `v3=23.39`, `v4=95.96`
  - `polyline`: `v1=2639.76`, `v2=62.88`, `v3=44.93`, `v4=86.48`

### Daily change tracking status
- Confirmed dataset advanced from seq `4701` to `4702`.
- Stored old/new Germany snapshots and recorded way/maxspeed deltas.
- Latest change row written to:
  - `mapdata/reports/change_tracking.csv`
- Current delta counts (4701 -> 4702):
  - `way_create=10189`, `way_modify=22737`, `way_delete=1111`, `way_total=34037`
  - `maxspeed_way_create=280`, `maxspeed_way_modify=400`, `maxspeed_way_delete=31`, `maxspeed_way_total=711`

## Product/architecture decision
- Select `v3` (single SQLite DB with RTree) as the primary app runtime target for now.
- Keep `v2` tile concepts as an optional distribution/update channel when partial updates become a hard requirement.

## Next steps (next sprint)

### 1) Implement S3 (`v3`) in the production iPhone app
- Integrate `v3` query path into the actual app runtime (not benchmark-only harness).
- Add app-side repository/service layer for:
  - nearest-way candidate retrieval
  - hybrid/polyline scoring
  - confidence + source attribution (`camera`, `map`, `default`)
- Add telemetry hooks:
  - query latency percentiles
  - candidate-set sizes
  - cache hit/miss and fallback reason codes

### 2) Daily file update downloads (aligned with upcoming requirements)
- Implement update manager for independent data shipping from app binary:
  - check remote manifest/state
  - compare installed data version and compatibility
  - download verified update payload
  - atomic swap + rollback on failure
- Phase 1 baseline:
  - full-file `v3` snapshot replacement with checksum/signature verification
  - background-safe apply at app idle/startup
- Phase 2 (if product requires lower bandwidth/latency):
  - selective delta/tile channel (v2-style or DB page-level delta strategy)
  - policy by network type, battery, and user settings

### 3) Close known gaps
- Profile and optimize `v4` bbox regression on device.
- Stabilize DNS/network handling in automated diff fetch jobs (retry/backoff and fallback path).
- Add scheduled weekly refresh benchmark and trend dashboard from `change_tracking.csv` + benchmark JSON reports.

## Risks and dependencies
- Large monolithic DB updates (`v3`) can be expensive on mobile bandwidth/storage.
- Incremental update strategy needs clear product requirements:
  - update cadence
  - data freshness SLA
  - max acceptable download size/time
  - offline behavior and rollback guarantees
- iOS background download/apply behavior must be validated on real devices under power/network constraints.
