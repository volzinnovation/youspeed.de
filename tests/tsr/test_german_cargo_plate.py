"""Exercise the native classifier shared by both mobile inference backends."""
import ctypes
from pathlib import Path
import shutil
import subprocess

from PIL import Image, ImageDraw, ImageEnhance
import pytest


ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/tsr-cargo-plates"


@pytest.fixture(scope="module")
def classify(tmp_path_factory):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("C++ compiler needed for the shared mobile classifier")
    library = tmp_path_factory.mktemp("cargo-plate") / "cargo-plate.so"
    subprocess.run([compiler, "-std=c++17", "-O2", "-shared", "-fPIC", "-Wall", "-Wextra", "-Werror",
                    str(ROOT / "shared/tsr/german_cargo_plate.cpp"), "-o", str(library)], check=True)
    match = ctypes.CDLL(str(library)).ysp_german_cargo_plate
    match.argtypes = ctypes.c_char_p, ctypes.c_double, ctypes.POINTER(ctypes.c_int32)
    match.restype = ctypes.c_int32

    def detect(scene, primary):
        x, y, width, height = primary
        left = x - .25 * width
        top = y + height - .25 * width
        side = 1.5 * width
        pixels = scene.transform((96, 96), Image.Transform.EXTENT, (left, top, left + side, top + side),
                                 Image.Resampling.BILINEAR).convert("RGBA")
        return match(pixels.tobytes(), width, (ctypes.c_int32 * 4)())

    return detect


@pytest.mark.parametrize("suffix", [30, 31])
@pytest.mark.parametrize("width", [24, 32, 56, 96])
@pytest.mark.parametrize("exposure", [1.0, 0.65])
def test_both_faces_at_ordinary_and_darker_exposures(classify, suffix, width, exposure):
    scene = Image.new("RGB", (3 * width, 3 * width), (65, 75, 70))
    with Image.open(FIXTURES / f"vzkat-{suffix}.png") as panel:
        scene.paste(panel.resize((width, round(width * .75)), Image.Resampling.LANCZOS), (width, 2 * width))
    assert classify(ImageEnhance.Brightness(scene).enhance(exposure), (width, width, width, width)) == suffix


@pytest.mark.parametrize("file,box,code", [
    ("dobel.png", (31, 28, 34, 35), 31),
    ("stack-30.png", (44, 25, 40, 40), 30),
    ("stack-wet.png", (44, 25, 40, 40), 0),
    ("stack-30.png", (44, 25, 20, 20), 0),
    ("stack-30.png", (2, 25, 40, 40), 0),
])
def test_assembly_and_unrelated_plates(classify, file, box, code):
    with Image.open(FIXTURES / file) as image:
        assert classify(image, box) == code


def test_orange_alone_is_insufficient(classify):
    scene = Image.new("RGB", (128, 128), "#414b46")
    draw = ImageDraw.Draw(scene)
    draw.rectangle((44, 65, 84, 95), outline="black", fill="white", width=2)
    draw.rectangle((57, 70, 70, 82), fill="#ed861b")
    assert classify(scene, (44, 25, 40, 40)) == 0
