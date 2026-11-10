#!/usr/bin/env bash
set -euo pipefail
if [[ $# -lt 2 || $# -gt 3 ]]; then
  echo "Usage: $0 INPUT_DIRECTORY OUTPUT_DIRECTORY [ADB_SERIAL]" >&2
  exit 2
fi
script_dir=$(cd -- "$(dirname -- "$0")" && pwd)
input_dir=$(cd -- "$1" && pwd)
output_dir=$2
serial=${3:-}
adb_command=(adb)
if [[ -n "$serial" ]]; then adb_command+=(-s "$serial"); fi
package=de.youspeed.classifierbenchmark
apk="$script_dir/app/build/outputs/apk/debug/app-debug.apk"
test -f "$apk"
test -f "$input_dir/manifest.json"
run_id=$(python3 - "$input_dir/manifest.json" <<'PY'
import json,re,sys
d=json.load(open(sys.argv[1])); r=d['runId']
assert d['schemaVersion']==1 and re.fullmatch(r'[a-zA-Z0-9_-]{1,100}',r)
print(r)
PY
)
mkdir -p "$output_dir"
"${adb_command[@]}" get-state
"${adb_command[@]}" shell dumpsys package de.youspeed.android > "$output_dir/production-package-before.txt"
"${adb_command[@]}" install -r "$apk"
"${adb_command[@]}" shell am force-stop "$package"
"${adb_command[@]}" shell am start -W -n "$package/.BenchmarkActivity"
"${adb_command[@]}" push "$input_dir/." "/sdcard/Android/data/$package/files/input/"
remote="/sdcard/Android/data/$package/files/results/$run_id"
if "${adb_command[@]}" shell test -e "$remote"; then
  echo "Run $run_id already exists; choose a new runId." >&2
  exit 2
fi
"${adb_command[@]}" shell am force-stop "$package"
"${adb_command[@]}" shell dumpsys thermalservice > "$output_dir/thermal-before.txt"
"${adb_command[@]}" shell am start -W -n "$package/.BenchmarkActivity" --ez run true
benchmark_pid=$("${adb_command[@]}" shell pidof "$package" | tr -d '\r')
for attempt in $(seq 1 360); do
  if "${adb_command[@]}" shell test -f "$remote/complete.json"; then break; fi
  if "${adb_command[@]}" shell test -f "$remote/failure.json"; then break; fi
  sleep 5
done
"${adb_command[@]}" pull "$remote" "$output_dir/"
if [[ -n "$benchmark_pid" ]]; then
  "${adb_command[@]}" logcat --pid="$benchmark_pid" -d -v threadtime > "$output_dir/$run_id/logcat.txt"
fi
"${adb_command[@]}" shell dumpsys package de.youspeed.android > "$output_dir/production-package-after.txt"
"${adb_command[@]}" shell dumpsys thermalservice > "$output_dir/thermal-after.txt"
python3 - "$output_dir/$run_id" <<'PY'
import json,pathlib,sys
p=pathlib.Path(sys.argv[1]); f=p/'complete.json'
if not f.exists(): raise SystemExit('Run did not complete; inspect preserved failure/progress files')
d=json.load(open(f)); failed=[r for r in d['trials'] if r['status']!='complete']
print(json.dumps({'trials':len(d['trials']),'failed':failed,'results':str(p)}))
if failed: raise SystemExit(1)
PY
