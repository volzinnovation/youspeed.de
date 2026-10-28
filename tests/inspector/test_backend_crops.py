"""Read-only crop API, private asset access and stored-image integrity checks."""
from contextlib import contextmanager
import hashlib
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler
import importlib.util
import json
import sqlite3
from pathlib import Path
import io
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch

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
        self.store.has_panoramax = lambda db: False
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
                if "pg_try_advisory" in test.calls[-1][0]:
                    return {"acquired": True}
                if "AS fresh" in test.calls[-1][0]:
                    return test.control
                return test.rows[0] if test.rows else None

        @contextmanager
        def connection():
            yield Database()

        self.store.connection = connection

    def image_proxy(self):
        test = self
        self.proxy_calls = []
        self.proxy_payload = PNG
        self.proxy_status = 200
        self.proxy_on_get = None

        class Upstream(BaseHTTPRequestHandler):
            def do_GET(self):
                test.proxy_calls.append((self.path, self.headers.get("Authorization")))
                if test.proxy_on_get:
                    test.proxy_on_get()
                self.send_response(test.proxy_status)
                self.send_header("Location", f"http://127.0.0.1:{self.server.server_port}/redirect-target")
                self.end_headers()
                try:
                    self.wfile.write(test.proxy_payload)
                except (BrokenPipeError, ConnectionResetError):
                    pass

            def log_message(self, *_):
                pass

        upstream = server.ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        thread = threading.Thread(target=upstream.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(thread.join)
        self.addCleanup(upstream.server_close)
        self.addCleanup(upstream.shutdown)
        origin = f"http://127.0.0.1:{upstream.server_port}"
        args = server.arguments(["--mobile-image-proxy-url", origin])
        store = server.CropStore(args)
        store.connection = self.store.connection
        return store

    def public_panoramax_fixture(self, enabled=True, bridge=True):
        self.store.panoramax_public_image_fallback = enabled
        self.store.args.panoramax_image_proxy_url = "http://127.0.0.1:18082" if bridge else None
        row = {"picture_id": CROP, "annotation_id": INSTALLATION, "source_item": {"picture": {}},
            "feature": {"shape": {}}, "crop_geometry": {"actual_box": [0, 0, 2, 2]},
            "digest": hashlib.sha256(PNG).hexdigest(), "bytes": len(PNG),
            "object_path": "panoramax/crop-objects/sha256/aa/" + "a" * 64 + ".png"}
        self.rows = [row]
        module = types.ModuleType("commercial_backend.youspeed.panoramax_public_images")
        class PublicCropError(Exception):
            def __init__(self, message, status):
                self.message, self.status = message, status
        module.PublicCropError = PublicCropError
        module.reconstruct_public_crop = Mock(return_value=PNG)
        overlay = patch.dict(server.sys.modules, {module.__name__: module})
        overlay.start(); self.addCleanup(overlay.stop)
        return row, module

    @staticmethod
    def unavailable_panoramax_bridge():
        return types.SimpleNamespace(open=Mock(side_effect=server.urllib.error.HTTPError(
            "http://127.0.0.1:18082/private", 503, "unavailable", {}, io.BytesIO(b"unavailable"))))

    def test_statistics_cli_does_not_require_gallery_media_options(self):
        from scripts.inspector.sign_statistics import arguments as report_arguments
        store = server.CropStore(report_arguments([]))
        self.assertIsNone(store.media_root)
        self.assertIsNone(store.panoramax_root)
        self.assertIsNone(store.mapping_digest)

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
                      {"class": ["x" * 161]}, {"class": ["bad", "bad:round"]},
                      {"installation": [INSTALLATION, CROP]}):
            with self.subTest(query=query), self.assertRaises(server.InspectorError):
                self.store.list(query)
        self.assertEqual(self.calls, [])

    def test_exact_class_is_parameterized_and_combines_with_other_filters(self):
        self.store.list({"class": ["  ' OR TRUE --  "], "country": ["DE"],
                         "query": ["465bad98"], "offset": ["50"]})
        sql, params = self.calls[-1]
        self.assertNotIn("' OR TRUE --", sql)
        self.assertEqual(params[:3], ["DE", "' or true --", "' or true --"])
        self.assertEqual(params[3:-2], ["465bad98"] * 4)
        self.assertEqual(params[-2:], [51, 50])

    def test_exact_bad_class_excludes_uuid_substrings_and_subclasses(self):
        # Execute the generated JSON/equality predicate against synthetic rows.
        # SQLite supports the same JSON operators used by this filter.
        with sqlite3.connect(":memory:") as db:
            db.execute("CREATE TABLE events (crop_id TEXT, payload TEXT)")
            fixtures = [
                ("model-match", {"country": "DE", "model_label": "bad"}),
                ("canonical-match", {"country": "DE", "canonical_code": "bad"}),
                ("465bad98-c093-404b-9a47-8f19c833f988", {"country": "DE", "model_label": "Maximum speed 70 km/h"}),
                ("subclass", {"country": "DE", "model_label": "bad:round"}),
                ("other-country", {"country": "CH", "model_label": "bad"}),
                ("missing-class", {"country": "DE"}),
            ]
            db.executemany("INSERT INTO events VALUES (?, ?)", [
                (crop_id, json.dumps({"event": {"classification": classification}}))
                for crop_id, classification in fixtures
            ])
            _, _, clauses, params = server.crop_filters({"class": [" BAD "], "country": ["DE"]})
            sql = "SELECT e.crop_id FROM events e WHERE " + " AND ".join(clauses)
            matches = {row[0] for row in db.execute(sql.replace("%s", "?"), params)}
            self.assertEqual(matches, {"model-match", "canonical-match"})
            # Empty input imposes no class restriction.
            self.assertEqual(server.crop_filters({"class": ["  "]})[2:], ([], []))

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

    def test_panoramax_device_filters_are_separate_from_phone_installations(self):
        for device in ("panoramax", "panoramax:panoramax.woladen.de"):
            _, _, clauses, params = server.crop_filters({"installation": [device]})
            self.assertIn("FALSE", clauses)
            self.assertEqual(params, [])
        clauses, params = self.store.panoramax_filters({"installation": ["panoramax:panoramax.woladen.de"]})
        self.assertEqual(clauses, ["f.source_id=%s"])
        self.assertEqual(params, ["panoramax.woladen.de"])
        self.assertIn("FALSE", self.store.panoramax_filters({"installation": [INSTALLATION]})[0])
        for value in ("panoramax:x/../../", "panoramax:", "panoramax:not a host"):
            with self.assertRaises(server.InspectorError):
                server.crop_filters({"installation": [value]})

    def test_panoramax_exact_class_and_country_match_the_same_current_label(self):
        self.store.mapping_digest = "current-mapping"
        sql, params = self.store.panoramax_sql({"source": ["panoramax"], "class": [" BAD "], "country": ["DE"]})
        self.assertIn("EXISTS (SELECT 1 FROM youspeed.panoramax_class_labels", sql)
        self.assertIn("l.fingerprint=f.fingerprint", sql)
        self.assertIn("l.mapping_sha256=%s", sql)
        self.assertIn("l.label#>>'{selected_yolo,label}'", sql)
        self.assertIn("l.label->>'target_classifier_country'=%s", sql)
        self.assertEqual(params, ["current-mapping", "current-mapping", "DE", "bad"])
        self.assertNotIn("bad", sql)
        for condition in ("f.current_render", "f.state='ready'", "i.active", "s.visibility_scope", "panoramax_suppressions"):
            self.assertIn(condition, sql)

    def test_panoramax_combined_gallery_paginates_once_and_preserves_source_identity(self):
        self.store.has_panoramax = lambda db: True
        self.rows = [{"record": {"source": "panoramax", "crop_id": CROP}}]
        result = self.store.list({"source": ["panoramax"], "offset": ["50"], "limit": ["2"]})
        sql, params = self.calls[-1]
        self.assertIn("UNION ALL", sql)
        self.assertEqual(sql.count("OFFSET"), 1)
        self.assertEqual(params[-2:], [3, 50])
        row = result["crops"][0]
        self.assertNotIn("installation", row)
        self.assertEqual(row["image_url"], f"/inspector/api/panoramax/crops/{CROP}/image")

    def test_exact_reviewed_class_combines_with_phone_way_and_context(self):
        way = "9007199254740993"
        self.store.list({"class": [" DE:274-30 "], "class_source": ["reviewed"],
                         "phone_way_id": [way], "review_state": ["wrong_class"],
                         "exit_context": ["near_exit"], "query": ["crop-id"], "offset": ["50"]})
        sql, params = self.calls[-1]
        self.assertIn("WHEN r.verdict='wrong_class' THEN r.corrected_classification ELSE NULL END)->>'canonical_code',''))=%s", sql)
        self.assertIn("->>'osm_way_id'=%s", sql)
        self.assertIn("c.status=%s", sql)
        self.assertLess(sql.index("c.status=%s"), sql.rindex(" LIMIT "))
        self.assertNotIn(way, sql)
        self.assertEqual(params, [way, "de:274-30", "de:274-30", "wrong_class", "near_exit",
                                  "crop-id", "crop-id", "crop-id", "crop-id", 51, 50])

    def test_mobile_review_and_sequence_filters_never_admit_unfiltered_panoramax_rows(self):
        for extra in ({"review_state": ["confirmed"]}, {"exit_context": ["near_exit"]},
                      {"class_source": ["reviewed"]}, {"phone_way_id": ["123"]},
                      {"installation": [INSTALLATION], "observation_id": [CROP], "collection_epoch": ["0"]}):
            with self.subTest(extra=extra):
                clauses, _ = self.store.panoramax_filters({"class": ["bad"], **extra})
                self.assertIn("FALSE", clauses)
        clauses, _ = self.store.panoramax_filters({"class": ["bad"], "country": ["DE"], "scope": ["live"]})
        self.assertNotIn("FALSE", clauses)

    def test_panoramax_unavailable_image_never_reads_storage(self):
        # An admitted request still checks current lifecycle before any disk/API read.
        self.rows = [{"acquired": True}]
        calls = self.calls
        class Database:
            def execute(self, sql, params=None):
                calls.append((sql, params))
                self.row = {"acquired": True} if "pg_try_advisory" in sql else None
                return self
            def fetchone(self):
                return self.row
        @contextmanager
        def connection():
            yield Database()
        self.store.connection = connection
        with patch.object(server, "read_image") as read:
            with self.assertRaises(server.InspectorError) as error:
                self.store.panoramax_image(CROP)
            self.assertEqual(error.exception.status, 404)
            read.assert_not_called()
        self.assertIn("panoramax_suppressions", calls[-1][0])

    def test_public_panoramax_fallback_verifies_png_and_rechecks_current_source_after_bridge_503(self):
        row, helper = self.public_panoramax_fixture()
        with patch.object(server.urllib.request, "build_opener", return_value=self.unavailable_panoramax_bridge()), patch.object(server, "read_image") as disk:
            self.assertEqual(self.store.panoramax_image(CROP), (PNG, "image/png"))
            disk.assert_not_called()
        helper.reconstruct_public_crop.assert_called_once_with({key: row[key] for key in server.PANORAMAX_IMAGE_BINDING})
        self.assertEqual(len(self.calls), 3)  # Shared lock, initial eligibility, post-fetch eligibility.
        for sql, params in self.calls[1:]:
            self.assertEqual(params, (CROP,))
            for condition in ("f.active", "i.active", "visibility='anyone'", "panoramax_suppressions"):
                self.assertIn(condition, sql)

    def test_public_panoramax_fallback_rejects_revocation_after_public_fetch(self):
        _, helper = self.public_panoramax_fixture(bridge=False)
        def reconstruct(_):
            self.rows = []
            return PNG
        helper.reconstruct_public_crop.side_effect = reconstruct
        with self.assertRaises(server.InspectorError) as error:
            self.store.panoramax_image(CROP)
        self.assertEqual(error.exception.status, 404)
        self.assertIn("Öffentliches Panoramax-Bild", str(error.exception))

    def test_public_panoramax_fallback_rejects_corrupt_bytes_and_changed_render_binding(self):
        for changed_row in (False, True):
            with self.subTest(changed_row=changed_row):
                row, helper = self.public_panoramax_fixture(bridge=False)
                def reconstruct(_):
                    if changed_row:
                        self.rows = [{**row, "crop_geometry": {"actual_box": [1, 0, 3, 2]}}]
                        return PNG
                    return PNG + b"changed"
                helper.reconstruct_public_crop.side_effect = reconstruct
                with self.assertRaises(server.InspectorError) as error:
                    self.store.panoramax_image(CROP)
                self.assertEqual(error.exception.status, 422)
                self.assertIn("Öffentliches Panoramax-Bild", str(error.exception))

    def test_public_panoramax_fallback_requires_explicit_flag(self):
        for bridge in (False, True):
            with self.subTest(bridge=bridge):
                _, helper = self.public_panoramax_fixture(enabled=False, bridge=bridge)
                with patch.object(server.urllib.request, "build_opener", return_value=self.unavailable_panoramax_bridge()):
                    with self.assertRaises(server.InspectorError) as error:
                        self.store.panoramax_image(CROP)
                self.assertEqual(error.exception.status, 503)
                helper.reconstruct_public_crop.assert_not_called()

    def test_public_panoramax_fallback_prefers_healthy_bridge_and_does_not_mask_bridge_denial(self):
        _, helper = self.public_panoramax_fixture()
        bridge = types.SimpleNamespace(open=Mock(return_value=io.BytesIO(PNG)))
        with patch.object(server.urllib.request, "build_opener", return_value=bridge):
            self.assertEqual(self.store.panoramax_image(CROP), (PNG, "image/png"))
        helper.reconstruct_public_crop.assert_not_called()
        self.assertEqual(len(self.calls), 2)
        bridge.open.side_effect = server.urllib.error.HTTPError("http://127.0.0.1/private", 403, "forbidden", {}, io.BytesIO(b"forbidden"))
        with patch.object(server.urllib.request, "build_opener", return_value=bridge):
            with self.assertRaises(server.InspectorError):
                self.store.panoramax_image(CROP)
        helper.reconstruct_public_crop.assert_not_called()

    def test_public_panoramax_fallback_is_explicit_cli_option_and_prefixes_helper_errors(self):
        self.assertFalse(server.arguments([]).panoramax_public_image_fallback)
        self.assertTrue(server.arguments(["--panoramax-public-image-fallback"]).panoramax_public_image_fallback)
        _, helper = self.public_panoramax_fixture(bridge=False)
        helper.reconstruct_public_crop.side_effect = helper.PublicCropError("Öffentliche Aufnahme nicht mehr verfügbar.", 404)
        with self.assertRaises(server.InspectorError) as error:
            self.store.panoramax_image(CROP)
        self.assertEqual(error.exception.status, 404)
        self.assertTrue(str(error.exception).startswith("Öffentliches Panoramax-Bild:"))

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

    def test_mobile_proxy_preserves_current_db_verified_png_and_jpeg_without_disk_access(self):
        store = self.image_proxy()
        for payload, encoding, content_type in [(PNG, "PNG", "image/png"),
                (b"\xff\xd8\xffsynthetic JPEG", "JPEG", "image/jpeg")]:
            with self.subTest(encoding=encoding):
                self.proxy_payload = payload
                row = media_row(payload)
                row["manifest"]["encoding"] = encoding
                self.rows = [row]
                with patch.object(server, "read_image") as read:
                    self.assertEqual(store.image((INSTALLATION, 0, CROP)), (payload, content_type))
                    read.assert_not_called()
        self.assertEqual(self.proxy_calls, [(IMAGE_PATH, None), (IMAGE_PATH, None)])

    def test_mobile_proxy_rejects_hash_length_manifest_and_image_format_mismatches(self):
        store = self.image_proxy()
        fixtures = []
        fixtures.append((PNG + b"changed", media_row()))
        row = media_row(); row["manifest"]["byte_length"] += 1
        fixtures.append((PNG, row))
        row = media_row(); row["manifest"]["encoded_sha256"] = "0" * 64
        fixtures.append((PNG, row))
        fixtures.append((b"<html>not an image</html>", media_row(b"<html>not an image</html>")))
        row = media_row(); row["manifest"]["encoding"] = "JPEG"
        fixtures.append((PNG, row))
        for payload, row in fixtures:
            with self.subTest(payload=payload, manifest=row["manifest"]):
                self.proxy_payload, self.rows = payload, [row]
                with self.assertRaises(server.InspectorError) as error:
                    store.image((INSTALLATION, 0, CROP))
                self.assertEqual(error.exception.status, 422)

    def test_mobile_proxy_bounds_image_bytes_even_when_database_claims_larger_valid_object(self):
        store = self.image_proxy()
        self.proxy_payload = PNG + b"x" * server.MAX_IMAGE_BYTES
        self.rows = [media_row(self.proxy_payload)]
        with self.assertRaises(server.InspectorError) as error:
            store.image((INSTALLATION, 0, CROP))
        self.assertEqual(error.exception.status, 422)

    def test_mobile_proxy_rechecks_lifecycle_on_every_request_before_network_access(self):
        store = self.image_proxy()
        self.rows = [media_row()]
        self.assertEqual(store.image((INSTALLATION, 0, CROP))[0], PNG)
        self.rows = []  # Same image has now expired, been deleted or lost authorization.
        with self.assertRaises(server.InspectorError) as error:
            store.image((INSTALLATION, 0, CROP))
        self.assertEqual(error.exception.status, 404)
        self.assertEqual(len(self.proxy_calls), 1)
        self.assertEqual(len(self.calls), 3)
        for sql, params in self.calls:
            self.assertEqual(params, (INSTALLATION, 0, CROP))
            for condition in ("m.expires >", "t.deleted_through", "a.state<>'granted'"):
                self.assertIn(condition, sql)

    def test_mobile_proxy_withholds_bytes_if_revoked_or_expired_during_fetch(self):
        store = self.image_proxy()
        self.rows = [media_row()]
        self.proxy_on_get = self.rows.clear
        with self.assertRaises(server.InspectorError) as error:
            store.image((INSTALLATION, 0, CROP))
        self.assertEqual(error.exception.status, 404)
        self.assertEqual(self.proxy_calls, [(IMAGE_PATH, None)])
        self.assertIn("clock_timestamp()", self.calls[-1][0])

    def test_mobile_proxy_withholds_bytes_if_image_binding_changes_during_fetch(self):
        for field in ("object_path", "digest", "manifest"):
            with self.subTest(field=field):
                store = self.image_proxy()
                self.rows = [media_row()]
                replacement = media_row()
                replacement[field] = {**replacement[field], "changed": True} if field == "manifest" else "changed"
                def replace_row():
                    self.rows = [replacement]
                self.proxy_on_get = replace_row
                with self.assertRaises(server.InspectorError) as error:
                    store.image((INSTALLATION, 0, CROP))
                self.assertEqual(error.exception.status, 422)
                self.assertEqual(self.proxy_calls, [(IMAGE_PATH, None)])

    def test_mobile_proxy_rejects_redirects_without_contacting_the_redirect_target(self):
        store = self.image_proxy()
        self.rows = [media_row()]
        self.proxy_status = 302
        with self.assertRaises(server.InspectorError) as error:
            store.image((INSTALLATION, 0, CROP))
        self.assertEqual(error.exception.status, 502)
        self.assertEqual(self.proxy_calls, [(IMAGE_PATH, None)])
        self.assertNotIn("127.0.0.1", str(error.exception))

    def test_mobile_proxy_configuration_rejects_non_loopback_origins_before_transport_creation(self):
        invalid = ["https://127.0.0.1:8080", "http://example.com", "http://127.0.0.1.evil.test",
            "http://localhost/path", "http://localhost?secret=x", "http://localhost#fragment",
            "http://user:dummy-password@localhost", "http://localhost:bad", "http://localhost:0",
            "http://localhost:65536", "file:///private/image", " http://localhost", "http://localhost\\@example.com"]
        with patch.object(server.urllib.request, "build_opener") as transport:
            for origin in invalid:
                with self.subTest(origin=origin), self.assertRaises(server.InspectorError) as error:
                    server.CropStore(server.arguments(["--mobile-image-proxy-url", origin]))
                self.assertNotIn("secret", str(error.exception))
            transport.assert_not_called()

    def test_mobile_proxy_status_reflects_configuration_without_probe_and_keeps_direct_mount(self):
        with patch.dict(server.os.environ, {"YOUSPEED_MOBILE_IMAGE_PROXY_URL": "http://localhost:18080"}):
            store = server.CropStore(server.arguments([]))
        store.connection = self.store.connection
        self.rows = [{"database": "youspeed", "user": "youspeed_report"}]
        with patch.object(store.mobile_image_opener, "open") as probe:
            self.assertEqual(store.status(), {"database": "youspeed", "user": "youspeed_report", "media_available": True})
            probe.assert_not_called()
        with tempfile.TemporaryDirectory() as directory:
            args = server.arguments(["--media-root", directory, "--mobile-image-proxy-url", ""])
            direct = server.CropStore(args); direct.connection = self.store.connection
            self.assertTrue(direct.status()["media_available"])
            self.rows = [media_row()]
            (Path(directory) / self.rows[0]["object_path"]).write_bytes(PNG)
            self.assertEqual(direct.image((INSTALLATION, 0, CROP)), (PNG, "image/png"))
        self.rows = [{"database": "youspeed", "user": "youspeed_report"}]
        self.assertFalse(direct.status()["media_available"])

    def test_default_report_user_and_redacted_database_errors(self):
        with patch.dict(server.os.environ, {}, clear=True):
            self.assertEqual(server.arguments([]).db_user, "youspeed_report")
        error = Exception("postgresql://user:dummy-password@private-host/db")
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

            def panoramax_image(self, crop_id):
                return PNG, "image/png"

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

    def test_panoramax_images_have_a_separate_uuid_route(self):
        response, body = self.request(f"/inspector/api/panoramax/crops/{CROP}/image")
        self.assertEqual(response.status, 200)
        self.assertEqual(body, PNG)
        self.assertEqual(response.headers["Content-Type"], "image/png")
        response, _ = self.request("/inspector/api/panoramax/crops/not-a-uuid/image")
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
