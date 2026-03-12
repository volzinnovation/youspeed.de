#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROJECT_PATH="$ROOT_DIR/iphone/SpeedDBBench.xcodeproj"
SCHEME_NAME="SpeedConsumer"
DEVICE_NAME="${DEVICE_NAME:-iPhone 16}"
DERIVED_DATA_PATH="$ROOT_DIR/tmp/ios-web-screenshots-derived-data"
APP_PATH="$DERIVED_DATA_PATH/Build/Products/Debug-iphonesimulator/SpeedConsumer.app"
OUTPUT_DIR="$ROOT_DIR/Web/assets/screenshots"
BUNDLE_ID="de.youspeed.SpeedConsumer"

captures=(
  "warn-level-0-no-violation.png:warn-level-0"
  "warn-level-1-money.png:warn-level-1"
  "warn-level-2-points.png:warn-level-2"
  "warn-level-3-driving-ban.png:warn-level-3"
  "autobahn-unlimited-over-130.png:autobahn-unlimited-above-130"
)

mkdir -p "$OUTPUT_DIR"

echo "Booting simulator: $DEVICE_NAME"
xcrun simctl boot "$DEVICE_NAME" >/dev/null 2>&1 || true
xcrun simctl bootstatus "$DEVICE_NAME" -b

echo "Building $SCHEME_NAME for $DEVICE_NAME"
xcodebuild \
  -project "$PROJECT_PATH" \
  -scheme "$SCHEME_NAME" \
  -destination "platform=iOS Simulator,name=$DEVICE_NAME" \
  -derivedDataPath "$DERIVED_DATA_PATH" \
  CODE_SIGNING_ALLOWED=NO \
  build >/dev/null

if [[ ! -d "$APP_PATH" ]]; then
  echo "Built app not found at $APP_PATH" >&2
  exit 1
fi

echo "Installing app"
xcrun simctl terminate "$DEVICE_NAME" "$BUNDLE_ID" >/dev/null 2>&1 || true
xcrun simctl install "$DEVICE_NAME" "$APP_PATH" >/dev/null
xcrun simctl status_bar "$DEVICE_NAME" override \
  --time 9:41 \
  --dataNetwork wifi \
  --wifiMode active \
  --wifiBars 3 \
  --cellularMode active \
  --cellularBars 4 \
  --batteryState charged \
  --batteryLevel 100 >/dev/null

for capture in "${captures[@]}"; do
  file_name="${capture%%:*}"
  screenshot_state="${capture#*:}"
  output_path="$OUTPUT_DIR/$file_name"

  echo "Capturing $file_name"
  xcrun simctl terminate "$DEVICE_NAME" "$BUNDLE_ID" >/dev/null 2>&1 || true
  SIMCTL_CHILD_YOUSPEED_SCREENSHOT_STATE="$screenshot_state" \
    xcrun simctl launch "$DEVICE_NAME" "$BUNDLE_ID" >/dev/null
  sleep 1.5
  xcrun simctl io "$DEVICE_NAME" screenshot "$output_path" >/dev/null
done

xcrun simctl terminate "$DEVICE_NAME" "$BUNDLE_ID" >/dev/null 2>&1 || true
xcrun simctl status_bar "$DEVICE_NAME" clear >/dev/null 2>&1 || true

echo "Screenshots written to $OUTPUT_DIR"
