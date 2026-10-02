import hashlib
import importlib.util
import io
import json
from pathlib import Path
import random
import stat
import tempfile
import unittest
import zipfile

from PIL import Image

spec = importlib.util.spec_from_file_location(
    "prepare_fr_end_sign_training",
    Path(__file__).parents[2] / "scripts/tsr/prepare_fr_end_sign_training.py",
)
preparation = importlib.util.module_from_spec(spec)
spec.loader.exec_module(preparation)


def picture(seed):
    rng = random.Random(seed)
    image = Image.frombytes("RGB", (64, 64), bytes(rng.randrange(256) for _ in range(64 * 64 * 3)))
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class PrepareEndSignTrainingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.archive = self.root / "train.zip"

    def tearDown(self):
        self.temp.cleanup()

    def write_archive(self, entries):
        with zipfile.ZipFile(self.archive, "w") as archive:
            for name, data in entries:
                archive.writestr(name, data)
        return hashlib.sha256(self.archive.read_bytes()).hexdigest()

    def basic_entries(self):
        return [(f"train/{name}/{index}.png", picture(f"{name}/{index}"))
                for name in ("B31", "B33-50", "B14-50") for index in range(6)]

    def run_prepare(self, entries, output="prepared"):
        digest = self.write_archive(entries)
        path = self.root / output
        summary = preparation.prepare(self.archive, path, .25, 11, digest)
        records = [json.loads(line) for line in (path / "inventory.jsonl").read_text().splitlines()]
        return path, summary, records

    def test_exact_and_visual_duplicates_never_cross_splits(self):
        entries = self.basic_entries()
        base = entries[0][1]
        edited = Image.open(io.BytesIO(base)).convert("RGB")
        red, green, blue = edited.getpixel((0, 0))
        edited.putpixel((0, 0), (red ^ 1, green, blue))
        output = io.BytesIO()
        edited.save(output, format="PNG")
        self.assertNotEqual(base, output.getvalue())
        self.assertEqual(preparation.image_fingerprints(base)[1], preparation.image_fingerprints(output.getvalue())[1])
        entries.extend([("train/B31/renamed.png", base), ("train/B31/reencoded.png", output.getvalue())])
        _, _, records = self.run_prepare(entries)
        selected = [record for record in records if record["member_path"] in
                    {"train/B31/0.png", "train/B31/renamed.png", "train/B31/reencoded.png"}]
        self.assertEqual(len({record["duplicate_group"] for record in selected}), 1)
        self.assertEqual(len({record["split"] for record in selected}), 1)
        groups = {}
        for record in records:
            groups.setdefault(record["duplicate_group"], set()).add(record["split"])
        self.assertTrue(all(len(splits) == 1 for splits in groups.values()))

    def test_conflicting_duplicate_labels_are_quarantined(self):
        entries = self.basic_entries()
        entries.append(("train/B14-50/conflict.png", entries[0][1]))
        _, summary, records = self.run_prepare(entries)
        conflicting = [record for record in records if record["member_path"] in
                       {"train/B31/0.png", "train/B14-50/conflict.png"}]
        self.assertEqual(summary["quarantined_image_count"], 2)
        self.assertTrue(all(record["split"] == "quarantine" and not record["output_paths"] for record in conflicting))

    def test_oversamples_only_target_training_and_preserves_class_order(self):
        path, summary, records = self.run_prepare(self.basic_entries())
        self.assertEqual(summary["class_names"], ["B14-50", "B31", "B33-50"])
        for record in records:
            expected = 4 if record["split"] == "train" and record["class_name"] in {"B31", "B33-50"} else 1
            self.assertEqual(len(record["output_paths"]), expected)
            for linked in record["output_paths"]:
                self.assertEqual((path / linked).stat().st_ino, (path / record["source_path"]).stat().st_ino)
        self.assertTrue(all(summary["target_counts"][name]["val"] > 0 for name in ("B31", "B33-50")))
        self.assertEqual(summary["inventory_sha256"], preparation.file_sha256(path / "inventory.jsonl"))
        self.assertIn("not an independent route holdout", " ".join(summary["grouping_limitations"]))

    def test_seed_deterministically_assigns_groups(self):
        _, first, records_a = self.run_prepare(self.basic_entries(), "first")
        _, second, records_b = self.run_prepare(list(reversed(self.basic_entries())), "second")
        assignments = lambda records: {record["member_path"]: record["split"] for record in records}
        self.assertEqual(assignments(records_a), assignments(records_b))
        self.assertEqual(first["train_counts"], second["train_counts"])

    def test_checkpoint_vocabulary_quarantines_archive_only_classes(self):
        entries = self.basic_entries() + [("train/B6D-M6j/extra.png", picture("unsupported"))]
        digest = self.write_archive(entries)
        vocabulary = self.root / "vocabulary.json"
        class_names = ["B14-50", "B31", "B33-50"]
        vocabulary.write_text(json.dumps({"class_names": class_names, "source_sha256": "model-digest"}))
        path = self.root / "with-vocabulary"
        summary = preparation.prepare(self.archive, path, expected_sha256=digest, model_vocabulary=vocabulary)
        self.assertEqual(summary["class_names"], class_names)
        self.assertTrue(summary["checkpoint_head_preserved"])
        self.assertEqual(summary["unsupported_class_counts"], {"B6D-M6j": 1})
        self.assertEqual(summary["source_model_sha256"], "model-digest")
        self.assertEqual(summary["model_vocabulary_sha256"], preparation.file_sha256(vocabulary))
        for split in ("train", "val"):
            self.assertEqual(sorted(item.name for item in (path / split).iterdir()), class_names)
        records = [json.loads(line) for line in (path / "inventory.jsonl").read_text().splitlines()]
        excluded = next(record for record in records if record["class_name"] == "B6D-M6j")
        self.assertEqual(excluded["split"], "quarantine")
        self.assertEqual(excluded["exclusion_reason"], "class_not_in_checkpoint_vocabulary")
        self.assertFalse(excluded["output_paths"])

    def test_missing_checkpoint_class_and_reordered_head_are_rejected(self):
        digest = self.write_archive(self.basic_entries())
        vocabulary = self.root / "vocabulary.json"
        for names, reason in ((["B14-50", "B31", "B33-50", "missing"], "missing from source"),
                              (["B31", "B14-50", "B33-50"], "head-order-placeholder")):
            vocabulary.write_text(json.dumps({"class_names": names}))
            message = "sorted unique ImageFolder" if reason == "head-order-placeholder" else reason
            with self.assertRaisesRegex(preparation.PreparationError, message):
                preparation.prepare(self.archive, self.root / "invalid-vocabulary", expected_sha256=digest,
                                    model_vocabulary=vocabulary)
            self.assertFalse((self.root / "invalid-vocabulary").exists())

    def test_rejects_path_traversal_and_symlinks(self):
        for path in ("../escaped.png", "train/B31/../../escaped.png", "/absolute.png", "train\\B31\\escape.png"):
            with self.subTest(path=path):
                digest = self.write_archive([(path, picture(1))])
                with self.assertRaises(preparation.PreparationError):
                    preparation.prepare(self.archive, self.root / "unsafe", expected_sha256=digest)
                self.assertFalse((self.root / "unsafe").exists())
        member = zipfile.ZipInfo("train/B31/link.png")
        member.create_system = 3
        member.external_attr = (stat.S_IFLNK | 0o777) << 16
        digest = self.write_archive([(member, b"../../../secret")])
        with self.assertRaises(preparation.PreparationError):
            preparation.prepare(self.archive, self.root / "unsafe", expected_sha256=digest)

    def test_hash_decode_and_existing_output_fail_without_partial_dataset(self):
        digest = self.write_archive(self.basic_entries())
        with self.assertRaisesRegex(preparation.PreparationError, "SHA-256 mismatch"):
            preparation.prepare(self.archive, self.root / "bad-hash")
        output = self.root / "existing"
        output.mkdir()
        (output / "keep.txt").write_text("user data")
        with self.assertRaisesRegex(preparation.PreparationError, "empty directory"):
            preparation.prepare(self.archive, output, expected_sha256=digest)
        self.assertEqual((output / "keep.txt").read_text(), "user data")
        digest = self.write_archive([("train/B31/broken.png", b"not an image")])
        with self.assertRaisesRegex(preparation.PreparationError, "cannot be decoded"):
            preparation.prepare(self.archive, self.root / "bad-image", expected_sha256=digest)
        self.assertFalse((self.root / "bad-image").exists())
        self.assertFalse(list(self.root.glob(".bad-image-prepare-*")))


if __name__ == "__main__":
    unittest.main()
