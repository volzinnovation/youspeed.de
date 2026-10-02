#!/usr/bin/env bash
set -euo pipefail

android_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
unsigned=0
if [[ "${1:-}" == --unsigned ]]; then
  unsigned=1
  shift
fi
if [[ $# -gt 1 || "${1:-}" == --* ]]; then
  echo 'Usage: prepare-play-release.sh [--unsigned] [output-directory]' >&2
  exit 1
fi
output_dir="${1:-$android_dir/app/build/play-release}"
if [[ "$unsigned" == 0 ]]; then
  for variable in YOUSPEED_ANDROID_RELEASE_STORE_FILE YOUSPEED_ANDROID_RELEASE_STORE_PASSWORD YOUSPEED_ANDROID_RELEASE_KEY_ALIAS YOUSPEED_ANDROID_RELEASE_KEY_PASSWORD; do
    if [[ -z "${!variable:-}" ]]; then
      printf 'Missing signing configuration: %s. Use --unsigned for local preparation.\n' "$variable" >&2
      exit 1
    fi
  done
  [[ -f "$YOUSPEED_ANDROID_RELEASE_STORE_FILE" ]] || { echo 'Configured upload keystore was not found.' >&2; exit 1; }
else
  # --unsigned is explicit even when a signing environment is present.
  unset YOUSPEED_ANDROID_RELEASE_STORE_FILE YOUSPEED_ANDROID_RELEASE_STORE_PASSWORD YOUSPEED_ANDROID_RELEASE_KEY_ALIAS YOUSPEED_ANDROID_RELEASE_KEY_PASSWORD
fi

mkdir -p "$output_dir"
"$android_dir/gradlew" --project-dir "$android_dir" --offline \
  :app:testDebugUnitTest :app:testReleaseUnitTest :app:lintRelease :app:bundleRelease
cp "$android_dir/app/build/outputs/bundle/release/app-release.aab" "$output_dir/YouSpeed-release.aab"
python3 "$android_dir/scripts/audit-release-artifact.py" "$output_dir/YouSpeed-release.aab" \
  --output "$output_dir/artifact-audit.json"

if [[ "$unsigned" == 1 ]]; then
  echo "Local unsigned preparation artifact: $output_dir/YouSpeed-release.aab"
  echo 'Signing and the remaining release gates must be completed before upload.'
else
  jarsigner -verify "$output_dir/YouSpeed-release.aab" > "$output_dir/signature-verification.txt"
  if ! rg -q 'jar verified' "$output_dir/signature-verification.txt"; then
    echo 'Release bundle signature verification failed.' >&2
    exit 1
  fi
  echo "Signed local artifact: $output_dir/YouSpeed-release.aab"
fi
# This command performs local preparation only. It never installs or uploads.
echo "Native audit: $output_dir/artifact-audit.json; test 16 KB runtime compatibility separately."
