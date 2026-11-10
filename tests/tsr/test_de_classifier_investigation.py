"""Check label boundaries in the fixed-budget classifier investigation.

The numerical tests use the experiment runtime's existing Torch installation;
dependency-free parameter-selection tests also run on a non-ML workstation.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/tsr/de_classifier_investigation.py"
SPEC = importlib.util.spec_from_file_location("de_classifier_investigation", SCRIPT)
investigation = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(investigation)

try:
    import torch
except ImportError:
    torch = None


@unittest.skipIf(torch is None, "Run numerical checks in the existing KI Torch environment")
class DistillationBoundaryTests(unittest.TestCase):
    def setUp(self):
        torch.manual_seed(42)

    def test_city_rows_have_no_distillation_gradient(self):
        student = torch.randn(3, 136, dtype=torch.float64, requires_grad=True)
        teacher = torch.randn(3, 134, dtype=torch.float64)
        labels = torch.tensor([59, 134, 135])
        loss = investigation.distillation_loss(torch, student, teacher, labels)
        loss.backward()
        self.assertGreater(student.grad[0, :134].abs().sum().item(), 0)
        self.assertEqual(student.grad[1:].abs().sum().item(), 0)
        self.assertEqual(student.grad[:, 134:].abs().sum().item(), 0)

    def test_appending_city_examples_does_not_dilute_shared_class_loss(self):
        student = torch.randn(1, 136, dtype=torch.float64)
        teacher = torch.randn(1, 134, dtype=torch.float64)
        original = investigation.distillation_loss(torch, student, teacher, torch.tensor([59]))
        augmented = investigation.distillation_loss(
            torch,
            torch.cat((student, torch.randn(2, 136, dtype=torch.float64))),
            torch.cat((teacher, torch.randn(2, 134, dtype=torch.float64))),
            torch.tensor([59, 134, 135]),
        )
        torch.testing.assert_close(original, augmented)

    def test_city_logits_do_not_change_old_class_distillation(self):
        student = torch.randn(4, 136, dtype=torch.float64)
        teacher = torch.randn(4, 134, dtype=torch.float64)
        labels = torch.tensor([0, 59, 72, 133])
        before = investigation.distillation_loss(torch, student, teacher, labels)
        changed = student.clone()
        changed[:, 134] = 1e5
        changed[:, 135] = -1e5
        after = investigation.distillation_loss(torch, changed, teacher, labels)
        torch.testing.assert_close(before, after)

    def test_identical_shared_logits_have_zero_loss_at_several_temperatures(self):
        teacher = torch.randn(3, 134, dtype=torch.float64)
        student = torch.cat((teacher, torch.randn(3, 2, dtype=torch.float64)), dim=1)
        for temperature in (0.5, 1.0, 2.0, 4.0):
            with self.subTest(temperature=temperature):
                loss = investigation.distillation_loss(
                    torch, student, teacher, torch.tensor([0, 58, 133]), temperature
                )
                self.assertAlmostEqual(loss.item(), 0.0, places=12)

    def test_city_only_batch_has_finite_differentiable_zero(self):
        student = torch.randn(2, 136, dtype=torch.float64, requires_grad=True)
        teacher = torch.randn(2, 134, dtype=torch.float64)
        loss = investigation.distillation_loss(torch, student, teacher, torch.tensor([134, 135]))
        self.assertTrue(torch.isfinite(loss).item())
        self.assertEqual(loss.item(), 0)
        loss.backward()
        self.assertEqual(student.grad.abs().sum().item(), 0)


class ParameterSelectionTests(unittest.TestCase):
    class Parameter:
        def __init__(self):
            self.requires_grad = True

        def requires_grad_(self, enabled):
            self.requires_grad = enabled

    class Model:
        def __init__(self, names):
            self.parameters = {name: ParameterSelectionTests.Parameter() for name in names}

        def named_parameters(self):
            return self.parameters.items()

    def test_yolo_warmup_preserves_backbone_and_updates_only_output_rows(self):
        model = self.Model(["model.0.conv.weight", "model.10.conv.bn.weight",
                            "model.10.linear.weight", "model.10.linear.bias"])
        investigation.select_training_parameters(model, "yolo_kd", True)
        enabled = {name for name, value in model.parameters.items() if value.requires_grad}
        self.assertEqual(enabled, {"model.10.linear.weight", "model.10.linear.bias"})
        investigation.select_training_parameters(model, "yolo_kd", False)
        self.assertTrue(all(parameter.requires_grad for parameter in model.parameters.values()))

    def test_mobilenet_warmup_updates_projection_and_classifier_only(self):
        model = self.Model(["conv_stem.weight", "blocks.0.0.bn1.weight", "conv_head.weight",
                            "conv_head.bias", "classifier.weight", "classifier.bias"])
        for variant in ("small_kd", "large_kd"):
            with self.subTest(variant=variant):
                investigation.select_training_parameters(model, variant, True)
                enabled = {name for name, value in model.parameters.items() if value.requires_grad}
                self.assertEqual(enabled, {"conv_head.weight", "conv_head.bias",
                                           "classifier.weight", "classifier.bias"})
                investigation.select_training_parameters(model, variant, False)
                self.assertTrue(all(parameter.requires_grad for parameter in model.parameters.values()))


if __name__ == "__main__":
    unittest.main()
