"""Serve a local place review and its admitted Panoramax pictures."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from http.client import HTTPException
import io
import json
import math
import os
import re
import stat
from threading import BoundedSemaphore
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit
from urllib.request import Request
from uuid import UUID


ROUTE = "/inspector/api/place-sign-review"
SOURCE_ID = "panoramax.woladen.de"
ORIGIN = f"https://{SOURCE_ID}"
PANORAMAX_HOSTS = {SOURCE_ID, "panoramax.youspeed.de"}
MAX_SNAPSHOT_BYTES = 16 * 1024**2
MAX_METADATA_BYTES = 2 * 1024**2
MAX_SOURCE_BYTES = 25 * 1024**2
MAX_OUTPUT_BYTES = 5 * 1024**2
MAX_SOURCE_PIXELS = 40_000_000
MAX_GROUPS = 2500
MAX_REFERENCES = 6000
MAX_FOLLOW_ON_OFFSET = 8
VISIBILITIES = {"anyone", "logged-only", "owner-only"}
SIGN_CODE = re.compile(r"DE:[0-9]{3,4}(?:[.-][0-9]{1,3})*")


class PlaceSignReviewError(Exception):
    def __init__(self, message, status=503):
        self.status = status
        super().__init__(message)


@dataclass(frozen=True)
class ImageReference:
    picture: str
    annotation: str
    dimensions: tuple[int, int]
    box: tuple[int, int, int, int]
    public: bool
    sign_code: str


def canonical_uuid(value):
    if not isinstance(value, str) or str(UUID(value)) != value:
        raise ValueError("invalid image identifier")
    return value


def private_bytes(path, limit, *, dir_fd=None):
    flags = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
    with os.fdopen(os.open(path, flags, dir_fd=dir_fd), "rb") as file:
        info = os.fstat(file.fileno())
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o077
            or not 0 < info.st_size <= limit
        ):
            raise ValueError("expected a bounded owner-only file")
        data = file.read(limit + 1)
    if len(data) > limit:
        raise ValueError("private file exceeded its size limit")
    return data


def reference(observation, sign_code):
    picture = canonical_uuid(observation["image_id"])
    annotation = canonical_uuid(observation["annotation_id"])
    width, height = observation["image_width"], observation["image_height"]
    box = observation["box_xyxy"]
    access = (
        observation["item_visibility"],
        observation["picture_visibility"],
        observation["sequence_visibility"],
    )
    if (
        observation["source_id"] != SOURCE_ID
        or observation.get("projection", "flat") != "flat"
        or observation.get("box_wrap", False) is not False
        or type(width) is not int
        or type(height) is not int
        or width < 1
        or height < 1
        or width * height > MAX_SOURCE_PIXELS
        or not isinstance(box, list)
        or len(box) != 4
        or any(type(value) is not int for value in box)
        or any(value not in VISIBILITIES for value in access)
    ):
        raise ValueError("invalid picture registration")
    left, top, right, bottom = box
    if not (0 <= left < right <= width and 0 <= top < bottom <= height):
        raise ValueError("invalid picture box")
    return ImageReference(
        picture,
        annotation,
        (width, height),
        tuple(box),
        access == ("anyone",) * 3,
        sign_code,
    )


def capture_time(observation):
    timestamp = datetime.fromisoformat(
        observation["captured_at"].replace("Z", "+00:00")
    )
    if timestamp.utcoffset() is None:
        raise ValueError("capture time lacks a timezone")
    return timestamp


def follow_on_entries(group, entries):
    follow_on = group.get("follow_on_observations", [])
    if not isinstance(follow_on, list):
        raise ValueError("invalid follow-on observations")
    if not follow_on:
        return follow_on
    anchors = {
        canonical_uuid(observation["image_id"]): observation for observation in entries
    }
    if len(anchors) != len(entries):
        raise ValueError("duplicate follow-on anchor image")
    seen_targets = set()
    by_anchor = {}
    for observation in follow_on:
        anchor_id = canonical_uuid(observation["anchor_image_id"])
        target = canonical_uuid(observation["image_id"])
        anchor = anchors.get(anchor_id)
        if anchor is None or target in anchors or target in seen_targets:
            raise ValueError("invalid follow-on photo membership")
        seen_targets.add(target)
        rank = observation["sequence_rank"]
        anchor_rank = anchor.get("sequence_rank")
        offset = observation["frame_offset"]
        if (
            canonical_uuid(observation["sequence_id"]) != anchor["sequence_id"]
            or type(rank) is not int
            or type(anchor_rank) is not int
            or type(offset) is not int
            or not 0 <= anchor_rank < rank <= 2**31 - 1
            or not 1 <= offset <= MAX_FOLLOW_ON_OFFSET
            or rank != anchor_rank + offset
        ):
            raise ValueError("invalid follow-on sequence or rank")
        timestamp = capture_time(observation)
        if timestamp <= capture_time(anchor):
            raise ValueError("follow-on photo precedes its anchor")
        by_anchor.setdefault(anchor_id, []).append((rank, timestamp))
    for ordered in by_anchor.values():
        ordered.sort()
        if any(
            a_rank >= b_rank or a_time >= b_time
            for (a_rank, a_time), (b_rank, b_time) in zip(ordered, ordered[1:])
        ):
            raise ValueError("conflicting follow-on order")
    return follow_on


def load_snapshot(path, local_media):
    def reject_constant(value):
        raise ValueError(value)

    def finite_float(value):
        result = float(value)
        if not math.isfinite(result):
            raise ValueError("non-finite number")
        return result

    try:
        document = json.loads(
            private_bytes(path, MAX_SNAPSHOT_BYTES),
            parse_constant=reject_constant,
            parse_float=finite_float,
        )
        groups = document["groups"]
        if (
            type(document["schema_version"]) is not int
            or document["schema_version"] != 1
            or not isinstance(document["place"], dict)
            or not isinstance(document["summary"], dict)
            or not isinstance(groups, list)
            or len(groups) > MAX_GROUPS
        ):
            raise ValueError("invalid review document")
        known = {}
        identifiers = set()
        observations = 0
        for group in groups:
            key = group["id"]
            sign_code = group["sign_code"]
            if (
                not isinstance(key, str)
                or not re.fullmatch(r"[a-zA-Z0-9_.:-]{1,100}", key)
                or key in identifiers
                or not isinstance(sign_code, str)
                or not SIGN_CODE.fullmatch(sign_code)
            ):
                raise ValueError("invalid group identity")
            identifiers.add(key)
            entries = group["observations"]
            if not isinstance(entries, list):
                raise ValueError("invalid group observations")
            entries = entries + follow_on_entries(group, entries)
            mobile = group.get("mobile_observations", [])
            if not isinstance(mobile, list) or len(mobile) > 100:
                raise ValueError("invalid mobile observations")
            refinement = group.get("mobile_refinement")
            if refinement is not None and (
                not document.get("mobile_reference")
                or not set(refinement.get("mobile_evidence_ids", ())) <= {row["evidence_id"] for row in mobile}
            ):
                raise ValueError("invalid mobile refinement")
            for observation in mobile:
                if (
                    observation.get("source_id") != "mobile"
                    or observation.get("mobile_kind") not in {"crop", "sighting"}
                    or not re.fullmatch(r"mobile:[a-z-]+:[0-9a-f]{64}", observation.get("evidence_id", ""))
                    or observation.get("association", {}).get("status") != "proposed"
                ):
                    raise ValueError("invalid mobile evidence")
                binding = observation.get("source_binding")
                if binding is not None:
                    canonical_uuid(binding["installation"])
                    canonical_uuid(binding["event_id"])
                    if type(binding["epoch"]) is not int or binding["epoch"] < 0:
                        raise ValueError("invalid mobile epoch")
                    if observation["mobile_kind"] == "crop":
                        canonical_uuid(binding["crop_id"])
                    if not re.fullmatch(r"[0-9a-f]{64}", binding["event_sha256"]):
                        raise ValueError("invalid source digest")
                observation.pop("photo_url", None)
                observation.pop("crop_url", None)
            observations += len(mobile)
            observations += len(entries)
            if observations > MAX_REFERENCES:
                raise ValueError("too many review observations")
            for observation in entries:
                item = reference(observation, sign_code)
                if item.annotation in known and known[item.annotation] != item:
                    raise ValueError("conflicting annotation registration")
                known[item.annotation] = item
                for variant in ("photo", "crop"):
                    observation[f"{variant}_url"] = (
                        f"{ROUTE}/images/{item.annotation}/{variant}"
                        if item.public or local_media
                        else None
                    )
        default = document["default_group_id"]
        if (groups and default not in identifiers) or (
            not groups and default is not None
        ):
            raise ValueError("invalid default group")
    except (
        AttributeError,
        KeyError,
        TypeError,
        ValueError,
        OSError,
        RecursionError,
    ) as error:
        raise PlaceSignReviewError(
            "Datei für die Ortsprüfung ist nicht lesbar oder ungültig."
        ) from error
    return document, known


def native_box(shape):
    if isinstance(shape, dict):
        if shape.get("type") != "Polygon" or shape.get("wrap"):
            raise ValueError("unsupported annotation geometry")
        rings = shape["coordinates"]
        if not isinstance(rings, list) or not 1 <= len(rings) <= 16:
            raise ValueError("invalid annotation rings")
        points = []
        for ring in rings:
            if (
                not isinstance(ring, list)
                or not 4 <= len(ring) <= 128
                or ring[0] != ring[-1]
            ):
                raise ValueError("invalid annotation ring")
            points.extend(ring)
        if not all(
            isinstance(point, list)
            and len(point) == 2
            and all(
                type(value) in (int, float) and math.isfinite(value) for value in point
            )
            for point in points
        ):
            raise ValueError("invalid annotation vertices")
        xs, ys = zip(*points)
        shape = [min(xs), min(ys), max(xs), max(ys)]
    if (
        not isinstance(shape, list)
        or len(shape) != 4
        or any(
            type(value) not in (int, float) or not math.isfinite(value)
            for value in shape
        )
    ):
        raise ValueError("invalid annotation coordinates")
    return tuple(
        convert(value)
        for convert, value in zip((math.floor, math.floor, math.ceil, math.ceil), shape)
    )


def asset_path(picture_id):
    return "/permanent/" + "/".join(
        [picture_id[i : i + 2] for i in range(0, 8, 2)] + [picture_id[9:] + ".jpg"]
    )


def local_picture(media_dir, picture_id):
    """Read the same owner-only original for review and live annotation editing."""
    if media_dir is None:
        return None
    canonical_uuid(picture_id)
    try:
        fd = os.open(media_dir, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            info = os.fstat(fd)
            if info.st_uid != os.getuid() or info.st_mode & 0o077:
                raise ValueError("image directory must be owner-only")
            try:
                return private_bytes(picture_id + ".jpg", MAX_SOURCE_BYTES, dir_fd=fd)
            except FileNotFoundError:
                return None
        finally:
            os.close(fd)
    except (ValueError, OSError) as error:
        raise PlaceSignReviewError("Privates Bildverzeichnis ist nicht lesbar oder ungültig.") from error


class PlaceSignReviewStore:
    def __init__(self, path, *, opener, media_dir=None, mobile_admitter=None):
        self.path = path
        self.opener = opener
        self.media_dir = media_dir
        self.mobile_admitter = mobile_admitter
        self.slots = BoundedSemaphore(3)

    def get(self):
        document = load_snapshot(self.path, self.media_dir is not None)[0]
        if document.get("mobile_reference"):
            if self.mobile_admitter:
                self.mobile_admitter(document)
            else:
                for group in document["groups"]:
                    group.pop("mobile_observations", None)
                    group.pop("mobile_refinement", None)
                document["mobile_reference"]["availability"] = "unconfigured"
        return document

    def image(self, annotation, variant):
        _, images = load_snapshot(self.path, self.media_dir is not None)
        item = images.get(annotation)
        if item is None or variant not in ("photo", "crop"):
            raise PlaceSignReviewError("Unbekanntes Bild für die Ortsprüfung.", 404)
        if not self.slots.acquire(timeout=10):
            raise PlaceSignReviewError("Bildvorschau ist ausgelastet.")
        try:
            raw = self.local_photo(item)
            if raw is None:
                if not item.public:
                    raise PlaceSignReviewError(
                        "Dieses Bild ist lokal nicht verfügbar.", 404
                    )
                raw = self.public_photo(item)
            return render(raw, item, variant)
        finally:
            self.slots.release()

    def local_photo(self, item):
        return local_picture(self.media_dir, item.picture)

    def upstream(self, path, accepted, limit):
        request = Request(
            ORIGIN + path,
            headers={
                "Accept": ", ".join(accepted),
                "Accept-Encoding": "identity",
                "Cache-Control": "no-cache",
                "User-Agent": "YouSpeed-Inspector-PlaceReview/1.0",
            },
        )
        try:
            with self.opener.open(request, timeout=8) as response:
                if (
                    response.status != 200
                    or response.headers.get_content_type() not in accepted
                    or response.headers.get("Content-Encoding", "identity").lower()
                    != "identity"
                ):
                    raise PlaceSignReviewError(
                        "Panoramax lieferte ein ungültiges Bildformat.", 502
                    )
                length = response.headers.get("Content-Length")
                if length is not None and (
                    not length.isdecimal() or int(length) > limit
                ):
                    raise PlaceSignReviewError("Panoramax-Bild ist zu groß.", 502)
                data = response.read(limit + 1)
        except HTTPError as error:
            if error.code in (401, 403, 404, 410):
                raise PlaceSignReviewError(
                    "Panoramax-Aufnahme ist nicht öffentlich verfügbar.", 404
                ) from None
            raise PlaceSignReviewError(
                "Panoramax-Bildquelle ist derzeit nicht erreichbar."
            ) from None
        except (URLError, OSError, HTTPException):
            raise PlaceSignReviewError(
                "Panoramax-Bildquelle ist derzeit nicht erreichbar."
            ) from None
        if not 0 < len(data) <= limit:
            raise PlaceSignReviewError("Panoramax lieferte ein ungültiges Bild.", 502)
        return data

    def public_photo(self, item):
        metadata = self.upstream(
            f"/api/pictures/{item.picture}",
            ("application/json", "application/geo+json"),
            MAX_METADATA_BYTES,
        )
        path = asset_path(item.picture)
        try:
            current = json.loads(metadata)
            properties = current["properties"]
            if current["id"] != item.picture or current["type"] != "Feature":
                raise ValueError("picture identity")
            if (
                properties.get("geovisio:visibility") != "anyone"
                or properties.get("geovisio:status") != "ready"
            ):
                raise PlaceSignReviewError(
                    "Panoramax-Aufnahme ist nicht öffentlich verfügbar.", 404
                )
            annotations = [
                entry
                for entry in properties["annotations"]
                if entry.get("id") == item.annotation
            ]
            if (
                len(annotations) != 1
                or native_box(annotations[0]["shape"]) != item.box
                or {
                    tag["value"].strip().upper()
                    for tag in annotations[0]["semantics"]
                    if tag["key"] == "osm|traffic_sign"
                    and tag["value"].strip().upper() != "YES"
                }
                != {item.sign_code}
                or properties["pers:interior_orientation"]["sensor_array_dimensions"]
                != list(item.dimensions)
            ):
                raise ValueError("annotation registration")
            hd = current["assets"]["hd"]
            url = urlsplit(urljoin(ORIGIN + "/", hd["href"]))
            if (
                url.scheme != "https"
                or url.hostname not in PANORAMAX_HOSTS
                or url.port not in (None, 443)
                or url.username is not None
                or url.password is not None
                or url.query
                or url.fragment
                or url.path != path
                or hd.get("type") != "image/jpeg"
            ):
                raise ValueError("unexpected asset origin or path")
        except (
            AttributeError,
            KeyError,
            TypeError,
            ValueError,
            OverflowError,
            RecursionError,
        ) as error:
            raise PlaceSignReviewError(
                "Panoramax-Aufnahme oder Markierung stimmt nicht mehr mit dem Prüfdatenstand überein.",
                409,
            ) from error
        return self.upstream(path, ("image/jpeg",), MAX_SOURCE_BYTES)


def render(raw, item, variant):
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError:
        raise PlaceSignReviewError("Bildvorschau benötigt Pillow.") from None
    output = io.BytesIO()
    try:
        with Image.open(io.BytesIO(raw), formats=("JPEG",)) as image:
            if image.size != item.dimensions or image.getexif().get(274, 1) != 1:
                raise PlaceSignReviewError(
                    "Bildabmessungen stimmen nicht mit dem Prüfdatenstand überein.", 409
                )
            pixels = image.crop(item.box) if variant == "crop" else image
            pixels.thumbnail((640, 640) if variant == "crop" else (1440, 1440))
            rendered = Image.new("RGB", pixels.size)
            rendered.paste(pixels)
            if variant == "crop":
                rendered.save(output, "PNG")
                mime = "image/png"
            else:
                rendered.save(output, "JPEG", quality=85)
                mime = "image/jpeg"
    except (
        UnidentifiedImageError,
        Image.DecompressionBombError,
        OSError,
        ValueError,
    ) as error:
        raise PlaceSignReviewError(
            "Panoramax lieferte ein ungültiges Bild.", 502
        ) from error
    data = output.getvalue()
    if not 0 < len(data) <= MAX_OUTPUT_BYTES:
        raise PlaceSignReviewError("Bildvorschau ist zu groß.", 502)
    return data, mime
