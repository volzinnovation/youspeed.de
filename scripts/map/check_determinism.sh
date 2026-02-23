#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<USAGE
Usage: $0 --region <region_name> --input <path_to_region.pbf> [--root <repo_root>] [--runs <n>]

Compares artifact hashes across repeated builds for deterministic output.
USAGE
}

region=""
input_pbf=""
repo_root=""
runs="2"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --region)
      region="$2"
      shift 2
      ;;
    --input)
      input_pbf="$2"
      shift 2
      ;;
    --root)
      repo_root="$2"
      shift 2
      ;;
    --runs)
      runs="$2"
      shift 2
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

if ! [[ "$runs" =~ ^[0-9]+$ ]] || [[ "$runs" -lt 2 ]]; then
  echo "--runs must be an integer >= 2" >&2
  exit 1
fi

if [[ -z "$repo_root" ]]; then
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  repo_root="$(cd "$script_dir/../.." && pwd)"
fi

if ! command -v jq >/dev/null 2>&1; then
  echo "Missing dependency: jq" >&2
  exit 1
fi

if [[ ! -f "$input_pbf" ]]; then
  echo "Input PBF not found: $input_pbf" >&2
  exit 1
fi

build_script="$repo_root/scripts/map/build_region_artifacts.sh"
check_script="$repo_root/scripts/map/check_artifacts.sh"
manifest="$repo_root/mapdata/dist/$region/manifest.json"

if [[ ! -x "$build_script" ]]; then
  echo "Missing executable build script: $build_script" >&2
  exit 1
fi

baseline=""
for i in $(seq 1 "$runs"); do
  echo "Run $i/$runs"
  "$build_script" --region "$region" --input "$input_pbf" --root "$repo_root" >/dev/null
  "$check_script" "$repo_root/mapdata/dist/$region" >/dev/null

  sig="$(jq -r '[.artifacts.ways_idx.sha256, .artifacts.ways_meta.sha256, .artifacts.areas_idx.sha256, .artifacts.ways_lookup.sha256, .artifacts.ways_geom.sha256, .artifacts.ways_geom_lookup.sha256] | join("|")' "$manifest")"
  echo "  artifact signature: $sig"

  if [[ -z "$baseline" ]]; then
    baseline="$sig"
  elif [[ "$sig" != "$baseline" ]]; then
    echo "Determinism check failed: signature differs from baseline." >&2
    echo "baseline: $baseline" >&2
    echo "current : $sig" >&2
    exit 1
  fi
done

echo "Determinism check passed for $region across $runs runs."
