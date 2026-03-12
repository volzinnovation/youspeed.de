#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
cd "${repo_root}"

"${repo_root}/scripts/map/prepare_karlsruhe_v3_benchmark_variants.sh"
"${repo_root}/scripts/iphone/generate_xcode_project.sh"

xcodebuild test \
  -project "${repo_root}/iphone/SpeedDBBench.xcodeproj" \
  -scheme SpeedDBBench \
  -destination 'platform=iOS Simulator,name=iPhone 16' \
  -only-testing:SpeedDBBenchTests/SpeedDBBenchTests/testKarlsruheVariantRouteBenchmarksIfPrepared
