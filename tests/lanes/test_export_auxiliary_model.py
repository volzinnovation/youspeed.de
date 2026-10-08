"""Small graph tests; real checkpoint/export checks live in the external report."""
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np
import torch
from torch import nn

sys.path.insert(0, str(Path(__file__).parents[2]))
from scripts.lanes import export_auxiliary_model as export
from scripts.lanes import export_auxiliary_litert as lite
from scripts.lanes import train_a2d2_auxiliary as training


class Concat(nn.Module):
    def forward(self, xs):
        return torch.cat(xs, dim=1)


class Decode(nn.Module):
    def forward(self, x):
        return x.flatten(2), {"unexported": x}


class BranchedDetector(nn.Module):
    def __init__(self):
        super().__init__()
        self.model = nn.ModuleList([
            nn.Conv2d(3, 2, 3, stride=2, padding=1),
            nn.Conv2d(2, 4, 3, stride=2, padding=1),
            nn.Sequential(nn.Conv2d(4, 2, 1), nn.Upsample(scale_factor=2, mode="nearest")),
            Concat(), Decode()])
        for index, module in enumerate(self.model):
            module.i, module.f = index, ([0, -1] if index == 3 else -1)
        self.save = [0]

    def forward(self, x):
        first = self.model[0](x)
        second = self.model[1](first)
        decoded = self.model[4](self.model[3]([first, self.model[2](second)]))
        return decoded, (first, second)


class ExportTest(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(71)

    def test_explicit_shared_graph_preserves_branch_and_multiple_inputs(self):
        detector = BranchedDetector().eval()
        head = training.AuxiliaryMarkingHead((2, 4), hidden=2).eval()
        wrapper = export.SharedDetectorAndLane(detector, head, (0, 1))
        with torch.inference_mode():
            for x in (torch.randn(1, 3, 16, 16), torch.zeros(1, 3, 16, 16), torch.ones(1, 3, 16, 16)):
                (decoded, _), features = detector(x)
                actual, logits = wrapper(x)
                self.assertTrue(torch.equal(decoded, actual))
                self.assertTrue(torch.equal(head(features), logits))

    def test_source_is_copied_and_not_mutated(self):
        detector = BranchedDetector().eval()
        head = training.AuxiliaryMarkingHead((2, 4), hidden=2).eval()
        before = training.state_hash(detector)
        wrapper = export.SharedDetectorAndLane(detector, head, (0, 1))
        with torch.no_grad():
            wrapper.detector.model[0].weight.zero_()
        self.assertEqual(before, training.state_hash(detector))
        self.assertFalse(any(p.requires_grad for p in wrapper.parameters()))

    def test_hook_capture_rejected_before_tracing(self):
        detector = BranchedDetector()
        handle = detector.model[0].register_forward_hook(lambda *_: None)
        with self.assertRaisesRegex(ValueError, "hooks"):
            export.SharedDetectorAndLane(detector, feature_layers=(0, 1))
        handle.remove()

    def test_invalid_feature_taps_rejected(self):
        for taps in ((0, 0), (0, 4), (-1, 1), (0,)):
            with self.assertRaises(ValueError):
                export.SharedDetectorAndLane(BranchedDetector(), feature_layers=taps)

    def test_trace_does_not_freeze_features(self):
        model = export.SharedDetectorAndLane(BranchedDetector(), training.AuxiliaryMarkingHead((2, 4), 2), (0, 1))
        x, y = torch.randn(1, 3, 16, 16), torch.randn(1, 3, 16, 16)
        with torch.inference_mode():
            trace = torch.jit.trace(model, x, check_inputs=[(y,)])
            for index in range(2):
                torch.testing.assert_close(trace(y)[index], model(y)[index])
                self.assertFalse(torch.equal(trace(x)[index], trace(y)[index]))

    def test_comparison_rejects_shapes_and_nonfinite(self):
        with self.assertRaisesRegex(ValueError, "shape"):
            export.compare_arrays(np.zeros((2, 3)), np.zeros((3, 2)))
        for invalid in (np.nan, np.inf, -np.inf):
            with self.assertRaisesRegex(ValueError, "Nonfinite"):
                export.compare_arrays([invalid], [0])
            with self.assertRaisesRegex(ValueError, "Nonfinite"):
                export.compare_arrays([0], [invalid])
        result = export.compare_arrays([0, 1], [0, 1.01], atol=.001, rtol=0)
        self.assertFalse(result["allclose"])
        self.assertAlmostEqual(result["maxAbsoluteDifference"], .01)

    def test_convolution_cost_counts_grouped_macs_and_removes_hooks(self):
        model = nn.Conv2d(4, 4, 3, groups=4, padding=1)
        cost = export.convolution_cost(model, torch.ones(1, 4, 8, 8))
        self.assertEqual(cost["conv2dMultiplyAccumulates"], 4 * 8 * 8 * 9)
        self.assertFalse(model._forward_hooks)

    def test_detector_diagnostics_distinguish_low_score_boxes_and_score_crossings(self):
        reference = np.zeros((1, 7, 2), np.float32)
        actual = reference.copy()
        reference[0, 4, 0] = .24
        actual[0, 4, 0] = .26
        actual[0, 0, 1] = 100
        result = export.compare_detections(reference, actual)
        self.assertEqual(result["signAnchorThresholdTransitions"], 1)
        self.assertEqual(result["coordinates"]["maxAbsoluteDifference"], 100)
        self.assertEqual(result["selectedSignCoordinates"]["maxAbsoluteDifference"], 0)
        with self.assertRaisesRegex(ValueError, "decoded tensor"):
            export.compare_detections(np.zeros((1, 6, 1)), np.zeros((1, 6, 1)))

    def test_artifacts_are_hashed_individually(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "weights.bin").write_bytes(b"unchanged fixed weights")
            (root / "manifest.json").write_text("{}")
            result = export.artifact(root)
            self.assertEqual(result["bytes"], 25)
            self.assertEqual(len(result["files"]), 2)
            self.assertTrue(all(len(row["sha256"]) == 64 for row in result["files"]))

    def test_litert_layout_mapping_rejects_unexpected_outputs(self):
        details = [dict(shape=(1, 160, 160, 1), dtype=np.float32, index=2),
                   dict(shape=(1, 7, 8400), dtype=np.float32, index=3)]
        self.assertEqual(lite.output_roles(details, True), {"lane_logits": 2, "detections": 3})
        self.assertEqual(lite.output_roles(details[1:], False), {"detections": 3})
        for invalid in (details[:1], details + details[:1],
                        [dict(shape=(1, 1, 160, 160), dtype=np.float32, index=2), details[1]],
                        [dict(shape=(1, 160, 160, 1), dtype=np.float16, index=2), details[1]]):
            with self.assertRaises(ValueError):
                lite.output_roles(invalid, True)

    def test_litert_trace_binding_rejects_changed_bytes(self):
        import json
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "shared.torchscript.pt"
            source.write_bytes(b"fake trace")
            (root / "artifact-sha256.json").write_text(json.dumps(export.artifact(root)))
            self.assertEqual(lite.bind_trace(root, "shared"), source)
            source.write_bytes(b"different trace")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                lite.bind_trace(root, "shared")

    def test_1280_resolution_control_requires_its_own_output_layout(self):
        details = [dict(shape=(1, 320, 320, 1), dtype=np.float32, index=2),
                   dict(shape=(1, 7, 33600), dtype=np.float32, index=3)]
        self.assertEqual(lite.output_roles(details, True, 1280), {"lane_logits": 2, "detections": 3})
        with self.assertRaises(ValueError):
            lite.output_roles(details, True, 640)
        with self.assertRaises(ValueError):
            lite.output_roles(details, True, 960)

    def test_tensorflow_transfer_preserves_half_pixel_resize_and_depthwise_order(self):
        try:
            import tensorflow as tf
        except ImportError:
            self.skipTest("Optional TensorFlow export dependency not installed")
        head = training.AuxiliaryMarkingHead((2, 4), hidden=2).eval()
        features = (torch.randn(1, 2, 7, 9), torch.randn(1, 4, 3, 5))
        module = export.make_tensorflow_head(head, [x.shape for x in features])
        with torch.inference_mode():
            expected = head(features).numpy()
        actual = module(*[x.numpy().transpose(0, 2, 3, 1) for x in features])["lane_logits"].numpy().transpose(0, 3, 1, 2)
        np.testing.assert_allclose(actual, expected, atol=1e-6, rtol=1e-5)


if __name__ == "__main__":
    unittest.main()
