#!/usr/bin/env python3
"""Execute shared survivor-selection cases in unchanged production Swift fusion.

Four unrelated local-observation model enums are copied verbatim from production
ConsumerModels.swift so host compilation does not require iOS download delegates.
No fusion/qualification logic is copied, translated or stubbed.
"""

from __future__ import annotations
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess

ROOT = Path(__file__).resolve().parents[3]
SOURCES = [
    "TrafficSignRecognition",
    "TrafficSignShadowRuntime",
    "TrafficSignApplicability",
    "TrafficSignApplicabilityIntegration",
    "TrafficSignPassageEvaluation",
    "RoadSpeedDefaults",
    "MatcherCoreModels",
    "DebugLogPersistence",
]
ENUMS = [
    "LocalObservationState",
    "LocalObservationOperation",
    "LocalObservationDirectionScope",
    "LocalObservationApplicability",
]


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def model_enums(source):
    parts = []
    for name in ENUMS:
        matches = re.findall(
            r"^enum " + name + r"\b[^\n]*\{\n.*?^}", source, re.M | re.S
        )
        if len(matches) != 1:
            raise ValueError("expected one production enum: " + name)
        parts.append(matches[0])
    return "import Foundation\n\n" + "\n\n".join(parts) + "\n"


SHIPPING_PACKS = [
    ROOT
    / "iphone/SpeedConsumerApp/TSRModelPacks/DE.panoramax-bootstrap.tsrmodelpack/manifest.json",
    ROOT
    / "android/app/src/main/assets/tsr/DE.panoramax-bootstrap.tsrmodelpack/manifest.json",
]


def shipping_mapping_bindings(fixture):
    cases = json.loads(fixture.read_text())["cases"]
    matches = [
        row
        for row in cases
        if row["id"] == "shipping_unknown_ancillary_alias_cannot_hide_mainline"
    ]
    if not matches:
        return []
    candidate = next(
        row for row in matches[0]["candidates"] if row["id"] == "no_overtaking:end"
    )
    expected = (
        candidate["id"],
        candidate["semantic_kind"],
        candidate["value"],
        candidate["class_threshold"],
    )
    bindings = []
    for path in SHIPPING_PACKS:
        entries = [
            row
            for row in json.loads(path.read_text())["class_mapping"]
            if row["class_id"] == candidate["id"]
        ]
        if len(entries) != 1:
            raise ValueError("shipping mapping missing or duplicated")
        row = entries[0]
        actual = (
            row["class_id"],
            row["semantic"]["kind"],
            row["semantic"].get("value"),
            row["threshold"],
        )
        if actual != expected:
            raise ValueError("fixture does not match shipping raw semantic tuple")
        bindings.append(
            {
                "path": str(path.relative_to(ROOT)),
                "sha256": sha(path),
                "tuple": list(actual),
            }
        )
    return bindings


def run(fixture, output):
    output, fixture = output.resolve(), fixture.resolve()
    if output == ROOT or ROOT in output.parents:
        raise ValueError("build evidence must be outside Git")
    output.mkdir(parents=True, exist_ok=False)
    native = ROOT / "iphone/SpeedConsumerApp"
    paths = [native / (name + ".swift") for name in SOURCES]
    models = native / "ConsumerModels.swift"
    harness = Path(__file__).with_name("ShadowSelection.swift")
    shipping = shipping_mapping_bindings(fixture)
    inputs = [
        *paths,
        models,
        harness,
        fixture,
        Path(__file__),
        *(SHIPPING_PACKS if shipping else []),
    ]
    source_hashes = {
        str(p.relative_to(ROOT)) if ROOT in p.parents else str(p): sha(p)
        for p in inputs
    }
    # Retain exact source bytes alongside the executable for later reproduction.
    for p in inputs:
        target = (
            output
            / "sources"
            / (p.relative_to(ROOT) if ROOT in p.parents else Path("fixture.json"))
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(p.read_bytes())
    support = output / "ProductionModelEnums.swift"
    support.write_text(model_enums(models.read_text()))
    binary = output / "shadow-selection-swift"
    command = [
        "swiftc",
        "-Onone",
        "-module-cache-path",
        str(output / "swift-cache"),
        *map(str, paths),
        str(support),
        str(harness),
        "-o",
        str(binary),
    ]
    with (output / "compile.log").open("w") as log:
        subprocess.run(
            command, stdout=log, stderr=subprocess.STDOUT, check=True, timeout=120
        )
    execution = subprocess.run(
        [str(binary), str(fixture)],
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    (output / "swift.json").write_text(execution.stdout)
    (output / "run.log").write_text(execution.stderr)
    result = json.loads(execution.stdout)
    if not result["passed"]:
        raise ValueError("native selection mismatch")
    if source_hashes != {
        str(p.relative_to(ROOT)) if ROOT in p.parents else str(p): sha(p)
        for p in inputs
    }:
        raise ValueError("production sources changed during run")
    receipt = {
        "schema_version": 1,
        "passed": True,
        "cases": len(result["cases"]),
        "sources": source_hashes,
        "production_model_enum_names": ENUMS,
        "shipping_mapping_bindings": shipping,
        "extracted_enum_sha256": sha(support),
        "binary_sha256": sha(binary),
        "output_sha256": sha(output / "swift.json"),
        "compiler": subprocess.check_output(
            ["swiftc", "--version"], text=True, stderr=subprocess.STDOUT
        ).strip(),
        "compile_command": command,
        "scope": "Actual production Swift first-frame fusion; no policy change, iOS app build, device deployment, road applicability or activation proof",
    }
    (output / "receipt.json").write_text(
        json.dumps(receipt, indent=2, sort_keys=True) + "\n"
    )
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--fixture",
        type=Path,
        default=ROOT / "shared/tsr/applicability/shadow-selection-fixtures.json",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(run(args.fixture, args.output), indent=2))


if __name__ == "__main__":
    main()
