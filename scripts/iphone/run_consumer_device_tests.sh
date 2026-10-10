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
  --only-testing <test-identifier>   Run only this XCTest identifier (repeatable)
  --skip-testing <test-identifier>   Skip this XCTest identifier (repeatable)
  --result-bundle <path>             Write an .xcresult evidence bundle
  --development-team <team-id>       Apply one signing team to app and test bundle
  --skip-project-gen                 Skip scripts/iphone/generate_xcode_project.sh
  --allow-provisioning-updates       Pass provisioning update flags to xcodebuild
  --installed-app-ui-tests          Run only UI tests on the driver's installed app
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
only_testing=()
skip_testing=()
result_bundle=""
development_team=""
installed_app_ui_tests=0

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
    --only-testing)
      only_testing+=("${2:-}")
      shift 2
      ;;
    --skip-testing)
      skip_testing+=("${2:-}")
      shift 2
      ;;
    --result-bundle)
      result_bundle="${2:-}"
      shift 2
      ;;
    --development-team)
      development_team="${2:-}"
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
    --installed-app-ui-tests)
      installed_app_ui_tests=1
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

if [[ "${installed_app_ui_tests}" == "1" ]]; then
  if [[ "${scheme}" != "SpeedConsumer" ]]; then
    echo "--installed-app-ui-tests requires the SpeedConsumer scheme." >&2
    exit 1
  fi
  for test_identifier in ${only_testing[@]+"${only_testing[@]}"}; do
    if [[ "${test_identifier}" != "SpeedConsumerUITests" && "${test_identifier}" != SpeedConsumerUITests/* ]]; then
      echo "Installed-app testing permits only SpeedConsumerUITests; unit tests require an isolated host." >&2
      exit 1
    fi
  done
  if [[ ${#only_testing[@]} -eq 0 ]]; then
    only_testing=("SpeedConsumerUITests")
  fi
fi

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

# A distinct app container protects the driver's maps, observations and settings.
# The one live UI flow explicitly depends on the driver's installed map, so run
# it separately with --installed-app-ui-tests after the isolated suite passes.
if [[ "${scheme}" == "SpeedConsumer" && "${installed_app_ui_tests}" != "1" ]]; then
  build_cmd+=("YOUSPEED_TEST_BUNDLE_SUFFIX=.TestHost")
  build_cmd+=("-skip-testing:SpeedConsumerUITests/ScreenOrientationUITests/testLiveSettingsDismissalReopenAndNestedDebugNavigation")
fi

for test_identifier in ${only_testing[@]+"${only_testing[@]}"}; do
  if [[ -z "${test_identifier}" ]]; then
    echo "Missing --only-testing value." >&2
    exit 1
  fi
  build_cmd+=("-only-testing:${test_identifier}")
done

for test_identifier in ${skip_testing[@]+"${skip_testing[@]}"}; do
  if [[ -z "${test_identifier}" ]]; then
    echo "Missing --skip-testing value." >&2
    exit 1
  fi
  build_cmd+=("-skip-testing:${test_identifier}")
done

if [[ -n "${result_bundle}" ]]; then
  build_cmd+=(
    -resultBundlePath "${result_bundle}"
  )
fi

if [[ -n "${development_team}" ]]; then
  build_cmd+=("DEVELOPMENT_TEAM=${development_team}")
fi

if [[ "${allow_provisioning_updates}" == "1" ]]; then
  build_cmd+=(
    -allowProvisioningUpdates
    -allowProvisioningDeviceRegistration
  )
fi

echo "Running tests on ${destination}."
"${build_cmd[@]}"
