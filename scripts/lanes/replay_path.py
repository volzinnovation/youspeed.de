#!/usr/bin/env python3
"""Compare production Swift/Kotlin path geometry on identical synthetic inputs.

All compilation and rendered pixel buffers stay in a temporary directory. This
checks implementation parity and engineering controls, never road accuracy or
device latency. Requires the existing Android kotlinx JSON jars, no downloads.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import random
import re
import shutil
import subprocess
import tempfile

from replay import render, compare

ROOT = Path(__file__).resolve().parents[2]
ANDROID = ROOT / "android/app/src/main/java/de/youspeed/android/alpha"
IPHONE = ROOT / "iphone/SpeedConsumerApp"


def canonical(value):
    if isinstance(value, dict):
        return {key: canonical(item) for key, item in value.items() if item is not None}
    if isinstance(value, list):
        return [canonical(item) for item in value]
    return value


def classpath():
    cache = Path(os.environ.get("GRADLE_USER_HOME", Path.home() / ".gradle")) / "caches/modules-2/files-2.1/org.jetbrains.kotlinx"
    jars = []
    for artifact in ("kotlinx-serialization-core-jvm", "kotlinx-serialization-json-jvm"):
        found = [p for p in (cache / artifact / "1.7.3").glob("*/*.jar") if not p.name.endswith(("-sources.jar", "-javadoc.jar"))]
        if len(found) != 1:
            raise SystemExit("Resolve the Android Gradle dependencies or pass --kotlin-classpath.")
        jars.extend(found)
    return os.pathsep.join(map(str, jars))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=ROOT / "shared/tsr/path-evidence/synthetic-v1.json")
    parser.add_argument("--output", type=Path, help="Optional JSON report; no checked-in result is changed by default")
    parser.add_argument("--kotlin-classpath")
    args = parser.parse_args()
    for tool in ("swiftc", "kotlinc", "java"):
        if not shutil.which(tool):
            parser.error(f"{tool} is required on PATH")
    fixture = json.loads(args.fixtures.read_text())
    if fixture["schemaVersion"] != 1 or fixture["provenance"] != "synthetic_engineering_only":
        parser.error("Expected the synthetic v1 fixture contract")
    sources = [IPHONE / name for name in ("LaneDetection.swift", "RoadBoundaryDetector.swift", "RoadPathEvidence.swift")]
    sources += [ANDROID / name for name in ("LaneDetection.kt", "RoadBoundaryDetector.kt", "RoadPathEvidence.kt")]
    sources += [Path(__file__), Path(__file__).with_name("PathReplay.kt"), Path(__file__).with_name("path_replay.swift")]
    cp = args.kotlin_classpath or classpath()
    with tempfile.TemporaryDirectory(prefix="youspeed-path-replay-") as directory:
        work = Path(directory)
        manifest = dict(fixture, boundaryCases=[])
        ids = set()
        for case in fixture["boundaryCases"] + fixture["pathCases"]:
            if not re.fullmatch(r"[A-Za-z0-9_-]+", case["id"]) or case["id"] in ids:
                parser.error("Fixture IDs must be unique and filesystem-safe")
            ids.add(case["id"])
        for case in fixture["boundaryCases"]:
            width, height = case["width"], case["height"]
            if not (64 <= width <= 384 and 64 <= height <= 216):
                parser.error("Boundary fixture outside bounded pixel contract")
            pixels = render(case, width, height)
            if "noiseSeed" in case:
                rng = random.Random(case["noiseSeed"])
                pixels = bytearray(rng.randrange(256) for _ in pixels)
            path = work / (case["id"] + ".gray")
            path.write_bytes(pixels)
            manifest["boundaryCases"].append(dict(case, pixelsPath=str(path)))
        input_file = work / "inputs.json"
        input_file.write_text(json.dumps(manifest, allow_nan=False))
        swift, jar = work / "swift", work / "kotlin.jar"
        subprocess.run(["swiftc", "-O", "-module-cache-path", str(work / "swift-cache"), *map(str, sources[:3]),
                        str(Path(__file__).with_name("path_replay.swift")), "-o", str(swift)], check=True)
        subprocess.run(["kotlinc", *map(str, sources[3:6]), str(Path(__file__).with_name("PathReplay.kt")),
                        "-cp", cp, "-include-runtime", "-d", str(jar)], check=True)
        left = canonical(json.loads(subprocess.check_output([str(swift), str(input_file)])))
        right = canonical(json.loads(subprocess.check_output(["java", "-cp", str(jar) + os.pathsep + cp,
                                                           "de.youspeed.android.alpha.PathReplayKt", str(input_file)])))
        compare(left, right)
        for case, actual in zip(fixture["boundaryCases"], left["boundaryCases"]):
            assert actual["id"] == case["id"]
            assert len(actual["boundaries"]) <= 6 and len(actual["corridors"]) <= 2
            expected = case.get("expected", {})
            for key in ("budgetExceeded", "operationCount"):
                if key in expected:
                    compare(expected[key], actual[key], f"{case['id']}.{key}")
            for field in ("boundaries", "corridors"):
                if "minimum" + field.title() in expected:
                    assert len(actual[field]) >= expected["minimum" + field.title()], case["id"]
                if "maximum" + field.title() in expected:
                    assert len(actual[field]) <= expected["maximum" + field.title()], case["id"]
            for boundary in actual["boundaries"]:
                if "boundaryCue" in expected:
                    compare(expected["boundaryCue"], boundary["cue"], f"{case['id']}.boundaryCue")
                if "maximumBoundaryConfidence" in expected:
                    assert boundary["confidence"] <= expected["maximumBoundaryConfidence"], case["id"]
                if "minimumSupportRows" in expected:
                    assert boundary["supportRows"] >= expected["minimumSupportRows"], case["id"]
        for case, actual in zip(fixture["pathCases"], left["pathCases"]):
            assert actual["id"] == case["id"]
            assert actual["result"]["shadowOnly"] is True
            for key, value in case["expected"].items():
                compare(value, actual["result"][key], f"{case['id']}.{key}")
        report = {"schemaVersion": 1, "parity": "passed", "fieldQualified": False, "numericTolerance": 1e-9,
                  "boundaryCases": len(left["boundaryCases"]), "pathCases": len(left["pathCases"]),
                  "scope": "Synthetic host parity only; no device, accuracy, mount or road-plane qualification",
                  "fixtureSha256": hashlib.sha256(args.fixtures.read_bytes()).hexdigest(),
                  "sourceHashes": {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources},
                  "results": left}
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + "\n")
        print(f"PASS: {report['boundaryCases']} boundary cases and {report['pathCases']} path cases; Swift/Kotlin parity within 1e-9.")


if __name__ == "__main__":
    main()
