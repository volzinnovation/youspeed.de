#!/usr/bin/env python3
"""Manuell sortierte Panoramax-Dateien prüfen und gekoppelte Datensätze erzeugen.

Verschieben Sie geprüfte Crops nach approved/classifier/<Klassenordner>/ und
vollständig geprüfte Bildpakete nach approved/detector/<Bild-ID>/. Ein freigegebenes
Detektorpaket bestätigt ausdrücklich vollständige Boxen für sign, plate und face.
Dieses Programm ergänzt keine Boxen, lädt nichts herunter und trainiert nichts.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
from pathlib import Path
import shutil
import sys
import tempfile
import uuid
from urllib.parse import urlparse

from prepare_dataset import (COLUMNS, DEFAULT_CLASSES, DEFAULT_SEED, SAFE_SAMPLE_ID,
                             canonical_bytes, image_source, inspect_image,
                             load_classes, partition_for_group, sha256_file)

SCHEMA = "panoramax-course-collection-v1"
DETECTOR_CLASSES = {"sign": 0, "plate": 1, "face": 2}
STATUSES = ("inbox", "approved", "rejected")
UI_METADATA_NAMES = frozenset({".DS_Store", "Thumbs.db"})


class ImportError(ValueError):
    """Prüffehler mit verständlicher Handlungsanweisung."""


def require(condition, message):
    if not condition:
        raise ImportError(message)


def is_ui_metadata(path):
    """Nur die zwei bekannten Dateimanager-Caches, keine beliebigen versteckten Dateien."""
    return path.name in UI_METADATA_NAMES and path.is_file() and not path.is_symlink()


def valid_uuid(value):
    try:
        return isinstance(value, str) and str(uuid.UUID(value)) == value
    except (ValueError, TypeError, AttributeError):
        return False


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (ValueError, OSError) as error:
        raise ImportError(f"JSON nicht lesbar: {path}: {error}") from error


def checked_file(root, path):
    require(not path.is_symlink() and path.is_file(), f"Reguläre Datei fehlt: {path}")
    require(path.resolve().is_relative_to(root), f"Dateipfad verlässt den Sammelordner: {path}")
    return path


def assert_hash(path, expected):
    require(isinstance(expected, str) and len(expected) == 64,
            f"Gültige SHA256-Angabe fehlt für {path.name}.")
    require(sha256_file(path) == expected, f"Datei verändert: {path}. Erneut sammeln statt Dateien/Boxen zu bearbeiten.")


def checked_box(box, width, height):
    require(isinstance(box, list) and len(box) == 4
            and all(isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v) for v in box),
            "Ungültige Boxkoordinaten im Sammelmanifest.")
    x0, y0, x1, y1 = box
    require(0 <= x0 < x1 <= width and 0 <= y0 < y1 <= height,
            "Box liegt außerhalb des zugehörigen Vollbilds.")
    return box


def expected_yolo(item):
    result = []
    ids = set()
    for annotation in item["annotations"]:
        aid = annotation["annotation_id"]
        require(valid_uuid(aid) and aid not in ids, "Annotations-ID ungültig oder doppelt.")
        ids.add(aid)
        kind = annotation["detector_class"]
        require(kind in DETECTOR_CLASSES, "Detektorklasse muss sign, plate oder face sein.")
        x0, y0, x1, y1 = checked_box(annotation["bbox_xyxy"], item["width"], item["height"])
        result.append((DETECTOR_CLASSES[kind], (x0 + x1) / (2 * item["width"]),
                       (y0 + y1) / (2 * item["height"]),
                       (x1 - x0) / item["width"], (y1 - y0) / item["height"]))
    return sorted(result)


def verify_bundle(source, folder, item):
    require(folder.is_dir() and not folder.is_symlink(), f"Bildpaket fehlt: {folder}")
    require({p.name for p in folder.iterdir() if not is_ui_metadata(p)} == {"image.png", "labels.txt", "metadata.json"},
            f"Paket {folder.name} muss exakt image.png, labels.txt und metadata.json enthalten.")
    for name in ["image.png", "labels.txt", "metadata.json"]:
        checked_file(source, folder / name)
    assert_hash(folder / "image.png", item["image_sha256"])
    assert_hash(folder / "labels.txt", item["labels_sha256"])
    assert_hash(folder / "metadata.json", item.get("metadata_sha256"))
    read_json(folder / "metadata.json")
    try:
        from PIL import Image
        with Image.open(folder / "image.png") as image:
            require(image.format == "PNG" and image.size == (item["width"], item["height"]),
                    f"Bildformat/-größe stimmt nicht zum Manifest: {folder.name}")
            image.verify()
    except ModuleNotFoundError as error:
        raise ImportError("Pillow fehlt. Verwenden Sie die vorbereitete Lehrumgebung.") from error
    actual = []
    for line in (folder / "labels.txt").read_text().splitlines():
        fields = line.split()
        require(len(fields) == 5, f"Ungültige YOLO-Zeile in {folder.name}.")
        try:
            kind = int(fields[0]); values = tuple(map(float, fields[1:]))
        except ValueError as error:
            raise ImportError(f"Ungültige YOLO-Zahlen in {folder.name}.") from error
        require(kind in DETECTOR_CLASSES.values() and all(math.isfinite(v) for v in values),
                f"Unbekannte Klasse oder ungültige Geometrie in {folder.name}.")
        cx, cy, width, height = values
        require(0 < width <= 1 and 0 < height <= 1 and
                cx - width / 2 >= -1e-7 and cy - height / 2 >= -1e-7 and
                cx + width / 2 <= 1 + 1e-7 and cy + height / 2 <= 1 + 1e-7,
                f"YOLO-Box außerhalb des Bilds in {folder.name}.")
        actual.append((kind,) + values)
    expected = expected_yolo(item)
    require(len(actual) == len(expected), f"YOLO-Boxanzahl stimmt nicht zum Manifest: {folder.name}")
    require(all(a[0] == e[0] and all(abs(x - y) <= 1e-7 for x, y in zip(a[1:], e[1:]))
                for a, e in zip(sorted(actual), expected)),
            f"YOLO-Boxen stimmen nicht zum Manifest: {folder.name}")


def read_collection(source, classes):
    source = source.resolve()
    require(source.is_dir(), f"Sammelordner fehlt: {source}")
    manifest = read_json(source / "manifest.json")
    require(manifest.get("schema_version") == SCHEMA, "Unbekanntes Sammelmanifest-Format.")
    unlocked = {key: value for key, value in manifest.items() if key != "lock_sha256"}
    require(manifest.get("lock_sha256") == hashlib.sha256(canonical_bytes(unlocked)).hexdigest(),
            "Sammelmanifest wurde verändert; Lock stimmt nicht.")
    expected_folders = {label.replace(":", "__"): label for label in classes}
    require(len(expected_folders) == len(classes) and manifest.get("class_folders") == expected_folders,
            "Klassenordner im Sammelmanifest stimmen nicht mit class-index.json überein.")
    require(isinstance(manifest.get("items"), list) and isinstance(manifest.get("crops"), list),
            "Bild-/Crop-Listen fehlen im Sammelmanifest.")
    items, crops = {}, {}
    for item in manifest["items"]:
        pid, seq = item["picture_id"], item["sequence_id"]
        require(valid_uuid(pid) and valid_uuid(seq) and pid not in items, "Bild-/Sequenz-ID ungültig oder doppelt.")
        require(item["group_id"] == "sequence-" + seq, "Die ursprüngliche Sequenzgruppe wurde verändert.")
        require(item["bundle_path"] == "inbox/detector/" + pid, "Ungültiger ursprünglicher Bildpaketpfad.")
        require(all(isinstance(item.get(k), str) and item[k].strip() for k in ["license", "author", "source_url", "asset_url"]),
                f"Herkunft, Autor oder Lizenz fehlt für Bild {pid}.")
        require(item["license"].strip().lower() not in {"unknown", "none", "unspecified"}, f"Lizenz ungeklärt: {pid}")
        require(all(urlparse(item[key]).scheme == "https" and urlparse(item[key]).netloc for key in ["source_url", "asset_url"]),
                f"Gültige HTTPS-Herkunftslinks fehlen: {pid}")
        require(all(isinstance(item.get(k), int) and not isinstance(item[k], bool) and item[k] > 0 for k in ["width", "height"]),
                f"Bildabmessungen fehlen: {pid}")
        require(isinstance(item.get("annotations"), list), "Annotationsliste fehlt.")
        expected_yolo(item)
        items[pid] = item
    for crop in manifest["crops"]:
        pid, aid, sid = crop["picture_id"], crop["annotation_id"], crop["sample_id"]
        require(pid in items and valid_uuid(aid) and sid == f"p{pid}_a{aid}" and sid not in crops,
                "Crop-ID ungültig, unbekannt oder doppelt.")
        item = items[pid]
        require(crop["group_id"] == item["group_id"] and crop["crop_path"] == f"inbox/classifier/{sid}.png",
                f"Gruppe oder ursprünglicher Crop-Pfad ungültig: {sid}")
        annotation = next((a for a in item["annotations"] if a["annotation_id"] == aid), None)
        require(annotation is not None and annotation["detector_class"] == "sign"
                and crop["bbox_xyxy"] == annotation["bbox_xyxy"], f"Crop passt nicht zur Schildannotation: {sid}")
        crops[sid] = crop
    return source, manifest, items, crops


def review_locations(source, manifest, items, crops):
    crop_locations, item_locations = {}, {}
    for status in STATUSES:
        status_root = source / status
        if status_root.exists():
            require(status_root.is_dir() and not status_root.is_symlink(), f"Ungültiger Review-Ordner: {status_root}")
            require(all(is_ui_metadata(p) or (p.name in {"classifier", "detector"} and p.is_dir()) for p in status_root.iterdir()),
                    f"Unbekannte Dateien/Ordner in {status_root}; nur classifier/ und detector/ verwenden.")
        crop_root = source / status / "classifier"
        if crop_root.exists():
            require(not crop_root.is_symlink(), "Review-Ordner darf kein symbolischer Link sein.")
            for path in crop_root.rglob("*"):
                if is_ui_metadata(path):
                    continue
                require(not path.is_symlink(), f"Symbolischer Link im Review-Ordner: {path}")
                if path.is_dir():
                    if status == "approved":
                        require(path.parent == crop_root and path.name in manifest["class_folders"], f"Unbekannter Klassenordner: {path}")
                    else:
                        raise ImportError(f"Crops direkt nach {crop_root} verschieben; keine Unterordner verwenden.")
                    continue
                checked_file(source, path)
                sid = path.stem
                require(path.suffix == ".png" and sid in crops and sid not in crop_locations,
                        f"Crop unbekannt, umbenannt oder mehrfach vorhanden: {path.name}")
                require((status == "approved" and path.parent.parent == crop_root)
                        or (status != "approved" and path.parent == crop_root), f"Falsche Ordnerstruktur: {path}")
                assert_hash(path, crops[sid]["crop_sha256"])
                require(inspect_image(path) == "pillow", "Pillow fehlt; Bildprüfung ist erforderlich.")
                label = manifest["class_folders"][path.parent.name] if status == "approved" else None
                crop_locations[sid] = (status, path, label)
        detector_root = source / status / "detector"
        if detector_root.exists():
            require(not detector_root.is_symlink(), "Review-Ordner darf kein symbolischer Link sein.")
            for folder in detector_root.iterdir():
                if is_ui_metadata(folder):
                    continue
                pid = folder.name
                require(pid in items and pid not in item_locations, f"Bildpaket unbekannt, umbenannt oder mehrfach vorhanden: {pid}")
                verify_bundle(source, folder, items[pid])
                item_locations[pid] = (status, folder)
    require(set(crop_locations) == set(crops), "Crops fehlen. Verwerfen Sie Dateien durch Verschieben nach rejected/classifier; nicht löschen.")
    require(set(item_locations) == set(items), "Bildpakete fehlen. Verwerfen Sie ganze Pakete durch Verschieben nach rejected/detector; nicht löschen.")
    return crop_locations, item_locations


def group_overrides(path, known_sequences):
    if path is None:
        return {}, None
    result = {}
    with path.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        require(reader.fieldnames == ["sequence_id", "group_id"], "Gruppen-CSV benötigt exakt sequence_id,group_id.")
        for row in reader:
            require(None not in row and all(v is not None for v in row.values()), "Ungültige Zeile in Gruppen-CSV.")
            seq, group = row["sequence_id"].strip(), row["group_id"].strip()
            require(seq in known_sequences and seq not in result, "Sequenz in Gruppen-CSV unbekannt oder doppelt.")
            require(group and len(group) <= 200 and not any(c in group for c in "\0\r\n\t"), "Ungültige gemeinsame Gruppen-ID.")
            result[seq] = group
    return result, sha256_file(path)


def teacher_samples(annotations, images, classes, occupied):
    require((annotations is None) == (images is None), "--include-annotations und --include-images immer gemeinsam angeben.")
    if annotations is None:
        return []
    images = images.resolve(); result = []; seen_paths = set()
    with annotations.open(newline="", encoding="utf-8-sig") as stream:
        reader = csv.DictReader(stream)
        require(reader.fieldnames == COLUMNS, "Bestands-CSV benötigt exakt: " + ",".join(COLUMNS))
        for number, row in enumerate(reader, 2):
            require(None not in row and all(v is not None for v in row.values()), "Ungültige Bestands-CSV-Zeile.")
            row = {key: value.strip() for key, value in row.items()}
            sid, group = row["sample_id"], row["group_id"]
            require(SAFE_SAMPLE_ID.fullmatch(sid) and sid.casefold() not in occupied, "Bestands-Sample-ID ungültig oder doppelt.")
            require(row["label"] in classes and group and len(group) <= 200
                    and not any(c in group for c in "\0\r\n\t"), "Bestandsklasse oder Gruppe ungültig.")
            path = image_source(images, row["image_path"], number)
            require(path not in seen_paths, "Dasselbe Bestandsbild ist mehrfach aufgeführt.")
            seen_paths.add(path)
            require(inspect_image(path) == "pillow", "Pillow fehlt; Bildprüfung ist erforderlich.")
            result.append({"sample_id": sid, "path": path, "label": row["label"], "group_id": group,
                           "sha256": sha256_file(path), "origin": "teacher", "source_path": row["image_path"]})
            occupied.add(sid.casefold())
    return result


def import_review(source, output, *, classes_file=DEFAULT_CLASSES, groups=None,
                  include_annotations=None, include_images=None, seed=DEFAULT_SEED, require_136=True):
    require(seed == DEFAULT_SEED, "Der gekoppelte Kurs-Split verwendet fest Seed 20261026, ebenso prepare_dataset.py.")
    classes, class_raw = load_classes(classes_file, require_136=require_136)
    source, collection, items, crops = read_collection(source, classes)
    require(collection.get("class_index_sha256") == hashlib.sha256(class_raw).hexdigest(),
            "Sammelmanifest und Klassentabelle haben unterschiedliche SHA256-Werte.")
    output = output.resolve()
    require(not output.exists(), "Ausgabeordner existiert bereits. Für die nächste Version einen neuen --output wählen.")
    require(not output.is_relative_to(source), "Ausgabe muss außerhalb des Sammelordners liegen.")
    crop_locations, item_locations = review_locations(source, collection, items, crops)
    overrides, groups_sha = group_overrides(groups, {item["sequence_id"] for item in items.values()})
    effective = {pid: overrides.get(item["sequence_id"], item["group_id"]) for pid, item in items.items()}
    classifier = []
    for sid, (status, path, label) in sorted(crop_locations.items()):
        if status == "approved":
            crop = crops[sid]; item = items[crop["picture_id"]]
            classifier.append({"sample_id": sid, "path": path, "label": label,
                               "group_id": effective[crop["picture_id"]], "sha256": crop["crop_sha256"],
                               "origin": "panoramax", "picture_id": crop["picture_id"], "annotation_id": crop["annotation_id"],
                               "source_url": item["source_url"], "license": item["license"], "author": item["author"]})
    classifier += teacher_samples(include_annotations, include_images, classes, {sid.casefold() for sid in crops})
    detector = [(pid, folder) for pid, (status, folder) in sorted(item_locations.items()) if status == "approved"]
    require(classifier or detector, "Noch keine Dateien freigegeben. Verschieben Sie geprüfte Beispiele nach approved/.")
    # Gleiche Pixeldateien dürfen die Gruppengrenze auch zwischen beiden Aufgaben nicht überwinden.
    seen_hashes, classifier_labels = {}, {}
    for digest, group in ([(row["sha256"], row["group_id"]) for row in classifier]
                          + [(items[pid]["image_sha256"], effective[pid]) for pid, _ in detector]):
        require(digest not in seen_hashes or seen_hashes[digest] == group,
                "Identische Bildbytes in verschiedenen Gruppen. Sequenzen über --groups gemeinsam gruppieren; Bestandsgruppen abgleichen.")
        seen_hashes[digest] = group
    for row in classifier:
        require(row["sha256"] not in classifier_labels or classifier_labels[row["sha256"]] == row["label"],
                "Identische Crop-Bytes besitzen widersprüchliche Klassen.")
        classifier_labels[row["sha256"]] = row["label"]
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=f".{output.name}-", dir=output.parent))
    try:
        image_root = staging / "classifier/images"; image_root.mkdir(parents=True)
        csv_rows, classifier_records = [], []
        for row in classifier:
            filename = row["sample_id"] + row["path"].suffix.lower()
            shutil.copyfile(row["path"], image_root / filename)
            assert_hash(image_root / filename, row["sha256"])
            csv_rows.append({"sample_id": row["sample_id"], "image_path": filename,
                             "label": row["label"], "group_id": row["group_id"]})
            classifier_records.append({key: value for key, value in row.items() if key != "path"}
                                      | {"split": partition_for_group(row["group_id"], seed), "image_path": filename})
        with (staging / "classifier/annotations.csv").open("w", newline="", encoding="utf-8") as stream:
            writer = csv.DictWriter(stream, fieldnames=COLUMNS); writer.writeheader(); writer.writerows(csv_rows)
        (staging / "classifier/class-index.json").write_bytes(class_raw)
        detector_records = []
        for split in ["train", "val", "test"]:
            for kind in ["images", "labels"]:
                (staging / "detector" / kind / split).mkdir(parents=True)
        for pid, folder in detector:
            item = items[pid]; group = effective[pid]; split = partition_for_group(group, seed)
            for original, kind, suffix in [("image.png", "images", ".png"), ("labels.txt", "labels", ".txt")]:
                destination = staging / "detector" / kind / split / (pid + suffix)
                shutil.copyfile(folder / original, destination)
                assert_hash(destination, item["image_sha256"] if kind == "images" else item["labels_sha256"])
            detector_records.append({"picture_id": pid, "sequence_id": item["sequence_id"], "group_id": group,
                                     "split": split, "image_sha256": item["image_sha256"], "labels_sha256": item["labels_sha256"],
                                     "source_url": item["source_url"], "license": item["license"], "author": item["author"],
                                     "review_attestation": {"method": "manually moved complete bundle to approved/detector",
                                                            "complete_for_classes": list(DETECTOR_CLASSES),
                                                            "negative_frame": not bool(item["annotations"])}})
        # Ultralytics darf relative Wurzeln nicht seinem globalen DATASETS_DIR zuordnen.
        # Nach Umzug des Datensatzes erneut mit einem neuen --output importieren.
        (staging / "detector/data.yaml").write_text("path: " + json.dumps(str(output / "detector"))
                                                  + "\ntrain: images/train\nval: images/val\ntest: images/test\nnames:\n  0: sign\n  1: plate\n  2: face\n", encoding="utf-8")
        detector_manifest = {"schema_version": "reviewed-sgblur-dataset-v1", "classes": DETECTOR_CLASSES,
                             "seed": seed, "source_collection_lock": collection["lock_sha256"], "samples": detector_records,
                             "scope": "Human completeness attestation, not an automated proof that all objects were found."}
        (staging / "detector/manifest.json").write_text(json.dumps(detector_manifest, ensure_ascii=False, indent=2) + "\n")
        counts = {kind: {status: sum(location[0] == status for location in locations.values()) for status in STATUSES}
                  for kind, locations in [("classifier", crop_locations), ("detector", item_locations)]}
        coverage = {split: {label: sum(row["label"] == label and row["split"] == split for row in classifier_records)
                            for label in classes} for split in ["train", "val", "test"]}
        manifest = {"schema_version": "reviewed-panoramax-course-data-v1", "source_collection_sha256": sha256_file(source / "manifest.json"),
                    "source_collection_lock": collection["lock_sha256"], "source_crawl": collection.get("crawl"),
                    "class_index_sha256": hashlib.sha256(class_raw).hexdigest(), "seed": seed,
                    "split_rule": "prepare_dataset.partition_for_group; sha256(seed + NUL + group_id); 70/15/15",
                    "group_overrides": overrides, "groups_csv_sha256": groups_sha,
                    "default_group_limitation": "Whole sequences stay together; the reviewer must merge repeated physical signs across sequences. Near duplicates are not automatically discovered.",
                    "review_counts": counts, "teacher_samples": sum(row["origin"] == "teacher" for row in classifier_records),
                    "teacher_annotations_sha256": sha256_file(include_annotations) if include_annotations else None,
                    "classifier_samples": classifier_records, "detector_samples": detector_records, "classifier_coverage": coverage,
                    "missing_classifier_classes": {split: [label for label, count in values.items() if not count] for split, values in coverage.items()},
                    "output_sha256": {str(p.relative_to(staging)): sha256_file(p) for p in sorted(staging.rglob("*")) if p.is_file()}}
        manifest["lock_sha256"] = hashlib.sha256(canonical_bytes(manifest)).hexdigest()
        (staging / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
        require(not output.exists(), "Ausgabe wurde inzwischen angelegt; nichts überschrieben.")
        staging.rename(output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=Path("data/collection"), help="Sammelordner mit unverändertem manifest.json")
    parser.add_argument("--output", type=Path, default=Path("data/reviewed"), help="Neuer Ausgabeordner; vorhandene Ergebnisse werden erhalten")
    parser.add_argument("--groups", type=Path, help="Geprüfte Zusammenführungen: CSV sequence_id,group_id")
    parser.add_argument("--include-annotations", type=Path, help="Geprüfte Bestands-Crop-CSV zusätzlich übernehmen")
    parser.add_argument("--include-images", type=Path, help="Bildwurzel der Bestands-CSV; gemeinsam mit --include-annotations")
    parser.add_argument("--classes", type=Path, help="Geordnete Klassenliste; Standard ist die feste Kursliste")
    parser.add_argument("--seed", default=DEFAULT_SEED, choices=[DEFAULT_SEED], help="Festgelegter Kurs-Split, identisch zu prepare_dataset.py")
    args = parser.parse_args(argv)
    try:
        result = import_review(args.source, args.output, classes_file=args.classes or DEFAULT_CLASSES,
                               groups=args.groups, include_annotations=args.include_annotations,
                               include_images=args.include_images, seed=args.seed, require_136=args.classes is None)
    except (ValueError, OSError, KeyError, TypeError, csv.Error) as error:
        print(f"Import nicht abgeschlossen: {error}", file=sys.stderr)
        return 2
    print(f"Geprüfte Daten geschrieben: {args.output}\nReview: {result['review_counts']}")
    for split, missing in result["missing_classifier_classes"].items():
        if missing:
            print(f"Hinweis: {split} fehlen {len(missing)} Klassen: " + ", ".join(missing))
    print("Detektorpakete sind durch Ihre Freigabe als vollständig für sign, plate und face bestätigt.\n"
          "Der Import prüft Dateiintegrität, nicht die menschliche Vollständigkeit der Boxen.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
