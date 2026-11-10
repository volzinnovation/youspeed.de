"""Contract and metric checks for frozen-feature classifier experiments."""
import importlib.util
from pathlib import Path
import unittest

import numpy as np


SPEC = importlib.util.spec_from_file_location(
    "de_classical_classifier_experiment",
    Path(__file__).resolve().parents[2] / "scripts/tsr/de_classical_classifier_experiment.py",
)
experiment = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(experiment)


def fixture():
    return {
        "train_features": np.array([[1, 2], [3, 4], [5, 6]], dtype=np.float32),
        "train_labels": np.array([0, 1, 2]),
        "val_features": np.array([[2, 3], [4, 5], [6, 7], [8, 9]], dtype=np.float32),
        "val_labels": np.array([0, 1, 1, 2]),
        "class_names": np.array(["a", "b", "c"]),
        "train_sample_ids": np.array(["t1", "t2", "t3"]),
        "val_sample_ids": np.array(["v1", "v2", "v3", "v4"]),
        "train_groups": np.array(["t1", "t2", "t3"]),
        "val_groups": np.array(["v1", "v1", "v2", "v2"]),
        "dev_indices": np.array([0, 1]),
        "report_indices": np.array([2, 3]),
    }


class FrozenFeatureContractTests(unittest.TestCase):
    def test_valid_partition_and_geometry(self):
        result = experiment.validate_arrays(fixture(), np)
        self.assertEqual(result["feature_dimensions"], 2)
        self.assertEqual(result["report_groups"], 1)
        self.assertEqual(result["development_rows"], 2)

    def test_cross_split_group_and_sample_leaks_are_rejected(self):
        for key, value in [("train_groups", "v1"), ("train_sample_ids", "v1")]:
            with self.subTest(key=key):
                arrays = fixture()
                arrays[key][0] = value
                with self.assertRaisesRegex(ValueError, "overlap"):
                    experiment.validate_arrays(arrays, np)
        arrays = fixture()
        arrays["val_groups"] = np.array(["same", "same", "same", "same"])
        with self.assertRaisesRegex(ValueError, "groups overlap"):
            experiment.validate_arrays(arrays, np)

    def test_indices_must_be_complete_unique_disjoint_and_in_bounds(self):
        cases = [np.array([1, 3]), np.array([2, 2]), np.array([2]), np.array([2, 4])]
        for indices in cases:
            with self.subTest(indices=indices.tolist()):
                arrays = fixture()
                arrays["report_indices"] = indices
                with self.assertRaises(ValueError):
                    experiment.validate_arrays(arrays, np)

    def test_nonfinite_features_and_silent_label_remapping_are_rejected(self):
        arrays = fixture()
        arrays["train_features"][0, 0] = np.nan
        with self.assertRaisesRegex(ValueError, "Nonfinite"):
            experiment.validate_arrays(arrays, np)
        arrays = fixture()
        arrays["val_labels"][0] = 3
        with self.assertRaisesRegex(ValueError, "outside"):
            experiment.validate_arrays(arrays, np)
        arrays = fixture()
        arrays["class_names"] = np.array(["a", "a", "c"])
        with self.assertRaisesRegex(ValueError, "unique"):
            experiment.validate_arrays(arrays, np)

    def test_probability_columns_align_by_estimator_classes(self):
        class Estimator:
            classes_ = np.array([2, 0])

            def predict_proba(self, features):
                return np.array([[0.8, 0.2], [0.1, 0.9]])
        result = experiment.aligned_probabilities(Estimator(), np.zeros((2, 4)), 3, np)
        np.testing.assert_allclose(result, [[0.2, 0, 0.8], [0.9, 0, 0.1]])

    def test_metrics_distinguish_unsupported_classes_and_false_positive_classes(self):
        metrics = experiment.calculate_metrics([0, 0, 1], [0, 2, 1], ["a", "b", "c", "d"])
        self.assertAlmostEqual(metrics["macro_f1_supported"], (2 / 3 + 1) / 2)
        self.assertAlmostEqual(metrics["weighted_f1"], (2 * 2 / 3 + 1) / 3)
        self.assertEqual(metrics["unsupported_true_classes"], ["c", "d"])
        self.assertEqual(metrics["per_class"][2]["f1"], 0)
        self.assertIsNone(metrics["per_class"][3]["f1"])
        self.assertIsNone(metrics["city_macro_f1_supported"])

    def test_candidate_forests_bound_dense_multiclass_storage(self):
        specs = experiment.candidate_specs()
        self.assertEqual(len(specs), 5)
        self.assertEqual(len(experiment.candidate_specs(True)), 2)
        for spec in specs:
            if spec["kind"] in {"random_forest", "extra_trees"}:
                self.assertLessEqual(spec["n_estimators"], 256)
                self.assertLessEqual(spec["max_leaf_nodes"], 512)
                self.assertGreaterEqual(spec["min_samples_leaf"], 2)


if __name__ == "__main__":
    unittest.main()
