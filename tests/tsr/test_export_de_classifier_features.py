"""Verify deterministic handcrafted geometry and color features."""
import importlib.util
from pathlib import Path
import numpy as np
import pytest

SPEC = importlib.util.spec_from_file_location("de_features", Path(__file__).resolve().parents[2] / "scripts/tsr/export_de_classifier_features.py")
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_constant_image_feature_shape_color_and_aspect():
    cv2 = pytest.importorskip("cv2")
    from PIL import Image
    hog = cv2.HOGDescriptor((64,64),(16,16),(8,8),(8,8),9)
    rgb = Image.new("RGB", (80,40), (255,0,0))
    result = module.handcrafted(rgb, np, cv2, Image, hog)
    assert result.shape == (2005,)
    assert result.dtype == np.float32
    np.testing.assert_allclose(result[:1764], 0)
    for i in range(3):
        assert result[1764+i*16:1764+(i+1)*16].sum() == pytest.approx(1)
    np.testing.assert_array_equal(result[1812:-1].reshape(-1,3), np.tile([1,0,0],(64,1)))
    assert result[-1] == pytest.approx(np.log(2))
    assert rgb.size == (80,40)


def test_feature_does_not_use_absolute_native_size():
    cv2 = pytest.importorskip("cv2")
    from PIL import Image
    hog = cv2.HOGDescriptor((64,64),(16,16),(8,8),(8,8),9)
    a = module.handcrafted(Image.new("RGB",(80,40),(80,120,200)),np,cv2,Image,hog)
    b = module.handcrafted(Image.new("RGB",(160,80),(80,120,200)),np,cv2,Image,hog)
    np.testing.assert_array_equal(a,b)
