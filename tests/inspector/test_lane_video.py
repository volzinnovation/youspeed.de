"""Real FFmpeg VFR/B-frame and rotation checks, with synthetic video only."""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("lane_video", ROOT / "inspector/lane_video.py")
lane = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(lane)


@unittest.skipUnless(shutil.which("ffmpeg") and shutil.which("ffprobe"), "FFmpeg is required")
class LaneVideoTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.root = Path(cls.tmp.name)
        for i, rgb in enumerate(((255, 0, 0), (0, 255, 0), (0, 0, 255), (255, 255, 0))):
            (cls.root / f"{i}.ppm").write_bytes(b"P6\n64 48\n255\n" + bytes(rgb) * (64*48))
        (cls.root / "frames.txt").write_text("\n".join(
            f"file '{i}.ppm'\nduration {duration}" for i, duration in enumerate((.04, 3.12, .08, .04))) + "\nfile '3.ppm'\n")
        cls.path = cls.root / "vfr.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-f", "concat", "-safe", "0", "-i", str(cls.root / "frames.txt"),
                        "-fps_mode", "vfr", "-c:v", "libx264", "-bf", "2", "-pix_fmt", "yuv420p", str(cls.path)], check=True)
        cls.rotated = cls.root / "rotated.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-display_rotation", "90", "-i", str(cls.path), "-c", "copy", str(cls.rotated)], check=True)
        cls.offset = cls.root / "offset.mp4"
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(cls.path), "-c", "copy", "-output_ts_offset", "5", str(cls.offset)], check=True)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def setUp(self):
        self.decoder = lane.LaneVideos()

    def tearDown(self):
        self.decoder.close()

    def verify_video(self, path):
        data = path.read_bytes()
        result = self.decoder.upload(io.BytesIO(data), len(data), path.name)
        source, token = result["source"], result["session"]
        self.assertEqual(source["sha256"], hashlib.sha256(data).hexdigest())
        expected = self.root / path.stem
        expected.mkdir(exist_ok=True)
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-map", "0:v:0", "-fps_mode", "passthrough", str(expected / "%d.png")], check=True)
        for index in reversed(range(len(source["frames"]))):
            self.assertEqual(self.decoder.frame(token, index), (expected / f"{index+1}.png").read_bytes())
        self.assertEqual(self.decoder.frame(token, 0), (expected / "1.png").read_bytes())
        with self.assertRaises(lane.VideoError):
            self.decoder.frame(token, len(source["frames"]))
        self.decoder.delete(token)
        with self.assertRaises(lane.VideoError):
            self.decoder.frame(token, 0)
        return source

    def test_vfr_b_frames_exact_pngs_forward_backward(self):
        source = self.verify_video(self.path)
        deltas = [round(b["timeSeconds"]-a["timeSeconds"], 3) for a,b in zip(source["frames"],source["frames"][1:])]
        self.assertGreater(len(set(deltas)), 1)
        self.assertEqual((source["width"],source["height"]), (64,48))

    def test_rotated_video_coordinates_are_decoded_full_frame(self):
        source = self.verify_video(self.rotated)
        self.assertEqual((source["width"],source["height"]), (48,64))

    def test_nonzero_pts_origin(self):
        source = self.verify_video(self.offset)
        self.assertNotEqual(source["startPts"], '0')
        self.assertEqual(source["frames"][0]["timeSeconds"], 0)

    def test_bad_upload_does_not_keep_a_session(self):
        with self.assertRaises(lane.VideoError):
            self.decoder.upload(io.BytesIO(b"broken"), 6, "broken.mp4")
        self.assertEqual(self.decoder.sessions, {})
        with self.assertRaises(lane.VideoError):
            self.decoder.upload(io.BytesIO(b"x"), 2, "short.mp4")
        self.assertEqual(self.decoder.sessions, {})
