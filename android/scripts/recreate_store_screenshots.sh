#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ADB="${ADB:-adb}"
PACKAGE_ID="${PACKAGE_ID:-de.youspeed.android.debug}"

captures=(
  "01-safe-speed.png:warn-level-0"
  "02-fine-warning.png:warn-level-1"
  "03-points-warning.png:warn-level-2"
  "04-driving-ban-warning.png:warn-level-3"
  "05-pedestrian-zone.png:pedestrian-zone"
  "06-autobahn-unlimited.png:autobahn-unlimited-above-130"
)

locales=(
  "de-DE"
  "en-US"
  "nl-NL"
  "fr-FR"
)

cd "$ROOT_DIR/android"
./gradlew :app:installDebug >/dev/null

"$ADB" shell settings put global window_animation_scale 0 >/dev/null
"$ADB" shell settings put global transition_animation_scale 0 >/dev/null
"$ADB" shell settings put global animator_duration_scale 0 >/dev/null

for locale in "${locales[@]}"; do
  output_dir="$ROOT_DIR/store/android/listing/$locale/phone-screenshots"
  mkdir -p "$output_dir"

  "$ADB" shell cmd locale set-app-locales "$PACKAGE_ID" "$locale" >/dev/null 2>&1 || true

  for capture in "${captures[@]}"; do
    file_name="${capture%%:*}"
    screenshot_state="${capture#*:}"
    output_path="$output_dir/$file_name"

    echo "Capturing $locale $file_name"
    "$ADB" shell am force-stop "$PACKAGE_ID" >/dev/null
    "$ADB" shell am start \
      -n "$PACKAGE_ID/de.youspeed.android.alpha.MainActivity" \
      --es screenshot_state "$screenshot_state" >/dev/null
    sleep 1.5
    "$ADB" exec-out screencap -p > "$output_path"
  done
done

echo "Store screenshots written to $ROOT_DIR/store/android/listing/*/phone-screenshots"
