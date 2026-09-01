import copy

import numpy as np
import pytest
from PIL import Image

from scripts.tsr.preprocessing_v2 import (
    PreprocessingV2Error,
    preprocess_classifier,
    preprocess_detector,
)


def _detector_spec():
    return {
        "version": "detector-preprocess-v2",
        "source": "full_frame",
        "input_width": 4,
        "input_height": 4,
        "color_space": "rgb",
        "layout": "nchw",
        "input_dtype": "float32",
        "resize": "scale_fit_letterbox",
        "interpolation": "nearest",
        "interpolation_coordinate_transform": "half_pixel_centers",
        "letterbox_alignment": "centered",
        "geometry_rounding": "floor_top_left_remainder_bottom_right",
        "orientation": "normalize_exif_and_mirroring",
        "scale": 1 / 255,
        "mean": [0, 0, 0],
        "std": [1, 1, 1],
        "normalization_formula": "((channel*scale)-mean)/std",
        "letterbox_value": 114,
        "crop_policy": None,
    }


def _classifier_spec():
    return {
        "version": "classifier-preprocess-v2",
        "source": "proposal_crop",
        "input_width": 4,
        "input_height": 4,
        "color_space": "rgb",
        "layout": "nhwc",
        "input_dtype": "float32",
        "resize": "scale_fill_center_crop",
        "interpolation": "nearest",
        "interpolation_coordinate_transform": "half_pixel_centers",
        "letterbox_alignment": "not_applicable",
        "geometry_rounding": "round_half_up",
        "orientation": "normalize_exif_and_mirroring",
        "scale": 1 / 255,
        "mean": [0, 0, 0],
        "std": [1, 1, 1],
        "normalization_formula": "((channel*scale)-mean)/std",
        "letterbox_value": 114,
        "crop_policy": {
            "context_expansion_ratio": 0,
            "include_linked_objects": False,
            "role_hint_required": True,
            "minimum_crop_pixels": 1,
            "out_of_frame_fill": "letterbox",
        },
    }


def test_detector_preserves_complete_portrait_frame_with_centered_letterbox() -> None:
    source = np.zeros((4, 2, 3), dtype=np.uint8)
    source[:, :, 0] = 255
    output = preprocess_detector(Image.fromarray(source, mode="RGB"), _detector_spec())

    pixels = np.asarray(output.pixels)
    assert output.tensor.shape == (1, 3, 4, 4)
    assert output.metadata["resized_size"] == [2, 4]
    assert output.metadata["padding"] == {"left": 1, "top": 0, "right": 1, "bottom": 0}
    assert np.all(pixels[:, 0] == 114)
    assert np.all(pixels[:, 1:3, 0] == 255)
    assert np.all(pixels[:, 3] == 114)


def test_classifier_uses_only_the_role_hinted_proposal_crop() -> None:
    source = np.zeros((8, 8, 3), dtype=np.uint8)
    source[1:3, 1:3] = [255, 0, 0]
    source[5:7, 5:7] = [0, 255, 0]
    image = Image.fromarray(source, mode="RGB")

    primary = preprocess_classifier(
        image,
        {"x": 1, "y": 1, "width": 2, "height": 2},
        _classifier_spec(),
        role_hint="primary_sign",
    )
    plate = preprocess_classifier(
        image,
        {"x": 5, "y": 5, "width": 2, "height": 2},
        _classifier_spec(),
        role_hint="supplementary_plate",
    )

    assert np.all(np.asarray(primary.pixels) == [255, 0, 0])
    assert np.all(np.asarray(plate.pixels) == [0, 255, 0])
    assert primary.tensor_sha256 != plate.tensor_sha256
    assert primary.metadata["role_hint"] == "primary_sign"
    assert plate.metadata["role_hint"] == "supplementary_plate"


def test_detector_and_classifier_preprocessing_identities_are_independent() -> None:
    image = Image.new("RGB", (8, 8), (10, 20, 30))
    detector = preprocess_detector(image, _detector_spec())
    classifier = preprocess_classifier(
        image,
        {"x": 0, "y": 0, "width": 8, "height": 8},
        _classifier_spec(),
        role_hint="primary_sign",
    )

    assert detector.metadata["preprocessing_version"] != classifier.metadata["preprocessing_version"]
    assert detector.tensor.shape == (1, 3, 4, 4)
    assert classifier.tensor.shape == (1, 4, 4, 3)


def test_linked_objects_or_missing_role_hint_fail_closed() -> None:
    spec = copy.deepcopy(_classifier_spec())
    spec["crop_policy"]["include_linked_objects"] = True
    image = Image.new("RGB", (8, 8))
    with pytest.raises(PreprocessingV2Error, match="remain independent"):
        preprocess_classifier(
            image,
            {"x": 1, "y": 1, "width": 2, "height": 2},
            spec,
            role_hint="primary_sign",
        )
    with pytest.raises(PreprocessingV2Error, match="role hint"):
        preprocess_classifier(
            image,
            {"x": 1, "y": 1, "width": 2, "height": 2},
            _classifier_spec(),
            role_hint="",
        )
