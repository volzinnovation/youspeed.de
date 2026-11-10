"""Prevent report leakage and verify the training-only class-prior adjustment."""
import importlib.util
import hashlib
import json
import math
from pathlib import Path
import unittest
import tempfile

try:
    from PIL import Image, ImageOps
except ImportError:
    Image = ImageOps = None


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/tsr/de_neural_refinement.py"
SPEC = importlib.util.spec_from_file_location("de_neural_refinement", SCRIPT)
refinement = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(refinement)

try:
    import torch
except ImportError:
    torch = None


class PartitionTests(unittest.TestCase):
    def setUp(self):
        self.rows = [dict(sample_id=f"s{i}", sha256=f"h{i}", group_id=f"g{i}") for i in range(4)]
        self.partition = dict(manifest_sha256="manifest", val_sample_ids=[f"s{i}" for i in range(4)],
                              dev_indices=[0, 2], report_indices=[1, 3])

    def check(self):
        return refinement.validate_partition(self.partition, self.rows, "manifest", ["a", "b"])

    def test_valid_partition(self):
        self.assertEqual(self.check(), ([0, 2], [1, 3]))

    def test_order_binding(self):
        self.partition["val_sample_ids"] = list(reversed(self.partition["val_sample_ids"]))
        with self.assertRaisesRegex(ValueError, "order"):
            self.check()

    def test_group_leakage_is_rejected(self):
        self.rows[1]["group_id"] = self.rows[0]["group_id"]
        with self.assertRaisesRegex(ValueError, "group_id"):
            self.check()

    def test_exact_duplicate_leakage_is_rejected(self):
        self.rows[1]["sha256"] = self.rows[0]["sha256"]
        with self.assertRaisesRegex(ValueError, "sha256"):
            self.check()

    def test_optional_source_and_pixel_overlap_are_rejected(self):
        for key in ("source_id", "rgb_sha256"):
            with self.subTest(key=key):
                self.rows[0][key] = self.rows[1][key] = "same-source"
                with self.assertRaisesRegex(ValueError, key):
                    self.check()
                del self.rows[0][key]
                del self.rows[1][key]

    def test_missing_or_overlapping_indices_are_rejected(self):
        for dev, report in [([0, 2], [1]), ([0, 2], [1, 2, 3]), ([0, 0, 2], [1, 3]), ([0, 2], [1, True])]:
            with self.subTest(dev=dev, report=report):
                self.partition.update(dev_indices=dev, report_indices=report)
                with self.assertRaises(ValueError):
                    self.check()

    def test_manifest_and_class_binding(self):
        self.partition["manifest_sha256"] = "another"
        with self.assertRaisesRegex(ValueError, "manifest"):
            self.check()
        self.partition["manifest_sha256"] = "manifest"
        self.partition["classes"] = ["b", "a"]
        with self.assertRaisesRegex(ValueError, "class order"):
            self.check()


class PriorAndScheduleTests(unittest.TestCase):
    def test_training_prior_scale_invariance(self):
        a = refinement.log_prior_offsets([10, 100, 30], .25)
        b = refinement.log_prior_offsets([100, 1000, 300], .25)
        self.assertEqual(a, b)
        self.assertAlmostEqual(a[1] - a[0], .25 * math.log(10))

    def test_tau_zero_is_plain_cross_entropy(self):
        self.assertEqual(refinement.log_prior_offsets([10, 100, 30], 0), [0, 0, 0])

    def test_missing_training_class_is_not_silently_smoothed(self):
        for counts, tau in [([0, 10], .25), ([1, -2], .25), ([1, 10], -1), ([1, 10], float("nan"))]:
            with self.subTest(counts=counts, tau=tau):
                with self.assertRaises(ValueError):
                    refinement.log_prior_offsets(counts, tau)

    def test_schedule_head_base_and_final_floor(self):
        rates = [refinement.epoch_learning_rate(3e-5, 3e-4, e, 10) for e in range(1, 11)]
        self.assertEqual(rates[0], 3e-4)
        self.assertAlmostEqual(rates[1], 3e-5)
        self.assertAlmostEqual(rates[-1], 3e-6)
        self.assertTrue(all(a >= b for a, b in zip(rates, rates[1:])))


class CityRepairTests(unittest.TestCase):
    def setUp(self):
        self.classes = ["old", "city:start", "city:end"]
        self.train = []
        for group, labels in [("large", ["city:start"] * 3 + ["city:end"]),
                              ("small", ["city:start", "city:end"]), ("old", ["old"])]:
            for label in labels:
                i = len(self.train)
                self.train.append(dict(sample_id=f"t{i}", sha256=f"h{i}", group_id=group, label=label))
        self.val = [dict(sample_id="v1", sha256="v1", group_id="v1", label="old"),
                    dict(sample_id="v2", sha256="v2", group_id="v2", label="city:start")]
        self.partition = dict(dev_indices=[0], report_indices=[1])

    def test_smallest_whole_group_and_report_preserved(self):
        train, val, partition, audit = refinement.city_dev_repair(self.partition, self.train, self.val, self.classes)
        self.assertEqual(audit["selected_groups"], ["small"])
        self.assertEqual(partition["report_indices"], [1])
        self.assertEqual(partition["dev_indices"], [0, 2, 3])
        self.assertEqual(val[:2], self.val)
        self.assertFalse(any(r["group_id"] == "small" for r in train))
        self.assertEqual({r["label"] for r in train}, set(self.classes))

    def test_all_rows_of_selected_group_are_moved(self):
        self.train.append(dict(sample_id="extra", sha256="extra", group_id="small", label="old"))
        train, val, _, audit = refinement.city_dev_repair(self.partition, self.train, self.val, self.classes)
        self.assertEqual(audit["selected_groups"], ["small"])
        self.assertIn("extra", [r["sample_id"] for r in val])
        self.assertNotIn("extra", [r["sample_id"] for r in train])

    def test_holdout_cannot_remove_last_class_support(self):
        only = [r for r in self.train if r["group_id"] != "large"]
        with self.assertRaisesRegex(ValueError, "preserves all"):
            refinement.city_dev_repair(self.partition, only, self.val, self.classes)

    def test_cross_split_source_overlap_rejected(self):
        self.train[0]["source_id"] = self.val[0]["source_id"] = "same"
        with self.assertRaisesRegex(ValueError, "source_id"):
            refinement.city_dev_repair(self.partition, self.train, self.val, self.classes)


@unittest.skipIf(Image is None, "Pillow required for native source crop verification")
class SourceAugmentationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.classes = ["old", "city:start", "city:end"]
        self.train = [dict(sample_id="old", sha256="old", rgb_sha256="old", source_id="old", group_id="old", label="old")]
        self.val = [dict(sample_id="val", sha256="val", rgb_sha256="val", source_id="val", group_id="val", label="old")]

    def tearDown(self):
        self.temp.cleanup()

    def row(self, number, group="source"):
        image = Image.new("RGB", (2, 4), (number, 2, 3))
        image.paste((4, 5, 6), (0, 2, 2, 4))
        path = self.root / f"{number}.png"
        image.save(path)
        def digest(value):
            return hashlib.sha256(str(value.size).encode() + b"\0" + value.tobytes()).hexdigest()
        return dict(sample_id=f"source-{number}", path=path.name, label="city:start", class_index=1,
                    group_id=group, source_id=f"picture-{number}", label_origin="source_annotation",
                    sha256=hashlib.sha256(path.read_bytes()).hexdigest(), rgb_sha256=digest(image),
                    sign_rgb_sha256=digest(image.crop((0, 0, 2, 2))), geometry={"sign_in_crop": [0, 0, 2, 2]})

    def apply(self, rows):
        path = self.root / "manifest.json"
        path.write_text(json.dumps({"existing_manifest_sha256": "manifest", "samples": rows}))
        return refinement.source_annotation_augmentation(path, self.train, self.val, [], self.classes,
                                                        "manifest", Image, ImageOps)

    def test_native_source_is_preserved_and_explicit_sign_window_retained(self):
        row = self.row(1)
        train, audit = self.apply([row])
        self.assertEqual(train[-1]["training_crop_box"], [0, 0, 2, 2])
        self.assertEqual(train[-1]["sha256"], row["sha256"])
        self.assertEqual(audit["source_fraction_per_epoch"], .5)
        self.assertFalse(audit["oversampling"])

    def test_one_evaluation_match_excludes_whole_connected_source_group(self):
        one, two, clean = self.row(1), self.row(2), self.row(3, "clean")
        one["existing_matches"] = [{"sample_id": "val", "split": "val"}]
        train, audit = self.apply([one, two, clean])
        self.assertEqual([r["sample_id"] for r in train], ["old", "source-3"])
        self.assertEqual(audit["source_intake_count"], 3)
        self.assertIn("connected_group_evaluation_overlap", audit["records"][1]["exclusion_reasons"])

    def test_pixel_hash_and_geometry_corruption_rejected(self):
        for key, value in [("sign_rgb_sha256", "wrong"), ("geometry", {"sign_in_crop": [0, 0, 3, 4]})]:
            with self.subTest(key=key):
                row = self.row(1)
                row[key] = value
                with self.assertRaises(ValueError):
                    self.apply([row])

    def test_sign_pixels_catch_padded_evaluation_duplicate(self):
        overlap, clean = self.row(1), self.row(2, "clean")
        self.val[0]["rgb_sha256"] = overlap["sign_rgb_sha256"]
        train, audit = self.apply([overlap, clean])
        self.assertEqual([r["sample_id"] for r in train], ["old", "source-2"])
        self.assertIn("evaluation_native_or_sign_rgb_sha256", audit["records"][0]["exclusion_reasons"])


@unittest.skipIf(torch is None, "Run in the existing KI Torch runtime")
class LossTests(unittest.TestCase):
    def test_equal_frequency_offset_preserves_ce(self):
        logits = torch.tensor([[2.0, 1.0, -1.0], [0.1, .5, 1.2]], dtype=torch.float64)
        labels = torch.tensor([0, 2])
        offsets = torch.tensor(refinement.log_prior_offsets([10, 10, 10], .25), dtype=torch.float64)
        torch.testing.assert_close(torch.nn.functional.cross_entropy(logits, labels),
                                   torch.nn.functional.cross_entropy(logits + offsets, labels))

    def test_gradient_is_finite_with_rare_class(self):
        logits = torch.zeros(2, 3, dtype=torch.float64, requires_grad=True)
        labels = torch.tensor([0, 2])
        offsets = torch.tensor(refinement.log_prior_offsets([1, 10000, 10], .25), dtype=torch.float64)
        loss = torch.nn.functional.cross_entropy(logits + offsets, labels)
        loss.backward()
        self.assertTrue(torch.isfinite(loss).item())
        self.assertTrue(torch.isfinite(logits.grad).all().item())
        # At equal visual evidence, a frequent-class offset imposes a larger
        # negative gradient on a correctly labelled rare class than plain CE.
        self.assertLess(logits.grad[0, 0].item(), -1 / 3)


if __name__ == "__main__":
    unittest.main()
