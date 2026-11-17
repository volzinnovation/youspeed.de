#!/usr/bin/env python3
"""Offline, class-blind map-point candidates for every HF detector image.

This is a metadata/geometry feasibility audit, not a visual review or a label
exporter. A nearby point inside a hypothetical camera cone does not establish
visibility, physical identity or a bounding box. No mapped sign classes are read.
No network calls, image downloads, training or source-data mutations are made.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from datetime import datetime
from fractions import Fraction
import gzip
from hashlib import sha256
import json
import math
from pathlib import Path
import re

EARTH_RADIUS_M = 6_371_008.8
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}


def digest(path):
    result = sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def json_lines(path):
    with text_stream(path) as stream:
        for number, line in enumerate(stream, 1):
            if line.strip():
                try:
                    yield json.loads(line)
                except json.JSONDecodeError as error:
                    raise ValueError(f"Invalid JSON at {path}:{number}") from error


def text_stream(path, mode="rt"):
    return gzip.open(path, mode) if str(path).endswith(".gz") else Path(path).open(mode)


def geojson_features(path):
    """Read the root FeatureCollection incrementally with the standard decoder."""
    decoder = json.JSONDecoder()
    with text_stream(path) as stream:
        buffer, position, exhausted = "", 0, False

        def fill():
            nonlocal buffer, position, exhausted
            block = stream.read(64 * 1024)
            buffer = buffer[position:] + block
            position = 0
            exhausted = not block

        def whitespace():
            nonlocal position
            while True:
                while position < len(buffer) and buffer[position].isspace():
                    position += 1
                if position < len(buffer) or exhausted:
                    return
                fill()

        def token(expected):
            nonlocal position
            whitespace()
            if position >= len(buffer) or buffer[position] != expected:
                raise ValueError(f"Invalid GeoJSON; expected {expected!r}")
            position += 1

        def value():
            nonlocal position
            whitespace()
            while True:
                try:
                    result, end = decoder.raw_decode(buffer, position)
                    if end == len(buffer) and not exhausted:
                        fill()
                        continue
                    position = end
                    return result
                except json.JSONDecodeError:
                    if exhausted:
                        raise ValueError("Invalid or truncated GeoJSON")
                    fill()

        token("{")
        collection_type, found = None, False
        while True:
            key = value()
            token(":")
            if key == "features":
                if found:
                    raise ValueError("Duplicate GeoJSON features member")
                found = True
                token("[")
                whitespace()
                if position < len(buffer) and buffer[position] != "]":
                    while True:
                        feature = value()
                        if not isinstance(feature, dict):
                            raise ValueError("GeoJSON feature is not an object")
                        yield feature
                        whitespace()
                        if position < len(buffer) and buffer[position] == "]":
                            break
                        token(",")
                token("]")
            else:
                item = value()
                if key == "type":
                    collection_type = item
            whitespace()
            if position < len(buffer) and buffer[position] == "}":
                token("}")
                break
            token(",")
        whitespace()
        if position != len(buffer) or not found or collection_type != "FeatureCollection":
            raise ValueError("Expected a complete GeoJSON FeatureCollection")


def numeric(value):
    if isinstance(value, str):
        try:
            value = float(Fraction(value))
        except (ValueError, OverflowError, ZeroDivisionError):
            return None
    return float(value) if type(value) in (int, float) and math.isfinite(value) else None


def point(geometry):
    if not isinstance(geometry, dict) or geometry.get("type") != "Point":
        return None
    coordinates = geometry.get("coordinates")
    if not isinstance(coordinates, list) or len(coordinates) < 2:
        return None
    lon, lat = map(numeric, coordinates[:2])
    if lon is None or lat is None or not (-180 <= lon <= 180 and -90 <= lat <= 90):
        return None
    return lon, lat


def angular_difference(a, b):
    return abs((a - b + 180) % 360 - 180)


def distance_and_bearing(origin, target):
    """Spherical range and true-north initial bearing; coincident has no bearing."""
    lon1, lat1 = map(math.radians, origin)
    lon2, lat2 = map(math.radians, target)
    dlon, dlat = lon2 - lon1, lat2 - lat1
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    distance = 2 * EARTH_RADIUS_M * math.asin(math.sqrt(min(1, max(0, h))))
    if distance < 0.001:
        return distance, None
    bearing = math.degrees(math.atan2(math.sin(dlon) * math.cos(lat2),
        math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon))) % 360
    return distance, bearing


def cartesian(coordinates):
    lon, lat = map(math.radians, coordinates)
    return (EARTH_RADIUS_M * math.cos(lat) * math.cos(lon),
            EARTH_RADIUS_M * math.cos(lat) * math.sin(lon), EARTH_RADIUS_M * math.sin(lat))


class PointIndex:
    """3-D chord grid: nearby spherical points cannot escape adjacent cells."""

    def __init__(self, features, radius_m, camera_coordinates=None):
        self.radius_m = radius_m
        self.cells = defaultdict(list)
        self.counts = Counter()
        relevant_cells = None
        if camera_coordinates is not None:
            relevant_cells = set()
            for coordinates in camera_coordinates:
                a, b, c = self.key(coordinates)
                relevant_cells.update((x, y, z) for x in range(a - 1, a + 2)
                                     for y in range(b - 1, b + 2) for z in range(c - 1, c + 2))
        identifiers = set()
        for feature in features:
            self.counts["input_features"] += 1
            coordinates = point(feature.get("geometry"))
            properties = feature.get("properties") or {}
            identifier = feature.get("id", properties.get("id"))
            if coordinates is None or identifier is None:
                self.counts["invalid_geometry_or_missing_id"] += 1
                continue
            identifier = str(identifier)
            if identifier in identifiers:
                raise ValueError(f"Duplicate Mapillary feature ID: {identifier}")
            identifiers.add(identifier)
            if relevant_cells is not None and self.key(coordinates) not in relevant_cells:
                self.counts["outside_camera_neighbor_cells"] += 1
                continue
            # Only ID and geometry survive intake. No sign classes, headings or
            # classifier confidence from the map are used to select candidates.
            self.cells[self.key(coordinates)].append((identifier, coordinates))
            self.counts["indexed_points"] += 1

    def key(self, coordinates):
        return tuple(math.floor(value / self.radius_m) for value in cartesian(coordinates))

    def nearby(self, coordinates):
        a, b, c = self.key(coordinates)
        matches = []
        for x in range(a - 1, a + 2):
            for y in range(b - 1, b + 2):
                for z in range(c - 1, c + 2):
                    for identifier, target in self.cells.get((x, y, z), ()):
                        distance, bearing = distance_and_bearing(coordinates, target)
                        if distance <= self.radius_m:
                            matches.append(dict(mapillary_id=identifier, coordinates=list(target),
                                                range_m=distance, bearing_deg=bearing))
        return sorted(matches, key=lambda item: (item["range_m"], item["mapillary_id"]))


def timestamp(value):
    if not isinstance(value, str):
        return None
    try:
        # Python 3.10 accepts only three/six fractional digits, while the
        # Panoramax timestamps legitimately use one/two digits as well.
        value = value.replace("Z", "+00:00")
        value = re.sub(r"(\d{2}:\d{2}:\d{2})\.(\d{1,6})(?=[+-]\d{2}:\d{2}$)",
                       lambda match: match[1] + "." + match[2].ljust(6, "0"), value)
        result = datetime.fromisoformat(value)
        return result if result.tzinfo else None
    except ValueError:
        return None


def camera_pose(row, annotation):
    """Qualify an explicit forward-mounted-phone hypothesis, never optical yaw.

    Course/EXIF, landscape, FOV, crop and fix-age checks follow the conservative
    forward-phone metadata conditions in the prior Panoramax ray investigation.
    This audit deliberately does not infer the phone's mounting orientation.
    """
    source = annotation.get("source_metadata") or {}
    picture = source.get("picture") or {}
    metadata = picture.get("metadata") or {}
    exif = picture.get("exif") or {}
    coordinates = point(picture.get("geometry"))
    heading = numeric(picture.get("heading"))
    course = numeric(exif.get("Exif.GPSInfo.GPSImgDirection"))
    fov = numeric(metadata.get("field_of_view"))
    accuracy = numeric(picture.get("gps_accuracy_m"))
    width, height = numeric(metadata.get("width")), numeric(metadata.get("height"))
    captured, fixed = timestamp(metadata.get("ts_camera")), timestamp(metadata.get("ts_gps"))
    fix_age = abs((captured - fixed).total_seconds()) if captured and fixed else None
    reasons = []
    if not source:
        reasons.append("source_metadata_missing")
    if coordinates is None:
        reasons.append("camera_coordinates_missing_or_invalid")
    if metadata.get("type") != "flat":
        reasons.append("projection_not_flat")
    make, model = str(metadata.get("make", "")).lower(), str(metadata.get("model", "")).lower()
    if not ((make == "apple" and model.startswith("iphone")) or (make == "motorola" and model.startswith("moto"))):
        reasons.append("unsupported_phone_provenance")
    if width is None or height is None or width <= height or height <= 0:
        reasons.append("not_registered_landscape")
    if [width, height] != row.get("dimensions") or annotation.get("dimensions") != row.get("dimensions"):
        reasons.append("registered_dimensions_mismatch")
    if metadata.get("crop") is not None:
        reasons.append("cropped_camera_geometry")
    if any(metadata.get(key) is not None and numeric(metadata[key]) != 0 for key in ("yaw", "pitch", "roll")):
        reasons.append("nonzero_or_invalid_camera_pose")
    # Original EXIF orientation 3 rotates the raster by 180 degrees, but does
    # not alter the central optical axis or the horizontal cone's angular span.
    # This audit never projects bearings to image pixels. Quarter-turn/mirror
    # cases remain unqualified until their processed-raster transform is known.
    if exif.get("Exif.Image.Orientation") is not None and numeric(exif["Exif.Image.Orientation"]) not in (1, 3):
        reasons.append("unsupported_original_exif_orientation")
    if heading is None or not 0 <= heading <= 360:
        reasons.append("heading_missing_or_invalid")
    if course is None or not 0 <= course <= 360 or str(exif.get("Exif.GPSInfo.GPSImgDirectionRef", "")).upper() != "T":
        reasons.append("true_course_missing_or_invalid")
    elif heading is not None and angular_difference(heading, course) > 1.5:
        reasons.append("heading_course_disagreement")
    if picture.get("heading_computed") is not False:
        reasons.append("heading_computed_or_provenance_unknown")
    if fov is None or not 45 <= fov <= 100:
        reasons.append("fov_missing_or_outside_45_100")
    if accuracy is None or not 0 <= accuracy <= 25:
        reasons.append("gps_accuracy_missing_or_over_25m")
    if fix_age is None or fix_age > 3:
        reasons.append("capture_fix_age_missing_or_over_3s")
    return dict(coordinates=list(coordinates) if coordinates else None,
                heading_proxy_deg=heading, exif_course_deg=course, declared_fov_deg=fov,
                gps_accuracy_m=accuracy, capture_fix_age_s=fix_age,
                gps_accuracy_interpretation="declared_metadata_may_be_estimated_not_verified_measurement",
                projection=metadata.get("type"), source_dimensions=[width, height],
                original_exif_orientation=exif.get("Exif.Image.Orientation"),
                camera_make=metadata.get("make"), camera_model=metadata.get("model"),
                cone_eligible=not reasons, cone_ineligibility_reasons=reasons,
                optical_yaw_measured=False,
                heading_interpretation="phone_location_course_proxy_not_measured_optical_yaw",
                sequence_ids=sorted({str(entry["id"]) for entry in source.get("collections", []) if entry.get("id")}))


def image_candidates(pose, index, margin_deg):
    if pose["coordinates"] is None:
        return [], 0, 0
    nearby = index.nearby(pose["coordinates"])
    candidates, rejected = [], 0
    for candidate in nearby:
        bearing = candidate["bearing_deg"]
        difference = angular_difference(bearing, pose["heading_proxy_deg"]) if bearing is not None and pose["heading_proxy_deg"] is not None else None
        if bearing is None:
            status = "ungated_coincident_coordinates_bearing_undefined"
        elif not pose["cone_eligible"]:
            status = "ungated_camera_pose_unqualified"
        elif difference <= pose["declared_fov_deg"] / 2 + margin_deg:
            status = "inside_hypothetical_forward_phone_cone"
        else:
            rejected += 1
            continue
        candidates.append(candidate | {"heading_difference_deg": difference, "status": status})
    return candidates, len(nearby), rejected


def audit(tree_path, metadata_path, source_plan_path, mapillary_path, output, *, prefix="data/2026-11/detector/", radius_m=150, margin_deg=15):
    if not math.isfinite(radius_m) or not 0 < radius_m <= 10_000:
        raise ValueError("Radius must be in (0, 10000] metres")
    if not math.isfinite(margin_deg) or not 0 <= margin_deg <= 90:
        raise ValueError("Cone margin must be in [0, 90] degrees")
    tree = json.loads(Path(tree_path).read_text())
    image_paths = {entry["path"] for entry in tree["files"] if entry.get("type") == "RepoFile" and entry["path"].startswith(prefix) and Path(entry["path"]).suffix.lower() in IMAGE_SUFFIXES}
    if not image_paths:
        raise ValueError("HF tree has no detector image files")
    rows = {}
    for row in json_lines(metadata_path):
        if row.get("path") in image_paths:
            if row["path"] in rows:
                raise ValueError(f"Duplicate metadata image: {row['path']}")
            if row.get("task") != "detector":
                raise ValueError("Detector tree image has another metadata task")
            rows[row["path"]] = row
    camera_coordinates = []
    for planned in json_lines(source_plan_path):
        if planned.get("row", {}).get("path") in image_paths:
            picture = ((planned.get("annotation") or {}).get("source_metadata") or {}).get("picture") or {}
            coordinates = point(picture.get("geometry"))
            if coordinates is not None:
                camera_coordinates.append(coordinates)
    index = PointIndex(geojson_features(mapillary_path), radius_m, camera_coordinates)
    del camera_coordinates
    output = Path(output)
    output.mkdir(parents=True, exist_ok=True)
    records_path = output / "image-candidates.jsonl.gz"
    counts, pose_reasons, candidate_statuses, field_coverage = Counter(), Counter(), Counter(), Counter()
    seen = set()

    def emit(path, annotation, stream):
        row = rows.get(path, {"path": path})
        pose = camera_pose(row, annotation)
        candidates, nearby, rejected = image_candidates(pose, index, margin_deg)
        counts["images"] += 1
        counts["images_with_source_metadata"] += bool(annotation.get("source_metadata"))
        counts["cone_eligible_images"] += pose["cone_eligible"]
        counts["images_with_nearby_map_points"] += nearby > 0
        counts["images_with_retained_candidates"] += bool(candidates)
        counts["images_with_cone_candidates"] += any(c["status"] == "inside_hypothetical_forward_phone_cone" for c in candidates)
        counts["nearby_pairs"] += nearby
        counts["retained_pairs"] += len(candidates)
        counts["pairs_outside_hypothetical_cone"] += rejected
        pose_reasons.update(pose["cone_ineligibility_reasons"])
        candidate_statuses.update(c["status"] for c in candidates)
        for key in ("coordinates", "heading_proxy_deg", "exif_course_deg", "declared_fov_deg", "gps_accuracy_m", "capture_fix_age_s", "projection", "camera_make", "camera_model"):
            field_coverage[key] += pose[key] is not None
        field_coverage["sequence_ids"] += bool(pose["sequence_ids"])
        record = dict(image_path=path, picture_id=row.get("picture_id"), sample_id=row.get("sample_id"),
                      image_sha256=row.get("sha256"), annotation_sha256=row.get("annotation_sha256"),
                      source_revision=row.get("source_revision"), capture_at=row.get("capture_at"),
                      metadata_present=path in rows, pose=pose, nearby_count=nearby,
                      outside_cone_count=rejected, candidate_count=len(candidates), candidates=candidates,
                      visual_review_status="not_performed_by_this_script", visibility_established=False,
                      training_labels_created=False)
        stream.write(json.dumps(record, separators=(",", ":"), allow_nan=False) + "\n")

    # Fixed gzip timestamp and empty header filename make identical audits
    # reproducible byte-for-byte, including the output digest.
    import io
    with records_path.open("wb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as compressed, io.TextIOWrapper(compressed, encoding="utf-8") as stream:
        for planned in json_lines(source_plan_path):
            row = planned.get("row", {})
            path = row.get("path")
            if path not in image_paths:
                continue
            if path in seen:
                raise ValueError(f"Duplicate source-plan image: {path}")
            seen.add(path)
            actual = rows.get(path)
            if actual:
                for key in ("sample_id", "picture_id", "source_revision", "dimensions"):
                    if actual.get(key) != row.get(key):
                        raise ValueError(f"Source plan differs from pinned metadata: {path} ({key})")
                if row.get("sha256") and actual.get("sha256") != row["sha256"]:
                    raise ValueError(f"Source plan image hash differs: {path}")
            emit(path, planned.get("annotation") or {}, stream)
        for path in sorted(image_paths - seen):
            emit(path, {}, stream)
    inputs = {key: dict(path=str(Path(path).resolve()), sha256=digest(path), bytes=Path(path).stat().st_size)
              for key, path in (("hf_tree", tree_path), ("hf_metadata", metadata_path), ("hf_source_plan", source_plan_path), ("mapillary_geojson", mapillary_path))}
    summary = dict(schema="youspeed-hf-mapillary-teacher-feasibility-v1", hf_revision=tree.get("revision"),
                   script_sha256=digest(__file__), inputs=inputs, mapillary_points=dict(index.counts),
                   tree_image_count=len(image_paths), metadata_image_count=len(rows), source_plan_image_count=len(seen),
                   counts=dict(counts), pose_ineligibility_reasons=dict(pose_reasons),
                   metadata_field_presence=dict(field_coverage), candidate_statuses=dict(candidate_statuses),
                   configuration=dict(detector_prefix=prefix, radius_m=radius_m, cone_margin_deg=margin_deg,
                       cone_half_angle="declared_fov_deg / 2 + cone_margin_deg", earth_radius_m=EARTH_RADIUS_M,
                       heading_course_max_difference_deg=1.5, gps_accuracy_max_m=25, capture_fix_max_age_s=3,
                       declared_fov_range_deg=[45, 100], class_blind=True),
                   limitations=["No image pixels inspected; every row is a metadata audit, not a visual assessment.",
                       "Location course is a heading proxy; forward mounting, optical yaw and true horizontal FOV are unverified.",
                       "The configurable cone margin is a screening hypothesis, not a calibrated uncertainty bound.",
                       "GPS accuracy is declared source metadata and may be a fallback estimate, not measured position error.",
                       "Range and azimuth do not establish line of sight, sign facing, occlusion, persistence, identity or a box.",
                       "No candidates or an out-of-cone point do not establish a negative image or absent traffic sign.",
                       "Missing or unqualified pose keeps all nearby points ungated; coincident points have undefined bearing.",
                       "Image bytes and sidecar hashes are indexed, not verified by this metadata-only script."],
                   output=dict(path=str(records_path.resolve()), sha256=digest(records_path), rows=counts["images"]))
    (output / "summary.json").write_text(json.dumps(summary, indent=2, allow_nan=False) + "\n")
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tree", type=Path, required=True)
    parser.add_argument("--metadata", type=Path, required=True)
    parser.add_argument("--source-plan", type=Path, required=True)
    parser.add_argument("--mapillary", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--prefix", default="data/2026-11/detector/")
    parser.add_argument("--radius-m", type=float, default=150)
    parser.add_argument("--cone-margin-deg", type=float, default=15)
    args = parser.parse_args()
    result = audit(args.tree, args.metadata, args.source_plan, args.mapillary, args.output,
                   prefix=args.prefix, radius_m=args.radius_m, margin_deg=args.cone_margin_deg)
    print(json.dumps({"hf_revision": result["hf_revision"], "counts": result["counts"], "output": result["output"]}, indent=2))


if __name__ == "__main__":
    main()
