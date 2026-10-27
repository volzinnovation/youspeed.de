#!/usr/bin/env python3
"""Measure actual native qualifier/cache cost on supplied real-mask envelopes.

External document parsing is separately timed; core-internal copies/parsing remain in
API measurements. This is host-only descriptive timing, not device/3 ms acceptance.
"""
import argparse
import hashlib
import json
import math
import os
from pathlib import Path
import platform
import statistics
import subprocess
import tempfile

from compare_semantic_hint_platforms import ROOT, kotlin_classpath

METRICS = ("qualificationMs", "cacheConstructionMs", "acceptedOfferMs", "currentRevalidationMs", "cycleMs")


def distribution(samples):
    if not samples or any(not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0 for value in samples):
        raise ValueError("Expected nonempty finite nonnegative timing samples")
    ordered = sorted(samples)
    return dict(samples=len(samples), minimumMs=ordered[0], medianMs=statistics.median(ordered),
                meanMs=statistics.mean(ordered), p95NearestRankMs=ordered[math.ceil(.95 * len(ordered)) - 1], maximumMs=ordered[-1])


def run(vectors, output, warmups=3, repeats=12, classpath=None, typed=False):
    vectors = Path(vectors).resolve(); output = Path(output).resolve()
    if not 1 <= warmups <= 20 or not 3 <= repeats <= 100:
        raise ValueError("warmups must be 1..20; repeats 3..100")
    value = json.loads(vectors.read_text())
    accepted = [case for case in value["qualificationCases"] if case.get("expectedReason") == "qualified"]
    if not accepted or len({case["id"] for case in accepted}) != len(accepted):
        raise ValueError("Expected unique expected-qualified input masks")
    output.mkdir(parents=True, exist_ok=False)
    sources = [ROOT / "iphone/SpeedConsumerApp/LaneSemanticHint.swift",
               ROOT / "android/app/src/main/java/de/youspeed/android/alpha/LaneSemanticHint.kt",
               Path(__file__).with_name("SemanticHintBenchmark.swift"), Path(__file__).with_name("SemanticHintBenchmark.kt")]
    cp = kotlin_classpath(classpath)
    report = dict(schemaVersion=1, inputRepresentation="typed_buffers" if typed else "json_bridge", scope="Host-only descriptive timing; no phone, live camera, asynchronous scheduling, sustained thermal or 3 ms acceptance claim.",
                  host=dict(system=platform.system(), release=platform.release(), machine=platform.machine(), processor=platform.processor()),
                  inputPath=str(vectors), inputSha256=hashlib.sha256(vectors.read_bytes()).hexdigest(),
                  warmupsPerCase=warmups, measuredRepetitionsPerCase=repeats,
                  externalParsingExcludedFromAPI=True, coreInternalCopiesIncluded=True,
                  measurementNotes=[
                      "External file read and whole-document parse are measured once per fresh process; parsing includes all input cases, even rejection controls.",
                      "API samples use already-parsed metadata and, in typed mode, materialized native arrays. Mask materialization is measured separately per case.",
                      "Accepted cache offer includes ownership/validation cost; the immutable accepted-evidence cache never serializes or rescans masks during current revalidation.",
                      "Each cache offer uses a newly constructed owner cache; construction is measured separately, with no duplicate-result fast path.",
                      "Current revalidation checks the last accepted owner metadata/time against immutable evidence; it does not read a clock or scan mask scores/validity.",
                      "Swift drains an autorelease pool after each cycle; cycle timing includes that drain and lifecycle overhead beyond individual API samples.",
                      "Kotlin uses ordinary JVM GC with no forced collection. JVM startup/JIT, GC and host contention limit cross-platform comparisons.",
                      "Only 3 warmups and 12 measured repetitions per mask by default: small descriptive samples, not a confidence bound or sustained performance qualification.",
                      "Full cycle includes standalone qualify, cache construction, offer and current; it is a benchmark sequence, not a proposed production frame schedule.",
                  ], platforms={})
    with tempfile.TemporaryDirectory(prefix="semantic-hint-benchmark-") as temporary:
        temporary = Path(temporary); swift = temporary / "swift"; jar = temporary / "kotlin.jar"
        subprocess.run(["swiftc", "-O", str(sources[0]), str(sources[2]), "-o", str(swift)], check=True)
        subprocess.run(["kotlinc", str(sources[1]), str(sources[3]), "-cp", cp, "-include-runtime", "-d", str(jar)], check=True)
        commands = {"swift": [str(swift)], "kotlin": ["java", "-cp", str(jar) + os.pathsep + cp, "de.youspeed.android.alpha.SemanticHintBenchmarkKt"]}
        for name, command in commands.items():
            target = output / f"{name}.json"
            with target.open("w") as handle:
                subprocess.run(command + [str(vectors), str(warmups), str(repeats)] + (["--typed"] if typed else []), stdout=handle, check=True)
            native = json.loads(target.read_text())
            if [case["id"] for case in native["cases"]] != [case["id"] for case in accepted]:
                raise ValueError("Native benchmark did not use every selected mask")
            for case in native["cases"]:
                if len(case["samples"]) != repeats:
                    raise ValueError("Incomplete native samples")
            summary = {key: native[key] for key in ("clock", "inputBytes", "inputReadMs", "inputParseMs")}
            summary["distributions"] = {metric: distribution([sample[metric] for case in native["cases"] for sample in case["samples"]]) for metric in METRICS}
            summary["typedMaterializationTotalMs"] = sum(case["typedMaterializationMs"] for case in native["cases"])
            summary["perMask"] = [dict(id=case["id"], width=case["width"], height=case["height"], typedMaterializationMs=case["typedMaterializationMs"],
                distributions={metric: distribution([sample[metric] for sample in case["samples"]]) for metric in METRICS}) for case in native["cases"]]
            report["platforms"][name] = summary
    sources.append(Path(__file__))
    for path in sources:
        destination = output / "sources" / path.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(path.read_bytes())
    report["sourceHashes"] = {str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources}
    report["status"] = "measured"
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({name: data["distributions"] for name, data in report["platforms"].items()}, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vectors", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--warmups", type=int, default=3)
    parser.add_argument("--repeats", type=int, default=12)
    parser.add_argument("--kotlin-classpath")
    parser.add_argument("--typed", action="store_true")
    args = parser.parse_args(); run(args.vectors, args.output, args.warmups, args.repeats, args.kotlin_classpath, args.typed)


if __name__ == "__main__":
    main()
