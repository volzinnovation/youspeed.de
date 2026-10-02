#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
ADB="${ADB:-adb}"
PACKAGE_ID="de.youspeed.android.debug"
ANDROID_SERIAL="${ANDROID_SERIAL:-}"

if [[ -z "$ANDROID_SERIAL" ]]; then
  echo 'Set ANDROID_SERIAL to a running emulator (for example emulator-5554).' >&2
  exit 1
fi
if [[ "$ANDROID_SERIAL" != emulator-* ]] || [[ "$("$ADB" -s "$ANDROID_SERIAL" shell getprop ro.kernel.qemu | tr -d '\r')" != 1 ]]; then
  echo 'Store screenshots require an emulator; physical-device installation is disabled.' >&2
  exit 1
fi
adb_target() { "$ADB" -s "$ANDROID_SERIAL" "$@"; }

# The Play phone gallery permits eight images. Use the current app's real UI
# with deterministic debug fixtures; no camera, recording, or upload is started.
captures=(
  "01-safe-speed.png:warn-level-0"
  "02-dashcam.png:camera-limit-active:dashcam"
  "03-camera-recognition.png:camera-limit-active"
  "04-traffic-signs.png:other-sign-give-way"
  "05-france-fine.png:warn-level-0:FRA:3"
  "06-switzerland-fine.png:warn-level-0:CHE:11"
  "07-belgium-fine.png:warn-level-0:BEL:5"
  "08-netherlands-fine.png:warn-level-0:NLD:12"
)
capture_kind="${SCREENSHOT_CAPTURE_KIND:-all}"
if [[ "$capture_kind" == dashcam ]]; then
  captures=("02-dashcam.png:camera-limit-active:dashcam")
elif [[ "$capture_kind" == netherlands ]]; then
  captures=("08-netherlands-fine.png:warn-level-0:NLD:12")
elif [[ "$capture_kind" == country-examples ]]; then
  captures=("05-france-fine.png:warn-level-0:FRA:3" "06-switzerland-fine.png:warn-level-0:CHE:11"
    "07-belgium-fine.png:warn-level-0:BEL:5" "08-netherlands-fine.png:warn-level-0:NLD:12")
elif [[ "$capture_kind" != all ]]; then
  echo 'SCREENSHOT_CAPTURE_KIND must be all, dashcam, netherlands or country-examples.' >&2
  exit 1
fi
dashcam_orientation="${DASHCAM_SCREENSHOT_ORIENTATION:-landscape_camera_upper_left}"
if [[ "$dashcam_orientation" != portrait && "$dashcam_orientation" != landscape_camera_upper_left ]]; then
  echo 'DASHCAM_SCREENSHOT_ORIENTATION must be portrait or landscape_camera_upper_left.' >&2
  exit 1
fi
locales=(de-DE en-US fr-FR nl-NL es-ES it-IT pl-PL pt-BR sv-SE)
if [[ -n "${SCREENSHOT_LOCALES:-}" ]]; then
  read -r -a locales <<< "$SCREENSHOT_LOCALES"
fi

if [[ "${SKIP_BUILD:-0}" != 1 ]]; then
  "$ROOT_DIR/android/gradlew" --project-dir "$ROOT_DIR/android" --offline :app:assembleDebug >/dev/null
fi
apk_path="$ROOT_DIR/android/app/build/outputs/apk/debug/app-debug.apk"
[[ -f "$apk_path" ]] || { echo "Missing debug APK: $apk_path" >&2; exit 1; }
adb_target install -r "$apk_path" >/dev/null

animation_keys=(window_animation_scale transition_animation_scale animator_duration_scale)
animation_values=()
for key in "${animation_keys[@]}"; do
  animation_values+=("$(adb_target shell settings get global "$key" | tr -d '\r')")
done
original_locale="$(adb_target shell cmd locale get-app-locales "$PACKAGE_ID" | sed -n 's/.*\[\(.*\)\].*/\1/p' | tr -d '\r ')"
[[ "$original_locale" =~ ^[A-Za-z0-9,-]*$ ]] || { echo 'Unexpected original locale value.' >&2; exit 1; }
set_app_locale() {
  [[ "$1" =~ ^[A-Za-z0-9,-]*$ ]] || { echo 'Invalid screenshot locale.' >&2; return 1; }
  # Pass one shell command so the empty locale list survives adb argument joining.
  adb_target shell "cmd locale set-app-locales $PACKAGE_ID --locales '$1'" >/dev/null
}
staging_dir="$(mktemp -d "${TMPDIR:-/tmp}/youspeed-android-screenshots.XXXXXX")"
ui_dump_path="/sdcard/youspeed-store-capture-ui-$$.xml"
chmod 700 "$staging_dir"
adb_target shell am force-stop "$PACKAGE_ID" >/dev/null
# Use the app's existing orientation preference, and restore its original bytes
# afterwards. Keep debug preferences private; they may contain account state.
preference_files=(youspeed.xml youspeed.xml.bak)
preference_present=()
for preference in "${preference_files[@]}"; do
  if adb_target shell run-as "$PACKAGE_ID" test -f "shared_prefs/$preference"; then
    preference_present+=(1)
    adb_target exec-out run-as "$PACKAGE_ID" cat "shared_prefs/$preference" > "$staging_dir/$preference"
    chmod 600 "$staging_dir/$preference"
  else
    preference_present+=(0)
  fi
done
write_preferences() {
  adb_target shell run-as "$PACKAGE_ID" mkdir -p shared_prefs
  adb_target shell "run-as $PACKAGE_ID sh -c 'cat > shared_prefs/$1'" < "$2"
}
set_orientation() {
  python3 - "$staging_dir/youspeed.xml" "$staging_dir/orientation.xml" "$1" <<'PYPREF'
import sys,xml.etree.ElementTree as ET
from pathlib import Path
source,output,orientation=Path(sys.argv[1]),Path(sys.argv[2]),sys.argv[3]
root=ET.fromstring(source.read_bytes()) if source.exists() else ET.Element('map')
for entry in list(root):
    if entry.get('name')=='youspeed.manual_orientation': root.remove(entry)
ET.SubElement(root,'string',{'name':'youspeed.manual_orientation'}).text=orientation
output.write_bytes(ET.tostring(root,encoding='utf-8',xml_declaration=True))
output.chmod(0o600)
PYPREF
  adb_target shell run-as "$PACKAGE_ID" rm -f shared_prefs/youspeed.xml.bak
  write_preferences youspeed.xml "$staging_dir/orientation.xml"
}
restore() {
  adb_target shell am force-stop "$PACKAGE_ID" >/dev/null 2>&1 || true
  for index in "${!preference_files[@]}"; do
    preference="${preference_files[$index]}"
    if [[ "${preference_present[$index]}" == 1 ]]; then
      write_preferences "$preference" "$staging_dir/$preference" >/dev/null 2>&1 || true
    else
      adb_target shell run-as "$PACKAGE_ID" rm -f "shared_prefs/$preference" >/dev/null 2>&1 || true
    fi
  done
  set_app_locale "$original_locale" >/dev/null 2>&1 || true
  for index in "${!animation_keys[@]}"; do
    if [[ "${animation_values[$index]}" == null ]]; then
      adb_target shell settings delete global "${animation_keys[$index]}" >/dev/null 2>&1 || true
    else
      adb_target shell settings put global "${animation_keys[$index]}" "${animation_values[$index]}" >/dev/null 2>&1 || true
    fi
  done
  rm -rf "$staging_dir"
  adb_target shell rm -f "$ui_dump_path" >/dev/null 2>&1 || true
}
trap restore EXIT
for key in "${animation_keys[@]}"; do
  adb_target shell settings put global "$key" 0 >/dev/null
done

for locale in "${locales[@]}"; do
  locale_staging="$staging_dir/$locale"
  mkdir -p "$locale_staging"
  set_app_locale "$locale"
  for capture in "${captures[@]}"; do
    IFS=: read -r file_name screenshot_state scenario delta <<< "$capture"
    launch=(-n "$PACKAGE_ID/de.youspeed.android.alpha.MainActivity" --es screenshot_state "$screenshot_state")
    if [[ "${scenario:-}" == dashcam ]]; then
      launch+=(--ez screenshot_dashcam true)
    elif [[ -n "${scenario:-}" ]]; then
      launch+=(--es screenshot_country "$scenario" --ei screenshot_delta "$delta" --ei screenshot_limit 50
        --ez screenshot_inside_city true --es screenshot_highway residential)
    fi
    echo "Capturing $locale $file_name"
    adb_target shell am force-stop "$PACKAGE_ID" >/dev/null
    if [[ "${scenario:-}" == dashcam ]]; then
      set_orientation "$dashcam_orientation"
    else
      set_orientation portrait
    fi
    # A cold launch on a busy emulator may take several seconds; wait for the
    # Activity's first frame before the additional Compose settling interval.
    adb_target shell am start -W "${launch[@]}" >/dev/null
    sleep 2
    # A successful launch can still leave the system splash visible. Country
    # examples must expose a monetary unit before entering the upload gallery.
    if [[ -n "${scenario:-}" && "$scenario" != dashcam ]]; then
      ready=0
      for attempt in {1..6}; do
        adb_target shell uiautomator dump "$ui_dump_path" >/dev/null 2>&1
        ui_tree="$(adb_target shell cat "$ui_dump_path")"
        if [[ "$scenario" == CHE && "$ui_tree" == *CHF* ]] ||
           [[ "$scenario" != CHE && "$ui_tree" == *EUR* ]]; then
          ready=1
          break
        fi
        sleep 2
      done
      [[ "$ready" == 1 ]] || { echo "Country screen did not settle: $locale $file_name" >&2; exit 1; }
    fi
    adb_target exec-out screencap -p > "$locale_staging/$file_name"
    python3 - "$locale_staging/$file_name" <<'PYPNG'
import struct,sys
from pathlib import Path
raw=Path(sys.argv[1]).read_bytes()
assert raw[:8]==b'\x89PNG\r\n\x1a\n', 'Invalid PNG screenshot'
w,h=struct.unpack('>II', raw[16:24])
assert min(w,h)>=320 and max(w,h)<=3840 and max(w,h)<=2*min(w,h), f'Invalid Play screenshot dimensions: {w}x{h}'
PYPNG
  done
  output_dir="$ROOT_DIR/store/android/listing/$locale/phone-screenshots"
  mkdir -p "$output_dir"
  # Replace only the known old gallery files after every new image is valid.
  if [[ "$capture_kind" == all ]]; then
    for old in 01-safe-speed.png 02-fine-warning.png 03-points-warning.png 04-driving-ban-warning.png 05-pedestrian-zone.png 06-autobahn-unlimited.png; do
      rm -f "$output_dir/$old"
    done
  fi
  rm -f "$output_dir/08-netherlands-warning.png"
  cp "$locale_staging/"*.png "$output_dir/"
  fastlane_dir="$ROOT_DIR/fastlane/metadata/android/$locale/images/phoneScreenshots"
  mkdir -p "$fastlane_dir"
  if [[ "$capture_kind" == all ]]; then
    for old in 01-safe-speed.png 02-fine-warning.png 03-points-warning.png 04-driving-ban-warning.png 05-pedestrian-zone.png 06-autobahn-unlimited.png; do
      rm -f "$fastlane_dir/$old"
    done
  fi
  rm -f "$fastlane_dir/08-netherlands-warning.png"
  cp "$locale_staging/"*.png "$fastlane_dir/"
done

layout_locales="$(IFS=,; echo "${locales[*]}")"
"${STORE_SCREENSHOT_NODE:-node}" "$ROOT_DIR/scripts/release/generate_store_screenshot_layouts.mjs" android --capture-source "--locales=$layout_locales"

echo "Store screenshots written to $ROOT_DIR/store/android/listing/*/phone-screenshots"
