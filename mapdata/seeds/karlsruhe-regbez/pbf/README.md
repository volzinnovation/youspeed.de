# Karlsruhe PBF Seed (Versioned in Git)

This directory stores the Karlsruhe Regierungsbezirk seed PBF as Git-safe split parts.

- Source: Geofabrik Karlsruhe extract
- Canonical file: `karlsruhe-regbez-latest.osm.pbf`
- Part metadata: `karlsruhe-regbez-latest.osm.pbf.parts.json`

## Reassemble

```bash
cat karlsruhe-regbez-latest.osm.pbf.part[0-9][0-9][0-9] > /tmp/karlsruhe-regbez-latest.osm.pbf
```

## Verify

```bash
python3 - <<'PY'
import hashlib, json
from pathlib import Path
p = Path("karlsruhe-regbez-latest.osm.pbf.parts.json")
meta = json.loads(p.read_text(encoding="utf-8"))
target = Path("/tmp/karlsruhe-regbez-latest.osm.pbf")
h = hashlib.sha256()
with target.open("rb") as f:
    while True:
        b = f.read(8 * 1024 * 1024)
        if not b:
            break
        h.update(b)
print("ok" if h.hexdigest() == meta["sha256"] else "mismatch")
PY
```
