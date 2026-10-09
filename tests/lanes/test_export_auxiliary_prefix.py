from pathlib import Path
import sys
import unittest

import numpy as np
import torch
from torch import nn

sys.path.insert(0, str(Path(__file__).parents[2]))
from scripts.lanes import export_auxiliary_prefix as prefix


class ForbiddenTail(nn.Module):
    def __init__(self):
        super().__init__()
        self.unused_parameter = nn.Parameter(torch.ones(100))

    def forward(self, _):
        raise AssertionError("Lane-only prefix must not invoke the detector tail")


class Detector(nn.Module):
    def __init__(self):
        super().__init__()
        self.model = nn.ModuleList([nn.Conv2d(3, 2, 3, stride=2, padding=1),
                                    nn.Conv2d(2, 4, 3, stride=2, padding=1), ForbiddenTail()])
        for index, module in enumerate(self.model):
            module.i, module.f = index, -1
        self.save = []


class PrefixTest(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(73)

    def test_tail_is_excluded_and_logits_equal_original_features(self):
        detector = Detector().eval()
        head = prefix.training.AuxiliaryMarkingHead((2, 4), hidden=2).eval()
        model = prefix.FrozenLanePrefix(detector, head, (0, 1))
        self.assertEqual(len(model.layers), 2)
        self.assertFalse(any(isinstance(module, ForbiddenTail) for module in model.modules()))
        with torch.inference_mode():
            for image in (torch.zeros(1, 3, 16, 16), torch.randn(1, 3, 16, 16)):
                p2 = detector.model[0](image)
                p3 = detector.model[1](p2)
                self.assertTrue(torch.equal(model(image), head((p2, p3))))

    def test_trace_depends_on_new_frame_and_keeps_source_immutable(self):
        detector = Detector().eval()
        head = prefix.training.AuxiliaryMarkingHead((2, 4), hidden=2).eval()
        source_hash = prefix.training.state_hash(detector)
        head_hash = prefix.training.state_hash(head)
        model = prefix.FrozenLanePrefix(detector, head, (0, 1))
        a, b = torch.randn(1, 3, 16, 16), torch.randn(1, 3, 16, 16)
        with torch.inference_mode():
            traced = torch.jit.trace(model, a, check_inputs=[(b,)])
            torch.testing.assert_close(traced(b), model(b))
            self.assertFalse(torch.equal(traced(a), traced(b)))
            model.layers[0].weight.zero_()
        self.assertEqual(source_hash, prefix.training.state_hash(detector))
        self.assertEqual(head_hash, prefix.training.state_hash(head))
        self.assertFalse(any(parameter.requires_grad for parameter in model.parameters()))

    def test_rejects_hooks_and_invalid_taps(self):
        detector = Detector()
        head = prefix.training.AuxiliaryMarkingHead((2, 4), hidden=2)
        for layers in ((0, 0), (0, 2), (0,), (-1, 1)):
            with self.assertRaises(ValueError):
                prefix.FrozenLanePrefix(detector, head, layers)
        handle = detector.model[0].register_forward_hook(lambda *_: None)
        with self.assertRaisesRegex(ValueError, "hooks"):
            prefix.FrozenLanePrefix(detector, head, (0, 1))
        handle.remove()

    def test_litert_output_is_unambiguously_one_stride_four_lane_grid(self):
        for size in (640, 1280):
            good = dict(shape=(1, size // 4, size // 4, 1), dtype=np.float32, index=3)
            self.assertEqual(prefix.lane_output_index([good], size), 3)
            for invalid in ([], [good, good], [dict(good, dtype=np.float16)],
                            [dict(good, shape=(1, 1, size // 4, size // 4))]):
                with self.assertRaises(ValueError):
                    prefix.lane_output_index(invalid, size)


if __name__ == "__main__":
    unittest.main()
