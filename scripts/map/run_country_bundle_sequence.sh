#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'USAGE'
Usage:
  scripts/map/run_country_bundle_sequence.sh [options]

Runs country bundle generation sequentially on GitHub Actions with cooldown and retry logic.
Countries are read from BundleTargets.top10.json by default.

Options:
  --workflow <file>           Workflow file name (default: generate_country_bundles.yml)
  --config <path>             Bundle target config JSON
                              (default: iphone/SpeedConsumerApp/BundleTargets.top10.json)
  --cooldown-sec <n>          Seconds to wait between countries (default: 120)
  --retry-attempts <n>        API retry attempts (default: 10)
  --retry-delay-sec <n>       Seconds between API retries (default: 15)
  --poll-sec <n>              Poll interval for run status (default: 30)
  --countries <csv>           Optional comma-separated country ids override
                              (example: germany,netherlands,romania)
  --ref <branch>              Git ref (default: main)
  --skip-release-urls <bool>  true/false, passed to workflow input (default: true)
  -h, --help                  Show this help
USAGE
}

workflow_file="generate_country_bundles.yml"
config_path="iphone/SpeedConsumerApp/BundleTargets.top10.json"
cooldown_sec=120
retry_attempts=10
retry_delay_sec=15
poll_sec=30
countries_csv=""
git_ref="main"
skip_release_urls="true"

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

dispatch_country() {
  local country="$1"
  local attempt
  local out
  local run_id=""
  for attempt in $(seq 1 "$retry_attempts"); do
    if out="$(gh workflow run "$workflow_file" \
      --ref "$git_ref" \
      --field "bundle_country=$country" \
      --field "execute=true" \
      --field "skip_release_urls=$skip_release_urls" 2>&1)"; then
      run_id="$(echo "$out" | sed -nE 's#^.*/actions/runs/([0-9]+)$#\1#p' | tail -n1)"
      if [[ -n "$run_id" ]]; then
        echo "$run_id"
        return 0
      fi
      echo "[dispatch] $country succeeded but run id could not be parsed; output: $out" >&2
    else
      echo "[dispatch] $country attempt $attempt/$retry_attempts failed" >&2
      echo "$out" >&2
    fi
    sleep "$retry_delay_sec"
  done
  return 1
}

wait_for_run() {
  local run_id="$1"
  local country="$2"
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
      echo "[monitor] $country run=$run_id API unreachable; continuing polling" >&2
      sleep "$poll_sec"
      continue
    fi

    status="$(echo "$line" | cut -f1)"
    conclusion="$(echo "$line" | cut -f2)"
    echo "[monitor] $country run=$run_id status=$status conclusion=${conclusion:-n/a}"

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

failed_countries=()
successful_countries=()

for country in "${countries[@]}"; do
  country="$(echo "$country" | xargs)"
  [[ -n "$country" ]] || continue

  echo
  echo "=== Country: $country ==="
  run_id=""
  if ! run_id="$(dispatch_country "$country")"; then
    echo "[result] $country dispatch failed"
    failed_countries+=("$country")
    echo "[cooldown] ${cooldown_sec}s"
    sleep "$cooldown_sec"
    continue
  fi

  echo "[dispatch] $country run=$run_id"
  if wait_for_run "$run_id" "$country"; then
    echo "[result] $country success"
    successful_countries+=("$country")
  else
    echo "[result] $country failed"
    failed_countries+=("$country")
  fi

  echo "[cooldown] ${cooldown_sec}s"
  sleep "$cooldown_sec"
done

echo
echo "=== Summary ==="
echo "Succeeded (${#successful_countries[@]}): ${successful_countries[*]:-}"
echo "Failed (${#failed_countries[@]}): ${failed_countries[*]:-}"

if [[ ${#failed_countries[@]} -gt 0 ]]; then
  exit 1
fi
