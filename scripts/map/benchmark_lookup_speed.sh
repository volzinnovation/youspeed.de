#!/usr/bin/env bash
set -euo pipefail

if [[ $# -lt 3 || $# -gt 7 ]]; then
  echo "Usage: $0 <dist_dir> <lat> <lon> [heading=90] [repeats=10] [top_k=5] [polyline_top_n=250]" >&2
  exit 1
fi

dist_dir="$1"
lat="$2"
lon="$3"
heading="${4:-90}"
repeats="${5:-10}"
top_k="${6:-5}"
polyline_top_n="${7:-250}"

if ! command -v jq >/dev/null 2>&1; then
  echo "Missing dependency: jq" >&2
  exit 1
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
query_script="${script_dir}/query_speed_limit.py"
if [[ ! -x "$query_script" ]]; then
  echo "Missing executable query script: $query_script" >&2
  exit 1
fi

run_mode() {
  local mode="$1"
  local totals=()
  local loads=()
  local polys=()

  for _ in $(seq 1 "$repeats"); do
    payload="$($query_script \
      --dist-dir "$dist_dir" \
      --lat "$lat" \
      --lon "$lon" \
      --heading "$heading" \
      --top-k "$top_k" \
      --distance-mode "$mode" \
      --polyline-top-n "$polyline_top_n" \
      2>/dev/null)"

    totals+=("$(jq -r '.timing_ms.total' <<<"$payload")")
    loads+=("$(jq -r '.timing_ms.load_candidates' <<<"$payload")")
    polys+=("$(jq -r '.timing_ms.polyline_refine' <<<"$payload")")
  done

  python3 - "$mode" "${totals[@]}" -- "${loads[@]}" -- "${polys[@]}" <<'PY'
import statistics
import sys

mode = sys.argv[1]
parts = " ".join(sys.argv[2:]).split(" -- ")
totals = [float(x) for x in parts[0].split()]
loads = [float(x) for x in parts[1].split()]
polys = [float(x) for x in parts[2].split()]

print(
    f"{mode}: total_ms avg={statistics.mean(totals):.2f} p50={statistics.median(totals):.2f} "
    f"min={min(totals):.2f} max={max(totals):.2f}; "
    f"load_candidates_ms avg={statistics.mean(loads):.2f}; "
    f"polyline_refine_ms avg={statistics.mean(polys):.2f}"
)
PY
}

echo "Benchmarking $dist_dir @ lat=$lat lon=$lon heading=$heading repeats=$repeats"
run_mode bbox
run_mode hybrid
run_mode polyline
