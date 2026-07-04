#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROJECT_PATH="$ROOT_DIR/iphone/SpeedDBBench.xcodeproj"
SCHEME_NAME="SpeedConsumer"
DEVICE_NAME="${DEVICE_NAME:-iPhone 17 Pro Max}"
DEVICE_ID="${DEVICE_ID:-}"
DERIVED_DATA_PATH="$ROOT_DIR/tmp/ios-store-screenshots-derived-data"
APP_PATH="$DERIVED_DATA_PATH/Build/Products/Debug-iphonesimulator/SpeedConsumer.app"
BUNDLE_ID="de.youspeed.SpeedConsumer"

captures=(
  "01-safe-speed.png:warn-level-0"
  "02-fine-warning.png:warn-level-1"
  "03-points-warning.png:warn-level-2"
  "04-driving-ban-warning.png:warn-level-3"
  "05-pedestrian-zone.png:pedestrian-zone"
  "06-autobahn-unlimited.png:autobahn-unlimited-above-130"
)

locales=(
  "de-DE:de:de_DE"
  "en-US:en:en_US"
  "nl-NL:nl:nl_NL"
  "fr-FR:fr:fr_FR"
)

if [[ -z "$DEVICE_ID" ]]; then
  DEVICE_ID="$(xcrun simctl list devices available | sed -nE "s/^[[:space:]]*$DEVICE_NAME \\(([A-F0-9-]+)\\).*/\\1/p" | head -n 1)"
fi

if [[ -z "$DEVICE_ID" ]]; then
  echo "No available simulator found for DEVICE_NAME=$DEVICE_NAME. Set DEVICE_ID to a simulator UDID." >&2
  exit 1
fi

echo "Booting simulator: $DEVICE_NAME ($DEVICE_ID)"
xcrun simctl boot "$DEVICE_ID" >/dev/null 2>&1 || true
xcrun simctl bootstatus "$DEVICE_ID" -b

echo "Building $SCHEME_NAME for $DEVICE_NAME"
xcodebuild \
  -project "$PROJECT_PATH" \
  -scheme "$SCHEME_NAME" \
  -destination "platform=iOS Simulator,id=$DEVICE_ID" \
  -derivedDataPath "$DERIVED_DATA_PATH" \
  CODE_SIGNING_ALLOWED=NO \
  build >/dev/null

if [[ ! -d "$APP_PATH" ]]; then
  echo "Built app not found at $APP_PATH" >&2
  exit 1
fi

echo "Installing app"
xcrun simctl terminate "$DEVICE_ID" "$BUNDLE_ID" >/dev/null 2>&1 || true
xcrun simctl install "$DEVICE_ID" "$APP_PATH" >/dev/null
xcrun simctl status_bar "$DEVICE_ID" override \
  --time 9:41 \
  --dataNetwork wifi \
  --wifiMode active \
  --wifiBars 3 \
  --cellularMode active \
  --cellularBars 4 \
  --batteryState charged \
  --batteryLevel 100 >/dev/null

for locale in "${locales[@]}"; do
  store_locale="${locale%%:*}"
  rest="${locale#*:}"
  apple_language="${rest%%:*}"
  apple_locale="${rest#*:}"
  output_dir="$ROOT_DIR/store/apple/screenshots/$store_locale/iphone-6.9"
  mkdir -p "$output_dir"

  for capture in "${captures[@]}"; do
    file_name="${capture%%:*}"
    screenshot_state="${capture#*:}"
    output_path="$output_dir/$file_name"

    echo "Capturing $store_locale $file_name"
    xcrun simctl terminate "$DEVICE_ID" "$BUNDLE_ID" >/dev/null 2>&1 || true
    SIMCTL_CHILD_APPLE_LANGUAGES="($apple_language)" \
      SIMCTL_CHILD_APPLE_LOCALE="$apple_locale" \
      SIMCTL_CHILD_YOUSPEED_SCREENSHOT_STATE="$screenshot_state" \
      xcrun simctl launch "$DEVICE_ID" "$BUNDLE_ID" \
        -AppleLanguages "($apple_language)" \
        -AppleLocale "$apple_locale" >/dev/null
    sleep 1.5
    xcrun simctl io "$DEVICE_ID" screenshot "$output_path" >/dev/null
  done
done

xcrun simctl terminate "$DEVICE_ID" "$BUNDLE_ID" >/dev/null 2>&1 || true
xcrun simctl status_bar "$DEVICE_ID" clear >/dev/null 2>&1 || true

echo "Store screenshots written to $ROOT_DIR/store/apple/screenshots"
