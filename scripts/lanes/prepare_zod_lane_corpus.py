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
import itertools
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


def safe_source(root, name, require_exists=True):
    if not isinstance(name, str) or not name or "\\" in name:
        raise ValueError("Invalid source path")
    relative = PurePosixPath(name)
    if relative.is_absolute() or ".." in relative.parts or "." in relative.parts:
        raise ValueError("Source path must stay under the dataset root")
    root = Path(root).resolve()
    result = (root / name).resolve()
    if root not in result.parents or (require_exists and not result.is_file()):
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


def loss_space_counts(positive, valid, width, height, size):
    if type(size) is not int or not 32 <= size <= 1280 or size % 32:
        raise ValueError("Invalid predeclared training input size")
    scale = min(size / width, size / height)
    dims = (round(width * scale), round(height * scale))
    # Exact training letterbox pixel-center convention. Zero-valid padding does
    # not change these counts; original masks are preserved in the corpus.
    return {"training_input_size":size,
        "training_input_positive_pixels":int(np.count_nonzero(cv2.resize(positive, dims, interpolation=cv2.INTER_NEAREST_EXACT))),
        "training_input_valid_pixels":int(np.count_nonzero(cv2.resize(valid, dims, interpolation=cv2.INTER_NEAREST_EXACT)))}


def assign_groups(records, proximity_m=250.0):
    """Exact spherical proximity components with bounded spatial-cell comparisons.

    Vehicle/day edges and ALL source rows must be included before cohort sampling.
    Earth-centered coordinates avoid dateline/polar special cases. A cell diagonal
    is shorter than the proximity chord, so its rows form a clique. Neighbor-cell
    comparisons stop after one connecting pair and use bounded arrays; repeated
    coordinates are deduplicated. No quadratic all-dataset distance scan is used.
    """
    if not math.isfinite(proximity_m) or not 0 < proximity_m < math.pi * 6371008.8:
        raise ValueError("Invalid grouping proximity")
    identities = [r["frame_id"] for r in records]
    if len(identities) != len(set(identities)):
        raise ValueError("Duplicate source frame ID")
    parents, sizes = list(range(len(records))), [1] * len(records)
    def root(i):
        while parents[i] != i:
            parents[i] = parents[parents[i]]
            i = parents[i]
        return i
    def join(a, b):
        a, b = root(a), root(b)
        if a != b:
            if sizes[a] < sizes[b]:
                a, b = b, a
            parents[b] = a
            sizes[a] += sizes[b]
    radius = 6371008.8
    chord = 2 * radius * math.sin(proximity_m / (2 * radius))
    # Tiny conservative tolerance only covers floating-point coordinate error.
    threshold = chord + 1e-7
    cell_size = chord / math.sqrt(3) * (1 - 1e-12)
    cells, days = {}, {}
    for i, row in enumerate(records):
        if row["official_split"] not in ("train", "val", "blacklisted"):
            raise ValueError("Unknown official partition")
        if not row.get("collection_car") or not re.fullmatch(r"\d{4}-\d{2}-\d{2}", row["capture_date"]):
            raise ValueError("Missing capture grouping metadata")
        lat, lon = row["latitude"], row["longitude"]
        if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (lat, lon)) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise ValueError("Invalid geographic metadata")
        day = (row["collection_car"], row["capture_date"])
        if day in days:
            join(i, days[day])
        else:
            days[day] = i
        lat, lon = math.radians(lat), math.radians(lon)
        xyz = (radius * math.cos(lat) * math.cos(lon), radius * math.cos(lat) * math.sin(lon), radius * math.sin(lat))
        key = tuple(math.floor(v / cell_size) for v in xyz)
        if key in cells:
            join(i, cells[key][0])
            cells[key][1].add(xyz)
        else:
            cells[key] = [i, {xyz}]
    indexed = {}
    for key, (i, points) in cells.items():
        points = np.array(sorted(points), dtype=np.float64)
        indexed[key] = (i, points, points.min(axis=0), points.max(axis=0))
    # Neighbors at distance <= chord can differ by at most two cell indices.
    offsets = [(x, y, z) for x in range(-2, 3) for y in range(-2, 3) for z in range(-2, 3) if (x, y, z) > (0, 0, 0)]
    for key, (i, points, lo, hi) in indexed.items():
        for offset in offsets:
            other = indexed.get(tuple(a + b for a, b in zip(key, offset)))
            if other is None or root(i) == root(other[0]):
                continue
            j, candidates, other_lo, other_hi = other
            gap = np.maximum(0, np.maximum(lo - other_hi, other_lo - hi))
            if float(gap @ gap) > threshold * threshold:
                continue
            connected = False
            for a in range(0, len(points), 128):
                for b in range(0, len(candidates), 128):
                    delta = points[a:a + 128, None, :] - candidates[None, b:b + 128, :]
                    if np.any(np.einsum("ijk,ijk->ij", delta, delta) <= threshold * threshold):
                        join(i, j)
                        connected = True
                        break
                if connected:
                    break
    groups = defaultdict(list)
    for i, row in enumerate(records):
        groups[root(i)].append(row)
    for members in groups.values():
        identity = "zod-" + hashlib.sha256("\n".join(sorted(r["frame_id"] for r in members)).encode()).hexdigest()[:16]
        for row in members:
            row["group_id"] = identity
    return list(groups.values())


def assign_day_graph(records, proximity_m=250.0):
    """Whole vehicle/day nodes; witness-backed direct geography edges, no closure."""
    if not math.isfinite(proximity_m) or not 0 < proximity_m < math.pi * 6371008.8:
        raise ValueError("Invalid graph proximity")
    if len({r["frame_id"] for r in records}) != len(records):
        raise ValueError("Duplicate source frame ID")
    radius = 6371008.8
    chord = 2 * radius * math.sin(proximity_m / (2 * radius))
    cell_size, threshold = chord / math.sqrt(3) * (1 - 1e-12), chord + 1e-7
    cells, nodes = defaultdict(lambda:defaultdict(dict)), defaultdict(list)
    for row in sorted(records, key=lambda r:r["frame_id"]):
        car, date = row["collection_car"], row["capture_date"]
        if (not isinstance(car, str) or not car or "\n" in car
                or not isinstance(date,str) or not re.fullmatch(r"\d{4}-\d{2}-\d{2}",date)
                or row["official_split"] not in ("train","val","blacklisted")):
            raise ValueError("Invalid vehicle/day graph metadata")
        lat, lon = row["latitude"], row["longitude"]
        if any(isinstance(v,bool) or not isinstance(v,(int,float)) or not math.isfinite(v) for v in (lat,lon)) or not -90 <= lat <= 90 or not -180 <= lon <= 180:
            raise ValueError("Invalid graph geographic metadata")
        identity = "zod-day-" + hashlib.sha256((car + "\n" + date).encode()).hexdigest()[:16]
        row["group_id"] = identity
        nodes[identity].append(row)
        lat, lon = math.radians(lat), math.radians(lon)
        xyz = (radius*math.cos(lat)*math.cos(lon),radius*math.cos(lat)*math.sin(lon),radius*math.sin(lat))
        cells[tuple(math.floor(v/cell_size) for v in xyz)][identity].setdefault(xyz,row["frame_id"])
    edges = {}
    def add(a,b,pa,pb):
        distance = float(np.linalg.norm(np.array(pa[0])-np.array(pb[0])))
        pair = tuple(sorted((a,b)))
        edges[pair] = {"nodes":list(pair),"witness_frame_ids":[pa[1],pb[1]],
            "spherical_distance_m":2*radius*math.asin(min(1.,distance/(2*radius)))}
    indexed = {}
    for cell, members in cells.items():
        for a,b in itertools.combinations(sorted(members),2):
            if (a,b) not in edges:
                add(a,b,next(iter(members[a].items())),next(iter(members[b].items())))
        indexed[cell] = {}
        for identity, points in members.items():
            array=np.array(list(points),dtype=np.float64)
            indexed[cell][identity]=(array,list(points.values()),array.min(axis=0),array.max(axis=0))
    offsets=[(x,y,z) for x in range(-2,3) for y in range(-2,3) for z in range(-2,3) if (x,y,z)>(0,0,0)]
    for cell, members in indexed.items():
        for offset in offsets:
            other=indexed.get(tuple(a+b for a,b in zip(cell,offset)))
            if other is None:
                continue
            for a,(points,ids,lo,hi) in members.items():
                for b,(candidates,cids,blo,bhi) in other.items():
                    if a==b or tuple(sorted((a,b))) in edges:
                        continue
                    gap=np.maximum(0,np.maximum(lo-bhi,blo-hi))
                    if float(gap@gap)>threshold*threshold:
                        continue
                    found=False
                    for i in range(0,len(points),128):
                        for j in range(0,len(candidates),128):
                            delta=points[i:i+128,None,:]-candidates[None,j:j+128,:]
                            hits=np.argwhere(np.einsum("ijk,ijk->ij",delta,delta)<=threshold*threshold)
                            if len(hits):
                                u,v=map(int,hits[0]); add(a,b,(points[i+u],ids[i+u]),(candidates[j+v],cids[j+v]))
                                found=True
                                break
                        if found:
                            break
    return {"schemaVersion":1,"method":"all-source-vehicle-day-direct-spherical-adjacency-v2",
        "proximity_m":proximity_m,"floating_tolerance_m":1e-7,
        "nodes":[{"day_id":identity,"collection_car":members[0]["collection_car"],
            "capture_date":members[0]["capture_date"],"frame_ids":[r["frame_id"] for r in members]}
            for identity,members in sorted(nodes.items())],
        "edges":[edges[pair] for pair in sorted(edges)]}


def assign_splits(records, proximity_m=250.0, validation_fraction=0.0):
    """Preserve all official val; purge train components touching that holdout."""
    if not 0 <= validation_fraction < 1 or any(r["official_split"] not in ("train", "val") for r in records):
        raise ValueError("Invalid grouping parameters or official partition")
    groups = assign_groups(records, proximity_m)
    clean_train, excluded = [], []
    for members in groups:
        group_id = members[0]["group_id"]
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
    if receipt.get("annotation_coverage") not in ("unknown", "complete_lane_markings", "per_frame"):
        raise ValueError("Annotation coverage must be explicit")
    qa = receipt.get("frame_qa")
    if receipt["annotation_coverage"] == "per_frame" and qa is None:
        raise ValueError("Per-frame coverage requires hash-bound frame QA")
    if qa is not None:
        if not isinstance(qa, dict) or not re.fullmatch(r"[0-9a-f]{64}", str(qa.get("trainval_sha256", ""))) or not isinstance(qa.get("frames"), list):
            raise ValueError("Malformed frame QA scope")
        seen = set()
        for row in qa["frames"]:
            if (not isinstance(row, dict) or not re.fullmatch(r"\d{6}", str(row.get("frame_id", "")))
                    or row["frame_id"] in seen or row.get("decision") not in ("accept", "exclude", "positive_only")
                    or not isinstance(row.get("reason"), str) or not row["reason"].strip()
                    or any(not re.fullmatch(r"[0-9a-f]{64}", str(row.get(key, ""))) for key in ("rgb_sha256", "annotation_sha256"))):
                raise ValueError("Malformed, duplicate or unbound frame QA decision")
            seen.add(row["frame_id"])
    return receipt


def read_records(dataset_root, trainval_path, require_assets=True, include_blacklisted=False):
    data = json.loads(Path(trainval_path).read_text())
    if not isinstance(data, dict) or not {"train", "val"} <= data.keys() or set(data) - {"train", "val", "blacklisted"}:
        raise ValueError("Expected SDK >=0.2 trainval Frames schema with train/val lists")
    blacklisted = data.get("blacklisted", [])
    if not isinstance(blacklisted, list) or any(not isinstance(row, dict) or not isinstance(row.get("id"), str) for row in blacklisted):
        raise ValueError("Malformed official blacklist")
    blacklist_ids = {row["id"] for row in blacklisted}
    records = []
    for split in (("train", "val", "blacklisted") if include_blacklisted else ("train", "val")):
        if not isinstance(data.get(split, []), list):
            raise ValueError("Official partition must be a list of frame information")
        for info in data.get(split, []):
            identity = info.get("id")
            if not isinstance(identity, str) or not re.fullmatch(r"\d{6}", identity):
                raise ValueError("Expected six-digit official frame ID")
            if identity in blacklist_ids and split != "blacklisted":
                raise ValueError("Official blacklisted frame also appears in train/val: " + identity)
            annotation = field(info, "annotations").get("lane_markings")
            if not isinstance(annotation, dict) or annotation.get("project") != "lane_markings":
                raise ValueError("Missing lane annotation; cannot infer negative labels")
            metadata_key = field(info, "metadata_path", "metadataPath")
            metadata_bytes = safe_source(dataset_root, metadata_key).read_bytes()
            metadata = json.loads(metadata_bytes)
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
                safe_source(dataset_root, key, require_exists=require_assets)
            width, height = camera.get("width", 3848), camera.get("height", 2168)
            records.append({"frame_id": identity, "official_split": split, "rgb": rgb_key,
                "annotation": annotation_key, "metadata": metadata_key, "width": width, "height": height,
                "metadata_sha256": hashlib.sha256(metadata_bytes).hexdigest(),
                "camera_timestamp": camera_time.isoformat(), "capture_date": camera_time.astimezone(timezone.utc).date().isoformat(),
                "collection_car": field(metadata, "collection_car", "collectionCar"),
                "latitude": metadata["latitude"], "longitude": metadata["longitude"]})
    return records


def apply_cohort(records, trainval_path, selection_path):
    """Use a hash-bound full-source grouping, never regroup only selected rows."""
    selection_path = Path(selection_path).resolve()
    cohort = json.loads(selection_path.read_text())
    direct_day = cohort.get("kind") == "predeclared-full-source-day-cohort-v2"
    if (cohort.get("schemaVersion") != 1 or cohort.get("kind") not in ("predeclared-full-source-cohort-v1", "predeclared-full-source-day-cohort-v2")
            or cohort.get("selected_trainval_sha256") != sha256_file(trainval_path)):
        raise ValueError("Cohort selection does not match selected original trainval")
    file_key,hash_key=("full_source_graph_file","full_source_graph_sha256") if direct_day else ("full_source_groups_file","full_source_groups_sha256")
    groups_path = safe_source(selection_path.parent, cohort[file_key])
    if sha256_file(groups_path) != cohort[hash_key]:
        raise ValueError("Full-source grouping hash mismatch")
    full_graph=json.loads(groups_path.read_text())
    source = full_graph["records"]
    source_map = {r["frame_id"]:r for r in source}
    if len(source_map) != len(source) or len(source) != cohort["grouping"]["full_source_count"]:
        raise ValueError("Incomplete or duplicate full-source grouping")
    members = defaultdict(list)
    for row in source:
        members[row["group_id"]].append(row["frame_id"])
    adjacency=defaultdict(set)
    if direct_day:
        # Rebuild from ALL source coordinates so a missing/forged adjacency edge
        # cannot silently admit nearby training days or hide outside-cohort rows.
        declared={r["frame_id"]:r["group_id"] for r in source}
        rebuilt=assign_day_graph(source,cohort["grouping"]["proximity_m"])
        if (any(r["group_id"]!=declared[r["frame_id"]] for r in source)
                or rebuilt["nodes"]!=full_graph["nodes"] or rebuilt["edges"]!=full_graph["edges"]):
            raise ValueError("Full-source day adjacency/membership/witness proof mismatch")
        for edge in rebuilt["edges"]:
            a,b=edge["nodes"];adjacency[a].add(b);adjacency[b].add(a)
    else:
        for identity, ids in members.items():
            expected = "zod-" + hashlib.sha256("\n".join(sorted(ids)).encode()).hexdigest()[:16]
            if identity != expected:
                raise ValueError("Full-source component membership identity mismatch")
    selected = {r["frame_id"]:r["split"] for r in cohort["selected"]}
    if len(selected) != len(cohort["selected"]) or set(selected) != {r["frame_id"] for r in records}:
        raise ValueError("Cohort selected IDs mismatch")
    if not set(cohort["exposure_ids"]) <= set(source_map):
        raise ValueError("Unknown prior exposure in full-source grouping")
    exposed_groups = {source_map[i]["group_id"] for i in cohort["exposure_ids"]}
    split_groups = defaultdict(set)
    for row in records:
        full = source_map[row["frame_id"]]
        split = selected[row["frame_id"]]
        if split != {"train":"train", "val":"test"}.get(row["official_split"]) or full["official_split"] != row["official_split"]:
            raise ValueError("Cohort changes official frame partition")
        if full["metadata"] != row["metadata"]:
            raise ValueError("Cohort metadata path mismatch")
        row["group_id"], row["split"] = full["group_id"], split
        row["cohort_metadata_sha256"] = full["metadata_sha256"]
        split_groups[split].add(row["group_id"])
    if split_groups["train"] & split_groups["test"] or split_groups["test"] & exposed_groups:
        raise ValueError("Cohort component overlaps train/test or prior exposure")
    if direct_day and split_groups["train"] & {neighbor for h in split_groups["test"] for neighbor in adjacency[h]}:
        raise ValueError("Cohort train days violate direct full-source holdout proximity buffer")
    if set(cohort["qa_plan"]["full_review_test_ids"]) != {i for i,s in selected.items() if s == "test"}:
        raise ValueError("Cohort QA plan does not cover every holdout frame")
    return cohort, groups_path


def prepare(dataset_root, trainval_path, receipt_path, output, proximity_m=250.0, validation_fraction=0.0, quarantine_invalid_annotations=False, cohort_selection_path=None):
    dataset_root, output = Path(dataset_root).resolve(), Path(output).resolve()
    repository = Path(__file__).resolve().parents[2]
    if output == repository or repository in output.parents or output.exists():
        raise ValueError("Choose a new output directory outside the repository")
    receipt = read_receipt(receipt_path)
    records = read_records(dataset_root, trainval_path)
    cohort, groups_path, excluded = None, None, []
    if cohort_selection_path is None:
        records, excluded = assign_splits(records, proximity_m, validation_fraction)
    else:
        if validation_fraction != 0:
            raise ValueError("Cohort partitions cannot be reassigned")
        cohort, groups_path = apply_cohort(records, trainval_path, cohort_selection_path)
        if receipt.get("cohort_selection_sha256") != sha256_file(cohort_selection_path):
            raise ValueError("Source QA receipt must bind the predeclared cohort selection")
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
        if cohort is not None:
            add_object("provenance/cohort.json", cohort_selection_path, "predeclared_cohort")
            add_object("provenance/full-source-groups.json", groups_path, "full_source_grouping")
        for row in records:
            # Hash/read all originals, including purged frames, so grouping and
            # exclusion decisions remain auditable without silently omitting rows.
            for key, role in ((row["rgb"], "rgb"), (row["annotation"], "original_annotation"), (row["metadata"], "metadata")):
                add_object(key, safe_source(dataset_root, key), role)
            rgb_hash = objects[row["rgb"]]["sha256"]
            if rgb_hash in image_hashes:
                raise ValueError("Duplicate RGB source bytes across official frame IDs")
            image_hashes[rgb_hash] = row["frame_id"]
            if cohort is not None and row["cohort_metadata_sha256"] != objects[row["metadata"]]["sha256"]:
                raise ValueError("Cohort metadata hash mismatch: " + row["frame_id"])
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
            row_complete = complete or (receipt["annotation_coverage"] == "per_frame" and decision["decision"] == "accept")
            if decision is not None and decision["decision"] == "positive_only":
                row_complete = False
            if not row_complete and row["split"] != "train" and (receipt["annotation_coverage"] == "per_frame" or cohort is not None or (decision and decision["decision"] == "positive_only")):
                raise ValueError("Positive-only or unreviewed coverage cannot enter an evaluation split")
            if cohort is not None and row["split"] == "train" and row_complete and row["frame_id"] not in cohort["qa_plan"]["full_review_train_ids"]:
                raise ValueError("Full training coverage requires predeclared visual QA")
            image = cv2.imread(str(safe_source(dataset_root, row["rgb"])), cv2.IMREAD_COLOR)
            if image is None or image.shape[:2] != (row["height"], row["width"]):
                raise ValueError("RGB dimensions differ from original camera metadata")
            try:
                annotations = json.loads(safe_source(dataset_root, row["annotation"]).read_text())
                positive, valid, stats = rasterize_annotations(annotations, row["width"], row["height"], row_complete)
            except ValueError as error:
                if not quarantine_invalid_annotations:
                    raise
                excluded.append({"frame_id": row["frame_id"], "group_id": row["group_id"],
                    "official_split": row["official_split"], "assigned_split": row["split"],
                    "reason": "Invalid annotation: " + str(error),
                    "annotation_sha256": objects[row["annotation"]]["sha256"]})
                continue
            if not row_complete and stats["positive_pixels"] == 0:
                excluded.append({"frame_id":row["frame_id"], "group_id":row["group_id"],
                    "official_split":row["official_split"], "assigned_split":row["split"],
                    "reason":"Source QA: Positive-only frame contains no eligible paint pixels; no valid supervision",
                    "annotation_sha256":objects[row["annotation"]]["sha256"]})
                continue
            if cohort is not None:
                size = cohort["qa_plan"]["training_input_size"]
                stats.update(loss_space_counts(positive, valid, row["width"], row["height"], size))
                if stats["training_input_valid_pixels"] == 0:
                    excluded.append({"frame_id":row["frame_id"], "group_id":row["group_id"],
                        "official_split":row["official_split"], "assigned_split":row["split"],
                        "reason":"Source QA: No valid supervision survives predeclared training letterbox",
                        "annotation_sha256":objects[row["annotation"]]["sha256"], "training_input_size":size})
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
            row["annotation_coverage"] = "complete_lane_markings" if row_complete else "positive_only"
            row["coverage_decision"] = decision["decision"] if decision else "legacy_receipt"
            stats["negative_pixels"] = stats["valid_pixels"] - stats["positive_pixels"]
            row["transform"] = {"type": "identity", "sourceWidth": row["width"], "sourceHeight": row["height"]}
            row["statistics"] = stats
            selected.append(row)
        train_rows = [row for row in selected if row["split"] == "train"]
        train_positive = sum(row["statistics"]["positive_pixels"] for row in train_rows)
        train_valid = sum(row["statistics"]["valid_pixels"] for row in train_rows)
        coverage_counts = {}
        for row in selected:
            entry = coverage_counts.setdefault(row["split"], {}).setdefault(row["annotation_coverage"], {"frames":0, "positive_pixels":0, "valid_pixels":0, "negative_pixels":0})
            entry["frames"] += 1
            for key in ("positive_pixels", "valid_pixels", "negative_pixels"):
                entry[key] += row["statistics"][key]
        retained_test_groups = len({row["group_id"] for row in selected if row["split"] == "test"})
        cohort_gate = cohort is None or retained_test_groups >= cohort["grouping"]["min_test_groups"]
        manifest = {"schemaVersion": 1, "dataset": "ZOD", "target_kind": "paint",
            "source_revision": receipt["source_revision"], "source_url": receipt["source_url"],
            "license": LICENSE, "license_url": "https://zod.zenseact.com/license/", "source_receipt": receipt,
            "sdk_reference_revision": SDK_REVISION, "adapter_sha256": sha256_file(__file__),
            "objects": list(objects.values()), "pairs": selected, "excluded": excluded,
            "exclusion_counts": dict(Counter("invalid_annotation" if row["reason"].startswith("Invalid annotation:") else "source_qa" if row["reason"].startswith("Source QA:") else "split_overlap" for row in excluded)),
            "quarantine_invalid_annotations": quarantine_invalid_annotations,
            "grouping": cohort["grouping"] if cohort else {"method": "vehicle-capture-day-or-geographic-connected-components-v1", "proximity_m": proximity_m,
                "validation_fraction": validation_fraction, "official_val": "test", "overlap_policy": "exclude official train components touching official val"},
            "partition_counts": {split: sum(row["split"] == split for row in selected) for split in ("train", "validation", "test")},
            "training_eligible": cohort_gate and (complete or receipt["annotation_coverage"] == "per_frame") and train_positive > 0 and any(row["split"] != "train" for row in selected) and all(row["annotation_coverage"] == "complete_lane_markings" for row in selected if row["split"] != "train"),
            "cohort_post_qa_gate": {"passed":cohort_gate, "retained_test_groups":retained_test_groups, "minimum_test_groups":cohort["grouping"]["min_test_groups"] if cohort else None},
            "coverage_counts": coverage_counts,
            "cohort_selection": cohort,
            "supervision_policy": "Positive-only rows supervise annotated paint only; all unlabeled pixels are ignored. Use with A2D2 dense negatives in mixed-source training; no standalone coverage/accuracy claim. Evaluation requires reviewed complete coverage.",
            "mask_policy": {"positive": sorted(POSITIVE_CLASSES), "explicit_ignore": sorted(IGNORE_CLASSES) + ["road_painting", "unclear", "odd"],
                "unmarked_pixels": "per-pair annotation_coverage: complete_lane_markings is valid negative; positive_only is ignored", "overlap": "ignore wins",
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
    parser.add_argument("--cohort-selection", type=Path, help="Hash-bound predeclared cohort with ALL-source grouping")
    args = parser.parse_args()
    try:
        result = prepare(args.dataset_root, args.trainval, args.source_receipt, args.output_dir, args.proximity_m, args.validation_fraction, args.quarantine_invalid_annotations, args.cohort_selection)
    except (ValueError, KeyError, TypeError, OSError) as error:
        parser.error(str(error))
    print(json.dumps({key: result[key] for key in ("dataset", "partition_counts", "training_eligible", "qualification")}, indent=2))


if __name__ == "__main__":
    main()
