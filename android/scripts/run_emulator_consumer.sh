#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<USAGE
Usage:
  $(basename "$0") [--avd NAME] [--lat VALUE] [--lon VALUE] [--skip-build] [--reuse-running] [--save-snapshot NAME] [--screenshot-state VALUE]

Options:
  --avd NAME             AVD name (default: Pixel_API_36)
  --lat VALUE            Latitude (default: 49.0102)
  --lon VALUE            Longitude (default: 8.4266)
  --skip-build           Skip ./gradlew :app:assembleDebug
  --reuse-running        Reuse already running emulator device instead of restarting
  --save-snapshot NAME   Save emulator snapshot at end
  --screenshot-state V   Launch app with screenshot fixture state
  --help                 Show this help
USAGE
}

log() {
  printf '[run-youspeed-emu] %s\n' "$*"
}

fail() {
  printf '[run-youspeed-emu] ERROR: %s\n' "$*" >&2
  exit 1
}

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANDROID_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"

AVD_NAME="${AVD_NAME:-Pixel_API_36}"
LAT="${LAT:-49.0102}"
LON="${LON:-8.4266}"
SKIP_BUILD="${SKIP_BUILD:-0}"
REUSE_RUNNING="${REUSE_RUNNING:-0}"
BOOT_TIMEOUT_SEC="${BOOT_TIMEOUT_SEC:-180}"
SAVE_SNAPSHOT_NAME=""
SCREENSHOT_STATE="${SCREENSHOT_STATE:-}"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --avd)
      AVD_NAME="$2"
      shift 2
      ;;
    --lat)
      LAT="$2"
      shift 2
      ;;
    --lon)
      LON="$2"
      shift 2
      ;;
    --skip-build)
      SKIP_BUILD="1"
      shift
      ;;
    --reuse-running)
      REUSE_RUNNING="1"
      shift
      ;;
    --save-snapshot)
      SAVE_SNAPSHOT_NAME="$2"
      shift 2
      ;;
    --screenshot-state)
      SCREENSHOT_STATE="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      fail "Unknown argument: $1"
      ;;
  esac
done

if [[ -z "${ANDROID_SDK_ROOT:-}" ]]; then
  if [[ -n "${ANDROID_HOME:-}" ]]; then
    ANDROID_SDK_ROOT="$ANDROID_HOME"
  elif [[ -d "$HOME/Library/Android/sdk" ]]; then
    ANDROID_SDK_ROOT="$HOME/Library/Android/sdk"
  else
    fail "ANDROID_SDK_ROOT not set and default SDK path not found"
  fi
fi
export ANDROID_SDK_ROOT

ADB="$ANDROID_SDK_ROOT/platform-tools/adb"
EMU="$ANDROID_SDK_ROOT/emulator/emulator"
APK="$ANDROID_DIR/app/build/outputs/apk/debug/app-debug.apk"
PKG="de.youspeed.android.alpha"
ACTIVITY=".MainActivity"
LOG_FILE="/tmp/youspeed-consumer-emu.log"

[[ -x "$ADB" ]] || fail "adb not found at: $ADB"
[[ -x "$EMU" ]] || fail "emulator not found at: $EMU"
[[ -x "$ANDROID_DIR/gradlew" ]] || fail "gradlew not found in $ANDROID_DIR"

if [[ "$SKIP_BUILD" != "1" ]]; then
  log "Building debug APK"
  (
    cd "$ANDROID_DIR"
    ./gradlew :app:assembleDebug
  )
else
  log "Skipping build (--skip-build)"
fi

[[ -f "$APK" ]] || fail "APK not found: $APK"

log "Starting adb server"
"$ADB" kill-server >/dev/null 2>&1 || true
"$ADB" start-server >/dev/null

existing_device="$("$ADB" devices | awk '/^emulator-[0-9]+[[:space:]]+device$/ {print $1; exit}')"

if [[ "$REUSE_RUNNING" == "1" && -n "$existing_device" ]]; then
  log "Reusing running emulator: $existing_device"
else
  log "Restarting emulator AVD '$AVD_NAME' (cold boot)"
  pkill -f "emulator .* -avd ${AVD_NAME}" >/dev/null 2>&1 || true
  pkill -f "qemu-system-.* -avd ${AVD_NAME}" >/dev/null 2>&1 || true
  nohup "$EMU" -avd "$AVD_NAME" -no-snapshot-load -no-snapshot-save >"$LOG_FILE" 2>&1 &
fi

log "Waiting for emulator device connection (timeout: ${BOOT_TIMEOUT_SEC}s)"
for _ in $(seq 1 "$BOOT_TIMEOUT_SEC"); do
  if "$ADB" devices | grep -Eq '^emulator-[0-9]+[[:space:]]+device$'; then
    break
  fi
  sleep 1
done

if ! "$ADB" devices | grep -Eq '^emulator-[0-9]+[[:space:]]+device$'; then
  tail -n 120 "$LOG_FILE" >&2 || true
  fail "Timed out waiting for emulator device"
fi

log "Waiting for Android boot completion"
"$ADB" wait-for-device
for _ in $(seq 1 "$BOOT_TIMEOUT_SEC"); do
  boot_completed="$("$ADB" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')"
  if [[ "$boot_completed" == "1" ]]; then
    break
  fi
  sleep 1
done

boot_completed="$("$ADB" shell getprop sys.boot_completed 2>/dev/null | tr -d '\r')"
[[ "$boot_completed" == "1" ]] || fail "Timed out waiting for boot completion"

log "Configuring location mode"
"$ADB" shell settings put secure location_mode 3 || true

log "Applying GPS fix: lon=$LON lat=$LAT"
"$ADB" emu geo fix "$LON" "$LAT"

log "Installing APK"
"$ADB" install -r "$APK"

log "Launching app"
"$ADB" shell am force-stop "$PKG" >/dev/null 2>&1 || true
if [[ -n "$SCREENSHOT_STATE" ]]; then
  "$ADB" shell am start -n "$PKG/$ACTIVITY" --es screenshot_state "$SCREENSHOT_STATE" >/dev/null
else
  "$ADB" shell am start -n "$PKG/$ACTIVITY" >/dev/null
fi

if [[ -n "$SAVE_SNAPSHOT_NAME" ]]; then
  log "Saving snapshot: $SAVE_SNAPSHOT_NAME"
  "$ADB" emu avd snapshot save "$SAVE_SNAPSHOT_NAME"
fi

log "Done"
log "German test location set to lat=$LAT lon=$LON"
