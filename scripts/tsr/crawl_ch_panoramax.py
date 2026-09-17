#!/usr/bin/env python3
"""Crawl Swiss Panoramax metadata and build a reviewable CH sign-crop queue.

The job is deliberately metadata/provenance first. It only downloads public
blurred derivatives after a feature has been admitted to the deduplicated
queue, and it never writes annotations back to Panoramax.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import io
import json
import math
from pathlib import Path
import time
from typing import Any
from urllib.parse import urlparse

import requests


API = "https://api.panoramax.xyz/api/search"
DEFAULT_BBOX = (5.9, 45.8, 10.6, 47.9)
USER_AGENT = "youspeed-ch-tsr-panoramax-research/1.0"


def atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".part")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def parse_bbox(value: str) -> tuple[float, float, float, float]:
    parts = tuple(float(item) for item in value.split(","))
    if len(parts) != 4 or parts[0] >= parts[2] or parts[1] >= parts[3]:
        raise argparse.ArgumentTypeError("bbox must be min_lon,min_lat,max_lon,max_lat")
    return parts


def tile_key(bbox: tuple[float, float, float, float]) -> str:
    return ",".join(f"{item:.7f}" for item in bbox)


def split_bbox(bbox: tuple[float, float, float, float]) -> list[tuple[float, float, float, float]]:
    min_lon, min_lat, max_lon, max_lat = bbox
    mid_lon = (min_lon + max_lon) / 2
    mid_lat = (min_lat + max_lat) / 2
    return [
        (min_lon, min_lat, mid_lon, mid_lat),
        (mid_lon, min_lat, max_lon, mid_lat),
        (min_lon, mid_lat, mid_lon, max_lat),
        (mid_lon, mid_lat, max_lon, max_lat),
    ]


def initial_tiles(bbox: tuple[float, float, float, float], degrees: float) -> list[tuple[float, float, float, float]]:
    min_lon, min_lat, max_lon, max_lat = bbox
    tiles = []
    lon = min_lon
    while lon < max_lon:
        next_lon = min(max_lon, lon + degrees)
        lat = min_lat
        while lat < max_lat:
            next_lat = min(max_lat, lat + degrees)
            tiles.append((lon, lat, next_lon, next_lat))
            lat = next_lat
        lon = next_lon
    return tiles


def fetch_tile(
    session: requests.Session,
    bbox: tuple[float, float, float, float],
    limit: int,
    delay: float,
    retry_attempts: int,
) -> dict[str, Any]:
    last_error = "unknown request failure"
    for attempt in range(1, retry_attempts + 1):
        if delay:
            time.sleep(delay)
        try:
            response = session.get(
                API,
                params={"bbox": ",".join(str(item) for item in bbox), "limit": limit, "sortby": "+id"},
                timeout=(20, 180),
            )
            response.raise_for_status()
            value = response.json()
            if not isinstance(value, dict) or not isinstance(value.get("features"), list):
                raise RuntimeError("Panoramax search response is not a FeatureCollection")
            return value
        except (requests.RequestException, ValueError, RuntimeError) as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            if attempt < retry_attempts:
                time.sleep(min(30, 2 ** (attempt - 1)))
    raise RuntimeError(f"skipped after {retry_attempts} attempts: {last_error}")


def crawl(
    session: requests.Session,
    output: Path,
    bbox: tuple[float, float, float, float],
    tile_degrees: float,
    limit: int,
    max_depth: int,
    delay: float,
    retry_attempts: int,
) -> tuple[list[dict[str, Any]], list[str], list[dict[str, Any]], list[dict[str, Any]]]:
    cache = output / "tiles"
    cache.mkdir(parents=True, exist_ok=True)
    features: dict[str, dict[str, Any]] = {}
    saturated: list[str] = []
    skipped: list[dict[str, Any]] = []
    subdivided_failures: list[dict[str, Any]] = []
    pending = [(tile, 0) for tile in initial_tiles(bbox, tile_degrees)]
    while pending:
        tile, depth = pending.pop()
        key = tile_key(tile)
        cache_path = cache / (hashlib.sha256(key.encode()).hexdigest()[:20] + ".json")
        if cache_path.is_file():
            payload = json.loads(cache_path.read_text(encoding="utf-8"))
        else:
            try:
                payload = fetch_tile(session, tile, limit, delay, retry_attempts)
            except RuntimeError as exc:
                failure = {"bbox": list(tile), "depth": depth, "error": str(exc)}
                if depth < max_depth:
                    subdivided_failures.append(failure)
                    pending.extend((child, depth + 1) for child in split_bbox(tile))
                else:
                    skipped.append(failure)
                continue
            atomic_json(cache_path, {"bbox": tile, "depth": depth, "payload": payload})
        if "payload" in payload:
            payload = payload["payload"]
        rows = payload.get("features", [])
        if len(rows) >= limit and depth < max_depth:
            pending.extend((child, depth + 1) for child in split_bbox(tile))
            continue
        if len(rows) >= limit:
            saturated.append(key)
        for row in rows:
            if isinstance(row, dict) and row.get("id"):
                features[str(row["id"])] = row
    return list(features.values()), saturated, skipped, subdivided_failures


def asset_url(feature: dict[str, Any], asset_key: str) -> str | None:
    assets = feature.get("assets")
    if isinstance(assets, dict) and isinstance(assets.get(asset_key), dict):
        value = assets[asset_key].get("href")
        if isinstance(value, str):
            return value
    properties = feature.get("properties") or {}
    fallback = properties.get("geovisio:thumbnail") or properties.get("geovisio:image")
    return fallback if isinstance(fallback, str) else None


def normalize(feature: dict[str, Any], asset_key: str) -> dict[str, Any]:
    properties = feature.get("properties") or {}
    geometry = feature.get("geometry") or {}
    coords = geometry.get("coordinates") or []
    providers = feature.get("providers") or []
    return {
        "id": str(feature["id"]),
        "collection": str(feature.get("collection") or ""),
        "rank_in_collection": properties.get("geovisio:rank_in_collection"),
        "datetime": properties.get("datetime"),
        "coordinates": list(coords[:2]) if isinstance(coords, list) and len(coords) >= 2 else None,
        "providers": [str(item.get("name")) for item in providers if isinstance(item, dict) and item.get("name")],
        "license": properties.get("license"),
        "visibility": properties.get("geovisio:visibility"),
        "image_url": asset_url(feature, asset_key),
        "source_item_url": next((link.get("href") for link in feature.get("links", []) if link.get("rel") == "self"), None),
        "source_instance_url": next((link.get("href") for link in feature.get("links", []) if link.get("rel") == "via"), None),
    }


def parse_datetime(value: Any) -> float | None:
    if not isinstance(value, str):
        return None
    try:
        from datetime import datetime
        return datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return None


def distance_meters(first: list[float] | None, second: list[float] | None) -> float:
    if not first or not second:
        return math.inf
    lat = math.radians((first[1] + second[1]) / 2)
    dx = (second[0] - first[0]) * 111320 * math.cos(lat)
    dy = (second[1] - first[1]) * 110540
    return math.hypot(dx, dy)


def deduplicate(rows: list[dict[str, Any]], frame_stride: int, distance_stride: float) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[row["collection"]].append(row)
    selected = []
    for collection, items in grouped.items():
        items.sort(key=lambda row: (row["rank_in_collection"] is None, row["rank_in_collection"] or 0, row["datetime"] or "", row["id"]))
        last_rank = None
        last_coords = None
        last_time = None
        for row in items:
            rank = row["rank_in_collection"] if isinstance(row["rank_in_collection"], int) else None
            timestamp = parse_datetime(row["datetime"])
            rank_ok = last_rank is None or rank is None or rank - last_rank >= frame_stride
            distance_ok = last_coords is None or distance_meters(last_coords, row["coordinates"]) >= distance_stride
            time_ok = last_time is None or timestamp is None or last_time is None or timestamp - last_time >= 5
            if last_rank is not None and rank is not None and rank - last_rank < frame_stride and not distance_ok and not time_ok:
                continue
            if not rank_ok and not distance_ok and not time_ok:
                continue
            selected.append(row)
            last_rank, last_coords, last_time = rank, row["coordinates"], timestamp
    selected.sort(key=lambda row: (row["datetime"] or "", row["collection"], row["id"]))
    return selected


def download(session: requests.Session, row: dict[str, Any], path: Path, max_bytes: int) -> tuple[bool, str | None]:
    url = row.get("image_url")
    if not isinstance(url, str) or urlparse(url).scheme != "https":
        return False, "missing_or_non_https_derivative"
    if any(marker in url.lower() for marker in ("original", "raw", "unblurred")):
        return False, "refused_non_blurred_asset_url"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_file():
        return True, None
    temporary = path.with_suffix(path.suffix + ".part")
    try:
        with session.get(url, stream=True, timeout=(20, 180)) as response:
            response.raise_for_status()
            size = 0
            with temporary.open("wb") as handle:
                for chunk in response.iter_content(1024 * 256):
                    size += len(chunk)
                    if size > max_bytes:
                        raise RuntimeError("derivative exceeds byte limit")
                    handle.write(chunk)
        from PIL import Image
        with Image.open(temporary) as image:
            image.verify()
        temporary.replace(path)
        return True, None
    except Exception as exc:
        temporary.unlink(missing_ok=True)
        return False, f"{type(exc).__name__}:{exc}"


def detect_crops(rows: list[dict[str, Any]], output: Path, model_path: str, device: str, imgsz: int, conf: float, batch: int) -> int:
    from PIL import Image
    from ultralytics import YOLO

    model = YOLO(model_path)
    image_paths = [output / "images" / f"{row['id']}.jpg" for row in rows if (output / "images" / f"{row['id']}.jpg").is_file()]
    by_id = {path.stem: row for path, row in zip(image_paths, [row for row in rows if (output / "images" / f"{row['id']}.jpg").is_file()])}
    crops_dir = output / "crops"
    crops_dir.mkdir(parents=True, exist_ok=True)
    ledger = output / "candidates.jsonl"
    existing = set()
    if ledger.is_file():
        for line in ledger.read_text(encoding="utf-8").splitlines():
            try:
                existing.add(json.loads(line)["candidate_id"])
            except (KeyError, json.JSONDecodeError):
                continue
    count = 0
    for start in range(0, len(image_paths), batch):
        paths = image_paths[start : start + batch]
        results = model([str(path) for path in paths], device=device, imgsz=imgsz, conf=conf, verbose=False)
        for path, result in zip(paths, results):
            row = by_id[path.stem]
            with Image.open(path) as image:
                image = image.convert("RGB")
                width, height = image.size
                boxes = getattr(result, "boxes", None)
                if boxes is None:
                    continue
                for index, box in enumerate(boxes):
                    class_id = int(box.cls.item())
                    class_name = str(result.names.get(class_id, class_id))
                    if class_name != "sign":
                        continue
                    confidence = float(box.conf.item())
                    x1, y1, x2, y2 = (float(value) for value in box.xyxy[0].tolist())
                    pad_x = max(4, int((x2 - x1) * 0.15))
                    pad_y = max(4, int((y2 - y1) * 0.15))
                    crop_box = (max(0, int(x1) - pad_x), max(0, int(y1) - pad_y), min(width, int(x2) + pad_x), min(height, int(y2) + pad_y))
                    candidate_id = f"{row['id']}-{index}"
                    crop_path = crops_dir / f"{candidate_id}.jpg"
                    if candidate_id not in existing:
                        image.crop(crop_box).save(crop_path, format="JPEG", quality=95)
                        record = {
                            "candidate_id": candidate_id,
                            "picture_id": row["id"],
                            "collection": row["collection"],
                            "coordinates": row["coordinates"],
                            "datetime": row["datetime"],
                            "providers": row["providers"],
                            "license": row["license"],
                            "source_item_url": row["source_item_url"],
                            "source_instance_url": row["source_instance_url"],
                            "image_url": row["image_url"],
                            "image_path": str(path.relative_to(output)),
                            "crop_path": str(crop_path.relative_to(output)),
                            "detector": {"model": model_path, "class": class_name, "confidence": confidence, "xyxy": [x1, y1, x2, y2], "padding_ratio": 0.15},
                            "label_status": "unreviewed_ch_candidate",
                        }
                        with ledger.open("a", encoding="utf-8") as handle:
                            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                        existing.add(candidate_id)
                        count += 1
    return count


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--bbox", type=parse_bbox, default=DEFAULT_BBOX)
    parser.add_argument("--tile-degrees", type=float, default=0.5)
    parser.add_argument("--limit", type=int, default=1000)
    parser.add_argument("--max-depth", type=int, default=4)
    parser.add_argument("--request-delay", type=float, default=0.15)
    parser.add_argument("--retry-attempts", type=int, default=3)
    parser.add_argument("--frame-stride", type=int, default=10)
    parser.add_argument("--distance-stride-m", type=float, default=25)
    parser.add_argument("--max-images", type=int, default=10000)
    parser.add_argument("--asset-key", choices=("thumb", "sd"), default="sd")
    parser.add_argument("--max-image-bytes", type=int, default=12 * 1024 * 1024)
    parser.add_argument("--model", type=str, default="/mnt/nvme/prolix/models/DE/detector/yolo11l_panoramax.pt")
    parser.add_argument("--device", default="0")
    parser.add_argument("--imgsz", type=int, default=1280)
    parser.add_argument("--confidence", type=float, default=0.25)
    parser.add_argument("--batch", type=int, default=8)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept": "application/geo+json"})

    raw, saturated, skipped, subdivided_failures = crawl(
        session,
        args.output,
        args.bbox,
        args.tile_degrees,
        args.limit,
        args.max_depth,
        args.request_delay,
        args.retry_attempts,
    )
    normalized = [normalize(feature, args.asset_key) for feature in raw]
    normalized = [row for row in normalized if row["license"] == "CC-BY-SA-4.0" and row["visibility"] in (None, "anyone") and row["image_url"]]
    deduped = deduplicate(normalized, args.frame_stride, args.distance_stride_m)[: args.max_images]
    atomic_json(args.output / "catalog-summary.json", {
        "api": API,
        "bbox": args.bbox,
        "asset_key": args.asset_key,
        "fetched_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "raw_unique_features": len(raw),
        "eligible_features": len(normalized),
        "deduplicated_download_queue": len(deduped),
        "saturated_tiles_at_max_depth": saturated,
        "failed_tiles_subdivided": subdivided_failures,
        "skipped_tiles_after_retries": skipped,
        "retry_attempts": args.retry_attempts,
        "deduplication": {"frame_stride": args.frame_stride, "distance_stride_m": args.distance_stride_m},
        "detector": {"model": args.model, "device": args.device, "imgsz": args.imgsz, "confidence": args.confidence},
        "license_policy": "Only public CC-BY-SA-4.0 features and HTTPS derivatives; no Panoramax writes; CH labels require later human review.",
    })
    (args.output / "catalog.jsonl").write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in normalized) + "\n", encoding="utf-8")
    queue_path = args.output / "download-queue.jsonl"
    queue_path.write_text("\n".join(json.dumps(row, ensure_ascii=False) for row in deduped) + "\n", encoding="utf-8")
    downloaded = 0
    failed = 0
    for row in deduped:
        ok, error = download(session, row, args.output / "images" / f"{row['id']}.jpg", args.max_image_bytes)
        if ok:
            downloaded += 1
        else:
            failed += 1
            with (args.output / "download-errors.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"picture_id": row["id"], "error": error, "source_item_url": row["source_item_url"]}) + "\n")
    candidates = detect_crops(deduped, args.output, args.model, args.device, args.imgsz, args.confidence, args.batch)
    summary = json.loads((args.output / "catalog-summary.json").read_text(encoding="utf-8"))
    summary.update({"downloaded_images": downloaded, "download_failures": failed, "new_candidate_crops": candidates})
    atomic_json(args.output / "catalog-summary.json", summary)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
