#!/usr/bin/env python3
"""Check one authoritative mobile rule directory and optional packaged bytes."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[1]
RULES = ROOT / "shared/Rules"


def check(android_apk: Path | None = None, iphone_app: Path | None = None) -> None:
    files = sorted(RULES.glob("*-rules.json"))
    assert files, "No authoritative country rules"
    for path in files:
        record = json.loads(path.read_text())
        code = record.get("country_code", record.get("land_code"))
        assert path.name == f"{code}-rules.json", f"Country/filename mismatch: {path}"
    for duplicate in (ROOT / "iphone/SpeedConsumerApp/Rules", ROOT / "android/app/src/main/assets/Rules"):
        assert not list(duplicate.glob("*.json")), f"Duplicate rule source: {duplicate}"
    assert "path: ../shared/Rules" in (ROOT / "iphone/project.yml").read_text()
    assert '"../../shared"' in (ROOT / "android/app/build.gradle.kts").read_text()
    for path in (ROOT / "iphone/SpeedConsumerApp/BundleTargets.top10.json",
                 ROOT / "android/app/src/main/assets/BundleTargets.top10.json"):
        def walk(value):
            if isinstance(value, dict):
                source = value.get("source")
                if isinstance(source, str) and source.endswith("-rules.json"):
                    assert source.startswith("shared/Rules/"), (path, source)
                    assert (ROOT / source).is_file(), (path, source)
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)
        walk(json.loads(path.read_text()))
    if android_apk:
        with zipfile.ZipFile(android_apk) as apk:
            packaged = {name for name in apk.namelist() if name.startswith("assets/Rules/") and name.endswith("-rules.json")}
            assert packaged == {f"assets/Rules/{path.name}" for path in files}, "Android country set differs"
            for path in files:
                assert apk.read(f"assets/Rules/{path.name}") == path.read_bytes(), f"Android packaged bytes differ: {path.name}"
    if iphone_app:
        for path in files:
            candidates = [candidate for candidate in (iphone_app / path.name, iphone_app / "Rules" / path.name) if candidate.is_file()]
            assert len(candidates) == 1, f"Missing/duplicate iPhone rule: {path.name}"
            assert candidates[0].read_bytes() == path.read_bytes(), f"iPhone packaged bytes differ: {path.name}"
        packaged = {path.name for path in iphone_app.glob("*-rules.json")} | {path.name for path in (iphone_app / "Rules").glob("*-rules.json")}
        assert packaged == {path.name for path in files}, "iPhone country set differs"
    print(f"PASS: {len(files)} authoritative country rules; packaging inputs and requested app artifacts agree")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--android-apk", type=Path)
    parser.add_argument("--iphone-app", type=Path)
    args = parser.parse_args()
    check(args.android_apk, args.iphone_app)
