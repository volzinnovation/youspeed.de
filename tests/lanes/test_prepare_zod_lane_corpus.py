import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

SPEC = importlib.util.spec_from_file_location("zod_adapter", Path(__file__).parents[2] / "scripts/lanes/prepare_zod_lane_corpus.py")
zod = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(zod)


def feature(identity, x1, y1, x2, y2, category="lm_dashed", **properties):
    props = {"annotation_uuid": identity, "InstanceID": 1, **properties}
    if category is not None:
        props["class"] = category
    return {"geometry": {"type": "Polygon", "coordinates": [[[x1, y1], [x2, y1], [x2, y2], [x1, y2]]]}, "properties": props}


def record(identity, latitude, split="train", date="2020-01-01", car="car1"):
    return {"frame_id": identity, "latitude": latitude, "longitude": 10., "capture_date": date,
            "collection_car": car, "official_split": split}


class RasterizationTest(unittest.TestCase):
    def test_same_instance_dash_gaps_are_background(self):
        polygons = [feature("first", 2, 2, 4, 4), feature("second", 2, 8, 4, 10)]
        positive, valid, stats = zod.rasterize_annotations(polygons, 12, 12, True)
        self.assertEqual(int(positive[3, 3]), 255)
        self.assertEqual(int(positive[9, 3]), 255)
        self.assertEqual(int(positive[6, 3]), 0)
        self.assertEqual(int(valid[6, 3]), 255)
        self.assertEqual(stats["annotation_counts"], {"lm_dashed": 2})

    def test_other_paint_uncertainty_and_overlap_ignore_wins(self):
        annotations = [feature("positive", 1, 1, 8, 8, "lm_solid"),
                       feature("arrow", 3, 3, 4, 4, None, ContainsArrow=True),
                       feature("unclear", 6, 6, 10, 10, Unclear=True),
                       feature("raised", 0, 0, 2, 2, "lm_botts_dot")]
        positive, valid, _ = zod.rasterize_annotations(annotations, 12, 12, True)
        for y, x in ((3, 3), (7, 7), (1, 1)):
            self.assertEqual(int(positive[y, x]), 0)
            self.assertEqual(int(valid[y, x]), 0)
        self.assertEqual(int(positive[5, 5]), 255)
        self.assertEqual(int(valid[11, 11]), 255)

    def test_unknown_coverage_never_infers_negatives(self):
        positive, valid, _ = zod.rasterize_annotations([feature("dash", 2, 2, 4, 4)], 10, 10)
        np.testing.assert_array_equal(positive, valid)
        self.assertEqual(int(valid[0, 0]), 0)
        empty, empty_valid, _ = zod.rasterize_annotations([], 10, 10)
        self.assertFalse(empty.any())
        self.assertFalse(empty_valid.any())

    def test_unknown_class_invalid_flag_and_duplicate_uuid_fail(self):
        cases = [([feature("new", 1, 1, 3, 3, "unknown")], "Unrecognized ZOD lane class"),
                 ([feature("bad", 1, 1, 3, 3, Unclear="False")], "flag"),
                 ([feature("bad", 1, 1, 3, 3, None)], "road-painting"),
                 ([feature("same", 1, 1, 3, 3), feature("same", 4, 4, 6, 6)], "Duplicate")]
        for annotations, message in cases:
            with self.subTest(message=message), self.assertRaisesRegex(ValueError, message):
                zod.rasterize_annotations(annotations, 10, 10, True)

    def test_geometry_is_not_rescaled_or_flattened(self):
        oversized = feature("outside", 1, 1, 20, 20)
        multi = feature("multi", 1, 1, 3, 3)
        multi["geometry"]["coordinates"].append([[5, 5], [7, 5], [7, 7], [5, 7]])
        nonfinite = feature("nan", 1, 1, 3, 3)
        nonfinite["geometry"]["coordinates"][0][0][0] = float("nan")
        line = feature("line", 1, 1, 3, 3)
        line["geometry"]["type"] = "LineString"
        for annotation in (oversized, multi, nonfinite, line):
            with self.subTest(annotation=annotation["properties"]["annotation_uuid"]), self.assertRaises(ValueError):
                zod.rasterize_annotations([annotation], 10, 10, True)

    def test_flat_and_single_ring_sdk_formats_match(self):
        wrapped = feature("shape", 1.9, 1.9, 4.9, 4.9)
        flat = copy.deepcopy(wrapped)
        flat["geometry"]["coordinates"] = flat["geometry"]["coordinates"][0]
        a = zod.rasterize_annotations([wrapped], 10, 10, True)[0]
        b = zod.rasterize_annotations([flat], 10, 10, True)[0]
        np.testing.assert_array_equal(a, b)
        self.assertEqual(int(a[1, 1]), 255)  # SDK truncation, not rounding


class GroupingTest(unittest.TestCase):
    def test_official_val_preserved_and_nearby_train_purged(self):
        rows = [record("000001", 50., "val"),
                record("000002", 50.001, date="2020-02-01"),
                record("000003", 51., date="2020-02-01"),
                record("000004", 53., date="2020-03-01")]
        result, excluded = zod.assign_splits(rows)
        self.assertEqual([r["split"] for r in result], ["test", "excluded", "excluded", "train"])
        self.assertEqual(len(excluded), 2)
        self.assertEqual(len({r["group_id"] for r in result[:3]}), 1)

    def test_optional_validation_is_whole_group_and_order_independent(self):
        rows = [record("000001", 50., date="2020-01-01"),
                record("000002", 50.5, date="2020-01-01"),
                record("000003", 51., date="2020-01-02"),
                record("000004", 52., "val", date="2020-01-03")]
        first, _ = zod.assign_splits(copy.deepcopy(rows), validation_fraction=.5)
        second, _ = zod.assign_splits(list(reversed(copy.deepcopy(rows))), validation_fraction=.5)
        self.assertEqual({r["frame_id"]: r["split"] for r in first}, {r["frame_id"]: r["split"] for r in second})
        self.assertEqual(first[0]["split"], first[1]["split"])
        self.assertEqual({r["split"] for r in first}, {"train", "validation", "test"})

    def test_missing_or_invalid_grouping_metadata_fails(self):
        for update in ({"latitude": float("nan")}, {"collection_car": ""}, {"official_split": "test"}):
            with self.subTest(update=update), self.assertRaises(ValueError):
                zod.assign_splits([dict(record("000001", 50.), **update)])


class ImportTest(unittest.TestCase):
    def fixture(self, root, coverage="complete_lane_markings"):
        source = root / "source"
        source.mkdir()
        infos = {"train": [], "val": []}
        for i, split in enumerate(("train", "val")):
            identity = f"{i + 1:06d}"
            prefix = "single_frames/" + identity
            frame = source / prefix
            frame.mkdir(parents=True)
            time = f"2020-01-0{i + 1}T12:00:00+00:00"
            cv2.imwrite(str(frame / "image.jpg"), np.full((12, 12, 3), 30 + i * 50, np.uint8))
            (frame / "lanes.json").write_text(json.dumps([feature(identity, 2, 2, 4, 4)]))
            metadata = {"frameId": identity, "time": time, "collectionCar": "car1", "latitude": 50. + i, "longitude": 10.}
            (frame / "metadata.json").write_text(json.dumps(metadata))
            infos[split].append({"id": identity, "keyframeTime": time, "metadataPath": prefix + "/metadata.json",
                "annotations": {"lane_markings": {"project": "lane_markings", "filepath": prefix + "/lanes.json"}},
                "cameraFrames": {"front_blur": [{"filepath": prefix + "/image.jpg", "time": time, "width": 12, "height": 12}]}})
        trainval = source / "trainval-frames-mini.json"
        trainval.write_text(json.dumps(infos))
        receipt = root / "receipt.json"
        receipt.write_text(json.dumps({"schemaVersion": 1, "dataset": "ZOD", "source_revision": "unit-test-fixture",
            "source_url": "https://example.invalid/test", "license": "CC BY-SA 4.0", "geometry": "original-pixel-polygons",
            "annotation_coverage": coverage, "coverage_evidence": "Synthetic test fixture, not downloaded data"}))
        return source, trainval, receipt, root / "prepared", infos

    def test_complete_import_hashes_masks_and_preserves_official_holdout(self):
        with tempfile.TemporaryDirectory() as directory:
            source, trainval, receipt, output, _ = self.fixture(Path(directory))
            manifest = zod.prepare(source, trainval, receipt, output)
            self.assertEqual(manifest["partition_counts"], {"train": 1, "validation": 0, "test": 1})
            self.assertTrue(manifest["training_eligible"])
            objects = {o["key"]: o for o in manifest["objects"]}
            for obj in objects.values():
                self.assertEqual(zod.sha256_file(obj["local_path"]), obj["sha256"])
            for pair in manifest["pairs"]:
                for key in ("label", "valid"):
                    mask = cv2.imread(objects[pair[key]]["local_path"], cv2.IMREAD_UNCHANGED)
                    self.assertEqual(mask.shape, (12, 12))
                    self.assertTrue(set(np.unique(mask)) <= {0, 255})
                if pair["official_split"] == "val":
                    self.assertEqual(pair["split"], "test")

    def test_unknown_coverage_manifest_not_eligible(self):
        with tempfile.TemporaryDirectory() as directory:
            source, trainval, receipt, output, _ = self.fixture(Path(directory), "unknown")
            result = zod.prepare(source, trainval, receipt, output)
            self.assertFalse(result["training_eligible"])

    def test_resized_image_rejected_with_incomplete_receipt(self):
        with tempfile.TemporaryDirectory() as directory:
            source, trainval, receipt, output, _ = self.fixture(Path(directory))
            cv2.imwrite(str(source / "single_frames/000001/image.jpg"), np.zeros((6, 6, 3), np.uint8))
            with self.assertRaisesRegex(ValueError, "dimensions"):
                zod.prepare(source, trainval, receipt, output)
            self.assertTrue((output / "incomplete.json").exists())
            self.assertFalse((output / "manifest.json").exists())

    def test_missing_annotation_is_not_negative_scene(self):
        with tempfile.TemporaryDirectory() as directory:
            source, trainval, receipt, output, infos = self.fixture(Path(directory))
            infos["train"][0]["annotations"] = {}
            trainval.write_text(json.dumps(infos))
            with self.assertRaisesRegex(ValueError, "Missing lane annotation"):
                zod.prepare(source, trainval, receipt, output)
            self.assertFalse(output.exists())

    def test_blacklisted_train_frame_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            source, trainval, receipt, output, infos = self.fixture(Path(directory))
            infos["blacklisted"] = [copy.deepcopy(infos["train"][0])]
            trainval.write_text(json.dumps(infos))
            with self.assertRaisesRegex(ValueError, "blacklisted"):
                zod.prepare(source, trainval, receipt, output)
            self.assertFalse(output.exists())

    def test_optional_quarantine_keeps_valid_frame_and_exposes_filtered_holdout(self):
        with tempfile.TemporaryDirectory() as directory:
            source, trainval, receipt, output, infos = self.fixture(Path(directory))
            invalid_path = source / infos["val"][0]["annotations"]["lane_markings"]["filepath"]
            invalid_path.write_text(json.dumps([feature("invalid", 1, 1, 3, 3, "new_unknown_class")]))
            result = zod.prepare(source, trainval, receipt, output, quarantine_invalid_annotations=True)
            self.assertEqual(result["partition_counts"], {"train": 1, "validation": 0, "test": 0})
            self.assertFalse(result["training_eligible"])
            self.assertEqual(result["exclusion_counts"], {"invalid_annotation": 1})
            self.assertEqual(result["excluded"][0]["official_split"], "val")
            self.assertEqual(result["excluded"][0]["annotation_sha256"], zod.sha256_file(invalid_path))

    def test_source_path_cannot_escape(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "some.json").write_text("{}")
            for path in ("../some.json", str(root / "some.json")):
                with self.assertRaises(ValueError):
                    zod.safe_source(root, path)


if __name__ == "__main__":
    unittest.main()
