#!/usr/bin/env python3
"""Loopback-only, read-only image bridge to the existing Panoramax report API.

Run as the existing service account on volz-db. The operator token stays there;
only this one image operation is exposed to an SSH-forwarded Inspector.
"""
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import re
from urllib.error import HTTPError, URLError
from urllib.request import Request, build_opener, HTTPRedirectHandler
from uuid import UUID

MAX_BYTES = 5 * 1024**2


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args):
        return None


class ImageProxy(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        if self.headers.get('Host') not in self.server.allowed_hosts or self.client_address[0] != '127.0.0.1':
            return self.respond(403, b'Forbidden', 'text/plain')
        if self.headers.get('Origin') or self.headers.get('Sec-Fetch-Site') == 'cross-site':
            return self.respond(403, b'Forbidden', 'text/plain')
        match = re.fullmatch(r'/inspector/api/panoramax/crops/([a-fA-F0-9-]{36})/image', self.path)
        try:
            crop_id = str(UUID(match[1])) if match else None
        except ValueError:
            crop_id = None
        if not crop_id:
            return self.respond(404, b'Unknown crop route', 'text/plain')
        request = Request('http://127.0.0.1:8022/youspeed/reports/v1/panoramax-image',
            data=json.dumps({'crop_id': crop_id}).encode(),
            headers={'Authorization': 'Bearer ' + self.server.token, 'Content-Type': 'application/json'})
        try:
            with build_opener(NoRedirect).open(request, timeout=20) as response:
                data = response.read(MAX_BYTES + 1)
                if len(data) > MAX_BYTES or not data.startswith(b'\x89PNG\r\n\x1a\n'):
                    return self.respond(502, b'Invalid crop image', 'text/plain')
                return self.respond(200, data, 'image/png')
        except HTTPError as error:
            return self.respond(error.code if error.code in (404, 503) else 502, b'Crop unavailable', 'text/plain')
        except (URLError, OSError):
            return self.respond(503, b'Crop service unavailable', 'text/plain')

    def respond(self, status, data, kind):
        self.send_response(status)
        self.send_header('Content-Type', kind)
        self.send_header('Content-Length', str(len(data)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        try:
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--token-file', type=Path, required=True)
    parser.add_argument('--port', type=int, default=8082)
    parser.add_argument('--forwarded-port', type=int, default=18082)
    args = parser.parse_args()
    server = ThreadingHTTPServer(('127.0.0.1', args.port), ImageProxy)
    server.token = args.token_file.read_text().strip()
    if not server.token:
        parser.error('Operator token is empty')
    server.allowed_hosts = {f'{host}:{port}' for host in ('127.0.0.1', 'localhost') for port in (args.port, args.forwarded_port)}
    print(f'Panoramax crop image bridge on 127.0.0.1:{args.port}', flush=True)
    server.serve_forever()


if __name__ == '__main__':
    main()
