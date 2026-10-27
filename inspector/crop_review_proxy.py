"""Bounded same-origin proxy to the separately authenticated review service.

The browser supplies a review credential per request. The read-only gallery has
no hidden write credential, and the destination cannot be selected by a client.
"""
from __future__ import annotations

import json
import re
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

MAX_REPLY_BYTES = 2 * 1024 * 1024
ROUTES = {
    "taxonomy": "/youspeed/reports/v1/review/crop-taxonomy",
    "history": "/youspeed/reports/v1/review/crop-history",
    "save": "/youspeed/reports/v1/decisions/crop-reviews",
    "export": "/youspeed/reports/v1/review/crop-export",
}


class ReviewProxyError(Exception):
    def __init__(self, message, status=503):
        super().__init__(message)
        self.status = status


class NoRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class CropReviewProxy:
    def __init__(self, origin=None, opener=None):
        self.origin = None
        self.opener = opener or build_opener(NoRedirects())
        if origin:
            parsed = urlsplit(origin)
            if (parsed.scheme not in {"http", "https"} or not parsed.hostname
                    or parsed.username or parsed.password or parsed.query or parsed.fragment
                    or parsed.path not in {"", "/"}
                    or (parsed.scheme == "http" and parsed.hostname not in {"localhost", "127.0.0.1", "::1", "youspeed-review"})):
                raise ValueError("Review service must use HTTPS, loopback HTTP, or the private youspeed-review service")
            self.origin = origin.rstrip("/")

    @property
    def configured(self):
        return self.origin is not None

    def request(self, action, payload, authorization):
        if action not in ROUTES:
            raise ReviewProxyError("Unbekannte Prüfaktion.", 404)
        if not self.configured:
            raise ReviewProxyError("Prüfdienst ist noch nicht eingerichtet.", 503)
        if not isinstance(authorization, str) or not re.fullmatch(r"Bearer [!-~]{32,4096}", authorization):
            raise ReviewProxyError("Prüfschlüssel erforderlich.", 401)
        if not isinstance(payload, dict):
            raise ReviewProxyError("Ungültige Prüfanfrage.", 400)
        data = json.dumps(payload, allow_nan=False, ensure_ascii=False).encode("utf-8")
        if len(data) > 128 * 1024:
            raise ReviewProxyError("Prüfanfrage zu groß.", 413)
        request = Request(self.origin + ROUTES[action], data=data, method="POST", headers={
            "Authorization": authorization, "Content-Type": "application/json", "Accept": "application/json",
        })
        try:
            with self.opener.open(request, timeout=15) as response:
                raw = response.read(MAX_REPLY_BYTES + 1)
                if len(raw) > MAX_REPLY_BYTES:
                    raise ReviewProxyError("Antwort des Prüfdienstes zu groß.", 502)
                try:
                    result = json.loads(raw)
                except (ValueError, UnicodeError):
                    raise ReviewProxyError("Ungültige Antwort des Prüfdienstes.", 502) from None
                if not isinstance(result, dict):
                    raise ReviewProxyError("Ungültige Antwort des Prüfdienstes.", 502)
                return result
        except HTTPError as error:
            # Never return upstream bodies, URLs, headers or transport errors;
            # database and bearer credentials remain outside browser errors/logs.
            messages = {
                400: "Prüfangaben sind ungültig.",
                401: "Prüfschlüssel fehlt oder ist ungültig.",
                403: "Keine Berechtigung für diese Prüfung.",
                404: "Crop oder Prüfung nicht mehr verfügbar.",
                409: "Prüfung wurde inzwischen geändert. Neu laden und erneut prüfen.",
                410: "Crop ist abgelaufen oder zurückgezogen.",
                413: "Prüfanfrage zu groß.",
                422: "Prüfangaben oder Crop-Quelle sind nicht zulässig.",
                429: "Zu viele Prüfanfragen. Bitte später erneut versuchen.",
            }
            status = error.code if error.code in messages else 502
            raise ReviewProxyError(messages.get(status, "Prüfdienst nicht verfügbar."), status) from None
        except (URLError, OSError, TimeoutError):
            raise ReviewProxyError("Prüfdienst nicht erreichbar.", 503) from None
