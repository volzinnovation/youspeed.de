import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/tsr"))
import generate_mobidata_contours as generator


def test_every_shared_german_sign_has_a_pinned_presentation_contour():
    root = ROOT / "shared/tsr/sign-pictograms"
    metadata = json.loads((root / "contours/manifest.json").read_text())
    assert metadata["display_scale"] == 1.125
    assert {entry["source_path"] for entry in metadata["artworks"]} == {
        entry["png_path"] for entry in json.loads((root / "manifest.json").read_text())["artworks"]}
    for entry in metadata["artworks"]:
        source = root / entry["source_path"]
        contour = root / entry["contour_path"]
        assert hashlib.sha256(source.read_bytes()).hexdigest() == entry["source_sha256"]
        assert hashlib.sha256(contour.read_bytes()).hexdigest() == entry["contour_sha256"]
        pixels = np.asarray(Image.open(contour).convert("RGBA"))
        assert pixels.shape == (288, 288, 4)
        assert np.any(np.all(pixels == (255, 255, 255, 255), axis=2))
        assert np.any(np.all(pixels == (0, 0, 0, 255), axis=2))
        assert all(pixels[y, x, 3] == 0 for y, x in [(0, 0), (0, 287), (287, 0), (287, 287)])
        art = Image.open(source).convert("RGBA")
        alpha = np.asarray(art)[:, :, 3]
        y, x = (288 - art.height) // 2, (288 - art.width) // 2
        # The extra cue cannot overwrite or recolor a single opaque artwork pixel.
        assert np.all(pixels[y:y+art.height, x:x+art.width, 3][alpha >= 128] == 0)


def test_contours_reproduce_from_the_pinned_artwork_without_changes():
    assert generator.generate(check=True) == 117
