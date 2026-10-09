"""Private fit loading, per-load source binding and geographic pruning."""

from contextlib import contextmanager
from copy import deepcopy
from http.client import HTTPConnection
import json
from pathlib import Path
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
from uuid import uuid4

from inspector import server
from inspector import sign_positions as positions

ROOT = Path(__file__).resolve().parents[2]


def example():
    installation, crop, event, session = (str(uuid4()) for _ in range(4))
    manifest = {
        "installation_id": installation,
        "collection_epoch": 0,
        "crop_id": crop,
        "observation_id": event,
        "encoded_sha256": "a" * 64,
        "source_kind": "detector",
        "local_frame_token": "live-upright-1",
    }
    observation = {
        "event_id": event,
        "source_kind": "detector",
        "observer_version": "sighting-observer-1",
        "app": {"platform": "ios", "version": "1", "build": "2"},
        "evidence": {"quality_flags": []},
        "collection_session_id": session,
    }
    member = {
        "installation_id": installation,
        "collection_epoch": 0,
        "crop_id": crop,
        "observation_id": event,
        "encoded_sha256": "a" * 64,
        "manifest_sha256": positions.digest(manifest),
        "observation_sha256": positions.digest(observation),
        "review_revision": 0,
    }
    row = {
        "installation": installation,
        "epoch": 0,
        "crop_id": crop,
        "digest": "a" * 64,
        "manifest": manifest,
        "observation": observation,
        "current_revision": 0,
        "expires": 2000.0,
    }
    case = {
        "label": "Fit 07",
        "classification": {"family": "maximum_speed", "value": 50, "unit": "km/h"},
        "speedLimit": {"family": "wrong", "value": 999, "unit": "mph"},
        "roadIds": [2],
        "nearestRoad": 2,
        "portals": [{"mainline": [1], "incoming": 2, "link": 1}],
        "point": [8, 49],
        "captures": [{"point": [8, 49]}],
    }
    display = {
        "version": 1,
        "cases": [case],
        "roadClasses": ["motorway", "primary"],
        "roads": [
            ["unused", 0, "", "", [1000000, 1000000]],
            ["link", 0, "", "", [8000000, 49000000]],
            ["main", 1, "", "", [8000001, 49000001]],
        ],
        "meta": {"totalSourceFits": 48},
    }
    wrapper = {
        "schema_version": 1,
        "source_policy": positions.SOURCE_POLICY,
        "display_data": display,
        "case_bindings": [{"label": case["label"], "source_members": [member]}],
    }
    return wrapper, row


class Database:
    def __init__(self, rows, *, reviews=False, fresh=True, now=1000):
        self.rows, self.reviews, self.fresh, self.now = rows, reviews, fresh, now
        self.calls = []

    def execute(self, sql, params=None):
        self.calls.append((sql, params))
        return self

    def fetchone(self):
        sql = self.calls[-1][0]
        if "AS fresh" in sql:
            return {"fresh": self.fresh}
        if "to_regclass" in sql:
            return {"reviews": "youspeed.crop_reviews" if self.reviews else None}
        if "clock_timestamp" in sql:
            return {"checked_at": self.now, "controls_refreshed_at": self.now - 100}
        raise AssertionError(sql)

    def fetchall(self):
        return self.rows


class PositionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "private.json"
        self.wrapper, self.row = example()
        self.save()
        self.db = Database([self.row])
        self.crop = server.CropStore(server.arguments([]))

        @contextmanager
        def connection():
            yield self.db

        self.crop.connection = connection
        self.store = positions.SignPositionStore(self.path, self.crop)

    def save(self):
        self.path.write_text(json.dumps(self.wrapper))

    def test_shared_semantic_vectors(self):
        data = json.loads(
            (
                ROOT
                / "shared/tsr/collection-contract-v1/fixtures/semantic-json-v1.json"
            ).read_text()
        )
        vectors = data
        for item in vectors:
            self.assertEqual(
                positions.canonical(item["input"]).decode(), item["canonical"]
            )
            self.assertEqual(positions.digest(item["input"]), item["sha256"])

    def test_valid_sources_no_migration_no_cached_response_and_pruned_geography(self):
        result = self.store.get()
        self.assertEqual(result["cases"][0]["roadIds"], [1])
        self.assertEqual(result["cases"][0]["nearestRoad"], 1)
        self.assertEqual(
            result["cases"][0]["portals"], [{"mainline": [0], "incoming": 1, "link": 0}]
        )
        self.assertEqual([r[0] for r in result["roads"]], ["link", "main"])
        self.assertEqual(
            result["cases"][0]["speedLimit"],
            {"family": "maximum_speed", "value": 50, "unit": "km/h"},
        )
        self.assertEqual(result["meta"]["scope"], "maximum_speed_and_zone_start")
        self.assertNotIn("case_bindings", result)
        text = json.dumps(result)
        for field in (
            "installation_id",
            "encoded_sha256",
            "manifest_sha256",
            "observation_sha256",
        ):
            self.assertNotIn(field, text)
        self.db.rows = []
        self.assertEqual(self.store.get()["cases"], [])
        self.assertEqual(self.store.get()["roads"], [])

    def test_every_dependency_required_including_nonidentity_support(self):
        _, support = example()
        member = deepcopy(self.wrapper["case_bindings"][0]["source_members"][0])
        member.update(
            installation_id=support["installation"],
            crop_id=support["crop_id"],
            observation_id=support["observation"]["event_id"],
            manifest_sha256=positions.digest(support["manifest"]),
            observation_sha256=positions.digest(support["observation"]),
        )
        self.wrapper["case_bindings"][0]["source_members"].append(member)
        self.save()
        self.assertEqual(self.store.get()["cases"], [])
        self.db.rows.append(support)
        self.assertEqual(len(self.store.get()["cases"]), 1)

    def test_changed_manifest_event_digest_identity_review_or_expiry_withholds(self):
        original = deepcopy(self.row)
        for change in (
            "manifest",
            "event",
            "digest",
            "identity",
            "review",
            "expiry",
            "replay",
        ):
            self.db.rows = [deepcopy(original)]
            row = self.db.rows[0]
            if change == "manifest":
                row["manifest"]["local_frame_token"] = "another-live-frame"
            elif change == "event":
                row["observation"]["app"]["build"] = "3"
            elif change == "digest":
                row["digest"] = "b" * 64
            elif change == "identity":
                row["manifest"]["crop_id"] = str(uuid4())
            elif change == "review":
                row["current_revision"] = 1
                self.db.reviews = True
            elif change == "expiry":
                row["expires"] = 1000
            elif change == "replay":
                row["observation"]["evidence"]["quality_flags"] = ["archive_replay"]
            with self.subTest(change=change):
                result = self.store.get()
                self.assertEqual(result["cases"], [])
                self.assertEqual(result["roads"], [])

    def test_fresh_controls_fail_closed_and_queries_are_readonly_parameterized(self):
        self.db.fresh = False
        with self.assertRaises(server.InspectorError):
            self.store.get()
        self.db.fresh = True
        self.db.calls = []
        self.store.get()
        sql = "\n".join(q for q, _ in self.db.calls)
        self.assertIn("REPEATABLE READ READ ONLY", sql)
        self.assertIn("t.deleted_through>=m.epoch", sql)
        self.assertIn("a.scope='sign_metadata' AND a.state='granted'", sql)
        self.assertIn("a.scope='crop_storage' AND a.state='granted'", sql)
        self.assertNotIn(self.row["crop_id"], sql)
        self.assertNotIn("youspeed.crop_reviews rr", sql)
        self.db.reviews = True
        self.store.get()
        self.assertTrue(any("youspeed.crop_reviews rr" in q for q, _ in self.db.calls))

    def test_speed_semantics_defense_and_zone_start(self):
        for family, value, unit, expected in [
            ("maximum_speed", 50, "km/h", 1),
            ("zone_start", 30, "km/h", 1),
            ("zone_end", 30, "km/h", 0),
            ("maximum_speed", None, "km/h", 0),
            ("maximum_speed", True, "km/h", 0),
            ("maximum_speed", 0, "km/h", 0),
            ("maximum_speed", 50, "mph", 0),
        ]:
            self.wrapper["display_data"]["cases"][0]["classification"] = {
                "family": family,
                "value": value,
                "unit": unit,
            }
            self.save()
            self.assertEqual(len(self.store.get()["cases"]), expected)

    def test_live_scope_does_not_scan_arbitrary_description_text(self):
        self.row["observation"]["reason"] = "archive discussion"
        self.assertTrue(
            positions.live_source(self.row["manifest"], self.row["observation"])
        )
        self.row["observation"]["collection_session_id"] = "unknown"
        self.assertFalse(
            positions.live_source(self.row["manifest"], self.row["observation"])
        )

    def test_invalid_wrapper_duplicate_json_symlink_road_and_binding_rejected(self):
        original = deepcopy(self.wrapper)
        for change in (
            "missing-binding",
            "extra-binding",
            "road",
            "duplicate-source",
            "hash",
            "extra-private-case-field",
        ):
            self.wrapper = deepcopy(original)
            if change == "missing-binding":
                self.wrapper["case_bindings"] = []
            elif change == "extra-binding":
                self.wrapper["case_bindings"] *= 2
            elif change == "road":
                self.wrapper["display_data"]["cases"][0]["roadIds"] = [99]
            elif change == "duplicate-source":
                self.wrapper["case_bindings"][0]["source_members"] *= 2
            elif change == "hash":
                self.wrapper["case_bindings"][0]["source_members"][0][
                    "manifest_sha256"
                ] = "x"
            elif change == "extra-private-case-field":
                self.wrapper["display_data"]["cases"][0]["crop_id"] = "forbidden"
            self.save()
            with (
                self.subTest(change=change),
                self.assertRaises(positions.SignPositionsError),
            ):
                positions.load(self.path)
        self.path.write_text('{"x":1,"x":2}')
        with self.assertRaises(positions.SignPositionsError):
            positions.load(self.path)
        target = self.path.with_name("link.json")
        target.symlink_to(self.path)
        with self.assertRaises(positions.SignPositionsError):
            positions.load(target)
        with self.assertRaises(positions.SignPositionsError):
            positions.load(ROOT / "inspector/example.json")


class HttpTests(unittest.TestCase):
    def setUp(self):
        self.http = server.ThreadingHTTPServer(
            ("127.0.0.1", 0), server.InspectorHandler
        )
        self.http.allowed_hosts = {f"127.0.0.1:{self.http.server_port}"}
        self.calls = 0
        test = self

        class Store:
            def get(self):
                test.calls += 1
                return {
                    "version": 1,
                    "cases": [],
                    "roads": [],
                    "meta": {"scope": "maximum_speed_and_zone_start"},
                }

        self.http.sign_positions = Store()
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)

    def close(self):
        self.http.shutdown()
        self.http.server_close()
        self.thread.join()

    def request(self, path, method="GET"):
        c = HTTPConnection("127.0.0.1", self.http.server_port, timeout=3)
        c.request(method, path)
        r = c.getresponse()
        body = r.read()
        c.close()
        return r, body

    def test_endpoint_aliases_no_store_head_and_query_rejection(self):
        for endpoint in ("/api/sign-positions", "/inspector/api/sign-positions"):
            r, body = self.request(endpoint)
            self.assertEqual(r.status, 200)
            self.assertEqual(r.headers["Cache-Control"], "no-store")
            self.assertEqual(json.loads(body)["cases"], [])
            r, body = self.request(endpoint, method="HEAD")
            self.assertEqual(r.status, 200)
            self.assertEqual(body, b"")
            self.assertEqual(self.request(endpoint + "?raw=true")[0].status, 400)
        self.assertEqual(self.calls, 4)

    def test_missing_or_unavailable_source_fails_closed(self):
        self.http.sign_positions = None
        self.assertEqual(self.request("/api/sign-positions")[0].status, 503)

        def unavailable():
            raise positions.SignPositionsError("Daten nicht verfügbar.")

        self.http.sign_positions = SimpleNamespace(get=unavailable)
        r, body = self.request("/api/sign-positions")
        self.assertEqual(r.status, 503)
        self.assertNotIn(b"cases", body)

    def test_file_option_environment(self):
        with patch.dict(
            "os.environ", {"YOUSPEED_SIGN_POSITIONS_FILE": "/private/export.json"}
        ):
            self.assertEqual(
                server.arguments([]).sign_positions_file, Path("/private/export.json")
            )
        self.assertEqual(
            server.arguments(
                ["--sign-positions-file", "/private/other.json"]
            ).sign_positions_file,
            Path("/private/other.json"),
        )


if __name__ == "__main__":
    unittest.main()
