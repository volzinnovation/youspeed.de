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
from urllib.parse import parse_qs, unquote, urlsplit
from uuid import UUID

ROOT = Path(__file__).resolve().parents[1]
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
    if getattr(error, "sqlstate", None) in ("42P01", "3F000"):
        return InspectorError("YouSpeed-Backend-Schema fehlt auf dieser Datenbank.")
    return InspectorError("Report-Datenbank nicht erreichbar oder Anmeldung fehlgeschlagen. VPN, privaten PostgreSQL-Endpunkt und serverseitige Report-Zugangsdaten prüfen.")


def crop_filters(query):
    allowed = {"offset", "limit", "country", "source", "installation", "query", "from", "to"}
    if set(query) - allowed or any(len(values) != 1 for values in query.values()):
        raise InspectorError("Ungültige Crop-Filter.", 400)
    get = lambda name, default="": query.get(name, [default])[0]
    try:
        offset, limit = int(get("offset", "0")), int(get("limit", "50"))
        if not 0 <= offset <= 1_000_000 or not 1 <= limit <= 100:
            raise ValueError
        country, source, search = get("country"), get("source"), get("query")
        if country and not re.fullmatch(r"[A-Z]{2}", country):
            raise ValueError
        if source and source not in ("detector", "manual"):
            raise ValueError
        if len(search) > 160:
            raise ValueError
        clauses, params = [], []
        if get("installation"):
            installation = str(UUID(get("installation")))
            clauses.append("m.installation=%s")
            params.append(installation)
        if country:
            clauses.append("e.payload->'event'->'classification'->>'country'=%s")
            params.append(country)
        if source:
            clauses.append("m.manifest->>'source_kind'=%s")
            params.append(source)
        if search:
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

    def list(self, query):
        offset, limit, clauses, params = crop_filters(query)
        sql = """SELECT m.installation::text, m.epoch, m.crop_id::text, m.digest,
          m.manifest, m.expires, e.payload->'event' AS observation
          FROM youspeed.media m """ + OBSERVATION_JOIN + " WHERE " + ACTIVE_MEDIA
        if clauses:
            sql += " AND " + " AND ".join(clauses)
        sql += " ORDER BY (m.manifest->>'source_frame_at')::timestamptz DESC, m.crop_id, m.installation, m.epoch LIMIT %s OFFSET %s"
        with self.connection() as db:
            rows = db.execute(sql, [*params, limit + 1, offset]).fetchall()
        crops = rows[:limit]
        for row in crops:
            row["image_url"] = f"/inspector/api/crops/{row['installation']}/{row['epoch']}/{row['crop_id']}/image"
        return {"crops": crops, "offset": offset, "has_more": len(rows) > limit}

    def devices(self):
        # Read all active device sources, independently of the current gallery page.
        sql = """SELECT m.installation::text, count(*) AS crop_count,
          array_agg(DISTINCT e.payload->'event'->'app'->>'platform')
            FILTER (WHERE e.payload->'event'->'app'->>'platform' IS NOT NULL) AS platforms
          FROM youspeed.media m """ + OBSERVATION_JOIN + " WHERE " + ACTIVE_MEDIA
        sql += " GROUP BY m.installation ORDER BY m.installation"
        with self.connection() as db:
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

    def do_HEAD(self):
        self.do_GET(head=True)

    def lane_request(self, method, head=False):
        """The local decoder is available on loopback; crop access remains read-only."""
        parsed = urlsplit(self.path)
        host = self.headers.get("Host", "")
        origin = self.headers.get("Origin")
        if (host not in self.server.allowed_hosts or self.client_address[0] != "127.0.0.1"
                or self.headers.get("Sec-Fetch-Site") == "cross-site"
                or (origin and origin != "http://" + host)
                or (method != "GET" and origin != "http://" + host)):
            self.json_response({"error": "Spurannotation erlaubt nur lokalen Same-Origin-Zugriff."}, 403, head)
            return
        decoder = getattr(self.server, "lane_videos", None)
        if decoder is None:
            self.json_response({"error": "Spurannotation benötigt den lokalen Python-Server auf 127.0.0.1 und ffmpeg/ffprobe."}, 503, head)
            return
        uploaded = None
        try:
            if parsed.query:
                raise InspectorError("Ungültige Videoabfrage.", 400)
            if method == "POST" and parsed.path == "/inspector/api/lanes/video":
                if self.headers.get("Content-Type") != "application/octet-stream" or self.headers.get("Transfer-Encoding"):
                    raise InspectorError("Video als Datei mit bekannter Länge übertragen.", 400)
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                except ValueError:
                    raise InspectorError("Ungültige Videolänge.", 400) from None
                name = unquote(self.headers.get("X-Video-Name", "dashcam"))
                uploaded = decoder.upload(self.rfile, length, name)
                self.json_response(uploaded)
            else:
                match = re.fullmatch(r"/inspector/api/lanes/video/([a-f0-9]{32})(?:/frames/([0-9]{1,7}))?", parsed.path)
                if not match:
                    raise InspectorError("Ungültige Videositzung.", 404)
                token, index = match.groups()
                if method == "DELETE" and index is None:
                    decoder.delete(token)
                    self.json_response({"closed": True})
                elif method == "GET" and index is not None:
                    data = decoder.frame(token, int(index))
                    self.send_response(200)
                    self.send_header("Content-Type", "image/png")
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    if not head:
                        self.wfile.write(data)
                else:
                    raise InspectorError("Ungültige Videomethode.", 405)
        except (BrokenPipeError, ConnectionResetError):
            if uploaded:
                decoder.delete(uploaded["session"])
        except Exception as error:
            self.json_response({"error": str(error) if hasattr(error, "status") else "Lokale Videodekodierung fehlgeschlagen."},
                               getattr(error, "status", 500), head)

    def do_POST(self):
        if urlsplit(self.path).path.startswith("/inspector/api/lanes/"):
            self.lane_request("POST")
        else:
            self.json_response({"error": "Unbekannter Endpunkt."}, 404)

    def do_DELETE(self):
        if urlsplit(self.path).path.startswith("/inspector/api/lanes/"):
            self.lane_request("DELETE")
        else:
            self.json_response({"error": "Unbekannter Endpunkt."}, 404)

    def do_GET(self, head=False):
        parsed = urlsplit(self.path)
        host = self.headers.get("Host", "")
        if host not in self.server.allowed_hosts:
            self.json_response({"error": "Unbekannter Host."}, 403, head)
            return
        origin = self.headers.get("Origin")
        if (origin and origin not in {"http://" + host, "https://" + host}) or self.headers.get("Sec-Fetch-Site") == "cross-site":
            self.json_response({"error": "Nur direkter Zugriff auf den privaten Inspector erlaubt."}, 403, head)
            return
        if parsed.path.startswith("/inspector/api/"):
            if parsed.path.startswith("/inspector/api/lanes/"):
                self.lane_request("GET", head)
                return
            try:
                if len(parsed.query) > 2048:
                    raise InspectorError("Abfrage zu lang.", 400)
                if parsed.path == "/inspector/api/crops/status":
                    self.json_response(self.server.store.status(), head=head)
                elif parsed.path == "/inspector/api/crops/devices":
                    if parsed.query:
                        raise InspectorError("Ungültige Geräteabfrage.", 400)
                    self.json_response(self.server.store.devices(), head=head)
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
            except InspectorError as error:
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
    parser.add_argument("--media-root", type=Path, default=os.environ.get("YOUSPEED_MANAGEMENT_MEDIA_ROOT"), help="Read-only path to management-media on volz-db (or its read-only mount)")
    return parser.parse_args(argv)


def main():
    args = arguments()
    lane_videos = None
    if args.bind == "127.0.0.1":
        from lane_video import LaneVideos, VideoError
        try:
            lane_videos = LaneVideos()
        except VideoError as error:
            print(str(error), flush=True)
    store = CropStore(args)
    server = ThreadingHTTPServer((args.bind, args.port), InspectorHandler)
    server.store = store
    server.lane_videos = lane_videos
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
        if lane_videos:
            lane_videos.close()


if __name__ == "__main__":
    main()
