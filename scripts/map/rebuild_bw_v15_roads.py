#!/usr/bin/env python3
"""Rebuild BW road/settlement tables with the current v3 readiness capabilities.

The source PBF is explicit: this does not claim freshness or publish a release.
The MobiData runtime overlay is a subsequent step; this supplies its road base.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import shlex
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
REGION = "baden-wuerttemberg-v1.5-roads"


def commands(input_pbf: Path, geojson: Path, *, root: Path = ROOT, python: str = sys.executable):
    v1 = root / "mapdata/dist" / REGION
    output = root / "mapdata/dist-v3" / REGION
    fields = ["ways.idx", "ways.meta", "areas.idx", "ways.lookup", "ways.geom", "ways.geom.lookup"]
    files = [str(v1 / name) for name in fields]
    return [
        [python, str(root / "scripts/map/pack_runtime_artifacts_pyosmium.py"), str(input_pbf), *files],
        ["bash", str(root / "scripts/map/generate_manifest.sh"), REGION, str(input_pbf), *files, str(v1 / "manifest.json")],
        [python, str(root / "scripts/map/build_spatialite_v3.py"), "--v1-dist", str(v1),
         "--out-db", str(output / "speeds_v3.sqlite"), "--input-pbf", str(input_pbf),
         "--country-code", "DE", "--build-settlement-context", "--build-way-links",
         "--way-links-schema", "detailed", "--corridor-mode", "paired",
         "--traffic-sign-geojson", str(geojson)],
        [python, str(root / "scripts/map/validate_v3_testing_bundle.py"), "--db", str(output / "speeds_v3.sqlite"),
         "--require-settlement", "--out-json", str(output / "structural-validation.json")],
    ]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input-pbf", required=True, type=Path)
    parser.add_argument("--geojson", required=True, type=Path)
    parser.add_argument("--execute", action="store_true", help="Run local commands; default prints the plan")
    parser.add_argument("--replace-output", action="store_true", help="Allow replacing this script's existing generated road DB")
    args = parser.parse_args()
    for path in (args.input_pbf, args.geojson):
        if not path.is_file():
            parser.error(f"Missing input: {path}")
    output = ROOT / "mapdata/dist-v3" / REGION
    if args.execute and (output / "speeds_v3.sqlite").exists() and not args.replace_output:
        parser.error("Road output already exists; choose --replace-output to rebuild it explicitly")
    planned = commands(args.input_pbf.resolve(), args.geojson.resolve())
    for command in planned:
        print(shlex.join(command), flush=True)
        if args.execute:
            subprocess.run(command, check=True, cwd=ROOT)
    if args.execute:
        validation = json.loads((output / "structural-validation.json").read_text())
        if not validation.get("ready"):
            raise RuntimeError("Current road readiness validation did not pass")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
