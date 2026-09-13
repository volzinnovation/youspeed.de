#!/usr/bin/env python3
"""Compile both production lane cores and compare their output on identical pixels.

Requires Swift, Kotlin CLI and Java on PATH. No image packages or network access.
Build products and rendered fixtures live in a temporary directory. These
synthetic replays verify implementation parity, not real-road accuracy or phone
performance.
"""

import argparse
import json
import math
from pathlib import Path
import re
import shutil
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]


def render(case, width, height):
    pixels = bytearray([case.get("background", 55)]) * (width * height)
    for stroke in case.get("strokes", []):
        points = [(x * (width - 1), y * (height - 1)) for x, y in stroke["points"]]
        radius = stroke["width"] / 2
        for (ax, ay), (bx, by) in zip(points, points[1:]):
            dx, dy = bx - ax, by - ay
            squared_length = dx * dx + dy * dy
            for y in range(max(0, math.floor(min(ay, by) - radius)), min(height, math.ceil(max(ay, by) + radius) + 1)):
                for x in range(max(0, math.floor(min(ax, bx) - radius)), min(width, math.ceil(max(ax, bx) + radius) + 1)):
                    t = max(0, min(1, ((x - ax) * dx + (y - ay) * dy) / squared_length)) if squared_length else 0
                    if (x - ax - t * dx) ** 2 + (y - ay - t * dy) ** 2 <= radius * radius:
                        pixels[y * width + x] = stroke.get("brightness", 230)
    return pixels


def compare(left, right, path="result"):
    if isinstance(left, dict) and isinstance(right, dict):
        if left.keys() != right.keys():
            raise AssertionError(f"{path}: different keys")
        for key in left:
            compare(left[key], right[key], f"{path}.{key}")
    elif isinstance(left, list) and isinstance(right, list):
        if len(left) != len(right):
            raise AssertionError(f"{path}: different lengths")
        for index, (a, b) in enumerate(zip(left, right)):
            compare(a, b, f"{path}[{index}]")
    elif isinstance(left, (int, float)) and not isinstance(left, bool) and isinstance(right, (int, float)) and not isinstance(right, bool):
        if not math.isfinite(left) or not math.isfinite(right) or not math.isclose(left, right, rel_tol=1e-9, abs_tol=1e-9):
            raise AssertionError(f"{path}: {left} != {right}")
    elif left != right:
        raise AssertionError(f"{path}: {left!r} != {right!r}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", type=Path, default=ROOT / "shared/lanes/replay_cases.json")
    parser.add_argument("--output", type=Path, help="Optional parity report JSON")
    args = parser.parse_args()
    for tool in ("swiftc", "kotlinc", "java"):
        if not shutil.which(tool):
            parser.error(f"{tool} is required on PATH")
    fixture = json.loads(args.fixtures.read_text())
    with tempfile.TemporaryDirectory(prefix="youspeed-lane-replay-") as directory:
        work = Path(directory)
        manifest = []
        for case in fixture["cases"]:
            width, height = case.get("width", fixture["width"]), case.get("height", fixture["height"])
            if not (64 <= width <= 640 and 64 <= height <= 960):
                parser.error("Fixture dimensions are outside the bounded detector contract")
            name = case["name"]
            if not re.fullmatch(r"[A-Za-z0-9_-]+", name):
                parser.error(f"Invalid fixture name: {name!r}")
            path = work / f"{name}.gray"
            path.write_bytes(render(case, width, height))
            manifest.append(f"{name}\t{width}\t{height}\t{path}")
        input_file = work / "fixtures.tsv"
        input_file.write_text("\n".join(manifest))
        swift = work / "swift-replay"
        jar = work / "kotlin-replay.jar"
        subprocess.run(["swiftc", "-O", "-module-cache-path", str(work / "swift-cache"),
                        str(ROOT / "iphone/SpeedConsumerApp/LaneDetection.swift"),
                        str(ROOT / "scripts/lanes/replay.swift"), "-o", str(swift)], check=True)
        subprocess.run(["kotlinc", str(ROOT / "android/app/src/main/java/de/youspeed/android/alpha/LaneDetection.kt"),
                        str(ROOT / "scripts/lanes/Replay.kt"), "-include-runtime", "-d", str(jar)], check=True)
        swift_result = json.loads(subprocess.check_output([str(swift), str(input_file)]))
        kotlin_result = json.loads(subprocess.check_output(["java", "-jar", str(jar), str(input_file)]))
        compare(swift_result, kotlin_result)
        for index, case in enumerate(fixture["cases"]):
            result = swift_result[index * 3 + 2]
            expected = case["expected"]
            for side in ("left", "right"):
                if side in expected and (result[side] is not None) != expected[side]:
                    raise AssertionError(f"{case['name']}: expected {side} presence {expected[side]}")
            if "state" in expected and result["state"] != expected["state"]:
                raise AssertionError(f"{case['name']}: expected {expected['state']}, got {result['state']}")
        report = {"status": "passed", "case_count": len(fixture["cases"]),
                  "compared_frame_count": len(swift_result), "absolute_tolerance": 1e-9,
                  "scope": "host synthetic replay; not device or real-road validation", "results": swift_result}
        if args.output:
            args.output.write_text(json.dumps(report, indent=2) + "\n")
        print(f"PASS: {report['case_count']} cases, {report['compared_frame_count']} frames; matching states, boundaries and confidence.")


if __name__ == "__main__":
    main()
