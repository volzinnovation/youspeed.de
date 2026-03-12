#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANDROID_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_ID="de.youspeed.android.alpha"
TEST_RUNNER="${APP_ID}.test/androidx.test.runner.AndroidJUnitRunner"
DEVICE_DB_PATH="/data/user/0/${APP_ID}/files/replay/replay_regressions.sqlite"
DEVICE_TRACE_DIR="/data/user/0/${APP_ID}/files/replay/traces"
OUTPUT_DB="${OUTPUT_DB:-$ANDROID_DIR/app/build/replay/replay_regressions.sqlite}"
TRACE_DIR="${TRACE_DIR:-$ANDROID_DIR/app/build/replay/traces}"
SOURCE_ZLIB="${SOURCE_ZLIB:-$ANDROID_DIR/app/src/main/assets/karlsruhe-regbez_speeds.sqlite.zlib}"
LOGS_ROOT="${LOGS_ROOT:-$ANDROID_DIR/../inspector/logs}"

if [[ -z "${ANDROID_SDK_ROOT:-}" ]]; then
  if [[ -n "${ANDROID_HOME:-}" ]]; then
    ANDROID_SDK_ROOT="$ANDROID_HOME"
  elif [[ -d "$HOME/Library/Android/sdk" ]]; then
    ANDROID_SDK_ROOT="$HOME/Library/Android/sdk"
  else
    echo "ANDROID_SDK_ROOT not set and default SDK path not found" >&2
    exit 1
  fi
fi
export ANDROID_SDK_ROOT

ADB="${ANDROID_SDK_ROOT}/platform-tools/adb"

if ! "$ADB" devices | awk '/\tdevice$/ {found=1} END {exit !found}'; then
  echo "No connected Android device or emulator. Start one before running replay regressions." >&2
  exit 1
fi

cd "$ANDROID_DIR"
./gradlew :app:assembleDebug :app:assembleDebugAndroidTest :app:installDebug :app:installDebugAndroidTest

python3 "$SCRIPT_DIR/build_replay_regression_db.py" \
  --source-zlib "$SOURCE_ZLIB" \
  --logs-root "$LOGS_ROOT" \
  --output "$OUTPUT_DB"

python3 "$SCRIPT_DIR/build_replay_trace_bundle.py" \
  --logs-root "$LOGS_ROOT" \
  --output-dir "$TRACE_DIR"

"$ADB" shell "run-as ${APP_ID} mkdir -p files/replay"
"$ADB" shell "run-as ${APP_ID} rm -f files/replay/replay_regressions.sqlite"
"$ADB" shell "run-as ${APP_ID} sh -c 'cat > files/replay/replay_regressions.sqlite'" < "$OUTPUT_DB"

DEVICE_TMP_TRACE_DIR="/data/local/tmp/${APP_ID}_replay_traces"
"$ADB" shell "rm -rf ${DEVICE_TMP_TRACE_DIR} && mkdir -p ${DEVICE_TMP_TRACE_DIR}"
"$ADB" shell "run-as ${APP_ID} sh -c 'rm -rf ${DEVICE_TRACE_DIR} && mkdir -p ${DEVICE_TRACE_DIR}'"
while IFS= read -r local_file; do
  base_name="$(basename "$local_file")"
  "$ADB" push "$local_file" "${DEVICE_TMP_TRACE_DIR}/${base_name}" >/dev/null < /dev/null
  "$ADB" shell "run-as ${APP_ID} cp ${DEVICE_TMP_TRACE_DIR}/${base_name} ${DEVICE_TRACE_DIR}/${base_name}" < /dev/null
done < <(find "$TRACE_DIR" -maxdepth 1 -type f | sort)
"$ADB" shell "rm -rf ${DEVICE_TMP_TRACE_DIR}"

"$ADB" shell am instrument -w -r \
  -e class de.youspeed.android.alpha.V3ReplayInstrumentedTest \
  -e replay_db_path "$DEVICE_DB_PATH" \
  -e replay_trace_dir "$DEVICE_TRACE_DIR" \
  "$TEST_RUNNER"
