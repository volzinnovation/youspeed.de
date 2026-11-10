"""Numerical and taxonomy boundaries for folding a standardized DE head."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np


SPEC = importlib.util.spec_from_file_location(
    "de_linear_head", Path(__file__).resolve().parents[2] / "scripts/tsr/de_linear_head.py"
)
folding = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(folding)


def names():
    return [f"old:{i}" for i in range(134)] + ["city:start", "city:end"]


def fixture(dimensions=8):
    rng = np.random.default_rng(42)
    return {"mean": rng.normal(size=dimensions), "scale": rng.uniform(0.5, 2, dimensions),
            "coef": rng.normal(size=(136, dimensions)), "intercept": rng.normal(size=136),
            "estimator_classes": np.arange(136), "fitted_class_names": names(),
            "expected_class_names": names()}


class LinearHeadFoldingTests(unittest.TestCase):
    def test_double_precision_matches_scaler_and_linear_algebra(self):
        data = fixture()
        weights, bias = folding.fold_standardized_head(**data, dtype="float64")
        features = np.random.default_rng(7).normal(size=(29, 8))
        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            original = ((features - data["mean"]) / data["scale"]) @ data["coef"].T + data["intercept"]
            transformed = features @ weights.T + bias
        self.assertTrue(np.isfinite(original).all() and np.isfinite(transformed).all())
        np.testing.assert_allclose(transformed, original, rtol=1e-13, atol=1e-13)

    def test_float32_rounding_is_measured_not_assumed(self):
        data = fixture(dimensions=1280)
        weights, bias = folding.fold_standardized_head(**data)
        features = np.random.default_rng(11).normal(size=(13, 1280)).astype(np.float32)
        report = folding.parity_report(features, data["mean"], data["scale"], data["coef"], data["intercept"], weights, bias)
        self.assertEqual(weights.dtype, np.dtype("float32"))
        self.assertEqual(report["argmax_disagreements"], 0)
        self.assertGreater(report["max_absolute_logit_error"], 0)
        self.assertLess(report["max_absolute_logit_error"], 0.0002)
        self.assertLess(report["max_absolute_probability_error"], 0.0001)

    def test_cancellation_can_change_argmax_and_is_reported(self):
        data = fixture(dimensions=1)
        data["mean"] = np.array([100000.])
        data["scale"] = np.array([1.])
        data["coef"] = np.zeros((136, 1))
        data["coef"][0, 0] = 0.1
        data["intercept"] = np.full(136, -10.)
        data["intercept"][0] = 0.
        data["intercept"][1] = 0.0009
        weights, bias = folding.fold_standardized_head(**data)
        report = folding.parity_report(np.array([[100000.01]], dtype=np.float32), data["mean"],
                data["scale"], data["coef"], data["intercept"], weights, bias)
        self.assertEqual(report["argmax_disagreements"], 1)
        self.assertFalse(report["all_argmax_equal"])

    def test_missing_reordered_or_wrong_name_classes_are_rejected(self):
        for mutation in ("missing", "indices", "names", "city_names"):
            with self.subTest(mutation=mutation):
                data = fixture()
                if mutation == "missing":
                    data["estimator_classes"] = np.arange(135)
                elif mutation == "indices":
                    data["estimator_classes"][[0, 1]] = [1, 0]
                elif mutation == "names":
                    data["fitted_class_names"][0], data["fitted_class_names"][1] = data["fitted_class_names"][1], data["fitted_class_names"][0]
                else:
                    data["expected_class_names"][-1] = "wrong"
                with self.assertRaises(ValueError):
                    folding.fold_standardized_head(**data)

    def test_invalid_scaling_shapes_and_nonfinite_arrays_are_rejected(self):
        for mutation in ("zero", "negative", "nan", "intercept_shape", "mean_shape", "complex"):
            with self.subTest(mutation=mutation):
                data = fixture()
                if mutation == "zero": data["scale"][0] = 0
                elif mutation == "negative": data["scale"][0] = -1
                elif mutation == "nan": data["coef"][0, 0] = np.nan
                elif mutation == "intercept_shape": data["intercept"] = np.zeros((136, 1))
                elif mutation == "mean_shape": data["mean"] = np.zeros(9)
                else: data["coef"] = data["coef"].astype(complex)
                with self.assertRaises(ValueError):
                    folding.fold_standardized_head(**data)

    def test_float32_overflow_is_rejected(self):
        data = fixture()
        data["coef"][0, 0] = 1e40
        with self.assertRaisesRegex(ValueError, "represented"):
            folding.fold_standardized_head(**data, dtype="float32")

    def test_cli_round_trip_keeps_arrays_and_provenance(self):
        data = fixture()
        with tempfile.TemporaryDirectory() as directory:
            directory = Path(directory)
            source, index, output = directory / "fit.npz", directory / "classes.json", directory / "folded.npz"
            np.savez(source, **{key: data[key] for key in ("mean", "scale", "coef", "intercept", "estimator_classes")}, class_names=np.asarray(names()))
            index.write_text(json.dumps({"classes": names()}))
            folding.main(["--parameters", str(source), "--class-index", str(index), "--output", str(output)])
            with np.load(output, allow_pickle=False) as archive:
                self.assertEqual(archive["weights"].shape, (136, 8))
                self.assertEqual(archive["class_names"].tolist(), names())
            metadata = json.loads(output.with_suffix(".json").read_text())
            self.assertEqual(metadata["parameters_npz_sha256"], folding.sha256(source))
            self.assertEqual(metadata["output_npz_sha256"], folding.sha256(output))
            self.assertFalse(metadata["native_model_exported"])
            with self.assertRaises(ValueError):
                folding.main(["--parameters", str(source), "--class-index", str(index), "--output", str(output)])


if __name__ == "__main__":
    unittest.main()
