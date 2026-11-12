import copy
import unittest

from scripts.inspector.apply_sign_review_decisions import apply_decisions


def fixture():
    groups = [{"id": key, "sign_code": "DE:205", "observations": [{"image_id": "image-" + key,
               "annotation_id": "annotation-" + key, "box_xyxy": [10, 20, 40, 60]}],
               "proposal": {"longitude": 8.0 + index, "latitude": 48.0}}
              for index, key in enumerate(("a", "b"))]
    reviews = [{"group_id": group["id"], "reviewed_class": "DE:205",
                "current_annotation_ids": [group["observations"][0]["annotation_id"]],
                "current_evidence": [{**copy.deepcopy(group["observations"][0]), "source_sign_code": "DE:205"}]}
               for group in groups]
    return {"groups": groups, "default_group_id": "b", "summary": {}}, {
        "reviews": reviews, "aliases": {"b": "a"}, "pose_sources": {"a": "b"}}


class ReviewBindingTests(unittest.TestCase):
    def test_identity_review_uses_only_current_source_pose_and_preserves_inputs(self):
        source, decisions = fixture()
        before = copy.deepcopy(source)
        result, report = apply_decisions(source, decisions)
        self.assertEqual(source, before)
        self.assertEqual(result["default_group_id"], "a")
        self.assertEqual(result["groups"][0]["proposal"], source["groups"][1]["proposal"])
        self.assertEqual(len(result["groups"][0]["observations"]), 2)
        self.assertEqual(report["merged_alias_count"], 1)
        self.assertFalse(report["spatial_ground_truth_established"])

    def test_changed_class_box_or_membership_requires_new_review(self):
        for kind in ("class", "box", "membership"):
            with self.subTest(kind=kind):
                source, decisions = fixture()
                if kind == "class":
                    source["groups"][0]["sign_code"] = "DE:206"
                elif kind == "box":
                    source["groups"][0]["observations"][0]["box_xyxy"][0] = 9
                else:
                    source["groups"][0]["observations"].append({"annotation_id": "new", "image_id": "new"})
                with self.assertRaises(ValueError):
                    apply_decisions(source, decisions)

    def test_withheld_or_mixed_positions_never_reappear_from_selected_source(self):
        for key, value in (("withheld_positions", {"a": "Conflicting source hypothesis"}),
                           ("excluded_identity_group_ids", ["a"])):
            source, decisions = fixture()
            decisions[key] = value
            source["groups"][1]["mobile_refinement"] = {"status": "refined", "proposal": {"latitude": 48, "longitude": 8}}
            result, _ = apply_decisions(source, decisions)
            self.assertIsNone(result["groups"][0]["proposal"])
            self.assertNotIn("mobile_refinement", result["groups"][0])


if __name__ == "__main__":
    unittest.main()
