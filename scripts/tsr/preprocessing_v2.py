"""Reference pixel preprocessing for the two independent TSR v2 stages.

This module is deliberately small and deterministic.  It is not a model
runtime; it produces the exact detector or classifier tensor whose digest can
be compared across ONNX, Core ML, and LiteRT harnesses.  Detector preprocessing
always consumes the complete orientation-normalized frame.  Classifier
preprocessing consumes exactly one role-hinted proposal crop and never folds a
linked primary/plate object into that crop.
"""

from __future__ import annotations

import hashlib
import math
from dataclasses import dataclass
from typing import Any, Mapping

import numpy as np
from PIL import Image, ImageOps


class PreprocessingV2Error(ValueError):
    """Raised when a preprocessing contract or input is unsafe."""


@dataclass(frozen=True)
class PreprocessedInput:
    pixels: Image.Image
    tensor: np.ndarray
    tensor_sha256: str
    metadata: Mapping[str, Any]


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise PreprocessingV2Error(message)


def _round_half_up(value: float) -> int:
    return int(math.floor(value + 0.5))


def _dimension(value: float, rule: str) -> int:
    if rule == "floor_top_left_remainder_bottom_right":
        return max(1, int(math.floor(value)))
    if rule == "round_half_up":
        return max(1, _round_half_up(value))
    raise PreprocessingV2Error(f"unsupported geometry rounding: {rule}")


def _resample(name: str) -> Image.Resampling:
    values = {
        "bilinear": Image.Resampling.BILINEAR,
        "bicubic": Image.Resampling.BICUBIC,
        "nearest": Image.Resampling.NEAREST,
    }
    try:
        return values[name]
    except KeyError as error:
        raise PreprocessingV2Error(f"unsupported interpolation: {name}") from error


def validate_preprocessing_spec(
    value: Mapping[str, Any],
    *,
    expected_source: str | None = None,
) -> dict[str, Any]:
    required = {
        "version",
        "source",
        "input_width",
        "input_height",
        "color_space",
        "layout",
        "input_dtype",
        "resize",
        "interpolation",
        "interpolation_coordinate_transform",
        "letterbox_alignment",
        "geometry_rounding",
        "orientation",
        "scale",
        "mean",
        "std",
        "normalization_formula",
        "letterbox_value",
        "crop_policy",
    }
    _require(isinstance(value, Mapping), "preprocessing must be an object")
    _require(set(value) == required, "preprocessing has missing or unexpected fields")
    spec = dict(value)
    _require(isinstance(spec["version"], str) and spec["version"], "version is required")
    _require(spec["source"] in {"full_frame", "proposal_crop"}, "source is invalid")
    if expected_source is not None:
        _require(spec["source"] == expected_source, "preprocessing source is wrong for its stage")
    for field in ("input_width", "input_height"):
        _require(type(spec[field]) is int and spec[field] > 0, f"{field} is invalid")
    _require(spec["color_space"] in {"rgb", "bgr"}, "color_space is invalid")
    _require(spec["layout"] in {"nchw", "nhwc"}, "layout is invalid")
    _require(spec["input_dtype"] in {"float32", "float16"}, "reference preprocessing supports floating tensors only")
    _require(
        spec["resize"] in {"scale_fit_letterbox", "scale_fill_center_crop"},
        "resize is invalid",
    )
    _resample(spec["interpolation"])
    _require(
        spec["interpolation_coordinate_transform"] == "half_pixel_centers",
        "reference Pillow preprocessing supports half-pixel centers only",
    )
    _require(
        spec["letterbox_alignment"] in {"centered", "top_left", "not_applicable"},
        "letterbox_alignment is invalid",
    )
    _require(
        spec["geometry_rounding"]
        in {"floor_top_left_remainder_bottom_right", "round_half_up"},
        "geometry_rounding is invalid",
    )
    _require(
        spec["orientation"] == "normalize_exif_and_mirroring",
        "orientation policy is invalid",
    )
    _require(isinstance(spec["scale"], (int, float)) and spec["scale"] > 0, "scale is invalid")
    for field in ("mean", "std"):
        _require(
            isinstance(spec[field], list)
            and len(spec[field]) == 3
            and all(isinstance(item, (int, float)) and math.isfinite(item) for item in spec[field]),
            f"{field} must contain three finite values",
        )
    _require(all(item > 0 for item in spec["std"]), "std values must be positive")
    _require(
        spec["normalization_formula"] == "((channel*scale)-mean)/std",
        "normalization formula is unsupported",
    )
    _require(
        isinstance(spec["letterbox_value"], (int, float))
        and 0 <= spec["letterbox_value"] <= 255,
        "letterbox_value is invalid",
    )

    crop_policy = spec["crop_policy"]
    if spec["source"] == "full_frame":
        _require(crop_policy is None, "full-frame preprocessing cannot have a crop policy")
        _require(spec["resize"] == "scale_fit_letterbox", "detector must preserve the complete frame")
        _require(spec["letterbox_alignment"] in {"centered", "top_left"}, "detector letterbox alignment is required")
    else:
        _require(isinstance(crop_policy, Mapping), "proposal preprocessing needs a crop policy")
        crop_required = {
            "context_expansion_ratio",
            "include_linked_objects",
            "role_hint_required",
            "minimum_crop_pixels",
            "out_of_frame_fill",
        }
        _require(set(crop_policy) == crop_required, "crop policy has missing or unexpected fields")
        _require(
            isinstance(crop_policy["context_expansion_ratio"], (int, float))
            and crop_policy["context_expansion_ratio"] >= 0,
            "crop context expansion is invalid",
        )
        _require(crop_policy["include_linked_objects"] is False, "proposal crops must remain independent")
        _require(crop_policy["role_hint_required"] is True, "classifier role hint must be required")
        _require(
            type(crop_policy["minimum_crop_pixels"]) is int
            and crop_policy["minimum_crop_pixels"] > 0,
            "minimum crop size is invalid",
        )
        _require(crop_policy["out_of_frame_fill"] in {"letterbox", "edge"}, "crop fill is invalid")
        _require(spec["resize"] == "scale_fill_center_crop", "classifier resize policy is invalid")
        _require(spec["letterbox_alignment"] == "not_applicable", "classifier cannot declare letterbox alignment")
    return spec


def _fit_letterbox(image: Image.Image, spec: Mapping[str, Any]) -> tuple[Image.Image, dict[str, Any]]:
    target_width = spec["input_width"]
    target_height = spec["input_height"]
    scale = min(target_width / image.width, target_height / image.height)
    resized_width = min(target_width, _dimension(image.width * scale, spec["geometry_rounding"]))
    resized_height = min(target_height, _dimension(image.height * scale, spec["geometry_rounding"]))
    resized = image.resize((resized_width, resized_height), _resample(spec["interpolation"]))
    remaining_x = target_width - resized_width
    remaining_y = target_height - resized_height
    if spec["letterbox_alignment"] == "centered":
        left = remaining_x // 2
        top = remaining_y // 2
    else:
        left = 0
        top = 0
    fill = _round_half_up(float(spec["letterbox_value"]))
    canvas = Image.new("RGB", (target_width, target_height), (fill, fill, fill))
    canvas.paste(resized, (left, top))
    return canvas, {
        "source_size": [image.width, image.height],
        "resized_size": [resized_width, resized_height],
        "scale": scale,
        "padding": {
            "left": left,
            "top": top,
            "right": remaining_x - left,
            "bottom": remaining_y - top,
        },
    }


def _expanded_crop_bounds(
    image: Image.Image,
    box: Mapping[str, Any],
    crop_policy: Mapping[str, Any],
) -> tuple[int, int, int, int]:
    _require(
        isinstance(box, Mapping) and set(box) == {"x", "y", "width", "height"},
        "proposal box must use pixel x/y/width/height",
    )
    values = [box[field] for field in ("x", "y", "width", "height")]
    _require(all(isinstance(item, (int, float)) and math.isfinite(item) for item in values), "proposal box is invalid")
    x, y, width, height = (float(item) for item in values)
    _require(x >= 0 and y >= 0 and width > 0 and height > 0, "proposal box dimensions are invalid")
    _require(x + width <= image.width and y + height <= image.height, "proposal box exceeds the frame")
    expansion = float(crop_policy["context_expansion_ratio"])
    crop_width = max(width * (1 + expansion), float(crop_policy["minimum_crop_pixels"]))
    crop_height = max(height * (1 + expansion), float(crop_policy["minimum_crop_pixels"]))
    center_x = x + width / 2
    center_y = y + height / 2
    left = math.floor(center_x - crop_width / 2)
    top = math.floor(center_y - crop_height / 2)
    right = math.ceil(center_x + crop_width / 2)
    bottom = math.ceil(center_y + crop_height / 2)
    _require(right > left and bottom > top, "expanded proposal crop is empty")
    return left, top, right, bottom


def _crop_with_fill(
    image: Image.Image,
    bounds: tuple[int, int, int, int],
    *,
    fill_policy: str,
    fill_value: int,
) -> Image.Image:
    left, top, right, bottom = bounds
    if fill_policy == "letterbox":
        canvas = Image.new("RGB", (right - left, bottom - top), (fill_value,) * 3)
        source_box = (
            max(0, left),
            max(0, top),
            min(image.width, right),
            min(image.height, bottom),
        )
        if source_box[2] > source_box[0] and source_box[3] > source_box[1]:
            canvas.paste(
                image.crop(source_box),
                (source_box[0] - left, source_box[1] - top),
            )
        return canvas

    array = np.asarray(image, dtype=np.uint8)
    pad_left = max(0, -left)
    pad_top = max(0, -top)
    pad_right = max(0, right - image.width)
    pad_bottom = max(0, bottom - image.height)
    padded = np.pad(
        array,
        ((pad_top, pad_bottom), (pad_left, pad_right), (0, 0)),
        mode="edge",
    )
    shifted_left = left + pad_left
    shifted_top = top + pad_top
    return Image.fromarray(
        padded[
            shifted_top : shifted_top + (bottom - top),
            shifted_left : shifted_left + (right - left),
        ],
        mode="RGB",
    )


def _fill_center_crop(image: Image.Image, spec: Mapping[str, Any]) -> tuple[Image.Image, dict[str, Any]]:
    target_width = spec["input_width"]
    target_height = spec["input_height"]
    scale = max(target_width / image.width, target_height / image.height)
    resized_width = max(target_width, _dimension(image.width * scale, spec["geometry_rounding"]))
    resized_height = max(target_height, _dimension(image.height * scale, spec["geometry_rounding"]))
    resized = image.resize((resized_width, resized_height), _resample(spec["interpolation"]))
    left = (resized_width - target_width) // 2
    top = (resized_height - target_height) // 2
    return resized.crop((left, top, left + target_width, top + target_height)), {
        "source_size": [image.width, image.height],
        "resized_size": [resized_width, resized_height],
        "scale": scale,
        "center_crop_origin": [left, top],
    }


def _tensor(pixels: Image.Image, spec: Mapping[str, Any]) -> tuple[np.ndarray, str]:
    values = np.asarray(pixels, dtype=np.float32)
    if spec["color_space"] == "bgr":
        values = values[..., ::-1]
    values = values * np.float32(spec["scale"])
    mean = np.asarray(spec["mean"], dtype=np.float32)
    std = np.asarray(spec["std"], dtype=np.float32)
    values = (values - mean) / std
    if spec["layout"] == "nchw":
        values = np.transpose(values, (2, 0, 1))[None, ...]
    else:
        values = values[None, ...]
    dtype = np.float16 if spec["input_dtype"] == "float16" else np.float32
    contiguous = np.ascontiguousarray(values, dtype=dtype)
    return contiguous, hashlib.sha256(contiguous.tobytes(order="C")).hexdigest()


def preprocess_detector(image: Image.Image, raw_spec: Mapping[str, Any]) -> PreprocessedInput:
    spec = validate_preprocessing_spec(raw_spec, expected_source="full_frame")
    oriented = ImageOps.exif_transpose(image).convert("RGB")
    pixels, metadata = _fit_letterbox(oriented, spec)
    tensor, digest = _tensor(pixels, spec)
    return PreprocessedInput(
        pixels=pixels,
        tensor=tensor,
        tensor_sha256=digest,
        metadata={"preprocessing_version": spec["version"], **metadata},
    )


def preprocess_classifier(
    image: Image.Image,
    box: Mapping[str, Any],
    raw_spec: Mapping[str, Any],
    *,
    role_hint: str,
) -> PreprocessedInput:
    spec = validate_preprocessing_spec(raw_spec, expected_source="proposal_crop")
    _require(role_hint in {"primary_sign", "supplementary_plate"}, "classifier role hint is invalid")
    oriented = ImageOps.exif_transpose(image).convert("RGB")
    crop_policy = spec["crop_policy"]
    bounds = _expanded_crop_bounds(oriented, box, crop_policy)
    crop = _crop_with_fill(
        oriented,
        bounds,
        fill_policy=crop_policy["out_of_frame_fill"],
        fill_value=_round_half_up(float(spec["letterbox_value"])),
    )
    pixels, resize_metadata = _fill_center_crop(crop, spec)
    tensor, digest = _tensor(pixels, spec)
    return PreprocessedInput(
        pixels=pixels,
        tensor=tensor,
        tensor_sha256=digest,
        metadata={
            "preprocessing_version": spec["version"],
            "role_hint": role_hint,
            "source_box": dict(box),
            "expanded_crop_bounds": list(bounds),
            **resize_metadata,
        },
    )
