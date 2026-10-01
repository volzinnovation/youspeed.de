#!/bin/bash
# Native macOS XCTest for the shared lane core. No device or app installation.
set -euo pipefail
cd "$(dirname "$0")/../.."
work=$(mktemp -d "${TMPDIR:-/tmp}/youspeed-lane-tests.XXXXXX")
trap 'rm -rf "$work"' EXIT
names=(RoadBoundaryDetectorTests RoadPathSessionTests RoadBoundaryTemporalTrackerTests RoadBoundaryPresentationGateTests RoadBoundaryMotionHintTests LanePreviewPresentationTests)
files=()
printf 'import XCTest\nlet suite = XCTestSuite(name: "Lane preview")\n' > "$work/main.swift"
for name in "${names[@]}"; do
    sed '/^@testable import SpeedConsumer$/d' "iphone/SpeedConsumerTests/$name.swift" > "$work/$name.swift"
    files+=("$work/$name.swift")
    printf 'suite.addTest(XCTestSuite(forTestCaseClass: %s.self))\n' "$name" >> "$work/main.swift"
done
printf 'suite.run()\nexit(suite.testRun!.hasSucceeded ? 0 : 1)\n' >> "$work/main.swift"
core=()
for name in LaneDetection RoadBoundaryDetector VisualRoadCalibration RoadBoundaryTemporalTracker RoadBoundaryPresentationGate RoadBoundaryMotionHint RoadPathEvidence TrafficSignApplicability RoadPathSession LanePreviewPresentation; do
    core+=("iphone/SpeedConsumerApp/$name.swift")
done
xcode_developer=$(xcode-select -p)
frameworks="$xcode_developer/Platforms/MacOSX.platform/Developer/Library/Frameworks"
libraries="$xcode_developer/Platforms/MacOSX.platform/Developer/usr/lib"
swiftc -O -module-cache-path "$work/cache" -F "$frameworks" -I "$libraries" -L "$libraries" \
    -Xlinker -rpath -Xlinker "$frameworks" -Xlinker -rpath -Xlinker "$libraries" \
    -Xlinker -rpath -Xlinker "$xcode_developer/../SharedFrameworks" \
    "${core[@]}" "${files[@]}" "$work/main.swift" -o "$work/tests"
"$work/tests"
