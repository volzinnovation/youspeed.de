"""Inspector has no implicit write authority; review credentials are per request."""
from http.client import HTTPConnection
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import threading
import unittest

from inspector.crop_review_proxy import CropReviewProxy, ReviewProxyError
from inspector.server import InspectorHandler

TOKEN = "x" * 40


class ProxyTests(unittest.TestCase):
    def setUp(self):
        test = self
        self.calls = []
        self.reply_status = 200
        self.reply = {"state": "recorded"}

        class Upstream(BaseHTTPRequestHandler):
            def do_POST(self):
                test.calls.append((self.path, self.headers.get("Authorization"), json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                self.send_response(test.reply_status)
                self.send_header("Location", "http://127.0.0.1:1/secret")
                self.end_headers()
                self.wfile.write(json.dumps(test.reply).encode())
            def log_message(self, *_):
                pass

        self.upstream = ThreadingHTTPServer(("127.0.0.1", 0), Upstream)
        self.thread = threading.Thread(target=self.upstream.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.upstream.server_close)
        self.addCleanup(self.upstream.shutdown)
        self.proxy = CropReviewProxy(f"http://127.0.0.1:{self.upstream.server_port}")

    def test_fixed_route_and_explicit_bearer(self):
        self.assertEqual(self.proxy.request("save", {"decision": {"request_id": "example"}}, "Bearer " + TOKEN), {"state": "recorded"})
        self.assertEqual(self.calls, [("/youspeed/reports/v1/decisions/crop-reviews", "Bearer " + TOKEN, {"decision": {"request_id": "example"}})])

    def test_missing_malformed_credentials_never_reach_upstream(self):
        for token in (None, "", "Bearer short", "Basic " + TOKEN, "Bearer " + TOKEN + "\r\nX: bad"):
            with self.subTest(token=token), self.assertRaises(ReviewProxyError) as error:
                self.proxy.request("save", {}, token)
            self.assertEqual(error.exception.status, 401)
        self.assertEqual(self.calls, [])

    def test_backend_errors_are_sanitized_and_conflict_preserved(self):
        self.reply_status, self.reply = 409, {"error": "private database URL or token"}
        with self.assertRaises(ReviewProxyError) as error:
            self.proxy.request("save", {}, "Bearer " + TOKEN)
        self.assertEqual(error.exception.status, 409)
        self.assertNotIn("private database", str(error.exception))

    def test_redirect_does_not_forward_bearer(self):
        self.reply_status = 307
        with self.assertRaises(ReviewProxyError) as error:
            self.proxy.request("history", {}, "Bearer " + TOKEN)
        self.assertEqual(error.exception.status, 502)
        self.assertEqual(len(self.calls), 1)

    def test_remote_plaintext_credentials_and_userinfo_urls_rejected(self):
        for url in ("http://example.com", "https://user:pass@example.com", "https://example.com/path", "https://example.com?key=abc", "file:///private/secret"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                CropReviewProxy(url)

    def test_unknown_action_and_non_object_reply(self):
        with self.assertRaises(ReviewProxyError):
            self.proxy.request("https://example.com", {}, "Bearer " + TOKEN)
        self.assertEqual(self.calls, [])
        self.reply = []
        with self.assertRaises(ReviewProxyError) as error:
            self.proxy.request("history", {}, "Bearer " + TOKEN)
        self.assertEqual(error.exception.status, 502)


class InspectorWriteTests(unittest.TestCase):
    def setUp(self):
        test = self
        self.calls = []
        class Proxy:
            configured = True
            def request(self, action, payload, authorization):
                if authorization != "Bearer " + TOKEN:
                    raise ReviewProxyError("Unauthorized", 401)
                test.calls.append((action, payload))
                return {"state": "recorded"}
        self.http = ThreadingHTTPServer(("127.0.0.1", 0), InspectorHandler)
        self.http.review_proxy = Proxy()
        self.host = f"127.0.0.1:{self.http.server_port}"
        self.http.allowed_hosts = {self.host}
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)

    def post(self, body=b'{}', extra=None, path="/inspector/api/crops/review/save"):
        c = HTTPConnection("127.0.0.1", self.http.server_port, timeout=5)
        headers = {"Content-Type": "application/json", "Authorization": "Bearer " + TOKEN}
        headers.update(extra or {})
        c.request("POST", path, body=body, headers=headers)
        r = c.getresponse()
        status, data = r.status, r.read()
        c.close()
        return status, data

    def test_same_origin_save_and_history(self):
        self.assertEqual(self.post(b'{"decision":{"request_id":"a"}}', {"Origin": "http://" + self.host})[0], 200)
        self.assertEqual(self.calls, [("save", {"decision": {"request_id": "a"}})])
        self.assertEqual(self.post(path="/inspector/api/crops/review/history")[0], 200)

    def test_cross_site_or_missing_bearer_cannot_write(self):
        for extra in ({"Origin": "https://evil.example"}, {"Sec-Fetch-Site": "cross-site"}, {"Host": "evil.example"}, {"Authorization": ""}):
            with self.subTest(extra=extra):
                self.assertIn(self.post(extra=extra)[0], (401, 403))
        self.assertEqual(self.calls, [])

    def test_only_bounded_json_objects_accepted(self):
        for body in (b'[]', b'{"value":NaN}', b'{bad', b'{}' * (128 * 1024)):
            with self.subTest(body_length=len(body)):
                self.assertIn(self.post(body)[0], (400, 413))
        self.assertEqual(self.post(extra={"Content-Type": "text/plain"})[0], 415)
        self.assertEqual(self.calls, [])

    def test_unknown_endpoint_or_query_never_proxied(self):
        for path in ("/inspector/api/crops/review/save?url=https://evil.example", "/inspector/api/crops/review/delete", "/inspector/api/crops"):
            self.assertEqual(self.post(path=path)[0], 404)
        self.assertEqual(self.calls, [])


if __name__ == "__main__":
    unittest.main()
