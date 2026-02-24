# youspeed.de

This repository has two separate workstreams:

- `Track A`: scientific probing and reproducible benchmarking for the paper (v1/v2/v3/v4 comparison, v3 selection).
- `Track B`: production consumer iPhone app development (v3 only) with independent data-bundle delivery.

Do not mix these concerns when adding code, tests, or workflows.

## Shared prerequisites

- `python3`
- Python package `osmium` (`pyosmium`)
- `sqlite3`
- `jq`
- Xcode + iOS toolchain (for iPhone apps)
- optional: `osmium-tool` (alternative engine)

## Track A: Scientific Probing and Paper Reproducibility

Goal: reproduce architecture evaluation, benchmark matrix, and paper outputs that justified choosing `v3`.

### Scope

- Runtime variants under test:
  - `v1`: JSONL + grid index artifacts (`mapdata/dist/...`)
  - `v2`: tile/segment assets (`mapdata/dist-v2/...`)
  - `v3`: single SQLite runtime DB (`mapdata/dist-v3/...`)
  - `v4`: SQLite + tile prefilter (`mapdata/dist-v4/...`)
- Dedicated benchmark app (kept stable for reproducibility):
  - `/Users/raphaelvolz/Github/youspeed.de/iphone/SpeedDBBenchSketch`
  - scheme in project: `SpeedDBBench`

### Repro pipeline (country scale)

1. Prepare Germany source PBF:

```bash
mkdir -p mapdata/raw
curl -L --fail https://download.geofabrik.de/europe/germany-latest.osm.pbf -o mapdata/raw/DEU-latest.osm.pbf
```

2. Build `v1` base artifacts:

```bash
./scripts/map/build_region_artifacts.sh --region germany --input mapdata/raw/DEU-latest.osm.pbf --engine pyosmium --max-geom-points 8
```

3. Build `v2`, `v3`, `v4`:

```bash
python3 scripts/map/build_tile_assets_v2.py --v1-dist mapdata/dist/germany --out-dir mapdata/dist-v2/germany --region germany --tile-size-m 4096 --subgrid 32 --content-version 1 --max-area-tiles 1024
python3 scripts/map/build_spatialite_v3.py --v1-dist mapdata/dist/germany --out-db mapdata/dist-v3/germany/speeds_v3.sqlite
python3 scripts/map/build_spatialite_v4.py --v1-dist mapdata/dist/germany --out-db mapdata/dist-v4/germany/speeds_v4.sqlite --tile-size-m 4096 --max-way-tiles 1024
```

4. Run query benchmarks:

```bash
./scripts/map/benchmark_lookup_speed.sh mapdata/dist/germany 52.5200 13.4050 90 10 5 250
./scripts/map/benchmark_lookup_speed_v2.sh mapdata/dist-v2/germany 52.5200 13.4050 90 10 5 250 1
python3 scripts/map/query_speed_limit_v3.py --db mapdata/dist-v3/germany/speeds_v3.sqlite --lat 52.5200 --lon 13.4050 --heading 90 --distance-mode hybrid --polyline-top-n 250
python3 scripts/map/query_speed_limit_v4.py --db mapdata/dist-v4/germany/speeds_v4.sqlite --lat 52.5200 --lon 13.4050 --heading 90 --tile-radius 1 --distance-mode hybrid --polyline-top-n 250
```

5. Run scientific test suite:

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

6. Run on-device benchmark harness (paper replication app):

```bash
./scripts/iphone/run_device_benchmark.sh /Users/raphaelvolz/Github/youspeed.de/iphone/SpeedDBBench.xcodeproj SpeedDBBench <DeviceUDID>
```

### Paper sources

- ITSC paper: `/Users/raphaelvolz/Github/youspeed.de/paper/itsc2026`
- Tech report (arXiv-style): `/Users/raphaelvolz/Github/youspeed.de/paper/techreport`
- Shared bibliography/assets: `/Users/raphaelvolz/Github/youspeed.de/paper/share`

Build:

```bash
cd paper/itsc2026 && latexmk -pdf main.tex
cd ../techreport && latexmk -pdf main.tex
```

## Track B: Consumer iPhone App (v3 only)

Goal: ship the real app with a stable `v3` runtime format and independently updatable map bundles.

### Scope

- Production app:
  - `/Users/raphaelvolz/Github/youspeed.de/iphone/SpeedConsumerApp`
  - scheme in project: `SpeedConsumer`
- Runtime format:
  - `v3` only (`speeds_v3.sqlite`)
- Delivery model:
  - full bundle + incremental SQL patches from GitHub releases

### Consumer data model

Latest bundle assets (release tag `deu-v3-data-latest`):

- `DEU-latest.bundle-manifest.v3.json`
- `DEU-latest.speeds_v3.sqlite` (if under GitHub per-asset limit)
- `DEU-latest.speeds_v3.sqlite.partNNN` (if DB exceeds GitHub 2 GB per-asset limit; app reassembles parts)
- `DEU-latest.delta-index.v3.json`
- `DEU-YYYY-MM-DD.v3_delta_manifest_from_YYYY-MM-DD.json` (0..30 recent updates)
- `DEU-YYYY-MM-DD.v3_patch_from_YYYY-MM-DD.sql` (matching delta manifests)

Important policy enforced in app:

- If installed data is older than 30 days relative to target bundle version, skip incremental patching and do full bundle reload.

Open TODO (IRL validation):

- Run real-world on-road validation for geometry sampling setting `--max-geom-points 8` and compare match quality/latency against higher values (for example `12`, `16`, `24`) before locking production defaults.

### Local v3 bundle build/publish commands

```bash
FROM_VERSION=YYYY-MM-DD
TO_VERSION=YYYY-MM-DD

python3 scripts/map/build_spatialite_v3.py --v1-dist mapdata/dist/germany --out-db mapdata/dist-v3/germany/speeds_v3.sqlite
python3 scripts/map/build_v3_delta_pack.py --base-db mapdata/dist-v3/germany/speeds_v3.sqlite --diff-file mapdata/reports/deltas/daily/DEU-${TO_VERSION}.osc.gz --region germany --from-version "${FROM_VERSION}" --to-version "${TO_VERSION}" --out-dir mapdata/bundles/v3/germany/latest/deltas/${FROM_VERSION}_to_${TO_VERSION} --patch-file-name DEU-${TO_VERSION}.v3_patch_from_${FROM_VERSION}.sql --manifest-name DEU-${TO_VERSION}.v3_delta_manifest_from_${FROM_VERSION}.json --github-owner volzinnovation --github-repo youspeed.de --github-release-tag deu-v3-data-latest
python3 scripts/map/roll_v3_delta_index.py --existing-index mapdata/bundles/v3/germany/latest/DEU-latest.delta-index.v3.json --new-delta-manifest mapdata/bundles/v3/germany/latest/deltas/${FROM_VERSION}_to_${TO_VERSION}/DEU-${TO_VERSION}.v3_delta_manifest_from_${FROM_VERSION}.json --new-delta-manifest-asset-path DEU-${TO_VERSION}.v3_delta_manifest_from_${FROM_VERSION}.json --release-asset-base-url https://github.com/volzinnovation/youspeed.de/releases/download/deu-v3-data-latest --retention-count 30 --output mapdata/bundles/v3/germany/latest/DEU-latest.delta-index.v3.json
python3 scripts/map/publish_v3_bundle.py --region germany --db mapdata/dist-v3/germany/speeds_v3.sqlite --bundle-version "${TO_VERSION}" --bundle-dir-name latest --out-root mapdata/bundles/v3 --db-file-name DEU-latest.speeds_v3.sqlite --manifest-name DEU-latest.bundle-manifest.v3.json --delta-index mapdata/bundles/v3/germany/latest/DEU-latest.delta-index.v3.json --delta-index-file-name DEU-latest.delta-index.v3.json --github-owner volzinnovation --github-repo youspeed.de --github-release-tag deu-v3-data-latest
./scripts/map/publish_v3_release_assets.sh --repo volzinnovation/youspeed.de --tag deu-v3-data-latest --bundle-dir mapdata/bundles/v3/germany/latest
```

### Consumer app build command

Build the `SpeedConsumer` app (with optional private-release token injection):

```bash
./scripts/iphone/build_consumer_app.sh
```

Use local GitHub auth token automatically:

```bash
./scripts/iphone/build_consumer_app.sh --use-gh-token
```

Or pass the token explicitly:

```bash
YOUSPEED_RELEASE_READ_TOKEN='<token>' ./scripts/iphone/build_consumer_app.sh
```

For device builds that need signing/profile updates:

```bash
./scripts/iphone/build_consumer_app.sh --destination 'generic/platform=iOS' --allow-provisioning-updates
```

Token-enforced on-device test run (fails fast if token is missing or not embedded):

```bash
YOUSPEED_RELEASE_READ_TOKEN="$(gh auth token --hostname github.com)" \
  ./scripts/iphone/run_consumer_device_tests.sh --allow-provisioning-updates
```

### Automated GitHub workflows (consumer pipeline)

- Daily generate + publish latest full bundle and incrementals:
  - `/Users/raphaelvolz/Github/youspeed.de/.github/workflows/v3_generate_and_release_latest.yml`
- Manual publish helper:
  - `/Users/raphaelvolz/Github/youspeed.de/.github/workflows/publish_v3_bundle_release.yml`
- Geofabrik diff ingestion and delta analysis:
  - `/Users/raphaelvolz/Github/youspeed.de/.github/workflows/daily_geofabrik_diff_update.yml`
- Workflow dependency:
  - `Germany PBF Diff Update And Release` publishes `deu-pbf-latest`, then `Germany V3 Bundle Build And Release` consumes that release snapshot.

## Maintenance checklist

Preview stale generated artifacts (safe):

```bash
git clean -ndX
```

Delete stale ignored artifacts after preview:

```bash
git clean -fdX
```

Check recent scheduled pipeline health:

```bash
gh run list --workflow "Germany PBF Diff Update And Release" --limit 5 --json databaseId,status,conclusion,event,createdAt,headSha
gh run list --workflow "Germany V3 Bundle Build And Release" --limit 5 --json databaseId,status,conclusion,event,createdAt,headSha
```

## Separation rule for contributors

- Paper/benchmark changes must not alter consumer behavior unless explicitly migrating v3 production logic.
- Consumer app changes must not alter benchmark harness assumptions or paper reproducibility data paths.
