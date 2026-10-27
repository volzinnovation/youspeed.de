#!/usr/bin/env python3
"""Verify native bounded score guidance changes selection only after existing gates/dwell.

Synthetic candidate fixtures exercise actual Swift/Kotlin selectors. No inference, camera,
paint accuracy or deployment claim. Production callers continue using default nil inputs.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

from compare_semantic_hint_platforms import compare, kotlin_classpath, ROOT

CORE = ("LaneDetection", "RoadBoundaryDetector", "RoadPathEvidence", "RoadBoundaryPresentationGate", "VisualRoadCalibration")


def check_expected(vectors, results):
    if len(vectors["cases"]) != len(results):
        raise AssertionError("Incomplete native selector output")
    for case, actual in zip(vectors["cases"], results):
        if actual["id"] != case["id"] or len(case["frames"]) != len(actual["frames"]):
            raise AssertionError("Selector identities/frame counts differ")
        for index, (frame, result) in enumerate(zip(case["frames"], actual["frames"])):
            path = f"{case['id']}/{index}"
            for variant in ("baseline", "guided"):
                compare(frame["expected" + variant.title()], result[variant]["visibleBoundaryIndices"], path + variant)
            if frame.get("expectedIdentical"):
                compare(result["baseline"], result["guided"], path + ".malformedFallback")
            if "expectedReason" in frame:
                if result["guided"]["selectionDecisions"][0]["reason"] != frame["expectedReason"]:
                    raise AssertionError(path + ": existing gate bypassed")
            if not result["rawEvidenceUnchanged"] or not result["confirmationCountsUnchanged"]:
                raise AssertionError(path + ": raw evidence or maturity changed")


def run(output, classpath=None):
    output = Path(output); output.mkdir(parents=True, exist_ok=False)
    fixture = ROOT / "shared/lanes/semantic-hint-v1/selector-cases.json"
    vectors = json.loads(fixture.read_text())
    cp = kotlin_classpath(classpath)
    sources = [ROOT / "iphone/SpeedConsumerApp" / (name + ".swift") for name in CORE]
    sources += [ROOT / "android/app/src/main/java/de/youspeed/android/alpha" / (name + ".kt") for name in CORE]
    harnesses = [Path(__file__).with_name("SemanticSelectorParity.swift"), Path(__file__).with_name("SemanticSelectorParity.kt")]
    with tempfile.TemporaryDirectory(prefix="lane-semantic-selector-") as directory:
        directory = Path(directory); swift = directory / "swift"; jar = directory / "kotlin.jar"
        subprocess.run(["swiftc", "-O", *map(str, sources[:len(CORE)]), str(harnesses[0]), "-o", str(swift)], check=True)
        subprocess.run(["kotlinc", *map(str, sources[len(CORE):]), str(harnesses[1]), "-cp", cp, "-include-runtime", "-d", str(jar)], check=True)
        commands = {"swift": [str(swift), str(fixture)], "kotlin": ["java", "-cp", str(jar) + os.pathsep + cp, "de.youspeed.android.alpha.SemanticSelectorParityKt", str(fixture)]}
        results = {}
        for name, command in commands.items():
            with (output / f"{name}.json").open("w") as target:
                subprocess.run(command, stdout=target, check=True)
            results[name] = json.loads((output / f"{name}.json").read_text())
    compare(results["swift"], results["kotlin"])
    check_expected(vectors, results["swift"])
    source_files = sources + harnesses + [Path(__file__), fixture]
    report = dict(schemaVersion=1, status="passed", scenarios=len(vectors["cases"]),
                  frames=sum(len(case["frames"]) for case in vectors["cases"]), numericTolerance=0,
                  rawEvidenceAndConfirmationsUnchanged=True, malformedInputMatchesBaseline=True,
                  demonstratedInitialRankChange=True, challengerMarginAndDwellPreserved=True,
                  sourceHashes={str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in source_files},
                  scope="Actual native selectors on synthetic mature candidates: bounded rank adjustment, existing rejection gates and stateful challenger dwell. Not road accuracy or device performance.")
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--kotlin-classpath")
    args = parser.parse_args(); run(args.output, args.kotlin_classpath)


if __name__ == "__main__":
    main()
