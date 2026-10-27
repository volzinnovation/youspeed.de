import copy
from dataclasses import FrozenInstanceError
import importlib.util
import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("qualify_semantic_hints", ROOT / "scripts/lanes/qualify_semantic_hints.py")
m = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m
SPEC.loader.exec_module(m)
FIXTURES = json.loads((ROOT / "shared/lanes/semantic-hint-v1/synthetic-cases.json").read_text())


def mutate(value, operations):
    for operation in operations:
        target = value
        for key in operation["path"][:-1]:
            target = target[key]
        key = operation["path"][-1]
        if operation.get("remove"):
            del target[key]
        else:
            target[key] = operation["value"]


class SemanticHintQualificationTests(unittest.TestCase):
    def setUp(self):
        self.context = copy.deepcopy(FIXTURES["context"])
        self.hint = copy.deepcopy(FIXTURES["hint"])
        self.policy = m.QualificationPolicy.from_mapping(FIXTURES["policy"])

    def next_frame(self):
        context, hint = copy.deepcopy(self.context), copy.deepcopy(self.hint)
        for exposure in (context["exposure"], hint["exposure"]):
            exposure["frameId"] = "frame-11"
            exposure["sourceTimeNs"] += 100_000_000
            exposure["capturedAtNs"] += 100_000_000
        context["now"]["atNs"] += 100_000_000
        hint["arrival"]["atNs"] += 100_000_000
        return context, hint

    def test_shared_fault_fixtures(self):
        names = set()
        for case in FIXTURES["cases"]:
            with self.subTest(case=case["id"]):
                self.assertNotIn(case["id"], names)
                names.add(case["id"])
                hint = None if case.get("missingHint") else copy.deepcopy(self.hint)
                context = copy.deepcopy(self.context)
                if hint is not None:
                    mutate(hint, case.get("hintMutations", []))
                mutate(context, case.get("contextMutations", []))
                result = m.qualify(hint, context, self.policy)
                self.assertEqual(result.reason, case["expectedReason"])
                self.assertEqual(result.accepted, case["expectedReason"] == "qualified")
                if not result.accepted:
                    self.assertIsNone(result.hint)

    def test_nonfinite_extreme_and_boolean_scores_fail_closed_even_in_invalid_cells(self):
        for value in (float("nan"), float("inf"), -float("inf"), 10**1000, True, "0.5", None):
            with self.subTest(value=repr(value)[:30]):
                self.hint["mask"]["probabilities"][0] = value
                self.hint["mask"]["validity"][0] = False
                self.assertEqual(m.qualify(self.hint, self.context, self.policy).reason, "invalid_scores")

    def test_qualified_evidence_is_detached_and_immutable(self):
        result = m.qualify(self.hint, self.context, self.policy)
        expected = result.hint.probabilities
        self.hint["mask"]["probabilities"][0] = 0.99
        self.hint["scope"]["sessionId"] = "changed"
        self.assertEqual(result.hint.probabilities, expected)
        self.assertIn("synthetic-session", result.hint.scope_identity)
        with self.assertRaises(FrozenInstanceError):
            result.hint.frame_id = "changed"
        self.assertEqual(result.hint.validity, (True, True, False, True))

    def test_missing_invalid_and_valid_hint_never_mutate_baseline(self):
        baseline = {"rawConfidence": 0.6, "supportRows": 5, "confirmations": 2,
                    "observedSegments": [[[0.2, 0.6], [0.3, 0.8]]], "trackId": 17}
        before = json.dumps(baseline, sort_keys=True)
        invalid = copy.deepcopy(self.hint)
        invalid["scope"]["cameraGeneration"] += 1
        for hint in (None, invalid, self.hint):
            result = m.prepare_guidance(baseline, hint, self.context, self.policy)
            self.assertIs(result.baseline, baseline)
            self.assertEqual(json.dumps(baseline, sort_keys=True), before)
        # This verifies only the pure adapter, not mobile-pipeline parity.

    def test_mask_and_policy_bounds_reject_before_large_allocation(self):
        self.hint["mask"]["width"] = 10**100
        self.assertEqual(m.qualify(self.hint, self.context, self.policy).reason, "shape_mismatch")
        for field, value in (("maskWidth", 513), ("maskHeight", True), ("maxCaptureAgeNs", 0)):
            policy = copy.deepcopy(FIXTURES["policy"])
            policy[field] = value
            with self.assertRaises(ValueError):
                m.QualificationPolicy.from_mapping(policy)
        with self.assertRaises(FrozenInstanceError):
            self.policy.max_capture_age_ns = 100

    def test_exact_maximum_age_is_accepted_then_expires(self):
        self.context["now"]["atNs"] = self.context["exposure"]["capturedAtNs"] + self.policy.max_capture_age_ns
        self.assertTrue(m.qualify(self.hint, self.context, self.policy).accepted)
        self.context["now"]["atNs"] += 1
        self.assertEqual(m.qualify(self.hint, self.context, self.policy).reason, "stale_hint")

    def test_clock_domains_can_differ_for_source_and_capture_but_must_match_context(self):
        self.context["exposure"]["sourceTimeNs"] = self.hint["exposure"]["sourceTimeNs"] = 80_000_000_000
        self.assertTrue(m.qualify(self.hint, self.context, self.policy).accepted)
        self.hint["exposure"]["sourceClockId"] = "unknown-origin"
        self.assertEqual(m.qualify(self.hint, self.context, self.policy).reason, "clock_mismatch")

    def test_cache_rejects_duplicate_without_overwriting_valid_evidence(self):
        cache = m.HintCache(self.policy, self.context)
        first = cache.offer(self.hint)
        self.assertTrue(first.accepted)
        duplicate = copy.deepcopy(self.hint)
        duplicate["mask"]["probabilities"] = [0.9] * 4
        self.assertEqual(cache.offer(duplicate).reason, "duplicate_exposure")
        self.assertEqual(cache.current().hint, first.hint)

    def test_out_of_order_arrival_cannot_replace_newer_source(self):
        cache = m.HintCache(self.policy, self.context)
        self.assertTrue(cache.offer(self.hint).accepted)
        next_context, next_hint = self.next_frame()
        self.assertEqual(cache.advance(next_context), "advanced")
        self.assertEqual(cache.current().reason, "exposure_mismatch")
        current = cache.offer(next_hint)
        self.assertTrue(current.accepted)
        late = copy.deepcopy(self.hint)
        late["arrival"]["atNs"] = next_context["now"]["atNs"]
        self.assertEqual(cache.offer(late).reason, "exposure_mismatch")
        self.assertEqual(cache.current().hint, current.hint)
        self.assertEqual(cache.latest_source_time_ns, next_hint["exposure"]["sourceTimeNs"])

    def test_cache_cannot_advance_to_older_exposure_even_with_newer_arrival_clock(self):
        cache = m.HintCache(self.policy, self.context)
        next_context, next_hint = self.next_frame()
        cache.advance(next_context)
        accepted = cache.offer(next_hint)
        self.context["now"]["atNs"] = next_context["now"]["atNs"] + 1
        self.assertEqual(cache.advance(self.context), "context_exposure_regression")
        self.assertEqual(cache.current().hint, accepted.hint)

    def test_old_scope_never_resets_cache_and_explicit_owner_reset_invalidates_it(self):
        cache = m.HintCache(self.policy, self.context)
        cache.offer(self.hint)
        new_context, new_hint = self.next_frame()
        for scope in (new_context["scope"], new_hint["scope"]):
            scope["sessionGeneration"] += 1
        self.assertEqual(cache.advance(new_context), "context_scope_mismatch")
        cache.reset_scope(new_context)
        self.assertIsNone(cache.latest_source_time_ns)
        self.assertEqual(cache.current().reason, "missing_hint")
        result = cache.offer(new_hint)
        self.assertTrue(result.accepted)
        self.assertEqual(cache.offer(self.hint).reason, "scope_mismatch")
        self.assertEqual(cache.current().hint, result.hint)

    def test_invalid_new_result_does_not_evict_valid_cached_result(self):
        cache = m.HintCache(self.policy, self.context)
        first = cache.offer(self.hint)
        self.hint["mask"]["probabilities"][0] = float("nan")
        self.assertEqual(cache.offer(self.hint).reason, "invalid_scores")
        self.assertEqual(cache.current().hint, first.hint)

    def test_cache_revalidates_capture_age_without_changing_source_timestamp(self):
        cache = m.HintCache(self.policy, self.context)
        cache.offer(self.hint)
        self.context["now"]["atNs"] += self.policy.max_capture_age_ns
        self.assertEqual(cache.advance(self.context), "advanced")
        self.assertEqual(cache.current().reason, "stale_hint")
        self.assertEqual(cache.latest_source_time_ns, self.hint["exposure"]["sourceTimeNs"])

    def test_cache_context_is_detached_and_rejects_clock_and_identity_conflicts(self):
        cache = m.HintCache(self.policy, self.context)
        self.context["scope"]["sessionId"] = "mutated-caller"
        self.assertTrue(cache.offer(self.hint).accepted)
        for change, reason in (({"now": {"atNs": 10_090_000_000}}, "context_clock_regression"),
                               ({"exposure": {"frameId": "different"}}, "context_exposure_conflict")):
            context = copy.deepcopy(FIXTURES["context"])
            for section, updates in change.items():
                context[section].update(updates)
            self.assertEqual(cache.advance(context), reason)
        bad = copy.deepcopy(FIXTURES["context"])
        bad["now"]["clockKnown"] = False
        with self.assertRaisesRegex(ValueError, "unknown_clock"):
            cache.reset_scope(bad)
        self.assertTrue(cache.current().accepted)

    def test_json_schemas_and_fixture_examples(self):
        try:
            import jsonschema
        except ImportError:
            self.skipTest("Optional jsonschema dependency unavailable; semantic fixtures still tested")
        schema = json.loads((ROOT / "shared/lanes/semantic-hint-v1/contract.schema.json").read_text())
        jsonschema.Draft202012Validator.check_schema(schema)
        for name in ("hint", "context", "policy"):
            document_schema = {"$schema": schema["$schema"], "$defs": schema["$defs"], "$ref": f"#/$defs/{name}"}
            jsonschema.validate(FIXTURES[name], document_schema)


if __name__ == "__main__":
    unittest.main()
