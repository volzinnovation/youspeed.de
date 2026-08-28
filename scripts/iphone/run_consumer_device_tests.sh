#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: run_consumer_device_tests.sh [options]

Run SpeedConsumer tests on an explicitly selected simulator or device.

Options:
  --destination <xcode destination>  Xcode destination (default: platform=iOS Simulator,name=iPhone 16)
  --derived-data <path>              DerivedData path (default: iphone/.derived/SpeedConsumerDeviceTest)
  --project <path>                   Xcode project path (default: iphone/SpeedDBBench.xcodeproj)
  --scheme <name>                    Xcode scheme (default: SpeedConsumer)
  --skip-project-gen                 Skip scripts/iphone/generate_xcode_project.sh
  --allow-provisioning-updates       Pass provisioning update flags to xcodebuild
  -h, --help                         Show this help text

EOF
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
destination="platform=iOS Simulator,name=iPhone 16"
derived_data="${repo_root}/iphone/.derived/SpeedConsumerDeviceTest"
project_path="${repo_root}/iphone/SpeedDBBench.xcodeproj"
scheme="SpeedConsumer"
skip_project_gen=0
allow_provisioning_updates=0

while [[ $# -gt 0 ]]; do
  case "$1" in
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

if [[ "${skip_project_gen}" != "1" ]]; then
  "${repo_root}/scripts/iphone/generate_xcode_project.sh"
fi

mkdir -p "${derived_data}"

build_cmd=(
  xcodebuild
  test
  -project "${project_path}"
  -scheme "${scheme}"
  -destination "${destination}"
  -derivedDataPath "${derived_data}"
  -hideShellScriptEnvironment
)

if [[ "${allow_provisioning_updates}" == "1" ]]; then
  build_cmd+=(
    -allowProvisioningUpdates
    -allowProvisioningDeviceRegistration
  )
fi

echo "Running tests on ${destination}."
"${build_cmd[@]}"
