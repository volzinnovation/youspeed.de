#!/usr/bin/env python3
"""Local equirectangular -> rectilinear QA proposals; never approved ground truth.

Coordinates use pixel EDGES. Pano longitude zero is its horizontal midpoint,
not geographic north. Raster x increases with longitude; y increases downward.
Input x0 > x1 means a source box crossing the periodic panorama seam.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import hashlib
import json
import math
import os
from pathlib import Path
import shutil
import tempfile

import numpy as np
from PIL import Image


TRANSFORM_VERSION = "spherical-pinhole-bilinear-v1"


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2,
                                    allow_nan=False) + "\n", encoding="utf-8")


def panorama_directions(u, v, width, height):
    """Native pixel-edge positions -> world unit vectors (right, up, forward)."""
    lon = 2 * np.pi * (np.asarray(u) / width - 0.5)
    lat = np.pi * (0.5 - np.asarray(v) / height)
    lon, lat = np.broadcast_arrays(lon, lat)
    return np.stack((np.cos(lat) * np.sin(lon), np.sin(lat),
                     np.cos(lat) * np.cos(lon)), axis=-1)


def directions_to_panorama(directions, width, height):
    d = np.asarray(directions, dtype=np.float64)
    lon = np.arctan2(d[..., 0], d[..., 2])
    lat = np.arctan2(d[..., 1], np.hypot(d[..., 0], d[..., 2]))
    return np.stack(((lon / (2 * np.pi) + 0.5) * width % width,
                     (0.5 - lat / np.pi) * height), axis=-1)


@dataclass(frozen=True)
class Camera:
    width: int
    height: int
    horizontal_fov_degrees: float
    longitude_radians: float
    latitude_radians: float

    def __post_init__(self):
        if not (isinstance(self.width, int) and isinstance(self.height, int)
                and self.width >= 2 and self.height >= 2):
            raise ValueError("Ausgaberaster muss mindestens2x2Pixel enthalten.")
        values = [self.horizontal_fov_degrees, self.longitude_radians, self.latitude_radians]
        if not all(math.isfinite(x) for x in values):
            raise ValueError("Kamerawinkel müssen endlich sein.")
        if not 0 < self.horizontal_fov_degrees < 179:
            raise ValueError("Horizontales Sichtfeld muss zwischen0und179Grad liegen.")
        if not -np.pi / 2 <= self.latitude_radians <= np.pi / 2:
            raise ValueError("Vertikaler Mittelpunkt liegt außerhalb der Kugel.")

    @property
    def focal_pixels(self):
        return self.width / (2 * math.tan(math.radians(self.horizontal_fov_degrees) / 2))

    @property
    def vertical_fov_degrees(self):
        return math.degrees(2 * math.atan(self.height / (2 * self.focal_pixels)))

    def basis(self):
        """Columns are camera right, up, forward in the source sphere axes."""
        lon, lat = self.longitude_radians, self.latitude_radians
        right = [math.cos(lon), 0.0, -math.sin(lon)]
        up = [-math.sin(lat) * math.sin(lon), math.cos(lat),
              -math.sin(lat) * math.cos(lon)]
        forward = [math.cos(lat) * math.sin(lon), math.sin(lat),
                   math.cos(lat) * math.cos(lon)]
        return np.column_stack((right, up, forward))


def checked_box(box, width, height):
    if len(box) != 4 or not all(math.isfinite(float(x)) for x in box):
        raise ValueError("Box benötigt vier endliche native Pixelkoordinaten.")
    x0, y0, x1, y1 = map(float, box)
    if not (0 <= x0 < width and 0 <= x1 <= width and 0 <= y0 < y1 <= height):
        raise ValueError("Box liegt außerhalb des unveränderten nativen Rasters.")
    span = x1 - x0 if x1 > x0 else x1 + width - x0
    if not 0 < span <= width or x0 == x1:
        raise ValueError("Box besitzt keine gültige horizontale Ausdehnung.")
    return (x0, y0, x1, y1), span


def camera_for_box(box, source_width, source_height, width=1920, height=1080, hfov=75.0):
    (x0, y0, _, y1), span = checked_box(box, source_width, source_height)
    u, v = (x0 + span / 2) % source_width, (y0 + y1) / 2
    return Camera(width, height, hfov, 2 * np.pi * (u / source_width - 0.5),
                  np.pi * (0.5 - v / source_height))


def viewport_to_panorama(x, y, camera, source_width, source_height):
    """Viewport pixel-edge positions -> native pano pixel-edge positions."""
    x, y = np.broadcast_arrays(np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64))
    rays = np.stack(((x - camera.width / 2) / camera.focal_pixels,
                     (camera.height / 2 - y) / camera.focal_pixels,
                     np.ones_like(x)), axis=-1)
    basis = camera.basis()
    world = (rays[..., 0, None] * basis[:, 0] + rays[..., 1, None] * basis[:, 1]
             + rays[..., 2, None] * basis[:, 2])
    return directions_to_panorama(world, source_width, source_height)


def directions_to_viewport(directions, camera):
    """World rays -> edge coordinates and depth. Behind-camera values are NaN."""
    d, basis = np.asarray(directions), camera.basis()
    # Three explicit scalar products avoid a platform BLAS dependency for3Dmath.
    rays = np.stack([d[..., 0] * basis[0, j] + d[..., 1] * basis[1, j]
                     + d[..., 2] * basis[2, j] for j in range(3)], axis=-1)
    z = rays[..., 2]
    front = z > 1e-10
    denominator = np.where(front, z, np.nan)
    xy = np.stack((camera.width / 2 + camera.focal_pixels * rays[..., 0] / denominator,
                   camera.height / 2 - camera.focal_pixels * rays[..., 1] / denominator), axis=-1)
    return xy, z


def bilinear_sample(source, uv):
    """Periodic x, clamped poles; pixel edges -> sample-index coordinates -0.5."""
    height, width = source.shape[:2]
    x = (uv[..., 0] - 0.5) % width
    y = np.clip(uv[..., 1] - 0.5, 0, height - 1)
    x0, y0 = np.floor(x).astype(np.int64), np.floor(y).astype(np.int64)
    x1, y1 = (x0 + 1) % width, np.minimum(y0 + 1, height - 1)
    wx, wy = (x - x0)[..., None], (y - y0)[..., None]
    top = source[y0, x0].astype(np.float32) * (1 - wx) + source[y0, x1].astype(np.float32) * wx
    bottom = source[y1, x0].astype(np.float32) * (1 - wx) + source[y1, x1].astype(np.float32) * wx
    return top * (1 - wy) + bottom * wy


def render(source, camera, block_rows=64):
    if not isinstance(block_rows, int) or not 1 <= block_rows <= 256:
        raise ValueError("Zeilenblock muss zwischen1und256liegen.")
    if source.ndim != 3 or source.shape[2] != 3:
        raise ValueError("Quelldaten müssen ein RGB-Raster sein.")
    result = np.empty((camera.height, camera.width, 3), dtype=np.uint8)
    x = np.arange(camera.width, dtype=np.float64)[None, :] + 0.5
    for y0 in range(0, camera.height, block_rows):
        y1 = min(camera.height, y0 + block_rows)
        y = np.arange(y0, y1, dtype=np.float64)[:, None] + 0.5
        uv = viewport_to_panorama(x, y, camera, source.shape[1], source.shape[0])
        result[y0:y1] = np.clip(np.rint(bilinear_sample(source, uv)), 0, 255).astype(np.uint8)
    return result


def project_box(box, source_width, source_height, camera, edge_samples=1025):
    if not isinstance(edge_samples, int) or edge_samples < 65:
        raise ValueError("Mindestens65Stützpunkte pro Boxrand erforderlich.")
    (x0, y0, _, y1), span = checked_box(box, source_width, source_height)
    xs, ys = np.linspace(x0, x0 + span, edge_samples), np.linspace(y0, y1, edge_samples)
    u = np.concatenate((xs, xs, np.full(edge_samples, x0), np.full(edge_samples, x0 + span)))
    v = np.concatenate((np.full(edge_samples, y0), np.full(edge_samples, y1), ys, ys))
    xy, depth = directions_to_viewport(panorama_directions(u, v, source_width, source_height), camera)
    behind = depth <= 1e-10
    result = {"method": "dense_source_box_perimeter_then_floor_ceil_with_one_pixel_margin",
              "samples_per_edge": edge_samples, "boundary_samples": len(depth),
              "source_seam_crossing": box[2] < box[0],
              "has_boundary_at_or_behind_camera": bool(np.any(behind)),
              "boundary_samples_at_or_behind_camera": int(np.count_nonzero(behind)),
              "bbox_xyxy_float": None, "bbox_xyxy_pixels": None,
              "target_clipped_by_viewport": None, "status": None}
    if np.any(behind):
        result["status"] = "boundary_not_fully_in_front_of_camera_no_valid_target_box"
        return result
    minimum, maximum = xy.min(axis=0), xy.max(axis=0)
    result["bbox_xyxy_float"] = [float(minimum[0]), float(minimum[1]), float(maximum[0]), float(maximum[1])]
    result["target_clipped_by_viewport"] = bool(minimum[0] < 0 or minimum[1] < 0
                                                or maximum[0] > camera.width or maximum[1] > camera.height)
    clipped = [max(0, math.floor(minimum[0]) - 1), max(0, math.floor(minimum[1]) - 1),
               min(camera.width, math.ceil(maximum[0]) + 1), min(camera.height, math.ceil(maximum[1]) + 1)]
    if clipped[0] >= clipped[2] or clipped[1] >= clipped[3]:
        result["status"] = "outside_viewport_no_target_crop"
        return result
    result["bbox_xyxy_pixels"] = clipped
    result["status"] = "clipped_requires_review" if result["target_clipped_by_viewport"] else "fully_visible_proposal_requires_review"
    return result


def source_annotation_box(item, annotation_id):
    matches = [a for a in item.get("properties", {}).get("annotations", []) if a.get("id") == annotation_id]
    if len(matches) != 1 or matches[0].get("shape", {}).get("type") != "Polygon":
        raise ValueError("Angegebene Originalannotation fehlt oder besitzt keine Polygonbox.")
    points = matches[0]["shape"]["coordinates"][0]
    return [min(p[0] for p in points), min(p[1] for p in points),
            max(p[0] for p in points), max(p[1] for p in points)]


def create_projection(image_path, item_path, box, output, *, source_annotation_id=None,
                      class_proposal=None, expected_image_sha256=None, expected_item_sha256=None,
                      width=1920, height=1080, hfov=75.0, block_rows=64, edge_samples=1025):
    image_path, item_path, output = Path(image_path).resolve(), Path(item_path).resolve(), Path(output).resolve()
    if output.exists():
        raise ValueError("Ausgabeordner existiert bereits; wählen Sie einen neuen Pfad.")
    image_sha, item_sha = sha256(image_path), sha256(item_path)
    if expected_image_sha256 and image_sha != expected_image_sha256:
        raise ValueError("HD-Raster stimmt nicht mit der erwarteten SHA256überein.")
    if expected_item_sha256 and item_sha != expected_item_sha256:
        raise ValueError("Originalitem stimmt nicht mit der erwarteten SHA256überein.")
    item = json.loads(item_path.read_text(encoding="utf-8"))
    props = item.get("properties", {})
    orientation = props.get("pers:interior_orientation", {})
    if orientation.get("field_of_view") != 360:
        raise ValueError("Originalmetadaten müssen ein360-Grad-Panorama ausweisen.")
    with Image.open(image_path) as image:
        if image.getexif().get(274) not in (None, 1):
            raise ValueError("EXIF-Orientierung würde natives Raster drehen; keine stille Korrektur erlaubt.")
        sw, sh = image.size
        if sw != 2 * sh or orientation.get("sensor_array_dimensions") != [sw, sh]:
            raise ValueError("Native2:1-Abmessungen stimmen nicht mit den Originalmetadaten überein.")
        exif = props.get("exif", {})
        if exif.get("Xmp.GPano.ProjectionType", "equirectangular") != "equirectangular":
            raise ValueError("Eingabe ist laut Metadaten nicht equirektangular.")
        rgb = image.convert("RGB")
        source = np.asarray(rgb)
        rgb.close()
    checked_box(box, sw, sh)
    if source_annotation_id is not None and not np.array_equal(source_annotation_box(item, source_annotation_id), box):
        raise ValueError("Native Eingabebox stimmt nicht mit der angegebenen Originalannotation überein.")
    camera = camera_for_box(box, sw, sh, width, height, hfov)
    projected = project_box(box, sw, sh, camera, edge_samples)
    raster = render(source, camera, block_rows)
    source_url = next((link["href"] for link in item.get("links", []) if link.get("rel") == "self"), None)
    asset_url = item.get("assets", {}).get("hd", {}).get("href")
    config = {"version": TRANSFORM_VERSION, "source_sha256": image_sha, "source_bbox": list(box),
              "width": width, "height": height, "horizontal_fov_degrees": hfov,
              "longitude_radians": camera.longitude_radians, "latitude_radians": camera.latitude_radians}
    config_sha = hashlib.sha256(json.dumps(config, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    proposal_id = "local-perspective-target-" + str(item.get("id", "unknown")) + "-" + config_sha[:12]
    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix="." + output.name + "-", dir=output.parent))
    try:
        Image.fromarray(raster).save(staging / "perspective.png")
        crop_box = projected["bbox_xyxy_pixels"]
        crop_file = None
        if crop_box is not None:
            crop_file = "target-crop-proposal.png"
            Image.fromarray(raster).crop(tuple(crop_box)).save(staging / crop_file)
        shutil.copyfile(item_path, staging / "source-item.json")
        relative_source = os.path.relpath(image_path, output)
        projection = {"schema_version": "youspeed-spherical-perspective-projection-v1",
                      "transform_version": TRANSFORM_VERSION, "transform_config_sha256": config_sha,
                      "picture_id": item.get("id"), "sequence_id": item.get("collection"),
                      "source_url": source_url, "source_asset_url": asset_url,
                      "source_file": relative_source, "source_sha256": image_sha,
                      "source_item_file": "source-item.json", "source_item_sha256": item_sha,
                      "source_item_data_modified": False, "source_raster_dimensions": [sw, sh],
                      "source_raster_orientation": "native_no_exif_rotation",
                      "source_bbox_xyxy": list(box), "source_bbox_coordinate_system": "native_panorama_pixel_edges",
                      "source_annotation_id": source_annotation_id,
                      "source_bbox_provenance": "verified_original_annotation" if source_annotation_id else "local_visual_inspection_box_proposal",
                      "license": props.get("license"), "author": props.get("geovisio:producer"),
                      "capture_datetime": props.get("datetime"), "camera_geometry": item.get("geometry"),
                      "viewport_center_relative_to_panorama": {
                          "native_pixel_edge_u": (camera.longitude_radians / (2 * np.pi) + 0.5) * sw % sw,
                          "native_pixel_edge_v": (0.5 - camera.latitude_radians / np.pi) * sh,
                          "longitude_degrees_from_panorama_midpoint": math.degrees(camera.longitude_radians),
                          "latitude_degrees_above_panorama_equator": math.degrees(camera.latitude_radians),
                          "is_geographic_heading": False},
                      "pinhole_camera": {"output_dimensions": [width, height], "horizontal_fov_degrees": hfov,
                                         "vertical_fov_degrees": camera.vertical_fov_degrees,
                                         "focal_length_pixels_x_and_y": camera.focal_pixels,
                                         "principal_point_pixel_edges": [width / 2, height / 2],
                                         "basis_columns_right_up_forward": camera.basis().tolist(), "roll_degrees": 0},
                      "transform_evidence": {
                          "source_unit_ray": "lon=2*pi*(u/W-0.5); lat=pi*(0.5-v/H); ray=(cos(lat)*sin(lon),sin(lat),cos(lat)*cos(lon))",
                          "output_ray": "camera_ray=((x-Wout/2)/f,(Hout/2-y)/f,1); world_ray=basis@camera_ray",
                          "sampling": "Bilinear RGB at output pixel centers; source array indices=(u-0.5,v-0.5); horizontal periodic wrap, vertical pole clamp.",
                          "block_rows": block_rows, "source_geographic_yaw_used": False,
                          "box_projection": projected},
                      "perspective_file": "perspective.png", "perspective_sha256": sha256(staging / "perspective.png"),
                      "target_crop_file": crop_file, "target_crop_sha256": sha256(staging / crop_file) if crop_file else None,
                      "all_visible_object_annotation_complete": False,
                      "human_approved": False, "eligible_for_training": False, "approved_for_evaluation": False,
                      "role": "prospective_test_candidates",
                      "note": "Local geometric derivative and target proposal. Source tags unchanged. No complete SGBlur ground truth; other visible objects have not been fully annotated."}
        write_json(staging / "projection.json", projection)
        proposal = {"schema_version": "youspeed-projected-box-proposal-v1", "proposal_id": proposal_id,
                    "annotation_source": "local_projection_of_native_source_box" if source_annotation_id else "local_visual_box_proposal_projected",
                    "source_annotation_id": source_annotation_id,
                    "picture_id": item.get("id"), "sequence_id": item.get("collection"),
                    "source_sha256": image_sha, "source_bbox_native": list(box),
                    "projection_file": "projection.json", "projection_sha256": sha256(staging / "projection.json"),
                    "image_file": "perspective.png", "image_sha256": projection["perspective_sha256"],
                    "bbox_xyxy": crop_box, "bbox_coordinate_system": "projected_pixel_edges_right_bottom_exclusive",
                    "box_geometry_status": projected["status"], "target_clipped_by_viewport": projected["target_clipped_by_viewport"],
                    "has_boundary_at_or_behind_camera": projected["has_boundary_at_or_behind_camera"],
                    "class_proposal": {"osm|traffic_sign": class_proposal,
                                       "model_label": {"DE:310": "city:start", "DE:311": "city:end"}.get(class_proposal)},
                    "crop_file": crop_file, "crop_sha256": projection["target_crop_sha256"],
                    "all_visible_object_annotation_complete": False,
                    "human_approved": False, "eligible_for_training": False, "approved_for_evaluation": False,
                    "review_required": "Confirm projection, native/projected box, class and physical-group independence; annotate every visible sign,plate,face before any SGBlur ground-truth claim."}
        write_json(staging / "box-proposal.json", proposal)
        if output.exists():
            raise ValueError("Ausgabe wurde inzwischen angelegt; nichts überschrieben.")
        staging.rename(output)
    finally:
        if staging.exists():
            shutil.rmtree(staging)
    return projection, proposal


def main(argv=None):
    parser = argparse.ArgumentParser(description="Lokale sphärische Perspektivprojektion mit ungeprüftem Boxvorschlag.")
    parser.add_argument("--image", type=Path, required=True, help="Verifiziertes natives2:1-HD-Panorama")
    parser.add_argument("--item", type=Path, required=True, help="Unverändertes Original-STAC-ItemJSON")
    parser.add_argument("--bbox", type=float, nargs=4, required=True, metavar=("X0", "Y0", "X1", "Y1"))
    parser.add_argument("--output", type=Path, required=True, help="Neuer Ausgabeordner")
    parser.add_argument("--source-annotation-id", help="Nur tatsächlich vorhandene Originalannotation; sonst weglassen")
    parser.add_argument("--class-proposal", choices=["DE:310", "DE:311"])
    parser.add_argument("--expected-image-sha256")
    parser.add_argument("--expected-item-sha256")
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    parser.add_argument("--hfov", type=float, default=75.0)
    parser.add_argument("--block-rows", type=int, default=64)
    parser.add_argument("--edge-samples", type=int, default=1025)
    args = parser.parse_args(argv)
    try:
        projection, proposal = create_projection(args.image, args.item, args.bbox, args.output,
            source_annotation_id=args.source_annotation_id, class_proposal=args.class_proposal,
            expected_image_sha256=args.expected_image_sha256, expected_item_sha256=args.expected_item_sha256,
            width=args.width, height=args.height, hfov=args.hfov, block_rows=args.block_rows, edge_samples=args.edge_samples)
    except (ValueError, OSError, KeyError) as error:
        parser.exit(2, f"FEHLER: {error}\n")
    print(json.dumps({"output": str(args.output), "box_status": proposal["box_geometry_status"],
                      "human_approved": False, "all_visible_object_annotation_complete": False}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
