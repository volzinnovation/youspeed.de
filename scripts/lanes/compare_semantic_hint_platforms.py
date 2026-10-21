#!/usr/bin/env python3
"""Compile real Swift/Kotlin qualifier cores and compare fault, cache and clock evidence.

Default input combines the 32 shared contract cases with native lifecycle/clock cases.
--vectors accepts prepared real-mask envelopes (same contract); this establishes semantic
parity only, never actual clock synchronization, calibration or model correctness.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import tempfile

import qualify_semantic_hints as reference

ROOT = Path(__file__).resolve().parents[2]
CONTRACT = ROOT / "shared/lanes/semantic-hint-v1"
BASELINE = {"confidence": 0.6, "supportRows": 5, "confirmations": 2, "trackId": 17}


def mutate(value, operations):
    for operation in operations:
        target = value
        for key in operation["path"][:-1]:
            target = target[key]
        key = operation["path"][-1]
        if operation.get("remove"):
            del target[key]
        else:
            target[key] = copy.deepcopy(operation["value"])


def expand(base, descriptor):
    context, hint = copy.deepcopy(base["context"]), copy.deepcopy(base["hint"])
    offset = descriptor.get("frameOffset", 0)
    if offset:
        for exposure in (context["exposure"], hint["exposure"]):
            exposure["frameId"] = f"frame-{10 + offset}"
            exposure["sourceTimeNs"] += offset * 100_000_000
            exposure["capturedAtNs"] += offset * 100_000_000
        context["now"]["atNs"] += offset * 100_000_000
        hint["arrival"]["atNs"] += offset * 100_000_000
    for scope in (context["scope"], hint["scope"]):
        scope["sessionGeneration"] += descriptor.get("generationOffset", 0)
    mutate(context, descriptor.get("contextMutations", []))
    mutate(hint, descriptor.get("hintMutations", []))
    result = {key: value for key, value in descriptor.items() if key not in
              ("frameOffset", "generationOffset", "contextMutations", "hintMutations", "missingHint")}
    result.update(context=context, hint=None if descriptor.get("missingHint") else hint)
    return result


def default_vectors():
    base = json.loads((CONTRACT / "synthetic-cases.json").read_text())
    extra = json.loads((CONTRACT / "native-cases.json").read_text())
    vectors = {"schemaVersion": 1, "policy": base["policy"],
               "qualificationCases": [expand(base, case) for case in base["cases"] + extra["qualificationCases"]],
               "cacheSequences": [], "clockCases": extra["clockCases"], "policyCases": []}
    for sequence in extra["cacheSequences"]:
        vectors["cacheSequences"].append({"id": sequence["id"], "context": expand(base, sequence)["context"],
                                          "operations": [expand(base, operation) for operation in sequence["operations"]]})
    for case in extra["policyCases"]:
        policy = copy.deepcopy(base["policy"]); mutate(policy, case["mutations"])
        vectors["policyCases"].append({"id": case["id"], "policy": policy, "expectedReason": case["expectedReason"]})
    return vectors


def typed_vectors():
    vectors = default_vectors()
    base = json.loads((CONTRACT / "synthetic-cases.json").read_text())
    extra = json.loads((CONTRACT / "typed-cases.json").read_text())
    vectors["qualificationCases"] = [row for row in vectors["qualificationCases"] if row["id"] not in extra["excludedJsonCaseIds"]]
    vectors["qualificationCases"].extend(expand(base, row) for row in extra["qualificationCases"])
    for sequence in extra["cacheSequences"]:
        vectors["cacheSequences"].append({"id": sequence["id"], "context": expand(base, sequence)["context"],
            "operations": [expand(base, row) for row in sequence["operations"]]})
    return vectors


def nonfinite(item):
    hint = copy.deepcopy(item.get("hint"))
    if hint is not None and item.get("nonfiniteScore"):
        hint["mask"]["probabilities"][0] = {"nan": float("nan"), "positive_infinity": float("inf"),
                                             "negative_infinity": -float("inf")}[item["nonfiniteScore"]]
    return hint


def record(result):
    output = {"reason": result.reason, "accepted": result.accepted, "captureAgeNs": result.capture_age_ns, "hint": None}
    hint = result.hint
    if hint is not None:
        packed = b"".join(struct.pack(">d", value) for value in hint.probabilities) + bytes(hint.validity)
        output["hint"] = dict(frameId=hint.frame_id, sourceTimeNs=hint.source_time_ns, sourceClockId=hint.source_clock_id,
            capturedAtNs=hint.captured_at_ns, clockId=hint.clock_id, arrivedAtNs=hint.arrived_at_ns,
            scope=json.loads(hint.scope_identity), geometry=json.loads(hint.geometry_identity),
            modelIdentity=json.loads(hint.model_identity), provenance=json.loads(hint.provenance_identity),
            width=hint.width, height=hint.height, maskSha256=hashlib.sha256(packed).hexdigest(), validCells=sum(hint.validity),
            unknownCellsStayUnknown=True, outsideCellsStayUnknown=True)
    return output


def reference_output(vectors):
    policy = reference.QualificationPolicy.from_mapping(vectors["policy"])
    output = {"qualificationCases": [], "cacheSequences": [], "policyCases": []}
    for case in vectors.get("qualificationCases", []):
        baseline = copy.deepcopy(BASELINE)
        result = reference.prepare_guidance(baseline, nonfinite(case), case["context"], policy)
        output["qualificationCases"].append(dict(record(result.qualification), id=case["id"],
            baselinePreserved=result.baseline is baseline and baseline == BASELINE, baseline=baseline))
    for sequence in vectors.get("cacheSequences", []):
        cache = reference.HintCache(policy, sequence["context"]); steps = []
        for operation in sequence["operations"]:
            op = operation["op"]
            if op == "offer":
                row = record(cache.offer(nonfinite(operation)))
            elif op == "current":
                row = record(cache.current())
            elif op == "advance":
                row = {"reason": cache.advance(operation["context"])}
            elif op == "reset":
                try:
                    cache.reset_scope(operation["context"]); reason = "reset"
                except ValueError as error:
                    reason = str(error)
                row = {"reason": reason}
            else:
                raise ValueError(f"Unknown operation {op}")
            row.update(current=record(cache.current()), latestSourceTimeNs=cache.latest_source_time_ns)
            steps.append(row)
        output["cacheSequences"].append({"id": sequence["id"], "steps": steps})
    for case in vectors.get("policyCases", []):
        try:
            reference.QualificationPolicy.from_mapping(case["policy"]); reason = "valid_policy"
        except ValueError:
            reason = "invalid_policy"
        output["policyCases"].append({"id": case["id"], "reason": reason})
    return output


def compare(left, right, path="root"):
    if type(left) is not type(right) and not (type(left) in (int, float) and type(right) in (int, float)):
        raise AssertionError(f"{path}: different types {type(left).__name__}/{type(right).__name__}")
    if isinstance(left, dict):
        if left.keys() != right.keys():
            raise AssertionError(f"{path}: keys differ")
        for key in left:
            compare(left[key], right[key], f"{path}.{key}")
    elif isinstance(left, list):
        if len(left) != len(right):
            raise AssertionError(f"{path}: lengths differ")
        for index, (a, b) in enumerate(zip(left, right)):
            compare(a, b, f"{path}[{index}]")
    elif left != right:
        raise AssertionError(f"{path}: {left!r} != {right!r}")


def check_expected(vectors, output):
    for field in ("qualificationCases", "clockCases", "policyCases"):
        for case, actual in zip(vectors.get(field, []), output[field]):
            if "expectedReason" in case and actual["reason"] != case["expectedReason"]:
                raise AssertionError(f"{case['id']}: expected {case['expectedReason']}, got {actual['reason']}")
            for expected, result in (("expectedRelativeNs", "relativeNs"), ("expectedExposure", "exposure")):
                if expected in case:
                    compare(case[expected], actual.get(result), case["id"])
    for sequence, actual in zip(vectors.get("cacheSequences", []), output["cacheSequences"]):
        for index, (operation, row) in enumerate(zip(sequence["operations"], actual["steps"])):
            if "expectedReason" in operation and operation["expectedReason"] != row["reason"]:
                raise AssertionError(f"{sequence['id']}/{index}: {row['reason']} != {operation['expectedReason']}")


def kotlin_classpath(explicit=None):
    if explicit:
        return explicit
    cache = Path(os.environ.get("GRADLE_USER_HOME", Path.home() / ".gradle")) / "caches/modules-2/files-2.1/org.jetbrains.kotlinx"
    jars = []
    for artifact in ("kotlinx-serialization-core-jvm", "kotlinx-serialization-json-jvm"):
        found = [path for path in (cache / artifact / "1.7.3").glob("*/*.jar") if not path.name.endswith(("-sources.jar", "-javadoc.jar"))]
        if len(found) != 1:
            raise ValueError("Resolve Android Gradle dependencies or supply --kotlin-classpath")
        jars.extend(found)
    return os.pathsep.join(map(str, jars))


def run(vectors, output, classpath=None, typed=False):
    for tool in ("swiftc", "kotlinc", "java"):
        if not shutil.which(tool):
            raise ValueError(f"{tool} required on PATH")
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    vector_path = output / "vectors.json"
    vector_path.write_text(json.dumps(vectors, separators=(",", ":"), allow_nan=False) + "\n")
    sources = [ROOT / "iphone/SpeedConsumerApp/LaneSemanticHint.swift",
               ROOT / "android/app/src/main/java/de/youspeed/android/alpha/LaneSemanticHint.kt",
               ROOT / "scripts/lanes/SemanticHintParity.swift", ROOT / "scripts/lanes/SemanticHintParity.kt"]
    cp = kotlin_classpath(classpath)
    with tempfile.TemporaryDirectory(prefix="lane-semantic-parity-") as temp:
        temp = Path(temp); swift = temp / "swift"; jar = temp / "kotlin.jar"
        subprocess.run(["swiftc", "-O", str(sources[0]), str(sources[2]), "-o", str(swift)], check=True)
        subprocess.run(["kotlinc", str(sources[1]), str(sources[3]), "-cp", cp, "-include-runtime", "-d", str(jar)], check=True)
        commands = {"swift": [str(swift), str(vector_path)],
                    "kotlin": ["java", "-cp", str(jar) + os.pathsep + cp, "de.youspeed.android.alpha.SemanticHintParityKt", str(vector_path)]}
        results = {}
        for name, command in commands.items():
            with (output / f"{name}.json").open("w") as target:
                subprocess.run(command + (["--typed"] if typed else []), stdout=target, check=True)
            results[name] = json.loads((output / f"{name}.json").read_text())
    compare(results["swift"], results["kotlin"])
    python = reference_output(vectors)
    for field, expected in python.items():
        compare(expected, results["swift"][field], "python." + field)
    check_expected(vectors, results["swift"])
    sources += [Path(__file__), ROOT / "scripts/lanes/qualify_semantic_hints.py"]
    for path in sources:
        destination = output / "sources" / path.relative_to(ROOT)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(path.read_bytes())
    report = dict(schemaVersion=1, status="passed", inputRepresentation="typed_buffers" if typed else "json_bridge", qualifierCases=len(vectors.get("qualificationCases", [])),
                  cacheSequences=len(vectors.get("cacheSequences", [])), cacheOperations=sum(len(row["operations"]) for row in vectors.get("cacheSequences", [])),
                  clockCases=len(vectors.get("clockCases", [])), policyCases=len(vectors.get("policyCases", [])),
                  allBaselineObjectsPreserved=all(row["baselinePreserved"] for row in results["swift"]["qualificationCases"]),
                  exactNativeAndPythonMaskParity=True, vectorsSha256=hashlib.sha256(vector_path.read_bytes()).hexdigest(),
                  sourceHashes={str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in sources},
                  scope="Actual Swift/Kotlin host cores: qualification, immutable evidence, owner cache, relative clock arithmetic. No mobile inference, actual clock synchronization, live mailbox, device latency or real-road accuracy claim.")
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report, indent=2))
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--vectors", type=Path, help="Prepared qualification/cache/clock vectors; may contain private real masks, keep outside Git")
    parser.add_argument("--output", required=True, type=Path, help="New output directory")
    parser.add_argument("--kotlin-classpath")
    parser.add_argument("--typed", action="store_true", help="Exercise native typed arrays and caller mutation controls")
    args = parser.parse_args()
    vectors = json.loads(args.vectors.read_text()) if args.vectors else typed_vectors() if args.typed else default_vectors()
    run(vectors, args.output, args.kotlin_classpath, args.typed)


if __name__ == "__main__":
    main()
