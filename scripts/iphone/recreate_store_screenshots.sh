#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
PROJECT_PATH="$ROOT_DIR/iphone/SpeedDBBench.xcodeproj"
SCHEME_NAME="SpeedConsumer"
DEVICE_NAME="${DEVICE_NAME:-iPhone 17 Pro Max}"
DEVICE_ID="${DEVICE_ID:-}"
DERIVED_DATA_PATH="${DERIVED_DATA_PATH:-$ROOT_DIR/tmp/ios-store-screenshots-derived-data}"
APP_PATH="${PREBUILT_APP_PATH:-$DERIVED_DATA_PATH/Build/Products/Debug-iphonesimulator/SpeedConsumer.app}"
CAPTURE_REPORT_DIR="${CAPTURE_REPORT_DIR:-}"
CAPTURE_FILE="${CAPTURE_FILE:-}"
SCREENSHOT_PYTHON="${SCREENSHOT_PYTHON:-python3}"
RAW_CAPTURE_BACKUP_DIR="${RAW_CAPTURE_BACKUP_DIR:-${CAPTURE_REPORT_DIR:-${TMPDIR:-/private/tmp}/youspeed-store-screenshots}/raw-captures-$(date +%Y%m%d-%H%M%S)-$$}"
BUNDLE_ID="de.youspeed.SpeedConsumer"

# Install the declared requirements-screenshots.txt into the selected Python
# environment if needed. The normalizer rejects non-opaque captures and verifies
# identical decoded RGB bytes before saving App Store-compatible RGB PNGs.
"$SCREENSHOT_PYTHON" -c 'from PIL import Image, PngImagePlugin' || {
  echo "Pillow is required; see scripts/iphone/requirements-screenshots.txt." >&2
  exit 1
}

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

if [[ -z "${PREBUILT_APP_PATH:-}" ]]; then
  echo "Building $SCHEME_NAME for $DEVICE_NAME"
  xcodebuild \
    -project "$PROJECT_PATH" \
    -scheme "$SCHEME_NAME" \
    -destination "platform=iOS Simulator,id=$DEVICE_ID" \
    -derivedDataPath "$DERIVED_DATA_PATH" \
    CODE_SIGNING_ALLOWED=NO \
    build >/dev/null
fi

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
  # Replace the obsolete, duplicate German penalty examples. This is a maximum
  # of ten captures per locale/device size, as accepted by App Store Connect.
  if [[ -z "$CAPTURE_FILE" ]]; then
    rm -f "$output_dir/02-fine-warning.png" "$output_dir/03-points-warning.png" \
      "$output_dir/04-driving-ban-warning.png" "$output_dir/05-pedestrian-zone.png" \
      "$output_dir/06-autobahn-unlimited.png"
  fi

  capture() {
    local file_name="$1" screenshot_state="$2" orientation="$3"
    shift 3
    if [[ -n "$CAPTURE_FILE" && "$CAPTURE_FILE" != "$file_name" ]]; then return; fi
    output_path="$output_dir/$file_name"
    echo "Capturing $store_locale $file_name"
    xcrun simctl terminate "$DEVICE_ID" "$BUNDLE_ID" >/dev/null 2>&1 || true
    local child_environment=(
      "SIMCTL_CHILD_APPLE_LANGUAGES=($apple_language)"
      "SIMCTL_CHILD_APPLE_LOCALE=$apple_locale"
      "SIMCTL_CHILD_YOUSPEED_SCREENSHOT_STATE=$screenshot_state"
    )
    local setting
    for setting in "$@"; do
      child_environment+=("SIMCTL_CHILD_$setting")
    done
    env "${child_environment[@]}" xcrun simctl launch "$DEVICE_ID" "$BUNDLE_ID" \
      -AppleLanguages "($apple_language)" -AppleLocale "$apple_locale" \
      -youspeed.screen_orientation "$orientation" >/dev/null
    sleep 2
    xcrun simctl io "$DEVICE_ID" screenshot "$output_path" >/dev/null
    "$SCREENSHOT_PYTHON" "$ROOT_DIR/scripts/iphone/normalize_store_screenshot.py" \
      --backup-root "$RAW_CAPTURE_BACKUP_DIR" "$output_path"
    if [[ -n "$CAPTURE_REPORT_DIR" ]]; then
      local app_data report_name
      app_data="$(xcrun simctl get_app_container "$DEVICE_ID" "$BUNDLE_ID" data)"
      case "$screenshot_state" in
        country-penalty) report_name="country-review.json" ;;
        traffic-sign-pictogram) report_name="sign-review.json" ;;
        *) report_name="" ;;
      esac
      if [[ -n "$report_name" && -f "$app_data/Documents/$report_name" ]]; then
        mkdir -p "$CAPTURE_REPORT_DIR/$store_locale"
        cp "$app_data/Documents/$report_name" "$CAPTURE_REPORT_DIR/$store_locale/${file_name%.png}.json"
      fi
    fi
  }

  capture "01-safe-speed.png" "warn-level-0" "portrait"
  capture "02-camera-speed-limit.png" "camera-limit-active" "portrait"
  capture "03-secondary-sign.png" "traffic-sign-pictogram" "portrait" "YOUSPEED_SCREENSHOT_SIGNS=give_way"
  capture "04-dashcam.png" "camera-limit-active" "portrait" "YOUSPEED_SCREENSHOT_DASHCAM=1"
  capture "05-france-fine.png" "country-penalty" "portrait" \
    "YOUSPEED_SCREENSHOT_COUNTRY=FR" "YOUSPEED_SCREENSHOT_LIMIT=50" "YOUSPEED_SCREENSHOT_DELTA=3" \
    "YOUSPEED_SCREENSHOT_INSIDE_CITY=1" "YOUSPEED_SCREENSHOT_HIGHWAY=residential"
  capture "06-switzerland-fine.png" "country-penalty" "portrait" \
    "YOUSPEED_SCREENSHOT_COUNTRY=CH" "YOUSPEED_SCREENSHOT_LIMIT=50" "YOUSPEED_SCREENSHOT_DELTA=11" \
    "YOUSPEED_SCREENSHOT_INSIDE_CITY=1" "YOUSPEED_SCREENSHOT_HIGHWAY=residential"
  capture "07-belgium-fine.png" "country-penalty" "portrait" \
    "YOUSPEED_SCREENSHOT_COUNTRY=BE" "YOUSPEED_SCREENSHOT_LIMIT=50" "YOUSPEED_SCREENSHOT_DELTA=5" \
    "YOUSPEED_SCREENSHOT_INSIDE_CITY=1" "YOUSPEED_SCREENSHOT_HIGHWAY=residential"
  capture "08-netherlands-fine.png" "country-penalty" "portrait" \
    "YOUSPEED_SCREENSHOT_COUNTRY=NL" "YOUSPEED_SCREENSHOT_LIMIT=50" "YOUSPEED_SCREENSHOT_DELTA=12" \
    "YOUSPEED_SCREENSHOT_INSIDE_CITY=1" "YOUSPEED_SCREENSHOT_HIGHWAY=residential"
  capture "09-pedestrian-zone.png" "pedestrian-zone" "portrait"
  capture "10-autobahn-unlimited.png" "autobahn-unlimited-above-130" "portrait"
done

xcrun simctl terminate "$DEVICE_ID" "$BUNDLE_ID" >/dev/null 2>&1 || true
xcrun simctl status_bar "$DEVICE_ID" clear >/dev/null 2>&1 || true

"${STORE_SCREENSHOT_NODE:-node}" "$ROOT_DIR/scripts/release/generate_store_screenshot_layouts.mjs" apple --capture-source

echo "Store screenshots written to $ROOT_DIR/store/apple/screenshots"
