#!/usr/bin/env bash
# Run the offline component benchmark on the explicitly selected Moto g86.
# Does not build, download, clear app data, or install unless --install is supplied.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ANDROID_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_ID="de.youspeed.android.debug"
TEST_ID="${APP_ID}.test"
TEST_CLASS="de.youspeed.android.alpha.RoadPathPerformanceInstrumentedTest"
SERIAL=""
INSTALL=0
ITERATIONS=120
WARMUP=8
RUN_ID="$(date -u +%Y%m%dT%H%M%SZ)-$$"
OUTPUT="$ANDROID_DIR/app/build/reports/road-path/$RUN_ID"

usage() {
  cat <<'USAGE'
Usage: benchmark-road-path.sh [--serial SERIAL] [--install] [--iterations N] [--warmup N]

Requires one online Moto g86, or --serial selecting an online Moto g86.
By default the debug app and test APK must already be installed. --install
updates the existing APKs from app/build/outputs/apk using adb install -r;
it never clears or uninstalls application data. Build both APKs separately:

  ./gradlew --offline :app:assembleDebug :app:assembleDebugAndroidTest

Reports are written under app/build/reports/road-path/ (Git-ignored).
This measures the offline production components on replayed inputs. It does
not certify live CameraX/TSR/recording overhead or sustained thermal behavior.
USAGE
}

while (($#)); do
  case "$1" in
    --serial) SERIAL="${2:?Missing serial}"; shift 2 ;;
    --install) INSTALL=1; shift ;;
    --iterations) ITERATIONS="${2:?Missing iterations}"; shift 2 ;;
    --warmup) WARMUP="${2:?Missing warmup}"; shift 2 ;;
    --help|-h) usage; exit 0 ;;
    *) printf 'Unknown argument: %s\n' "$1" >&2; usage >&2; exit 2 ;;
  esac
done

if [[ ! "$ITERATIONS" =~ ^[0-9]+$ || ! "$WARMUP" =~ ^[0-9]+$ ]] ||
   ((ITERATIONS < 20 || ITERATIONS > 2000 || WARMUP < 1 || WARMUP > 100)); then
  echo "Require 20–2000 iterations and 1–100 warmup samples per fixture." >&2
  exit 2
fi

ADB="${ANDROID_SDK_ROOT:-${ANDROID_HOME:-$HOME/Library/Android/sdk}}/platform-tools/adb"
[[ -x "$ADB" ]] || ADB="$(command -v adb || true)"
[[ -n "$ADB" && -x "$ADB" ]] || { echo "adb is unavailable." >&2; exit 1; }
command -v python3 >/dev/null || { echo "python3 is required to verify the saved report." >&2; exit 1; }

DEVICES="$("$ADB" devices)"
if [[ -z "$SERIAL" ]]; then
  ONLINE_COUNT="$(awk 'NR > 1 && $2 == "device" { n++ } END { print n+0 }' <<<"$DEVICES")"
  if [[ "$ONLINE_COUNT" != 1 ]]; then
    echo "Expected exactly one online Moto g86; connect it or use --serial when several devices are present." >&2
    printf '%s\n' "$DEVICES" >&2
    exit 1
  fi
  SERIAL="$(awk 'NR > 1 && $2 == "device" { print $1 }' <<<"$DEVICES")"
elif ! awk -v selected="$SERIAL" '$1 == selected && $2 == "device" { found=1 } END { exit !found }' <<<"$DEVICES"; then
  echo "Selected device is absent, offline, or unauthorized." >&2
  exit 1
fi
DEVICE_ADB=("$ADB" -s "$SERIAL")
MODEL="$("${DEVICE_ADB[@]}" shell getprop ro.product.model | tr -d '\r')"
MANUFACTURER="$("${DEVICE_ADB[@]}" shell getprop ro.product.manufacturer | tr -d '\r')"
if [[ "$(printf '%s' "$MODEL" | tr '[:upper:]' '[:lower:]')" != *g86* ||
      "$(printf '%s' "$MANUFACTURER" | tr '[:upper:]' '[:lower:]')" != motorola ]]; then
  printf 'Refusing non-Moto-g86 target: %s / %s\n' "$MANUFACTURER" "$MODEL" >&2
  exit 1
fi

mkdir -p "$OUTPUT"
if ((INSTALL)); then
  APP_APK="$ANDROID_DIR/app/build/outputs/apk/debug/app-debug.apk"
  TEST_APK="$ANDROID_DIR/app/build/outputs/apk/androidTest/debug/app-debug-androidTest.apk"
  [[ -f "$APP_APK" && -f "$TEST_APK" ]] || { echo "Build both APKs first; no installation was attempted." >&2; exit 1; }
  "${DEVICE_ADB[@]}" install -r "$APP_APK" > "$OUTPUT/install-app.txt"
  "${DEVICE_ADB[@]}" install -r "$TEST_APK" > "$OUTPUT/install-test.txt"
  shasum -a 256 "$APP_APK" "$TEST_APK" > "$OUTPUT/apk-sha256.txt"
fi
"${DEVICE_ADB[@]}" shell run-as "$APP_ID" pwd > "$OUTPUT/app-access.txt"
"${DEVICE_ADB[@]}" shell pm list instrumentation > "$OUTPUT/instrumentation-installed.txt"
if [[ "$(cat "$OUTPUT/instrumentation-installed.txt")" != *"${TEST_ID}/androidx.test.runner.AndroidJUnitRunner"* ]]; then
  echo "The debug test package is missing. Build it and explicitly use --install to update APKs." >&2
  exit 1
fi
"${DEVICE_ADB[@]}" shell getprop ro.build.fingerprint > "$OUTPUT/device-fingerprint.txt"
"${DEVICE_ADB[@]}" shell dumpsys package "$APP_ID" > "$OUTPUT/installed-app.txt"
"${DEVICE_ADB[@]}" shell dumpsys thermalservice > "$OUTPUT/thermal-before.txt"
"${DEVICE_ADB[@]}" shell dumpsys meminfo "$APP_ID" > "$OUTPUT/memory-before.txt"

set +e
"${DEVICE_ADB[@]}" shell am instrument -w -r \
  -e class "$TEST_CLASS" -e road_path_run_id "$RUN_ID" \
  -e road_path_iterations "$ITERATIONS" -e road_path_warmup "$WARMUP" \
  "${TEST_ID}/androidx.test.runner.AndroidJUnitRunner" > "$OUTPUT/instrumentation.txt" 2>&1
TEST_EXIT=$?
"${DEVICE_ADB[@]}" exec-out run-as "$APP_ID" cat cache/road-path-performance.json > "$OUTPUT/report.json"
REPORT_EXIT=$?
"${DEVICE_ADB[@]}" shell dumpsys thermalservice > "$OUTPUT/thermal-after.txt"
"${DEVICE_ADB[@]}" shell dumpsys meminfo "$APP_ID" > "$OUTPUT/memory-after.txt"
set -e

printf 'Device: %s\nReports: %s\n' "$MODEL" "$OUTPUT"
if ((TEST_EXIT != 0 || REPORT_EXIT != 0)); then
  echo "Instrumentation or report retrieval failed; inspect instrumentation.txt. No performance claim can be made." >&2
  exit 1
fi
python3 - "$OUTPUT/report.json" "$RUN_ID" "$OUTPUT/instrumentation.txt" <<'PY'
import json
import pathlib
import sys

try:
    report = json.loads(pathlib.Path(sys.argv[1]).read_text())
except (OSError, json.JSONDecodeError):
    raise SystemExit("No valid benchmark JSON was produced; inspect instrumentation.txt. No performance claim can be made.")
if report.get("runId") != sys.argv[2]:
    raise SystemExit("Report belongs to a previous run; current run is unverified.")
if not report.get("completed", False):
    raise SystemExit("Current benchmark report is partial; no performance claim can be made.")
transcript = pathlib.Path(sys.argv[3]).read_text()
if "OK (" not in transcript or "FAILURES!!!" in transcript or "INSTRUMENTATION_FAILED" in transcript:
    raise SystemExit("Instrumentation did not pass; inspect the retained report and transcript.")
for fixture in report["fixtures"]:
    stats = fixture["addedComponentsMs"]
    print(f'{fixture["name"]}: p50={stats["p50"]:.3f} ms, p95={stats["p95"]:.3f} ms, '
          f'p99={stats["p99"]:.3f} ms, max={stats["max"]:.3f} ms, '
          f'>200 ms={stats["deadlineMisses"]}/{stats["samples"]}')
if not report.get("componentBudgetPassed", False):
    raise SystemExit("At least one measured component replay exceeded the 200 ms budget.")
print("Component replay passed. Live CameraX/TSR/capture overhead and 30-minute endurance remain unverified.")
PY
