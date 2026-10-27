"""Native contract regression tests; compile actual app cores when host tools exist."""
import copy
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/lanes"))
import compare_semantic_hint_platforms as parity
import compare_semantic_selector_platforms as selector


class SemanticNativeVectorTests(unittest.TestCase):
    def test_all_shared_cases_reach_actual_native_input(self):
        original = json.loads((parity.CONTRACT / "synthetic-cases.json").read_text())
        vectors = parity.default_vectors()
        names = [case["id"] for case in vectors["qualificationCases"]]
        self.assertEqual(len(names), len(set(names)))
        self.assertTrue({case["id"] for case in original["cases"]}.issubset(names))
        self.assertEqual(len(original["cases"]), 32)

    def test_expansion_copies_and_preserves_original_fixture(self):
        original = json.loads((parity.CONTRACT / "synthetic-cases.json").read_text())
        before = copy.deepcopy(original)
        value = parity.expand(original, {"frameOffset": 1, "generationOffset": 1})
        self.assertEqual(original, before)
        self.assertEqual(value["context"]["exposure"], value["hint"]["exposure"])
        self.assertEqual(value["hint"]["exposure"]["sourceTimeNs"], 1_100_000_000)
        self.assertEqual(value["context"]["scope"]["sessionGeneration"], 2)

    def test_expected_cases_are_checked_against_reference(self):
        vectors = parity.default_vectors()
        result = parity.reference_output(vectors)
        result["clockCases"] = []
        without_clocks = dict(vectors, clockCases=[])
        parity.check_expected(without_clocks, result)
        result["qualificationCases"][0]["reason"] = "incorrect"
        with self.assertRaises(AssertionError):
            parity.check_expected(without_clocks, result)

    def test_nonfinite_injection_does_not_corrupt_serializable_fixture(self):
        vectors = parity.default_vectors()
        case = next(case for case in vectors["qualificationCases"] if case["id"] == "nan-score")
        before = copy.deepcopy(case)
        parity.nonfinite(case)
        self.assertEqual(case, before)
        json.dumps(vectors, allow_nan=False)

    def test_exact_comparison_does_not_confuse_boolean_and_integer(self):
        with self.assertRaises(AssertionError):
            parity.compare({"valid": True}, {"valid": 1})


@unittest.skipUnless(all(shutil.which(name) for name in ("swiftc", "kotlinc", "java")), "Native Swift/Kotlin host tools unavailable")
class SemanticNativeExecutionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        try:
            cls.classpath = parity.kotlin_classpath()
        except ValueError as error:
            raise unittest.SkipTest(str(error))

    def test_actual_qualifiers_cache_clocks_and_decimal_mask_regression(self):
        with tempfile.TemporaryDirectory(prefix="semantic-native-test-") as directory:
            report = parity.run(parity.default_vectors(), Path(directory) / "qualifier", self.classpath)
        self.assertEqual(report["qualifierCases"], 61)
        self.assertEqual(report["cacheOperations"], 48)
        self.assertEqual(report["clockCases"], 13)
        self.assertTrue(report["allBaselineObjectsPreserved"])
        self.assertTrue(report["exactNativeAndPythonMaskParity"])

    def test_actual_typed_buffers_metadata_and_immutable_cache(self):
        with tempfile.TemporaryDirectory(prefix="semantic-typed-test-") as directory:
            report = parity.run(parity.typed_vectors(), Path(directory) / "typed", self.classpath, typed=True)
        self.assertEqual(report["qualifierCases"], 62)
        self.assertEqual(report["cacheOperations"], 52)
        self.assertTrue(report["allBaselineObjectsPreserved"])
        self.assertTrue(report["exactNativeAndPythonMaskParity"])

    def test_actual_selectors_preserve_gates_and_temporal_dwell(self):
        with tempfile.TemporaryDirectory(prefix="semantic-selector-test-") as directory:
            report = selector.run(Path(directory) / "selector", self.classpath)
        self.assertEqual(report["scenarios"], 16)
        self.assertTrue(report["malformedInputMatchesBaseline"])
        self.assertTrue(report["challengerMarginAndDwellPreserved"])


if __name__ == "__main__":
    unittest.main()
