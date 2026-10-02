#!/usr/bin/env python3
"""Compare the native Swift/Kotlin render fits for recorded boundary NDJSON.

Requires Xcode, kotlinc and Java. Runs the production helpers, preserves their
source snapshots and refuses to replace existing evidence. Input rows have
boundaries[].points as normalized [x,y] pairs (as emitted by replay_path.py).
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import shutil
import subprocess

ROOT = Path(__file__).resolve().parents[2]
KOTLIN_RUNNER = r'''package de.youspeed.android.alpha
import java.io.File
fun main(args: Array<String>) {
    File(args[1]).bufferedWriter().use { output ->
        File(args[0]).forEachLine { line ->
            val values = if (line.isBlank()) emptyList() else line.split(" ").map(String::toDouble)
            val points = values.chunked(2).map { LanePoint(it[0], it[1]) }
            output.write(LaneBoundaryBezier.fit(points).joinToString(prefix="[", postfix="]") { curve ->
                listOf(curve.start, curve.control1, curve.control2, curve.end)
                    .joinToString(prefix="[", postfix="]") { "[${it.x},${it.y}]" }
            })
            output.newLine()
        }
    }
}
'''


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    input_path = args.input.resolve()
    rows = [json.loads(line) for line in input_path.read_text().splitlines() if line.strip()]
    boundaries = [boundary["points"] for row in rows for boundary in row.get("boundaries", [])]
    if not boundaries:
        raise ValueError("No boundaries to compare")
    for points in boundaries:
        if any(not isinstance(p, list) or len(p) != 2 or
               any(type(v) not in (int, float) or not math.isfinite(v) for v in p) for p in points):
            raise ValueError("Expected each boundary point to be a finite [x,y] pair")
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    sources = output / "sources"
    sources.mkdir()
    paths = [ROOT / "iphone/SpeedConsumerApp" / name for name in
             ("LaneDetection.swift", "LaneBoundaryBezier.swift")]
    paths += [ROOT / "android/app/src/main/java/de/youspeed/android/alpha" / name for name in
              ("LaneDetection.kt", "LaneBoundaryBezier.kt")]
    paths += [ROOT / "scripts/lanes/RenderLaneCurves.swift"]
    for path in paths:
        shutil.copyfile(path, sources / path.name)
    (sources / "VerifyLaneCurves.kt").write_text(KOTLIN_RUNNER)
    (output / "points.txt").write_text("\n".join(" ".join(str(v) for p in points for v in p)
                                                       for points in boundaries) + "\n")
    subprocess.run(["xcrun", "swiftc", "-O", "-module-cache-path", str(output / "swift-cache"),
                    *(str(sources / name) for name in
                      ("LaneDetection.swift", "LaneBoundaryBezier.swift", "RenderLaneCurves.swift")),
                    "-o", str(output / "render-lane-curves")], check=True)
    subprocess.run([str(output / "render-lane-curves"), str(input_path), str(output / "swift.ndjson")], check=True)
    subprocess.run(["kotlinc", *(str(sources / name) for name in
                                 ("LaneDetection.kt", "LaneBoundaryBezier.kt", "VerifyLaneCurves.kt")),
                    "-include-runtime", "-d", str(output / "kotlin.jar")], check=True)
    subprocess.run(["java", "-jar", str(output / "kotlin.jar"), str(output / "points.txt"),
                    str(output / "kotlin.ndjson")], check=True)
    swift = [boundary["segments"] for line in (output / "swift.ndjson").read_text().splitlines()
             for boundary in json.loads(line)["renderCurves"]]
    kotlin = [json.loads(line) for line in (output / "kotlin.ndjson").read_text().splitlines()]
    if len(swift) != len(kotlin) or len(swift) != len(boundaries):
        raise AssertionError("Boundary count differs")
    maximum = 0.0
    for index, (a, b) in enumerate(zip(swift, kotlin)):
        if len(a) != len(b):
            raise AssertionError(f"Cubic segment count differs at boundary {index}")
        for sa, sb in zip(a, b):
            for pa, pb in zip(sa, sb):
                for xa, xb in zip(pa, pb):
                    maximum = max(maximum, abs(xa - xb))
    summary = dict(input=str(input_path), inputSha256=digest(input_path), boundaries=len(boundaries),
                   sourcePolylineSegments=sum(max(0, len(points) - 1) for points in boundaries),
                   cubicSegments=sum(len(curves) for curves in swift), maximumCoordinateDifference=maximum,
                   tolerance=1e-12, passed=maximum <= 1e-12,
                   sources={path.name: digest(sources / path.name) for path in paths})
    (output / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary, indent=2))
    if not summary["passed"]:
        raise AssertionError("Native curve coordinates differ beyond tolerance")


if __name__ == "__main__":
    main()
