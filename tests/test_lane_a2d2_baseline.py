"""Protect label identity, aspect ratio and unknown-support behavior in research replay."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

spec = importlib.util.spec_from_file_location("a2d2", Path(__file__).resolve().parents[1] / "scripts/lanes/a2d2_baseline.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class A2D2BaselineTests(unittest.TestCase):
    def test_replay_split_uses_only_hash_bound_normalized_input(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "input.normalized.json"
            rows = [dict(id="one", sequenceId="one", time=0, inputSha256="correct")]
            normalized = [dict(id="one", sequenceId="one", time=0, graySha256="correct", split="test")]
            path.write_text(json.dumps(dict(frames=normalized)))
            self.assertEqual(m.replay_splits(rows, path), {"one": "test"})
            normalized[0]["graySha256"] = "different"
            path.write_text(json.dumps(dict(frames=normalized)))
            with self.assertRaisesRegex(ValueError, "identity/hash/split"):
                m.replay_splits(rows, path)

    def test_preserves_test_split_through_image_preparation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image = root / "image.png"
            m.cv2.imwrite(str(image), np.zeros((80, 100, 3), np.uint8))
            manifest = root / "source.json"
            manifest.write_text(json.dumps({"pairs": [{"sequence": "date-group", "rgb": "rgb", "label": "label", "split": "test"}],
                "objects": [{"key": key, "local_path": str(image), "sha256": m.sha(image)} for key in ("rgb", "label")]}))
            m.prepare(manifest, root / "out")
            for filename, key in (("manifest.json", "frames"), ("targets.json", "targets")):
                self.assertEqual(json.loads((root / "out" / filename).read_text())[key][0]["split"], "test")

    def test_only_solid_and_dashed_are_lane_paint(self):
        rgb = np.array([[[255, 193, 37], [128, 0, 255], [200, 125, 210], [210, 50, 115], [0, 0, 0]]], dtype=np.uint8)
        self.assertEqual(m.paint_mask(rgb[:, :, ::-1]).tolist(), [[1, 1, 0, 0, 0]])

    def test_preserves_unusual_camera_aspect(self):
        xs, ys = m.sample_indices(1920, 1208)
        self.assertEqual((len(xs), len(ys)), (343, 216))
        self.assertLess(abs(len(xs) / len(ys) - 1920 / 1208), .015)

    def test_missing_observed_segments_never_fills_geometry(self):
        b = [{"cue": "paint", "points": [[.4, .6], [.3, .9]], "observedSegments": []}]
        self.assertEqual(int(m.rasterize(b, 100, 100, "observed").sum()), 0)
        self.assertGreater(int(m.rasterize(b, 100, 100, "geometry").sum()), 0)

    def test_empty_prediction_is_undefined_precision_zero_coverage(self):
        truth = np.zeros((100, 100), np.uint8); truth[70:90, 40] = 1
        result = m.with_rates(m.counts(np.zeros_like(truth), truth))
        self.assertIsNone(result["centerlineSupportPrecision"])
        self.assertEqual(result["annotatedPaintCoverage"], 0)

    def test_outside_region_does_not_count_and_tolerance_is_explicit(self):
        truth = np.zeros((100, 100), np.uint8); truth[70:90, 40] = 1
        pred = np.zeros_like(truth); pred[70:90, 42] = 1; pred[:20, 42] = 1
        self.assertEqual(m.counts(pred, truth, 0)["supportedCenterlinePixels"], 0)
        self.assertEqual(m.counts(pred, truth, 2)["supportedCenterlinePixels"], 20)
        self.assertEqual(m.counts(pred, truth, 2)["predictedCenterlinePixels"], 20)

    def test_rejects_invented_temporal_context_for_stills(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target, replay = root / "targets.json", root / "frames.ndjson"
            target.write_text(json.dumps({"targets": [{"id": "still"}]}))
            for row in ({"id": "still", "sequenceId": "other-still", "time": 0},
                        {"id": "still", "sequenceId": "still", "time": 1}):
                replay.write_text(json.dumps(row) + "\n")
                with self.assertRaisesRegex(ValueError, "independent still"):
                    m.score(target, replay, root / "score.json")


if __name__ == "__main__":
    unittest.main()
