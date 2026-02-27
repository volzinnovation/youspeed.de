#!/usr/bin/env bash
set -euo pipefail

if [[ $# -ne 9 ]]; then
  echo "Usage: $0 <roads.pbf> <context.pbf> <ways_idx_out> <ways_meta_out> <areas_idx_out> <ways_lookup_out> <ways_geom_out> <ways_geom_lookup_out> <work_dir>" >&2
  exit 1
fi

roads_pbf="$1"
context_pbf="$2"
ways_idx_out="$3"
ways_meta_out="$4"
areas_idx_out="$5"
ways_lookup_out="$6"
ways_geom_out="$7"
ways_geom_lookup_out="$8"
work_dir="$9"

grid_scale="100" # 0.01 degree cells

require_cmd() {
  if ! command -v "$1" >/dev/null 2>&1; then
    echo "Missing dependency: $1" >&2
    exit 1
  fi
}

for f in "$roads_pbf" "$context_pbf"; do
  if [[ ! -f "$f" ]]; then
    echo "Input file not found: $f" >&2
    exit 1
  fi
done

require_cmd osmium
require_cmd jq
require_cmd awk
require_cmd sort
require_cmd python3

mkdir -p "$(dirname "$ways_idx_out")" "$(dirname "$ways_meta_out")" "$(dirname "$areas_idx_out")" "$(dirname "$ways_lookup_out")" "$(dirname "$ways_geom_out")" "$(dirname "$ways_geom_lookup_out")" "$work_dir"

roads_geojsonseq="$work_dir/roads.geojsonseq"
context_geojsonseq="$work_dir/context.geojsonseq"
ways_bbox_tsv="$work_dir/ways_bbox.tsv"
areas_bbox_tsv="$work_dir/areas_bbox.tsv"
ways_cell_pairs="$work_dir/ways_cell_pairs.jsonl"
areas_cell_pairs="$work_dir/areas_cell_pairs.jsonl"
ways_cells_json="$work_dir/ways_cells.json"
areas_cells_json="$work_dir/areas_cells.json"
areas_meta_jsonl="$work_dir/areas.meta.jsonl"

# Convert filtered PBF layers to GeoJSON sequence for deterministic downstream packing.
osmium export --overwrite -f geojsonseq "$roads_pbf" -o "$roads_geojsonseq"
osmium export --overwrite -f geojsonseq "$context_pbf" -o "$context_geojsonseq"

# Way metadata used by runtime scoring and rule fusion.
jq -c '
  def way_id:
    (.properties["@id"] // .id // "") as $raw |
    if ($raw | type) == "number" then ($raw | tostring)
    else (($raw | tostring | split("/"))[-1]) end;
  def way_points:
    if .geometry == null then []
    elif .geometry.type == "LineString" then .geometry.coordinates
    elif .geometry.type == "MultiLineString" then [ .geometry.coordinates[][] ]
    else [] end;
  def is_car_drivable($h):
    $h == "motorway" or
    $h == "trunk" or
    $h == "primary" or
    $h == "secondary" or
    $h == "tertiary" or
    $h == "unclassified" or
    $h == "residential" or
    $h == "service" or
    $h == "living_street" or
    $h == "motorway_link" or
    $h == "trunk_link" or
    $h == "primary_link" or
    $h == "secondary_link" or
    $h == "tertiary_link" or
    $h == "road";
  select(.type == "Feature")
  | (.properties.highway // null) as $highway
  | select($highway != null and is_car_drivable($highway))
  | (way_points) as $pts
  | select(($pts | length) > 1)
  | {
    way_id: way_id,
      highway: $highway,
      street_name: (.properties.name // null),
      maxspeed: (.properties.maxspeed // null),
      maxspeed_type: (.properties["maxspeed:type"] // null),
      source_maxspeed: (.properties["source:maxspeed"] // null),
      maxspeed_conditional: (.properties["maxspeed:conditional"] // null),
      zone_maxspeed: (.properties["zone:maxspeed"] // null),
      traffic_sign: (.properties.traffic_sign // null),
      min_lon: ($pts | map(.[0]) | min),
      min_lat: ($pts | map(.[1]) | min),
      max_lon: ($pts | map(.[0]) | max),
      max_lat: ($pts | map(.[1]) | max),
      center_lon: ((($pts | map(.[0]) | min) + ($pts | map(.[0]) | max)) / 2),
      center_lat: ((($pts | map(.[1]) | min) + ($pts | map(.[1]) | max)) / 2)
    }
' "$roads_geojsonseq" > "$ways_meta_out"

jq -r '[.way_id, .min_lon, .min_lat, .max_lon, .max_lat] | @tsv' "$ways_meta_out" > "$ways_bbox_tsv"

# Area metadata for built-up-area context candidates.
jq -c '
  def area_id:
    (.properties["@id"] // .id // "") as $raw |
    if ($raw | type) == "number" then ($raw | tostring)
    else (($raw | tostring | split("/"))[-1]) end;
  def geom_points:
    if .geometry == null then []
    elif .geometry.type == "Point" then [ .geometry.coordinates ]
    elif .geometry.type == "MultiPoint" then .geometry.coordinates
    elif .geometry.type == "LineString" then .geometry.coordinates
    elif .geometry.type == "MultiLineString" then [ .geometry.coordinates[][] ]
    elif .geometry.type == "Polygon" then [ .geometry.coordinates[][] ]
    elif .geometry.type == "MultiPolygon" then [ .geometry.coordinates[][][] ]
    else [] end;
  select(.type == "Feature")
  | (geom_points) as $pts
  | select(($pts | length) > 0)
  | ((.properties.residential // (if .properties.landuse == "residential" then "landuse" else null end)) // null) as $residential
  | (
      if .geometry == null then []
      elif .geometry.type == "Polygon" then (.geometry.coordinates[0] // [])
      elif .geometry.type == "MultiPolygon" then (.geometry.coordinates[0][0] // [])
      else []
      end
    ) as $ring
  | {
      area_id: area_id,
      geometry_type: (.geometry.type // null),
      name: (.properties.name // null),
      place: (.properties.place // null),
      boundary: (.properties.boundary // null),
      admin_level: (.properties.admin_level // null),
      residential: $residential,
      points: (if $residential != null and ($ring | length) >= 4 then $ring else null end),
      min_lon: ($pts | map(.[0]) | min),
      min_lat: ($pts | map(.[1]) | min),
      max_lon: ($pts | map(.[0]) | max),
      max_lat: ($pts | map(.[1]) | max)
    }
' "$context_geojsonseq" > "$areas_meta_jsonl"

jq -r '[.area_id, .min_lon, .min_lat, .max_lon, .max_lat] | @tsv' "$areas_meta_jsonl" > "$areas_bbox_tsv"

build_cells_json() {
  local bbox_tsv="$1"
  local pairs_out="$2"
  local cells_json_out="$3"

  awk -F'\t' -v scale="$grid_scale" '
    function floor_int(v,   i) {
      i = int(v)
      if (v < 0 && v != i) {
        return i - 1
      }
      return i
    }
    {
      id = $1
      min_lon = $2 + 0
      min_lat = $3 + 0
      max_lon = $4 + 0
      max_lat = $5 + 0
      x0 = floor_int((min_lon + 180.0) * scale)
      x1 = floor_int((max_lon + 180.0) * scale)
      y0 = floor_int((min_lat + 90.0) * scale)
      y1 = floor_int((max_lat + 90.0) * scale)
      for (x = x0; x <= x1; x++) {
        for (y = y0; y <= y1; y++) {
          printf "%s\t%s\n", x ":" y, id
        }
      }
    }
  ' "$bbox_tsv" \
    | LC_ALL=C sort -u \
    | awk -F'\t' '{printf "{\"cell\":\"%s\",\"id\":\"%s\"}\n", $1, $2}' > "$pairs_out"

  if [[ ! -s "$pairs_out" ]]; then
    echo '{}' > "$cells_json_out"
    return
  fi

  jq -s '
    reduce .[] as $row ({};
      .[$row.cell] = ((.[$row.cell] // []) + [$row.id])
    )
  ' "$pairs_out" > "$cells_json_out"
}

build_cells_json "$ways_bbox_tsv" "$ways_cell_pairs" "$ways_cells_json"
build_cells_json "$areas_bbox_tsv" "$areas_cell_pairs" "$areas_cells_json"

ways_count="$(wc -l < "$ways_meta_out" | tr -d ' ')"
areas_count="$(wc -l < "$areas_meta_jsonl" | tr -d ' ')"

jq -n \
  --argjson grid_scale "$grid_scale" \
  --argjson ways_count "$ways_count" \
  --slurpfile cells "$ways_cells_json" \
  '{
    schema_version: 1,
    grid_scale: $grid_scale,
    ways_count: $ways_count,
    cells: $cells[0]
  }' > "$ways_idx_out"

jq -n \
  --argjson grid_scale "$grid_scale" \
  --argjson areas_count "$areas_count" \
  --slurpfile cells "$areas_cells_json" \
  --slurpfile areas "$areas_meta_jsonl" \
  '{
    schema_version: 1,
    grid_scale: $grid_scale,
    areas_count: $areas_count,
    cells: $cells[0],
    areas: $areas
  }' > "$areas_idx_out"

python3 - "$ways_meta_out" "$ways_lookup_out" <<'PY'
import json
import sys

ways_meta = sys.argv[1]
ways_lookup = sys.argv[2]

index = {}
with open(ways_meta, "r", encoding="utf-8") as f:
    while True:
        offset = f.tell()
        line = f.readline()
        if not line:
            break
        row = json.loads(line)
        index[row["way_id"]] = offset

with open(ways_lookup, "w", encoding="utf-8") as out:
    json.dump({"schema_version": 1, "index": index}, out, sort_keys=True, separators=(",", ":"))
PY

jq -c '
  def way_id:
    (.properties["@id"] // .id // "") as $raw |
    if ($raw | type) == "number" then ($raw | tostring)
    else (($raw | tostring | split("/"))[-1]) end;
  def way_points:
    if .geometry == null then []
    elif .geometry.type == "LineString" then .geometry.coordinates
    elif .geometry.type == "MultiLineString" then [ .geometry.coordinates[][] ]
    else [] end;
  def is_car_drivable($h):
    $h == "motorway" or
    $h == "trunk" or
    $h == "primary" or
    $h == "secondary" or
    $h == "tertiary" or
    $h == "unclassified" or
    $h == "residential" or
    $h == "service" or
    $h == "living_street" or
    $h == "motorway_link" or
    $h == "trunk_link" or
    $h == "primary_link" or
    $h == "secondary_link" or
    $h == "tertiary_link" or
    $h == "road";
  select(.type == "Feature")
  | (.properties.highway // null) as $highway
  | select($highway != null and is_car_drivable($highway))
  | (way_points) as $pts
  | select(($pts | length) > 1)
  | {
      way_id: way_id,
      points: ($pts | map([.[1], .[0]]))
    }
' "$roads_geojsonseq" > "$ways_geom_out"

python3 - "$ways_geom_out" "$ways_geom_lookup_out" <<'PY'
import json
import sys

ways_geom = sys.argv[1]
ways_geom_lookup = sys.argv[2]

index = {}
with open(ways_geom, "r", encoding="utf-8") as f:
    while True:
        offset = f.tell()
        line = f.readline()
        if not line:
            break
        row = json.loads(line)
        index[row["way_id"]] = offset

with open(ways_geom_lookup, "w", encoding="utf-8") as out:
    json.dump({"schema_version": 1, "index": index}, out, sort_keys=True, separators=(",", ":"))
PY

echo "Packed runtime artifacts:"
echo "- $ways_meta_out"
echo "- $ways_idx_out"
echo "- $areas_idx_out"
echo "- $ways_lookup_out"
echo "- $ways_geom_out"
echo "- $ways_geom_lookup_out"
