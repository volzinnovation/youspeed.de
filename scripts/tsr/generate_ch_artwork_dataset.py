#!/usr/bin/env python3
"""Build a CH classifier dataset by mixing real pseudo-labels with artwork renders.

Artwork renders provide coverage for classes that are absent from the current
Swiss imagery queue. They are synthetic augmentation, not a substitute for a
Swiss field-image holdout; the summary records that distinction explicitly.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
import shutil
from pathlib import Path
import re

from PIL import Image, ImageEnhance, ImageFilter


def safe_label(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.:-]+", "_", value)


def seed_for(seed: int, label: str, index: int) -> int:
    raw = f"{seed}\0{label}\0{index}".encode()
    return int.from_bytes(hashlib.sha256(raw).digest()[:8], "big")


def render(source: Image.Image, rng: random.Random) -> Image.Image:
    width = height = 320
    background = Image.new(
        "RGB",
        (width, height),
        (
            rng.randrange(80, 190),
            rng.randrange(80, 190),
            rng.randrange(80, 190),
        ),
    )
    sign = source.copy()
    bbox = sign.getbbox()
    if bbox:
        sign = sign.crop(bbox)
    edge = rng.uniform(95, 235)
    scale = edge / max(sign.size)
    sign = sign.resize(
        (max(1, round(sign.width * scale)), max(1, round(sign.height * scale))),
        Image.Resampling.LANCZOS,
    )
    sign = sign.rotate(rng.uniform(-8.0, 8.0), resample=Image.Resampling.BICUBIC, expand=True)
    x = (width - sign.width) // 2 + rng.randrange(-18, 19)
    y = (height - sign.height) // 2 + rng.randrange(-18, 19)
    background.paste(sign, (x, y), sign)
    if rng.random() < 0.7:
        background = ImageEnhance.Brightness(background).enhance(rng.uniform(0.75, 1.2))
    if rng.random() < 0.45:
        background = background.filter(ImageFilter.GaussianBlur(rng.uniform(0.2, 1.4)))
    return background


def copy_real(real_data: Path, output: Path) -> dict[str, int]:
    counts = {"train": 0, "val": 0}
    if not real_data:
        return counts
    for split in ("train", "val"):
        source_root = real_data / split
        if not source_root.is_dir():
            continue
        for source in source_root.rglob("*.jpg"):
            relative = source.relative_to(source_root)
            destination = output / split / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            counts[split] += 1
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--artwork-manifest", type=Path, required=True)
    parser.add_argument("--artwork-root", type=Path, required=True)
    parser.add_argument("--real-data", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--samples-per-class", type=int, default=24)
    parser.add_argument("--val-per-class", type=int, default=4)
    parser.add_argument("--seed", type=int, default=20260917)
    args = parser.parse_args()
    if args.samples_per_class <= 0 or not 0 < args.val_per_class < args.samples_per_class:
        parser.error("require samples-per-class > val-per-class > 0")

    manifest = json.loads(args.artwork_manifest.read_text(encoding="utf-8"))
    real_counts = copy_real(args.real_data, args.output)
    synthetic_counts = {"train": 0, "val": 0}
    labels = []
    for artwork in manifest["artworks"]:
        label = artwork["model_class_label"]
        if label in labels:
            raise SystemExit(f"duplicate artwork model class label: {label}")
        labels.append(label)
        source = args.artwork_root / artwork["png_path"]
        if not source.is_file():
            raise SystemExit(f"missing artwork PNG: {source}")
        image = Image.open(source).convert("RGBA")
        label_dir = safe_label(label)
        for index in range(args.samples_per_class):
            split = "val" if index < args.val_per_class else "train"
            rng = random.Random(seed_for(args.seed, label, index))
            rendered = render(image, rng)
            destination = args.output / split / label_dir / f"synthetic-{index:04d}.jpg"
            destination.parent.mkdir(parents=True, exist_ok=True)
            rendered.save(destination, format="JPEG", quality=88, optimize=True)
            synthetic_counts[split] += 1

    summary = {
        "schema_version": 1,
        "dataset_id": "ch-panoramax-artwork-mixed-bootstrap-v1",
        "status": "evaluation_only",
        "artwork_source_manifest": str(args.artwork_manifest),
        "artwork_source_status": manifest["status"],
        "synthetic_policy": "Official-source artwork renders provide class coverage only; they are not Swiss field imagery or human ground truth.",
        "real_data": str(args.real_data),
        "real_counts": real_counts,
        "synthetic_counts": synthetic_counts,
        "class_count": len(labels),
        "labels": sorted(labels),
        "seed": args.seed,
        "samples_per_class": args.samples_per_class,
        "val_per_class": args.val_per_class,
        "split_policy": "Real samples retain their existing route split; synthetic samples are generated deterministically per artwork source.",
    }
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / "dataset-summary.json").write_text(
        json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
