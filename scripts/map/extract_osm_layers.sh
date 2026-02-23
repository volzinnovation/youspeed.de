#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 3 ]]; then
  echo "Usage: $0 <input.pbf> <roads_out.pbf> <context_out.pbf>" >&2
  exit 1
fi

input_pbf="$1"
roads_out="$2"
context_out="$3"

if [[ ! -f "$input_pbf" ]]; then
  echo "Input PBF not found: $input_pbf" >&2
  exit 1
fi

if ! command -v osmium >/dev/null 2>&1; then
  echo "Missing dependency: osmium" >&2
  echo "Install osmium-tool, then rerun." >&2
  exit 1
fi

mkdir -p "$(dirname "$roads_out")" "$(dirname "$context_out")"

# Layer 1: speed-relevant road network (all highways with speed-related tags preserved).
osmium tags-filter \
  "$input_pbf" \
  w/highway \
  w/maxspeed \
  w/maxspeed:type \
  w/source:maxspeed \
  w/maxspeed:conditional \
  w/zone:maxspeed \
  w/traffic_sign \
  --add-referenced \
  --overwrite \
  -o "$roads_out"

# Layer 2: built-up area context for inside/outside default speed logic.
osmium tags-filter \
  "$input_pbf" \
  r/boundary=administrative \
  r/admin_level=8 \
  r/admin_level=9 \
  w/boundary=administrative \
  n/place=city \
  n/place=town \
  n/place=village \
  n/place=hamlet \
  --add-referenced \
  --overwrite \
  -o "$context_out"

printf 'Extracted layers:\n- roads: %s\n- context: %s\n' "$roads_out" "$context_out"
