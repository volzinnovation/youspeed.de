#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: build_consumer_app.sh [options]

Build the SpeedConsumer iOS app and optionally inject a GitHub release token at build time.

Options:
  --configuration <Debug|Release>   Build configuration (default: Debug)
  --destination <xcode destination> Xcode destination (default: generic/platform=iOS Simulator)
  --derived-data <path>             DerivedData path (default: iphone/.derived/SpeedConsumerBuild)
  --project <path>                  Xcode project path (default: iphone/SpeedDBBench.xcodeproj)
  --scheme <name>                   Xcode scheme (default: SpeedConsumer)
  --token <value>                   Token value for YOUSPEED_RELEASE_READ_TOKEN build setting
  --use-gh-token                    Resolve token from `gh auth token`
  --allow-empty-token               Allow empty token even for GitHub-hosted manifest URL
  --skip-project-gen                Skip running scripts/iphone/generate_xcode_project.sh
  --clean                           Run xcodebuild clean before build
  --allow-provisioning-updates      Pass -allowProvisioningUpdates and -allowProvisioningDeviceRegistration
  -h, --help                        Show this help text

Environment:
  YOUSPEED_RELEASE_READ_TOKEN       Preferred token source when --token/--use-gh-token are not passed
  GITHUB_RELEASE_TOKEN              Legacy fallback token source
  GH_TOKEN                          Fallback token source if release token vars are not set
EOF
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
configuration="Debug"
destination="generic/platform=iOS Simulator"
derived_data="${repo_root}/iphone/.derived/SpeedConsumerBuild"
project_path="${repo_root}/iphone/SpeedDBBench.xcodeproj"
scheme="SpeedConsumer"
token="${YOUSPEED_RELEASE_READ_TOKEN:-${GITHUB_RELEASE_TOKEN:-}}"
use_gh_token=0
allow_empty_token=0
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
    --token)
      token="${2:-}"
      shift 2
      ;;
    --use-gh-token)
      use_gh_token=1
      shift
      ;;
    --allow-empty-token)
      allow_empty_token=1
      shift
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

if [[ -z "${token}" && -n "${GH_TOKEN:-}" ]]; then
  token="${GH_TOKEN}"
fi

if [[ "${use_gh_token}" == "1" || -z "${token}" ]]; then
  if command -v gh >/dev/null 2>&1; then
    gh_token_candidate="$(gh auth token 2>/dev/null || true)"
    if [[ -n "${gh_token_candidate}" ]]; then
      token="${gh_token_candidate}"
    elif [[ "${use_gh_token}" == "1" ]]; then
      echo "gh auth token was requested, but no GitHub token is configured in gh." >&2
      exit 1
    fi
  elif [[ "${use_gh_token}" == "1" ]]; then
    echo "gh is not installed; cannot use --use-gh-token." >&2
    exit 1
  fi
fi

if [[ "${skip_project_gen}" != "1" ]]; then
  "${repo_root}/scripts/iphone/generate_xcode_project.sh"
fi

manifest_url="$(/usr/libexec/PlistBuddy -c 'Print :YouSpeedV3ManifestURL' "${repo_root}/iphone/SpeedConsumerApp/Info.plist" 2>/dev/null || true)"
manifest_host="$(python3 - <<'PY' "${manifest_url}"
import sys
from urllib.parse import urlparse
url = (sys.argv[1] or "").strip()
if not url:
    print("")
else:
    print((urlparse(url).hostname or "").lower())
PY
)"

if [[ "${allow_empty_token}" != "1" && -z "${token}" ]]; then
  if [[ "${manifest_host}" == "github.com" || "${manifest_host}" == "www.github.com" || "${manifest_host}" == "githubusercontent.com" || "${manifest_host}" == *.githubusercontent.com ]]; then
    echo "Missing YOUSPEED_RELEASE_READ_TOKEN for GitHub-hosted manifest URL: ${manifest_url}" >&2
    echo "Set YOUSPEED_RELEASE_READ_TOKEN (or GITHUB_RELEASE_TOKEN/GH_TOKEN), or pass --token <value>. Use --allow-empty-token only for public assets." >&2
    exit 2
  fi
fi

mkdir -p "${derived_data}"

token_xcconfig=""
cleanup() {
  if [[ -n "${token_xcconfig}" && -f "${token_xcconfig}" ]]; then
    rm -f "${token_xcconfig}"
  fi
}
trap cleanup EXIT

if [[ -n "${token}" ]]; then
  token_xcconfig="$(mktemp "${TMPDIR:-/tmp}/speedconsumer-token.XXXXXX.xcconfig")"
  chmod 600 "${token_xcconfig}"
  cat > "${token_xcconfig}" <<EOF
YOUSPEED_RELEASE_READ_TOKEN = ${token}
GITHUB_RELEASE_TOKEN = \$(YOUSPEED_RELEASE_READ_TOKEN)
EOF
fi

build_cmd=(
  xcodebuild
  -project "${project_path}"
  -scheme "${scheme}"
  -configuration "${configuration}"
  -destination "${destination}"
  -derivedDataPath "${derived_data}"
  build
)
if [[ -n "${token_xcconfig}" ]]; then
  build_cmd+=(
    -xcconfig "${token_xcconfig}"
  )
fi

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
    clean
  )
  if [[ "${allow_provisioning_updates}" == "1" ]]; then
    clean_cmd+=(
      -allowProvisioningUpdates
      -allowProvisioningDeviceRegistration
    )
  fi
  if [[ -n "${token_xcconfig}" ]]; then
    clean_cmd+=(
      -xcconfig "${token_xcconfig}"
    )
  fi
  "${clean_cmd[@]}"
fi

if [[ -n "${token}" ]]; then
  echo "Building with YOUSPEED_RELEASE_READ_TOKEN (length=${#token})."
else
  echo "Building without YOUSPEED_RELEASE_READ_TOKEN."
fi

"${build_cmd[@]}"

echo "Build finished successfully."
echo "DerivedData: ${derived_data}"
find "${derived_data}/Build/Products" -maxdepth 3 -name "${scheme}.app" -print | head -n 5
