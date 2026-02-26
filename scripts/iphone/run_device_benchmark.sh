#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 || $# -gt 5 ]]; then
  echo "Usage: $0 <xcodeproj_path> <scheme> <device_udid> [configuration=Release] [result_dir=/tmp/speeddbbench]" >&2
  echo "Hint: list devices with: xcrun xctrace list devices" >&2
  exit 1
fi

project_path="$1"
scheme="$2"
device_udid="$3"
configuration="${4:-Release}"
result_dir="${5:-/tmp/speeddbbench}"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
run_start_epoch="$(date +%s)"
result_bundle="${result_dir}/SpeedDBBench-${timestamp}.xcresult"
result_json="${result_dir}/SpeedDBBench-${timestamp}.xcresult.json"
matrix_json="${result_dir}/SpeedDBBench-${timestamp}.matrix.json"
derived_data="${result_dir}/DerivedData-${timestamp}"
run_log="${result_dir}/SpeedDBBench-${timestamp}.log"
destinations_log="${result_dir}/SpeedDBBench-${timestamp}.destinations.log"
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
bundle_id="de.youspeed.SpeedDBBench"
country_db_src="${SPEEDDBBENCH_COUNTRY_DB:-${repo_root}/mapdata/dist-v4/germany/speeds_v4.sqlite}"
fallback_country_db_src="${repo_root}/mapdata/dist-v4/germany/speeds_v4.sqlite"

action_log_json="${result_dir}/SpeedDBBench-${timestamp}.action-log.json"
docs_dump_dir="${result_dir}/SpeedDBBench-${timestamp}.device-docs"

mkdir -p "${result_dir}"

has_full_matrix_schema() {
  local db_path="$1"
  if [[ ! -f "${db_path}" ]]; then
    return 1
  fi
  if ! command -v sqlite3 >/dev/null 2>&1; then
    return 1
  fi

  local ways_count
  local rtree_count
  local tile_count
  ways_count="$(sqlite3 "${db_path}" "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='ways';" 2>/dev/null || echo 0)"
  rtree_count="$(sqlite3 "${db_path}" "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='ways_rtree';" 2>/dev/null || echo 0)"
  tile_count="$(sqlite3 "${db_path}" "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='way_tile';" 2>/dev/null || echo 0)"

  [[ "${ways_count}" == "1" && "${rtree_count}" == "1" && "${tile_count}" == "1" ]]
}

resolve_country_db_for_full_matrix() {
  if has_full_matrix_schema "${country_db_src}"; then
    return 0
  fi

  echo "Provided DB is not full-matrix (v1-v4) capable: ${country_db_src}" >&2
  if [[ "${country_db_src}" != "${fallback_country_db_src}" ]] && has_full_matrix_schema "${fallback_country_db_src}"; then
    echo "Switching to full-matrix fallback DB: ${fallback_country_db_src}" >&2
    country_db_src="${fallback_country_db_src}"
    return 0
  fi

  echo "No suitable DB found with ways+ways_rtree+way_tile schema." >&2
  echo "Build or provide mapdata/dist-v4/germany/speeds_v4.sqlite to benchmark v1-v4 distinctly." >&2
  return 1
}

run_xcodebuild_with_timeout() {
  local timeout_s="$1"
  shift
  python3 - "$timeout_s" "$@" <<'PY'
import subprocess
import sys

timeout_s = float(sys.argv[1])
cmd = sys.argv[2:]
try:
    res = subprocess.run(cmd, timeout=timeout_s, check=False)
    raise SystemExit(res.returncode)
except subprocess.TimeoutExpired:
    raise SystemExit(124)
PY
}

require_device_ready() {
  echo "Checking destination availability for device id=${device_udid}" >&2
  if ! xcodebuild -showdestinations \
    -project "${project_path}" \
    -scheme "${scheme}" \
    -configuration Debug \
    >"${destinations_log}" 2>&1; then
    cat "${destinations_log}" >&2
  fi

  if ! rg -q "${device_udid}" "${destinations_log}"; then
    echo "Configured device is not available for the current scheme." >&2
    exit 1
  fi
}

stage_country_db_on_device() {
  local stage_derived_data="${result_dir}/StageDerivedData-${timestamp}"
  local stage_build_log="${result_dir}/SpeedDBBench-${timestamp}.stage-build.log"
  local stage_install_log="${result_dir}/SpeedDBBench-${timestamp}.stage-install.log"
  local stage_copy_log="${result_dir}/SpeedDBBench-${timestamp}.stage-copy.log"
  local app_path="${stage_derived_data}/Build/Products/Debug-iphoneos/${scheme}.app"

  if [[ ! -f "${country_db_src}" ]]; then
    echo "Missing country-scale DB artifact: ${country_db_src}" >&2
    return 1
  fi

  echo "Staging country-scale DB to device: ${country_db_src}" >&2
  ls -lh "${country_db_src}" >&2

  if ! run_xcodebuild_with_timeout 1200 \
    xcodebuild build \
      -project "${project_path}" \
      -scheme "${scheme}" \
      -configuration Debug \
      -destination "generic/platform=iOS" \
      -derivedDataPath "${stage_derived_data}" \
      -allowProvisioningUpdates \
      -allowProvisioningDeviceRegistration \
      -quiet >"${stage_build_log}" 2>&1; then
    cat "${stage_build_log}" >&2
    return 1
  fi

  if [[ ! -d "${app_path}" ]]; then
    app_path="$(find "${stage_derived_data}/Build/Products" -maxdepth 2 -name '*.app' | head -n1 || true)"
  fi
  if [[ -z "${app_path}" || ! -d "${app_path}" ]]; then
    echo "Unable to locate built app in ${stage_derived_data}" >&2
    return 1
  fi

  if ! xcrun devicectl --timeout 1800 device install app \
    --device "${device_udid}" \
    "${app_path}" >"${stage_install_log}" 2>&1; then
    cat "${stage_install_log}" >&2
    return 1
  fi

  if ! xcrun devicectl --timeout 7200 device copy to \
    --device "${device_udid}" \
    --source "${country_db_src}" \
    --destination "tmp/speeds_v4_germany.sqlite" \
    --domain-type appDataContainer \
    --domain-identifier "${bundle_id}" >"${stage_copy_log}" 2>&1; then
    cat "${stage_copy_log}" >&2
    return 1
  fi
}

run_ui_benchmark_tests() {
  echo "Running UI benchmark test flow on device id=${device_udid}" >&2
  if [[ "${configuration}" != "Debug" ]]; then
    echo "Using Debug for test execution (required for testability)." >&2
  fi

  local rc=0
  run_xcodebuild_with_timeout 3600 \
    xcodebuild test \
      -project "${project_path}" \
      -scheme "${scheme}" \
      -configuration Debug \
      -destination "id=${device_udid}" \
      -destination-timeout 30 \
      -derivedDataPath "${derived_data}" \
      -resultBundlePath "${result_bundle}" \
      -allowProvisioningUpdates \
      -allowProvisioningDeviceRegistration \
      -only-testing:SpeedDBBenchUITests \
      -quiet >"${run_log}" 2>&1 || rc=$?

  if [[ "${rc}" -ne 0 ]]; then
    cat "${run_log}" >&2
    if [[ "${rc}" -eq 124 ]]; then
      echo "Device UI benchmark timed out." >&2
    fi
    exit 1
  fi
}

extract_xcresult_json() {
  echo "Extracting xcresult JSON..." >&2
  xcrun xcresulttool get object --legacy --path "${result_bundle}" --format json > "${result_json}"

  python3 - "${result_json}" "${result_bundle}" "${action_log_json}" <<'PY'
import json
import subprocess
import sys
from pathlib import Path

result_json = Path(sys.argv[1])
xcresult = Path(sys.argv[2])
action_log_json = Path(sys.argv[3])
root = json.loads(result_json.read_text())
log_ref = root["actions"]["_values"][0]["actionResult"]["logRef"]["id"]["_value"]
payload = subprocess.check_output(
    [
        "xcrun",
        "xcresulttool",
        "get",
        "object",
        "--legacy",
        "--path",
        str(xcresult),
        "--id",
        log_ref,
        "--format",
        "json",
    ],
    text=True,
)
action_log_json.write_text(payload)
PY
}

copy_report_from_device() {
  rm -rf "${docs_dump_dir}"
  mkdir -p "${docs_dump_dir}"

  echo "Copying benchmark reports from device Documents..." >&2
  if ! xcrun devicectl --timeout 1800 device copy from \
    --device "${device_udid}" \
    --source "Documents" \
    --destination "${docs_dump_dir}" \
    --domain-type appDataContainer \
    --domain-identifier "${bundle_id}" \
    --remove-existing-content true >"${result_dir}/SpeedDBBench-${timestamp}.copy-docs.log" 2>&1; then
    cat "${result_dir}/SpeedDBBench-${timestamp}.copy-docs.log" >&2
    exit 1
  fi
}

validate_matrix() {
  python3 - "${docs_dump_dir}" "${run_start_epoch}" "${matrix_json}" <<'PY'
import json
import re
import sys
from pathlib import Path

docs = Path(sys.argv[1])
min_epoch = int(sys.argv[2])
out = Path(sys.argv[3])

candidates = sorted(docs.rglob("benchmark_report_*.json"), key=lambda p: p.stat().st_mtime, reverse=True)
if not candidates:
    raise SystemExit("No benchmark_report_*.json found in copied Documents")

picked = None
for path in candidates:
    m = re.search(r"benchmark_report_(\d+)\.json$", path.name)
    if m and int(m.group(1)) >= (min_epoch - 30):
        picked = path
        break
if picked is None:
    picked = candidates[0]

report = json.loads(picked.read_text())
bench = report.get("benchmarkMs", {})
required_variants = ("v1", "v2", "v3", "v4")
required_modes = ("bbox", "hybrid", "polyline", "polycontainment")
for variant in required_variants:
    if variant not in bench:
        raise SystemExit(f"Missing variant in report: {variant}")
    for mode in required_modes:
        mode_row = bench.get(variant, {}).get(mode)
        if mode_row is None:
            raise SystemExit(f"Missing mode in report: {variant}.{mode}")
        if mode_row.get("avgMs") is None:
            raise SystemExit(f"Missing avgMs in report: {variant}.{mode}")

size_bytes = int(report.get("dbSizeBytes", 0))
if size_bytes < 1_000_000_000:
    raise SystemExit(f"Expected country-scale DB (>=1e9 bytes), got {size_bytes}")

db_path = str(report.get("dbPath", ""))
if "speeds_v4_germany.sqlite" not in db_path:
    raise SystemExit(f"Expected country DB path to include speeds_v4_germany.sqlite, got {db_path!r}")

out_payload = {
    "datasetKind": "country_germany_v4",
    "sourceReportPath": str(picked),
    "report": report,
}
out.write_text(json.dumps(out_payload, indent=2, sort_keys=True))

print(f"matrix_json={out}")
print(f"source_report={picked}")
print(f"db_size_bytes={size_bytes}")
for mode in required_modes:
    vals = [bench[v][mode]["avgMs"] for v in required_variants]
    print(f"{mode}: v1={vals[0]} v2={vals[1]} v3={vals[2]} v4={vals[3]}")
PY
}

require_device_ready
resolve_country_db_for_full_matrix
stage_country_db_on_device
run_ui_benchmark_tests
cat "${run_log}" >&2
extract_xcresult_json
copy_report_from_device
validate_matrix

echo "run mode:         device"
echo "xcresult bundle: ${result_bundle}"
echo "xcresult json:   ${result_json}"
echo "matrix json:     ${matrix_json}"
echo "derived data:    ${derived_data}"
echo "run log:         ${run_log}"
echo "destinations:    ${destinations_log}"
