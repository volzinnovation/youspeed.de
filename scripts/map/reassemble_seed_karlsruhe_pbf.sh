#!/usr/bin/env bash
set -euo pipefail

repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
seed_dir="${repo_root}/mapdata/seeds/karlsruhe-regbez/pbf"
meta_path="${seed_dir}/karlsruhe-regbez-latest.osm.pbf.parts.json"
out_path="${1:-${repo_root}/mapdata/raw/karlsruhe-regbez-latest.osm.pbf}"

if [[ ! -f "${meta_path}" ]]; then
  echo "Missing metadata file: ${meta_path}" >&2
  exit 1
fi

mkdir -p "$(dirname "${out_path}")"
cat "${seed_dir}"/karlsruhe-regbez-latest.osm.pbf.part[0-9][0-9][0-9] > "${out_path}"

python3 - <<'PY' "${meta_path}" "${out_path}"
import hashlib
import json
import sys
from pathlib import Path

meta = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
out = Path(sys.argv[2])
h = hashlib.sha256()
with out.open("rb") as f:
    while True:
        b = f.read(8 * 1024 * 1024)
        if not b:
            break
        h.update(b)
actual = h.hexdigest()
expected = str(meta.get("sha256") or "")
if actual != expected:
    raise SystemExit(f"Checksum mismatch for {out}: expected {expected}, got {actual}")
print(f"Reassembled and verified: {out}")
PY
