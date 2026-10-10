"""HTTP contract and origin gates for the local decoder; no private video evidence."""
from http.client import HTTPConnection
import importlib.util
import json
from pathlib import Path
import threading
import unittest
from unittest.mock import Mock

SPEC = importlib.util.spec_from_file_location("inspector_server", Path(__file__).resolve().parents[2] / "inspector/server.py")
server = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(server)
TOKEN = "a" * 32


class LaneAPITests(unittest.TestCase):
    def setUp(self):
        self.http = server.ThreadingHTTPServer(("127.0.0.1", 0), server.InspectorHandler)
        self.host = f"127.0.0.1:{self.http.server_port}"
        self.http.allowed_hosts = {self.host}
        self.http.lane_videos = Mock()
        self.http.lane_videos.upload.return_value = {"session": TOKEN}
        self.http.lane_videos.frame.return_value = b"synthetic-png"
        self.thread = threading.Thread(target=self.http.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.http.server_close)
        self.addCleanup(self.http.shutdown)

    def request(self, path, method="GET", body=None, headers=None):
        conn = HTTPConnection(self.host)
        conn.request(method, path, body=body, headers=headers or {})
        response = conn.getresponse()
        data = response.read()
        conn.close()
        return response, data

    def test_local_upload_frame_and_delete(self):
        headers = {"Origin":"http://"+self.host, "Content-Type":"application/octet-stream", "X-Video-Name":"drive.mp4"}
        response, data = self.request("/inspector/api/lanes/video", "POST", b"video", headers)
        self.assertEqual(response.status,200)
        self.assertEqual(json.loads(data)["session"],TOKEN)
        self.assertEqual(self.http.lane_videos.upload.call_args.args[1:],(5,"drive.mp4"))
        response, data = self.request(f"/inspector/api/lanes/video/{TOKEN}/frames/42")
        self.assertEqual(response.status,200)
        self.assertEqual(response.getheader("Content-Type"),"image/png")
        self.assertEqual(response.getheader("Cache-Control"),"no-store")
        self.assertEqual(data,b"synthetic-png")
        self.http.lane_videos.frame.assert_called_once_with(TOKEN,42)
        response, _ = self.request(f"/inspector/api/lanes/video/{TOKEN}","DELETE",headers={"Origin":"http://"+self.host})
        self.assertEqual(response.status,200)
        self.http.lane_videos.delete.assert_called_once_with(TOKEN)

    def test_cross_origin_and_missing_origin_cannot_upload(self):
        for headers in ({}, {"Origin":"https://example.com"}, {"Origin":"http://"+self.host,"Sec-Fetch-Site":"cross-site"}):
            response, _ = self.request("/inspector/api/lanes/video","POST",b"video",headers)
            self.assertEqual(response.status,403)
        self.http.lane_videos.upload.assert_not_called()

    def test_remote_decoder_unavailable_and_bad_routes_rejected(self):
        response, _ = self.request("/inspector/api/lanes/video/../../etc/passwd/frames/0")
        self.assertEqual(response.status,404)
        response, _ = self.request(f"/inspector/api/lanes/video/{TOKEN}/frames/0?path=secret")
        self.assertEqual(response.status,400)
        self.http.lane_videos = None
        response, _ = self.request(f"/inspector/api/lanes/video/{TOKEN}/frames/0")
        self.assertEqual(response.status,503)

    def test_post_does_not_change_backend_crop_routes(self):
        response, _ = self.request("/inspector/api/crops","POST",b"video",{"Origin":"http://"+self.host})
        self.assertEqual(response.status,404)
