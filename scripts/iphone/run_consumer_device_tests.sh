#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: run_consumer_device_tests.sh [options]

Run SpeedConsumer tests with mandatory GitHub release token injection and verify
the token is embedded into the built app Info.plist.

Options:
  --destination <xcode destination>  Xcode destination (default: id=00008120-000251EC3E10201E)
  --derived-data <path>              DerivedData path (default: iphone/.derived/SpeedConsumerTokenDeviceTest)
  --project <path>                   Xcode project path (default: iphone/SpeedDBBench.xcodeproj)
  --scheme <name>                    Xcode scheme (default: SpeedConsumer)
  --token <value>                    Token value for YOUSPEED_RELEASE_READ_TOKEN
  --use-gh-token                     Resolve token from `gh auth token`
  --skip-project-gen                 Skip scripts/iphone/generate_xcode_project.sh
  --allow-provisioning-updates       Pass provisioning update flags to xcodebuild
  -h, --help                         Show this help text

Environment:
  YOUSPEED_RELEASE_READ_TOKEN        Required token source
  GITHUB_RELEASE_TOKEN               Legacy fallback token source
  GH_TOKEN                           Optional fallback token source
EOF
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
destination="id=00008120-000251EC3E10201E"
derived_data="${repo_root}/iphone/.derived/SpeedConsumerTokenDeviceTest"
project_path="${repo_root}/iphone/SpeedDBBench.xcodeproj"
scheme="SpeedConsumer"
skip_project_gen=0
allow_provisioning_updates=0
token="${YOUSPEED_RELEASE_READ_TOKEN:-${GITHUB_RELEASE_TOKEN:-${GH_TOKEN:-}}}"
use_gh_token=0

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
    --token)
      token="${2:-}"
      shift 2
      ;;
    --use-gh-token)
      use_gh_token=1
      shift
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

if [[ "${use_gh_token}" == "1" ]]; then
  if command -v gh >/dev/null 2>&1; then
    gh_token_candidate="$(gh auth token 2>/dev/null || true)"
    if [[ -n "${gh_token_candidate}" ]]; then
      token="${gh_token_candidate}"
    else
      echo "gh auth token was requested, but no GitHub token is configured in gh." >&2
      exit 2
    fi
  else
    echo "gh is not installed; cannot use --use-gh-token." >&2
    exit 2
  fi
fi

if [[ -z "${token}" ]]; then
  echo "Missing GitHub token. Set YOUSPEED_RELEASE_READ_TOKEN (or GITHUB_RELEASE_TOKEN/GH_TOKEN), or pass --use-gh-token." >&2
  exit 2
fi
if [[ "${token}" == *'$('* || "${token}" == *'${'* || "${token}" == *$'\n'* || "${token}" == *$'\r'* ]]; then
  echo "Refusing to use an unresolved or multiline GitHub token." >&2
  exit 2
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

if [[ "${allow_provisioning_updates}" == "1" ]]; then
  build_cmd+=(
    -allowProvisioningUpdates
    -allowProvisioningDeviceRegistration
  )
fi

echo "Running tests with injected token (length=${#token})."
build_status=0
YOUSPEED_RELEASE_READ_TOKEN="${token}" GITHUB_RELEASE_TOKEN="${token}" "${build_cmd[@]}" || build_status=$?

plist_path="$(find "${derived_data}/Build/Products" -maxdepth 4 -path "*/${scheme}.app/Info.plist" | head -n 1)"
if [[ -z "${plist_path}" || ! -f "${plist_path}" ]]; then
  echo "Unable to locate built app Info.plist under ${derived_data}/Build/Products" >&2
  exit 3
fi

embedded_token="$(/usr/libexec/PlistBuddy -c 'Print :YouSpeedGitHubReleaseToken' "${plist_path}" 2>/dev/null || true)"
if [[ -z "${embedded_token}" ]]; then
  embedded_token="$(/usr/libexec/PlistBuddy -c 'Print :YOUSPEED_RELEASE_READ_TOKEN' "${plist_path}" 2>/dev/null || true)"
fi
if [[ -z "${embedded_token}" ]]; then
  echo "Embedded token missing in ${plist_path}" >&2
  exit 4
fi
if [[ "${embedded_token}" == *'$('* || "${embedded_token}" == *'${'* ]]; then
  echo "Embedded token appears unresolved placeholder in ${plist_path}" >&2
  exit 5
fi
if [[ "${embedded_token}" != "${token}" ]]; then
  echo "Embedded token does not match injected token in ${plist_path} (embedded length=${#embedded_token}, expected length=${#token})." >&2
  exit 6
fi

echo "Verified embedded token in ${plist_path} (length=${#embedded_token})."
if [[ "${build_status}" != "0" ]]; then
  echo "xcodebuild test failed after token verification." >&2
  exit 10
fi
