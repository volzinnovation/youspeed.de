#!/usr/bin/env python3
"""Build the shared physical-phone regression DB and cases from preserved OSM.

Run with the settlement requirements installed, for example:
  python scripts/map/build_directional_speed_fixture.py --output-dir /tmp/directional-speeds

The fixture contains public OSM source geometry/tags, never personal drive data.
Both phones must receive the same generated SQLite and cases.json bytes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sqlite3
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "tests/map/fixtures/baden-wuerttemberg-directional-speeds-20260913.osm"


def source_cases(fixture: Path) -> list[dict]:
    source = ET.parse(fixture).getroot()
    nodes = {node.attrib["id"]: (float(node.attrib["lat"]), float(node.attrib["lon"]))
             for node in source.findall("node")}
    cases = []
    for way in source.findall("way"):
        points = [nodes[node.attrib["ref"]] for node in way.findall("nd")]
        tags = {tag.attrib["k"]: tag.attrib["v"] for tag in way.findall("tag")}
        # A midpoint of the longest source segment avoids junctions and has a
        # precisely known local direction, including on the curved K 4331 way.
        a, b = max(zip(points, points[1:]), key=lambda pair:
                   (pair[1][0] - pair[0][0]) ** 2 +
                   ((pair[1][1] - pair[0][1]) * math.cos(math.radians(pair[0][0]))) ** 2)
        lat_a, lat_b = math.radians(a[0]), math.radians(b[0])
        longitude_delta = math.radians(b[1] - a[1])
        heading = math.degrees(math.atan2(
            math.sin(longitude_delta) * math.cos(lat_b),
            math.cos(lat_a) * math.sin(lat_b) - math.sin(lat_a) * math.cos(lat_b) * math.cos(longitude_delta),
        )) % 360
        cases.append({"wayId": way.attrib["id"], "lat": (a[0] + b[0]) / 2,
                      "lon": (a[1] + b[1]) / 2, "forwardHeadingDeg": heading,
                      "expectedForwardKmh": int(tags["maxspeed:forward"]),
                      "expectedBackwardKmh": int(tags["maxspeed:backward"])})
    return cases


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output_dir.resolve()
    database = output / "speeds_v3.sqlite"
    if database.exists():
        parser.error("Choose a new output directory; an existing shared phone fixture must not be replaced")
    provenance = json.loads(FIXTURE.with_suffix(".source.json").read_text())
    if hashlib.sha256(FIXTURE.read_bytes()).hexdigest() != provenance["fixture_sha256"]:
        raise ValueError("Historical OSM fixture does not match its source manifest")
    output.mkdir(parents=True, exist_ok=True)
    scripts = Path(__file__).resolve().parent
    artifacts = [output / name for name in ("ways.idx", "ways.meta", "areas.idx", "ways.lookup", "ways.geom", "ways.geom.lookup")]
    subprocess.run([sys.executable, str(scripts / "pack_runtime_artifacts_pyosmium.py"), str(FIXTURE), *map(str, artifacts)], check=True)
    subprocess.run([sys.executable, str(scripts / "build_spatialite_v3.py"), "--v1-dist", str(output),
                    "--out-db", str(database), "--input-pbf", str(FIXTURE), "--build-settlement-context",
                    "--country-code", "DE", "--build-way-links", "--way-links-schema", "detailed"], check=True)
    cases = source_cases(FIXTURE)
    with sqlite3.connect(database) as conn:
        for case in cases:
            expected = (None, str(case["expectedForwardKmh"]), str(case["expectedBackwardKmh"]))
            actual = conn.execute("SELECT maxspeed,maxspeed_forward,maxspeed_backward FROM ways WHERE way_id=?", (case["wayId"],)).fetchone()
            if actual != expected:
                raise ValueError(f"Source-to-SQLite speed loss for way {case['wayId']}: {actual}")
        if conn.execute("SELECT COUNT(*) FROM settlement_segment WHERE inside_city IS NOT NULL").fetchone()[0]:
            raise ValueError("Numeric directional speeds must not manufacture settlement evidence")
    result = {"databaseSHA256": hashlib.sha256(database.read_bytes()).hexdigest(), "cases": cases}
    (output / "cases.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"database": str(database), "cases": str(output / "cases.json"),
                      "databaseSHA256": result["databaseSHA256"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
