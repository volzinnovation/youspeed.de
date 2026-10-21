import json
import math
from pathlib import Path
import tempfile
import unittest

import numpy as np
from PIL import Image

from project_panorama import (Camera, bilinear_sample, camera_for_box, checked_box,
                             create_projection, directions_to_panorama,
                             directions_to_viewport, panorama_directions,
                             project_box, render, sha256, viewport_to_panorama)


class ProjectionMathTests(unittest.TestCase):
    def test_panorama_cardinal_directions_and_poles(self):
        rays = panorama_directions(np.array([0, 90, 180, 270, 360, 180, 180]),
                                   np.array([90, 90, 90, 90, 90, 0, 180]), 360, 180)
        np.testing.assert_allclose(rays, [[0, 0, -1], [-1, 0, 0], [0, 0, 1],
                                        [1, 0, 0], [0, 0, -1], [0, 1, 0], [0, -1, 0]], atol=1e-15)

    def test_independent_pinhole_fov_boundaries(self):
        camera = Camera(400, 200, 90, 0, 0)
        vertical_limit = math.atan(0.5)
        rays = [[0, 0, 1], [1, 0, 1], [-1, 0, 1],
                [0, math.tan(vertical_limit), 1], [0, -math.tan(vertical_limit), 1]]
        xy, _ = directions_to_viewport(rays, camera)
        np.testing.assert_allclose(xy, [[200, 100], [400, 100], [0, 100], [200, 0], [200, 200]], atol=1e-12)
        self.assertAlmostEqual(camera.vertical_fov_degrees, 53.13010235415598)

    def test_yaw_and_pitch_change_forward_axis(self):
        camera = Camera(400, 200, 75, math.pi / 2, 0)
        xy, depth = directions_to_viewport([[1, 0, 0], [-1, 0, 0]], camera)
        np.testing.assert_allclose(xy[0], [200, 100])
        self.assertTrue(np.isnan(xy[1]).all())
        self.assertLess(depth[1], 0)
        tilted = Camera(400, 200, 75, 0, math.pi / 6)
        xy, _ = directions_to_viewport([[0, 0.5, math.sqrt(3) / 2]], tilted)
        np.testing.assert_allclose(xy[0], [200, 100], atol=1e-12)

    def test_roundtrip_asymmetric_viewport_across_panorama_seam(self):
        camera = Camera(1920, 1080, 75, math.radians(175), math.radians(-23))
        x = np.array([0.5, 250.5, 959.5, 1400.5, 1919.5])
        y = np.array([0.5, 900.5, 539.5, 120.5, 1079.5])
        uv = viewport_to_panorama(x, y, camera, 7680, 3840)
        xy, depth = directions_to_viewport(panorama_directions(uv[:, 0], uv[:, 1], 7680, 3840), camera)
        np.testing.assert_allclose(xy, np.column_stack((x, y)), atol=2e-12)
        self.assertTrue((depth > 0).all())

    def test_bilinear_known_pixel_centers_and_periodic_seam(self):
        source = np.array([[[0, 0, 0], [20, 0, 0], [40, 0, 0], [60, 0, 0]],
                           [[0, 100, 0], [20, 100, 0], [40, 100, 0], [60, 100, 0]]], dtype=np.uint8)
        uv = np.array([[0.5, 0.5], [1.0, 1.0], [0.0, 1.0], [4.0, 1.0], [2.5, 0.0], [2.5, 2.0]])
        np.testing.assert_allclose(bilinear_sample(source, uv),
                                   [[0, 0, 0], [10, 50, 0], [30, 50, 0], [30, 50, 0], [40, 0, 0], [40, 100, 0]])

    def test_render_optical_center_uses_source_pixel_centers(self):
        source = np.zeros((32, 64, 3), dtype=np.uint8)
        source[..., 0] = np.arange(64)[None, :] * 4
        source[..., 1] = np.arange(32)[:, None] * 8
        source[..., 2] = 127
        camera = Camera(41, 41, 90, 0, 0)
        result = render(source, camera, block_rows=7)
        np.testing.assert_array_equal(result[20, 20], [126, 124, 127])
        self.assertTrue((result[..., 2] == 127).all())
        np.testing.assert_array_equal(result, render(source, camera, block_rows=1))

    def test_box_envelope_matches_analytic_spherical_rectangle(self):
        camera = Camera(400, 200, 90, 0, 0)
        result = project_box([150, 80, 210, 100], 360, 180, camera)
        dx = 200 * math.tan(math.radians(30))
        dy = 200 * math.tan(math.radians(10)) / math.cos(math.radians(30))
        np.testing.assert_allclose(result["bbox_xyxy_float"], [200-dx, 100-dy, 200+dx, 100+dy], atol=1e-12)
        self.assertFalse(result["target_clipped_by_viewport"])
        self.assertEqual(result["boundary_samples"], 4100)

    def test_seam_box_looks_backward_instead_of_toward_wrong_midpoint(self):
        camera = camera_for_box([350, 80, 10, 100], 360, 180, width=400, height=200, hfov=90)
        np.testing.assert_allclose(camera.basis()[:, 2], [0, 0, -1], atol=1e-15)
        result = project_box([350, 80, 10, 100], 360, 180, camera)
        self.assertTrue(result["source_seam_crossing"])
        self.assertFalse(result["has_boundary_at_or_behind_camera"])
        self.assertAlmostEqual((result["bbox_xyxy_float"][0]+result["bbox_xyxy_float"][2])/2, 200)

    def test_behind_camera_never_becomes_valid_front_box(self):
        result = project_box([0, 80, 20, 100], 360, 180, Camera(400, 200, 90, 0, 0))
        self.assertTrue(result["has_boundary_at_or_behind_camera"])
        self.assertIsNone(result["bbox_xyxy_pixels"])

    def test_target_clipping_is_marked(self):
        camera = Camera(400, 200, 60, 0, 0)
        result = project_box([140, 80, 220, 100], 360, 180, camera)
        self.assertTrue(result["target_clipped_by_viewport"])
        self.assertEqual(result["bbox_xyxy_pixels"][0], 0)
        self.assertEqual(result["bbox_xyxy_pixels"][2], 400)
        self.assertEqual(result["status"], "clipped_requires_review")

    def test_invalid_geometry_is_rejected(self):
        for box in [[1, 5, 1, 10], [1, 10, 20, 5], [-1, 1, 2, 5], [1, 1, 361, 5], [1, 1, float('nan'), 5]]:
            with self.assertRaises(ValueError): checked_box(box, 360, 180)
        with self.assertRaises(ValueError): Camera(100, 100, 180, 0, 0)


class ProjectionProvenanceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.image = self.root / "source.png"
        Image.new("RGB", (64, 32), (20, 80, 140)).save(self.image)
        self.box = [29, 14, 35, 18]
        self.item = {"id": "fixture-picture", "collection": "fixture-sequence",
                     "links": [{"rel": "self", "href": "https://example.invalid/source"}],
                     "assets": {"hd": {"href": "https://example.invalid/hd.jpg"}},
                     "properties": {"license": "CC-BY-SA-4.0", "geovisio:producer": "fixture",
                                    "pers:interior_orientation": {"field_of_view": 360, "sensor_array_dimensions": [64, 32]},
                                    "annotations": [{"id": "actual-source-id", "shape": {"type": "Polygon", "coordinates": [[[29,14],[35,14],[35,18],[29,18],[29,14]]]}}]}}
        self.item_path = self.root / "original-item.json"
        self.item_path.write_text(json.dumps(self.item))

    def test_real_outputs_preserve_sources_and_never_claim_approval(self):
        original_item = self.item_path.read_bytes()
        original_image_sha = sha256(self.image)
        output = self.root / "projection"
        projection, proposal = create_projection(self.image, self.item_path, self.box, output,
            source_annotation_id="actual-source-id", class_proposal="DE:310",
            expected_image_sha256=original_image_sha, expected_item_sha256=sha256(self.item_path),
            width=80, height=45)
        self.assertEqual(self.item_path.read_bytes(), original_item)
        self.assertEqual((output / "source-item.json").read_bytes(), original_item)
        self.assertEqual(sha256(self.image), original_image_sha)
        self.assertEqual(proposal["source_annotation_id"], "actual-source-id")
        self.assertTrue(proposal["proposal_id"].startswith("local-perspective-target-"))
        for record in [proposal, projection]:
            for key in ["human_approved", "eligible_for_training", "approved_for_evaluation", "all_visible_object_annotation_complete"]:
                self.assertIs(record[key], False)
        self.assertEqual(proposal["class_proposal"]["model_label"], "city:start")
        with Image.open(output / "perspective.png") as image: self.assertEqual(image.size, (80,45))
        with Image.open(output / proposal["crop_file"]) as image:
            x0,y0,x1,y1 = proposal["bbox_xyxy"]
            self.assertEqual(image.size, (x1-x0,y1-y0))
        self.assertEqual(sha256(output / "projection.json"), proposal["projection_sha256"])

    def test_manual_source_box_has_no_fabricated_original_id(self):
        _, proposal = create_projection(self.image, self.item_path, self.box, self.root / "manual", width=40,height=24)
        self.assertIsNone(proposal["source_annotation_id"])
        self.assertEqual(proposal["annotation_source"], "local_visual_box_proposal_projected")

    def test_unknown_or_changed_original_annotation_fails(self):
        for ann,box in [("fake-id",self.box),("actual-source-id",[28,14,35,18])]:
            with self.assertRaises(ValueError):
                create_projection(self.image,self.item_path,box,self.root/"bad",source_annotation_id=ann,width=40,height=24)
        self.assertFalse((self.root/"bad").exists())

    def test_hash_and_existing_output_fail_before_writing(self):
        with self.assertRaises(ValueError):
            create_projection(self.image,self.item_path,self.box,self.root/"bad",expected_image_sha256="0"*64)
        output=self.root/"existing";output.mkdir()
        with self.assertRaises(ValueError):create_projection(self.image,self.item_path,self.box,output)
        self.assertEqual(list(output.iterdir()),[])

    def test_exif_rotation_and_non_2_to_1_raster_fail(self):
        exif=Image.Exif();exif[274]=6
        Image.new("RGB",(64,32)).save(self.image,exif=exif)
        with self.assertRaisesRegex(ValueError,"EXIF"):
            create_projection(self.image,self.item_path,self.box,self.root/"rotated",width=40,height=24)
        Image.new("RGB",(65,32)).save(self.image)
        with self.assertRaises(ValueError):
            create_projection(self.image,self.item_path,self.box,self.root/"shape",width=40,height=24)


if __name__ == "__main__":
    unittest.main()
