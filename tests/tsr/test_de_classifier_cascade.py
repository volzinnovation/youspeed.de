"""Routing, calibration and partition protections for the diagnostic cascade."""
import importlib.util
from pathlib import Path
import unittest

import numpy as np

SPEC = importlib.util.spec_from_file_location(
    "de_classifier_cascade", Path(__file__).resolve().parents[2] / "scripts/tsr/de_classifier_cascade.py")
cascade = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(cascade)


def fixture():
    names = np.array(["stop"] + [f"class:{i}" for i in range(1, 134)] + ["city:start", "city:end"])
    logits = np.zeros((4, 136))
    logits[np.arange(4), [0, 1, 2, 3]] = 5
    return {"class_names": names, "model_class_names": names.copy(), "val_logits": logits,
            "val_labels": np.arange(4), "val_sample_ids": np.array(["v0", "v1", "v2", "v3"]),
            "val_group_ids": np.array(["d", "d", "r", "r"]), "dev_indices": np.array([0, 1]),
            "report_indices": np.array([2, 3]), "train_sample_ids": np.array(["t0", "t1"]),
            "train_group_ids": np.array(["t", "t"])}


class CascadeTests(unittest.TestCase):
    def test_exact_class_sample_and_partition_order_required(self):
        self.assertEqual(len(cascade.validate_pair(fixture(), fixture())), 136)
        for key in ("model_class_names", "val_sample_ids", "val_labels", "dev_indices"):
            with self.subTest(key=key):
                changed = fixture()
                changed[key] = changed[key][::-1]
                with self.assertRaises(ValueError):
                    cascade.validate_pair(fixture(), changed)

    def test_group_train_and_partition_leakage_rejected(self):
        for mutation in (lambda a: a.update(val_group_ids=np.array(["d"] * 4)),
                         lambda a: a.update(train_group_ids=np.array(["d", "t"])),
                         lambda a: a.update(train_sample_ids=np.array(["v0", "t1"])),
                         lambda a: a.update(report_indices=np.array([1, 3])),
                         lambda a: a.update(report_indices=np.array([2, 2])),
                         lambda a: a.update(report_indices=np.array([2., 3.]))):
            arrays = fixture()
            mutation(arrays)
            with self.assertRaises(ValueError):
                cascade.validate_pair(arrays, arrays)

    def test_routing_and_explicit_all_fallback_sentinel(self):
        small = np.array([[1000., 0.], [.1, 0.]])
        yolo = np.array([[0., 1.], [0., 1.]])
        prediction, early, confidence = cascade.route_predictions(small, yolo, 1., .9)
        np.testing.assert_array_equal(prediction, [0, 1])
        np.testing.assert_array_equal(early, [True, False])
        self.assertEqual(confidence[0], 1.)
        prediction, early, _ = cascade.route_predictions(small, yolo, 1., 1.)
        np.testing.assert_array_equal(prediction, [1, 1])
        self.assertFalse(early.any())
        np.testing.assert_array_equal(cascade.route_predictions(small, yolo, 1., 0.)[0], [0, 0])

    def test_calibration_uses_development_arrays_only_and_preserves_argmax(self):
        arrays = fixture()
        first = cascade.select_gate(arrays["val_logits"][:2], arrays["val_logits"][:2], arrays["val_labels"][:2], arrays["class_names"].tolist())
        arrays["val_logits"][2:] = -500
        arrays["val_labels"][2:] = 133
        second = cascade.select_gate(arrays["val_logits"][:2], arrays["val_logits"][:2], arrays["val_labels"][:2], arrays["class_names"].tolist())
        self.assertEqual(first, second)
        self.assertLessEqual(first["calibration"]["dev_nll"], first["calibration"]["uncalibrated_dev_nll"])
        probabilities = cascade.softmax(arrays["val_logits"][:2], first["calibration"]["temperature"])
        np.testing.assert_array_equal(probabilities.argmax(1), [0, 1])

    def test_guard_counts_false_positives_for_unsupported_critical_classes(self):
        baseline = cascade.metrics([1, 1], [1, 1], ["stop", "other"])
        candidate = cascade.metrics([1, 1], [0, 1], ["stop", "other"])
        guard = cascade.critical_guard(baseline, candidate)
        self.assertFalse(guard["passes"])
        self.assertEqual(guard["violations"][0]["cascade_fp"], 1)

    def test_no_nontrivial_candidate_can_pass_for_critical_wrong_confident_stage(self):
        # Small is wrong on every row; T calibration reaches upper bound but
        # its 10000-unit margins remain confidently wrong at all thresholds <1.
        small = np.array([[0., 10000.], [10000., 0.]])
        yolo = small[:, ::-1]
        result = cascade.select_gate(small, yolo, np.array([0, 1]), ["stop", "give_way"])
        self.assertEqual(result["selected"]["threshold"], 1.)
        self.assertTrue(result["no_early_exit_gain"])
        self.assertEqual(result["selected"]["fallback_fraction"], 1.)

    def test_selection_maximizes_early_share_subject_to_guard(self):
        logits = np.array([[5., 0.], [0., 5.]])
        result = cascade.select_gate(logits, logits, np.array([0, 1]), ["stop", "other"])
        self.assertEqual(result["selected"]["small_stage_share"], 1.)
        self.assertFalse(result["no_early_exit_gain"])
        self.assertTrue(result["selected"]["critical_guard"]["passes"])
        self.assertEqual(len(result["development_grid"]), len(cascade.THRESHOLDS))

    def test_cost_estimate_pays_small_upfront_even_all_fallback(self):
        meta = lambda ms: {"feature_cpu_latency": {"threads": 1, "dtype": "float32", "p50_ms": ms, "scope": "forward only"}}
        result = cascade.cost_estimate(meta(4.), meta(60.), 1.)
        self.assertEqual(result["estimated_average_component_ms"], 64.)
        self.assertLess(result["estimated_cost_reduction_fraction"], 0.)


if __name__ == "__main__":
    unittest.main()
