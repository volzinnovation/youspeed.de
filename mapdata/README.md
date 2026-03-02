# mapdata

Directory layout for offline OpenStreetMap preprocessing artifacts.

- `raw/`: source `.osm.pbf` files (immutable inputs)
- `build/`: intermediate outputs created by extraction steps
- `dist/`: runtime artifact packs consumed by the app

Current pipeline entrypoint:
- `../scripts/map/build_region_artifacts.sh`
- Python/Osmium packer:
  - `../scripts/map/pack_runtime_artifacts_pyosmium.py`

Validation scripts:
- `../scripts/map/check_artifacts.sh <dist_region_dir>`
- `../scripts/map/check_determinism.sh --region <name> --input <raw_pbf>`
- `../scripts/map/query_speed_limit.py --dist-dir <dist_region_dir> --lat <lat> --lon <lon> [--heading <deg>]`
- `../scripts/map/check_tile_assets_v2.py --catalog spec/examples/catalog.v2.example.json --tile-manifest spec/examples/tile_manifest.v2.example.json`
- `../scripts/map/migrate_v2_tile_layout_xy.py --dist-dir dist-v2/germany`
- `../scripts/map/query_speed_limit_v2.py --dist-dir dist-v2/germany --lat 52.5200 --lon 13.4050 --heading 90`
- `../scripts/map/benchmark_lookup_speed_v2.sh dist-v2/germany 52.5200 13.4050 90 10 5 250 1`
- `../scripts/map/build_spatialite_v3.py --v1-dist dist/germany --out-db dist-v3/germany/speeds_v3.sqlite`
- `../scripts/map/query_speed_limit_v3.py --db dist-v3/germany/speeds_v3.sqlite --lat 52.5200 --lon 13.4050 --heading 90`
- `../scripts/map/plan_country_region_bundles.py --country-id germany --country-pbf mapdata/raw/DEU-latest.osm.pbf --geofabrik-index mapdata/build/geofabrik/index-v1.json --max-country-pbf-bytes 1000000000 --out-json mapdata/reports/germany_bundle_plan.v3.json`
- `../scripts/map/build_v3_delta_pack.py --base-db dist-v3/germany/speeds_v3.sqlite --diff-file reports/deltas/daily/DEU-YYYY-MM-DD.osc.gz --from-version 2026-02-23 --to-version 2026-02-24 --out-dir bundles/v3/germany/2026-02-24/deltas/2026-02-23_to_2026-02-24 --patch-file-name v3_patch_2026-02-23_to_2026-02-24.sql --manifest-name v3_delta_manifest_2026-02-23_to_2026-02-24.json`
- `../scripts/map/build_v3_delta_index.py --delta-manifest-dir bundles/v3/germany/2026-02-24/deltas --output bundles/v3/germany/2026-02-24/delta-index.v3.json`
- `../scripts/map/roll_v3_delta_index.py --existing-index bundles/v3/germany/latest/delta-index.v3.json --new-delta-manifest bundles/v3/germany/latest/deltas/2026-02-23_to_2026-02-24/v3_delta_manifest_2026-02-23_to_2026-02-24.json --new-delta-manifest-asset-path v3_delta_manifest_2026-02-23_to_2026-02-24.json --release-asset-base-url https://github.com/volzinnovation/youspeed.de/releases/download/deu-v3-data-latest --retention-count 30 --output bundles/v3/germany/latest/delta-index.v3.json`
- `../scripts/map/publish_v3_bundle.py --region germany --db dist-v3/germany/speeds_v3.sqlite --bundle-version 2026-02-24 --bundle-dir-name latest --out-root bundles/v3 --delta-index bundles/v3/germany/latest/delta-index.v3.json --github-owner volzinnovation --github-repo youspeed.de --github-release-tag deu-v3-data-latest`
- `../scripts/map/publish_v3_bundle.py --region germany-baden-wuerttemberg --db dist-v3/germany-baden-wuerttemberg/speeds_v3.sqlite --bundle-version 2026-03-02 --bundle-dir-name latest --out-root bundles/v3 --coverage-poly mapdata/raw/germany/baden-wuerttemberg.poly`
- `../scripts/map/build_v3_country_bundle_catalog.py --country DEU --bundle-version 2026-03-02 --manifest mapdata/bundles/v3/germany-baden-wuerttemberg/latest/DEU-latest.bundle-manifest.v3.json --manifest mapdata/bundles/v3/germany-bayern/latest/DEU-latest.bundle-manifest.v3.json --out-json mapdata/bundles/v3/germany/latest/DEU-latest.bundle-catalog.v3.json`
- `../scripts/map/generate_v3_country_bundles.py --bundle-region germany/baden-wuerttemberg --iso2 DE --execute`
- `../scripts/map/generate_v3_country_bundles.py --top-n 10 --execute`
- `../scripts/map/publish_v3_release_assets.sh --repo volzinnovation/youspeed.de --tag deu-v3-data-latest --bundle-dir bundles/v3/germany/latest`
- `../scripts/map/prune_v3_release_assets.py --repo volzinnovation/youspeed.de --release-tag deu-v3-data-latest --delta-index bundles/v3/germany/latest/delta-index.v3.json`
- `../scripts/map/build_spatialite_v4.py --v1-dist dist/germany --out-db dist-v4/germany/speeds_v4.sqlite --tile-size-m 4096`
- `../scripts/map/query_speed_limit_v4.py --db dist-v4/germany/speeds_v4.sqlite --lat 52.5200 --lon 13.4050 --heading 90 --tile-radius 1`
- `../scripts/map/build_and_benchmark_v2.py --region germany --input-pbf raw/germany-latest.osm.pbf --lat 52.5200 --lon 13.4050 --heading 90 --repeats 10`

Runtime artifact semantics:
- `dist/<region>/ways.meta`: JSONL with speed-relevant attributes and bboxes per way (car-drivable highways only).
- `dist/<region>/ways.lookup`: JSON lookup map of `way_id -> byte_offset` into `ways.meta`.
- `dist/<region>/ways.geom`: JSONL with sampled polyline points per way (`[lat, lon]` points).
- `dist/<region>/ways.geom.lookup`: JSON lookup map of `way_id -> byte_offset` into `ways.geom`.
- `dist/<region>/ways.idx`: JSON with coarse grid cells mapped to candidate way IDs.
- `dist/<region>/areas.idx`: JSON with coarse grid cells mapped to area IDs plus area metadata.
- `dist/<region>/manifest.json`: hashes, sizes, source provenance, generator metadata.

v2 tile/segment contract artifacts:
- `spec/catalog.v2.schema.json`
- `spec/tile_manifest.v2.schema.json`
- `spec/examples/*.json`

v2 generated runtime artifacts:
- `dist-v2/<region>/catalog.v2.json`
- `dist-v2/<region>/tiles/<x>/<y>/tile_manifest.v2.json`
- `dist-v2/<region>/tiles/<x>/<y>/<content_sha256>.tilepack`

v3 generated runtime artifact:
- `dist-v3/<region>/speeds_v3.sqlite`

v3 consumer bundle artifacts:
- `bundles/v3/<region>/latest/bundle-manifest.v3.json`
- `bundles/v3/<region>/latest/speeds_v3.sqlite` (single-file mode)
- `bundles/v3/<region>/latest/speeds_v3.sqlite.partNNN` (auto-split mode for release size limits)
- `bundles/v3/<region>/latest/delta-index.v3.json` (rolling window of latest 30 updates)
- `bundles/v3/<region>/latest/deltas/**/v3_delta_manifest_<from>_to_<to>.json` + `v3_patch_<from>_to_<to>.sql` (optional)
- `bundles/v3/<region>/latest/*.poly` (optional region coverage polygon used for on-device bundle routing)
- `bundles/v3/<country>/latest/*bundle-catalog.v3.json` (optional country-level catalog that references multiple regional manifests)

Automation:
- Daily PBF update + release snapshot: `../.github/workflows/daily_geofabrik_diff_update.yml`
- V3 bundle build/release from published PBF snapshot: `../.github/workflows/germany_generate_and_release_latest.yml`
- GitHub release assets are uploaded with flat names; manifests carry explicit URLs for full bundle and delta files.

v4 generated runtime artifact:
- `dist-v4/<region>/speeds_v4.sqlite`
