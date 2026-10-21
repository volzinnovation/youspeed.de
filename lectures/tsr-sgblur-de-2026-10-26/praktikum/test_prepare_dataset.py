"""Meaningful, offline contract tests with tiny synthetic PNGs in temp folders.

Run from this folder: python -m unittest test_prepare_dataset.py
These fixtures test data handling, not traffic-sign recognition or ML quality.
"""

from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest import mock
import zlib


SPEC = importlib.util.spec_from_file_location("city_prepare", Path(__file__).with_name("prepare_dataset.py"))
PREPARE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(PREPARE)


def synthetic_png(red: int) -> bytes:
    """Create a valid 3x2 RGB PNG with stdlib only; each value has unique bytes."""
    def chunk(kind: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    pixels = b"\0" + bytes([red, 71, 133]) * 3
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 3, 2, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(pixels * 2)) + chunk(b"IEND", b""))


class PreparationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.images = self.root / "raw" / "images"
        self.images.mkdir(parents=True)
        self.csv = self.root / "annotations.csv"
        self.classes = self.root / "class-index.json"
        self.labels = ["old:sign", "city:start", "city:end"]
        self.write_classes(self.labels)
        self.rows = []
        color = 1
        # Fixture group names are selected for explicit partition coverage only.
        # Production data never changes its reviewed identity to tune a split.
        self.groups = {}
        for split in PREPARE.SPLITS:
            group = next(f"fixture-{n}" for n in range(1000)
                         if PREPARE.partition_for_group(f"fixture-{n}", PREPARE.DEFAULT_SEED) == split)
            self.groups[split] = group
            for label in self.labels:
                sample = f"sample-{color:02}"
                file_name = sample + ".png"
                (self.images / file_name).write_bytes(synthetic_png(color))
                self.rows.append([sample, file_name, label, group])
                color += 1
        self.write_rows()
        self.output = self.root / "dataset"

    def write_classes(self, labels):
        self.classes.write_text(json.dumps({"schema_version": 1, "baseline_class_count": 1,
                                            "classes": labels}), encoding="utf-8")

    def write_rows(self):
        with self.csv.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(PREPARE.COLUMNS)
            writer.writerows(self.rows)

    def prepare(self, **kwargs):
        return PREPARE.prepare_dataset(self.csv, self.images, self.output, self.classes, **kwargs)

    def test_stable_grouped_copy_manifest_and_idempotent_rerun(self):
        manifest = self.prepare()
        frozen_manifest = (self.output / "manifest.json").read_bytes()
        lockless = {key: value for key, value in manifest.items() if key != "lock_sha256"}
        self.assertEqual(manifest["lock_sha256"], hashlib.sha256(PREPARE.canonical_bytes(lockless)).hexdigest())
        self.assertEqual(manifest["class_index_sha256"], PREPARE.sha256_file(self.classes))
        self.assertEqual(manifest["seed"], "20261026")
        self.assertEqual(manifest["counts"]["images"], {"train": 3, "val": 3, "test": 3})
        groups = {split: set() for split in PREPARE.SPLITS}
        for item in manifest["samples"]:
            groups[item["split"]].add(item["group_id"])
            self.assertEqual((self.output / item["dataset_path"]).read_bytes(),
                             (self.images / item["image_path"]).read_bytes())
            self.assertEqual(item["class_index"], self.labels.index(item["label"]))
        self.assertFalse(groups["train"] & groups["val"])
        self.assertFalse(groups["train"] & groups["test"])
        self.assertFalse(groups["val"] & groups["test"])
        self.assertEqual(self.prepare(), manifest)
        self.assertEqual((self.output / "manifest.json").read_bytes(), frozen_manifest)

    def test_missing_train_class_blocks_before_writing_and_explains_next_steps(self):
        self.write_classes(self.labels + ["missing:old"])
        with self.assertRaisesRegex(PREPARE.DatasetError, "Trainingsdaten fehlen für: missing:old"):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_empty_validation_partition_blocks_without_resplitting(self):
        self.rows = [row for row in self.rows if row[3] != self.groups["val"]]
        self.write_rows()
        with self.assertRaisesRegex(PREPARE.DatasetError, "Partition val enthält keine Bilder"):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_zero_per_class_validation_support_is_reported_and_folders_remain(self):
        self.rows = [row for row in self.rows if not (row[2] == "city:end" and row[3] == self.groups["val"])]
        self.write_rows()
        manifest = self.prepare()
        self.assertEqual(manifest["missing_classes"]["val"], ["city:end"])
        self.assertTrue((self.output / "val" / "city:end").is_dir())

    def test_exact_duplicates_across_reviewed_groups_are_rejected(self):
        (self.images / self.rows[3][1]).write_bytes((self.images / self.rows[0][1]).read_bytes())
        with self.assertRaisesRegex(PREPARE.DatasetError, "identische Bildbytes"):
            self.prepare()
        self.assertFalse(self.output.exists())

    def test_path_traversal_and_symlink_escape_are_rejected(self):
        outside = self.root / "outside.png"
        outside.write_bytes(synthetic_png(80))
        self.rows[0][1] = "../outside.png"
        self.write_rows()
        with self.assertRaisesRegex(PREPARE.DatasetError, "image_path muss relativ"):
            self.prepare()
        (self.images / "escape.png").symlink_to(outside)
        self.rows[0][1] = "escape.png"
        self.write_rows()
        with self.assertRaisesRegex(PREPARE.DatasetError, "Bildpfad verlässt"):
            self.prepare()

    def test_unknown_labels_and_duplicate_sample_ids_fail(self):
        self.rows[0][2] = "typo:sign"
        self.write_rows()
        with self.assertRaisesRegex(PREPARE.DatasetError, "unbekannte Klasse"):
            self.prepare()
        self.rows[0][2] = self.labels[0]
        self.rows[1][0] = self.rows[0][0].upper()
        self.write_rows()
        with self.assertRaisesRegex(PREPARE.DatasetError, "sample_id"):
            self.prepare()

    def test_blank_group_is_not_treated_as_independent_sample(self):
        self.rows[0][3] = ""
        self.write_rows()
        with self.assertRaisesRegex(PREPARE.DatasetError, "geprüfte group_id fehlt"):
            self.prepare()

    def test_frozen_dataset_rejects_changed_source_and_preserves_original(self):
        self.prepare()
        manifest_before = (self.output / "manifest.json").read_bytes()
        first = self.rows[0][1]
        (self.images / first).write_bytes(synthetic_png(230))
        with self.assertRaisesRegex(PREPARE.DatasetError, "eingefroren"):
            self.prepare()
        self.assertEqual((self.output / "manifest.json").read_bytes(), manifest_before)

    def test_frozen_dataset_detects_tampering_and_extra_augmentation_files(self):
        manifest = self.prepare()
        sample = manifest["samples"][0]
        image = self.output / sample["dataset_path"]
        original = image.read_bytes()
        image.write_bytes(synthetic_png(240))
        with self.assertRaisesRegex(PREPARE.DatasetError, "Eingefrorenes Bild"):
            self.prepare()
        image.write_bytes(original)
        extra = image.with_name("untracked-augmentation.png")
        extra.write_bytes(original)
        with self.assertRaisesRegex(PREPARE.DatasetError, "Zusätzliche Dateien"):
            self.prepare()

    def test_existing_directory_without_manifest_is_not_overwritten(self):
        self.output.mkdir()
        marker = self.output / "keep.txt"
        marker.write_text("keep")
        with self.assertRaisesRegex(PREPARE.DatasetError, "ohne lesbares Manifest"):
            self.prepare()
        self.assertEqual(marker.read_text(), "keep")

    def test_default_course_class_count_is_strict_but_small_explicit_fixture_works(self):
        with self.assertRaisesRegex(PREPARE.DatasetError, "136 Klassen"):
            PREPARE.load_classes(self.classes, require_136=True)
        self.assertEqual(PREPARE.load_classes(self.classes)[0], self.labels)

    def test_class_names_cannot_escape_dataset_directories(self):
        self.write_classes(self.labels + ["../bad"])
        with self.assertRaisesRegex(PREPARE.DatasetError, "sichere Ordnernamen"):
            self.prepare()

    def test_cli_defaults_point_to_fixed_beginner_structure(self):
        plan = {"lock_sha256": "abc", "counts": {"images": dict.fromkeys(PREPARE.SPLITS, 1),
                                                   "groups": dict.fromkeys(PREPARE.SPLITS, 1)},
                "missing_classes": {"val": [], "test": []}, "image_validation": "pillow"}
        with mock.patch.object(PREPARE, "prepare_dataset", return_value=plan) as prepare:
            with mock.patch("sys.stdout", new_callable=io.StringIO):
                self.assertEqual(PREPARE.main([]), 0)
        prepare.assert_called_once_with(Path("data/annotations.csv"), Path("data/raw/images"),
                                        Path("data/dataset"), PREPARE.DEFAULT_CLASSES, "20261026",
                                        require_136=True)


if __name__ == "__main__":
    unittest.main()
