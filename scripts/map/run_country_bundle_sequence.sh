#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/map/run_country_bundle_sequence.sh [options]

Runs country PBF snapshot and bundle generation sequentially on GitHub Actions
with cooldown and retry logic.
Countries are read from BundleTargets.top10.json by default.

Options:
  --workflow <file>           Bundle workflow file name
                              (default: generate_country_bundles.yml)
  --pbf-workflow <file>       PBF snapshot workflow file name
                              (default: country_pbf_diff_update.yml)
  --config <path>             Bundle target config JSON
                              (default: iphone/SpeedConsumerApp/BundleTargets.top10.json)
  --cooldown-sec <n>          Seconds to wait between countries (default: 120)
  --retry-attempts <n>        API retry attempts (default: 10)
  --retry-delay-sec <n>       Seconds between API retries (default: 15)
  --poll-sec <n>              Poll interval for run status (default: 30)
  --countries <csv>           Optional comma-separated country ids override
                              (example: germany,netherlands,romania)
  --ref <branch>              Git ref (default: main)
  --skip-release-urls <bool>  true/false, passed to bundle workflow input
                              (default: false)
  --force-publish <bool>      true/false, passed to bundle workflow input
                              (default: false)
  --skip-pbf-step             Skip the PBF snapshot workflow
  --skip-bundle-step          Skip the bundle workflow
  -h, --help                  Show this help
USAGE
}

workflow_file="generate_country_bundles.yml"
pbf_workflow_file="country_pbf_diff_update.yml"
config_path="iphone/SpeedConsumerApp/BundleTargets.top10.json"
cooldown_sec=120
retry_attempts=10
retry_delay_sec=15
poll_sec=30
countries_csv=""
git_ref="main"
skip_release_urls="false"
force_publish="false"
run_pbf_step="true"
run_bundle_step="true"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --workflow)
      workflow_file="${2:-}"
      shift 2
      ;;
    --config)
      config_path="${2:-}"
      shift 2
      ;;
    --pbf-workflow)
      pbf_workflow_file="${2:-}"
      shift 2
      ;;
    --cooldown-sec)
      cooldown_sec="${2:-}"
      shift 2
      ;;
    --retry-attempts)
      retry_attempts="${2:-}"
      shift 2
      ;;
    --retry-delay-sec)
      retry_delay_sec="${2:-}"
      shift 2
      ;;
    --poll-sec)
      poll_sec="${2:-}"
      shift 2
      ;;
    --countries)
      countries_csv="${2:-}"
      shift 2
      ;;
    --ref)
      git_ref="${2:-}"
      shift 2
      ;;
    --skip-release-urls)
      skip_release_urls="${2:-}"
      shift 2
      ;;
    --force-publish)
      force_publish="${2:-}"
      shift 2
      ;;
    --skip-pbf-step)
      run_pbf_step="false"
      shift
      ;;
    --skip-bundle-step)
      run_bundle_step="false"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if ! command -v gh >/dev/null 2>&1; then
  echo "gh CLI is required" >&2
  exit 1
fi

if ! command -v python3 >/dev/null 2>&1; then
  echo "python3 is required" >&2
  exit 1
fi

if [[ -z "$countries_csv" ]]; then
  if [[ ! -f "$config_path" ]]; then
    echo "Config file not found: $config_path" >&2
    exit 1
  fi
  countries=()
  while IFS= read -r line; do
    [[ -n "$line" ]] && countries+=("$line")
  done < <(python3 - "$config_path" <<'PY'
import json
import sys
from pathlib import Path

path = Path(sys.argv[1])
obj = json.loads(path.read_text(encoding="utf-8"))
for row in obj.get("countries", []):
    cid = str(row.get("country_id", "")).strip().lower()
    if cid:
        print(cid)
PY
)
else
  IFS=',' read -r -a countries <<< "$countries_csv"
fi

if [[ ${#countries[@]} -eq 0 ]]; then
  echo "No countries to process" >&2
  exit 1
fi

if [[ "$run_pbf_step" != "true" && "$run_bundle_step" != "true" ]]; then
  echo "Nothing to do: both PBF and bundle steps are disabled" >&2
  exit 1
fi

dispatch_workflow() {
  local workflow="$1"
  shift
  local attempt
  local out
  local run_id=""
  for attempt in $(seq 1 "$retry_attempts"); do
    local cmd=(
      gh workflow run "$workflow"
      --ref "$git_ref"
    )
    local field
    for field in "$@"; do
      cmd+=(--field "$field")
    done

    if out="$("${cmd[@]}" 2>&1)"; then
      run_id="$(echo "$out" | sed -nE 's#^.*/actions/runs/([0-9]+)$#\1#p' | tail -n1)"
      if [[ -n "$run_id" ]]; then
        echo "$run_id"
        return 0
      fi
      echo "[dispatch] workflow=${workflow} succeeded but run id could not be parsed; output: $out" >&2
    else
      echo "[dispatch] workflow=${workflow} attempt $attempt/$retry_attempts failed" >&2
      echo "$out" >&2
    fi
    sleep "$retry_delay_sec"
  done
  return 1
}

wait_for_run() {
  local run_id="$1"
  local label="$2"
  local status=""
  local conclusion=""
  local line=""
  local attempt
  while true; do
    line=""
    for attempt in $(seq 1 "$retry_attempts"); do
      if line="$(gh run view "$run_id" \
        --json status,conclusion,url \
        --jq '.status + "\t" + (.conclusion // "") + "\t" + .url' 2>/dev/null)"; then
        break
      fi
      sleep "$retry_delay_sec"
    done

    if [[ -z "$line" ]]; then
      echo "[monitor] $label run=$run_id API unreachable; continuing polling" >&2
      sleep "$poll_sec"
      continue
    fi

    status="$(echo "$line" | cut -f1)"
    conclusion="$(echo "$line" | cut -f2)"
    echo "[monitor] $label run=$run_id status=$status conclusion=${conclusion:-n/a}"

    if [[ "$status" == "completed" ]]; then
      if [[ "$conclusion" == "success" ]]; then
        return 0
      fi
      return 1
    fi
    sleep "$poll_sec"
  done
}

echo "Workflow: $workflow_file"
echo "Countries (${#countries[@]}): ${countries[*]}"
echo "Cooldown: ${cooldown_sec}s, retries: ${retry_attempts}, retry delay: ${retry_delay_sec}s"
echo "Force publish: ${force_publish}"

failed_countries=()
successful_countries=()
pbf_failed_countries=()
bundle_failed_countries=()

for country in "${countries[@]}"; do
  country="$(echo "$country" | xargs)"
  [[ -n "$country" ]] || continue

  echo
  echo "=== Country: $country ==="

  country_failed=0

  if [[ "$run_pbf_step" == "true" ]]; then
    run_id=""
    if ! run_id="$(dispatch_workflow "$pbf_workflow_file" "bundle_country=$country")"; then
      echo "[result] $country pbf dispatch failed"
      failed_countries+=("$country")
      pbf_failed_countries+=("$country")
      country_failed=1
    else
      echo "[dispatch] $country pbf run=$run_id"
      if wait_for_run "$run_id" "$country:pbf"; then
        echo "[result] $country pbf success"
      else
        echo "[result] $country pbf failed"
        failed_countries+=("$country")
        pbf_failed_countries+=("$country")
        country_failed=1
      fi
    fi

    echo "[cooldown] ${cooldown_sec}s"
    sleep "$cooldown_sec"
  fi

  if [[ "$country_failed" == "1" ]]; then
    continue
  fi

  if [[ "$run_bundle_step" == "true" ]]; then
    run_id=""
    if ! run_id="$(dispatch_workflow "$workflow_file" \
      "bundle_country=$country" \
      "execute=true" \
      "skip_release_urls=$skip_release_urls" \
      "force_publish=$force_publish")"; then
      echo "[result] $country bundle dispatch failed"
      failed_countries+=("$country")
      bundle_failed_countries+=("$country")
      country_failed=1
    else
      echo "[dispatch] $country bundle run=$run_id"
      if wait_for_run "$run_id" "$country:bundle"; then
        echo "[result] $country bundle success"
      else
        echo "[result] $country bundle failed"
        failed_countries+=("$country")
        bundle_failed_countries+=("$country")
        country_failed=1
      fi
    fi

    echo "[cooldown] ${cooldown_sec}s"
    sleep "$cooldown_sec"
  fi

  if [[ "$country_failed" == "0" ]]; then
    successful_countries+=("$country")
  fi
done

echo
echo "=== Summary ==="
echo "Succeeded (${#successful_countries[@]}): ${successful_countries[*]:-}"
echo "Failed (${#failed_countries[@]}): ${failed_countries[*]:-}"
if [[ "$run_pbf_step" == "true" ]]; then
  echo "PBF failed (${#pbf_failed_countries[@]}): ${pbf_failed_countries[*]:-}"
fi
if [[ "$run_bundle_step" == "true" ]]; then
  echo "Bundle failed (${#bundle_failed_countries[@]}): ${bundle_failed_countries[*]:-}"
fi

if [[ ${#failed_countries[@]} -gt 0 ]]; then
  exit 1
fi
