#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage: archive_consumer_appstore.sh [options]

Archive SpeedConsumer for App Store Connect with mandatory GitHub release token
injection, then verify the token survived in the .xcarchive and exported .ipa.

Options:
  --configuration <name>             Build configuration (default: Release)
  --derived-data <path>              DerivedData path (default: iphone/.derived/SpeedConsumerAppStore/DerivedData)
  --archive-path <path>              Archive path (default: iphone/.derived/SpeedConsumerAppStore/SpeedConsumer.xcarchive)
  --export-path <path>               IPA export path (default: iphone/.derived/SpeedConsumerAppStore/export)
  --export-options <path>            ExportOptions.plist path (default: generated temporary plist)
  --project <path>                   Xcode project path (default: iphone/SpeedDBBench.xcodeproj)
  --scheme <name>                    Xcode scheme/product name (default: SpeedConsumer)
  --token <value>                    Token value for YOUSPEED_RELEASE_READ_TOKEN
  --use-gh-token                     Resolve token from `gh auth token`
  --no-gh-token-fallback             Do not fall back to `gh auth token` when env token vars are unset
  --skip-export                      Create and verify .xcarchive only
  --skip-project-gen                 Skip scripts/iphone/generate_xcode_project.sh
  --allow-provisioning-updates       Pass provisioning update flags to xcodebuild
  --keep-existing                    Do not remove the previous archive/export directory first
  -h, --help                         Show this help text

Environment:
  YOUSPEED_RELEASE_READ_TOKEN        Preferred token source
  GITHUB_RELEASE_TOKEN               Legacy fallback token source
  GH_TOKEN                           Fallback token source before gh auth lookup
  DEVELOPMENT_TEAM                   Optional export team override
EOF
}

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
configuration="Release"
derived_root="${repo_root}/iphone/.derived/SpeedConsumerAppStore"
derived_data="${derived_root}/DerivedData"
archive_path="${derived_root}/SpeedConsumer.xcarchive"
export_path="${derived_root}/export"
export_options=""
project_path="${repo_root}/iphone/SpeedDBBench.xcodeproj"
scheme="SpeedConsumer"
token="${YOUSPEED_RELEASE_READ_TOKEN:-${GITHUB_RELEASE_TOKEN:-${GH_TOKEN:-}}}"
use_gh_token=0
gh_token_fallback=1
skip_export=0
skip_project_gen=0
allow_provisioning_updates=0
keep_existing=0
expected_bundle_id="de.youspeed.SpeedConsumer"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --configuration)
      configuration="${2:-}"
      shift 2
      ;;
    --derived-data)
      derived_data="${2:-}"
      shift 2
      ;;
    --archive-path)
      archive_path="${2:-}"
      shift 2
      ;;
    --export-path)
      export_path="${2:-}"
      shift 2
      ;;
    --export-options)
      export_options="${2:-}"
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
    --no-gh-token-fallback)
      gh_token_fallback=0
      shift
      ;;
    --skip-export)
      skip_export=1
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
    --keep-existing)
      keep_existing=1
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

if [[ -z "${configuration}" || -z "${derived_data}" || -z "${archive_path}" || -z "${project_path}" || -z "${scheme}" ]]; then
  echo "Missing required option value." >&2
  usage >&2
  exit 1
fi
if [[ "${skip_export}" != "1" && -z "${export_path}" ]]; then
  echo "Missing --export-path value." >&2
  exit 1
fi

resolve_gh_token() {
  if ! command -v gh >/dev/null 2>&1; then
    return 1
  fi
  gh auth token 2>/dev/null || true
}

if [[ "${use_gh_token}" == "1" || ( -z "${token}" && "${gh_token_fallback}" == "1" ) ]]; then
  gh_token_candidate="$(resolve_gh_token)"
  if [[ -n "${gh_token_candidate}" ]]; then
    token="${gh_token_candidate}"
  elif [[ "${use_gh_token}" == "1" ]]; then
    echo "gh auth token was requested, but no GitHub token is configured in gh." >&2
    exit 2
  fi
fi

if [[ -z "${token}" ]]; then
  echo "Missing GitHub token. Set YOUSPEED_RELEASE_READ_TOKEN (or GITHUB_RELEASE_TOKEN/GH_TOKEN), or configure gh auth." >&2
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
mkdir -p "$(dirname "${archive_path}")"
if [[ "${skip_export}" != "1" ]]; then
  mkdir -p "$(dirname "${export_path}")"
fi

temp_files=()
temp_dirs=()
cleanup() {
  for file in "${temp_files[@]}"; do
    rm -f "${file}"
  done
  for dir in "${temp_dirs[@]}"; do
    rm -rf "${dir}"
  done
}
trap cleanup EXIT

plist_value() {
  local plist_path="$1"
  local key="$2"
  /usr/libexec/PlistBuddy -c "Print :${key}" "${plist_path}" 2>/dev/null || true
}

verify_token_plist() {
  local plist_path="$1"
  local label="$2"
  if [[ ! -f "${plist_path}" ]]; then
    echo "Missing ${label} Info.plist at ${plist_path}" >&2
    exit 3
  fi

  local embedded_token
  embedded_token="$(plist_value "${plist_path}" "YouSpeedGitHubReleaseToken")"
  if [[ -z "${embedded_token}" ]]; then
    embedded_token="$(plist_value "${plist_path}" "YOUSPEED_RELEASE_READ_TOKEN")"
  fi
  embedded_token="${embedded_token#"${embedded_token%%[![:space:]]*}"}"
  embedded_token="${embedded_token%"${embedded_token##*[![:space:]]}"}"

  if [[ -z "${embedded_token}" ]]; then
    echo "Embedded GitHub token missing in ${label} (${plist_path})." >&2
    exit 4
  fi
  if [[ "${embedded_token}" == *'$('* || "${embedded_token}" == *'${'* ]]; then
    echo "Embedded GitHub token is still an unresolved placeholder in ${label} (${plist_path})." >&2
    exit 5
  fi
  if [[ "${embedded_token}" != "${token}" ]]; then
    echo "Embedded GitHub token in ${label} does not match the injected token (embedded length=${#embedded_token}, expected length=${#token})." >&2
    exit 6
  fi

  echo "Verified GitHub token in ${label} (length=${#embedded_token})."
}

verify_bundle_id() {
  local plist_path="$1"
  local label="$2"
  local actual_bundle_id
  actual_bundle_id="$(plist_value "${plist_path}" "CFBundleIdentifier")"
  if [[ "${actual_bundle_id}" != "${expected_bundle_id}" ]]; then
    echo "Unexpected bundle id in ${label}: ${actual_bundle_id:-<missing>} (expected ${expected_bundle_id})." >&2
    exit 7
  fi
}

archive_cmd=(
  xcodebuild
  archive
  -project "${project_path}"
  -scheme "${scheme}"
  -configuration "${configuration}"
  -destination "generic/platform=iOS"
  -derivedDataPath "${derived_data}"
  -archivePath "${archive_path}"
  -hideShellScriptEnvironment
)
if [[ "${allow_provisioning_updates}" == "1" ]]; then
  archive_cmd+=(
    -allowProvisioningUpdates
    -allowProvisioningDeviceRegistration
  )
fi

if [[ "${keep_existing}" != "1" ]]; then
  rm -rf "${archive_path}"
  if [[ "${skip_export}" != "1" ]]; then
    rm -rf "${export_path}"
  fi
fi

echo "Archiving ${scheme} for App Store Connect with embedded GitHub token (length=${#token})."
YOUSPEED_RELEASE_READ_TOKEN="${token}" GITHUB_RELEASE_TOKEN="${token}" "${archive_cmd[@]}"

archive_plist="${archive_path}/Products/Applications/${scheme}.app/Info.plist"
verify_bundle_id "${archive_plist}" ".xcarchive"
verify_token_plist "${archive_plist}" ".xcarchive"

short_version="$(plist_value "${archive_plist}" "CFBundleShortVersionString")"
build_version="$(plist_value "${archive_plist}" "CFBundleVersion")"
echo "Archive verified: ${archive_path}"
echo "Version: ${short_version:-unknown} (${build_version:-unknown})"

if [[ "${skip_export}" == "1" ]]; then
  exit 0
fi

export_options_to_use="${export_options}"
if [[ -z "${export_options_to_use}" ]]; then
  export_options_to_use="$(mktemp "${TMPDIR:-/tmp}/speedconsumer-export-options.XXXXXX.plist")"
  temp_files+=("${export_options_to_use}")
  team_id="${DEVELOPMENT_TEAM:-}"
  if [[ -z "${team_id}" ]]; then
    team_id="$(awk '/^[[:space:]]*DEVELOPMENT_TEAM:[[:space:]]*/ { sub(/^[[:space:]]*DEVELOPMENT_TEAM:[[:space:]]*/, "", $0); print $0; exit }' "${repo_root}/iphone/project.yml")"
  fi
  {
    printf '%s\n' '<?xml version="1.0" encoding="UTF-8"?>'
    printf '%s\n' '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">'
    printf '%s\n' '<plist version="1.0">'
    printf '%s\n' '<dict>'
    printf '%s\n' '  <key>method</key>'
    printf '%s\n' '  <string>app-store-connect</string>'
    printf '%s\n' '  <key>destination</key>'
    printf '%s\n' '  <string>export</string>'
    printf '%s\n' '  <key>signingStyle</key>'
    printf '%s\n' '  <string>automatic</string>'
    printf '%s\n' '  <key>manageAppVersionAndBuildNumber</key>'
    printf '%s\n' '  <false/>'
    printf '%s\n' '  <key>stripSwiftSymbols</key>'
    printf '%s\n' '  <true/>'
    printf '%s\n' '  <key>uploadSymbols</key>'
    printf '%s\n' '  <true/>'
    if [[ -n "${team_id}" ]]; then
      printf '%s\n' '  <key>teamID</key>'
      printf '  <string>%s</string>\n' "${team_id}"
    fi
    printf '%s\n' '</dict>'
    printf '%s\n' '</plist>'
  } > "${export_options_to_use}"
fi

export_cmd=(
  xcodebuild
  -exportArchive
  -archivePath "${archive_path}"
  -exportPath "${export_path}"
  -exportOptionsPlist "${export_options_to_use}"
)
if [[ "${allow_provisioning_updates}" == "1" ]]; then
  export_cmd+=(
    -allowProvisioningUpdates
  )
fi

echo "Exporting App Store Connect IPA."
"${export_cmd[@]}"

ipa_path="$(find "${export_path}" -maxdepth 2 -name "*.ipa" -print | head -n 1)"
if [[ -z "${ipa_path}" ]]; then
  echo "No .ipa was exported under ${export_path}." >&2
  exit 8
fi

payload_dir="$(mktemp -d "${TMPDIR:-/tmp}/speedconsumer-ipa.XXXXXX")"
temp_dirs+=("${payload_dir}")
unzip -q "${ipa_path}" "Payload/${scheme}.app/Info.plist" -d "${payload_dir}"
ipa_plist="${payload_dir}/Payload/${scheme}.app/Info.plist"
verify_bundle_id "${ipa_plist}" ".ipa"
verify_token_plist "${ipa_plist}" ".ipa"

echo "Export verified: ${ipa_path}"
