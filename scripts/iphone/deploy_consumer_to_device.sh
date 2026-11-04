#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: deploy_consumer_to_device.sh [options]

Install the latest built SpeedConsumer .app onto a connected iPhone and launch it.

Options:
  --derived-data <path>      DerivedData path (default: iphone/.derived/SpeedConsumerBuild)
  --scheme <name>            App scheme/product name (default: SpeedConsumer)
  --app-path <path>          Explicit .app path (skip latest-build lookup)
  --device <identifier>      Device UUID/UDID/name for devicectl (default: first connected device)
  --bundle-id <id>           Expected app identifier (must match app Info.plist)
  --no-launch                Install only; do not launch app
  --no-terminate-existing    Launch without --terminate-existing
  --timeout <seconds>        devicectl timeout in seconds (default: 1800)
  -h, --help                 Show this help text
EOF
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
derived_data="${repo_root}/iphone/.derived/SpeedConsumerBuild"
scheme="SpeedConsumer"
app_path=""
device=""
bundle_id=""
launch_after_install=1
terminate_existing=1
timeout_seconds="1800"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --derived-data)
      derived_data="${2:-}"
      shift 2
      ;;
    --scheme)
      scheme="${2:-}"
      shift 2
      ;;
    --app-path)
      app_path="${2:-}"
      shift 2
      ;;
    --device)
      device="${2:-}"
      shift 2
      ;;
    --bundle-id)
      bundle_id="${2:-}"
      shift 2
      ;;
    --no-launch)
      launch_after_install=0
      shift
      ;;
    --no-terminate-existing)
      terminate_existing=0
      shift
      ;;
    --timeout)
      timeout_seconds="${2:-}"
      shift 2
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown option: $1" >&2
      usage >&2
      exit 1
      ;;
  esac
done

if ! [[ "${timeout_seconds}" =~ ^[0-9]+$ ]]; then
  echo "Invalid --timeout value: ${timeout_seconds}" >&2
  exit 1
fi

pick_latest_app() {
  local products_dir="$1"
  local app_name="$2"
  local latest_path=""
  local latest_mtime=0

  if [[ -d "${products_dir}" ]]; then
    while IFS= read -r -d '' candidate; do
      local mtime
      mtime="$(stat -f '%m' "${candidate}" 2>/dev/null || echo 0)"
      if (( mtime > latest_mtime )); then
        latest_mtime="${mtime}"
        latest_path="${candidate}"
      fi
    done < <(find "${products_dir}" -type d -path "*-iphoneos/${app_name}.app" -print0)

    if [[ -z "${latest_path}" ]]; then
      while IFS= read -r -d '' candidate; do
        local mtime
        mtime="$(stat -f '%m' "${candidate}" 2>/dev/null || echo 0)"
        if (( mtime > latest_mtime )); then
          latest_mtime="${mtime}"
          latest_path="${candidate}"
        fi
      done < <(find "${products_dir}" -type d -name "${app_name}.app" -print0)
    fi
  fi

  printf '%s' "${latest_path}"
}

if [[ -z "${app_path}" ]]; then
  app_path="$(pick_latest_app "${derived_data}/Build/Products" "${scheme}")"
fi

if [[ -z "${app_path}" || ! -d "${app_path}" ]]; then
  echo "No built app found for scheme '${scheme}' under '${derived_data}/Build/Products'." >&2
  echo "Build first (for device), e.g. scripts/iphone/build_consumer_app.sh --destination 'generic/platform=iOS' --skip-project-gen" >&2
  exit 2
fi

if [[ -z "${device}" ]]; then
  device="$(
    xcrun devicectl list devices \
      | sed -nE 's/.* ([0-9A-Fa-f-]{36}) +connected.*/\1/p' \
      | head -n 1
  )"
fi

if [[ -z "${device}" ]]; then
  echo "No connected iOS device found. Connect/unlock a device and trust this Mac." >&2
  exit 3
fi

artifact_bundle_id="$(/usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' "${app_path}/Info.plist")"
if [[ -z "${artifact_bundle_id}" ]]; then
  echo "Built app has no bundle identifier; installation stopped." >&2
  exit 4
fi
if [[ -n "${bundle_id}" && "${bundle_id}" != "${artifact_bundle_id}" ]]; then
  echo "Expected app '${bundle_id}', but built app is '${artifact_bundle_id}'; installation stopped." >&2
  exit 4
fi
bundle_id="${artifact_bundle_id}"

# A different identifier creates another sandbox instead of updating user data.
# Inspect the phone before installing; never resolve a conflict by uninstalling.
inventory_path="$(mktemp -t youspeed-install-inventory)"
trap 'rm -f "${inventory_path}"' EXIT
xcrun devicectl --timeout "${timeout_seconds}" --json-output "${inventory_path}" \
  device info apps --device "${device}" --include-all-apps >/dev/null
python3 "${repo_root}/scripts/iphone/check_consumer_install_identity.py" \
  --inventory "${inventory_path}" --bundle-id "${bundle_id}"

echo "Deploying app:"
echo "  app:      ${app_path}"
echo "  device:   ${device}"
echo "  bundleId: ${bundle_id}"

xcrun devicectl --timeout "${timeout_seconds}" device install app \
  --device "${device}" \
  "${app_path}"

if [[ "${launch_after_install}" == "1" ]]; then
  launch_cmd=(
    xcrun devicectl --timeout "${timeout_seconds}" device process launch
    --device "${device}"
  )
  if [[ "${terminate_existing}" == "1" ]]; then
    launch_cmd+=(--terminate-existing)
  fi
  launch_cmd+=("${bundle_id}")
  "${launch_cmd[@]}"
fi

echo "Deploy finished."
