import copy
import csv
import hashlib
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from PIL import Image

from scripts.tsr import annotation_training_intake as intake
from scripts.tsr import student_crop_intake


REVISION = "a" * 40
BASE = "panoramax-studenten-2026-10-19.zip"
PROPOSALS = "mapillary-mobidata-bw-review-2026-10-21-additions.zip"
CLASSES = {"classes": ["bad", "city:start", "city:end"], "baseline_class_count": 1,
           "new_class_mapping": {"city:start": "DE:310", "city:end": "DE:311"}}


def png(color="yellow", size=(8, 6)):
    stream = io.BytesIO()
    Image.new("RGB", size, color).save(stream, format="PNG")
    return stream.getvalue()


def source_label(class_id="city:start", raw="DE:310"):
    return {"raw_tag": raw, "target_classifier_country": "DE",
            "semantic_mapping_status": "unique", "semantic_candidates": [{"label": class_id}],
            "yolo_mapping_status": "catalog_mismatch", "selected_yolo": None}


class AnnotationTrainingIntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.images = self.root / "server-images"
        self.images.mkdir()
        self.output_number = 0

    def city(self, *, crop="current", picture="picture", annotation="annotation", color="yellow", labels=None,
             rights=True, sequence="sequence"):
        data = png(color)
        digest = hashlib.sha256(data).hexdigest()
        (self.images / (digest + ".png")).write_bytes(data)
        row = {"crop_id": crop, "picture_id": picture, "annotation_id": annotation,
               "source_id": "panoramax.woladen.de", "source_base_url": "https://panoramax.woladen.de",
               "crop_sha256": digest, "width": 8, "height": 6,
               "labels": [source_label()] if labels is None else labels,
               "license": None, "contributor": {"name": "admin"},
               "sequence_ids": [sequence], "geometry": {"actual_box": [1, 2, 9, 8]}}
        if rights:
            row["rights"] = {"license": "CC-BY-SA-4.0", "author": "admin",
                             "source_url": "https://panoramax.woladen.de/api/pictures/" + picture,
                             "license_evidence_url": "https://panoramax.woladen.de/api/pictures/" + picture}
        return row

    def student(self, *, archive_name=BASE, codes=None, color="orange", sample="old-student",
                picture="picture", annotation="annotation", extra_packages=None):
        data = png(color)
        digest = hashlib.sha256(data).hexdigest()
        tags = [{"key": "osm|traffic_sign", "value": value}
                for value in (["DE:310"] if codes is None else codes)]
        row = {"sample_id": sample, "candidate_id": sample, "picture_id": picture,
               "annotation_id": annotation, "sequence_id": "sequence",
               "source_url": "https://panoramax.youspeed.de/api/pictures/" + picture,
               "crop_path": "inbox/classifier/" + sample + ".png", "crop_sha256": digest,
               "suggested_label": "city:start", "proposed_model_label": "city:end",
               "visible_class_proposal": "DE:311", "osm_tags": tags,
               "human_approved": True, "eligible_for_training": True,
               "author": "admin", "license": "CC-BY-SA-4.0"}
        payload = {"schema_version": student_crop_intake.PACKAGE_SCHEMAS[archive_name],
                   "items": [{"picture_id": picture, "sequence_id": "sequence",
                              "source_url": row["source_url"], "author": "admin", "license": "CC-BY-SA-4.0"}],
                   "crops" if archive_name == BASE else "records": [row]}
        path = self.root / archive_name
        with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("learning/manifest.json", json.dumps(payload))
            archive.writestr("learning/" + row["crop_path"], data)
        package = {"path": "packages/" + archive_name, "archive_root": "learning", "crops": 1,
                   "bytes": path.stat().st_size, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        collection = {"schema_version": student_crop_intake.COLLECTION_SCHEMA,
                      "repository_id": student_crop_intake.DATASET_ID,
                      "packages": [package] + (extra_packages or []), "totals": {"crops": 1}}
        manifest = self.root / "collection.json"
        manifest.write_text(json.dumps(collection))
        records = student_crop_intake.read_student_archives(manifest, self.root, dataset_revision=REVISION)
        return records, manifest

    def build(self, rows, students=None, **kwargs):
        self.output_number += 1
        self.output = self.root / ("intake-" + str(self.output_number))
        return intake.build_from_records(rows, students or [], panoramax_images=self.images,
                                         classes=kwargs.pop("classes", CLASSES),
                                         output=self.output, **kwargs)

    def test_manual_city_and_generic_yes_preserve_native_image_and_source_origin(self):
        labels = [source_label(), {"raw_tag": "yes", "parsed": {"raw": "yes", "code": "yes"}}]
        current = self.city(labels=labels)
        before = copy.deepcopy(current)
        result = self.build([current], include_source_labels=True)
        self.assertEqual(current, before)
        self.assertEqual(result["record_count"], 1)
        self.assertEqual(result["training_sample_count"], 1)
        sample = result["samples"][0]
        self.assertEqual(sample["label"], "city:start")
        self.assertEqual(sample["label_origin"], "source_annotation")
        self.assertFalse(sample["human_approved"])
        self.assertEqual(sample["review_status"], "unreviewed")
        self.assertFalse(sample["classifier_supported"])
        self.assertEqual(sample["split"], "train")
        self.assertEqual(result["records"][0]["resolution"]["ignored_detection_tags"], ["yes"])
        self.assertEqual((self.output / sample["image"]["path"]).read_bytes(), png())
        self.assertEqual((sample["image"]["width"], sample["image"]["height"]), (8, 6))
        with (self.output / "train.csv").open(newline="") as stream:
            row = next(csv.DictReader(stream))
        self.assertEqual((row["label"], row["split"], row["class_index"]), ("city:start", "train", "1"))

    def test_source_annotation_needs_explicit_opt_in_even_if_model_unsupported(self):
        result = self.build([self.city()])
        self.assertEqual(result["training_sample_count"], 0)
        self.assertFalse(result["samples"][0]["training_ready"])
        self.assertIn("source_label_training_not_enabled", result["samples"][0]["reasons"])
        self.assertEqual(result["native_image_object_count"], 1)

    def test_current_owned_annotation_supersedes_old_hf_copy_without_adding_crop(self):
        students, _ = self.student(codes=["DE:311"], color="orange")
        result = self.build([self.city()], students, include_source_labels=True)
        self.assertEqual(result["record_count"], 2)
        self.assertEqual(result["unique_sample_count"], 1)
        self.assertEqual(result["native_image_object_count"], 2)
        self.assertEqual(result["training_sample_count"], 1)
        self.assertEqual(result["samples"][0]["sample_id"], "panoramax-current")
        self.assertEqual(result["samples"][0]["label"], "city:start")
        self.assertEqual(result["records"][1]["duplicate_of"], "panoramax-current")
        self.assertEqual(sum(s["source_record_count"] for s in result["samples"]), 2)
        self.assertTrue(all(record["image"]["valid"] for record in result["records"]))

    def test_exact_crop_bytes_deduplicate_and_conflicting_annotations_require_review(self):
        left = self.city(crop="left", picture="left-picture", annotation="left-sign")
        right = self.city(crop="right", picture="right-picture", annotation="right-sign")
        result = self.build([left, right], include_source_labels=True)
        self.assertEqual((result["record_count"], result["unique_sample_count"], result["native_image_object_count"]), (2, 1, 1))
        self.assertEqual(result["training_sample_count"], 1)
        self.assertEqual(result["records"][0]["group_id"], result["records"][1]["group_id"])
        right["labels"] = [source_label("city:end", "DE:311")]
        result = self.build([left, right], include_source_labels=True)
        self.assertEqual(result["training_sample_count"], 0)
        self.assertIn("identical_crop_bytes_have_conflicting_source_labels", result["samples"][0]["reasons"])

    def test_all_four_archive_visual_proposals_stay_unreviewed_even_with_source_opt_in(self):
        for name in student_crop_intake.PACKAGE_SCHEMAS:
            if name == BASE:
                continue
            students, _ = self.student(archive_name=name, sample="candidate-" + str(self.output_number))
            result = self.build([], students, include_source_labels=True)
            self.assertEqual(result["training_sample_count"], 0, name)
            self.assertEqual(result["native_image_object_count"], 1)
            self.assertEqual(result["records"][0]["proposed_label"], "city:end")
            self.assertIsNone(result["samples"][0]["label"])
            self.assertEqual(result["samples"][0]["proposed_labels"], ["city:end"])
            self.assertTrue(result["samples"][0]["review_required"])
            self.assertFalse(result["samples"][0]["human_approved"])

    def test_explicit_review_csv_admits_proposal_without_changing_its_source_metadata(self):
        students, _ = self.student(archive_name=PROPOSALS)
        reviews = self.root / "approved.csv"
        reviews.write_text("sample_id,label,reviewer\nold-student,city:end,reviewer-one\n")
        result = self.build([], students, reviewed_csv=reviews)
        self.assertEqual(result["training_sample_count"], 1)
        sample = result["samples"][0]
        self.assertEqual(sample["label_origin"], "human_review")
        self.assertTrue(sample["human_approved"])
        self.assertEqual(sample["reviewer"], "reviewer-one")
        self.assertEqual(result["records"][0]["provenance"]["review_status"], "unreviewed")

    def test_hash_conflict_unresolved_label_and_missing_rights_cannot_train(self):
        row = self.city()
        (self.images / (row["crop_sha256"] + ".png")).write_bytes(png("blue"))
        result = self.build([row], include_source_labels=True)
        self.assertEqual(result["invalid_image_record_count"], 1)
        self.assertEqual(result["training_sample_count"], 0)
        self.assertEqual(result["records"][0]["image"]["error"], "crop_sha256_mismatch")
        row = self.city(labels=[{"parsed": {"code": "yes"}}])
        result = self.build([row], include_source_labels=True)
        self.assertEqual(result["training_sample_count"], 0)
        self.assertTrue(result["samples"][0]["review_required"])
        row = self.city(rights=False)
        result = self.build([row], include_source_labels=True)
        self.assertEqual(result["native_image_object_count"], 1)
        self.assertEqual(result["training_sample_count"], 0)
        self.assertIn("missing_or_unknown_image_license", result["samples"][0]["reasons"])

    def test_missing_native_file_is_retained_as_actionable_error(self):
        row = self.city()
        path = self.images / (row["crop_sha256"] + ".png")
        path.unlink()
        result = self.build([row], include_source_labels=True)
        self.assertEqual(result["record_count"], 1)
        self.assertEqual(result["invalid_image_record_count"], 1)
        self.assertIn(str(path), result["records"][0]["image"]["error"])
        self.assertEqual(result["training_sample_count"], 0)

    def test_unknown_base_class_stays_queue_and_generic_yes_does_not_erase_city(self):
        students, _ = self.student(codes=["yes", "DE:310"])
        result = self.build([], students, include_source_labels=True)
        self.assertEqual(result["training_sample_count"], 1)
        self.assertEqual(result["samples"][0]["label"], "city:start")
        students, _ = self.student(codes=["DE:306"])
        result = self.build([], students, include_source_labels=True)
        self.assertEqual(result["training_sample_count"], 0)
        self.assertIsNone(result["samples"][0]["label"])

    def test_precise_baseline_source_codes_resolve_through_shared_catalog(self):
        classes = {"classes": ["bad", "priority:start", "maxspeed:30", "city:start", "city:end"],
                   "baseline_class_count": 3}
        for codes, expected in [(["DE:306"], "priority:start"),
                                (["yes", "DE:306"], "priority:start"),
                                (["DE:274-30"], "maxspeed:30")]:
            with self.subTest(codes=codes):
                students, _ = self.student(codes=codes)
                result = self.build([], students, classes=classes, include_source_labels=True)
                self.assertEqual(result["training_sample_count"], 1)
                sample = result["samples"][0]
                self.assertEqual(sample["label"], expected)
                self.assertEqual(sample["label_origin"], "source_annotation")
                self.assertTrue(sample["classifier_supported"])
                self.assertFalse(sample["human_approved"])
                self.assertEqual(result["records"][0]["provenance"]["source_annotation_labels"], sorted(codes))
                mapping = result["source_label_mapping"]
                self.assertEqual(mapping["policy"], "exact_shared_de_catalog_intersection_v1")
                self.assertEqual(mapping["catalog"]["sha256"], hashlib.sha256(intake.DE_CATALOG.read_bytes()).hexdigest())
                self.assertEqual(mapping["catalog"]["path"], "shared/tsr/prolix-de-class-catalog-v1.json")

    def test_ambiguous_baseline_source_code_remains_withheld(self):
        classes = {"classes": ["parking:perpendicular", "parking:sidewalk", "city:start", "city:end"],
                   "baseline_class_count": 2}
        students, _ = self.student(codes=["DE:315"])
        result = self.build([], students, classes=classes, include_source_labels=True)
        self.assertEqual(result["training_sample_count"], 0)
        self.assertIsNone(result["samples"][0]["label"])
        self.assertTrue(result["samples"][0]["review_required"])
        self.assertEqual(result["records"][0]["resolution"]["status"], "ambiguous")
        self.assertEqual(result["source_label_mapping"]["candidate_classes_by_source_code"]["DE:315"],
                         ["parking:perpendicular", "parking:sidewalk"])

    def test_builder_uses_adapter_reserved_teacher_demo_and_supplement_gate(self):
        forbidden = [{"path": "packages/" + name, "crops": 999} for name in [
            "panoramax-testkandidaten-2026-10-20.zip", "panoramax-beispiele-v6.zip",
            "panoramax-mobidata-sign-review-2026-10-23.zip"]]
        _, collection = self.student(extra_packages=forbidden)
        export = self.root / "server.json"
        export.write_text(json.dumps({"as_of": "2026-11-03T20:00:00+00:00", "records": []}))
        classes = self.root / "classes.json"
        classes.write_text(json.dumps(CLASSES))
        result = intake.build_intake(panoramax_export=export, panoramax_images=self.images,
                                     student_collection=collection, student_archives=self.root,
                                     student_revision=REVISION, classes=classes, output=self.root / "integration",
                                     include_source_labels=True)
        self.assertEqual(result["record_count"], 1)
        self.assertEqual(result["training_sample_count"], 1)
        self.assertFalse(result["policy"]["reserved_teacher_demo_and_review_supplements_admitted"])
        self.assertEqual(result["source_snapshot"], "2026-11-03T20:00:00+00:00")

    def test_review_cannot_override_missing_rights_and_bad_reviews_are_rejected(self):
        row = self.city(rights=False)
        reviews = self.root / "reviewed.csv"
        reviews.write_text("sample_id,label,reviewer\npanoramax-current,city:start,reviewer\n")
        result = self.build([row], reviewed_csv=reviews)
        self.assertTrue(result["samples"][0]["human_approved"])
        self.assertEqual(result["training_sample_count"], 0)
        reviews.write_text("sample_id,label,reviewer\nnot-present,city:start,reviewer\n")
        with self.assertRaisesRegex(intake.IntakeError, "unknown sample"):
            self.build([row], reviewed_csv=reviews)

    def test_connected_sequence_groups_do_not_claim_independent_samples(self):
        left = self.city(crop="left", picture="one", annotation="one", color="yellow")
        right = self.city(crop="right", picture="two", annotation="two", color="blue")
        result = self.build([left, right], include_source_labels=True)
        self.assertEqual(result["unique_sample_count"], 2)
        self.assertEqual(result["samples"][0]["group_id"], result["samples"][1]["group_id"])
        self.assertFalse(result["policy"]["physical_sign_independence_established"])
        self.assertTrue(all(s["split"] == "train" for s in result["samples"]))


if __name__ == "__main__":
    unittest.main()
