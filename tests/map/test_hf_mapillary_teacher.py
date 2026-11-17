import importlib.util
import gzip
import json
from pathlib import Path
import tempfile
import unittest

MODULE = Path(__file__).resolve().parents[2] / "scripts/research/audit_hf_mapillary_teacher.py"
spec = importlib.util.spec_from_file_location("hf_mapillary_teacher", MODULE)
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


def feature(identifier, lon, lat):
    return {"type": "Feature", "id": identifier, "geometry": {"type": "Point", "coordinates": [lon, lat]},
            "properties": {"value": "MUST_NOT_APPEAR_IN_OUTPUT"}}


class TeacherGeometryTests(unittest.TestCase):
    def pose(self, **changes):
        return dict(coordinates=[0, 0], heading_proxy_deg=359, declared_fov_deg=60,
                    cone_eligible=True) | changes

    def test_wraparound_bearing_and_behind_rejection(self):
        index = audit.PointIndex([feature("ahead", .00002, .001), feature("behind", 0, -.001)], 150)
        candidates, nearby, rejected = audit.image_candidates(self.pose(), index, 15)
        self.assertEqual((nearby, rejected), (2, 1))
        self.assertEqual([c["mapillary_id"] for c in candidates], ["ahead"])
        self.assertLess(candidates[0]["heading_difference_deg"], 3)
        self.assertNotIn("MUST_NOT_APPEAR", json.dumps(candidates))

    def test_zero_distance_kept_unresolved_not_invented_north(self):
        index = audit.PointIndex([feature("same", 0, 0)], 150)
        candidates, _, _ = audit.image_candidates(self.pose(heading_proxy_deg=180), index, 15)
        self.assertIsNone(candidates[0]["bearing_deg"])
        self.assertEqual(candidates[0]["status"], "ungated_coincident_coordinates_bearing_undefined")

    def test_unqualified_pose_keeps_behind_point_and_missing_gps_is_empty(self):
        index = audit.PointIndex([feature("behind", 0, -.001)], 150)
        candidates, _, rejected = audit.image_candidates(self.pose(cone_eligible=False), index, 15)
        self.assertEqual(rejected, 0)
        self.assertEqual(candidates[0]["status"], "ungated_camera_pose_unqualified")
        self.assertEqual(audit.image_candidates(self.pose(coordinates=None), index, 15), ([], 0, 0))

    def test_grid_handles_date_line(self):
        index = audit.PointIndex([feature("other_side", -179.9998, 0)], 150)
        nearby = index.nearby([179.9998, 0])
        self.assertEqual(len(nearby), 1)
        self.assertAlmostEqual(nearby[0]["range_m"], 44.478, places=2)

    def test_forward_course_is_hypothesis_and_180_raster_keeps_center_cone(self):
        row = {"dimensions": [4000, 3000]}
        picture = {"geometry": {"type": "Point", "coordinates": [8, 48]},
                   "heading": 359, "heading_computed": False, "gps_accuracy_m": 5,
                   "metadata": {"type": "flat", "width": 4000, "height": 3000,
                                "make": "Apple", "model": "iPhone 14 Pro", "field_of_view": 72,
                                "ts_camera": "2026-11-14T12:00:00.4Z", "ts_gps": "2026-11-14T12:00:00Z"},
                   "exif": {"Exif.Image.Orientation": "3", "Exif.GPSInfo.GPSImgDirection": "359/1",
                            "Exif.GPSInfo.GPSImgDirectionRef": "T"}}
        annotation = {"dimensions": [4000, 3000], "source_metadata": {"picture": picture}}
        pose = audit.camera_pose(row, annotation)
        self.assertTrue(pose["cone_eligible"])
        self.assertFalse(pose["optical_yaw_measured"])
        picture["heading_computed"] = True
        self.assertFalse(audit.camera_pose(row, annotation)["cone_eligible"])

    def test_iso_short_fractional_seconds_supported_on_python_310(self):
        self.assertEqual(audit.timestamp("2026-10-14T14:16:18.49Z"),
                         audit.timestamp("2026-10-14T16:16:18.490000+02:00"))
        self.assertIsNone(audit.timestamp("2026-10-14T14:16:18"))

    def test_every_tree_image_emitted_even_without_metadata_or_pose(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            image = "data/2026-11/detector/aa/frame.jpg"
            (root / "tree.json").write_text(json.dumps({"revision": "frozen", "files": [
                {"path": image, "type": "RepoFile"}]}))
            (root / "metadata.jsonl").write_text("")
            (root / "plan.jsonl").write_text("")
            (root / "map.json").write_text(json.dumps({"type": "FeatureCollection", "features": []}))
            result = audit.audit(root / "tree.json", root / "metadata.jsonl", root / "plan.jsonl",
                                 root / "map.json", root / "out")
            self.assertEqual(result["counts"]["images"], 1)
            with gzip.open(root / "out/image-candidates.jsonl.gz", "rt") as stream:
                record = json.loads(stream.read())
            self.assertFalse(record["metadata_present"])
            self.assertEqual(record["candidates"], [])
            self.assertFalse(record["visibility_established"])
            self.assertEqual(record["visual_review_status"], "not_performed_by_this_script")

    def test_streaming_feature_collection_preserves_features_and_rejects_truncation(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "map.json.gz"
            features = [feature("a", 8, 48), feature("b", 8.001, 48)]
            payload = json.dumps({"type": "FeatureCollection", "description": "x" * 70000,
                                  "features": features, "tail": True})
            with gzip.open(path, "wt") as stream:
                stream.write(payload)
            self.assertEqual(list(audit.geojson_features(path)), features)
            with gzip.open(path, "wt") as stream:
                stream.write(payload[:-20])
            with self.assertRaises(ValueError):
                list(audit.geojson_features(path))


if __name__ == "__main__":
    unittest.main()
