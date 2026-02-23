# Weekly Refresh Benchmark Plan (March 2, 2026)

Planned execution date:
- Monday, March 2, 2026 (UTC date tag: `2026-03-02`)

Goal:
- Rebuild and benchmark `v1-v4` from a fresh Germany PBF snapshot.
- Compare query latency, artifact sizes, and update-delivery costs against the 2026-02-23 baseline.

## Inputs
- Source URL:
  - `https://download.geofabrik.de/europe/germany-latest.osm.pbf`
- Baseline report:
  - `techreport/data/benchmark_report.json` (generated 2026-02-23)

## Command
```bash
./scripts/map/refresh_and_benchmark_weekly.sh 2026-03-02
```

Optional:
- `BENCH_REPEATS=10 ./scripts/map/refresh_and_benchmark_weekly.sh 2026-03-02`

## Outputs
- Dated report:
  - `mapdata/reports/benchmark_report.2026-03-02.json`
- Archived copy for techreport:
  - `techreport/data/benchmark_report.2026-03-02.json`
- New input snapshot:
  - `mapdata/raw/germany-latest-2026-03-02.osm.pbf`

## Metrics to compare
- Query latency (avg/p50/min/max) for each mode (`bbox`, `hybrid`, `polyline`) and variant (`v1-v4`).
- Artifact footprint:
  - file count
  - total bytes
- Delivery cost estimates:
  - full replacement (`v2`, `v3`, `v4`)
  - hypothetical selective update (`v2` changed-tile subsets, e.g. 1%, 2%, 5%)

## Acceptance checks
- `v3` remains the best runtime for `hybrid` and `polyline` mode latency.
- `v4` remains competitive in `bbox` mode.
- No regression above +20% in `v3 hybrid` at Berlin probe vs baseline.
- Build scripts and benchmarks complete without manual fixes.
