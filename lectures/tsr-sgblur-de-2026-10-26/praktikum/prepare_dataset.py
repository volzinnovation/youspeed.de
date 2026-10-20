#!/usr/bin/env python3
"""Create a frozen, grouped classification dataset from reviewed SIGN CROPS.

CSV: sample_id,image_path,label,group_id. image_path is relative to --images.
group_id must already combine sequences, repeated views of the same physical
sign and near duplicates. This program cannot discover those relationships.
It never crops full road images, augments samples, downloads or trains models.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import sys
import tempfile
from typing import Any


HERE = Path(__file__).resolve().parent
DEFAULT_CLASSES = HERE / "class-index.json"
DEFAULT_SEED = "20261026"
SPLITS = ("train", "val", "test")
FRACTIONS = {"train": 0.70, "val": 0.15, "test": 0.15}
COLUMNS = ["sample_id", "image_path", "label", "group_id"]
EXTENSIONS = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
SAFE_SAMPLE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


class DatasetError(ValueError):
    """An actionable input, coverage or frozen-manifest error."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def load_classes(path: Path, *, require_136: bool = False) -> tuple[list[str], bytes]:
    """Read the course's canonical order; --classes also allows tiny test fixtures."""
    try:
        raw = path.read_bytes()
        payload = json.loads(raw)
    except (OSError, ValueError) as error:
        raise DatasetError(f"Klassenliste nicht lesbar: {path}: {error}") from error
    classes = payload.get("classes") if isinstance(payload, dict) else payload
    if not isinstance(classes, list) or not classes:
        raise DatasetError("class-index.json benötigt eine geordnete Liste 'classes'.")
    if any(not isinstance(label, str) or not label.strip() or label != label.strip()
           or label in {".", ".."} or any(c in label for c in "/\\\x00\n\r\t")
           for label in classes):
        raise DatasetError("Klassen müssen eindeutige, sichere Ordnernamen sein.")
    if len(classes) != len(set(classes)):
        raise DatasetError("Die Klassenliste enthält doppelte Namen.")
    if len({label.casefold() for label in classes}) != len(classes):
        raise DatasetError("Klassen unterscheiden sich nur in Groß-/Kleinschreibung.")
    if require_136 and (len(classes) != 136 or
                        not {"city:start", "city:end"}.issubset(classes)):
        raise DatasetError("Die Kurs-Klassenliste muss 134 Altklassen und "
                           "city:start/city:end enthalten (136 Klassen).")
    return classes, raw


def partition_for_group(group_id: str, seed: str) -> str:
    """Stable SHA-256 group assignment; ratios are expectations, not exact quotas."""
    digest = hashlib.sha256(f"{seed}\0{group_id}".encode("utf-8")).digest()
    value = int.from_bytes(digest[:8], "big") / (1 << 64)
    return "train" if value < 0.70 else "val" if value < 0.85 else "test"


def image_source(images_root: Path, relative: str, row_number: int) -> Path:
    # Explicit POSIX paths keep the portable CSV independent of host separators.
    rel = PurePosixPath(relative)
    if not relative or rel.is_absolute() or ".." in rel.parts or "\\" in relative:
        raise DatasetError(f"Zeile {row_number}: image_path muss relativ und ohne '..' sein.")
    candidate = (images_root / Path(*rel.parts)).resolve()
    if not candidate.is_relative_to(images_root):
        raise DatasetError(f"Zeile {row_number}: Bildpfad verlässt den Bildordner.")
    if not candidate.is_file() or candidate.suffix.lower() not in EXTENSIONS:
        raise DatasetError(f"Zeile {row_number}: Bild fehlt oder Format nicht unterstützt: {relative}")
    return candidate


def inspect_image(path: Path) -> str:
    """Pillow is optional; the course environment should install it for decode QA."""
    try:
        from PIL import Image
    except ImportError:
        return "bytes_only"
    try:
        with Image.open(path) as image:
            image.verify()
        with Image.open(path) as image:
            if min(image.size) <= 0:
                raise ValueError("ungültige Bildabmessungen")
            if image.getexif().get(274, 1) not in (None, 1):
                raise ValueError("EXIF-Orientierung ist noch nicht normalisiert")
    except Exception as error:
        raise DatasetError(f"Crop nicht nutzbar: {path.name}: {error}. "
                           "Bild vor dem Export prüfen und aufrecht speichern.") from error
    return "pillow"


def make_plan(annotations: Path, images: Path, classes_file: Path,
              seed: str = DEFAULT_SEED, *, require_136: bool = False
              ) -> tuple[dict[str, Any], dict[str, Path], bytes]:
    if not seed.strip():
        raise DatasetError("Der Split-Seed darf nicht leer sein.")
    images = images.resolve()
    if not images.is_dir():
        raise DatasetError(f"Ordner mit geprüften Schild-Crops fehlt: {images}")
    classes, class_raw = load_classes(classes_file, require_136=require_136)
    indices = {label: index for index, label in enumerate(classes)}
    try:
        annotation_raw = annotations.read_bytes()
        reader = csv.DictReader(io.StringIO(annotation_raw.decode("utf-8-sig")))
    except (OSError, UnicodeError) as error:
        raise DatasetError(f"annotations.csv nicht lesbar: {error}") from error
    if reader.fieldnames != COLUMNS:
        raise DatasetError("CSV-Kopf muss exakt lauten: " + ",".join(COLUMNS))
    samples: list[dict[str, Any]] = []
    sources: dict[str, Path] = {}
    seen_ids: set[str] = set()
    seen_paths: set[str] = set()
    seen_hashes: dict[str, tuple[str, str]] = {}
    counts = {
        "images": {split: 0 for split in SPLITS},
        "groups": {split: 0 for split in SPLITS},
        "per_class": {label: {split: 0 for split in SPLITS} for label in classes},
    }
    group_sets: dict[str, set[str]] = {split: set() for split in SPLITS}
    image_validation = "bytes_only"
    for number, row in enumerate(reader, 2):
        if None in row or any(value is None for value in row.values()):
            raise DatasetError(f"Zeile {number}: falsche Anzahl CSV-Spalten.")
        row = {key: value.strip() for key, value in row.items()}
        sample_id, label, group = row["sample_id"], row["label"], row["group_id"]
        if not SAFE_SAMPLE_ID.fullmatch(sample_id) or sample_id.casefold() in seen_ids:
            raise DatasetError(f"Zeile {number}: sample_id fehlt, ist ungültig oder doppelt.")
        if label not in indices:
            raise DatasetError(f"Zeile {number}: unbekannte Klasse {label!r}; "
                               "Schreibweise mit class-index.json abgleichen.")
        if not group or len(group) > 200 or any(c in group for c in "\x00\n\r\t"):
            raise DatasetError(f"Zeile {number}: geprüfte group_id fehlt oder ist ungültig.")
        source = image_source(images, row["image_path"], number)
        if str(source) in seen_paths:
            raise DatasetError(f"Zeile {number}: dasselbe Bild ist mehrfach aufgeführt.")
        digest = sha256_file(source)
        previous = seen_hashes.get(digest)
        if previous and previous != (group, label):
            raise DatasetError(f"Zeile {number}: identische Bildbytes haben verschiedene "
                               "Gruppen oder Labels. Identität/Label prüfen und gemeinsam gruppieren.")
        seen_hashes[digest] = (group, label)
        image_validation = inspect_image(source)
        split = partition_for_group(group, seed)
        output_path = f"{split}/{label}/{sample_id}{source.suffix.lower()}"
        samples.append({
            "sample_id": sample_id, "image_path": row["image_path"], "label": label,
            "class_index": indices[label], "group_id": group, "split": split,
            "sha256": digest, "size_bytes": source.stat().st_size,
            "dataset_path": output_path,
        })
        sources[sample_id] = source
        seen_ids.add(sample_id.casefold())
        seen_paths.add(str(source))
        counts["images"][split] += 1
        counts["per_class"][label][split] += 1
        group_sets[split].add(group)
    if not samples:
        raise DatasetError("annotations.csv enthält keine Samples.")
    for split in SPLITS:
        counts["groups"][split] = len(group_sets[split])
    missing = {split: [label for label in classes
                       if counts["per_class"][label][split] == 0] for split in SPLITS}
    problems = []
    if missing["train"]:
        problems.append("Trainingsdaten fehlen für: " + ", ".join(missing["train"]))
    for split in ("val", "test"):
        if not counts["images"][split]:
            problems.append(f"Partition {split} enthält keine Bilder.")
    if problems:
        raise DatasetError("\n".join(problems) +
                           "\nNächste Schritte: Kursarchiv der 134 Altklassen ergänzen; "
                           "weitere unabhängige Schildgruppen sammeln; Labels/Gruppen prüfen. "
                           "Der feste Split wird nicht für ein besseres Ergebnis umgewürfelt. "
                           "Es wurde kein Datensatz geschrieben.")
    plan: dict[str, Any] = {
        "schema_version": 1, "dataset_id": "youspeed-city-crops-v1", "seed": seed,
        "class_index_sha256": hashlib.sha256(class_raw).hexdigest(), "classes": classes,
        "fractions": FRACTIONS, "annotations_sha256": hashlib.sha256(annotation_raw).hexdigest(),
        "group_rule": "reviewed_group_id_includes_sequences_physical_signs_near_duplicates",
        "image_validation": image_validation, "samples": sorted(samples, key=lambda item: item["sample_id"]),
        "counts": counts, "missing_classes": missing,
    }
    plan["lock_sha256"] = hashlib.sha256(canonical_bytes(plan)).hexdigest()
    return plan, sources, class_raw


def check_existing(output: Path, plan: dict[str, Any]) -> None:
    try:
        existing = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise DatasetError(f"Ausgabeordner existiert ohne lesbares Manifest: {output}. "
                           "Einen neuen Ausgabeordner wählen.") from error
    if existing != plan:
        raise DatasetError("Der Datensatz ist eingefroren: CSV, Bilder, Seed, Klassenliste "
                           "oder Prüfmodus unterscheiden sich. Für eine neue Version "
                           "einen neuen Ausgabeordner wählen.")
    if not (output / "class-index.json").is_file() or \
            sha256_file(output / "class-index.json") != plan["class_index_sha256"]:
        raise DatasetError("Die eingefrorene class-index.json wurde verändert.")
    expected = {"manifest.json", "class-index.json"}
    for sample in plan["samples"]:
        target = output / sample["dataset_path"]
        expected.add(sample["dataset_path"])
        if not target.is_file() or sha256_file(target) != sample["sha256"]:
            raise DatasetError(f"Eingefrorenes Bild fehlt oder wurde verändert: {sample['dataset_path']}")
    actual = {path.relative_to(output).as_posix() for path in output.rglob("*") if path.is_file()}
    if actual != expected:
        raise DatasetError("Zusätzliche Dateien im eingefrorenen Datensatz. "
                           "Abgeleitete/augmentierte Bilder außerhalb dieses Ordners speichern.")


def prepare_dataset(annotations: Path, images: Path, output: Path,
                    classes_file: Path = DEFAULT_CLASSES, seed: str = DEFAULT_SEED,
                    *, require_136: bool = False) -> dict[str, Any]:
    plan, sources, class_raw = make_plan(annotations, images, classes_file, seed,
                                        require_136=require_136)
    output = output.resolve()
    if output.exists():
        check_existing(output, plan)
        return plan
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        for split in SPLITS:
            for label in plan["classes"]:
                (staging / split / label).mkdir(parents=True)
        for sample in plan["samples"]:
            target = staging / sample["dataset_path"]
            shutil.copyfile(sources[sample["sample_id"]], target)
            if sha256_file(target) != sample["sha256"]:
                raise DatasetError("Quellbild änderte sich während der Vorbereitung; erneut prüfen.")
        (staging / "class-index.json").write_bytes(class_raw)
        (staging / "manifest.json").write_text(
            json.dumps(plan, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
        if output.exists():
            raise DatasetError("Ausgabeordner wurde inzwischen angelegt; nichts überschrieben.")
        staging.rename(output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotations", type=Path, default=Path("data/annotations.csv"),
                        help="geprüfte CSV; Standard data/annotations.csv")
    parser.add_argument("--images", type=Path, default=Path("data/raw/images"),
                        help="geprüfte SCHILD-CROPS; Standard data/raw/images")
    parser.add_argument("--output", type=Path, default=Path("data/dataset"),
                        help="neuer Datensatzordner; Standard data/dataset")
    parser.add_argument("--classes", type=Path, default=None, help="geordnete Klassenliste; Standard neben diesem Skript")
    parser.add_argument("--seed", default=DEFAULT_SEED, help=f"fester Split-Seed; Standard {DEFAULT_SEED}")
    args = parser.parse_args(argv)
    try:
        plan = prepare_dataset(args.annotations, args.images, args.output,
                               args.classes or DEFAULT_CLASSES, args.seed,
                               require_136=args.classes is None)
    except (DatasetError, OSError, csv.Error) as error:
        print(f"Datensatz nicht vorbereitet:\n{error}", file=sys.stderr)
        return 2
    print(f"Datensatz geprüft: {args.output}\nLock: {plan['lock_sha256']}")
    for split in SPLITS:
        print(f"{split}: {plan['counts']['images'][split]} Bilder, "
              f"{plan['counts']['groups'][split]} unabhängige Gruppen")
    for split in ("val", "test"):
        if plan["missing_classes"][split]:
            print(f"Hinweis: {split} ohne Beispiele für " + ", ".join(plan["missing_classes"][split]) +
                  ". Diese Klassenmetriken bleiben undefiniert.", file=sys.stderr)
    if plan["image_validation"] == "bytes_only":
        print("Hinweis: Pillow fehlt; nur Bildbytes geprüft. Im Kursimage Pillow "
              "bereitstellen und vor dem ersten Export erneut prüfen.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
