"""Prüft manuelle Freigabe, Integrität und gekoppelte Split-Grenzen."""
import csv
import hashlib
import io
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import uuid

from PIL import Image, ImageDraw

from import_sorted_folders import ImportError, import_review
from prepare_dataset import canonical_bytes, partition_for_group, sha256_file


class ReviewImportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.source = self.root / "collection"
        self.source.mkdir()
        self.output = self.root / "reviewed"
        self.classes = ["stop", "city:start", "city:end"]
        self.classes_file = self.root / "classes.json"
        self.classes_file.write_text(json.dumps({"classes": self.classes}))
        self.manifest = {"schema_version": "panoramax-course-collection-v1",
                         "class_folders": {label.replace(":", "__"): label for label in self.classes},
                         "class_index_sha256": sha256_file(self.classes_file),
                         "items": [], "crops": [], "crawl": {"complete_inventory": False}}

    def tearDown(self):
        self.temp.cleanup()

    def write_manifest(self):
        self.manifest.pop("lock_sha256", None)
        self.manifest["lock_sha256"] = hashlib.sha256(canonical_bytes(self.manifest)).hexdigest()
        (self.source / "manifest.json").write_text(json.dumps(self.manifest))

    def add_picture(self, number=1, *, duplicate_pixels=False, negative=False):
        pid = str(uuid.UUID(int=number))
        seq = str(uuid.UUID(int=1000 + number))
        aid = str(uuid.UUID(int=2000 + number))
        bundle = self.source / "inbox/detector" / pid
        bundle.mkdir(parents=True)
        color = (10, 20, 30) if duplicate_pixels else (number * 20, 30, 40)
        Image.new("RGB", (100, 80), color).save(bundle / "image.png")
        annotations = [] if negative else [{"annotation_id": aid, "detector_class": "sign", "bbox_xyxy": [10, 20, 70, 60]}]
        (bundle / "labels.txt").write_text("" if negative else "0 0.40000000 0.50000000 0.60000000 0.50000000\n")
        (bundle / "metadata.json").write_text(json.dumps({"picture_id": pid, "annotations": annotations}))
        item = {"picture_id": pid, "sequence_id": seq, "group_id": "sequence-" + seq,
                "width": 100, "height": 80, "image_sha256": sha256_file(bundle / "image.png"),
                "labels_sha256": sha256_file(bundle / "labels.txt"), "metadata_sha256": sha256_file(bundle / "metadata.json"),
                "bundle_path": "inbox/detector/" + pid, "source_url": "https://example.org/api/items/" + pid,
                "asset_url": "https://example.org/image/" + pid, "license": "CC-BY-SA-4.0", "author": "Dozent",
                "annotations": annotations}
        self.manifest["items"].append(item)
        crop = None
        if not negative:
            sid = f"p{pid}_a{aid}"
            path = self.source / "inbox/classifier" / (sid + ".png")
            path.parent.mkdir(parents=True, exist_ok=True)
            with Image.open(bundle / "image.png") as image:
                image.crop((10, 20, 70, 60)).save(path)
            crop = {"sample_id": sid, "picture_id": pid, "annotation_id": aid, "group_id": item["group_id"],
                    "crop_sha256": sha256_file(path), "crop_path": "inbox/classifier/" + sid + ".png",
                    "suggested_label": "city:end", "osm_tags": ["DE:311"], "bbox_xyxy": [10, 20, 70, 60]}
            self.manifest["crops"].append(crop)
        self.write_manifest()
        return item, crop

    def move_crop(self, crop, status="approved", folder="city__start", copy=False):
        original = self.source / crop["crop_path"]
        destination = self.source / status / "classifier"
        if status == "approved":
            destination /= folder
        destination.mkdir(parents=True, exist_ok=True)
        destination /= original.name
        if copy:
            shutil.copyfile(original, destination)
        else:
            shutil.move(original, destination)
        return destination

    def move_bundle(self, item, status="approved"):
        target = self.source / status / "detector" / item["picture_id"]
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(self.source / item["bundle_path"], target)
        return target

    def run_import(self, **kwargs):
        return import_review(self.source, self.output, classes_file=self.classes_file, require_136=False, **kwargs)

    def test_folder_overrides_machine_suggestion_and_both_sets_share_split(self):
        item, crop = self.add_picture()
        self.move_crop(crop); self.move_bundle(item)
        result = self.run_import()
        classifier = result["classifier_samples"][0]
        detector = result["detector_samples"][0]
        self.assertEqual(classifier["label"], "city:start")
        self.assertEqual(classifier["group_id"], detector["group_id"])
        self.assertEqual(classifier["split"], detector["split"])
        self.assertEqual(detector["split"], partition_for_group(item["group_id"], "20261026"))
        self.assertEqual(detector["review_attestation"]["complete_for_classes"], ["sign", "plate", "face"])
        with (self.output / "classifier/annotations.csv").open() as stream:
            rows = list(csv.DictReader(stream))
        self.assertEqual(list(rows[0]), ["sample_id", "image_path", "label", "group_id"])
        self.assertIn(str(self.output / "detector"), (self.output / "detector/data.yaml").read_text())
        self.assertTrue((self.output / "detector/images" / detector["split"] / (item["picture_id"] + ".png")).is_file())

    def test_unreviewed_is_not_training_ready(self):
        self.add_picture()
        with self.assertRaisesRegex(ImportError, "Noch keine"):
            self.run_import()
        self.assertFalse(self.output.exists())

    def test_duplicate_copied_crop_rejected(self):
        _, crop = self.add_picture()
        self.move_crop(crop, copy=True)
        with self.assertRaisesRegex(ImportError, "mehrfach"):
            self.run_import()

    def test_unknown_label_folder_rejected(self):
        _, crop = self.add_picture(); self.move_crop(crop, folder="DE_310")
        with self.assertRaisesRegex(ImportError, "Unbekannter Klassenordner"):
            self.run_import()

    def test_renamed_crop_rejected(self):
        _, crop = self.add_picture(); p = self.move_crop(crop); p.rename(p.with_name("renamed.png"))
        with self.assertRaisesRegex(ImportError, "umbenannt"):
            self.run_import()

    def test_modified_crop_rejected(self):
        _, crop = self.add_picture(); p = self.move_crop(crop); p.write_bytes(b"edited")
        with self.assertRaisesRegex(ImportError, "Datei verändert"):
            self.run_import()

    def test_changed_yolo_labels_rejected(self):
        item, crop = self.add_picture(); self.move_crop(crop); bundle = self.move_bundle(item)
        (bundle / "labels.txt").write_text("0 0.5 0.5 0.5 0.5\n")
        with self.assertRaisesRegex(ImportError, "Datei verändert"):
            self.run_import()

    def test_metadata_change_rejected(self):
        item, crop = self.add_picture(); self.move_crop(crop); bundle = self.move_bundle(item)
        (bundle / "metadata.json").write_text("{}")
        with self.assertRaisesRegex(ImportError, "Datei verändert"):
            self.run_import()

    def test_geometry_must_match_even_if_manifest_lock_recomputed(self):
        item, crop = self.add_picture(); self.move_crop(crop); self.move_bundle(item)
        item["annotations"][0]["bbox_xyxy"] = [20, 20, 70, 60]
        crop["bbox_xyxy"] = [20, 20, 70, 60]
        self.write_manifest()
        with self.assertRaisesRegex(ImportError, "YOLO-Boxen"):
            self.run_import()

    def test_missing_license_rejected(self):
        item, crop = self.add_picture(); self.move_crop(crop); item["license"] = ""; self.write_manifest()
        with self.assertRaisesRegex(ImportError, "Lizenz fehlt"):
            self.run_import()

    def test_path_traversal_manifest_rejected(self):
        item, _ = self.add_picture(); item["bundle_path"] = "../../escape"; self.write_manifest()
        with self.assertRaisesRegex(ImportError, "Bildpaketpfad"):
            self.run_import()

    def test_missing_files_must_be_rejected_not_deleted(self):
        _, crop = self.add_picture(); (self.source / crop["crop_path"]).unlink()
        with self.assertRaisesRegex(ImportError, "Crops fehlen"):
            self.run_import()

    def test_duplicate_bytes_cross_groups_block_until_explicit_merge(self):
        one, crop_one = self.add_picture(1, duplicate_pixels=True)
        two, crop_two = self.add_picture(2, duplicate_pixels=True)
        for item, crop in [(one, crop_one), (two, crop_two)]:
            self.move_crop(crop); self.move_bundle(item)
        with self.assertRaisesRegex(ImportError, "verschiedenen Gruppen"):
            self.run_import()
        groups = self.root / "groups.csv"
        groups.write_text("sequence_id,group_id\n" + one["sequence_id"] + ",same-physical-location\n" + two["sequence_id"] + ",same-physical-location\n")
        result = self.run_import(groups=groups)
        self.assertEqual({row["group_id"] for row in result["classifier_samples"]}, {"same-physical-location"})
        self.assertEqual(len({row["split"] for row in result["detector_samples"] + result["classifier_samples"]}), 1)

    def test_pending_and_rejected_counts_and_partial_class_coverage(self):
        one, crop_one = self.add_picture(1); two, crop_two = self.add_picture(2)
        self.move_crop(crop_one); self.move_crop(crop_two, status="rejected")
        self.move_bundle(two, status="rejected")
        result = self.run_import()
        self.assertEqual(result["review_counts"]["classifier"], {"inbox": 0, "approved": 1, "rejected": 1})
        self.assertEqual(result["review_counts"]["detector"], {"inbox": 1, "approved": 0, "rejected": 1})
        self.assertEqual(len(result["detector_samples"]), 0)
        self.assertTrue(any(result["missing_classifier_classes"].values()))

    def test_teacher_corpus_merge_keeps_csv_contract_and_group(self):
        _, crop = self.add_picture(); self.move_crop(crop)
        images = self.root / "teacher"; images.mkdir()
        Image.new("RGB", (12, 12), "green").save(images / "stop.png")
        annotations = self.root / "teacher.csv"
        annotations.write_text("sample_id,image_path,label,group_id\nold-stop,stop.png,stop,teacher-stop-1\n")
        result = self.run_import(include_annotations=annotations, include_images=images)
        self.assertEqual(result["teacher_samples"], 1)
        self.assertEqual(next(row["group_id"] for row in result["classifier_samples"] if row["origin"] == "teacher"), "teacher-stop-1")
        self.assertEqual(result["teacher_annotations_sha256"], sha256_file(annotations))

    def test_teacher_options_must_be_paired(self):
        _, crop = self.add_picture(); self.move_crop(crop)
        with self.assertRaisesRegex(ImportError, "gemeinsam"):
            self.run_import(include_annotations=self.root / "none.csv")

    def test_empty_labels_only_exported_after_full_frame_approval(self):
        item, _ = self.add_picture(negative=True)
        self.move_bundle(item)
        result = self.run_import()
        row = result["detector_samples"][0]
        self.assertTrue(row["review_attestation"]["negative_frame"])
        self.assertEqual((self.output / "detector/labels" / row["split"] / (item["picture_id"] + ".txt")).read_text(), "")

    def test_existing_output_is_never_overwritten(self):
        _, crop = self.add_picture(); self.move_crop(crop); self.output.mkdir()
        marker = self.output / "keep.txt"; marker.write_text("keep")
        with self.assertRaisesRegex(ImportError, "existiert bereits"):
            self.run_import()
        self.assertEqual(marker.read_text(), "keep")

    def test_exact_file_manager_caches_are_ignored_at_all_review_levels(self):
        item, crop = self.add_picture(); crop_path = self.move_crop(crop); bundle = self.move_bundle(item)
        folders = [self.source / status for status in ["inbox", "approved", "rejected"]]
        folders += [self.source / "approved/classifier", self.source / "approved/detector", crop_path.parent, bundle]
        for folder in folders:
            folder.mkdir(parents=True, exist_ok=True)
            for filename in [".DS_Store", "Thumbs.db"]:
                (folder / filename).write_bytes(b"file-manager-cache")
        result = self.run_import()
        self.assertEqual(len(result["classifier_samples"]), 1)
        self.assertEqual(len(result["detector_samples"]), 1)
        self.assertFalse(any(Path(name).name in {".DS_Store", "Thumbs.db"} for name in result["output_sha256"]))
        self.assertEqual(sha256_file(bundle / "image.png"), item["image_sha256"])
        self.assertEqual(sha256_file(bundle / "labels.txt"), item["labels_sha256"])
        self.assertEqual(sha256_file(bundle / "metadata.json"), item["metadata_sha256"])

    def test_other_hidden_files_still_rejected(self):
        _, crop = self.add_picture(); path = self.move_crop(crop)
        (path.parent / ".unexpected.png").write_bytes(b"not-a-cache")
        with self.assertRaisesRegex(ImportError, "Crop unbekannt"):
            self.run_import()

    def test_custom_seed_cannot_decouple_detector_from_prepare_defaults(self):
        _, crop = self.add_picture(); self.move_crop(crop)
        with self.assertRaisesRegex(ImportError, "fest Seed"):
            self.run_import(seed="try-a-better-score")

    def test_class_index_bytes_must_match_crawler_source(self):
        _, crop = self.add_picture(); self.move_crop(crop)
        self.manifest["class_index_sha256"] = "0" * 64; self.write_manifest()
        with self.assertRaisesRegex(ImportError, "Klassentabelle"):
            self.run_import()

    def test_real_crawler_move_import_prepare_pipeline_with_136_classes(self):
        """408 künstliche Crops; echte Vorbedingungen ohne Abschalten von Prüfungen."""
        from crawl_panoramax import crawl, parser
        from prepare_dataset import DEFAULT_CLASSES, prepare_dataset
        labels = json.loads(DEFAULT_CLASSES.read_text())["classes"]
        base = "https://fixture.example/"
        features, assets, urls, ids = {}, {}, [], {}
        for split_index, split in enumerate(["train", "val", "test"], 1):
            seq_number = next(i for i in range(split_index * 10000, split_index * 10000 + 10000)
                              if partition_for_group("sequence-" + str(uuid.UUID(int=i)), "20261026") == split)
            sequence = str(uuid.UUID(int=seq_number))
            picture = str(uuid.UUID(int=50000 + split_index))
            image = Image.new("RGB", (1020, 480)); draw = ImageDraw.Draw(image)
            annotations = []
            for index, label in enumerate(labels):
                x, y = (index % 17) * 60, (index // 17) * 60
                draw.rectangle((x, y, x + 59, y + 59), fill=(index, split_index, 90))
                annotation = str(uuid.UUID(int=100000 + split_index * 1000 + index))
                annotations.append({"id": annotation, "semantics": [{"key": "osm|traffic_sign", "value": "yes"}],
                                    "shape": [x + 5, y + 5, x + 55, y + 55]})
                ids[f"p{picture}_a{annotation}"] = label
            asset = base + "images/" + picture + ".png"
            raw = io.BytesIO(); image.save(raw, format="PNG"); assets[asset] = raw.getvalue()
            url = base + f"api/collections/{sequence}/items/{picture}"; urls.append(url)
            features[url] = {"type": "Feature", "id": picture, "collection": sequence,
                             "assets": {"hd": {"href": asset}}, "links": [{"rel": "self", "href": url}],
                             "properties": {"license": "CC-BY-SA-4.0", "geovisio:producer": "synthetic-fixture",
                                            "geovisio:status": "ready", "geovisio:visibility": "anyone",
                                            "pers:interior_orientation": {"field_of_view": 60, "sensor_array_dimensions": [1020, 480]},
                                            "annotations": annotations}}
        class FakeClient:
            def json(self, url):
                return features[url]
            def get(self, url, max_bytes):
                return assets[url]
        collection = self.root / "integration-collection"
        arguments = ["--instance", base, "--output", str(collection)]
        for url in urls:
            arguments += ["--item-url", url]
        crawled = crawl(parser().parse_args(arguments), client=FakeClient())
        self.assertEqual(len(crawled["items"]), 3)
        self.assertEqual(len(crawled["crops"]), 408)
        for crop in crawled["crops"]:
            target = collection / "approved/classifier" / ids[crop["sample_id"]].replace(":", "__")
            shutil.move(collection / crop["crop_path"], target / (crop["sample_id"] + ".png"))
        for item in crawled["items"]:
            shutil.move(collection / item["bundle_path"], collection / "approved/detector" / item["picture_id"])
        reviewed = self.root / "integration-reviewed"
        review = import_review(collection, reviewed)
        dataset = self.root / "integration-dataset"
        prepared = prepare_dataset(reviewed / "classifier/annotations.csv", reviewed / "classifier/images", dataset,
                                   require_136=True)
        self.assertEqual(prepared["counts"]["images"], {"train": 136, "val": 136, "test": 136})
        picture_splits = {row["picture_id"]: row["split"] for row in review["detector_samples"]}
        for row in review["classifier_samples"]:
            self.assertEqual(row["split"], picture_splits[row["picture_id"]])
        imported_by_id = {row["sample_id"]: row for row in review["classifier_samples"]}
        for row in prepared["samples"]:
            self.assertEqual(row["split"], imported_by_id[row["sample_id"]]["split"])


if __name__ == "__main__":
    unittest.main()
