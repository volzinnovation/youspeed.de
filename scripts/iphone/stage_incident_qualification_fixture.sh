#!/usr/bin/env bash
set -euo pipefail

# Test resources only. Never copy captured traffic data into the driver's app.
repo_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
python3 - "${repo_root}" <<'PY'
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys

repo = Path(sys.argv[1])
capture = os.environ.get("YOUSPEED_INCIDENT_QUALIFICATION_DIR", "")
if os.environ.get("PRODUCT_BUNDLE_IDENTIFIER") != "de.youspeed.SpeedConsumerTests":
    raise SystemExit("Incident fixtures may only be staged into SpeedConsumerTests")
target = Path(os.environ["TARGET_BUILD_DIR"]) / os.environ["UNLOCALIZED_RESOURCES_FOLDER_PATH"]
if target.name != "SpeedConsumerTests.xctest":
    raise SystemExit("Unexpected unit-test resource bundle")
target.mkdir(parents=True, exist_ok=True)
shared = target / "roadworks"
shared.mkdir(exist_ok=True)
for name in ("snapshot-v1.json", "snapshot-v2.json", "manifest-v2.json"):
    shutil.copyfile(repo / "shared/roadworks" / name, shared / name)

captured = target / "IncidentQualification"
if captured.exists():
    shutil.rmtree(captured)
if capture:
    if os.environ.get("YOUSPEED_TEST_BUNDLE_SUFFIX") not in {".UnitTests", ".CityLookupTests"}:
        raise SystemExit("Captured incident data requires a separate .UnitTests or .CityLookupTests app")
    source = Path(capture).resolve()
    snapshot = (source / "snapshot.json").read_bytes()
    manifest = json.loads((source / "manifest.json").read_bytes())
    receipt = json.loads((source / "receipt.json").read_bytes())
    digest = hashlib.sha256(snapshot).hexdigest()
    if digest != manifest["snapshot_id"] or len(snapshot) != manifest["snapshot_bytes"]:
        raise SystemExit("Captured incident snapshot does not match its manifest")
    if receipt.get("snapshot_sha256", digest) != digest:
        raise SystemExit("Captured incident receipt checksum differs")
    enabled = {row["source_id"] for row in manifest["sources"] if row["enabled"]}
    if enabled != {"incidents-bw"}:
        raise SystemExit("The acceptance fixture must enable incidents only")
    captured.mkdir()
    for name in ("snapshot.json", "manifest.json", "receipt.json"):
        shutil.copyfile(source / name, captured / name)
    (captured / "required.json").write_text('{"captured_fixture_required":true}\n')
    print("Staged checksummed incident acceptance data in isolated unit-test bundle")
PY
