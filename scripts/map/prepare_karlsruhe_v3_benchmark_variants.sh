#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
raw_pbf="${repo_root}/mapdata/raw/karlsruhe-regbez-latest.osm.pbf"
bench_dir="${repo_root}/mapdata/bench/karlsruhe"
assets_dir="${repo_root}/iphone/SpeedDBBenchSketch/BenchmarkAssets"

variant_a_region="karlsruhe-regbez-v3a-geom16"
variant_b_region="karlsruhe-regbez-v3b-waylinks"
variant_a_db="${bench_dir}/karlsruhe_v3_A_geom16.sqlite"
variant_b_db="${bench_dir}/karlsruhe_v3_B_waylinks.sqlite"
variant_manifest="${bench_dir}/karlsruhe_variants.json"

mkdir -p "${bench_dir}" "${assets_dir}"

if [[ ! -f "${raw_pbf}" ]]; then
  echo "Reassembling Karlsruhe seed PBF into ${raw_pbf}" >&2
  "${repo_root}/scripts/map/reassemble_seed_karlsruhe_pbf.sh" "${raw_pbf}"
fi

echo "Building v3_A (max-geom-points=16)" >&2
"${repo_root}/scripts/map/build_region_artifacts.sh" \
  --region "${variant_a_region}" \
  --input "${raw_pbf}" \
  --root "${repo_root}" \
  --max-geom-points 16

python3 "${repo_root}/scripts/map/build_spatialite_v3.py" \
  --v1-dist "${repo_root}/mapdata/dist/${variant_a_region}" \
  --out-db "${variant_a_db}"

echo "Building v3_B (way_links)" >&2
"${repo_root}/scripts/map/build_region_artifacts.sh" \
  --region "${variant_b_region}" \
  --input "${raw_pbf}" \
  --root "${repo_root}" \
  --max-geom-points 8

python3 "${repo_root}/scripts/map/build_spatialite_v3.py" \
  --v1-dist "${repo_root}/mapdata/dist/${variant_b_region}" \
  --out-db "${variant_b_db}" \
  --build-way-links

cp -f "${variant_a_db}" "${assets_dir}/karlsruhe_v3_A_geom16.sqlite"
cp -f "${variant_b_db}" "${assets_dir}/karlsruhe_v3_B_waylinks.sqlite"

python3 - <<'PY' "${variant_a_db}" "${variant_b_db}" "${variant_manifest}" "${assets_dir}"
import json
import os
import sqlite3
import sys
from pathlib import Path


def describe(path: Path) -> dict:
    with sqlite3.connect(path) as conn:
        metadata = dict(conn.execute("SELECT key, value FROM metadata"))
        point_count = 0
        for (points_json,) in conn.execute("SELECT points_json FROM way_geom"):
            if not points_json:
                continue
            try:
                point_count += len(json.loads(points_json))
            except json.JSONDecodeError:
                pass
        way_count = conn.execute("SELECT COUNT(*) FROM ways").fetchone()[0]
        way_links_count = 0
        has_way_links = conn.execute(
            "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='way_links'"
        ).fetchone()[0] == 1
        if has_way_links:
            way_links_count = conn.execute("SELECT COUNT(*) FROM way_links").fetchone()[0]
    return {
        "file": path.name,
        "bytes": path.stat().st_size,
        "ways": way_count,
        "geom_points": point_count,
        "way_links": way_links_count,
        "way_links_mode": metadata.get("way_links_mode", "none"),
    }


variant_a = Path(sys.argv[1])
variant_b = Path(sys.argv[2])
manifest = Path(sys.argv[3])
assets_dir = Path(sys.argv[4])
payload = {
    "variants": [
        describe(variant_a),
        describe(variant_b),
    ],
    "assets_dir": str(assets_dir),
}
manifest.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
(assets_dir / "karlsruhe_variants.json").write_text(
    json.dumps(payload, indent=2, sort_keys=True),
    encoding="utf-8",
)
print(json.dumps(payload, indent=2, sort_keys=True))
PY

echo "Prepared benchmark assets:" >&2
echo "  ${assets_dir}/karlsruhe_v3_A_geom16.sqlite" >&2
echo "  ${assets_dir}/karlsruhe_v3_B_waylinks.sqlite" >&2
