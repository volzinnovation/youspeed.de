#!/usr/bin/env bash
set -euo pipefail

required_variables=(
  YOUSPEED_ANDROID_RELEASE_STORE_FILE
  YOUSPEED_ANDROID_RELEASE_STORE_PASSWORD
  YOUSPEED_ANDROID_RELEASE_KEY_ALIAS
  YOUSPEED_ANDROID_RELEASE_KEY_PASSWORD
)

for variable in "${required_variables[@]}"; do
  if [[ -z "${!variable:-}" ]]; then
    printf 'Missing required environment variable: %s\n' "$variable" >&2
    exit 1
  fi
done

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
android_dir="$(cd "$script_dir/.." && pwd)"
output_dir="${1:-$android_dir/dist}"
version_name="1.0.4"
base_version_code=10004
abis=(armeabi-v7a arm64-v8a x86 x86_64)

mkdir -p "$output_dir"

for index in "${!abis[@]}"; do
  abi="${abis[$index]}"
  version_code="$((base_version_code * 10 + index + 1))"

  "$android_dir/gradlew" \
    --project-dir "$android_dir" \
    clean assembleRelease \
    "-PyouspeedAbi=$abi"

  source_apk="$android_dir/app/build/outputs/apk/release/app-release.apk"
  destination_apk="$output_dir/YouSpeed-$version_name-$version_code.apk"
  cp "$source_apk" "$destination_apk"
  printf 'Created %s (%s)\n' "$destination_apk" "$abi"
done
