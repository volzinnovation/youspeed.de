#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 9 ]]; then
  echo "Usage: $0 <region> <source_pbf> <ways_idx> <ways_meta> <areas_idx> <ways_lookup> <ways_geom> <ways_geom_lookup> <manifest_out>" >&2
  exit 1
fi

region="$1"
source_pbf="$2"
ways_idx="$3"
ways_meta="$4"
areas_idx="$5"
ways_lookup="$6"
ways_geom="$7"
ways_geom_lookup="$8"
manifest_out="$9"

if ! command -v jq >/dev/null 2>&1; then
  echo "Missing dependency: jq" >&2
  exit 1
fi

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

size_bytes() {
  wc -c < "$1" | tr -d ' '
}

for f in "$source_pbf" "$ways_idx" "$ways_meta" "$areas_idx" "$ways_lookup" "$ways_geom" "$ways_geom_lookup"; do
  if [[ ! -f "$f" ]]; then
    echo "Required file not found: $f" >&2
    exit 1
  fi
done

mkdir -p "$(dirname "$manifest_out")"

generated_at="$(date -u +"%Y-%m-%dT%H:%M:%SZ")"
osmium_version="unknown"
if command -v osmium >/dev/null 2>&1; then
  osmium_version="$(osmium --version | head -n 1)"
fi

jq -n \
  --arg region "$region" \
  --arg generated_at "$generated_at" \
  --arg osmium_version "$osmium_version" \
  --arg source_path "$source_pbf" \
  --arg source_sha256 "$(sha256_file "$source_pbf")" \
  --argjson source_size "$(size_bytes "$source_pbf")" \
  --arg ways_idx_path "$ways_idx" \
  --arg ways_idx_sha256 "$(sha256_file "$ways_idx")" \
  --argjson ways_idx_size "$(size_bytes "$ways_idx")" \
  --arg ways_meta_path "$ways_meta" \
  --arg ways_meta_sha256 "$(sha256_file "$ways_meta")" \
  --argjson ways_meta_size "$(size_bytes "$ways_meta")" \
  --arg areas_idx_path "$areas_idx" \
  --arg areas_idx_sha256 "$(sha256_file "$areas_idx")" \
  --argjson areas_idx_size "$(size_bytes "$areas_idx")" \
  --arg ways_lookup_path "$ways_lookup" \
  --arg ways_lookup_sha256 "$(sha256_file "$ways_lookup")" \
  --argjson ways_lookup_size "$(size_bytes "$ways_lookup")" \
  --arg ways_geom_path "$ways_geom" \
  --arg ways_geom_sha256 "$(sha256_file "$ways_geom")" \
  --argjson ways_geom_size "$(size_bytes "$ways_geom")" \
  --arg ways_geom_lookup_path "$ways_geom_lookup" \
  --arg ways_geom_lookup_sha256 "$(sha256_file "$ways_geom_lookup")" \
  --argjson ways_geom_lookup_size "$(size_bytes "$ways_geom_lookup")" \
  '{
    schema_version: 1,
    region: $region,
    generated_at_utc: $generated_at,
    generator: {
      pipeline: "osmium-first",
      osmium_version: $osmium_version
    },
    source: {
      path: $source_path,
      sha256: $source_sha256,
      bytes: $source_size
    },
    artifacts: {
      ways_idx: { path: $ways_idx_path, sha256: $ways_idx_sha256, bytes: $ways_idx_size },
      ways_meta: { path: $ways_meta_path, sha256: $ways_meta_sha256, bytes: $ways_meta_size },
      areas_idx: { path: $areas_idx_path, sha256: $areas_idx_sha256, bytes: $areas_idx_size },
      ways_lookup: { path: $ways_lookup_path, sha256: $ways_lookup_sha256, bytes: $ways_lookup_size },
      ways_geom: { path: $ways_geom_path, sha256: $ways_geom_sha256, bytes: $ways_geom_size },
      ways_geom_lookup: { path: $ways_geom_lookup_path, sha256: $ways_geom_lookup_sha256, bytes: $ways_geom_lookup_size }
    }
  }' > "$manifest_out"

echo "Wrote manifest: $manifest_out"
