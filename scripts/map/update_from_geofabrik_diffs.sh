#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<USAGE
Usage: $0 --region <region_name> --input-pbf <path> [options]

Incrementally updates an existing regional OSM PBF using Geofabrik replication diffs
(and optionally exports a merged delta file for the applied sequence range).

Required:
  --region <name>                Logical region label (e.g. germany)
  --input-pbf <path>             Existing local OSM PBF to update in place

Options:
  --updates-url <url>            Replication base URL (default: from PBF header,
                                 else germany fallback URL for --region germany)
  --state-file <path>            Persistent state JSON (default:
                                 mapdata/raw/<region>.diff_state.json)
  --report-path <path>           Per-run report JSON (default:
                                 mapdata/reports/diff_update.<region>.<timestamp>.json)
  --work-dir <dir>               Work directory for logs/temp files (default:
                                 mapdata/build/<region>/updates)
  --size-mb <int>                Max diff size passed to pyosmium tools (default: 1024)
  --socket-timeout <sec>         Download timeout for pyosmium tools (default: 120)
  --tmpdir <dir>                 Temp dir for pyosmium-up-to-date
  --delta-out <path>             Explicit output path for merged delta .osc.gz
  --emit-delta                   Export merged delta for applied seq range (default)
  --no-emit-delta                Disable delta export
  --dry-run                      Fetch state + write report without changing PBF
  --ignore-osmosis-headers       Force pyosmium to ignore existing replication headers
  --force-update-of-old-planet   Pass through to pyosmium-up-to-date
  -h, --help                     Show this help message

Examples:
  $0 --region germany \
     --input-pbf mapdata/raw/germany-latest.osm.pbf

  $0 --region germany \
     --input-pbf mapdata/raw/germany-latest.osm.pbf \
     --updates-url https://download.geofabrik.de/europe/germany-updates/ \
     --report-path mapdata/reports/diff_update.germany.json
USAGE
}

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    echo "Missing required command: $cmd" >&2
    exit 1
  fi
}

is_int() {
  [[ "${1:-}" =~ ^[0-9]+$ ]]
}

ensure_trailing_slash() {
  local v="$1"
  if [[ "$v" == */ ]]; then
    printf "%s" "$v"
  else
    printf "%s/" "$v"
  fi
}

read_pbf_header_json() {
  local pbf_path="$1"
  python3 - "$pbf_path" <<'PY'
import json
import sys

path = sys.argv[1]
out = {
    "sequence_number": None,
    "timestamp": None,
    "base_url": None,
    "error": None,
}

try:
    import osmium
except Exception as exc:
    out["error"] = f"pyosmium import failed: {exc}"
    print(json.dumps(out))
    raise SystemExit(0)

try:
    reader = osmium.io.Reader(path)
    header = reader.header()
    reader.close()

    def _get(key):
        try:
            val = header.get(key)
            return val if val not in ("", None) else None
        except Exception:
            return None

    seq = _get("osmosis_replication_sequence_number")
    out["sequence_number"] = int(seq) if seq is not None else None
    out["timestamp"] = _get("osmosis_replication_timestamp")
    base_url = _get("osmosis_replication_base_url")
    if base_url and not base_url.endswith("/"):
        base_url += "/"
    out["base_url"] = base_url
except Exception as exc:
    out["error"] = str(exc)

print(json.dumps(out))
PY
}

fetch_server_state() {
  local state_url="$1"
  local out_file="$2"
  curl -L --fail --silent --show-error "$state_url" -o "$out_file"
}

parse_server_state_json() {
  local state_txt="$1"
  python3 - "$state_txt" <<'PY'
import json
import re
import sys
from pathlib import Path

text = Path(sys.argv[1]).read_text(encoding="utf-8", errors="replace")
seq = None
ts = None
for line in text.splitlines():
    if line.startswith("sequenceNumber="):
        raw = line.split("=", 1)[1].strip()
        if re.fullmatch(r"\d+", raw):
            seq = int(raw)
    elif line.startswith("timestamp="):
        ts = line.split("=", 1)[1].strip()
print(json.dumps({"sequence_number": seq, "timestamp": ts}))
PY
}

read_state_fallback_json() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    echo '{"last_applied_seq":null,"last_applied_timestamp":null,"last_updates_url":null}'
    return
  fi
  python3 - "$path" <<'PY'
import json
import sys
from pathlib import Path

try:
    payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
except Exception:
    payload = {}

out = {
    "last_applied_seq": payload.get("last_applied_seq"),
    "last_applied_timestamp": payload.get("last_applied_timestamp"),
    "last_updates_url": payload.get("updates_url") or payload.get("last_updates_url"),
}
print(json.dumps(out))
PY
}

count_delta_entities_json() {
  local delta_path="$1"
  python3 - "$delta_path" <<'PY'
import gzip
import json
import re
import sys
from pathlib import Path

p = Path(sys.argv[1])
out = {
    "node_count": None,
    "way_count": None,
    "relation_count": None,
    "total_entities": None,
    "create_count": None,
    "modify_count": None,
    "delete_count": None,
    "error": None,
}

if not p.exists():
    out["error"] = "delta file missing"
    print(json.dumps(out))
    raise SystemExit(0)

try:
    if p.suffix == ".gz":
        fh = gzip.open(p, "rt", encoding="utf-8", errors="replace")
    else:
        fh = p.open("rt", encoding="utf-8", errors="replace")

    node_count = way_count = relation_count = 0
    create_count = modify_count = delete_count = 0
    current_block = None

    with fh:
        for line in fh:
            s = line.strip()
            if s.startswith("<create"):
                current_block = "create"
                continue
            if s.startswith("<modify"):
                current_block = "modify"
                continue
            if s.startswith("<delete"):
                current_block = "delete"
                continue
            if s.startswith("</create") or s.startswith("</modify") or s.startswith("</delete"):
                current_block = None
                continue

            entity_seen = False
            if s.startswith("<node "):
                node_count += 1
                entity_seen = True
            elif s.startswith("<way "):
                way_count += 1
                entity_seen = True
            elif s.startswith("<relation "):
                relation_count += 1
                entity_seen = True

            if entity_seen:
                if current_block == "create":
                    create_count += 1
                elif current_block == "modify":
                    modify_count += 1
                elif current_block == "delete":
                    delete_count += 1

    out.update(
        {
            "node_count": node_count,
            "way_count": way_count,
            "relation_count": relation_count,
            "total_entities": node_count + way_count + relation_count,
            "create_count": create_count,
            "modify_count": modify_count,
            "delete_count": delete_count,
            "error": None,
        }
    )
except Exception as exc:
    out["error"] = str(exc)

print(json.dumps(out))
PY
}

region=""
input_pbf=""
updates_url=""
state_file=""
report_path=""
work_dir=""
size_mb="1024"
socket_timeout="120"
tmpdir=""
delta_out=""
emit_delta="1"
dry_run="0"
ignore_headers="0"
force_old="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --region)
      region="$2"
      shift 2
      ;;
    --input-pbf)
      input_pbf="$2"
      shift 2
      ;;
    --updates-url)
      updates_url="$2"
      shift 2
      ;;
    --state-file)
      state_file="$2"
      shift 2
      ;;
    --report-path)
      report_path="$2"
      shift 2
      ;;
    --work-dir)
      work_dir="$2"
      shift 2
      ;;
    --size-mb)
      size_mb="$2"
      shift 2
      ;;
    --socket-timeout)
      socket_timeout="$2"
      shift 2
      ;;
    --tmpdir)
      tmpdir="$2"
      shift 2
      ;;
    --delta-out)
      delta_out="$2"
      shift 2
      ;;
    --emit-delta)
      emit_delta="1"
      shift
      ;;
    --no-emit-delta)
      emit_delta="0"
      shift
      ;;
    --dry-run)
      dry_run="1"
      shift
      ;;
    --ignore-osmosis-headers)
      ignore_headers="1"
      shift
      ;;
    --force-update-of-old-planet)
      force_old="1"
      shift
      ;;
    -h|--help)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$region" || -z "$input_pbf" ]]; then
  usage
  exit 1
fi

if [[ ! -f "$input_pbf" ]]; then
  echo "Input PBF not found: $input_pbf" >&2
  exit 1
fi

if ! is_int "$size_mb" || [[ "$size_mb" -lt 1 ]]; then
  echo "Invalid --size-mb value: $size_mb (must be integer >= 1)" >&2
  exit 1
fi

if ! is_int "$socket_timeout" || [[ "$socket_timeout" -lt 1 ]]; then
  echo "Invalid --socket-timeout value: $socket_timeout (must be integer >= 1)" >&2
  exit 1
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
repo_root="$(cd "$script_dir/../.." && pwd)"

default_work_dir="$repo_root/mapdata/build/$region/updates"
default_state_file="$repo_root/mapdata/raw/${region}.diff_state.json"
run_id="$(date -u +%Y%m%dT%H%M%SZ)"
default_report_path="$repo_root/mapdata/reports/diff_update.${region}.${run_id}.json"

work_dir="${work_dir:-$default_work_dir}"
state_file="${state_file:-$default_state_file}"
report_path="${report_path:-$default_report_path}"

mkdir -p "$work_dir" "$(dirname "$state_file")" "$(dirname "$report_path")"

require_cmd python3
require_cmd curl
if [[ "$dry_run" != "1" ]]; then
  require_cmd pyosmium-up-to-date
fi
if [[ "$emit_delta" == "1" ]]; then
  require_cmd pyosmium-get-changes
fi

before_header_json="$(read_pbf_header_json "$input_pbf")"
before_seq="$(echo "$before_header_json" | python3 -c 'import json,sys; v=json.load(sys.stdin).get("sequence_number"); print("" if v is None else v)')"
before_ts="$(echo "$before_header_json" | python3 -c 'import json,sys; v=json.load(sys.stdin).get("timestamp"); print("" if not v else v)')"
before_base_url="$(echo "$before_header_json" | python3 -c 'import json,sys; v=json.load(sys.stdin).get("base_url"); print("" if not v else v)')"

state_fallback_json="$(read_state_fallback_json "$state_file")"
state_fallback_seq="$(echo "$state_fallback_json" | python3 -c 'import json,sys; v=json.load(sys.stdin).get("last_applied_seq"); print("" if v is None else v)')"
state_fallback_ts="$(echo "$state_fallback_json" | python3 -c 'import json,sys; v=json.load(sys.stdin).get("last_applied_timestamp"); print("" if not v else v)')"
state_fallback_url="$(echo "$state_fallback_json" | python3 -c 'import json,sys; v=json.load(sys.stdin).get("last_updates_url"); print("" if not v else v)')"

if [[ -z "$updates_url" ]]; then
  if [[ -n "$before_base_url" ]]; then
    updates_url="$before_base_url"
  elif [[ -n "$state_fallback_url" ]]; then
    updates_url="$state_fallback_url"
  elif [[ "$region" == "germany" ]]; then
    updates_url="https://download.geofabrik.de/europe/germany-updates/"
  else
    echo "Could not infer updates URL. Use --updates-url explicitly." >&2
    exit 1
  fi
fi
updates_url="$(ensure_trailing_slash "$updates_url")"
state_url="${updates_url}state.txt"

if [[ -z "$before_seq" && -n "$state_fallback_seq" ]]; then
  before_seq="$state_fallback_seq"
fi
if [[ -z "$before_ts" && -n "$state_fallback_ts" ]]; then
  before_ts="$state_fallback_ts"
fi

before_size_bytes="$(wc -c < "$input_pbf" | tr -d ' ')"

state_before_txt="$work_dir/server_state_before.${run_id}.txt"
state_after_txt="$work_dir/server_state_after.${run_id}.txt"
updater_log="$work_dir/updater.${run_id}.log"
delta_log="$work_dir/delta_export.${run_id}.log"
updated_tmp="$work_dir/$(basename "$input_pbf").updated.${run_id}.tmp"

server_before_seq=""
server_before_ts=""
if fetch_server_state "$state_url" "$state_before_txt"; then
  server_before_json="$(parse_server_state_json "$state_before_txt")"
  server_before_seq="$(echo "$server_before_json" | python3 -c 'import json,sys; v=json.load(sys.stdin).get("sequence_number"); print("" if v is None else v)')"
  server_before_ts="$(echo "$server_before_json" | python3 -c 'import json,sys; v=json.load(sys.stdin).get("timestamp"); print("" if not v else v)')"
else
  server_before_json='{"sequence_number":null,"timestamp":null}'
fi

status="ok"
updater_rc=0
notes=""
update_started_epoch="$(date +%s)"

if [[ "$dry_run" == "1" ]]; then
  status="dry_run"
  notes="Dry run enabled; no PBF modifications performed."
else
  update_cmd=(
    pyosmium-up-to-date
    --server "$updates_url"
    --size "$size_mb"
    --socket-timeout "$socket_timeout"
    --outfile "$updated_tmp"
  )

  if [[ "$ignore_headers" == "1" ]]; then
    update_cmd+=(--ignore-osmosis-headers)
  fi
  if [[ "$force_old" == "1" ]]; then
    update_cmd+=(--force-update-of-old-planet)
  fi
  if [[ -n "$tmpdir" ]]; then
    mkdir -p "$tmpdir"
    update_cmd+=(--tmpdir "$tmpdir")
  fi

  update_cmd+=("$input_pbf")

  set +e
  "${update_cmd[@]}" >"$updater_log" 2>&1
  updater_rc=$?
  set -e

  if [[ "$updater_rc" -gt 1 ]]; then
    status="error"
    notes="pyosmium-up-to-date failed (rc=$updater_rc)."
    rm -f "$updated_tmp"
  else
    if [[ -f "$updated_tmp" ]]; then
      mv "$updated_tmp" "$input_pbf"
      if [[ "$updater_rc" -eq 1 ]]; then
        status="partial"
        notes="Updates applied partially (pyosmium rc=1: more diffs may remain)."
      fi
    else
      if [[ "$updater_rc" -eq 1 ]]; then
        status="partial"
        notes="pyosmium rc=1 but no output file was produced; keeping existing PBF."
      else
        status="ok"
        notes="No updated output file produced; keeping existing PBF unchanged."
      fi
    fi
  fi
fi

after_header_json="$(read_pbf_header_json "$input_pbf")"
after_seq="$(echo "$after_header_json" | python3 -c 'import json,sys; v=json.load(sys.stdin).get("sequence_number"); print("" if v is None else v)')"
after_ts="$(echo "$after_header_json" | python3 -c 'import json,sys; v=json.load(sys.stdin).get("timestamp"); print("" if not v else v)')"
after_base_url="$(echo "$after_header_json" | python3 -c 'import json,sys; v=json.load(sys.stdin).get("base_url"); print("" if not v else v)')"
after_size_bytes="$(wc -c < "$input_pbf" | tr -d ' ')"

server_after_seq=""
server_after_ts=""
if fetch_server_state "$state_url" "$state_after_txt"; then
  server_after_json="$(parse_server_state_json "$state_after_txt")"
  server_after_seq="$(echo "$server_after_json" | python3 -c 'import json,sys; v=json.load(sys.stdin).get("sequence_number"); print("" if v is None else v)')"
  server_after_ts="$(echo "$server_after_json" | python3 -c 'import json,sys; v=json.load(sys.stdin).get("timestamp"); print("" if not v else v)')"
else
  server_after_json='{"sequence_number":null,"timestamp":null}'
fi

if [[ -z "$after_seq" && -n "$server_after_seq" ]]; then
  after_seq="$server_after_seq"
fi
if [[ -z "$after_ts" && -n "$server_after_ts" ]]; then
  after_ts="$server_after_ts"
fi

seq_delta=""
if is_int "$before_seq" && is_int "$after_seq"; then
  seq_delta="$((after_seq - before_seq))"
fi

emit_delta_status="skipped"
emit_delta_reason="disabled"
delta_counts_json='{"node_count":null,"way_count":null,"relation_count":null,"total_entities":null,"create_count":null,"modify_count":null,"delete_count":null,"error":null}'

if [[ "$emit_delta" == "1" ]]; then
  emit_delta_reason=""
  if [[ "$dry_run" == "1" ]]; then
    emit_delta_status="skipped"
    emit_delta_reason="dry_run"
  elif [[ "$status" == "error" ]]; then
    emit_delta_status="skipped"
    emit_delta_reason="update_error"
  elif is_int "$before_seq" && is_int "$after_seq" && [[ "$after_seq" -gt "$before_seq" ]]; then
    start_seq="$((before_seq + 1))"
    end_seq="$after_seq"

    if [[ -z "$delta_out" ]]; then
      delta_out="$work_dir/${region}.delta.${start_seq}-${end_seq}.osc.gz"
    fi

    set +e
    pyosmium-get-changes \
      --server "$updates_url" \
      --start-id "$start_seq" \
      --end-id "$end_seq" \
      --size "$size_mb" \
      --socket-timeout "$socket_timeout" \
      --outfile "$delta_out" >"$delta_log" 2>&1
    delta_rc=$?
    set -e

    if [[ "$delta_rc" -eq 0 && -s "$delta_out" ]]; then
      emit_delta_status="exported"
      emit_delta_reason=""
      delta_counts_json="$(count_delta_entities_json "$delta_out")"
    else
      emit_delta_status="error"
      emit_delta_reason="pyosmium-get-changes failed (rc=$delta_rc)"
    fi
  else
    emit_delta_status="skipped"
    emit_delta_reason="missing_or_non_increasing_sequence"
  fi
fi

run_finished_epoch="$(date +%s)"
elapsed_seconds="$((run_finished_epoch - update_started_epoch))"
updated_at_utc="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

python3 - \
  "$report_path" \
  "$state_file" \
  "$region" \
  "$input_pbf" \
  "$updates_url" \
  "$status" \
  "$notes" \
  "$updater_rc" \
  "$before_size_bytes" \
  "$after_size_bytes" \
  "$elapsed_seconds" \
  "$updated_at_utc" \
  "$emit_delta_status" \
  "$emit_delta_reason" \
  "${delta_out:-}" \
  "$seq_delta" \
  "$before_header_json" \
  "$after_header_json" \
  "$server_before_json" \
  "$server_after_json" \
  "$delta_counts_json" <<'PY'
import json
import sys
from pathlib import Path

(
    report_path,
    state_path,
    region,
    input_pbf,
    updates_url,
    status,
    notes,
    updater_rc,
    before_size,
    after_size,
    elapsed_s,
    updated_at,
    emit_delta_status,
    emit_delta_reason,
    delta_out,
    seq_delta,
    before_header_json,
    after_header_json,
    server_before_json,
    server_after_json,
    delta_counts_json,
) = sys.argv[1:]

def parse_json(raw, fallback):
    try:
        return json.loads(raw)
    except Exception:
        return fallback

before_header = parse_json(before_header_json, {})
after_header = parse_json(after_header_json, {})
server_before = parse_json(server_before_json, {})
server_after = parse_json(server_after_json, {})
delta_counts = parse_json(delta_counts_json, {})

try:
    before_size_i = int(before_size)
except Exception:
    before_size_i = None
try:
    after_size_i = int(after_size)
except Exception:
    after_size_i = None
try:
    updater_rc_i = int(updater_rc)
except Exception:
    updater_rc_i = None
try:
    elapsed_s_i = int(elapsed_s)
except Exception:
    elapsed_s_i = None

before_seq = before_header.get("sequence_number")
after_seq = after_header.get("sequence_number")
if after_seq is None:
    after_seq = server_after.get("sequence_number")

if seq_delta == "":
    seq_delta_i = None
else:
    try:
        seq_delta_i = int(seq_delta)
    except Exception:
        seq_delta_i = None

payload = {
    "region": region,
    "input_pbf": input_pbf,
    "updates_url": updates_url,
    "status": status,
    "notes": notes,
    "updated_at_utc": updated_at,
    "elapsed_seconds": elapsed_s_i,
    "updater_exit_code": updater_rc_i,
    "pbf_before": {
        "size_bytes": before_size_i,
        "sequence_number": before_header.get("sequence_number"),
        "timestamp": before_header.get("timestamp"),
        "base_url": before_header.get("base_url"),
        "read_error": before_header.get("error"),
    },
    "pbf_after": {
        "size_bytes": after_size_i,
        "sequence_number": after_header.get("sequence_number"),
        "timestamp": after_header.get("timestamp"),
        "base_url": after_header.get("base_url"),
        "read_error": after_header.get("error"),
    },
    "server_state_before": {
        "sequence_number": server_before.get("sequence_number"),
        "timestamp": server_before.get("timestamp"),
    },
    "server_state_after": {
        "sequence_number": server_after.get("sequence_number"),
        "timestamp": server_after.get("timestamp"),
    },
    "sequence_delta": seq_delta_i,
    "delta_export": {
        "status": emit_delta_status,
        "reason": emit_delta_reason or None,
        "path": delta_out or None,
        "size_bytes": (Path(delta_out).stat().st_size if delta_out and Path(delta_out).exists() else None),
        "counts": delta_counts,
    },
}

Path(report_path).write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

state_payload = {
    "region": region,
    "updated_at_utc": updated_at,
    "last_run_status": status,
    "last_run_report": report_path,
    "last_applied_seq": after_seq,
    "last_applied_timestamp": after_header.get("timestamp") or server_after.get("timestamp"),
    "last_server_seq": server_after.get("sequence_number"),
    "last_server_timestamp": server_after.get("timestamp"),
    "last_updates_url": updates_url,
    "updates_url": updates_url,
}
Path(state_path).write_text(json.dumps(state_payload, indent=2, sort_keys=True), encoding="utf-8")
PY

echo "status=${status}"
echo "report=${report_path}"
echo "state=${state_file}"
echo "updates_url=${updates_url}"
echo "before_seq=${before_seq:-} after_seq=${after_seq:-} server_seq=${server_after_seq:-}"

if [[ "$status" == "error" ]]; then
  echo "Update failed. Inspect log: ${updater_log}" >&2
  exit 1
fi
