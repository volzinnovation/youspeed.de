# youspeed.de

This repository has two separate workstreams:

- `Track A`: scientific probing and reproducible benchmarking for the paper (v1/v2/v3/v4 comparison, v3 selection).
- `Track B`: production consumer iPhone app development (v3 only) with independent data-bundle delivery.

Do not mix these concerns when adding code, tests, or workflows.

## Current overview (as of 2026-03-04)

- `Track B` (consumer app) is v3-only with startup sync/recovery hardening and multipart DB support.
- `Track A` (paper/benchmark) includes explicit city-context evaluation (`polycontainment`) in the on-device matrix.
- Bundle naming is region-scoped (`<region>_manifest.json`, `<region>_speeds.sqlite`) instead of legacy `DEU-latest*`.
- Country/region targeting is driven by `iphone/SpeedConsumerApp/BundleTargets.top10.json` (seed set excludes UK until mph/UK rules support is implemented).
- Country-specific fine/warning rules are bundled by `country_code` and resolved per active region bundle.
- Publication strategy is editor-mediated for OSM (user exports `.osc` and uploads with personal OSM account); no direct app-side OSM upload path.

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
- Benchmark dimensions:
  - maxspeed retrieval (`bbox`, `hybrid`, `polyline`)
  - city-context containment (`polycontainment`) in on-device matrix runs
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

This explicit `8`-point cap reproduces the historical paper baseline. Consumer bundle workflows now default to `24`.

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

6. Run release regression contract checks for v3 publishing safety:

```bash
python3 scripts/map/validate_v3_release_regressions.py --db mapdata/dist-v3/germany/speeds_v3.sqlite --probe-way-id 17721265 --expected-maxspeed-kmh 30 --probe-ref-way-id 1220097540 --expected-ref "L 564" --out-json mapdata/reports/germany-v3-release-regression.json
```

7. Run on-device benchmark harness (paper replication app):

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

### Implemented runtime behavior (consumer app)

- Per-fix lookup uses RTree candidate prefilter, geometric scoring, and preferred-way continuity.
- Effective speed precedence is: local override, explicit `maxspeed`, inherited regulatory tags, highway-class prior, legal fallback.
- In-city decision precedence is: highway class (`residential`, `service`, `crossing`, `living_street`) first, otherwise residential polygon containment.
- Tunnel mode is intentionally simple: matched way with `tunnel=yes` sets tunnel state; UI shows tunnel icon and penalty warnings are suppressed while active.
- Bundle routing is location-driven via coverage bbox/poly metadata across downloaded regional bundles, with fallback to the current DB if no coverage match exists.

### Consumer data model

Germany latest assets (release tag `germany`):

- `germany_manifest.json`
- `germany_speeds.sqlite` (if under GitHub per-asset limit)
- `germany_speeds.sqlite.partNNN` (if DB exceeds GitHub 2 GB per-asset limit; app reassembles parts)
- `germany_delta_index.json`
- `DEU-YYYY-MM-DD.v3_delta_manifest_from_YYYY-MM-DD.json` (0..30 recent updates)
- `DEU-YYYY-MM-DD.v3_patch_from_YYYY-MM-DD.sql.zlib` (matching delta manifests, zlib-compressed SQL)

Regional development example:

- `karlsruhe-regbez_manifest.json`
- `karlsruhe-regbez_speeds.sqlite`

Important policy enforced in app:

- If installed data is older than 30 days relative to target bundle version, skip incremental patching and do full bundle reload.

Geometry-sampling note:

- Consumer bundle generation now defaults to `--max-geom-points 24`. Karlsruhe seed and Netherlands release scans on the retained drivable-way subset showed that only `1.80%` and `1.94%` of ways exceed that cap, while a lower knee remains near `16` for future field validation.

### Local v3 bundle build/publish commands

```bash
FROM_VERSION=YYYY-MM-DD
TO_VERSION=YYYY-MM-DD

python3 scripts/map/build_spatialite_v3.py --v1-dist mapdata/dist/germany --out-db mapdata/dist-v3/germany/speeds_v3.sqlite
python3 scripts/map/build_v3_delta_pack.py --base-db mapdata/dist-v3/germany/speeds_v3.sqlite --diff-file mapdata/reports/deltas/daily/DEU-${TO_VERSION}.osc.gz --region germany --from-version "${FROM_VERSION}" --to-version "${TO_VERSION}" --out-dir mapdata/bundles/v3/germany/latest/deltas/${FROM_VERSION}_to_${TO_VERSION} --patch-file-name DEU-${TO_VERSION}.v3_patch_from_${FROM_VERSION}.sql.zlib --patch-compression zlib --manifest-name DEU-${TO_VERSION}.v3_delta_manifest_from_${FROM_VERSION}.json --github-owner volzinnovation --github-repo youspeed.de --github-release-tag germany
python3 scripts/map/roll_v3_delta_index.py --existing-index mapdata/bundles/v3/germany/latest/germany_delta_index.json --new-delta-manifest mapdata/bundles/v3/germany/latest/deltas/${FROM_VERSION}_to_${TO_VERSION}/DEU-${TO_VERSION}.v3_delta_manifest_from_${FROM_VERSION}.json --new-delta-manifest-asset-path DEU-${TO_VERSION}.v3_delta_manifest_from_${FROM_VERSION}.json --release-asset-base-url https://github.com/volzinnovation/youspeed.de/releases/download/germany --retention-count 30 --output mapdata/bundles/v3/germany/latest/germany_delta_index.json
python3 scripts/map/publish_v3_bundle.py --region germany --country-code DEU --db mapdata/dist-v3/germany/speeds_v3.sqlite --bundle-version "${TO_VERSION}" --bundle-dir-name latest --out-root mapdata/bundles/v3 --db-file-name germany_speeds.sqlite --manifest-name germany_manifest.json --delta-index mapdata/bundles/v3/germany/latest/germany_delta_index.json --delta-index-file-name germany_delta_index.json --github-owner volzinnovation --github-repo youspeed.de --github-release-tag germany
./scripts/map/publish_v3_release_assets.sh --repo volzinnovation/youspeed.de --tag germany --bundle-dir mapdata/bundles/v3/germany/latest
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
  - `/Users/raphaelvolz/Github/youspeed.de/.github/workflows/germany_generate_and_release_latest.yml`
- On-demand country/region bundle generation for the top-10 availability set:
  - `/Users/raphaelvolz/Github/youspeed.de/.github/workflows/generate_country_bundles.yml`
- Manual publish helper:
  - `/Users/raphaelvolz/Github/youspeed.de/.github/workflows/publish_bundle_release.yml`
- Manual Karlsruhe development bundle build/release:
  - `/Users/raphaelvolz/Github/youspeed.de/.github/workflows/karlsruhe_bundle_build_and_release.yml`
- Daily Karlsruhe PBF diff maintenance snapshot:
  - `/Users/raphaelvolz/Github/youspeed.de/.github/workflows/karlsruhe_pbf_diff_update_and_release.yml`
- Karlsruhe incremental bundle+delta release from maintained PBF snapshot:
  - `/Users/raphaelvolz/Github/youspeed.de/.github/workflows/karlsruhe_incremental_bundle_release.yml`
- Geofabrik diff ingestion and delta analysis:
  - `/Users/raphaelvolz/Github/youspeed.de/.github/workflows/daily_geofabrik_diff_update.yml`
- Workflow dependency:
  - `Germany PBF Diff Update And Release` publishes `deu-pbf-latest`, then `Germany Bundle Build And Release` consumes that release snapshot.

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
gh run list --workflow "Karlsruhe PBF Diff Update And Release" --limit 5 --json databaseId,status,conclusion,event,createdAt,headSha
gh run list --workflow "Karlsruhe Incremental Bundle Build And Release" --limit 5 --json databaseId,status,conclusion,event,createdAt,headSha
```

Quick project overview commands:

```bash
git status --short
git log --oneline --decorate -n 20
gh api rate_limit --jq '.resources.core'
```

Typical transient artifacts to avoid committing:

- `docs/cv/tmp/*`
- `docs/cv/*.aux`
- `iphone/SpeedDBBenchSketch/*.sqlite-wal`
- `iphone/SpeedDBBenchSketch/*.sqlite-shm`
- `mapdata/bundles/**/*.part*`
- timestamped device benchmark dumps under `paper/techreport/data/`

## Separation rule for contributors

- Paper/benchmark changes must not alter consumer behavior unless explicitly migrating v3 production logic.
- Consumer app changes must not alter benchmark harness assumptions or paper reproducibility data paths.
