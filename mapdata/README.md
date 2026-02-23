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

v4 generated runtime artifact:
- `dist-v4/<region>/speeds_v4.sqlite`
