from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/research"))
import profile_panoramax_route_signs as audit
import reverse_panoramax_route_comparison as reverse


def fix(index, lon, at):
    return dict(index=index, lat=48, lon=lon, timestamp=at, part=0, accuracy=2,
                heading=90, heading_accuracy=5, way_id="1", direction=1)


def sign(code="DE:274-50", identifier="s"):
    return dict(sign_id=identifier, lat=48, lon=8.0003, normalized_code=code, sign_code=code,
                kind="speed_limit" if code.startswith("DE:274-") else "secondary", numeric_value=50,
                association_status="accepted", associated_travel_heading=90, source_id="test",
                within_sampled_fix_geofence=True)


def photo(code="DE:274-50", azimuth=90):
    return dict(id="photo", collection="collection", geometry=dict(type="Point", coordinates=[8.0001, 48]),
                properties={"view:azimuth": azimuth, "annotations": [dict(id="annotation", semantics=[dict(key="osm|traffic_sign", value=code)])]},
                links=[dict(rel="self", href="https://example.test/api/photo")])


class PanoramaxRouteResearchTests(unittest.TestCase):
    def compare(self, photographs, signs):
        return audit.compare(photographs, dict(signs=signs), [fix(0, 8, 0), fix(1, 8.001, 5)], dict(selected_sign_ids=[]))

    def test_same_numeric_value_and_unique_direction_are_compatible(self):
        result = self.compare([photo()], [sign()])
        self.assertEqual(result["summary"]["distinct_inventory_ids_unique_direction_verified_exact"], 1)
        pair = result["match_pairs"][0]
        self.assertGreater(pair["along_route_offset_m"], 0)
        self.assertLess(pair["field_of_view_error_deg"], 1)

    def test_opposite_camera_direction_is_excluded(self):
        result = self.compare([photo(azimuth=270)], [sign()])
        self.assertEqual(result["summary"]["photo_direction_filters"], {"different_travel_direction": 1})
        self.assertFalse(result["observations"])

    def test_opposite_source_direction_cannot_be_a_target(self):
        target = sign()
        target["associated_travel_heading"] = 270
        result = self.compare([photo()], [target])
        self.assertEqual(result["observations"][0]["status"], "no_inventory_candidate_in_camera_cone")

    def test_different_numeric_value_is_not_a_family_match(self):
        result = self.compare([photo("DE:274-70")], [sign()])
        self.assertEqual(result["observations"][0]["status"], "unique_numeric_value_conflict_candidate")
        self.assertEqual(result["summary"]["distinct_inventory_ids_exact_code_compatible"], 0)
        self.assertEqual(result["summary"]["distinct_inventory_ids_family_only"], 0)
        self.assertIsNone(result["summary"]["confirmed_physical_mismatches"])

    def test_matching_label_does_not_establish_unique_identity_between_two_targets(self):
        result = self.compare([photo()], [sign(identifier="a"), sign(identifier="b")])
        self.assertEqual(result["summary"]["distinct_inventory_ids_exact_code_compatible"], 2)
        self.assertEqual(result["summary"]["distinct_inventory_ids_unique_direction_verified_exact"], 0)

    def test_crosswalk_variant_is_separate_from_exact(self):
        result = self.compare([photo("DE:350")], [sign("DE:350-10")])
        self.assertEqual(result["observations"][0]["status"], "family_class_consistent_variant_unresolved")
        self.assertEqual(result["summary"]["distinct_inventory_ids_exact_code_compatible"], 0)
        self.assertEqual(result["summary"]["distinct_inventory_ids_family_only"], 1)

    def test_unknown_annotation_does_not_become_mismatch(self):
        result = self.compare([photo("yes")], [sign()])
        self.assertEqual(result["observations"][0]["status"], "unknown_or_unparameterized_annotation")
        self.assertFalse(result["match_pairs"])

    def test_reverse_type_absence_and_cone_absence_are_exclusive(self):
        absent = {"canonical_code": "DE:283", "status": "no_inventory_candidate_in_camera_cone"}
        present = {"canonical_code": "DE:205", "status": "no_inventory_candidate_in_camera_cone"}
        self.assertEqual(reverse.category(absent, {"DE:205"}), "no_corresponding_type_in_dataset")
        self.assertEqual(reverse.category(present, {"DE:205"}), "type_present_no_spatial_counterpart_or_ambiguous")

    def test_reverse_unknown_and_numeric_conflicts_do_not_become_matches(self):
        unknown = {"canonical_code": None, "status": "unknown_or_unparameterized_annotation"}
        wrong_number = {"canonical_code": "DE:274-70", "status": "unique_numeric_value_conflict_candidate"}
        self.assertEqual(reverse.category(unknown, set()), "unknown_label")
        self.assertEqual(reverse.category(wrong_number, {"DE:274"}), "possible_wrong_number")

    def test_reverse_variant_uses_family_presence_not_literal_code_equality(self):
        crosswalk = {"canonical_code": "DE:350", "status": "family_class_consistent_variant_unresolved"}
        self.assertEqual(reverse.category(crosswalk, {"DE:350"}), "same_kind_variant_unclear")


if __name__ == "__main__":
    unittest.main()
