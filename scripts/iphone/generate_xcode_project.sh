#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
iphone_dir="${repo_root}/iphone"
spec="${iphone_dir}/project.yml"

if [[ ! -f "${spec}" ]]; then
  echo "Missing XcodeGen spec: ${spec}" >&2
  exit 1
fi

if ! command -v xcodegen >/dev/null 2>&1; then
  echo "xcodegen is required but not found in PATH" >&2
  exit 1
fi

echo "Generating Xcode project from ${spec}" >&2
spec_team="$(awk '/^[[:space:]]*DEVELOPMENT_TEAM:[[:space:]]*/ { sub(/^[[:space:]]*DEVELOPMENT_TEAM:[[:space:]]*/, "", $0); print $0; exit }' "${spec}")"
effective_team="${DEVELOPMENT_TEAM:-${spec_team:-}}"

if [[ -n "${effective_team}" ]]; then
  if [[ -n "${DEVELOPMENT_TEAM:-}" ]]; then
    echo "Using DEVELOPMENT_TEAM=${effective_team} (from environment)." >&2
  else
    echo "Using DEVELOPMENT_TEAM=${effective_team} (from project.yml)." >&2
  fi
else
  echo "No DEVELOPMENT_TEAM set (project will require selecting team in Xcode)." >&2
fi
xcodegen generate --spec "${spec}" --project "${iphone_dir}"
echo "Generated: ${iphone_dir}/SpeedDBBench.xcodeproj"
