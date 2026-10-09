#!/usr/bin/env python3
"""Private Inspector server: local assets and read-only volz-db crop access."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from datetime import date, datetime, timedelta, timezone
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from inspector.crop_review_proxy import CropReviewProxy, ReviewProxyError
from inspector.sign_positions import SignPositionStore, SignPositionsError  # noqa: E402
MAX_IMAGE_BYTES = 5 * 1024**2
VOLZ_DB_ADDRESS = "141.47.91.52"
ACTIVE_MEDIA = """
 m.expires > EXTRACT(EPOCH FROM now())
 AND NOT EXISTS (SELECT 1 FROM youspeed.tombstones t
   WHERE t.installation=m.installation AND m.epoch<=t.deleted_through)
 AND NOT EXISTS (SELECT 1 FROM youspeed.authorizations a
   WHERE a.installation=m.installation AND a.epoch=m.epoch
     AND a.scope IN ('sign_metadata','crop_storage') AND a.state<>'granted')
"""
LIVE_ACTIVE_MEDIA = ACTIVE_MEDIA + """
 AND EXISTS (SELECT 1 FROM youspeed.authorizations a WHERE a.installation=m.installation
   AND a.epoch=m.epoch AND a.scope='sign_metadata' AND a.state='granted')
 AND EXISTS (SELECT 1 FROM youspeed.authorizations a WHERE a.installation=m.installation
   AND a.epoch=m.epoch AND a.scope='crop_storage' AND a.state='granted')
"""
OBSERVATION_JOIN = """LEFT JOIN youspeed.events e
 ON e.installation=m.installation AND e.epoch=m.epoch AND e.kind='sighting'
 AND e.event_id::text=m.manifest->>'observation_id'"""


class InspectorError(Exception):
    def __init__(self, message, status=503):
        self.status = status
        super().__init__(message)


def default_connection_file():
    configured = os.environ.get("YOUSPEED_DATABASE_URL_FILE")
    if configured:
        return Path(configured)
    for path in (
        Path("/srv/woladen/config/youspeed/database-report.txt"),
        Path("/run/secrets/youspeed/database.txt"),
        ROOT.parent / "Woladen.de-analytics/secret/youspeed/database-report.txt",
    ):
        if path.is_file():
            return path
    return None


def database_error(error):
    # Never pass libpq exceptions through: they can contain connection secrets.
    if getattr(error, "sqlstate", None) == "42501":
        return InspectorError("Report-Leserechte fehlen. Administrator muss inspector/report-crops-grants.sql anwenden.")
    if getattr(error, "sqlstate", None) in ("42P01", "3F000", "42883"):
        return InspectorError("YouSpeed-Crop-Analyse benötigt die geprüften Backend-Migrationen und Leserechte. Die alte Galerie bleibt unter Altbestand verfügbar.")
    return InspectorError("Report-Datenbank nicht erreichbar oder Anmeldung fehlgeschlagen. VPN, privaten PostgreSQL-Endpunkt und serverseitige Report-Zugangsdaten prüfen.")


def crop_filters(query):
    allowed = {"offset", "limit", "country", "source", "installation", "query", "from", "to", "scope", "review_state", "exit_context", "class_source", "phone_way_id", "observation_id", "collection_epoch"}
    if set(query) - allowed or any(len(values) != 1 for values in query.values()):
        raise InspectorError("Ungültige Crop-Filter.", 400)
    get = lambda name, default="": query.get(name, [default])[0]
    try:
        offset, limit = int(get("offset", "0")), int(get("limit", "50"))
        if not 0 <= offset <= 1_000_000 or not 1 <= limit <= 100:
            raise ValueError
        country, source, search = get("country"), get("source"), get("query")
        scope, review_state, exit_context = get("scope", "live"), get("review_state"), get("exit_context")
        class_source = get("class_source", "original")
        if (scope not in {"live", "legacy"} or class_source not in {"original", "reviewed"}
                or review_state not in {"", "unreviewed", "confirmed", "wrong_class", "not_a_sign", "uncertain"}
                or exit_context not in {"", "near_exit", "no_exit", "unknown", "not_computed"}
                or (scope == "legacy" and (review_state or exit_context or class_source != "original"))):
            raise ValueError
        if country and not re.fullmatch(r"[A-Z]{2}", country):
            raise ValueError
        if source and source not in ("detector", "manual", "manual_capture"):
            raise ValueError
        if len(search) > 160:
            raise ValueError
        phone_way_id = get("phone_way_id")
        if phone_way_id and (not re.fullmatch(r"[1-9][0-9]{0,18}", phone_way_id)
                             or int(phone_way_id) > 9223372036854775807):
            raise ValueError
        clauses, params = [], []
        if get("installation"):
            installation = str(UUID(get("installation")))
            clauses.append("m.installation=%s")
            params.append(installation)
        if get("observation_id") or get("collection_epoch"):
            # A crop sequence is one source observation in one installation epoch.
            if not get("installation") or not get("observation_id") or not re.fullmatch(r"0|[1-9][0-9]{0,9}", get("collection_epoch")):
                raise ValueError
            epoch = int(get("collection_epoch"))
            if epoch > 2147483647:
                raise ValueError
            observation_id = str(UUID(get("observation_id")))
            clauses.extend(["m.epoch=%s", "m.manifest->>'observation_id'=%s"])
            params.extend([epoch, observation_id])
        if phone_way_id:
            clauses.append("jsonb_typeof(m.manifest->'phone_road_match'->'osm_way_id')='string'")
            clauses.append("m.manifest->'phone_road_match'->'schema_version'='1'::jsonb")
            clauses.append("m.manifest->'phone_road_match'->>'source'='on_device_bundle_matcher'")
            clauses.append("m.manifest->'phone_road_match'->>'osm_way_id'=%s")
            params.append(phone_way_id)
        if country:
            if class_source == "reviewed":
                clauses.append("(CASE WHEN r.verdict='confirmed' THEN e.payload->'event'->'classification' WHEN r.verdict='wrong_class' THEN r.corrected_classification ELSE NULL END)->>'country'=%s")
            else:
                clauses.append("e.payload->'event'->'classification'->>'country'=%s")
            params.append(country)
        if source:
            clauses.append("m.manifest->>'source_kind'=%s")
            params.append("manual_capture" if source == "manual" else source)
        if review_state:
            clauses.append("COALESCE(r.verdict,'unreviewed')=%s")
            params.append(review_state)
        if exit_context:
            if exit_context == "not_computed":
                clauses.append("c.context_key IS NULL")
            else:
                clauses.append("c.status=%s")
                params.append(exit_context)
        if search and class_source == "reviewed":
            effective = "(CASE WHEN r.verdict='confirmed' THEN e.payload->'event'->'classification' WHEN r.verdict='wrong_class' THEN r.corrected_classification ELSE NULL END)"
            clauses.append(f"""(strpos(lower(COALESCE({effective}->>'canonical_code','')),%s)>0
              OR strpos(lower(COALESCE({effective}->>'model_label','')),%s)>0
              OR strpos(m.crop_id::text,%s)>0 OR strpos(m.manifest->>'observation_id',%s)>0)""")
            params.extend([search.lower()] * 4)
        elif search:
            clauses.append("""(strpos(lower(COALESCE(e.payload->'event'->'classification'->>'canonical_code','')),%s)>0
              OR strpos(lower(COALESCE(e.payload->'event'->'classification'->>'model_label','')),%s)>0
              OR strpos(m.crop_id::text,%s)>0 OR strpos(m.manifest->>'observation_id',%s)>0)""")
            params.extend([search.lower()] * 4)
        start, end = None, None
        if get("from"):
            start = date.fromisoformat(get("from"))
            clauses.append("(m.manifest->>'source_frame_at')::timestamptz>=%s")
            params.append(datetime.combine(start, datetime.min.time(), timezone.utc))
        if get("to"):
            end = date.fromisoformat(get("to"))
            clauses.append("(m.manifest->>'source_frame_at')::timestamptz<%s")
            params.append(datetime.combine(end + timedelta(days=1), datetime.min.time(), timezone.utc))
        if start and end and start > end:
            raise ValueError
        return offset, limit, clauses, params
    except (ValueError, OverflowError):
        raise InspectorError("Ungültige Crop-Filter oder Zeitspanne.", 400) from None


def crop_identity(path):
    parts = path.split("/")
    try:
        if len(parts) != 8 or parts[:4] != ["", "inspector", "api", "crops"] or parts[7] != "image":
            raise ValueError
        installation, crop_id = str(UUID(parts[4])), str(UUID(parts[6]))
        epoch = int(parts[5])
        if not 0 <= epoch <= 2147483647:
            raise ValueError
        return installation, epoch, crop_id
    except ValueError:
        raise InspectorError("Ungültige Crop-ID.", 400) from None


def read_image(media_root, row):
    if media_root is None:
        raise InspectorError("Bildverzeichnis nicht eingerichtet. YOUSPEED_MANAGEMENT_MEDIA_ROOT auf das Backend-Medienverzeichnis setzen.")
    name = row["object_path"]
    if not re.fullmatch(r"(?:[a-f0-9]{64}|[a-f0-9-]{36}-[0-9]+-[a-f0-9-]{36}\.crop)", name):
        raise InspectorError("Ungültiger gespeicherter Bildpfad.", 422)
    path = media_root / name
    try:
        # O_NOFOLLOW prevents a changed symlink from escaping the media directory.
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(fd, "rb") as file:
            import stat
            metadata = os.fstat(file.fileno())
            if not stat.S_ISREG(metadata.st_mode) or not 0 < metadata.st_size <= MAX_IMAGE_BYTES:
                raise InspectorError("Gespeicherte Bildgröße ungültig.", 422)
            data = file.read(MAX_IMAGE_BYTES + 1)
    except (FileNotFoundError, PermissionError):
        raise InspectorError("Bilddatei fehlt oder ist für den Inspector nicht lesbar.", 404) from None
    except OSError:
        raise InspectorError("Gespeicherte Bilddatei kann nicht sicher gelesen werden.", 422) from None
    manifest = row["manifest"]
    if len(data) != manifest["byte_length"] or hashlib.sha256(data).hexdigest() != row["digest"] or row["digest"] != manifest["encoded_sha256"]:
        raise InspectorError("Bildintegrität fehlgeschlagen (Länge / SHA-256).", 422)
    encoding = manifest["encoding"]
    if encoding == "PNG" and data.startswith(b"\x89PNG\r\n\x1a\n"):
        return data, "image/png"
    if encoding == "JPEG" and data.startswith(b"\xff\xd8\xff"):
        return data, "image/jpeg"
    raise InspectorError("Gespeichertes Bildformat ungültig.", 422)


class CropStore:
    def __init__(self, args):
        self.args = args
        self.media_root = args.media_root.resolve() if args.media_root else None

    @contextmanager
    def connection(self):
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ImportError:
            raise InspectorError('Python-Treiber fehlt: python3 -m pip install "psycopg[binary]>=3.1,<4"') from None
        value = os.environ.get("YOUSPEED_DATABASE_URL", "")
        if self.args.database_file:
            try:
                path = self.args.database_file
                if path.stat().st_mode & 0o077:
                    raise InspectorError("Report-Zugangsdaten müssen eine private Datei sein (Modus 0600).")
                value = path.read_text().strip()
                if not value:
                    raise InspectorError("Report-Zugangsdaten-Datei ist leer.")
            except OSError:
                raise InspectorError("Report-Zugangsdaten-Datei nicht lesbar.") from None
        options = {"user": self.args.db_user, "dbname": "youspeed", "connect_timeout": 5,
                   "row_factory": dict_row, "options": "-c default_transaction_read_only=on -c statement_timeout=10000"}
        if self.args.db_host:
            options["host"] = self.args.db_host
        elif not value and not os.environ.get("PGHOST"):
            options["host"] = "volz-db"
        if self.args.db_port:
            options["port"] = self.args.db_port
        try:
            with psycopg.connect(value, **options) as db:
                db.execute("SET TRANSACTION READ ONLY")
                yield db
        except psycopg.Error as error:
            raise database_error(error) from None

    def status(self):
        with self.connection() as db:
            identity = db.execute("SELECT current_database() AS database, current_user AS user").fetchone()
            # Fail here with a useful grant error before the first gallery query.
            db.execute("SELECT 1 FROM youspeed.media, youspeed.tombstones, youspeed.authorizations, youspeed.events LIMIT 0")
        return {**identity, "media_available": bool(self.media_root and self.media_root.is_dir() and os.access(self.media_root, os.R_OK | os.X_OK))}

    @staticmethod
    def require_live_controls(db):
        control = db.execute("""SELECT (refreshed_at <= extract(epoch FROM now())
          AND refreshed_at >= extract(epoch FROM now()) - 900
          AND watermark >= 0 AND contiguous_sequence >= watermark) AS fresh
          FROM youspeed.control_state WHERE singleton""").fetchone()
        if not control or control["fresh"] is not True:
            raise InspectorError("Live-Analyse wartet auf aktuelle, vollständige Freigabe- und Löschkontrollen des Backends. Später neu laden; Altbestand bleibt nur lesbar.", 503)

    def list(self, query):
        offset, limit, clauses, params = crop_filters(query)
        scope = query.get("scope", ["live"])[0]
        base = """SELECT m.installation::text, m.epoch, m.crop_id::text, m.digest,
          m.manifest, m.expires, e.payload->'event' AS observation, """
        if scope == "live":
            base += """true AS analysis_eligible, NULL::text AS exclusion_reason,
              'live-crops-only-v1'::text AS source_policy,
              COALESCE(r.revision,0) AS current_revision,
              CASE WHEN r.request_id IS NOT NULL THEN to_jsonb(r) ELSE NULL END AS current_review,
              c.result AS exit_context FROM youspeed.media m """ + OBSERVATION_JOIN + """
              LEFT JOIN LATERAL (SELECT rr.* FROM youspeed.crop_reviews rr
                WHERE rr.installation=m.installation AND rr.epoch=m.epoch AND rr.crop_id=m.crop_id
                ORDER BY rr.revision DESC LIMIT 1) r ON true
              LEFT JOIN LATERAL (SELECT cc.* FROM youspeed.crop_exit_contexts cc
                WHERE cc.installation=m.installation AND cc.epoch=m.epoch AND cc.crop_id=m.crop_id
                ORDER BY cc.created_at DESC, cc.context_key DESC LIMIT 1) c ON true
              WHERE youspeed.live_crop_exclusion_reason(m.manifest,e.payload->'event') IS NULL AND """ + LIVE_ACTIVE_MEDIA
        else:
            base += """false AS analysis_eligible, 'legacy_scope_read_only'::text AS exclusion_reason,
              'live-crops-only-v1'::text AS source_policy, 0 AS current_revision,
              NULL::jsonb AS current_review, NULL::jsonb AS exit_context
              FROM youspeed.media m """ + OBSERVATION_JOIN + " WHERE " + ACTIVE_MEDIA
        if clauses:
            base += " AND " + " AND ".join(clauses)
        base += " ORDER BY (m.manifest->>'source_frame_at')::timestamptz DESC, m.crop_id, m.installation, m.epoch LIMIT %s OFFSET %s"
        with self.connection() as db:
            if scope == "live":
                self.require_live_controls(db)
            rows = db.execute(base, [*params, limit + 1, offset]).fetchall()
        crops = rows[:limit]
        for row in crops:
            row["image_url"] = f"/inspector/api/crops/{row['installation']}/{row['epoch']}/{row['crop_id']}/image"
        return {"crops": crops, "offset": offset, "has_more": len(rows) > limit,
                "scope": scope, "source_policy": "live-crops-only-v1"}

    def devices(self, scope="live"):
        if scope not in {"live", "legacy"}:
            raise InspectorError("Ungültiger Quellenfilter.", 400)
        # Read all active device sources, independently of the current gallery page.
        sql = """SELECT m.installation::text, count(*) AS crop_count,
          array_agg(DISTINCT e.payload->'event'->'app'->>'platform')
            FILTER (WHERE e.payload->'event'->'app'->>'platform' IS NOT NULL) AS platforms
          FROM youspeed.media m """ + OBSERVATION_JOIN + " WHERE " + ACTIVE_MEDIA
        if scope == "live":
            sql += " AND youspeed.live_crop_exclusion_reason(m.manifest,e.payload->'event') IS NULL AND " + LIVE_ACTIVE_MEDIA
        sql += " GROUP BY m.installation ORDER BY m.installation"
        with self.connection() as db:
            if scope == "live":
                self.require_live_controls(db)
            rows = db.execute(sql).fetchall()
        return {"devices": rows}

    def image(self, identity):
        with self.connection() as db:
            row = db.execute("SELECT m.* FROM youspeed.media m WHERE m.installation=%s AND m.epoch=%s AND m.crop_id=%s AND " + ACTIVE_MEDIA, identity).fetchone()
            if not row:
                raise InspectorError("Crop nicht verfügbar, abgelaufen oder zurückgezogen.", 404)
            return read_image(self.media_root, row)


def static_path_allowed(path):
    relative = path.relative_to(ROOT)
    if any(part.startswith(".") for part in relative.parts):
        return False
    if relative.parts[0] == "inspector":
        return len(relative.parts) <= 2 and (path.is_dir() or path.suffix in {".html", ".css", ".js", ".ndjson"})
    if relative.parts[:3] in (("shared", "tsr", "fixtures"), ("shared", "tsr", "sign-pictograms")):
        return path.suffix in {".json", ".png", ".jpg", ".jpeg", ".ppm", ".svg", ".txt"}
    if relative.parts[:2] == ("shared", "tsr") and len(relative.parts) == 3:
        return bool(re.fullmatch(r"prolix-[a-z]{2}-class-catalog-v1\.json", path.name))
    if relative.parts[:3] == ("iphone", "SpeedConsumerApp", "TSRModelPacks"):
        return path.name == "manifest.json"
    return relative.as_posix() == "iphone/SpeedConsumerApp/karlsruhe-regbez_speeds.sqlite"


class InspectorHandler(SimpleHTTPRequestHandler):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(ROOT), **kwargs)

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Cross-Origin-Resource-Policy", "same-origin")
        self.send_header("X-Frame-Options", "DENY")
        super().end_headers()

    def log_message(self, format, *args):
        # Private crop identities/filter strings do not belong in access logs.
        pass

    def json_response(self, body, status=200, head=False):
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        if not head:
            self.wfile.write(data)

    def request_allowed(self, head=False):
        host = self.headers.get("Host", "")
        if len(self.headers.get_all("Host", [])) != 1 or host not in self.server.allowed_hosts:
            self.json_response({"error": "Unbekannter Host."}, 403, head)
            return False
        origin = self.headers.get("Origin")
        if (origin and origin not in {"http://" + host, "https://" + host}) or self.headers.get("Sec-Fetch-Site") == "cross-site":
            self.json_response({"error": "Nur direkter Zugriff auf den privaten Inspector erlaubt."}, 403, head)
            return False
        return True

    def review_request(self, action, payload):
        proxy = getattr(self.server, "review_proxy", None)
        if proxy is None:
            raise ReviewProxyError("Prüfdienst ist noch nicht eingerichtet.", 503)
        return proxy.request(action, payload, self.headers.get("Authorization"))

    def do_POST(self):
        if not self.request_allowed():
            return
        parsed = urlsplit(self.path)
        actions = {f"/inspector/api/crops/review/{a}": a for a in ("history", "save", "export")}
        try:
            if parsed.query or parsed.path not in actions:
                raise InspectorError("Unbekannter Inspector-Endpunkt.", 404)
            lengths = self.headers.get_all("Content-Length", [])
            if self.headers.get("Transfer-Encoding") or len(lengths) != 1:
                raise InspectorError("Eindeutige Inhaltslänge erforderlich.", 400)
            try:
                length = int(lengths[0])
            except ValueError:
                raise InspectorError("Ungültige Inhaltslänge.", 400) from None
            if not 0 < length <= 128 * 1024:
                raise InspectorError("Prüfanfrage zu groß oder leer.", 413)
            if self.headers.get_content_type() != "application/json":
                raise InspectorError("JSON-Prüfanfrage erforderlich.", 415)
            self.connection.settimeout(15)
            raw = self.rfile.read(length)
            if len(raw) != length:
                raise InspectorError("Unvollständige Prüfanfrage.", 400)
            def invalid_constant(value):
                raise ValueError(value)
            try:
                payload = json.loads(raw, parse_constant=invalid_constant)
            except (ValueError, UnicodeError):
                raise InspectorError("Ungültige JSON-Prüfanfrage.", 400) from None
            if not isinstance(payload, dict):
                raise InspectorError("JSON-Objekt erforderlich.", 400)
            self.json_response(self.review_request(actions[parsed.path], payload))
        except (InspectorError, ReviewProxyError, SignPositionsError) as error:
            self.json_response({"error": str(error)}, error.status)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self.json_response({"error": "Prüfanfrage fehlgeschlagen."}, 500)

    def do_HEAD(self):
        self.do_GET(head=True)

    def do_GET(self, head=False):
        parsed = urlsplit(self.path)
        if not self.request_allowed(head):
            return
        if parsed.path.startswith("/inspector/api/") or parsed.path == "/api/sign-positions":
            try:
                if len(parsed.query) > 2048:
                    raise InspectorError("Abfrage zu lang.", 400)
                if parsed.path in ("/api/sign-positions", "/inspector/api/sign-positions"):
                    if parsed.query:
                        raise InspectorError("Ungültige Schildpositions-Abfrage.", 400)
                    store = getattr(self.server, "sign_positions", None)
                    if store is None:
                        raise SignPositionsError("Datei für Schildpositionen ist nicht eingerichtet.")
                    self.json_response(store.get(), head=head)
                elif parsed.path == "/inspector/api/crops/review/taxonomy":
                    if parsed.query:
                        raise InspectorError("Ungültige Taxonomie-Abfrage.", 400)
                    self.json_response(self.review_request("taxonomy", {}), head=head)
                elif parsed.path == "/inspector/api/crops/status":
                    status = self.server.store.status()
                    status["review_service_configured"] = bool(getattr(self.server, "review_proxy", None) and self.server.review_proxy.configured)
                    self.json_response(status, head=head)
                elif parsed.path == "/inspector/api/crops/devices":
                    query = parse_qs(parsed.query, keep_blank_values=True)
                    if set(query) - {"scope"} or any(len(values) != 1 for values in query.values()):
                        raise InspectorError("Ungültige Geräteabfrage.", 400)
                    if not query:
                        self.json_response(self.server.store.devices(), head=head)
                    else:
                        self.json_response(self.server.store.devices(query.get("scope", ["live"])[0]), head=head)
                elif parsed.path == "/inspector/api/crops":
                    self.json_response(self.server.store.list(parse_qs(parsed.query, keep_blank_values=True)), head=head)
                elif parsed.path.endswith("/image"):
                    data, content_type = self.server.store.image(crop_identity(parsed.path))
                    self.send_response(200)
                    self.send_header("Content-Type", content_type)
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    if not head:
                        self.wfile.write(data)
                else:
                    raise InspectorError("Unbekannter Inspector-Endpunkt.", 404)
            except (InspectorError, ReviewProxyError, SignPositionsError) as error:
                self.json_response({"error": str(error)}, error.status, head)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                self.json_response({"error": "Crop-Abfrage fehlgeschlagen. Backend-Konfiguration prüfen."}, 500, head)
            return
        if parsed.path == "/":
            self.send_response(302)
            self.send_header("Location", "/inspector/#crops")
            self.end_headers()
            return
        path = Path(self.translate_path(unquote(parsed.path))).resolve()
        if not path.is_relative_to(ROOT) or path == ROOT or not static_path_allowed(path):
            self.send_error(404)
            return
        if head:
            super().do_HEAD()
        else:
            super().do_GET()

    def list_directory(self, path):
        self.send_error(404)
        return None


def arguments(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bind", default="127.0.0.1", help="Loopback or the server's private VPN address")
    parser.add_argument("--port", type=int, default=8080)
    parser.add_argument("--allowed-host", action="append", default=[], help="Additional browser Host header, including port; e.g. volz-db:8080")
    parser.add_argument("--database-file", type=Path, default=default_connection_file())
    parser.add_argument("--db-user", default=os.environ.get("YOUSPEED_REPORT_USER", "youspeed_report"))
    parser.add_argument("--db-host", default=None, help="Override the credential file's PostgreSQL host")
    parser.add_argument("--db-port", type=int, default=None)
    parser.add_argument("--review-service-url", default=os.environ.get("YOUSPEED_CROP_REVIEW_URL"), help="Separately authenticated backend review origin (HTTPS, loopback HTTP or private youspeed-review service); no browser-selected destinations")
    parser.add_argument("--media-root", type=Path, default=os.environ.get("YOUSPEED_MANAGEMENT_MEDIA_ROOT"), help="Read-only path to management-media on volz-db (or its read-only mount)")
    parser.add_argument("--sign-positions-file", type=Path, default=os.environ.get("YOUSPEED_SIGN_POSITIONS_FILE"), help="Private external static fit export; sources rechecked on every request")
    return parser.parse_args(argv)


def main():
    args = arguments()
    store = CropStore(args)
    server = ThreadingHTTPServer((args.bind, args.port), InspectorHandler)
    server.store = store
    server.sign_positions = SignPositionStore(args.sign_positions_file, store)
    server.review_proxy = CropReviewProxy(args.review_service_url)
    server.allowed_hosts = {f"{args.bind}:{server.server_port}", f"volz-db:{server.server_port}",
                            f"{VOLZ_DB_ADDRESS}:{server.server_port}", *args.allowed_host}
    if args.bind == "127.0.0.1":
        server.allowed_hosts.add(f"localhost:{server.server_port}")
    print(f"Inspector: http://{args.bind}:{server.server_port}/inspector/#crops", flush=True)
    print(f"Default report user: {args.db_user}. Database credentials stay server-side.", flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
