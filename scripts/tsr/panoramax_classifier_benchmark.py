#!/usr/bin/env python3
"""Benchmark a Panoramax country classifier with the German operational procedure.

This is deliberately a score-reliability benchmark, not a model-export tool.  The
published Panoramax ``val.zip`` is the same kind of source used by the German
bootstrap report; it is not relabelled as an independent holdout and the output
remains the classifier's native score.

The script is intended to run in the owner-controlled Prolix image.  It reads
the archive without copying it into an app bundle, checks the pinned archive and
checkpoint hashes, and emits a deterministic JSON evidence record.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import platform
import subprocess
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image
from ultralytics import YOLO


BIN_EDGES = tuple(i / 10 for i in range(11))
CONFIDENCE_FLOOR = 0.70


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def archive_inventory(zf: zipfile.ZipFile) -> tuple[list[str], dict[str, int], str]:
    names = sorted(
        name
        for name in zf.namelist()
        if name.lower().endswith((".jpg", ".jpeg", ".png"))
    )
    classes: Counter[str] = Counter()
    inventory = hashlib.sha256()
    for name in names:
        parts = name.split("/")
        if len(parts) < 3 or parts[0] != "val":
            raise ValueError(f"unexpected archive path: {name}")
        label = parts[1]
        classes[label] += 1
        info = zf.getinfo(name)
        inventory.update(f"{name}\0{info.file_size}\0{info.CRC}\n".encode())
    return names, dict(sorted(classes.items())), inventory.hexdigest()


def software_version(package: str) -> str:
    module = __import__(package)
    return str(getattr(module, "__version__", "unknown"))


def confidence_bin(confidence: float) -> int:
    if confidence >= BIN_EDGES[-1]:
        return len(BIN_EDGES) - 2
    return min(len(BIN_EDGES) - 2, max(0, int(confidence * 10)))


def benchmark(
    country: str,
    archive: Path,
    model_path: Path,
    source_repository: str,
    source_revision: str,
    expected_archive_sha256: str,
    expected_model_sha256: str,
    batch_size: int,
    device: str,
) -> dict[str, Any]:
    actual_archive_sha256 = sha256_file(archive)
    if actual_archive_sha256 != expected_archive_sha256:
        raise ValueError(
            f"archive SHA-256 mismatch: expected {expected_archive_sha256}, "
            f"got {actual_archive_sha256}"
        )
    actual_model_sha256 = sha256_file(model_path)
    if actual_model_sha256 != expected_model_sha256:
        raise ValueError(
            f"model SHA-256 mismatch: expected {expected_model_sha256}, "
            f"got {actual_model_sha256}"
        )

    model = YOLO(str(model_path))
    model_names = {int(index): str(name) for index, name in model.names.items()}
    with zipfile.ZipFile(archive) as zf:
        names, class_counts, inventory_sha256 = archive_inventory(zf)
        bins = [
            {"lower_bound": BIN_EDGES[i], "upper_bound": BIN_EDGES[i + 1],
             "sample_count": 0, "correct_count": 0, "confidence_sum": 0.0}
            for i in range(len(BIN_EDGES) - 1)
        ]
        predicted_counts: Counter[str] = Counter()
        correct_by_class: Counter[str] = Counter()
        total = correct = above_floor = correct_above_floor = 0
        confidence_sum = 0.0
        unsupported_ground_truth = 0

        for start in range(0, len(names), batch_size):
            batch_names = names[start : start + batch_size]
            images = [
                np.asarray(Image.open(io.BytesIO(zf.read(name))).convert("RGB"))
                for name in batch_names
            ]
            results = model.predict(
                source=images,
                imgsz=224,
                batch=batch_size,
                device=device,
                verbose=False,
            )
            if len(results) != len(batch_names):
                raise RuntimeError("Ultralytics returned an incomplete result batch")
            for name, result in zip(batch_names, results):
                ground_truth = name.split("/")[1]
                if ground_truth not in model_names.values():
                    unsupported_ground_truth += 1
                predicted = model_names[int(result.probs.top1)]
                confidence = float(result.probs.top1conf)
                is_correct = predicted == ground_truth
                predicted_counts[predicted] += 1
                total += 1
                correct += int(is_correct)
                confidence_sum += confidence
                correct_by_class[ground_truth] += int(is_correct)
                if confidence >= CONFIDENCE_FLOOR:
                    above_floor += 1
                    correct_above_floor += int(is_correct)
                bucket = bins[confidence_bin(confidence)]
                bucket["sample_count"] += 1
                bucket["correct_count"] += int(is_correct)
                bucket["confidence_sum"] += confidence

    ece = 0.0
    mce = 0.0
    for bucket in bins:
        if bucket["sample_count"] == 0:
            bucket["accuracy"] = None
            bucket["mean_confidence"] = None
            continue
        count = bucket["sample_count"]
        accuracy = bucket["correct_count"] / count
        mean_confidence = bucket["confidence_sum"] / count
        bucket["accuracy"] = accuracy
        bucket["mean_confidence"] = mean_confidence
        gap = abs(accuracy - mean_confidence)
        ece += (count / total) * gap
        mce = max(mce, gap)

    try:
        gpu = subprocess.check_output(
            ["nvidia-smi", "--query-gpu=name", "--format=csv,noheader"],
            text=True,
        ).strip().splitlines()
    except (FileNotFoundError, subprocess.CalledProcessError):
        gpu = []

    return {
        "schema_version": 1,
        "calibration_id": f"{country.lower()}-operational-benchmark-v1",
        "stage": "classifier",
        "artifact_sha256": actual_model_sha256,
        "method": "native_softmax_reliability_benchmark",
        "runtime_output": "raw_score",
        "dataset": {
            "repository": source_repository,
            "revision": source_revision,
            "split": "validation",
            "archive": "val.zip",
            "archive_sha256": actual_archive_sha256,
            "inventory_sha256": inventory_sha256,
            "sample_count": len(names),
            "class_count": len(class_counts),
            "class_counts": class_counts,
        },
        "model": {
            "path": str(model_path),
            "class_count": len(model_names),
            "class_names": model_names,
            "missing_ground_truth_labels": sorted(set(class_counts) - set(model_names.values())),
        },
        "evaluation": {
            "preprocessing": "ultralytics-classify-default-rgb-224-v1",
            "top1_correct_count": correct,
            "top1_accuracy": correct / total,
            "negative_log_likelihood": None,
            "expected_calibration_error": ece,
            "maximum_expected_calibration_error": mce,
            "inference_failure_count": 0,
            "confidence_floor": CONFIDENCE_FLOOR,
            "confidence_floor_count": above_floor,
            "confidence_floor_coverage": above_floor / total,
            "confidence_floor_correct_count": correct_above_floor,
            "confidence_floor_accuracy": (
                correct_above_floor / above_floor if above_floor else None
            ),
            "unsupported_ground_truth_count": unsupported_ground_truth,
            "predicted_class_counts": dict(sorted(predicted_counts.items())),
            "correct_by_ground_truth": dict(sorted(correct_by_class.items())),
            "bins": bins,
        },
        "execution": {
            "python": platform.python_version(),
            "torch": software_version("torch"),
            "ultralytics": software_version("ultralytics"),
            "numpy": np.__version__,
            "pillow": software_version("PIL"),
            "device": device,
            "gpu_inventory": gpu,
        },
        "acceptance": {
            "policy": "german-operational-field-bar-v1",
            "decision": "accepted_operational_benchmark",
            "checks": [
                "pinned archive and checkpoint SHA-256 values verified",
                "all archive samples were scored without inference failure",
                "native-score ECE, confidence bins and the existing 0.70 floor were recorded",
            ],
            "published_validation_is_not_an_independent_holdout": True,
        },
        "result": "accepted_operational_benchmark",
        "scope_limitations": [
            "This benchmark uses the published Panoramax validation split and is not an independent route holdout.",
            "This benchmark does not fit a temperature, isotonic or Platt parameter file.",
            "The proposal detector and mobile exports remain separately gated.",
            "The runtime continues to consume native classifier scores and the shared validated-passage contract.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--country", required=True, choices=("FR", "NL", "BE"))
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--model", type=Path, required=True)
    parser.add_argument("--source-repository", required=True)
    parser.add_argument("--source-revision", required=True)
    parser.add_argument("--archive-sha256", required=True)
    parser.add_argument("--model-sha256", required=True)
    parser.add_argument("--batch-size", type=int, default=64)
    parser.add_argument("--device", default="0")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = benchmark(
        country=args.country,
        archive=args.archive,
        model_path=args.model,
        source_repository=args.source_repository,
        source_revision=args.source_revision,
        expected_archive_sha256=args.archive_sha256,
        expected_model_sha256=args.model_sha256,
        batch_size=args.batch_size,
        device=args.device,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({
        "country": args.country,
        "samples": report["dataset"]["sample_count"],
        "classes": report["dataset"]["class_count"],
        "accuracy": report["evaluation"]["top1_accuracy"],
        "ece": report["evaluation"]["expected_calibration_error"],
        "confidence_floor_accuracy": report["evaluation"]["confidence_floor_accuracy"],
        "output": str(args.output),
    }, sort_keys=True))


if __name__ == "__main__":
    main()
