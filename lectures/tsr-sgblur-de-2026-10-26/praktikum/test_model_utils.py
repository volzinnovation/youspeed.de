"""Fachliche Tests ohne ML-Installation: python -m unittest test_model_utils.py."""
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from model_utils import (load_classes, load_manifest, metrics_from_predictions,
                         old_class_regression, samples_for_split, sha256)
from evaluate import write_reports


class EvaluationTests(unittest.TestCase):
    def setUp(self):
        self.classes = load_classes()

    def test_fixed_inventory_keeps_original_labels_and_appends_city(self):
        self.assertEqual(len(self.classes), 136)
        self.assertEqual(self.classes[-2:], ["city:start", "city:end"])
        self.assertEqual(self.classes[70], "maxspeed:70")

    def test_confusion_and_precision_recall_f1_are_not_accuracy(self):
        result = metrics_from_predictions([0, 0, 1, 1], [0, 1, 1, 1], self.classes)
        self.assertEqual(result["confusion"][0][1], 1)
        self.assertEqual(result["accuracy"], 0.75)
        self.assertAlmostEqual(result["per_class"][1]["precision"], 2 / 3)
        self.assertEqual(result["per_class"][1]["recall"], 1)
        self.assertEqual(result["per_class"][1]["f1"], 0.8)
        self.assertIsNone(result["per_class"][2]["recall"])

    def test_baseline_cannot_emit_city_and_is_scored_on_city_truth(self):
        result = metrics_from_predictions([134, 135], [11, 11], self.classes)
        self.assertEqual(result["city_macro_f1_supported"], 0)
        self.assertEqual(result["per_class"][134]["support"], 1)

    def test_old_gate_excludes_new_city_target_images(self):
        truth = list(range(134)) + [134, 135]
        baseline = list(range(134)) + [0, 0]
        candidate = list(range(134)) + [134, 135]
        gate = old_class_regression(truth, baseline, candidate, self.classes)
        self.assertEqual(gate["status"], "BESTANDEN")
        self.assertEqual(gate["baseline"]["accuracy"], 1)
        self.assertEqual(gate["baseline"]["per_class"][0]["precision"], 1)

    def test_any_supported_old_class_decline_fails_even_if_city_improves(self):
        truth = list(range(136))
        baseline = list(range(134)) + [0, 0]
        candidate = list(range(136)); candidate[70] = 134
        gate = old_class_regression(truth, baseline, candidate, self.classes)
        self.assertEqual(gate["status"], "REGRESSION")
        self.assertFalse(gate["passed"])
        self.assertTrue(any("maxspeed:70" in reason for reason in gate["reasons"]))

    def test_missing_old_support_never_claims_preserved(self):
        gate = old_class_regression([0, 134], [0, 0], [0, 134], self.classes)
        self.assertEqual(gate["status"], "UNVOLLSTAENDIG")
        self.assertEqual(len(gate["missing_old_classes"]), 133)
        self.assertFalse(gate["passed"])

    def test_no_old_images_incomplete(self):
        gate = old_class_regression([134], [0], [134], self.classes)
        self.assertEqual(gate["status"], "UNVOLLSTAENDIG")

    def test_wrong_prediction_lengths_rejected(self):
        with self.assertRaises(ValueError):
            metrics_from_predictions([0], [], self.classes)

    def test_failed_regression_still_produces_readable_reports(self):
        truth = list(range(136)); old = list(range(134)) + [0, 0]
        new = list(range(136)); new[70] = 134
        report = {"split": "test", "baseline_sha256": "baseline", "candidate_sha256": "candidate",
                  "dataset_manifest_sha256": "dataset", "baseline": metrics_from_predictions(truth, old, self.classes),
                  "candidate": metrics_from_predictions(truth, new, self.classes),
                  "old_class_regression_gate": old_class_regression(truth, old, new, self.classes)}
        rows = [{"sample_id": str(i), "group_id": f"group-{i}"} for i in truth]
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "report"
            write_reports(output, report, rows, truth, old, new, self.classes)
            self.assertIn("REGRESSION", (output / "BERICHT.md").read_text())
            self.assertEqual(json.loads((output / "regression-gate.json").read_text())["status"], "REGRESSION")
            self.assertTrue((output / "old-only-per-class.csv").is_file())


class ManifestTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.classes = load_classes()
        source = Path(__file__).with_name("class-index.json")
        (self.root / "class-index.json").write_bytes(source.read_bytes())
        (self.root / "val" / self.classes[0]).mkdir(parents=True)
        sample = self.root / "val" / self.classes[0] / "sample.jpg"
        sample.write_bytes(b"unit-test-pixels-not-decoded")
        self.row = {"sample_id": "sample", "group_id": "physical-sign-1", "label": self.classes[0],
                    "class_index": 0, "split": "val", "dataset_path": str(sample.relative_to(self.root)), "sha256": sha256(sample)}
        self.manifest = {"schema_version": 1, "classes": self.classes,
                         "class_index_sha256": sha256(self.root / "class-index.json"), "samples": [self.row]}

    def tearDown(self):
        self.temporary.cleanup()

    def write_manifest(self):
        unlocked = {key: value for key, value in self.manifest.items() if key != "lock_sha256"}
        self.manifest["lock_sha256"] = hashlib.sha256(json.dumps(unlocked, ensure_ascii=False, sort_keys=True,
                                                                separators=(",", ":"), allow_nan=False).encode()).hexdigest()
        (self.root / "manifest.json").write_text(json.dumps(self.manifest))

    def test_valid_manifest_then_changed_pixels_rejected(self):
        self.write_manifest()
        manifest, _ = load_manifest(self.root, self.classes)
        self.assertEqual(len(samples_for_split(self.root, manifest, "val", self.classes)), 1)
        (self.root / self.row["dataset_path"]).write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "verändert"):
            samples_for_split(self.root, manifest, "val", self.classes)

    def test_group_leakage_rejected_even_with_recomputed_lock(self):
        self.manifest["samples"].append(dict(self.row, split="test"))
        self.write_manifest()
        with self.assertRaisesRegex(ValueError, "Datenleck"):
            load_manifest(self.root, self.classes)

    def test_unlocked_manifest_edit_rejected(self):
        self.write_manifest()
        data = json.loads((self.root / "manifest.json").read_text()); data["seed"] = "changed"
        (self.root / "manifest.json").write_text(json.dumps(data))
        with self.assertRaisesRegex(ValueError, "Lock"):
            load_manifest(self.root, self.classes)

    def test_training_demands_all_old_and_new_classes(self):
        train_path = self.root / "train" / self.classes[0] / "sample.jpg"
        train_path.parent.mkdir(parents=True); train_path.write_bytes(b"unit-test-pixels-not-decoded")
        manifest = dict(self.manifest, samples=[dict(self.row, split="train", dataset_path=str(train_path.relative_to(self.root)))])
        with self.assertRaisesRegex(ValueError, "Trainingsbilder fehlen"):
            samples_for_split(self.root, manifest, "train", self.classes, require_all=True)


if __name__ == "__main__":
    unittest.main()
