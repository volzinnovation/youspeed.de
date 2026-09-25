import importlib.util
from pathlib import Path
import tempfile
import unittest


spec = importlib.util.spec_from_file_location(
    "end_sign_training", Path(__file__).parents[2] / "scripts/tsr/train_fr_end_sign_classifier.py"
)
training = importlib.util.module_from_spec(spec)
spec.loader.exec_module(training)


class EndSignTrainingTests(unittest.TestCase):
    def test_reordered_same_size_head_is_rejected(self):
        names = list(training.TARGET_CLASSES)
        training.validate_vocabulary(names, names, names, names, expected_count=5)
        with self.assertRaisesRegex(ValueError, "class order differs"):
            training.validate_vocabulary(names, list(reversed(names)), names, names, expected_count=5)

    def test_dropping_non_target_classes_is_rejected(self):
        names = ["B14-50", *training.TARGET_CLASSES]
        with self.assertRaisesRegex(ValueError, "class order differs"):
            training.validate_vocabulary(names, names[1:], names[1:], names[1:], expected_count=6)
        with self.assertRaisesRegex(ValueError, "original 256-class head"):
            training.validate_vocabulary(names, names, names, names)

    def test_missing_target_variant_or_noncontiguous_index_is_rejected(self):
        names = ["B31", "B33-30", "B33-50", "B33-70", "B14-90"]
        with self.assertRaisesRegex(ValueError, "classes are missing"):
            training.validate_vocabulary(names, names, names, names, expected_count=5)
        with self.assertRaisesRegex(ValueError, "consecutive"):
            training.ordered_model_names({0: "B31", 2: "B33-30"})

    def test_metrics_distinguish_false_ends_and_wrong_end_number(self):
        metrics = training.ClassificationMetrics(["B14-50", "B31", "B33-30", "B33-50"])
        metrics.add([0, 0, 1, 2, 3], [0, 1, 1, 3, 3], [.9, .8, .6, .8, .9],
                    [[0], [1], [1], [3], [3]])
        result = metrics.result()
        self.assertEqual(result["sample_count"], 5)
        self.assertEqual(result["top1_accuracy"], .6)
        self.assertAlmostEqual(result["target"]["family_precision"], .75)
        self.assertEqual(result["target"]["family_recall"], 1)
        self.assertAlmostEqual(result["target"]["exact_class_recall"], 2 / 3)
        self.assertEqual(result["per_class"]["B31"]["precision"], .5)
        self.assertEqual(result["per_class"]["B31"]["precision_at_0_70"], 0)
        self.assertEqual(result["per_class"]["B33-30"]["confusions"], {"B33-50": 1})

    def test_incomplete_or_invalid_predictions_do_not_inflate_results(self):
        metrics = training.ClassificationMetrics(["B31"])
        with self.assertRaisesRegex(ValueError, "Incomplete"):
            metrics.add([0], [], [.9], [[0]])
        with self.assertRaisesRegex(ValueError, "Invalid model score"):
            metrics.add([0], [0], [float("nan")], [[0]])
        self.assertEqual(metrics.result()["sample_count"], 0)

    def test_inventory_counts_training_repeat_files_but_ignores_metadata(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary)
            (path / "B31").mkdir()
            (path / "B33-30").mkdir()
            (path / "B31" / "a.JPG").write_bytes(b"example")
            (path / "B31" / "a_repeat1.jpg").symlink_to("a.JPG")
            (path / "B31" / "metadata.json").write_text("{}")
            names, counts = training.split_inventory(path)
            self.assertEqual(names, ["B31", "B33-30"])
            self.assertEqual(counts, {"B31": 2, "B33-30": 0})

    def test_default_budget_and_transform_contract(self):
        common = ["--data", "data", "--model", "original.pt", "--output", "run"]
        args = training.parse_args(common)
        self.assertEqual((args.epochs, args.batch, args.imgsz, args.max_hours), (15, 32, 224, 3.25))
        for extra in (["--imgsz", "256"], ["--epochs", "0"], ["--lr", "nan"], ["--max-hours", "inf"]):
            with self.assertRaises(SystemExit):
                training.parse_args(common + extra)

    def test_upload_allowlist_excludes_images_and_optimizer_state(self):
        from fnmatch import fnmatch
        for private in ["weights/training-state.pt", "train/B31/image.jpg", "weights/epoch-001.pt"]:
            self.assertFalse(any(fnmatch(private, pattern) for pattern in training.HUB_FILES))
        for artifact in ["baseline-metrics.json", "weights/best.pt", "weights/last.pt"]:
            self.assertTrue(any(fnmatch(artifact, pattern) for pattern in training.HUB_FILES))


if __name__ == "__main__":
    unittest.main()
