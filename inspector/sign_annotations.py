"""Local Panoramax annotation editor, using the existing management transport.

Panoramax 2.15.1 supports new rectangles and semantic updates, not shape PATCH.
Every attempted write is journaled before transmission. No inventory baseline is
modified, and an uncertain submission is reconciled without resubmitting it.
"""
from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import importlib.util
import io
import json
import math
import os
from pathlib import Path
import sqlite3
import stat
import threading
from urllib.parse import urlsplit
from uuid import UUID, uuid5

from inspector.place_sign_review import asset_path, local_picture

ROUTE = "/inspector/api/sign-annotations"
ORIGIN = "https://panoramax.woladen.de"
NAMESPACE = UUID("4319d3fc-30cc-4a0b-a193-665737623d0e")
ROOT = Path(__file__).resolve().parents[1]
KEY = "osm|traffic_sign"
CLASS_KEY = "youspeed|tsr_class"


class AnnotationEditorError(Exception):
    def __init__(self, code, status=400, *, uncertain=False):
        super().__init__(code)
        self.status, self.uncertain = status, uncertain


def require(condition, code, status=400):
    if not condition:
        raise AnnotationEditorError(code, status)


def identifier(value):
    try:
        require(isinstance(value, str) and str(UUID(value)) == value, "invalid_uuid")
    except (ValueError, AttributeError):
        raise AnnotationEditorError("invalid_uuid") from None
    return value


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def digest(value):
    return hashlib.sha256(canonical(value).encode()).hexdigest()


def timestamp():
    return datetime.now(timezone.utc).isoformat()


def load_transport(backend_root):
    path = Path(backend_root) / "commercial_backend/youspeed/panoramax_annotation_client.py"
    spec = importlib.util.spec_from_file_location("inspector_panoramax_transport", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def private_file(path):
    path = Path(path).absolute()
    parent = path.parent
    info = parent.stat()
    require(parent.is_dir() and info.st_uid == os.getuid() and not info.st_mode & 0o077
            and not path.resolve().is_relative_to(ROOT), "private_external_journal_required")
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    info = os.fstat(fd)
    if not (stat.S_ISREG(info.st_mode) and info.st_uid == os.getuid() and info.st_nlink == 1
            and not info.st_mode & 0o077):
        os.close(fd)
        raise AnnotationEditorError("private_journal_required")
    return path, fd


class CorrectionJournal:
    def __init__(self, path):
        self.path, fd = private_file(path)
        os.close(fd)
        with self.connection() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS corrections (
              request_id TEXT PRIMARY KEY, payload_sha256 TEXT NOT NULL,
              timestamp TEXT NOT NULL, status TEXT NOT NULL, picture_id TEXT NOT NULL,
              annotation_id TEXT NOT NULL, sign_code TEXT,
              before_json TEXT NOT NULL, desired_json TEXT NOT NULL, after_json TEXT,
              error TEXT)""")

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=2)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA synchronous=FULL")
        try:
            with db:
                yield db
        finally:
            db.close()

    @contextmanager
    def exclusive(self):
        _, fd = private_file(str(self.path) + ".lock")
        try:
            try:
                fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                raise AnnotationEditorError("another_correction_in_progress", 409) from None
            yield
        finally:
            os.close(fd)

    def get(self, request_id):
        with self.connection() as db:
            row = db.execute("SELECT * FROM corrections WHERE request_id=?", (request_id,)).fetchone()
        return dict(row) if row else None

    def prepare(self, request_id, payload, picture_id, annotation_id, before, desired):
        with self.connection() as db:
            pending = db.execute("SELECT 1 FROM corrections WHERE picture_id=? AND status IN ('prepared','uncertain')",
                                 (picture_id,)).fetchone()
            require(not pending, "picture_has_unresolved_submission", 409)
            db.execute("INSERT INTO corrections VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                       (request_id, digest(payload), timestamp(), "prepared", picture_id, annotation_id,
                        payload["sign_code"], canonical(before), canonical(desired), None, None))

    def finish(self, request_id, status, *, after=None, error=None):
        with self.connection() as db:
            db.execute("UPDATE corrections SET status=?,after_json=?,error=? WHERE request_id=?",
                       (status, canonical(after) if after is not None else None, error, request_id))
        return self.receipt(self.get(request_id))

    @staticmethod
    def receipt(row):
        fields = ("timestamp", "status", "sign_code", "picture_id", "annotation_id", "request_id", "error")
        desired = json.loads(row["desired_json"])
        class_id = next((r["value"] for r in desired["semantics"] if r["key"] == CLASS_KEY), None)
        return {**{k: row[k] for k in fields}, "class_id": class_id, "before_sha256": digest(json.loads(row["before_json"])),
                "after_sha256": digest(json.loads(row["after_json"])) if row["after_json"] else None}

    def history(self):
        with self.connection() as db:
            rows = db.execute("SELECT * FROM corrections ORDER BY timestamp DESC LIMIT 100").fetchall()
        return {"corrections": [self.receipt(row) for row in rows]}


class SignAnnotations:
    def __init__(self, *, backend_root=None, token_file=None, journal_file=None, client=None, transport=None, media_dir=None):
        self._lock = threading.RLock()
        self.transport = transport
        self.client = client
        self.media_dir = media_dir
        self.unavailable = None
        self.journal = CorrectionJournal(journal_file) if journal_file else None
        self.catalog = {}
        self.classes = {}
        for path in sorted((ROOT / "shared/tsr").glob("prolix-*-class-catalog-v1.json")):
            for item in json.loads(path.read_text()).get("signs", []):
                code = item.get("sign_code")
                if code:
                    self.catalog[code] = {"code": code, "label": item.get("label", {}).get("de", code)}
        catalog = json.loads((ROOT / "shared/tsr/prolix-de-class-catalog-v1.json").read_text())
        for label in catalog["class_labels"]:
            rows = [r for r in catalog["signs"] if r["class_id"] == label]
            self.classes[label] = {"class_id": label, "label": rows[0].get("label", {}).get("de", label) if rows else label,
                                   "sign_codes": sorted({r["sign_code"] for r in rows if r.get("sign_code")})}
        if self.client is None:
            try:
                self.transport = load_transport(backend_root or ROOT.parent / "Woladen.de-analytics")
                self.client = self.transport.AnnotationClient(ORIGIN, token_file=token_file, timeout=(10, 20))
                if Path("/etc/ssl/cert.pem").is_file():
                    self.client.session.verify = "/etc/ssl/cert.pem"
            except (OSError, ImportError, ValueError):
                self.unavailable = "annotation_transport_unavailable"
            except Exception:
                self.unavailable = "annotation_configuration_invalid"

    @property
    def write_enabled(self):
        return bool(self.client and self.client.token and self.journal and not self.unavailable)

    def status(self):
        return {"write_enabled": self.write_enabled, "read_enabled": bool(self.client and not self.unavailable),
                "state": "unavailable" if self.unavailable else "enabled" if self.write_enabled else "read_only",
                "supports_shape_edit": False, "allow_create": self.write_enabled,
                "catalog": list(self.catalog.values()), "origin": ORIGIN,
                "classes": list(self.classes.values()), "unmapped_class_semantic_key": CLASS_KEY,
                "message": "Bestehende Markierungen: Zeichenklasse ändern. Neue Markierung: Rahmen zeichnen. "
                           "Panoramax unterstützt keine Änderung bestehender Rahmen." +
                           (" Schreibzugang und privates Änderungsjournal sind noch nicht eingerichtet." if not self.write_enabled else ""),
                "error": self.unavailable}

    def available(self):
        require(self.client and not self.unavailable, self.unavailable or "annotation_transport_unavailable", 503)

    def call(self, fn, *args, **kwargs):
        self.available()
        try:
            return fn(*args, **kwargs)
        except self.transport.AnnotationError as error:
            status = error.status if error.status in (400, 401, 403, 404, 409, 422, 429) else 503
            raise AnnotationEditorError(error.code, status, uncertain=error.uncertain) from None

    @contextmanager
    def reader(self):
        """Independent anonymous sessions keep image browsing separate from writes."""
        self.available()
        if not hasattr(self.transport, "AnnotationClient"):  # Injected fixture transport.
            yield self.client
            return
        client = self.transport.AnnotationClient(ORIGIN, timeout=(5, 10))
        if Path("/etc/ssl/cert.pem").is_file():
            client.session.verify = "/etc/ssl/cert.pem"
        try:
            yield client
        finally:
            client.session.close()

    def raw_picture(self, picture_id):
        identifier(picture_id)
        with self.reader() as client:
            return self.call(client.public_picture, picture_id)

    def rectangle(self, value):
        try:
            return self.transport.rectangle(value)
        except self.transport.AnnotationError:
            raise AnnotationEditorError("rectangle_required") from None

    def normalize(self, raw):
        props = raw["properties"]
        dimensions = props.get("pers:interior_orientation", {}).get("sensor_array_dimensions", [])
        require(len(dimensions) == 2 and all(type(n) is int and 0 < n <= 100000 for n in dimensions),
                "picture_dimensions_unavailable", 422)
        coords = raw.get("geometry", {}).get("coordinates", [])
        require(len(coords) >= 2 and all(type(v) in (int, float) and math.isfinite(v) for v in coords[:2]),
                "picture_location_unavailable", 422)
        annotations = []
        for row in props.get("annotations", []):
            identifier(row.get("id"))
            try:
                box = self.rectangle(row.get("shape"))
            except AnnotationEditorError:
                box = None
            codes = [s["value"] for s in row.get("semantics", []) if s.get("key") == KEY]
            classes = [s["value"] for s in row.get("semantics", []) if s.get("key") == CLASS_KEY]
            if not classes and len(codes) == 1:
                classes = [label for label, item in self.classes.items() if codes[0] in item["sign_codes"]]
            annotations.append({"id": row["id"], "box_xyxy": box, "sign_code": codes[0] if len(codes) == 1 else None,
                                "sign_codes": codes, "class_id": classes[0] if len(classes) == 1 else None,
                                "geometry_editable": False, "semantics": row.get("semantics", [])})
        annotations.sort(key=lambda r: r["id"])
        result = {"id": identifier(raw["id"]), "width": dimensions[0], "height": dimensions[1],
                  "longitude": coords[0], "latitude": coords[1], "heading_deg": props.get("view:azimuth"),
                  "captured_at": props.get("datetime"), "sequence_id": raw.get("collection"),
                  "rank": props.get("geovisio:rank_in_collection"), "annotations": annotations,
                  "photo_url": ROUTE + "/pictures/" + raw["id"] + "/photo", "geometry_editable": False}
        result["revision"] = digest({k: result[k] for k in ("id", "width", "height", "annotations")})
        return result

    def link(self, link, sequence_id=None):
        identifier(link.get("id"))
        parsed = urlsplit(link.get("href", ""))
        parts = parsed.path.strip("/").split("/")
        require(parsed.scheme + "://" + parsed.netloc == ORIGIN and not parsed.query and not parsed.fragment
                and len(parts) == 5 and parts[:2] == ["api", "collections"] and parts[3] == "items"
                and parts[4] == link["id"], "invalid_picture_link", 502)
        identifier(parts[2])
        require(sequence_id is None or parts[2] == sequence_id, "unexpected_sequence_link", 502)
        return {"id": link["id"], "sequence_id": parts[2], "navigation_basis": "source_sequence_order"}

    def picture(self, picture_id, *, nearby=False):
        raw = self.raw_picture(picture_id)
        result = self.normalize(raw)
        result.update(previous=None, next=None, nearby=[], nearby_available=False)
        attempted = 0
        for link in raw.get("links", []):
            if link.get("rel") in ("prev", "next"):
                key = "previous" if link["rel"] == "prev" else "next"
                result[key] = self.link(link, result["sequence_id"])
            elif link.get("rel") == "related":
                result["nearby_available"] = True
                if not nearby or attempted >= 6:
                    continue
                attempted += 1
                try:
                    candidate = self.normalize(self.raw_picture(self.link(link)["id"]))
                    dx = math.radians(candidate["longitude"] - result["longitude"]) * math.cos(math.radians(result["latitude"]))
                    dy = math.radians(candidate["latitude"] - result["latitude"])
                    candidate = {k: candidate[k] for k in ("id", "sequence_id", "rank", "heading_deg", "longitude", "latitude", "captured_at")}
                    candidate["distance_m"] = round(math.hypot(dx, dy) * 6371008.8, 2)
                    a, b = candidate["heading_deg"], result["heading_deg"]
                    candidate["heading_delta_deg"] = abs((a - b + 180) % 360 - 180) if type(a) in (int, float) and type(b) in (int, float) else None
                    candidate["navigation_basis"] = "related_capture_location_and_heading"
                    result["nearby"].append(candidate)
                except AnnotationEditorError:
                    continue
        result["nearby"].sort(key=lambda r: (r["distance_m"], r["heading_delta_deg"] if r["heading_delta_deg"] is not None else 361, r["id"]))
        return result

    def photo(self, picture_id):
        with self.reader() as reader:
            metadata = self.normalize(self.raw_picture(picture_id))
            self.available()
            try:
                local = local_picture(self.media_dir, picture_id)
                if local is not None:
                    self.validate_photo(local, metadata)
                    return local, "image/jpeg"
                response = reader.session.get(ORIGIN + asset_path(picture_id), timeout=(10, 20),
                                                   allow_redirects=False, stream=True)
                try:
                    require(response.status_code == 200 and response.headers.get("Content-Type", "").split(";")[0] == "image/jpeg", "picture_image_unavailable", 502)
                    chunks, size = [], 0
                    for chunk in response.iter_content(65536):
                        size += len(chunk)
                        require(size <= 32 * 1024 * 1024, "picture_image_too_large", 502)
                        chunks.append(chunk)
                finally:
                    response.close()
                data = b"".join(chunks)
                self.validate_photo(data, metadata)
                return data, "image/jpeg"
            except AnnotationEditorError:
                raise
            except Exception:
                raise AnnotationEditorError("picture_image_unavailable", 503) from None

    @staticmethod
    def validate_photo(data, metadata):
        from PIL import Image
        with Image.open(io.BytesIO(data)) as image:
            require(image.format == "JPEG" and image.size == (metadata["width"], metadata["height"]), "picture_dimensions_changed", 409)
            image.verify()

    def history(self):
        return self.journal.history() if self.journal else {"corrections": []}

    def confirmed_reply(self, picture_id, receipt):
        try:
            return {**self.picture(picture_id, nearby=False), "correction": receipt, "picture_sync": "current"}
        except AnnotationEditorError:
            # The write and verification succeeded; a later image-metadata
            # refresh failure must never turn this into an uncertain write.
            return {"id": picture_id, "correction": receipt, "picture_sync": "refresh_required"}

    def matches(self, actual, desired):
        if actual is None:
            return False
        try:
            return (actual.get("picture_id") == desired["picture_id"] and actual.get("id") == desired["id"]
                    and self.rectangle(actual.get("shape")) == desired["box_xyxy"]
                    and {tuple((r["key"], r["value"])) for r in actual.get("semantics", [])}
                    == {tuple((r["key"], r["value"])) for r in desired["semantics"]})
        except (KeyError, AnnotationEditorError):
            return False

    def save(self, picture_id, payload):
        require(self.write_enabled, "annotation_write_not_configured", 503)
        identifier(picture_id)
        required = {"request_id", "base_revision", "annotation_id", "box_xyxy", "sign_code"}
        require(isinstance(payload, dict) and required <= set(payload) <= required | {"class_id"}, "invalid_correction_payload")
        request_id = identifier(payload["request_id"])
        require(isinstance(payload["base_revision"], str) and len(payload["base_revision"]) == 64, "base_revision_required")
        class_id = payload.get("class_id")
        code = payload["sign_code"]
        require(code is None or isinstance(code, str) and code in self.catalog, "unknown_sign_code")
        if class_id is not None:
            require(isinstance(class_id, str) and class_id in self.classes, "unknown_tsr_class")
            allowed = self.classes[class_id]["sign_codes"]
            require(code is None or code in allowed, "class_sign_code_mismatch")
        else:
            require(code is not None, "class_or_sign_code_required")
        target = identifier(payload["annotation_id"]) if payload["annotation_id"] is not None else str(uuid5(NAMESPACE, request_id))
        box = self.rectangle(payload["box_xyxy"])
        with self._lock, self.journal.exclusive():
            old = self.journal.get(request_id)
            if old:
                require(old["picture_id"] == picture_id and old["payload_sha256"] == digest(payload), "request_id_reused", 409)
                desired = json.loads(old["desired_json"])
                actual = self.call(self.client.annotation, target)
                if self.matches(actual, desired):
                    receipt = self.journal.finish(request_id, "confirmed", after=actual)
                    return self.confirmed_reply(picture_id, receipt)
                if old["status"] in ("prepared", "uncertain"):
                    raise AnnotationEditorError("submission_outcome_unknown", 409, uncertain=True)
                raise AnnotationEditorError("previous_correction_no_longer_current", 409)
            raw = self.raw_picture(picture_id)
            picture = self.normalize(raw)
            require(picture["revision"] == payload["base_revision"], "picture_revision_changed", 409)
            require(box[2] <= picture["width"] and box[3] <= picture["height"], "box_outside_picture")
            annotations = raw["properties"].get("annotations", [])
            before = next((r for r in annotations if r["id"] == target), None)
            if payload["annotation_id"] is not None:
                require(before is not None, "annotation_missing", 409)
                require(self.rectangle(before.get("shape")) == box, "existing_shape_edit_unsupported", 422)
                pairs = self.transport.payload_pairs(before)
                require(any(k in (KEY, CLASS_KEY) for k, _ in pairs), "existing_annotation_is_not_a_sign", 422)
            else:
                pairs = []
                for row in annotations:
                    try:
                        same = self.rectangle(row.get("shape")) == box
                    except AnnotationEditorError:
                        same = False
                    require(not same, "annotation_shape_already_exists", 409)
            semantics = [{"key": k, "value": v} for k, v in pairs if k not in (KEY, CLASS_KEY)]
            if code is not None:
                semantics.append({"key": KEY, "value": code})
            if class_id is not None:
                semantics.append({"key": CLASS_KEY, "value": class_id})
            desired = {"id": target, "picture_id": picture_id, "box_xyxy": box, "semantics": semantics}
            self.journal.prepare(request_id, payload, picture_id, target, before, desired)
            error = None
            try:
                if before is None:
                    response = self.call(self.client._request, "POST", "/api/pictures/" + picture_id + "/annotations",
                                         payload={"id": target, "shape": box, "semantics": semantics})
                    require(isinstance(response, dict) and response.get("id") == target, "annotation_shape_collision_uncertain", 409)
                else:
                    wanted = {(r["key"], r["value"]) for r in semantics}
                    delta = [{"action": "delete", "key": k, "value": v} for k, v in pairs
                             if k in (KEY, CLASS_KEY) and (k, v) not in wanted]
                    delta += [{"action": "add", "key": k, "value": v} for k, v in sorted(wanted - set(pairs))]
                    if delta:
                        self.call(self.client._request, "PATCH", "/api/annotations/" + target, payload={"semantics": delta})
                actual = self.call(self.client.annotation, target)
                require(self.matches(actual, desired), "annotation_write_not_verified", 409)
                receipt = self.journal.finish(request_id, "confirmed", after=actual)
                return self.confirmed_reply(picture_id, receipt)
            except AnnotationEditorError as caught:
                error = str(caught)
                if not caught.uncertain and caught.status in (400, 401, 403, 404, 422, 429):
                    self.journal.finish(request_id, "failed", error=error)
                    raise
                try:
                    actual = self.call(self.client.annotation, target)
                    if self.matches(actual, desired):
                        receipt = self.journal.finish(request_id, "confirmed", after=actual)
                        return self.confirmed_reply(picture_id, receipt)
                except AnnotationEditorError:
                    pass
                self.journal.finish(request_id, "uncertain", error=error)
                raise AnnotationEditorError("submission_outcome_unknown", 409, uncertain=True) from None
