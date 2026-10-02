#!/usr/bin/env python3
"""Prepare a duplicate-grouped FR crop experiment with the checkpoint vocabulary.

This is a development split of published Panoramax training crops, not a route
holdout. The archive does not provide reliable sequence/physical-sign IDs.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import random
import shutil
import stat
import tempfile
import unicodedata
import warnings
import zipfile

from PIL import Image, ImageOps

PINNED_SHA256 = "2cd16ce20ff6675de9a14b2a7362a0f27acf5d84df8543e0dfad445e65ecd538"
PINNED_REVISION = "ea75988e381f16e4677c5f42aa5fedea005f23d6"
TARGET_CLASSES = ("B31", "B33-30", "B33-50", "B33-70", "B33-90")
MAX_MEMBER_BYTES = 16 * 1024 * 1024
MAX_TOTAL_BYTES = 3 * 1024 * 1024 * 1024
MAX_MEMBERS = 100_000
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


class PreparationError(ValueError):
    pass


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def image_fingerprints(data: bytes) -> tuple[str, str, tuple[int, int]]:
    """Decode every image and identify exact pixels and coarse visual duplicates.

    The perceptual key uses a 256-bit difference hash, rounded aspect ratio and
    coarse RGB means. It intentionally does not claim exhaustive near-duplicate
    or same-physical-sign discovery.
    """
    with warnings.catch_warnings():
        warnings.simplefilter("error", Image.DecompressionBombWarning)
        with Image.open(io.BytesIO(data)) as encoded:
            encoded.load()
            rgb = ImageOps.exif_transpose(encoded).convert("RGB")
            if rgb.width < 1 or rgb.height < 1:
                raise PreparationError("Image has no pixels")
            pixel_hash = hashlib.sha256(
                f"{rgb.width}x{rgb.height}:".encode() + rgb.tobytes()
            ).hexdigest()
            small = rgb.convert("L").resize((17, 16), Image.Resampling.LANCZOS)
            values = small.tobytes()
            difference = 0
            for y in range(16):
                for x in range(16):
                    difference = (difference << 1) | (values[y * 17 + x] > values[y * 17 + x + 1])
            means = rgb.resize((1, 1), Image.Resampling.BOX).getpixel((0, 0))
            color = ":".join(str(v // 32) for v in means)
            perceptual = f"{difference:064x}:{rgb.width / rgb.height:.2f}:{color}"
            return pixel_hash, perceptual, rgb.size


def checked_members(archive: zipfile.ZipFile) -> list[zipfile.ZipInfo]:
    infos = archive.infolist()
    if len(infos) > MAX_MEMBERS:
        raise PreparationError("Archive has too many entries")
    names, images, total = set(), [], 0
    for info in infos:
        name = info.filename
        path = PurePosixPath(name)
        if ("\\" in name or "\x00" in name or path.is_absolute() or
                any(p in {".", ".."} for p in name.split("/")) or
                any(ord(c) < 32 for c in name) or ":" in name):
            raise PreparationError(f"Unsafe archive path: {name!r}")
        canonical = unicodedata.normalize("NFC", name.rstrip("/")).casefold()
        if canonical in names:
            raise PreparationError(f"Duplicate archive path: {name!r}")
        names.add(canonical)
        mode = info.external_attr >> 16
        if stat.S_ISLNK(mode) or (stat.S_IFMT(mode) not in {0, stat.S_IFREG, stat.S_IFDIR}):
            raise PreparationError(f"Non-regular archive entry: {name!r}")
        if info.flag_bits & 1:
            raise PreparationError("Encrypted archives are unsupported")
        if info.is_dir():
            continue
        if len(path.parts) != 3 or path.parts[0] != "train" or path.suffix.lower() not in IMAGE_SUFFIXES:
            raise PreparationError(f"Expected train/<class>/<image>: {name!r}")
        if not 0 < info.file_size <= MAX_MEMBER_BYTES:
            raise PreparationError(f"Image exceeds size limit: {name!r}")
        total += info.file_size
        if total > MAX_TOTAL_BYTES:
            raise PreparationError("Archive exceeds total image-byte limit")
        images.append(info)
    if not images:
        raise PreparationError("Archive has no training images")
    return sorted(images, key=lambda info: info.filename)


def duplicate_groups(records: list[dict]) -> list[list[int]]:
    parents = list(range(len(records)))

    def root(index):
        while parents[index] != index:
            parents[index] = parents[parents[index]]
            index = parents[index]
        return index

    seen = {}
    for index, record in enumerate(records):
        for kind in ("sha256", "pixel_sha256", "perceptual_key"):
            key = (kind, record[kind])
            if key in seen:
                parents[root(index)] = root(seen[key])
            else:
                seen[key] = index
    result = defaultdict(list)
    for index in range(len(records)):
        result[root(index)].append(index)
    return sorted(result.values(), key=lambda group: records[group[0]]["member_path"])


def prepare(archive_path: Path, output: Path, validation_fraction: float = .15,
            seed: int = 20260924, expected_sha256: str = PINNED_SHA256,
            target_multiplier: int = 4, model_vocabulary: Path | None = None) -> dict:
    if not 0 < validation_fraction < 1:
        raise PreparationError("validation_fraction must be between zero and one")
    if target_multiplier < 1:
        raise PreparationError("target_multiplier must be positive")
    if output.is_symlink() or (output.exists() and (not output.is_dir() or any(output.iterdir()))):
        raise PreparationError("Output must not exist or must be an empty directory")
    archive_hash = file_sha256(archive_path)
    if archive_hash != expected_sha256:
        raise PreparationError(f"Archive SHA-256 mismatch: {archive_hash}")
    vocabulary = None
    vocabulary_hash = None
    if model_vocabulary is not None:
        vocabulary = json.loads(model_vocabulary.read_text())
        vocabulary_hash = file_sha256(model_vocabulary)
        names = vocabulary.get("class_names") if isinstance(vocabulary, dict) else None
        if (not isinstance(names, list) or not names or
                not all(isinstance(name, str) and name and name not in {".", ".."} and
                        not any(character in name for character in "/\\:") and
                        all(ord(character) >= 32 for character in name) for name in names)):
            raise PreparationError("model-vocabulary must contain a nonempty class_names string array")
        if names != sorted(set(names)):
            raise PreparationError("Checkpoint vocabulary must match sorted unique ImageFolder class order")
    output.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=f".{output.name}-prepare-", dir=output.parent))
    try:
        records = []
        (stage / "source-images").mkdir()
        with zipfile.ZipFile(archive_path) as archive:
            infos = checked_members(archive)
            source_class_names = sorted({PurePosixPath(info.filename).parts[1] for info in infos})
            class_names = vocabulary["class_names"] if vocabulary else source_class_names
            missing_classes = sorted(set(class_names) - set(source_class_names))
            if missing_classes:
                raise PreparationError(f"Checkpoint classes missing from source archive: {missing_classes}")
            unsupported_classes = set(source_class_names) - set(class_names)
            for index, info in enumerate(infos):
                with archive.open(info) as source:
                    data = source.read(MAX_MEMBER_BYTES + 1)
                if len(data) != info.file_size or len(data) > MAX_MEMBER_BYTES:
                    raise PreparationError(f"Invalid image length: {info.filename}")
                try:
                    pixel_hash, perceptual, dimensions = image_fingerprints(data)
                except Exception as error:
                    raise PreparationError(f"Image cannot be decoded: {info.filename}: {error}") from error
                digest = hashlib.sha256(data).hexdigest()
                filename = f"{index:06d}-{digest[:16]}{PurePosixPath(info.filename).suffix.lower()}"
                source_relative = f"source-images/{filename}"
                (stage / source_relative).write_bytes(data)
                records.append({
                    "member_path": info.filename, "class_name": PurePosixPath(info.filename).parts[1],
                    "sha256": digest, "size_bytes": len(data), "pixel_sha256": pixel_hash,
                    "perceptual_key": perceptual, "dimensions": list(dimensions),
                    "source_path": source_relative, "output_paths": [],
                })
                if (index + 1) % 5000 == 0:
                    print(f"Decoded and inventoried {index + 1}/{len(infos)} images", flush=True)
        groups = duplicate_groups(records)
        by_class, quarantine = defaultdict(list), []
        for group in groups:
            group_id = hashlib.sha256("\n".join(records[i]["member_path"] for i in group).encode()).hexdigest()
            labels = {records[i]["class_name"] for i in group}
            for index in group:
                records[index]["duplicate_group"] = group_id
            if len(labels) > 1 or labels & unsupported_classes:
                for index in group:
                    records[index]["split"] = "quarantine"
                    records[index]["exclusion_reason"] = (
                        "class_not_in_checkpoint_vocabulary"
                        if records[index]["class_name"] in unsupported_classes
                        else "conflicting_labels_in_duplicate_group"
                    )
                    quarantine.append(index)
            else:
                by_class[next(iter(labels))].append(group)
        for class_name in class_names:
            for split in ("train", "val"):
                (stage / split / class_name).mkdir(parents=True, exist_ok=True)
            candidates = by_class[class_name]
            if not candidates:
                raise PreparationError(f"All examples for {class_name} have conflicting labels")
            rng = random.Random(f"{seed}:{class_name}")
            rng.shuffle(candidates)
            # Split by groups, retaining at least one group for training and
            # validation wherever two distinct groups exist.
            validation_groups = min(len(candidates) - 1, max(1, math.floor(len(candidates) * validation_fraction + .5)))
            if class_name in TARGET_CLASSES and len(candidates) < 2:
                raise PreparationError(f"{class_name} needs at least two non-conflicting duplicate groups")
            for group_index, group in enumerate(candidates):
                split = "val" if group_index < validation_groups else "train"
                for index in group:
                    record = records[index]
                    record["split"] = split
                    multiplier = target_multiplier if split == "train" and class_name in TARGET_CLASSES else 1
                    source = stage / record["source_path"]
                    for repeat in range(multiplier):
                        suffix = f"_repeat{repeat}" if repeat else ""
                        destination = Path(split) / class_name / f"{source.stem}{suffix}{source.suffix}"
                        os.link(source, stage / destination)
                        record["output_paths"].append(destination.as_posix())
        train_counts = {name: 0 for name in class_names}
        val_counts = {name: 0 for name in class_names}
        original_train_counts = {name: 0 for name in class_names}
        for record in records:
            if record["split"] == "train":
                train_counts[record["class_name"]] += len(record["output_paths"])
                original_train_counts[record["class_name"]] += 1
            elif record["split"] == "val":
                val_counts[record["class_name"]] += len(record["output_paths"])
        inventory = stage / "inventory.jsonl"
        with inventory.open("w") as stream:
            for record in records:
                stream.write(json.dumps(record, sort_keys=True) + "\n")
        summary = {
            "schema_version": 1, "status": "development_experiment_only",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_repository": "Panoramax/classified_fr_road_signs",
            "source_revision": PINNED_REVISION, "source_archive_sha256": archive_hash,
            "source_archive_bytes": archive_path.stat().st_size,
            "class_names": class_names, "source_image_count": len(records),
            "source_class_names": source_class_names,
            "source_class_counts": dict(sorted(Counter(record["class_name"] for record in records).items())),
            "unsupported_class_counts": dict(sorted(Counter(record["class_name"] for record in records
                                                                if record["class_name"] in unsupported_classes).items())),
            "model_vocabulary_sha256": vocabulary_hash,
            "source_model_sha256": vocabulary.get("source_sha256") if vocabulary else None,
            "checkpoint_head_preserved": vocabulary is not None,
            "train_counts": train_counts, "val_counts": val_counts,
            "original_train_counts": original_train_counts,
            "train_count": sum(train_counts.values()), "val_count": sum(val_counts.values()),
            "target_counts": {name: {"train": train_counts[name], "train_original": original_train_counts[name],
                                      "val": val_counts[name]} for name in TARGET_CLASSES if name in train_counts},
            "target_multiplier": target_multiplier, "oversampling": "train_only_hardlinks_after_group_split",
            "seed": seed, "validation_fraction": validation_fraction,
            "duplicate_group_count": len(groups), "quarantined_image_count": len(quarantine),
            "quarantine_reason_counts": dict(sorted(Counter(records[index]["exclusion_reason"]
                                                               for index in quarantine).items())),
            "grouping": "union_of_byte_sha256_decoded_pixel_sha256_and_dhash256_aspect_rgb_mean_keys",
            "grouping_limitations": [
                "No reliable route, sequence or physical-sign identifiers are supplied by the crop archive.",
                "Perceptual hashing is not exhaustive near-duplicate or physical-sign detection.",
                "Development validation is not an independent route holdout; the starting model may have seen these crops.",
                "The published val.zip is not used to train or select the development split.",
            ],
            "inventory_file": "inventory.jsonl", "inventory_sha256": file_sha256(inventory),
            "license": "Etalab-2.0 as declared by the pinned upstream dataset; retain source attribution",
        }
        (stage / "dataset-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
        if output.exists():
            output.rmdir()  # Fails safely if another writer added files meanwhile.
        stage.rename(output)
        return summary
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--validation-fraction", type=float, default=.15)
    parser.add_argument("--seed", type=int, default=20260924)
    parser.add_argument("--expected-sha256", default=PINNED_SHA256)
    parser.add_argument("--target-multiplier", type=int, default=4)
    parser.add_argument("--model-vocabulary", type=Path, required=True,
                        help="JSON exported from the checkpoint: class_names in head order and source_sha256")
    args = parser.parse_args()
    try:
        summary = prepare(args.archive, args.output, args.validation_fraction, args.seed,
                          args.expected_sha256, args.target_multiplier, args.model_vocabulary)
    except (PreparationError, OSError, zipfile.BadZipFile) as error:
        parser.exit(1, f"Preparation failed: {error}\n")
    print(json.dumps({"output": str(args.output), "train_count": summary["train_count"],
                      "val_count": summary["val_count"], "target_counts": summary["target_counts"]}, indent=2))


if __name__ == "__main__":
    main()
