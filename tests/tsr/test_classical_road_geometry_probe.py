"""Guard source geometry and timing provenance in the offline extractor probe."""
import argparse
import json

import pytest
from PIL import Image

from scripts.tsr.applicability.classical_road_geometry_probe import (
    actual_pts, load_frame_manifest, resize_dimensions, run, sample_pts,
)


@pytest.mark.parametrize("size,expected", [((4224, 2376), (384, 216)),
                                         ((2160, 3840), (216, 384)),
                                         ((100, 50), (100, 50))])
def test_preserves_aspect_without_upscaling(size, expected):
    assert resize_dimensions(*size, 384) == expected


def test_four_three_still_respects_height_budget_without_stretching():
    assert resize_dimensions(4000, 3000, 384, 216) == (288, 216)


def test_actual_pts_is_not_requested_time():
    frame = {"pts_value": 368382, "pts_timescale": 600,
             "pts_seconds": 613.97, "requested_seconds": 614.0}
    assert actual_pts(frame) == 613.97
    with pytest.raises(ValueError, match="missing"):
        actual_pts({"requested_seconds": 614.0, "frame_number": 18420, "fps": 30})
    with pytest.raises(ValueError, match="disagree"):
        actual_pts({**frame, "pts_seconds": 614.0})


def test_sampling_retains_original_pts_and_rejects_duplicate_time():
    frames = [{"pts_seconds": t} for t in [10.03, 10.13, 10.23, 10.33, 10.43]]
    assert [f["pts_seconds"] for f in sample_pts(frames, .2)] == [10.03, 10.23, 10.43]
    with pytest.raises(ValueError, match="strictly increase"):
        sample_pts([{"pts_seconds": 1}, {"pts_seconds": 1}], .2)


def test_frame_manifest_requires_actual_pts(tmp_path):
    path = tmp_path / "frames.json"
    path.write_text(json.dumps({"frames": [{"image_path": "a.jpg", "requested_seconds": 1}]}))
    with pytest.raises(ValueError, match="missing"):
        load_frame_manifest(path, tmp_path)


def test_exif_rotation_and_missing_or_panorama_inputs(tmp_path):
    pytest.importorskip("cv2")  # Optional experiment dependency, not required by core TSR CI.
    path = tmp_path / "portrait.jpg"
    exif = Image.Exif()
    exif[274] = 6
    Image.new("RGB", (80, 40), "gray").save(path, exif=exif)
    args = argparse.Namespace(max_edge=40, max_height=216, roi_top=.35, warmup=0, repeats=1,
                              max_segments=8, overlays=0, output=tmp_path / "report.json")
    frames = [{"frame_id": "rotated", "image_path": str(path), "projection": "rectilinear"},
              {"frame_id": "pano", "image_path": str(path), "projection": "equirectangular"},
              {"frame_id": "absent", "image_path": str(tmp_path / "missing.jpg"), "projection": "rectilinear"}]
    result = run(frames, args)["frames"]
    assert result[0]["upright_size"] == [40, 80]
    assert result[0]["analysis_size"] == [20, 40]
    assert result[1]["status"] == "skipped" and "rectilinear" in result[1]["reason"]
    assert result[2]["status"] == "skipped" and "missing" in result[2]["reason"]
