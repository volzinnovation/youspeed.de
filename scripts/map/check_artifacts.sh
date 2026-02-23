#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 1 ]]; then
  echo "Usage: $0 <dist_region_dir>" >&2
  exit 1
fi

dist_dir="$1"
ways_idx="$dist_dir/ways.idx"
ways_meta="$dist_dir/ways.meta"
areas_idx="$dist_dir/areas.idx"
ways_lookup="$dist_dir/ways.lookup"
ways_geom="$dist_dir/ways.geom"
ways_geom_lookup="$dist_dir/ways.geom.lookup"
manifest="$dist_dir/manifest.json"

require_file() {
  local path="$1"
  if [[ ! -f "$path" ]]; then
    echo "Missing required file: $path" >&2
    exit 1
  fi
}

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing dependency: $1" >&2
    exit 1
  fi
}

sha256_file() {
  local path="$1"
  if command -v shasum >/dev/null 2>&1; then
    shasum -a 256 "$path" | awk '{print $1}'
  elif command -v sha256sum >/dev/null 2>&1; then
    sha256sum "$path" | awk '{print $1}'
  else
    echo "No SHA-256 utility found (shasum/sha256sum)." >&2
    exit 1
  fi
}

require_cmd jq
require_cmd wc
require_cmd awk

require_file "$ways_idx"
require_file "$ways_meta"
require_file "$areas_idx"
require_file "$ways_lookup"
require_file "$ways_geom"
require_file "$ways_geom_lookup"
require_file "$manifest"

jq -e '.schema_version == 1 and (.grid_scale | type) == "number" and (.cells | type) == "object"' "$ways_idx" >/dev/null
jq -e '.schema_version == 1 and (.grid_scale | type) == "number" and (.cells | type) == "object" and (.areas | type) == "array"' "$areas_idx" >/dev/null
jq -e '.schema_version == 1 and (.index | type) == "object"' "$ways_lookup" >/dev/null
jq -e '.schema_version == 1 and (.index | type) == "object"' "$ways_geom_lookup" >/dev/null
jq -e '.schema_version == 1 and .artifacts.ways_idx.sha256 and .artifacts.ways_meta.sha256 and .artifacts.areas_idx.sha256 and .artifacts.ways_lookup.sha256 and .artifacts.ways_geom.sha256 and .artifacts.ways_geom_lookup.sha256' "$manifest" >/dev/null

bad_way_rows="$(jq -c 'select((.way_id | type) != "string" or (.min_lon | type) != "number" or (.min_lat | type) != "number" or (.max_lon | type) != "number" or (.max_lat | type) != "number")' "$ways_meta" | wc -l | tr -d ' ')"
if [[ "$bad_way_rows" != "0" ]]; then
  echo "Invalid rows in ways.meta: $bad_way_rows" >&2
  exit 1
fi

invalid_highway_rows="$(jq -c '
  select(
    (.highway | type) != "string" or
    (
      .highway != "motorway" and
      .highway != "trunk" and
      .highway != "primary" and
      .highway != "secondary" and
      .highway != "tertiary" and
      .highway != "unclassified" and
      .highway != "residential" and
      .highway != "service" and
      .highway != "living_street" and
      .highway != "motorway_link" and
      .highway != "trunk_link" and
      .highway != "primary_link" and
      .highway != "secondary_link" and
      .highway != "tertiary_link" and
      .highway != "road"
    )
  )
' "$ways_meta" | wc -l | tr -d ' ')"
if [[ "$invalid_highway_rows" != "0" ]]; then
  echo "Found non-car-drivable rows in ways.meta: $invalid_highway_rows" >&2
  exit 1
fi

bad_geom_rows="$(jq -c '
  select(
    (.way_id | type) != "string" or
    (.points | type) != "array" or
    ((.points | length) < 2)
  )
' "$ways_geom" | wc -l | tr -d ' ')"
if [[ "$bad_geom_rows" != "0" ]]; then
  echo "Invalid rows in ways.geom: $bad_geom_rows" >&2
  exit 1
fi

manifest_ways_idx_sha="$(jq -r '.artifacts.ways_idx.sha256' "$manifest")"
manifest_ways_meta_sha="$(jq -r '.artifacts.ways_meta.sha256' "$manifest")"
manifest_areas_idx_sha="$(jq -r '.artifacts.areas_idx.sha256' "$manifest")"
manifest_ways_lookup_sha="$(jq -r '.artifacts.ways_lookup.sha256' "$manifest")"
manifest_ways_geom_sha="$(jq -r '.artifacts.ways_geom.sha256' "$manifest")"
manifest_ways_geom_lookup_sha="$(jq -r '.artifacts.ways_geom_lookup.sha256' "$manifest")"

actual_ways_idx_sha="$(sha256_file "$ways_idx")"
actual_ways_meta_sha="$(sha256_file "$ways_meta")"
actual_areas_idx_sha="$(sha256_file "$areas_idx")"
actual_ways_lookup_sha="$(sha256_file "$ways_lookup")"
actual_ways_geom_sha="$(sha256_file "$ways_geom")"
actual_ways_geom_lookup_sha="$(sha256_file "$ways_geom_lookup")"

[[ "$manifest_ways_idx_sha" == "$actual_ways_idx_sha" ]] || { echo "ways.idx hash mismatch" >&2; exit 1; }
[[ "$manifest_ways_meta_sha" == "$actual_ways_meta_sha" ]] || { echo "ways.meta hash mismatch" >&2; exit 1; }
[[ "$manifest_areas_idx_sha" == "$actual_areas_idx_sha" ]] || { echo "areas.idx hash mismatch" >&2; exit 1; }
[[ "$manifest_ways_lookup_sha" == "$actual_ways_lookup_sha" ]] || { echo "ways.lookup hash mismatch" >&2; exit 1; }
[[ "$manifest_ways_geom_sha" == "$actual_ways_geom_sha" ]] || { echo "ways.geom hash mismatch" >&2; exit 1; }
[[ "$manifest_ways_geom_lookup_sha" == "$actual_ways_geom_lookup_sha" ]] || { echo "ways.geom.lookup hash mismatch" >&2; exit 1; }

ways_count="$(wc -l < "$ways_meta" | tr -d ' ')"
idx_ways_count="$(jq -r '.ways_count' "$ways_idx")"
[[ "$ways_count" == "$idx_ways_count" ]] || { echo "ways_count mismatch (meta=$ways_count idx=$idx_ways_count)" >&2; exit 1; }

lookup_count="$(jq -r '.index | length' "$ways_lookup")"
[[ "$ways_count" == "$lookup_count" ]] || { echo "ways_count mismatch (meta=$ways_count lookup=$lookup_count)" >&2; exit 1; }

geom_count="$(wc -l < "$ways_geom" | tr -d ' ')"
[[ "$ways_count" == "$geom_count" ]] || { echo "ways_count mismatch (meta=$ways_count geom=$geom_count)" >&2; exit 1; }

geom_lookup_count="$(jq -r '.index | length' "$ways_geom_lookup")"
[[ "$ways_count" == "$geom_lookup_count" ]] || { echo "ways_count mismatch (meta=$ways_count geom_lookup=$geom_lookup_count)" >&2; exit 1; }

echo "Artifact check passed: $dist_dir"
