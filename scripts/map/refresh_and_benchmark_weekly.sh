#!/usr/bin/env bash
set -euo pipefail

# Weekly refresh benchmark helper (default target date: next Monday).
# Usage:
#   ./scripts/map/refresh_and_benchmark_weekly.sh [run_date_utc]
# Example:
#   ./scripts/map/refresh_and_benchmark_weekly.sh 2026-03-02

run_date="${1:-$(date -u +%F)}"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

pbf_url="${PBF_URL:-https://download.geofabrik.de/europe/germany-latest.osm.pbf}"
raw_dir="${repo_root}/mapdata/raw"
report_dir="${repo_root}/mapdata/reports"
techreport_data_dir="${repo_root}/techreport/data"

mkdir -p "${raw_dir}" "${report_dir}" "${techreport_data_dir}"

pbf_path="${raw_dir}/germany-latest-${run_date}.osm.pbf"
pbf_tmp="${pbf_path}.tmp"
report_path="${report_dir}/benchmark_report.${run_date}.json"
techreport_report_path="${techreport_data_dir}/benchmark_report.${run_date}.json"

echo "Downloading ${pbf_url} -> ${pbf_path}" >&2
curl -L --fail "${pbf_url}" -o "${pbf_tmp}"
mv "${pbf_tmp}" "${pbf_path}"

echo "Running build + benchmark (v1-v4) for ${run_date}" >&2
python3 "${repo_root}/scripts/map/build_and_benchmark_v2.py" \
  --region germany \
  --input-pbf "${pbf_path}" \
  --lat 52.5200 \
  --lon 13.4050 \
  --heading 90 \
  --repeats "${BENCH_REPEATS:-5}" \
  --report-path "${report_path}"

cp "${report_path}" "${techreport_report_path}"
echo "Wrote benchmark report: ${report_path}" >&2
echo "Copied report for techreport archive: ${techreport_report_path}" >&2
