# youspeed.de
## Summary
Data + Camera driven speed sign recognition with traffic fine calculation

## Project Description
This project shall create an iphone app that is able to recognize traffic signs (speed signs only) based on a suitable available vision neural network that is used to process the camera video feed and recognize speed signs detected on the video stream. The recognized speed limit is displayed to the user using the official traffic sign symbol for the respective speed in Germany,additionally the fine of driving faster than the allowed speed is calculated by official German traffic regulations and displayed to the user. User can pick warning levels (above speed limit or amount of fines) in the settings, and choose from visual and auditory warnings.

The recognized speed limits should be saved to a database, locally for the user and later in a global (online) database. The local database is augmented with the traffic sign information that is available in OpenStreetMap (see https://wiki.openstreetmap.org/wiki/Key:maxspeed ) hence a batch job is necessary to bootstrap this second database from a country PBF,we start with Germany.

While driving and using the app, the user geolocation is mapped to the appropriate ways from Openstreetmap to identify the existing speed limits. In addition general speed limits while driving on a certain type of way (e.g. Landstrasse maximum 100) should be considered based on German traffic rules. Also when driving within city limits the usual speed limit of 50 should be the default, so app needs to identify whether geolocation of user is within a certain city boundary. 

To test the app we want to start with a small region in particular https://download.geofabrik.de/europe/germany/baden-wuerttemberg/karlsruhe-regbez-latest.osm.pbf

User should be able to confirm a newly detected limit in a easy way while driving, e.g. through a speech command and voice interaction with the app.

Come up with a research on German traffic rules and an implementation plan before actually generating code

## Implementation Bootstrap (Osmium-First)

The first implementation step in this repo is an offline OSM preprocessing pipeline without PostgreSQL/PostGIS.

### Prerequisites
- `pyosmium` (Python `osmium` package)
- `python3`
- `osmium-tool` (only for optional `--engine osmium-cli` fallback)
- `jq`
- standard Unix tools: `awk`, `sort`, `wc`

### Run
1. Put the Karlsruhe PBF into:
   - `mapdata/raw/karlsruhe-regbez-latest.osm.pbf`
2. Build artifacts:
   - `./scripts/map/build_region_artifacts.sh --region karlsruhe-regbez --input mapdata/raw/karlsruhe-regbez-latest.osm.pbf`

Engine options:
- default: `pyosmium` (direct Python/Osmium processing)
- fallback: `osmium-cli`
  - `./scripts/map/build_region_artifacts.sh --region karlsruhe-regbez --input mapdata/raw/karlsruhe-regbez-latest.osm.pbf --engine osmium-cli`
- for large regions, reduce geometry footprint:
  - `./scripts/map/build_region_artifacts.sh --region germany --input mapdata/raw/germany-latest.osm.pbf --max-geom-points 8`

### Output
The pipeline writes versioned artifacts to:
- `mapdata/build/karlsruhe-regbez/` (intermediate filtered PBF layers)
- `mapdata/dist/karlsruhe-regbez/` (runtime artifacts)
  - `ways.meta` (one JSON object per way with speed tags + bbox)
  - `ways.lookup` (way_id -> byte-offset lookup for fast candidate fetch)
  - `ways.geom` (downsampled per-way polyline points for segment-distance scoring)
  - `ways.geom.lookup` (way_id -> byte-offset lookup for `ways.geom`)
  - `ways.idx` (grid-cell index for way candidate lookup)
  - `areas.idx` (grid-cell index + area metadata for built-up context lookup)
  - `manifest.json`

### Verify Artifacts
- Validate schema + manifest hashes:
  - `./scripts/map/check_artifacts.sh mapdata/dist/karlsruhe-regbez`
- Verify deterministic builds (same input -> same artifact signatures):
  - `./scripts/map/check_determinism.sh --region karlsruhe-regbez --input mapdata/raw/karlsruhe-regbez-latest.osm.pbf --runs 2`

### Query Candidates
Use the artifact matcher to query speed-limit candidates for a GPS point:

- `./scripts/map/query_speed_limit.py --dist-dir mapdata/dist/karlsruhe-regbez --lat 49.009 --lon 8.404 --heading 90 --top-k 5`
- Polyline backup scoring:
  - `./scripts/map/query_speed_limit.py --dist-dir mapdata/dist/karlsruhe-regbez --lat 49.009 --lon 8.404 --heading 90 --distance-mode polyline`
- Hybrid scoring (bbox prefilter + polyline refinement of top candidates):
  - `./scripts/map/query_speed_limit.py --dist-dir mapdata/dist/karlsruhe-regbez --lat 49.009 --lon 8.404 --heading 90 --distance-mode hybrid --polyline-top-n 250`
- Mode benchmark helper:
  - `./scripts/map/benchmark_lookup_speed.sh mapdata/dist/karlsruhe-regbez 49.009 8.404 90 10 5 250`

Output includes:
- candidate ways from `ways.idx`
- scored top matches (distance + optional heading penalty)
- inferred effective limit (`map_explicit` or fallback `default_rule`)
- query timing (`timing_ms` in JSON + `query_time_ms=...` log line on stderr)

Dataset policy:
- `ways.meta` includes only car-drivable `highway=*` types.
- Pedestrian/cycle/foot paths and non-drivable shapes are excluded from the runtime way dataset.

### Test Suite
Run:
- `python3 -m unittest discover -s tests -p 'test_*.py' -v`

Coverage includes:
- positive and negative checks for artifact validity
- deterministic and hash-integrity checks
- inside-city vs outside-city default speed behavior (`50` vs `100`)
- explicit limit parsing (`maxspeed`, `zone:maxspeed`, `maxspeed:type`, `source:maxspeed`, unit suffixes)
- filtering of non-car ways (pedestrian/cycle/path/building excluded)
- query timing output (`query_time_ms` log + `timing_ms` payload)

### Tile/Segment v2 Spec (Independent Data Delivery)
- design doc: `docs/TILE_SEGMENT_ASSET_SPEC.md`
- migration plan: `docs/TILE_ASSET_MIGRATION_PLAN.md`
- machine-readable contracts: `mapdata/spec/catalog.v2.schema.json`, `mapdata/spec/tile_manifest.v2.schema.json`
- concrete examples: `mapdata/spec/examples/catalog.v2.example.json`, `mapdata/spec/examples/tile_manifest.v2.example.json`

Validate v2 examples:
- `python3 scripts/map/check_tile_assets_v2.py --catalog mapdata/spec/examples/catalog.v2.example.json --tile-manifest mapdata/spec/examples/tile_manifest.v2.example.json`

Build Germany v2 tiles from existing v1 artifacts:
- `python3 scripts/map/build_tile_assets_v2.py --v1-dist mapdata/dist/germany --out-dir mapdata/dist-v2/germany --region germany --tile-size-m 4096 --subgrid 32 --content-version 1 --max-area-tiles 1024`

Query v2:
- `python3 scripts/map/query_speed_limit_v2.py --dist-dir mapdata/dist-v2/germany --lat 52.5200 --lon 13.4050 --heading 90 --distance-mode hybrid --polyline-top-n 250 --top-k 5`

Benchmark v2:
- `./scripts/map/benchmark_lookup_speed_v2.sh mapdata/dist-v2/germany 52.5200 13.4050 90 10 5 250 1`

One-shot build + benchmark report:
- `python3 scripts/map/build_and_benchmark_v2.py --region germany --input-pbf mapdata/raw/germany-latest.osm.pbf --lat 52.5200 --lon 13.4050 --heading 90 --repeats 10`
- report output default: `mapdata/dist-v4/germany/benchmark_report.json`

Build v3 (single Spatialite/SQLite DB):
- `python3 scripts/map/build_spatialite_v3.py --v1-dist mapdata/dist/germany --out-db mapdata/dist-v3/germany/speeds_v3.sqlite`

Query v3:
- `python3 scripts/map/query_speed_limit_v3.py --db mapdata/dist-v3/germany/speeds_v3.sqlite --lat 52.5200 --lon 13.4050 --heading 90 --distance-mode hybrid --polyline-top-n 250`

Build v4 (Spatialite/SQLite DB + tile prefilter table):
- `python3 scripts/map/build_spatialite_v4.py --v1-dist mapdata/dist/germany --out-db mapdata/dist-v4/germany/speeds_v4.sqlite --tile-size-m 4096 --max-way-tiles 1024`

Query v4:
- `python3 scripts/map/query_speed_limit_v4.py --db mapdata/dist-v4/germany/speeds_v4.sqlite --lat 52.5200 --lon 13.4050 --heading 90 --tile-radius 1 --distance-mode hybrid --polyline-top-n 250`

Weekly refresh benchmark (scheduled protocol example for 2026-03-02):
- `./scripts/map/refresh_and_benchmark_weekly.sh 2026-03-02`
- plan doc: `docs/WEEKLY_REFRESH_BENCHMARK_2026-03-02.md`

Daily incremental PBF update via Geofabrik diffs (no full re-download):
- `./scripts/map/update_from_geofabrik_diffs.sh --region germany --input-pbf mapdata/raw/germany-latest.osm.pbf`
- outputs:
  - run report: `mapdata/reports/diff_update.germany.<timestamp>.json`
  - persistent state: `mapdata/raw/germany.diff_state.json`
  - optional merged delta export (`.osc.gz`) in `mapdata/build/germany/updates/`

Automated daily diff processing (GitHub Actions):
- workflow: `.github/workflows/daily_geofabrik_diff_update.yml`
- pipeline entrypoint: `python3 scripts/map/run_daily_diff_pipeline.py`
- per-day CSV upsert: `python3 scripts/map/upsert_daily_diff_analysis_row.py`
- tracked analysis CSV: `mapdata/reports/deltas/daily-diff-analysis.csv`

v3 consumer data-bundle publishing (GitHub releases):
- build one incremental patch: `python3 scripts/map/build_v3_delta_pack.py --base-db mapdata/dist-v3/germany/speeds_v3.sqlite --diff-file mapdata/reports/deltas/daily/germany-YYYY-MM-DD.osc.gz --region germany --from-version 2026-02-23 --to-version 2026-02-24 --out-dir mapdata/bundles/v3/germany/2026-02-24/deltas/2026-02-23_to_2026-02-24 --patch-file-name v3_patch_2026-02-23_to_2026-02-24.sql --manifest-name v3_delta_manifest_2026-02-23_to_2026-02-24.json --github-owner volzinnovation --github-repo youspeed.de --github-release-tag v3-data-2026-02-24`
- build delta index: `python3 scripts/map/build_v3_delta_index.py --delta-manifest-dir mapdata/bundles/v3/germany/2026-02-24/deltas --output mapdata/bundles/v3/germany/2026-02-24/delta-index.v3.json`
- publish full bundle manifest into `latest/`: `python3 scripts/map/publish_v3_bundle.py --region germany --db mapdata/dist-v3/germany/speeds_v3.sqlite --bundle-version 2026-02-24 --bundle-dir-name latest --out-root mapdata/bundles/v3 --delta-index mapdata/bundles/v3/germany/latest/delta-index.v3.json --github-owner volzinnovation --github-repo youspeed.de --github-release-tag v3-data-latest`
- roll latest-30 incremental index: `python3 scripts/map/roll_v3_delta_index.py --existing-index mapdata/bundles/v3/germany/latest/delta-index.v3.json --new-delta-manifest mapdata/bundles/v3/germany/latest/deltas/2026-02-23_to_2026-02-24/v3_delta_manifest_2026-02-23_to_2026-02-24.json --new-delta-manifest-asset-path v3_delta_manifest_2026-02-23_to_2026-02-24.json --release-asset-base-url https://github.com/volzinnovation/youspeed.de/releases/download/v3-data-latest --retention-count 30 --output mapdata/bundles/v3/germany/latest/delta-index.v3.json`
- upload bundle artifacts to release: `./scripts/map/publish_v3_release_assets.sh --repo volzinnovation/youspeed.de --tag v3-data-latest --bundle-dir mapdata/bundles/v3/germany/latest`
- manual workflow: `.github/workflows/publish_v3_bundle_release.yml`
- automated daily full+incremental workflow: `.github/workflows/v3_generate_and_release_latest.yml`
- release asset naming on GitHub is flat (e.g. `bundle-manifest.v3.json`, `speeds_v3.sqlite`, `v3_delta_manifest_<from>_to_<to>.json`, `v3_patch_<from>_to_<to>.sql`)

iPhone benchmark sketch:
- app scaffold: `iphone/SpeedDBBenchSketch/`
- generated project: `iphone/SpeedDBBench.xcodeproj`
- regenerate project from spec: `./scripts/iphone/generate_xcode_project.sh`
- automation guide: `docs/IPHONE_BENCHMARK_AUTOMATION.md`
- run UI benchmark on attached device:
  - `./scripts/iphone/run_device_benchmark.sh /Users/raphaelvolz/Github/youspeed.de/iphone/SpeedDBBench.xcodeproj SpeedDBBench <DeviceUDID>`
  - if device signing/provisioning is unavailable, the script auto-falls back to simulator benchmark execution.

iPhone consumer app (v3-only):
- app scaffold: `iphone/SpeedConsumerApp/`
- generated project target: `SpeedConsumer` in `iphone/SpeedDBBench.xcodeproj`
- behavior:
  - bootstrap seed `speeds_v3.sqlite`
  - sync full/delta bundles from GitHub release asset `bundle-manifest.v3.json`
  - atomically activate updated DB before driving mode
  - if installed bundle is older than 30 days relative to target bundle version, skip deltas and force full-bundle reload
  - show current speed vs matched v3 speed-limit candidate
