#!/usr/bin/env python3
"""Prepare local ZOD Frames paint masks without joining dashed polygons.

Input is an extracted official ZOD Frames archive and its trainval JSON. Images
must retain the original camera geometry. A source receipt records provenance
and whether full-frame lane-annotation coverage has actually been verified.
Without that evidence, only labeled positives are valid and output is explicitly
ineligible for ordinary binary training. No download, redistribution or SDK
installation is performed. All outputs must remain outside this repository.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import re

import cv2
import numpy as np

SDK_REVISION = "601a3ef5cfccad9cc545230362077d299acbf898"
POSITIVE_CLASSES = frozenset(("solid", "dashed", "lm_solid", "lm_dashed"))
IGNORE_CLASSES = frozenset(("botts_dot", "lm_botts_dot", "shaded_area", "lm_shaded"))
ROAD_PROPERTIES = frozenset(("ContainsArrow", "ContainsPictogram", "ContainsText",
    "ContainsTrafficSign", "ContainsCrossWalk", "ContainsMarker", "ContainsOther", "Unclear", "Odd"))
LICENSE = "CC BY-SA 4.0"


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for data in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(data)
    return digest.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + "\n")


def field(data, snake, camel=None):
    """Support dataclass-wizard's documented snake/camel field serialization."""
    keys = [key for key in dict.fromkeys((snake, camel or snake)) if key in data]
    if len(keys) != 1:
        raise ValueError("Missing or ambiguous ZOD field: " + snake)
    return data[keys[0]]


def safe_source(root, name):
    if not isinstance(name, str) or not name or "\\" in name:
        raise ValueError("Invalid source path")
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts or "." in relative.parts:
        raise ValueError("Source path must stay under the dataset root")
    root = Path(root).resolve()
    result = (root / name).resolve()
    if root not in result.parents or not result.is_file():
        raise ValueError("Missing file or source escapes dataset root: " + name)
    return result


def parse_time(value):
    if not isinstance(value, str):
        raise ValueError("ZOD timestamps must be timezone-qualified strings")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("Invalid ZOD timestamp") from error
    if result.tzinfo is None:
        raise ValueError("ZOD timestamp has no timezone")
    return result


def polygon_points(feature, width, height):
    geometry = feature.get("geometry")
    if not isinstance(geometry, dict) or geometry.get("type", "Polygon") != "Polygon":
        raise ValueError("Only ZOD pixel polygons are supported; no lines or multipolygons")
    try:
        points = np.asarray(geometry["coordinates"], dtype=np.float64)
    except (ValueError, KeyError, TypeError) as error:
        raise ValueError("Malformed polygon coordinates") from error
    # SDK LaneAnnotation.geometry is Nx2. Accept the equivalent single-ring
    # GeoJSON envelope, but never flatten multiple rings or bridge instances.
    if points.ndim == 3 and points.shape[0] == 1:
        points = points[0]
    if points.ndim != 2 or points.shape[1] != 2 or len(points) < 3 or not np.isfinite(points).all():
        raise ValueError("Expected one finite polygon ring with at least three vertices")
    if len(np.unique(points, axis=0)) < 3:
        raise ValueError("Degenerate polygon")
    if ((points < 0).any() or (points[:, 0] > width).any() or (points[:, 1] > height).any()):
        raise ValueError("Polygon outside original image; coordinate transform must be verified")
    if abs(cv2.contourArea(points.astype(np.float32))) < 1e-6:
        raise ValueError("Zero-area polygon")
    # Match official SDK polygon_to_array: truncate pixel coordinates to int32.
    return points.astype(np.int32).reshape((-1, 1, 2))


def feature_kind(feature):
    properties = feature.get("properties")
    if not isinstance(properties, dict) or not isinstance(properties.get("annotation_uuid"), str):
        raise ValueError("Missing ZOD annotation properties/UUID")
    if not properties["annotation_uuid"]:
        raise ValueError("Empty annotation UUID")
    for key in ROAD_PROPERTIES | {"unclear", "odd"}:
        if key in properties and properties[key] is not None and type(properties[key]) is not bool:
            raise ValueError("Unrecognized annotation flag: " + key)
    uncertain = any(properties.get(k) is True for k in ("Unclear", "unclear", "Odd", "odd"))
    category = properties.get("class")
    if category in POSITIVE_CLASSES:
        return ("ignore" if uncertain else "positive"), category
    if category in IGNORE_CLASSES:
        return "ignore", category
    if category is not None:
        raise ValueError("Unrecognized ZOD lane class: " + str(category))
    if not any(properties.get(k) is True for k in ROAD_PROPERTIES):
        raise ValueError("Unrecognized road-painting annotation")
    return "ignore", "road_painting"


def rasterize_annotations(annotations, width, height, complete_coverage=False):
    if type(width) is not int or type(height) is not int or not (0 < width <= 10000 and 0 < height <= 10000):
        raise ValueError("Invalid original image dimensions")
    if not isinstance(annotations, list):
        raise ValueError("ZOD lane file must be a list; a missing file is not an empty scene")
    if type(complete_coverage) is not bool:
        raise ValueError("Coverage must be explicitly boolean")
    positive = np.zeros((height, width), np.uint8)
    ignored = np.zeros_like(positive)
    counts, uuids = Counter(), set()
    for feature in annotations:
        if not isinstance(feature, dict):
            raise ValueError("Malformed annotation feature")
        kind, category = feature_kind(feature)
        identity = feature["properties"]["annotation_uuid"]
        if identity in uuids:
            raise ValueError("Duplicate annotation UUID")
        uuids.add(identity)
        points = polygon_points(feature, width, height)
        cv2.fillPoly(positive if kind == "positive" else ignored, [points], 255)
        counts[category] += 1
    # Ignore wins even when paint and an uncertain/other-paint polygon overlap.
    positive[ignored != 0] = 0
    valid = np.full_like(positive, 255) if complete_coverage else positive.copy()
    valid[ignored != 0] = 0
    return positive, valid, {"annotation_counts": dict(counts),
        "positive_pixels": int(np.count_nonzero(positive)),
        "valid_pixels": int(np.count_nonzero(valid)),
        "explicit_ignore_pixels": int(np.count_nonzero(ignored))}


def distance_m(a, b):
    lat1, lat2 = math.radians(a["latitude"]), math.radians(b["latitude"])
    dlat = lat2 - lat1
    dlon = math.radians(b["longitude"] - a["longitude"])
    value = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 6371008.8 * 2 * math.asin(math.sqrt(min(1.0, max(0.0, value))))


def assign_splits(records, proximity_m=250.0, validation_fraction=0.0):
    """Conservative day/vehicle + geographic connected-component holdouts.

    Official validation frames are always test. Any official training component
    touching one is excluded, never promoted into the official holdout. Remaining
    components are split deterministically without consulting images or labels.
    """
    if not math.isfinite(proximity_m) or proximity_m <= 0 or not 0 <= validation_fraction < 1:
        raise ValueError("Invalid grouping parameters")
    if len(records) > 5000:
        raise ValueError("Bounded importer supports at most 5000 frames; implement a spatial index before full-data use")
    identities = [r["frame_id"] for r in records]
    if len(identities) != len(set(identities)):
        raise ValueError("Duplicate source frame ID")
    parents = list(range(len(records)))
    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i
    def join(a, b):
        parents[root(b)] = root(a)
    for i, row in enumerate(records):
        if row["official_split"] not in ("train", "val"):
            raise ValueError("Unknown official partition")
        if not row.get("collection_car") or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["capture_date"]):
            raise ValueError("Missing capture grouping metadata")
        lat, lon = row["latitude"], row["longitude"]
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (lat, lon)) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise ValueError("Invalid geographic metadata")
        for j, other in enumerate(records[:i]):
            same_drive_day = (row["collection_car"], row["capture_date"]) == (other["collection_car"], other["capture_date"])
            if same_drive_day or distance_m(row, other) <= proximity_m:
                join(i, j)
    groups = defaultdict(list)
    for i, row in enumerate(records):
        groups[root(i)].append(row)
    clean_train, excluded = [], []
    for members in groups.values():
        group_id = "zod-" + hashlib.sha256("\n".join(sorted(r["frame_id"] for r in members)).encode()).hexdigest()[:16]
        for row in members:
            row["group_id"] = group_id
        if any(r["official_split"] == "val" for r in members):
            for row in members:
                row["split"] = "test" if row["official_split"] == "val" else "excluded"
                if row["split"] == "excluded":
                    excluded.append({"frame_id": row["frame_id"], "group_id": group_id,
                                     "reason": "Training component overlaps official validation in drive-day or geography"})
        else:
            clean_train.append((group_id, members))
    # A one-component mini remains training-only; never split an individual drive
    # to manufacture a validation set. Full mixed runs may use A2D2 validation.
    clean_train.sort(key=lambda item: hashlib.sha256(("zod-validation-v1:" + item[0]).encode()).digest())
    count = min(len(clean_train) - 1, max(1, round(len(clean_train) * validation_fraction))) if len(clean_train) > 1 and validation_fraction else 0
    for i, (_, members) in enumerate(clean_train):
        for row in members:
            row["split"] = "validation" if i < count else "train"
    return records, excluded


def read_receipt(path):
    receipt = json.loads(Path(path).read_text())
    required = ("source_revision", "source_url", "coverage_evidence")
    if receipt.get("schemaVersion") != 1 or receipt.get("dataset") != "ZOD" or receipt.get("license") != LICENSE:
        raise ValueError("Expected ZOD provenance receipt with CC BY-SA 4.0 data license")
    if any(not isinstance(receipt.get(key), str) or not receipt[key].strip() for key in required):
        raise ValueError("Source revision, URL and coverage evidence are required")
    if not receipt["source_url"].startswith("https://"):
        raise ValueError("Expected HTTPS source URL")
    if receipt.get("geometry") != "original-pixel-polygons":
        raise ValueError("Only original image/annotation coordinates are supported; resized derivatives require a verified transform")
    if receipt.get("annotation_coverage") not in ("unknown", "complete_lane_markings"):
        raise ValueError("Annotation coverage must be explicit")
    qa = receipt.get("frame_qa")
    if qa is not None:
        if not isinstance(qa, dict) or not re.fullmatch(r"[0-9a-f]{64}", str(qa.get("trainval_sha256", ""))) or not isinstance(qa.get("frames"), list):
            raise ValueError("Malformed frame QA scope")
        seen = set()
        for row in qa["frames"]:
            if (not isinstance(row, dict) or not re.fullmatch(r"\d{6}", str(row.get("frame_id", "")))
                    or row["frame_id"] in seen or row.get("decision") not in ("accept", "exclude")
                    or not isinstance(row.get("reason"), str) or not row["reason"].strip()
                    or any(not re.fullmatch(r"[0-9a-f]{64}", str(row.get(key, ""))) for key in ("rgb_sha256", "annotation_sha256"))):
                raise ValueError("Malformed, duplicate or unbound frame QA decision")
            seen.add(row["frame_id"])
    return receipt


def read_records(dataset_root, trainval_path):
    data = json.loads(Path(trainval_path).read_text())
    if not isinstance(data, dict) or not {"train", "val"} <= data.keys() or set(data) - {"train", "val", "blacklisted"}:
        raise ValueError("Expected SDK >=0.2 trainval Frames schema with train/val lists")
    blacklisted = data.get("blacklisted", [])
    if not isinstance(blacklisted, list) or any(not isinstance(row, dict) or not isinstance(row.get("id"), str) for row in blacklisted):
        raise ValueError("Malformed official blacklist")
    blacklist_ids = {row["id"] for row in blacklisted}
    records = []
    for split in ("train", "val"):
        if not isinstance(data[split], list):
            raise ValueError("Official partition must be a list of frame information")
        for info in data[split]:
            identity = info.get("id")
            if not isinstance(identity, str) or not re.fullmatch(r"\d{6}", identity):
                raise ValueError("Expected six-digit official frame ID")
            if identity in blacklist_ids:
                raise ValueError("Official blacklisted frame also appears in train/val: " + identity)
            annotation = field(info, "annotations").get("lane_markings")
            if not isinstance(annotation, dict) or annotation.get("project") != "lane_markings":
                raise ValueError("Missing lane annotation; cannot infer negative labels")
            metadata_key = field(info, "metadata_path", "metadataPath")
            metadata = json.loads(safe_source(dataset_root, metadata_key).read_text())
            if field(metadata, "frame_id", "frameId") != identity:
                raise ValueError("Metadata frame ID disagrees with official split")
            keytime = parse_time(field(info, "keyframe_time", "keyframeTime"))
            camera_frames = field(info, "camera_frames", "cameraFrames").get("front_blur")
            if not isinstance(camera_frames, list) or len(camera_frames) != 1:
                raise ValueError("Require one original blurred front camera frame; sequence adapter is separate")
            camera = camera_frames[0]
            camera_time = parse_time(camera["time"])
            if abs((camera_time - keytime).total_seconds()) > 0.1:
                raise ValueError("Image and labeled keyframe timestamp disagree")
            if abs((parse_time(metadata["time"]) - keytime).total_seconds()) > 0.1:
                raise ValueError("Metadata and labeled keyframe timestamp disagree")
            rgb_key, annotation_key = camera["filepath"], annotation["filepath"]
            for key in (rgb_key, annotation_key):
                safe_source(dataset_root, key)
            width, height = camera.get("width", 3848), camera.get("height", 2168)
            records.append({"frame_id": identity, "official_split": split, "rgb": rgb_key,
                "annotation": annotation_key, "metadata": metadata_key, "width": width, "height": height,
                "camera_timestamp": camera_time.isoformat(), "capture_date": camera_time.astimezone(timezone.utc).date().isoformat(),
                "collection_car": field(metadata, "collection_car", "collectionCar"),
                "latitude": metadata["latitude"], "longitude": metadata["longitude"]})
    return records


def prepare(dataset_root, trainval_path, receipt_path, output, proximity_m=250.0, validation_fraction=0.0, quarantine_invalid_annotations=False):
    dataset_root, output = Path(dataset_root).resolve(), Path(output).resolve()
    repository = Path(__file__).resolve().parents[2]
    if output == repository or repository in output.parents or output.exists():
        raise ValueError("Choose a new output directory outside the repository")
    receipt = read_receipt(receipt_path)
    records = read_records(dataset_root, trainval_path)
    records, excluded = assign_splits(records, proximity_m, validation_fraction)
    qa = receipt.get("frame_qa")
    qa_frames = {row["frame_id"]: row for row in qa["frames"]} if qa is not None else {}
    if qa is not None and (qa["trainval_sha256"] != sha256_file(trainval_path)
            or set(qa_frames) != {row["frame_id"] for row in records}):
        raise ValueError("Frame QA scope does not match all original trainval records")
    complete = receipt["annotation_coverage"] == "complete_lane_markings"
    objects, selected, image_hashes = {}, [], {}
    def add_object(key, path, role):
        if key not in objects:
            objects[key] = {"key": key, "local_path": str(Path(path).resolve()),
                            "sha256": sha256_file(path), "size": Path(path).stat().st_size, "role": role}
        elif objects[key]["local_path"] != str(Path(path).resolve()):
            raise ValueError("Object key collision")
        return objects[key]
    output.mkdir(parents=True)
    try:
        add_object("provenance/trainval.json", trainval_path, "official_split_and_camera_info")
        add_object("provenance/receipt.json", receipt_path, "source_receipt")
        for row in records:
            # Hash/read all originals, including purged frames, so grouping and
            # exclusion decisions remain auditable without silently omitting rows.
            for key, role in ((row["rgb"], "rgb"), (row["annotation"], "original_annotation"), (row["metadata"], "metadata")):
                add_object(key, safe_source(dataset_root, key), role)
            rgb_hash = objects[row["rgb"]]["sha256"]
            if rgb_hash in image_hashes:
                raise ValueError("Duplicate RGB source bytes across official frame IDs")
            image_hashes[rgb_hash] = row["frame_id"]
            decision = qa_frames.get(row["frame_id"])
            if decision is not None:
                if (decision["rgb_sha256"] != rgb_hash
                        or decision["annotation_sha256"] != objects[row["annotation"]]["sha256"]):
                    raise ValueError("Frame QA source hash mismatch: " + row["frame_id"])
                if decision["decision"] == "exclude" and row["split"] != "excluded":
                    excluded.append({"frame_id": row["frame_id"], "group_id": row["group_id"],
                        "official_split": row["official_split"], "assigned_split": row["split"],
                        "reason": "Source QA: " + decision["reason"], "rgb_sha256": rgb_hash,
                        "annotation_sha256": objects[row["annotation"]]["sha256"]})
                    continue
            if row["split"] == "excluded":
                continue
            image = cv2.imread(str(safe_source(dataset_root, row["rgb"])), cv2.IMREAD_COLOR)
            if image is None or image.shape[:2] != (row["height"], row["width"]):
                raise ValueError("RGB dimensions differ from original camera metadata")
            try:
                annotations = json.loads(safe_source(dataset_root, row["annotation"]).read_text())
                positive, valid, stats = rasterize_annotations(annotations, row["width"], row["height"], complete)
            except ValueError as error:
                if not quarantine_invalid_annotations:
                    raise
                excluded.append({"frame_id": row["frame_id"], "group_id": row["group_id"],
                    "official_split": row["official_split"], "assigned_split": row["split"],
                    "reason": "Invalid annotation: " + str(error),
                    "annotation_sha256": objects[row["annotation"]]["sha256"]})
                continue
            for name, array in (("label", positive), ("valid", valid)):
                key = f"derived/{row['frame_id']}-{name}.png"
                path = output / key
                path.parent.mkdir(exist_ok=True)
                if not cv2.imwrite(str(path), array):
                    raise ValueError("Unable to write derived mask")
                add_object(key, path, "binary_" + name)
                row[name] = key
            row["target_kind"] = "paint"
            row["transform"] = {"type": "identity", "sourceWidth": row["width"], "sourceHeight": row["height"]}
            row["statistics"] = stats
            selected.append(row)
        train_rows = [row for row in selected if row["split"] == "train"]
        train_positive = sum(row["statistics"]["positive_pixels"] for row in train_rows)
        train_valid = sum(row["statistics"]["valid_pixels"] for row in train_rows)
        manifest = {"schemaVersion": 1, "dataset": "ZOD", "target_kind": "paint",
            "source_revision": receipt["source_revision"], "source_url": receipt["source_url"],
            "license": LICENSE, "license_url": "https://zod.zenseact.com/license/", "source_receipt": receipt,
            "sdk_reference_revision": SDK_REVISION, "adapter_sha256": sha256_file(__file__),
            "objects": list(objects.values()), "pairs": selected, "excluded": excluded,
            "exclusion_counts": dict(Counter("invalid_annotation" if row["reason"].startswith("Invalid annotation:") else "source_qa" if row["reason"].startswith("Source QA:") else "split_overlap" for row in excluded)),
            "quarantine_invalid_annotations": quarantine_invalid_annotations,
            "grouping": {"method": "vehicle-capture-day-or-geographic-connected-components-v1", "proximity_m": proximity_m,
                "validation_fraction": validation_fraction, "official_val": "test", "overlap_policy": "exclude official train components touching official val"},
            "partition_counts": {split: sum(row["split"] == split for row in selected) for split in ("train", "validation", "test")},
            "training_eligible": complete and train_valid > train_positive > 0 and any(row["split"] != "train" for row in selected),
            "mask_policy": {"positive": sorted(POSITIVE_CLASSES), "explicit_ignore": sorted(IGNORE_CLASSES) + ["road_painting", "unclear", "odd"],
                "unmarked_pixels": "valid negative" if complete else "ignored: coverage not verified", "overlap": "ignore wins",
                "rasterization": "Each polygon independently; SDK int32 coordinate truncation and cv2.fillPoly. Never join common InstanceID."},
            "qualification": "Bounded research import. Vehicle-day and configured proximity isolation do not prove route-disjointness. Mini results are smoke checks, not acceptance evidence. Report scores as corpus-filtered if exclusions are present. No private video is used."}
        write_json(output / "manifest.json", manifest)
        (output / "ATTRIBUTION.txt").write_text("Zenseact Open Dataset, Zenseact and contributors.\nhttps://zod.zenseact.com/\nData: CC BY-SA 4.0; https://zod.zenseact.com/license/\nLocal derived lane-paint and validity masks. Original source paths and SHA-256 hashes are in manifest.json.\nNo redistribution or trained-model release clearance is inferred.\n")
        return manifest
    except Exception as error:
        write_json(output / "incomplete.json", {"status": "incomplete", "reason": str(error)})
        raise


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--trainval", type=Path, required=True)
    parser.add_argument("--source-receipt", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--proximity-m", type=float, default=250.)
    parser.add_argument("--validation-fraction", type=float, default=0., help="Optional selection holdout from train components; default uses A2D2 validation separately")
    parser.add_argument("--quarantine-invalid-annotations", action="store_true", help="Exclude whole frames failing annotation validation and retain source hashes/reasons; default aborts")
    args = parser.parse_args()
    try:
        result = prepare(args.dataset_root, args.trainval, args.source_receipt, args.output_dir, args.proximity_m, args.validation_fraction, args.quarantine_invalid_annotations)
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.error(str(error))
    print(json.dumps({key: result[key] for key in ("dataset", "partition_counts", "training_eligible", "qualification")}, indent=2))


if __name__ == "__main__":
    main()
