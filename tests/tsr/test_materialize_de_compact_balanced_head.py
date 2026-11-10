import importlib.util
from pathlib import Path
import unittest

import numpy as np

SPEC = importlib.util.spec_from_file_location("materialize_de_compact_balanced_head",
    Path(__file__).resolve().parents[2] / "scripts/tsr/materialize_de_compact_balanced_head.py")
candidate = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(candidate)


class CompactHeadTests(unittest.TestCase):
    def test_fold_matches_explicit_temperature_and_prior_offset(self):
        rng = np.random.default_rng(18)
        weight, bias, features = rng.normal(size=(136, 8)), rng.normal(size=136), rng.normal(size=(30, 8))
        train = np.arange(1, 137, dtype=float); train /= train.sum()
        target = np.full(136, 1 / 136)
        w, b, offset = candidate.fold_prior_head(weight, bias, train, target, candidate.SELECTION)
        # Some local BLAS builds leave stale floating-point exception flags;
        # check actual arrays explicitly before numerical comparison.
        with np.errstate(all="ignore"):
            expected = (features @ weight.T + bias) / 1.5 + .1 * (np.log(target) - np.log(train))
            actual = features @ w.T + b
        self.assertTrue(np.isfinite(expected).all() and np.isfinite(actual).all())
        np.testing.assert_allclose(actual, expected, rtol=2e-5, atol=1e-6)
        np.testing.assert_allclose(offset, .1 * (np.log(target) - np.log(train)), atol=1e-15)
        self.assertEqual(w.dtype, np.float32)

    def test_gate_or_observed_source_cannot_be_folded_silently(self):
        for field, value in (("confidence_gate", .95), ("source", "ios"), ("alpha", .25), ("temperature", 2.)):
            with self.assertRaisesRegex(ValueError, "exact frozen"):
                candidate.fold_prior_head(np.zeros((136, 4)), np.zeros(136), np.full(136,1/136),
                    np.full(136,1/136), {**candidate.SELECTION, field:value})

    def test_nonfinite_missing_classes_and_invalid_prior_rejected(self):
        for train in (np.zeros(136), np.full(136,np.nan), np.ones(136), np.full(135,1/135)):
            with self.assertRaises(ValueError):
                candidate.fold_prior_head(np.zeros((136, 4)),np.zeros(136),train,np.full(136,1/136),candidate.SELECTION)
        target=np.arange(1,137,dtype=float); target/=target.sum()
        with self.assertRaises(ValueError):
            candidate.fold_prior_head(np.zeros((136,4)),np.zeros(136),np.full(136,1/136),target,candidate.SELECTION)


if __name__ == "__main__":
    unittest.main()
