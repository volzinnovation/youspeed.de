#!/usr/bin/env python3
"""GET-only Panoramax-Sammlung: unbewertete Box-Bündel und Schild-Crops.

Keine Annotationen schreiben, keine Klassen freigeben, keine Modelle ausführen.
Pillow wird erst beim Dekodieren geladen; --help benötigt keine Bildpakete.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import io
import json
import math
from pathlib import Path
import re
import shutil
import sys
import tempfile
import time
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urljoin, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
import uuid
import warnings

from prepare_dataset import canonical_bytes, load_classes


SCHEMA = "panoramax-course-collection-v1"
DEFAULT_INSTANCE = "https://panoramax.youspeed.de"
HERE = Path(__file__).resolve().parent
DETECTOR_CLASSES = {"sign": 0, "plate": 1, "face": 2}


class CrawlError(ValueError):
    pass


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def origin(url: str) -> tuple[str, str, int]:
    try:
        parsed = urlsplit(url)
        port = parsed.port or 443
    except ValueError as error:
        raise CrawlError("Ungültige URL/Portangabe.") from error
    if (parsed.scheme != "https" or not parsed.hostname or parsed.username
            or parsed.password or any(c in url for c in "\r\n\x00")):
        raise CrawlError("Nur HTTPS-URLs ohne Zugangsdaten sind erlaubt.")
    return parsed.scheme, parsed.hostname.lower(), port


def safe_url(url: str, base: str, expected_origin=None) -> str:
    if not isinstance(url, str) or not url:
        raise CrawlError("URL fehlt.")
    resolved = urljoin(base, url)
    if origin(resolved) != (expected_origin or origin(base)):
        raise CrawlError("Verweis/Redirect verlässt die gewählte HTTPS-Instanz.")
    if urlsplit(resolved).fragment:
        raise CrawlError("URL-Fragmente werden nicht als API-/Bildadressen akzeptiert.")
    return resolved


class SameOriginRedirect(HTTPRedirectHandler):
    def __init__(self, base):
        self.base = base

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        checked = safe_url(newurl, req.full_url, origin(self.base))
        return super().redirect_request(req, fp, code, msg, headers, checked)


class HttpClient:
    """TLS bleibt geprüft; urllib berücksichtigt SSL_CERT_FILE der Umgebung."""
    def __init__(self, base, timeout=30, retries=2, opener=None, sleep=time.sleep):
        self.base, self.timeout, self.retries = base, timeout, retries
        self.opener = opener or build_opener(SameOriginRedirect(base))
        self.sleep = sleep

    def get(self, url, max_bytes):
        url = safe_url(url, self.base)
        for attempt in range(self.retries + 1):
            request = Request(url, headers={"User-Agent": "YouSpeed-course-crawler/1.0",
                                           "Accept": "application/json,image/*"}, method="GET")
            try:
                with self.opener.open(request, timeout=self.timeout) as response:
                    safe_url(response.geturl(), self.base)
                    length = response.headers.get("Content-Length")
                    if length and (not length.isdigit() or int(length) > max_bytes):
                        raise CrawlError("Antwort überschreitet die Byte-Grenze.")
                    raw = response.read(max_bytes + 1)
                    if len(raw) > max_bytes:
                        raise CrawlError("Antwort überschreitet die Byte-Grenze.")
                    return raw
            except HTTPError as error:
                retry = error.code == 429 or 500 <= error.code < 600
                if not retry or attempt == self.retries:
                    raise CrawlError(f"HTTP {error.code}: {url}") from error
                retry_after = error.headers.get("Retry-After", "") if error.headers else ""
                delay = min(float(retry_after), 10.0) if retry_after.isdigit() else min(2 ** attempt, 10)
                error.close()
                self.sleep(delay)
            except (URLError, TimeoutError, OSError) as error:
                if attempt == self.retries:
                    raise CrawlError(f"GET fehlgeschlagen: {url}: {error}") from error
                self.sleep(min(2 ** attempt, 10))

    def json(self, url):
        def reject_constant(value):
            raise ValueError(f"Nichtendlicher JSON-Zahlenwert: {value}")
        try:
            value = json.loads(self.get(url, 8 * 1024 * 1024), parse_constant=reject_constant)
        except (ValueError, UnicodeError) as error:
            raise CrawlError(f"Keine gültige JSON-Antwort: {url}") from error
        if not isinstance(value, dict):
            raise CrawlError("API-Antwort muss ein JSON-Objekt sein.")
        return value


def object_id(value, kind="ID") -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, AttributeError, TypeError) as error:
        raise CrawlError(f"{kind} ist keine UUID.") from error


def page_next(payload, current_url, base):
    """Nur links des Seitenobjekts; niemals feature.links[next]."""
    links = payload.get("links", [])
    if not isinstance(links, list):
        raise CrawlError("Ungültige Seitenlinks.")
    candidates = [link.get("href") for link in links
                  if isinstance(link, dict) and link.get("rel") == "next"]
    if len(candidates) > 1:
        raise CrawlError("Mehrdeutige nächste API-Seite.")
    return safe_url(candidates[0], current_url, origin(base)) if candidates else None


def box_xyxy(shape, width, height):
    """Panoramax-Rasterpixel, keine EXIF-Drehung und kein Polygontraining."""
    if isinstance(shape, list) and len(shape) == 4:
        values = shape
    elif isinstance(shape, dict) and shape.get("type") == "Polygon":
        rings = shape.get("coordinates")
        if not isinstance(rings, list) or len(rings) != 1 or not isinstance(rings[0], list) or len(rings[0]) < 4:
            raise CrawlError("Ungültiges Box-Polygon.")
        points = rings[0]
        if any(not isinstance(p, (list, tuple)) or len(p) != 2 for p in points):
            raise CrawlError("Ungültige Polygonkoordinaten.")
        flat = [v for point in points for v in point]
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in flat):
            raise CrawlError("Nichtendliche Polygonkoordinaten.")
        values = [min(p[0] for p in points), min(p[1] for p in points),
                  max(p[0] for p in points), max(p[1] for p in points)]
    else:
        raise CrawlError("Annotation besitzt keine unterstützte Pixelbox.")
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in values):
        raise CrawlError("Nichtendliche Boxkoordinaten.")
    x1, y1, x2, y2 = map(float, values)
    if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise CrawlError("Box liegt außerhalb des HD-Rasters oder ist leer.")
    return [x1, y1, x2, y2]


def detector_class(annotation):
    explicit = annotation.get("detector_class", annotation.get("class"))
    candidates = {explicit} if isinstance(explicit, str) and explicit in DETECTOR_CLASSES else set()
    semantics = annotation.get("semantics", [])
    if not isinstance(semantics, list):
        raise CrawlError("Ungültige Annotation-Semantik.")
    # Nur eindeutige, explizite Quellenfelder auswerten. Keine nationale Klasse raten.
    if any(isinstance(tag, dict) and tag.get("key") == "osm|traffic_sign"
           and isinstance(tag.get("value"), str) and tag["value"] not in {"", "no"}
           for tag in semantics):
        candidates.add("sign")
    if len(candidates) > 1:
        raise CrawlError("Widersprüchliche Objektklasse.")
    return next(iter(candidates)) if candidates else None


def annotation_records(feature, width, height):
    raw = feature.get("properties", {}).get("annotations")
    if not isinstance(raw, list):
        raise CrawlError("Vollständige Annotation-Liste fehlt im Bildobjekt.")
    records, unknown, seen = [], [], set()
    for annotation in raw:
        if not isinstance(annotation, dict):
            raise CrawlError("Ungültiges Annotationsobjekt.")
        aid = object_id(annotation.get("id"), "Annotations-ID")
        if aid in seen:
            raise CrawlError("Doppelte Annotations-ID.")
        seen.add(aid)
        kind = detector_class(annotation)
        if kind is None:
            unknown.append(aid)
            continue
        records.append({"annotation_id": aid, "detector_class": kind,
                        "bbox_xyxy": box_xyxy(annotation.get("shape"), width, height)})
    return records, unknown


def yolo_labels(records, width, height):
    lines = []
    for record in records:
        x1, y1, x2, y2 = record["bbox_xyxy"]
        values = [(x1 + x2) / (2 * width), (y1 + y2) / (2 * height),
                  (x2 - x1) / width, (y2 - y1) / height]
        lines.append(str(DETECTOR_CLASSES[record["detector_class"]]) + " " +
                     " ".join(f"{v:.10f}" for v in values))
    return ("\n".join(lines) + ("\n" if lines else "")).encode("ascii")


def clean_rgb_image(raw, expected_size, max_pixels):
    try:
        from PIL import Image
    except ImportError as error:
        raise CrawlError("Pillow fehlt. Verwenden Sie die vorbereitete Kursumgebung.") from error
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(raw)) as opened:
                if opened.size != tuple(expected_size):
                    raise CrawlError("HD-Abmessungen stimmen nicht mit Annotationspixeln überein.")
                if opened.width * opened.height > max_pixels:
                    raise CrawlError("Bild überschreitet die Pixel-Grenze.")
                # Absichtlich KEIN ImageOps.exif_transpose: Annotationen liegen im Raster.
                rgb = opened.convert("RGB")
                return Image.frombytes("RGB", rgb.size, rgb.tobytes())
    except CrawlError:
        raise
    except Exception as error:
        raise CrawlError(f"Bild konnte nicht sicher dekodiert werden: {error}") from error


def png_bytes(image):
    target = io.BytesIO()
    image.save(target, format="PNG")
    return target.getvalue()


def class_folder_map(classes):
    result = {}
    for label in classes:
        folder = label.replace(":", "__")
        if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", folder) or folder in result:
            raise CrawlError("Klassenordner ist unsicher oder nicht eindeutig.")
        result[folder] = label
    return result


def write_manifest(output, manifest):
    value = dict(manifest)
    value["lock_sha256"] = digest(canonical_bytes(manifest))
    temporary = output / ".manifest.json.tmp"
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(output / "manifest.json")
    return value


def process_item(feature, item_url, base, output, client, args, on_image_attempt=None):
    if feature.get("type") != "Feature" or not isinstance(feature.get("properties"), dict):
        raise CrawlError("Kein vollständiges STAC-Bildobjekt.")
    pid = object_id(feature.get("id"), "Bild-ID")
    sid = object_id(feature.get("collection"), "Sequenz-ID")
    properties = feature["properties"]
    if properties.get("geovisio:status", "ready") != "ready":
        raise CrawlError("Bild ist noch nicht fertig verarbeitet.")
    if properties.get("geovisio:visibility", "anyone") not in {"anyone", "public"}:
        raise CrawlError("Kein öffentliches Bild.")
    camera = properties.get("pers:interior_orientation", {})
    fov = camera.get("field_of_view") if isinstance(camera, dict) else None
    if isinstance(fov, (int, float)) and fov >= 360:
        raise CrawlError("360-Grad-Bild benötigt eine eigene Perspektivprojektion.")
    dimensions = camera.get("sensor_array_dimensions") if isinstance(camera, dict) else None
    if (not isinstance(dimensions, list) or len(dimensions) != 2
            or any(isinstance(n, bool) or not isinstance(n, int) or n <= 0 for n in dimensions)):
        raise CrawlError("Verlässliche HD-Rasterabmessungen fehlen.")
    width, height = dimensions
    if width * height > args.max_pixels:
        raise CrawlError("Bild überschreitet die Pixel-Grenze.")
    license_name = properties.get("license")
    author = properties.get("geovisio:producer")
    if not isinstance(license_name, str) or not license_name or not author:
        raise CrawlError("Lizenz oder Urheber/Producer fehlt.")
    records, unknown = annotation_records(feature, width, height)
    if not records:
        raise CrawlError("Keine verwendbaren vorhandenen sign/plate/face-Annotationen; kein HD-Abruf.")
    asset = feature.get("assets", {}).get("hd", {})
    asset_url = safe_url(asset.get("href"), item_url, origin(base))
    source_url = item_url
    for link in feature.get("links", []):
        if isinstance(link, dict) and link.get("rel") == "self":
            source_url = safe_url(link.get("href"), item_url, origin(base))
            break
    if on_image_attempt:
        on_image_attempt()
    raw = client.get(asset_url, args.max_image_bytes)
    image = clean_rgb_image(raw, dimensions, args.max_pixels)
    image_raw = png_bytes(image)
    label_raw = yolo_labels(records, width, height)
    group = "sequence-" + sid
    bundle_path = "inbox/detector/" + pid
    item = {"picture_id": pid, "sequence_id": sid, "group_id": group,
            "width": width, "height": height, "image_sha256": digest(image_raw),
            "asset_sha256": digest(raw), "labels_sha256": digest(label_raw),
            "bundle_path": bundle_path, "source_url": source_url, "asset_url": asset_url,
            "license": license_name, "author": author, "annotations": records,
            "unknown_annotation_ids": unknown, "review_status": "unreviewed"}
    metadata = {"schema_version": SCHEMA, "review_status": "unreviewed",
                "eligible_for_training": False, "raster_orientation": "unchanged_no_exif_transpose",
                "detector_class_indices": DETECTOR_CLASSES, "item": dict(item),
                "original_item": feature}
    metadata_raw = (json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False) + "\n").encode()
    item["metadata_sha256"] = digest(metadata_raw)
    crops, crop_data = [], []
    original_annotations = {object_id(a["id"]): a for a in properties["annotations"]}
    for record in records:
        if record["detector_class"] != "sign":
            continue
        aid = record["annotation_id"]
        sample = "p" + pid + "_a" + aid
        box = record["bbox_xyxy"]
        pixel_box = [math.floor(box[0]), math.floor(box[1]), math.ceil(box[2]), math.ceil(box[3])]
        cropped = png_bytes(image.crop(pixel_box))
        tags = [tag for tag in original_annotations[aid].get("semantics", [])
                if isinstance(tag, dict) and isinstance(tag.get("key"), str) and tag["key"].startswith("osm|")]
        codes = {tag.get("value") for tag in tags if tag.get("key") == "osm|traffic_sign"
                 and isinstance(tag.get("value"), str)}
        suggestions = {"DE:310": "city:start", "DE:311": "city:end"}
        suggested = suggestions.get(next(iter(codes))) if len(codes) == 1 else None
        path = "inbox/classifier/" + sample + ".png"
        crops.append({"sample_id": sample, "picture_id": pid, "annotation_id": aid,
                      "group_id": group, "crop_sha256": digest(cropped), "crop_path": path,
                      "suggested_label": suggested, "osm_tags": tags,
                      "bbox_xyxy": box, "crop_pixel_box": pixel_box,
                      "review_status": "unreviewed", "eligible_for_training": False})
        crop_data.append((path, cropped))
    # Erst vollständig dekodieren/prüfen; danach ein ganzes Bildbündel atomar ablegen.
    staging = Path(tempfile.mkdtemp(prefix=".bundle-", dir=output))
    written_crops = []
    try:
        (staging / "image.png").write_bytes(image_raw)
        (staging / "labels.txt").write_bytes(label_raw)
        (staging / "metadata.json").write_bytes(metadata_raw)
        for path, data in crop_data:
            target = output / path
            target.write_bytes(data)
            written_crops.append(target)
        staging.replace(output / bundle_path)
    except BaseException:
        for path in written_crops:
            path.unlink(missing_ok=True)
        shutil.rmtree(staging, ignore_errors=True)
        raise
    return item, crops


def crawl(args, client=None):
    base = args.instance.rstrip("/") + "/"
    origin(base)
    classes, class_raw = load_classes(args.classes, require_136=True)
    folders = class_folder_map(classes)
    if args.output.exists():
        raise CrawlError("Ausgabeordner existiert bereits. Für einen neuen Crawl einen neuen --output wählen.")
    args.output.mkdir(parents=True)
    for relative in ["inbox/classifier", "inbox/detector", "approved/detector", "rejected/classifier", "rejected/detector"]:
        (args.output / relative).mkdir(parents=True)
    for folder in folders:
        (args.output / "approved/classifier" / folder).mkdir(parents=True)
    state = {"complete_inventory": False, "explicit_selection": bool(args.item_url or args.collection),
             "max_items": args.max_items, "max_images": args.max_images, "max_pages": args.max_pages,
             "pages_fetched": 0, "items_seen": 0, "image_attempts": 0,
             "limits_reached": [], "errors": [], "skipped": [], "duplicate_items": 0}
    manifest = {"schema_version": SCHEMA, "created_at": datetime.now(timezone.utc).isoformat(),
                "instance": base.rstrip("/"), "class_folders": folders,
                "class_index_sha256": digest(class_raw), "items": [], "crops": [], "crawl": state,
                "review_required": True, "detector_class_indices": DETECTOR_CLASSES,
                "grouping_note": "Sequenzen vorgruppiert; gleiche Tafeln über mehrere Sequenzen und Nahe-Duplikate müssen vor dem Split gemeinsam gruppiert werden."}
    write_manifest(args.output, manifest)
    client = client or HttpClient(base, args.timeout, args.retries)
    seen_items, seen_pages = set(), set()

    def limit(name):
        if name not in state["limits_reached"]:
            state["limits_reached"].append(name)

    def pages(first, key):
        current = safe_url(first, base)
        while current:
            if current in seen_pages:
                raise CrawlError("Zyklische API-Seitenpagination.")
            if state["pages_fetched"] >= args.max_pages:
                limit("max_pages")
                return
            seen_pages.add(current)
            state["pages_fetched"] += 1
            payload = client.json(current)
            rows = payload.get(key)
            if not isinstance(rows, list):
                raise CrawlError(f"API-Seite enthält keine Liste {key!r}.")
            yield rows, current
            current = page_next(payload, current, base)

    def accept(feature, page_url, sequence=None, full=False):
        pid = object_id(feature.get("id"), "Bild-ID")
        if pid in seen_items:
            state["duplicate_items"] += 1
            return True
        if state["items_seen"] >= args.max_items:
            limit("max_items")
            return False
        seen_items.add(pid)
        state["items_seen"] += 1
        if state["image_attempts"] >= args.max_images:
            limit("max_images")
            state["skipped"].append({"picture_id": pid, "reason": "max_images"})
            return True
        sid = object_id(feature.get("collection", sequence), "Sequenz-ID")
        item_url = safe_url("api/collections/" + sid + "/items/" + pid, base)
        for link in feature.get("links", []):
            if isinstance(link, dict) and link.get("rel") == "self":
                item_url = safe_url(link.get("href"), page_url, origin(base))
                break
        # Listenantworten können Annotationen auslassen. Vollständiges Bild erneut lesen.
        detailed = feature if full else client.json(item_url)
        if object_id(detailed.get("id")) != pid or object_id(detailed.get("collection")) != sid:
            raise CrawlError("Bildidentität änderte sich beim Detailabruf.")
        try:
            def count_image_attempt():
                state["image_attempts"] += 1
            item, crops = process_item(detailed, item_url, base, args.output, client, args,
                                       on_image_attempt=count_image_attempt)
            manifest["items"].append(item)
            manifest["crops"].extend(crops)
        except CrawlError as error:
            state["skipped"].append({"picture_id": pid, "reason": str(error)})
        write_manifest(args.output, manifest)
        if state["image_attempts"] >= args.max_images:
            limit("max_images")
            return False
        if state["items_seen"] >= args.max_items:
            limit("max_items")
            return False
        return True

    try:
        if args.item_url:
            for url in args.item_url:
                url = safe_url(url, base)
                feature = client.json(url)
                if not accept(feature, url, full=True):
                    break
        else:
            def sequence_ids():
                if args.collection:
                    for value in args.collection:
                        yield object_id(value, "Sammlungs-ID")
                else:
                    # Schon nach der ersten Sammlungsseite Bilder verarbeiten;
                    # sonst könnte die Inventarliste das Seitenbudget allein verbrauchen.
                    for rows, _ in pages("api/collections?limit=100", "collections"):
                        for collection in rows:
                            yield object_id(collection.get("id"), "Sammlungs-ID")
            seen_sequences = set()
            for sid in sequence_ids():
                if sid in seen_sequences:
                    continue
                seen_sequences.add(sid)
                exhausted = False
                for rows, page_url in pages("api/collections/" + quote(sid) + "/items?limit=100", "features"):
                    for feature in rows:
                        if not accept(feature, page_url, sid):
                            exhausted = True
                            break
                    if exhausted:
                        break
                if exhausted or "max_pages" in state["limits_reached"]:
                    break
        state["complete_inventory"] = not (state["explicit_selection"] or state["limits_reached"]
                                             or state["errors"] or state["skipped"])
    except (ValueError, OSError, KeyError, TypeError, AttributeError) as error:
        state["errors"].append({"reason": str(error)})
    except KeyboardInterrupt:
        state["errors"].append({"reason": "Vom Nutzer unterbrochen; Sammlung unvollständig."})
        write_manifest(args.output, manifest)
        raise
    finally:
        manifest = write_manifest(args.output, manifest)
    return manifest


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument("--instance", default=DEFAULT_INSTANCE)
    selection = result.add_mutually_exclusive_group()
    selection.add_argument("--collection", action="append", default=[], help="Sammlungs-UUID; wiederholbar")
    selection.add_argument("--item-url", action="append", default=[], help="Gezieltes Bildobjekt derselben HTTPS-Instanz; wiederholbar")
    result.add_argument("--output", type=Path, default=Path("data/collection"))
    result.add_argument("--classes", type=Path, default=HERE / "class-index.json")
    result.add_argument("--max-items", type=int, default=2000)
    result.add_argument("--max-images", type=int, default=100)
    result.add_argument("--max-pages", type=int, default=100)
    result.add_argument("--max-image-bytes", type=int, default=32 * 1024 * 1024)
    result.add_argument("--max-pixels", type=int, default=40_000_000)
    result.add_argument("--timeout", type=float, default=30)
    result.add_argument("--retries", type=int, default=2)
    return result


def main(argv=None):
    args = parser().parse_args(argv)
    if any(not math.isfinite(value) or value <= 0 for value in [args.max_items, args.max_images, args.max_pages,
                                    args.max_image_bytes, args.max_pixels, args.timeout]) or not 0 <= args.retries <= 5:
        print("FEHLER: Grenzen müssen positiv sein; retries muss zwischen 0 und 5 liegen.", file=sys.stderr)
        return 2
    try:
        manifest = crawl(args)
    except (CrawlError, OSError, ValueError) as error:
        print(f"FEHLER: {error}", file=sys.stderr)
        return 2
    print(f"{len(manifest['items'])} Bildbündel, {len(manifest['crops'])} ungeprüfte Crops. "
          f"Vollinventar: {manifest['crawl']['complete_inventory']}. {args.output / 'manifest.json'}")
    print("Prüfen Sie Klasse/Eignung und ALLE sign/plate/face-Boxen manuell; nichts ist automatisch freigegeben.")
    return 2 if manifest["crawl"]["errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
