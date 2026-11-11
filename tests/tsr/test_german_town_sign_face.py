"""Exercise the same native face check used by the Android and iPhone runtimes."""
import ctypes
from pathlib import Path
import shutil
import subprocess

from PIL import Image, ImageDraw, ImageEnhance
import pytest


ROOT = Path(__file__).resolve().parents[2]
TSR = ROOT / "shared/tsr"


@pytest.fixture(scope="module")
def town_face(tmp_path_factory):
    compiler = shutil.which("c++")
    if compiler is None:
        pytest.skip("C++ compiler needed for the shared mobile face check")
    library = tmp_path_factory.mktemp("town-face") / "town-face.so"
    subprocess.run(
        [compiler, "-std=c++17", "-shared", "-fPIC", "-Wall", "-Wextra", "-Werror",
         str(TSR / "german_town_sign_face.cpp"), "-o", str(library)],
        check=True,
    )
    check = ctypes.CDLL(str(library)).ysp_german_town_sign_face
    check.argtypes = (ctypes.c_char_p, ctypes.c_double, ctypes.c_double, ctypes.c_int32)
    check.restype = ctypes.c_int32

    def accepts(image, *, exit_sign=False):
        rgb = image.convert("RGBA").resize((80, 64), Image.Resampling.BILINEAR)
        return bool(check(rgb.tobytes(), *image.size, exit_sign))

    return accepts


def official(code):
    with Image.open(TSR / f"sign-pictograms/png/de-{code}.png") as image:
        return image.convert("RGB")


def test_entry_exit_and_low_exposure(town_face):
    entry, exit_sign = official(310), official(311)
    for exposure in (1.0, 0.61):
        dim_entry = ImageEnhance.Brightness(entry).enhance(exposure)
        dim_exit = ImageEnhance.Brightness(exit_sign).enhance(exposure)
        assert town_face(dim_entry)
        assert town_face(dim_exit, exit_sign=True)
        assert not town_face(dim_entry, exit_sign=True)
        assert not town_face(dim_exit)


def test_white_area_geometry_and_insufficient_detail(town_face):
    entry = official(310)
    white_insert = entry.copy()
    ImageDraw.Draw(white_insert).rectangle((35, 108, 150, 137), fill="white")
    assert not town_face(white_insert)
    assert not town_face(entry.resize((256, 85)))
    assert not town_face(entry.resize((21, 14)))


def test_small_pale_inset_survives_a_partial_direction_crop(town_face):
    panel = official(310).resize((80, 64))
    draw = ImageDraw.Draw(panel)
    # An inset occupies less than the area threshold for white pixels and
    # its warm cast puts it outside the strict white range.
    draw.rectangle((39, 34, 43, 37), fill=(250, 232, 209))
    assert not town_face(panel)


def test_pointed_direction_panel_is_not_rectangular(town_face):
    board = Image.new("RGB", (256, 172), "#324952")
    draw = ImageDraw.Draw(board)
    draw.polygon([(2, 2), (169, 2), (255, 86), (169, 169), (2, 169)],
                 fill="#e2b800", outline="black", width=4)
    draw.text((50, 66), "Town", fill="black", font_size=36)
    assert not town_face(board)


@pytest.mark.parametrize("arrow", [
    [(106, 55), (143, 55), (143, 45), (172, 65), (143, 85), (143, 75), (106, 75)],
    [(179, 109), (179, 62), (161, 62), (193, 33), (225, 62), (207, 62), (207, 109)],
])
def test_yellow_direction_board_is_not_a_town_sign(town_face, arrow):
    board = Image.new("RGB", (256, 172), "#e2b800")
    draw = ImageDraw.Draw(board)
    draw.rounded_rectangle((4, 4, 251, 167), radius=6, outline="black", width=4)
    draw.text((20, 52), "Town", fill="black", font_size=24)
    draw.polygon(arrow, fill="black")
    assert not town_face(board)
    assert not town_face(board, exit_sign=True)
