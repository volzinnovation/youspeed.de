#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: build_consumer_app.sh [options]

Build the SpeedConsumer iOS app from public release assets.

Options:
  --configuration <Debug|Release>   Build configuration (default: Debug)
  --destination <xcode destination> Xcode destination (default: generic/platform=iOS Simulator)
  --derived-data <path>             DerivedData path (default: iphone/.derived/SpeedConsumerBuild)
  --project <path>                  Xcode project path (default: iphone/SpeedDBBench.xcodeproj)
  --scheme <name>                   Xcode scheme (default: SpeedConsumer)
  --skip-project-gen                Skip running scripts/iphone/generate_xcode_project.sh
  --clean                           Run xcodebuild clean before build
  --allow-provisioning-updates      Pass -allowProvisioningUpdates and -allowProvisioningDeviceRegistration
  -h, --help                        Show this help text

EOF
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
configuration="Debug"
destination="generic/platform=iOS Simulator"
derived_data="${repo_root}/iphone/.derived/SpeedConsumerBuild"
project_path="${repo_root}/iphone/SpeedDBBench.xcodeproj"
scheme="SpeedConsumer"
skip_project_gen=0
run_clean=0
allow_provisioning_updates=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --configuration)
      configuration="${2:-}"
      shift 2
      ;;
    --destination)
      destination="${2:-}"
      shift 2
      ;;
    --derived-data)
      derived_data="${2:-}"
      shift 2
      ;;
    --project)
      project_path="${2:-}"
      shift 2
      ;;
    --scheme)
      scheme="${2:-}"
      shift 2
      ;;
    --skip-project-gen)
      skip_project_gen=1
      shift
      ;;
    --clean)
      run_clean=1
      shift
      ;;
    --allow-provisioning-updates)
      allow_provisioning_updates=1
      shift
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

if [[ -z "${configuration}" || -z "${destination}" || -z "${derived_data}" || -z "${project_path}" || -z "${scheme}" ]]; then
  echo "Missing required option value." >&2
  usage >&2
  exit 1
fi

if [[ "${skip_project_gen}" != "1" ]]; then
  "${repo_root}/scripts/iphone/generate_xcode_project.sh"
fi

mkdir -p "${derived_data}"

build_cmd=(
  xcodebuild
  -project "${project_path}"
  -scheme "${scheme}"
  -configuration "${configuration}"
  -destination "${destination}"
  -derivedDataPath "${derived_data}"
  -hideShellScriptEnvironment
  build
)

if [[ "${allow_provisioning_updates}" == "1" ]]; then
  build_cmd+=(
    -allowProvisioningUpdates
    -allowProvisioningDeviceRegistration
  )
fi

if [[ "${run_clean}" == "1" ]]; then
  clean_cmd=(
    xcodebuild
    -project "${project_path}"
    -scheme "${scheme}"
    -configuration "${configuration}"
    -destination "${destination}"
    -derivedDataPath "${derived_data}"
    -hideShellScriptEnvironment
    clean
  )
  if [[ "${allow_provisioning_updates}" == "1" ]]; then
    clean_cmd+=(
      -allowProvisioningUpdates
      -allowProvisioningDeviceRegistration
    )
  fi
  "${clean_cmd[@]}"
fi

"${build_cmd[@]}"

echo "Build finished successfully."
echo "DerivedData: ${derived_data}"
find "${derived_data}/Build/Products" -maxdepth 3 -name "${scheme}.app" -print | head -n 5
