"""The SSH-only bridge forwards only the current-crop image report operation."""
from contextlib import contextmanager
from http.client import HTTPConnection
import importlib.util
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

SPEC = importlib.util.spec_from_file_location('panoramax_proxy', Path(__file__).resolve().parents[2] / 'inspector/panoramax_image_proxy.py')
proxy = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(proxy)
CROP = '78b247a4-9f14-430d-a3c0-af218a95d101'
IMAGE = b'\x89PNG\r\n\x1a\nsynthetic'


class ProxyTests(unittest.TestCase):
    def setUp(self):
        self.server = proxy.ThreadingHTTPServer(('127.0.0.1', 0), proxy.ImageProxy)
        self.server.token = 'synthetic-test-token'
        self.host = f'127.0.0.1:{self.server.server_port}'
        self.server.allowed_hosts = {self.host}
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.server.shutdown(); self.server.server_close(); self.thread.join()

    def request(self, path, headers=None, method='GET'):
        connection = HTTPConnection('127.0.0.1', self.server.server_port, timeout=3)
        connection.request(method, path, headers=headers or {})
        response = connection.getresponse(); data = response.read(); connection.close()
        return response, data

    def test_only_uuid_image_get_is_forwarded(self):
        @contextmanager
        def response():
            class Body:
                def read(self, limit):
                    return IMAGE
            yield Body()
        with patch.object(proxy, 'build_opener') as opener:
            opener.return_value.open.return_value = response()
            result, data = self.request(f'/inspector/api/panoramax/crops/{CROP}/image')
            self.assertEqual((result.status, data), (200, IMAGE))
            self.assertEqual(result.headers['Cache-Control'], 'no-store')
            request = opener.return_value.open.call_args.args[0]
            self.assertEqual(request.full_url, 'http://127.0.0.1:8022/youspeed/reports/v1/panoramax-image')
            self.assertEqual(request.data, ('{"crop_id": "' + CROP + '"}').encode())
            self.assertNotIn(b'synthetic-test-token', data)
            opener.reset_mock()
            for path, headers, method in [('/other', {}, 'GET'),
                (f'/inspector/api/panoramax/crops/{CROP}/image?path=secret', {}, 'GET'),
                (f'/inspector/api/panoramax/crops/{CROP}/image', {'Host': 'evil.invalid'}, 'GET'),
                (f'/inspector/api/panoramax/crops/{CROP}/image', {'Origin': 'http://evil.invalid'}, 'GET'),
                (f'/inspector/api/panoramax/crops/{CROP}/image', {}, 'POST')]:
                result, _ = self.request(path, headers, method)
                self.assertGreaterEqual(result.status, 400)
            opener.assert_not_called()


if __name__ == '__main__':
    unittest.main()
