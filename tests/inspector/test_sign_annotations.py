"""Fixture-only annotation writes, replay, transport failures and browser boundary."""
import copy
from http.client import HTTPConnection
from http.server import ThreadingHTTPServer
import json
from pathlib import Path
import tempfile
import threading
import types
import unittest
from unittest.mock import patch
from uuid import uuid4

from inspector.sign_annotations import AnnotationEditorError, ORIGIN, ROUTE, SignAnnotations
from inspector.server import InspectorHandler, arguments

PICTURE = "bb121b52-313f-4a0b-81ef-06142cbe2ea0"
ANNOTATION = "0475cc30-65a4-49d3-ba66-541c385e408d"
SEQUENCE = "f27a1dea-e610-493c-8373-c6a8ad532308"
NEXT = "fb791383-43bf-41c7-a1fc-9b3e7338ba08"


class Transport:
    class AnnotationError(Exception):
        def __init__(self, code, status=None, uncertain=False):
            self.code, self.status, self.uncertain = code, status, uncertain

    @staticmethod
    def rectangle(value):
        if isinstance(value, dict):
            points = value["coordinates"][0]
            value = [min(p[0] for p in points), min(p[1] for p in points), max(p[0] for p in points), max(p[1] for p in points)]
        if not isinstance(value, list) or len(value) != 4 or not all(type(n) is int and n >= 0 for n in value) or value[0] >= value[2] or value[1] >= value[3]:
            raise Transport.AnnotationError("rectangle_required")
        return value

    @staticmethod
    def payload_pairs(value):
        return [(r["key"], r["value"]) for r in value.get("semantics", [])]


class FixtureClient:
    token = "fixture-token-never-sent"

    def __init__(self):
        self.rows = [{"id": ANNOTATION, "picture_id": PICTURE, "shape": [10, 10, 50, 50],
                      "semantics": [{"key": "osm|traffic_sign", "value": "DE:205"},
                                    {"key": "human|note", "value": "retain this"}]}]
        self.writes = []
        self.failure = None
        self.read_failure = False

    def picture(self, picture_id):
        return {"id": picture_id, "collection": SEQUENCE, "geometry": {"type": "Point", "coordinates": [8.437, 48.798]},
                "properties": {"pers:interior_orientation": {"sensor_array_dimensions": [100, 80]},
                               "geovisio:rank_in_collection": 14 if picture_id == PICTURE else 15,
                               "datetime": "2026-10-18T16:22:19Z", "view:azimuth": 283,
                               "annotations": copy.deepcopy(self.rows if picture_id == PICTURE else [])},
                "links": [{"rel": "next", "id": NEXT, "href": ORIGIN + "/api/collections/" + SEQUENCE + "/items/" + NEXT}] if picture_id == PICTURE else []}

    public_picture = picture

    def annotation(self, annotation_id):
        if self.read_failure:
            raise Transport.AnnotationError("unavailable")
        return copy.deepcopy(next((r for r in self.rows if r["id"] == annotation_id), None))

    def _request(self, method, path, *, payload):
        self.writes.append((method, path, payload))
        if self.failure == "denied":
            raise Transport.AnnotationError("annotation_http_error", status=403)
        if self.failure == "unknown":
            self.read_failure = True
            raise Transport.AnnotationError("annotation_transport_unavailable", uncertain=True)
        if method == "POST":
            row = {"id": payload["id"], "picture_id": PICTURE, "shape": payload["shape"], "semantics": payload["semantics"]}
            self.rows.append(row)
        else:
            row = next(r for r in self.rows if r["id"] == path.rsplit("/", 1)[1])
            for tag in payload["semantics"]:
                pair = {"key": tag["key"], "value": tag["value"]}
                if tag["action"] == "delete":
                    row["semantics"].remove(pair)
                elif pair not in row["semantics"]:
                    row["semantics"].append(pair)
        if self.failure == "lost_reply":
            raise Transport.AnnotationError("annotation_transport_unavailable", uncertain=True)
        return copy.deepcopy(row)


class AnnotationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "corrections.sqlite"
        self.client = FixtureClient()
        self.editor = SignAnnotations(client=self.client, transport=Transport, journal_file=self.path)

    def payload(self, **changes):
        result = {"request_id": str(uuid4()), "base_revision": self.editor.picture(PICTURE)["revision"],
                  "annotation_id": ANNOTATION, "box_xyxy": [10, 10, 50, 50], "sign_code": "DE:206"}
        return {**result, **changes}

    def test_native_patch_preserves_unrelated_tags_and_replays_across_views(self):
        payload = self.payload()
        result = self.editor.save(PICTURE, payload)
        self.assertEqual(result["correction"]["status"], "confirmed")
        self.assertEqual(result["annotations"][0]["sign_code"], "DE:206")
        self.assertIn({"key": "human|note", "value": "retain this"}, self.client.rows[0]["semantics"])
        other = SignAnnotations(client=self.client, transport=Transport, journal_file=self.path)
        self.assertEqual(other.save(PICTURE, payload)["correction"]["request_id"], payload["request_id"])
        self.assertEqual(len(self.client.writes), 1)
        self.assertEqual(len(other.history()["corrections"]), 1)

    def test_new_annotation_reconciles_lost_reply_using_exact_uuid(self):
        self.client.failure = "lost_reply"
        result = self.editor.save(PICTURE, self.payload(annotation_id=None, box_xyxy=[60, 20, 90, 70]))
        self.assertEqual(result["correction"]["status"], "confirmed")
        self.assertEqual(len(self.client.writes), 1)
        self.assertEqual(self.client.writes[0][0], "POST")
        self.assertEqual(self.client.writes[0][2]["id"], result["correction"]["annotation_id"])

    def test_confirmed_write_is_not_uncertain_when_picture_refresh_fails(self):
        payload = self.payload()
        with patch.object(self.editor, "picture", side_effect=AnnotationEditorError("refresh_unavailable", 503)):
            result = self.editor.save(PICTURE, payload)
        self.assertEqual(result["correction"]["status"], "confirmed")
        self.assertEqual(result["picture_sync"], "refresh_required")
        self.assertEqual(self.editor.history()["corrections"][0]["status"], "confirmed")

    def test_uncertain_submission_is_not_blindly_resubmitted(self):
        payload = self.payload(annotation_id=None, box_xyxy=[60, 20, 90, 70])
        self.client.failure = "unknown"
        with self.assertRaises(AnnotationEditorError) as error:
            self.editor.save(PICTURE, payload)
        self.assertTrue(error.exception.uncertain)
        self.assertEqual(self.editor.history()["corrections"][0]["status"], "uncertain")
        self.client.read_failure = False
        with self.assertRaises(AnnotationEditorError) as retry_error:
            self.editor.save(PICTURE, payload)
        self.assertTrue(retry_error.exception.uncertain)
        self.assertEqual(len(self.client.writes), 1)

    def test_auth_rejection_is_failed_not_uncertain(self):
        self.client.failure = "denied"
        with self.assertRaises(AnnotationEditorError) as error:
            self.editor.save(PICTURE, self.payload())
        self.assertEqual(error.exception.status, 403)
        self.assertEqual(self.editor.history()["corrections"][0]["status"], "failed")

    def test_unmapped_class_uses_native_namespaced_tag_without_fabricated_sign(self):
        result = self.editor.save(PICTURE, self.payload(class_id="bad:back", sign_code=None))
        self.assertEqual(result["annotations"][0]["class_id"], "bad:back")
        self.assertIsNone(result["annotations"][0]["sign_code"])
        self.assertIn({"key": "youspeed|tsr_class", "value": "bad:back"}, self.client.rows[0]["semantics"])
        self.assertNotIn("osm|traffic_sign", [r["key"] for r in self.client.rows[0]["semantics"]])

    def test_revision_shape_bounds_collision_and_class_mapping_fail_before_write(self):
        cases = [{"base_revision": "0" * 64}, {"box_xyxy": [10, 10, 51, 50]},
                 {"annotation_id": None, "box_xyxy": [60, 20, 101, 70]},
                 {"annotation_id": None}, {"class_id": "arrow_turn_left", "sign_code": "DE:209"},
                 {"class_id": "made-up", "sign_code": None}, {"annotation_id": False}]
        for change in cases:
            with self.subTest(change=change), self.assertRaises(AnnotationEditorError):
                self.editor.save(PICTURE, self.payload(**change))
        self.assertEqual(self.client.writes, [])
        self.assertEqual(self.editor.history()["corrections"], [])

    def test_navigation_includes_an_unannotated_next_picture(self):
        result = self.editor.picture(PICTURE)
        self.assertEqual(result["next"]["id"], NEXT)
        self.assertEqual(result["next"]["navigation_basis"], "source_sequence_order")
        self.assertEqual(self.editor.picture(NEXT)["annotations"], [])
        self.assertEqual(len(self.editor.status()["classes"]), 142)
        self.assertFalse(self.editor.status()["supports_shape_edit"])

    def test_nearby_metadata_cannot_delay_primary_picture_navigation(self):
        original = self.client.picture
        calls = []
        def with_related(picture_id):
            calls.append(picture_id)
            result = original(picture_id)
            if picture_id == PICTURE:
                result["links"].append({"rel": "related", "id": NEXT,
                    "href": ORIGIN + "/api/collections/" + SEQUENCE + "/items/" + NEXT})
            return result
        self.client.public_picture = with_related
        result = self.editor.picture(PICTURE)
        self.assertTrue(result["nearby_available"])
        self.assertEqual(result["nearby"], [])
        self.assertEqual(calls, [PICTURE])
        self.assertEqual(self.editor.picture(PICTURE, nearby=True)["nearby"][0]["id"], NEXT)

    def test_existing_inspector_photo_is_reused_only_after_current_public_admission(self):
        from PIL import Image
        directory = Path(self.temp.name)
        path = directory / (PICTURE + ".jpg")
        Image.new("RGB", (100, 80)).save(path)
        path.chmod(0o600)
        self.editor.media_dir = directory
        data, mime = self.editor.photo(PICTURE)
        self.assertEqual(mime, "image/jpeg")
        self.assertEqual(data, path.read_bytes())
        def denied(_):
            raise Transport.AnnotationError("annotation_picture_not_public_ready", status=404)
        self.client.public_picture = denied
        with self.assertRaises(AnnotationEditorError):
            self.editor.photo(PICTURE)

    def test_request_id_cannot_be_reused_for_another_payload(self):
        payload = self.payload()
        self.editor.save(PICTURE, payload)
        with self.assertRaises(AnnotationEditorError):
            self.editor.save(PICTURE, {**payload, "sign_code": "DE:205"})
        self.assertEqual(len(self.client.writes), 1)

    def test_journal_owner_only_and_no_token_in_history(self):
        self.editor.save(PICTURE, self.payload())
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn(self.client.token, json.dumps(self.editor.history()))

    def test_http_read_and_save_require_same_origin(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), InspectorHandler)
        server.sign_annotations = self.editor
        server.allowed_hosts = {f"127.0.0.1:{server.server_port}"}
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        connection = HTTPConnection("127.0.0.1", server.server_port, timeout=5)
        self.addCleanup(connection.close)
        connection.request("GET", ROUTE + "/status")
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertTrue(json.load(response)["write_enabled"])
        payload = self.payload()
        path = ROUTE + "/pictures/" + PICTURE + "/annotations"
        connection.request("POST", path, body=json.dumps(payload), headers={"Content-Type": "application/json"})
        response = connection.getresponse()
        self.assertEqual(response.status, 403)
        response.read()
        connection.request("POST", path, body=json.dumps(payload), headers={"Content-Type": "application/json", "Origin": f"http://127.0.0.1:{server.server_port}"})
        response = connection.getresponse()
        self.assertEqual(response.status, 200)
        self.assertEqual(json.load(response)["correction"]["status"], "confirmed")

    def test_database_timeout_configuration(self):
        self.assertEqual(arguments([]).db_connect_timeout, 20)
        self.assertEqual(arguments(["--db-connect-timeout", "60"]).db_connect_timeout, 60)


if __name__ == "__main__":
    unittest.main()
