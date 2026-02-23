#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<USAGE
Usage: $0 --region <region_name> --input <path_to_region.pbf> [--root <repo_root>] [--engine <pyosmium|osmium-cli>] [--max-geom-points <n>]

Example:
  $0 \
    --region karlsruhe-regbez \
    --input /Users/you/repo/mapdata/raw/karlsruhe-regbez-latest.osm.pbf
USAGE
}

region=""
input_pbf=""
repo_root=""
engine="pyosmium"
max_geom_points="24"

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
    --engine)
      engine="$2"
      shift 2
      ;;
    --max-geom-points)
      max_geom_points="$2"
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

if [[ "$engine" != "pyosmium" && "$engine" != "osmium-cli" ]]; then
  echo "Unsupported --engine value: $engine" >&2
  echo "Allowed: pyosmium | osmium-cli" >&2
  exit 1
fi

if ! [[ "$max_geom_points" =~ ^[0-9]+$ ]] || [[ "$max_geom_points" -lt 2 ]]; then
  echo "Invalid --max-geom-points value: $max_geom_points (must be integer >= 2)" >&2
  exit 1
fi

if [[ -z "$repo_root" ]]; then
  script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
  repo_root="$(cd "$script_dir/../.." && pwd)"
fi

if [[ ! -f "$input_pbf" ]]; then
  echo "Input PBF not found: $input_pbf" >&2
  exit 1
fi

build_dir="$repo_root/mapdata/build/$region"
dist_dir="$repo_root/mapdata/dist/$region"
mkdir -p "$build_dir" "$dist_dir"

ways_idx="$dist_dir/ways.idx"
ways_meta="$dist_dir/ways.meta"
areas_idx="$dist_dir/areas.idx"
ways_lookup="$dist_dir/ways.lookup"
ways_geom="$dist_dir/ways.geom"
ways_geom_lookup="$dist_dir/ways.geom.lookup"
manifest="$dist_dir/manifest.json"

if [[ "$engine" == "pyosmium" ]]; then
  "$repo_root/scripts/map/pack_runtime_artifacts_pyosmium.py" \
    "$input_pbf" \
    "$ways_idx" \
    "$ways_meta" \
    "$areas_idx" \
    "$ways_lookup" \
    "$ways_geom" \
    "$ways_geom_lookup" \
    --max-geom-points "$max_geom_points"
else
  roads_pbf="$build_dir/roads.osm.pbf"
  context_pbf="$build_dir/context.osm.pbf"

  "$repo_root/scripts/map/extract_osm_layers.sh" "$input_pbf" "$roads_pbf" "$context_pbf"

  "$repo_root/scripts/map/pack_runtime_artifacts.sh" \
    "$roads_pbf" \
    "$context_pbf" \
    "$ways_idx" \
    "$ways_meta" \
    "$areas_idx" \
    "$ways_lookup" \
    "$ways_geom" \
    "$ways_geom_lookup" \
    "$build_dir"
fi

"$repo_root/scripts/map/generate_manifest.sh" \
  "$region" \
  "$input_pbf" \
  "$ways_idx" \
  "$ways_meta" \
  "$areas_idx" \
  "$ways_lookup" \
  "$ways_geom" \
  "$ways_geom_lookup" \
  "$manifest"

echo "Build completed for region: $region"
echo "Engine: $engine"
echo "Artifacts:"
echo "- $ways_idx"
echo "- $ways_meta"
echo "- $areas_idx"
echo "- $ways_lookup"
echo "- $ways_geom"
echo "- $ways_geom_lookup"
echo "- $manifest"
