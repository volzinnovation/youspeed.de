import copy
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import tempfile
import unittest
import zipfile

from PIL import Image


spec = importlib.util.spec_from_file_location(
    "student_crop_intake", Path(__file__).parents[2] / "scripts/tsr/student_crop_intake.py")
intake = importlib.util.module_from_spec(spec)
spec.loader.exec_module(intake)

REVISION = "a" * 40
BASE = "panoramax-studenten-2026-10-19.zip"
ADDITIONS = "mapillary-mobidata-bw-review-2026-10-21-additions.zip"


class StudentCropIntakeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        stream = io.BytesIO()
        Image.new("RGB", (4, 3), "yellow").save(stream, format="PNG")
        self.png = stream.getvalue()

    def package(self, *, name=BASE, tags=None, rows=None, extra=None, schema=None):
        root = "collection"
        digest = hashlib.sha256(self.png).hexdigest()
        if name == BASE:
            row = {"sample_id": "picture-annotation", "picture_id": "picture", "annotation_id": "annotation",
                   "group_id": "sequence-sequence", "crop_path": "inbox/classifier/picture-annotation.png",
                   "crop_sha256": digest, "suggested_label": None,
                   "osm_tags": tags if tags is not None else [{"key": "osm|traffic_sign", "value": "DE:310"}]}
            payload = {"schema_version": schema or intake.PACKAGE_SCHEMAS[name],
                       "items": [{"picture_id": "picture", "sequence_id": "sequence",
                                  "source_url": "https://example.test/picture", "author": "author", "license": "CC-BY-SA-4.0"}],
                       "crops": [row] if rows is None else rows}
        else:
            row = {"candidate_id": "mapillary-image", "image_id": "image", "sequence_id": "journey",
                   "crop_path": "inbox/classifier/mapillary-image.png", "crop_sha256": digest,
                   "visible_class_proposal": "DE:311", "proposed_model_label": "city:end",
                   "conservative_split_group_id": "site-group", "source_url": "https://example.test/image",
                   "author": "author", "license": "CC-BY-SA-4.0", "human_approved": True,
                   "eligible_for_training": True}
            payload = {"schema_version": schema or intake.PACKAGE_SCHEMAS[name], "records": [row] if rows is None else rows}
        path = self.root / name
        with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(root + "/manifest.json", json.dumps(payload))
            for row in payload.get("crops", payload.get("records", [])):
                archive.writestr(root + "/" + row["crop_path"], self.png)
            for member, data in (extra or {}).items():
                archive.writestr(member, data)
        return {"path": "packages/" + name, "archive_root": root, "bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "crops": len(payload.get("crops", payload.get("records", [])))}

    def collection(self, packages, **extra):
        payload = {"schema_version": intake.COLLECTION_SCHEMA, "repository_id": intake.DATASET_ID,
                   "packages": packages, "totals": {"crops": sum(p["crops"] for p in packages)}, **extra}
        path = self.root / "LEARNING_COLLECTION.json"
        path.write_text(json.dumps(payload))
        return path

    def read(self, path):
        return intake.read_student_archives(path, self.root, dataset_revision=REVISION)

    def test_mixed_yes_preserves_specific_code_and_native_bytes_without_approval(self):
        tags = [{"key": "osm|traffic_sign", "value": "yes"},
                {"key": "osm|traffic_sign", "value": "DE:310"},
                {"key": "osm|name", "value": "Town"}]
        record = self.read(self.collection([self.package(tags=tags)]))[0]
        self.assertEqual(record["source_annotation_labels"], ["DE:310", "yes"])
        self.assertEqual(record["raw_tags"], tags)
        self.assertEqual(record["proposed_label"], "city:start")
        self.assertEqual(record["source_kind"], "hf_student")
        self.assertEqual(record["dataset_revision"], REVISION)
        self.assertEqual(record["group_id"], "sequence-sequence")
        self.assertEqual(record["review_status"], "unreviewed")
        self.assertFalse(record["human_approved"])
        self.assertFalse(record["eligible_for_training"])
        self.assertEqual(intake.read_crop_bytes(record), self.png)

    def test_source_metadata_preserves_model_qualifiers(self):
        package = self.package()
        path = self.root / BASE
        with zipfile.ZipFile(path) as archive:
            payload = json.loads(archive.read("collection/manifest.json"))
        tags = [{"key": "osm|traffic_sign", "value": "DE:310"},
                {"key": "classification_model[osm|traffic_sign=DE:310]", "value": "source-model"}]
        metadata = json.dumps({"original_item": {"properties": {"annotations": [
            {"id": "annotation", "semantics": tags}]}}}).encode()
        payload["items"][0].update(bundle_path="inbox/detector/picture",
                                   metadata_sha256=hashlib.sha256(metadata).hexdigest())
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("collection/manifest.json", json.dumps(payload))
            archive.writestr("collection/inbox/classifier/picture-annotation.png", self.png)
            archive.writestr("collection/inbox/detector/picture/metadata.json", metadata)
        package.update(bytes=path.stat().st_size, sha256=hashlib.sha256(path.read_bytes()).hexdigest())
        self.assertEqual(self.read(self.collection([package]))[0]["raw_tags"], tags)

    def test_visual_class_proposal_is_separate_from_source_annotation(self):
        record = self.read(self.collection([self.package(name=ADDITIONS)]))[0]
        self.assertEqual(record["proposed_label"], "city:end")
        self.assertEqual(record["label_origin"], "student_visual_proposal")
        self.assertEqual(record["source_annotation_labels"], [])
        self.assertEqual(record["group_id"], "site-group")
        self.assertFalse(record["human_approved"])
        self.assertTrue(record["candidate_record"]["human_approved"])

    def test_conflicting_specific_source_codes_are_not_guessed(self):
        tags = [{"key": "osm|traffic_sign", "value": code} for code in ["DE:310", "DE:311"]]
        record = self.read(self.collection([self.package(tags=tags)]))[0]
        self.assertIsNone(record["proposed_label"])
        self.assertEqual(record["source_annotation_labels"], ["DE:310", "DE:311"])

    def test_reserved_demo_and_review_supplement_are_not_opened(self):
        allowed = self.package()
        reserved = {"path": "packages/panoramax-testkandidaten-2026-10-20.zip", "crops": 100}
        demo = {"path": "packages/panoramax-beispiele-v6.zip", "crops": 2}
        supplement = {"path": "packages/panoramax-mobidata-sign-review-2026-10-23.zip", "crops": 85}
        manifest = self.collection([allowed, reserved, demo, supplement], totals={"crops": 1},
                                   excluded_from_learning=[reserved["path"], demo["path"]],
                                   review_supplements=[supplement])
        self.assertEqual(len(self.read(manifest)), 1)

    def test_archive_hash_and_size_tampering_fail(self):
        package = self.package()
        package["sha256"] = "0" * 64
        with self.assertRaisesRegex(intake.StudentIntakeError, "SHA-256 mismatch"):
            self.read(self.collection([package]))
        package = self.package()
        package["bytes"] += 1
        with self.assertRaisesRegex(intake.StudentIntakeError, "byte count"):
            self.read(self.collection([package]))

    def test_crop_hash_tampering_fails_without_extracting_files(self):
        record = self.read(self.collection([self.package()]))[0]
        record["crop_sha256"] = "0" * 64
        before = set(self.root.iterdir())
        with self.assertRaisesRegex(intake.StudentIntakeError, "crop SHA-256 mismatch"):
            intake.read_crop_bytes(record)
        self.assertEqual(set(self.root.iterdir()), before)

    def test_archive_change_after_initial_verification_invalidates_cache(self):
        record = self.read(self.collection([self.package()]))[0]
        path = Path(record["archive_path"])
        data = path.read_bytes()
        path.write_bytes(data[:-1] + bytes([data[-1] ^ 1]))
        with self.assertRaisesRegex(intake.StudentIntakeError, "archive SHA-256 mismatch"):
            intake.read_crop_bytes(record)

    def test_zip_path_traversal_is_rejected_even_in_unreferenced_members(self):
        package = self.package(extra={"../outside.png": self.png})
        with self.assertRaisesRegex(intake.StudentIntakeError, "Unsafe ZIP"):
            self.read(self.collection([package]))

    def test_record_member_traversal_and_size_limits_are_rejected(self):
        record = self.read(self.collection([self.package()]))[0]
        changed = copy.deepcopy(record)
        changed["member_path"] = "collection/../outside.png"
        with self.assertRaisesRegex(intake.StudentIntakeError, "Unsafe ZIP"):
            intake.read_crop_bytes(changed)
        old = intake.MAX_CROP_BYTES
        try:
            intake.MAX_CROP_BYTES = len(self.png) - 1
            with self.assertRaisesRegex(intake.StudentIntakeError, "byte limit"):
                intake.read_crop_bytes(record)
        finally:
            intake.MAX_CROP_BYTES = old

    def test_wrong_schema_counts_and_mutable_revision_are_rejected(self):
        with self.assertRaisesRegex(intake.StudentIntakeError, "schema"):
            self.read(self.collection([self.package(schema="unrecognized")]))
        package = self.package()
        package["crops"] = 2
        with self.assertRaisesRegex(intake.StudentIntakeError, "crop count"):
            self.read(self.collection([package]))
        with self.assertRaisesRegex(intake.StudentIntakeError, "immutable"):
            intake.read_student_archives(self.collection([self.package()]), self.root, dataset_revision="main")


if __name__ == "__main__":
    unittest.main()
