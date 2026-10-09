"""Read-only crop API, private asset access and stored-image integrity checks."""
from contextlib import contextmanager
import hashlib
from http.client import HTTPConnection
import importlib.util
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location("inspector_server", Path(__file__).resolve().parents[2] / "inspector/server.py")
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)

INSTALLATION = "d3e3c09c-2fc6-4f05-9698-67b8c3c30212"
CROP = "78b247a4-9f14-430d-a3c0-af218a95d101"
IMAGE_PATH = f"/inspector/api/crops/{INSTALLATION}/0/{CROP}/image"
PNG = b"\x89PNG\r\n\x1a\n" + b"synthetic image bytes"


def media_row(data=PNG):
    digest = hashlib.sha256(data).hexdigest()
    return {"object_path": f"{INSTALLATION}-0-{CROP}.crop", "digest": digest,
            "manifest": {"encoding": "PNG", "encoded_sha256": digest, "byte_length": len(data)}}


class ImageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.row = media_row()
        self.path = self.root / self.row["object_path"]
        self.path.write_bytes(PNG)

    def test_unchanged_image_bytes_and_digest(self):
        self.assertEqual(server.read_image(self.root, self.row), (PNG, "image/png"))

    def test_legacy_content_addressed_object(self):
        self.row["object_path"] = self.row["digest"]
        (self.root / self.row["digest"]).write_bytes(PNG)
        self.assertEqual(server.read_image(self.root, self.row)[0], PNG)

    def test_corrupt_image_and_manifest_are_rejected(self):
        for change in ("bytes", "manifest"):
            with self.subTest(change=change):
                if change == "bytes":
                    self.path.write_bytes(PNG[:-1] + b"x")
                else:
                    self.path.write_bytes(PNG)
                    self.row["manifest"]["byte_length"] += 1
                with self.assertRaises(server.InspectorError) as error:
                    server.read_image(self.root, self.row)
                self.assertEqual(error.exception.status, 422)

    def test_missing_directory_or_deleted_file(self):
        with self.assertRaises(server.InspectorError):
            server.read_image(None, self.row)
        self.path.unlink()
        with self.assertRaises(server.InspectorError) as error:
            server.read_image(self.root, self.row)
        self.assertEqual(error.exception.status, 404)

    def test_path_traversal_and_symlink_rejected(self):
        self.row["object_path"] = "../secret.txt"
        with self.assertRaises(server.InspectorError):
            server.read_image(self.root, self.row)
        self.row = media_row()
        target = self.root / "secret.txt"
        target.write_bytes(PNG)
        self.path.unlink()
        self.path.symlink_to(target)
        with self.assertRaises(server.InspectorError):
            server.read_image(self.root, self.row)

    def test_unsupported_format_is_rejected_even_with_matching_hash(self):
        data = b"<svg>untrusted</svg>"
        self.row = media_row(data)
        self.path.write_bytes(data)
        with self.assertRaises(server.InspectorError):
            server.read_image(self.root, self.row)


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.store = server.CropStore(server.arguments([]))
        self.calls = []
        self.rows = []
        self.control = {"fresh": True}
        test = self

        class Database:
            def execute(self, sql, params=None):
                test.calls.append((sql, params))
                return self

            def fetchall(self):
                return test.rows

            def fetchone(self):
                if "AS fresh" in test.calls[-1][0]:
                    return test.control
                return test.rows[0] if test.rows else None

        @contextmanager
        def connection():
            yield Database()

        self.store.connection = connection

    def test_pagination_and_search_stay_parameterized(self):
        self.rows = [{"crop_id": CROP, "installation": INSTALLATION, "epoch": n} for n in range(3)]
        result = self.store.list({"query": ["' OR true --"], "limit": ["2"]})
        self.assertEqual(len(result["crops"]), 2)
        self.assertTrue(result["has_more"])
        sql, params = self.calls[-1]
        self.assertNotIn("' OR true --", sql)
        self.assertEqual(params[-2:], [3, 0])
        self.assertIn("' or true --", params)
        self.assertEqual(result["crops"][0]["image_url"], IMAGE_PATH)

    def test_live_default_excludes_replay_before_pagination(self):
        result = self.store.list({})
        sql, params = self.calls[-1]
        self.assertEqual(result["scope"], "live")
        self.assertIn("youspeed.live_crop_exclusion_reason(m.manifest,e.payload->'event') IS NULL", sql)
        self.assertLess(sql.index("live_crop_exclusion_reason"), sql.rindex(" LIMIT "))
        self.assertIn("a.scope='crop_storage' AND a.state='granted'", sql)
        self.assertIn("a.scope='sign_metadata' AND a.state='granted'", sql)

    def test_review_and_exit_filters_are_global_and_distinct(self):
        self.store.list({"review_state": ["wrong_class"], "exit_context": ["near_exit"], "class_source": ["reviewed"], "query": ["274"]})
        sql, params = self.calls[-1]
        self.assertIn("COALESCE(r.verdict,'unreviewed')=%s", sql)
        self.assertIn("c.status=%s", sql)
        self.assertIn("WHEN r.verdict='confirmed' THEN e.payload->'event'->'classification'", sql)
        self.assertIn("WHEN r.verdict='wrong_class' THEN r.corrected_classification", sql)
        self.assertEqual(params, ["wrong_class", "near_exit", "274", "274", "274", "274", 51, 0])
        self.assertLess(sql.index("c.status=%s"), sql.rindex(" LIMIT "))

    def test_reviewed_country_uses_reviewed_classification(self):
        self.store.list({"class_source": ["reviewed"], "country": ["FR"]})
        sql, params = self.calls[-1]
        self.assertIn("WHEN r.verdict='wrong_class' THEN r.corrected_classification ELSE NULL END)->>'country'=%s", sql)
        self.assertEqual(params, ["FR", 51, 0])

    def test_phone_way_filter_is_exact_string_before_pagination(self):
        way = "9007199254740993"
        self.store.list({"phone_way_id": [way], "country": ["DE"], "offset": ["50"]})
        sql, params = self.calls[-1]
        self.assertIn("m.manifest->'phone_road_match'->>'osm_way_id'=%s", sql)
        self.assertIn("jsonb_typeof(m.manifest->'phone_road_match'->'osm_way_id')='string'", sql)
        self.assertIn("->>'source'='on_device_bundle_matcher'", sql)
        self.assertLess(sql.index("->>'osm_way_id'=%s"), sql.rindex(" LIMIT "))
        self.assertNotIn(way, sql)
        self.assertEqual(params, [way, "DE", 51, 50])

    def test_phone_way_filter_rejects_lossy_or_noncanonical_ids(self):
        for value in ["0", "01", "-1", "1.5", "1e4", "1 OR true", " 123", "9223372036854775808"]:
            with self.subTest(value=value), self.assertRaises(server.InspectorError):
                self.store.list({"phone_way_id": [value]})
        self.assertEqual(self.calls, [])

    def test_observation_sequence_is_bound_to_installation_epoch(self):
        self.store.list({"installation": [INSTALLATION], "observation_id": [CROP], "collection_epoch": ["0"]})
        sql, params = self.calls[-1]
        self.assertIn("m.installation=%s", sql)
        self.assertIn("m.epoch=%s", sql)
        self.assertIn("m.manifest->>'observation_id'=%s", sql)
        self.assertEqual(params, [INSTALLATION, 0, CROP, 51, 0])
        for fields in [{"observation_id": [CROP]},
                       {"observation_id": [CROP], "collection_epoch": ["0"]},
                       {"installation": [INSTALLATION], "collection_epoch": ["0"]},
                       {"installation": [INSTALLATION], "observation_id": [CROP], "collection_epoch": ["2147483648"]}]:
            with self.subTest(fields=fields), self.assertRaises(server.InspectorError):
                self.store.list(fields)

    def test_live_analysis_requires_fresh_complete_controls(self):
        for control in (None, {"fresh": False}, {"fresh": None}):
            self.control = control
            for operation in (lambda: self.store.list({}), self.store.devices):
                with self.subTest(control=control), self.assertRaises(server.InspectorError) as error:
                    operation()
                self.assertEqual(error.exception.status, 503)
                self.assertIn("AS fresh", self.calls[-1][0])
        self.store.list({"scope": ["legacy"]})
        self.assertNotIn("control_state", self.calls[-1][0])

    def test_legacy_browsing_has_no_analysis_or_review_authority(self):
        self.store.list({"scope": ["legacy"]})
        sql, _ = self.calls[-1]
        self.assertIn("false AS analysis_eligible", sql)
        self.assertNotIn("live_crop_exclusion_reason", sql)
        self.assertNotIn("crop_reviews", sql)
        with self.assertRaises(server.InspectorError):
            self.store.list({"scope": ["legacy"], "review_state": ["confirmed"]})

    def test_not_computed_is_not_a_negative_or_unknown_context(self):
        self.store.list({"exit_context": ["not_computed"]})
        sql, _ = self.calls[-1]
        self.assertIn("c.context_key IS NULL", sql)
        self.assertNotIn("c.status=%s", sql)

    def test_bad_filters_fail_before_database_access(self):
        for query in ({"limit": ["10000"]}, {"source": ["invented"]}, {"offset": ["-1"]},
                      {"country": ["DE", "FR"]}, {"sql": ["DROP TABLE"]},
                      {"from": ["2026-10-06"], "to": ["2026-10-01"]},
                      {"installation": ["not-a-device"]},
                      {"installation": [INSTALLATION, CROP]}):
            with self.subTest(query=query), self.assertRaises(server.InspectorError):
                self.store.list(query)
        self.assertEqual(self.calls, [])

    def test_individual_device_filter_uses_exact_uuid_and_keeps_other_filters(self):
        self.store.list({"installation": [INSTALLATION.upper()], "country": ["DE"], "offset": ["50"]})
        sql, params = self.calls[-1]
        self.assertIn("m.installation=%s", sql)
        self.assertNotIn(INSTALLATION, sql)
        self.assertEqual(params, [INSTALLATION, "DE", 51, 50])

    def test_device_choices_span_all_pages_and_keep_active_media_rules(self):
        self.rows = [{"installation": INSTALLATION, "crop_count": 228, "platforms": ["ios"]},
                     {"installation": CROP, "crop_count": 15, "platforms": ["android"]}]
        result = self.store.devices()
        self.assertEqual(result["devices"], self.rows)
        sql, params = self.calls[-1]
        self.assertIsNone(params)
        self.assertIn("GROUP BY m.installation", sql)
        self.assertNotIn("OFFSET", sql)
        for condition in ("m.expires >", "t.deleted_through", "a.state<>'granted'"):
            self.assertIn(condition, sql)

    def test_utc_inclusive_day_filter(self):
        _, _, clauses, params = server.crop_filters({"from": ["2026-10-01"], "to": ["2026-10-06"]})
        self.assertEqual(params[0].isoformat(), "2026-10-01T00:00:00+00:00")
        self.assertEqual(params[1].isoformat(), "2026-10-07T00:00:00+00:00")
        self.assertIn("timestamptz", clauses[0])

    def test_image_rechecks_lifecycle_and_missing_row_denies_disk_access(self):
        with patch.object(server, "read_image") as read:
            with self.assertRaises(server.InspectorError) as error:
                self.store.image((INSTALLATION, 0, CROP))
            self.assertEqual(error.exception.status, 404)
            read.assert_not_called()
        sql, params = self.calls[-1]
        self.assertEqual(params, (INSTALLATION, 0, CROP))
        for condition in ("m.expires >", "t.deleted_through", "a.state<>'granted'"):
            self.assertIn(condition, sql)

    def test_default_report_user_and_redacted_database_errors(self):
        with patch.dict(server.os.environ, {}, clear=True):
            self.assertEqual(server.arguments([]).db_user, "youspeed_report")
        error = Exception("postgresql://user:password@private-host/db")
        self.assertNotIn("password@", str(server.database_error(error)))


class HTTPTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        class Store:
            def status(self):
                return {"database": "youspeed", "user": "youspeed_report", "media_available": True}

            def list(self, query):
                server.crop_filters(query)
                return {"crops": [], "has_more": False}

            def devices(self):
                return {"devices": [{"installation": INSTALLATION, "crop_count": 228, "platforms": ["ios"]}]}

            def image(self, identity):
                raise server.InspectorError("Crop zurückgezogen.", 404)

        cls.http = server.ThreadingHTTPServer(("127.0.0.1", 0), server.InspectorHandler)
        cls.host = f"127.0.0.1:{cls.http.server_port}"
        cls.http.allowed_hosts = {cls.host}
        cls.http.store = Store()
        cls.thread = threading.Thread(target=cls.http.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.http.shutdown()
        cls.http.server_close()
        cls.thread.join()

    def request(self, path, headers=None, method="GET"):
        connection = HTTPConnection("127.0.0.1", self.http.server_port, timeout=3)
        connection.request(method, path, headers=headers or {})
        response = connection.getresponse()
        body = response.read()
        connection.close()
        return response, body

    def test_no_browser_login_and_no_cache(self):
        response, body = self.request("/inspector/api/crops/status")
        self.assertEqual(response.status, 200)
        self.assertEqual(json.loads(body)["user"], "youspeed_report")
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertNotIn("Set-Cookie", response.headers)
        response, body = self.request("/inspector/api/crops/status", method="HEAD")
        self.assertEqual(response.status, 200)
        self.assertEqual(body, b"")

    def test_invalid_host_or_cross_origin_denied(self):
        for headers in ({"Host": "attacker.invalid"}, {"Origin": "https://attacker.invalid"}, {"Sec-Fetch-Site": "cross-site"}):
            with self.subTest(headers=headers):
                response, _ = self.request("/inspector/api/crops/status", headers)
                self.assertEqual(response.status, 403)

    def test_device_source_endpoint_is_read_only_and_not_cached(self):
        response, body = self.request("/inspector/api/crops/devices")
        self.assertEqual(response.status, 200)
        self.assertEqual(response.headers["Cache-Control"], "no-store")
        self.assertEqual(json.loads(body)["devices"][0]["installation"], INSTALLATION)
        response, _ = self.request("/inspector/api/crops/devices?installation=bad")
        self.assertEqual(response.status, 400)

    def test_static_inspector_works_without_exposing_server_secrets(self):
        response, body = self.request("/inspector/")
        self.assertEqual(response.status, 200)
        self.assertIn(b"crops-workspace", body)
        for path in ("/inspector/server.py", "/.git/config", "/.env", "/shared/tsr/local-data/private.png", "/inspector/logs/"):
            with self.subTest(path=path):
                response, _ = self.request(path)
                self.assertEqual(response.status, 404)

    def test_deleted_image_and_bad_input_return_json_errors(self):
        response, body = self.request(IMAGE_PATH)
        self.assertEqual(response.status, 404)
        self.assertIn("zurückgezogen", json.loads(body)["error"])
        response, _ = self.request("/inspector/api/crops?limit=999999")
        self.assertEqual(response.status, 400)
        response, _ = self.request("/inspector/api/crops/x/0/y/image")
        self.assertEqual(response.status, 400)


if __name__ == "__main__":
    unittest.main()
