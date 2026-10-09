import importlib.util
import json
import os
from pathlib import Path
import random
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import warnings

import numpy as np
import torch
from torch import nn

SPEC = importlib.util.spec_from_file_location("auxiliary", Path(__file__).parents[2] / "scripts/lanes/train_a2d2_auxiliary.py")
aux = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(aux)


class ExecutionTest(unittest.TestCase):
    def setUp(self):
        rng, np_rng, py_rng = torch.random.get_rng_state(), np.random.get_state(), random.getstate()
        deterministic = torch.are_deterministic_algorithms_enabled()
        warn_only = torch.is_deterministic_algorithms_warn_only_enabled()
        precision = torch.get_float32_matmul_precision()
        benchmark, cudnn_deterministic = torch.backends.cudnn.benchmark, torch.backends.cudnn.deterministic
        cudnn_tf32, matmul_tf32 = torch.backends.cudnn.allow_tf32, torch.backends.cuda.matmul.allow_tf32
        threads = torch.get_num_threads()

        def restore():
            torch.random.set_rng_state(rng)
            np.random.set_state(np_rng)
            random.setstate(py_rng)
            torch.use_deterministic_algorithms(deterministic, warn_only=warn_only)
            torch.set_float32_matmul_precision(precision)
            torch.backends.cudnn.benchmark = benchmark
            torch.backends.cudnn.deterministic = cudnn_deterministic
            torch.backends.cudnn.allow_tf32 = cudnn_tf32
            torch.backends.cuda.matmul.allow_tf32 = matmul_tf32
            torch.set_num_threads(threads)
        self.addCleanup(restore)

    def test_cli_adds_cuda_without_changing_training_defaults(self):
        required = ["--manifest", "m.json", "--detector", "d.pt", "--output-dir", "/tmp/new"]
        args = aux.build_parser().parse_args(required)
        self.assertEqual((args.device, args.epochs, args.batch_size, args.input_size, args.seed),
                         ("mps", 15, 8, 640, 20261008))
        for device in ("cpu", "mps", "cuda", "cuda:0", "cuda:2"):
            self.assertEqual(aux.build_parser().parse_args(required + ["--device", device]).device, device)
        for invalid in ("cuda:-1", "cuda:01", "cuda:0,1", "cuda:1.0", "cpu:0", "auto"):
            with self.assertRaises(aux.argparse.ArgumentTypeError):
                aux.training_device(invalid)

    def test_cuda_environment_requires_launch_time_hash_and_blas_settings(self):
        valid = dict(CUBLAS_WORKSPACE_CONFIG=":4096:8", PYTHONHASHSEED="20261008")
        with patch.dict(os.environ, valid, clear=True):
            aux.validate_cuda_environment(20261008)
        for update in ({"CUBLAS_WORKSPACE_CONFIG": ""}, {"CUBLAS_WORKSPACE_CONFIG": ":4096:2"},
                       {"PYTHONHASHSEED": "0"}, {"NVIDIA_TF32_OVERRIDE": "1"}):
            with patch.dict(os.environ, dict(valid, **update), clear=True):
                with self.assertRaises(ValueError):
                    aux.validate_cuda_environment(20261008)
        with patch.dict(os.environ, dict(valid, CUBLAS_WORKSPACE_CONFIG=":16:8"), clear=True):
            aux.validate_cuda_environment(20261008)

    def test_cuda_selection_and_policies_are_recorded_without_silent_fallback(self):
        env = dict(CUBLAS_WORKSPACE_CONFIG=":4096:8", PYTHONHASHSEED="20261008", CUDA_VISIBLE_DEVICES="2,3,4")
        props = SimpleNamespace(name="fixture GPU", major=8, minor=6, total_memory=1234)
        with patch.dict(os.environ, env, clear=True), patch.object(torch.cuda, "is_available", return_value=True), \
                patch.object(torch.cuda, "device_count", return_value=3), \
                patch.object(torch.cuda, "get_device_properties", return_value=props), \
                patch.object(torch.cuda, "set_device") as select, patch.object(torch.cuda, "manual_seed_all"):
            for policy in ("seeded", "strict"):
                device, info = aux.configure_execution("cuda:2", 20261008, policy)
                self.assertEqual(device, "cuda:2")
                select.assert_called_with(2)
                self.assertTrue(info["deterministicAlgorithms"])
                self.assertEqual(info["deterministicWarnOnly"], policy == "seeded")
                self.assertFalse(info["cuda"]["cudnnBenchmark"])
                self.assertTrue(info["cuda"]["cudnnDeterministic"])
                self.assertFalse(info["cuda"]["cudnnAllowTF32"])
                self.assertFalse(info["cuda"]["matmulAllowTF32"])
                self.assertEqual(info["cuda"]["float32MatmulPrecision"], "highest")
                self.assertEqual(info["environment"]["CUDA_VISIBLE_DEVICES"], "2,3,4")
                json.dumps(info)
            self.assertEqual(aux.configure_execution("cuda", 20261008)[0], "cuda:0")
            with self.assertRaisesRegex(ValueError, "outside visible"):
                aux.configure_execution("cuda:3", 20261008)
        with patch.dict(os.environ, env, clear=True), patch.object(torch.cuda, "is_available", return_value=False):
            with self.assertRaisesRegex(ValueError, "no fallback"):
                aux.configure_execution("cuda", 20261008)
        with patch.object(torch.backends.mps, "is_available", return_value=False):
            with self.assertRaisesRegex(ValueError, "no fallback"):
                aux.configure_execution("mps", 20261008)
        for seed in (-1, 2**32):
            with self.assertRaisesRegex(ValueError, "Seed"):
                aux.configure_execution("cpu", seed)

    def test_synthetic_preflight_preserves_real_training_initialization_rng(self):
        aux.configure_execution("cpu", 20261008)
        before = torch.random.get_rng_state().clone()
        result = aux.training_preflight("cpu")
        self.assertTrue(torch.equal(before, torch.random.get_rng_state()))
        self.assertEqual(result["status"], "passed")
        self.assertTrue(np.isfinite(result["loss"]))
        first = aux.AuxiliaryMarkingHead()
        aux.configure_execution("cpu", 20261008)
        self.assertEqual(aux.state_hash(first), aux.state_hash(aux.AuxiliaryMarkingHead()))

    def test_preflight_reports_warnings_and_does_not_downgrade_kernel_errors(self):
        loss = aux.masked_loss

        def warning_loss(*args):
            warnings.warn("fixture unsupported deterministic kernel", UserWarning)
            return loss(*args)

        with patch.object(aux, "masked_loss", side_effect=warning_loss):
            result = aux.training_preflight("cpu")
            self.assertIn("fixture unsupported deterministic kernel", result["warnings"])
        before = torch.random.get_rng_state().clone()
        with patch.object(aux, "masked_loss", side_effect=RuntimeError("unsupported deterministic kernel")):
            with self.assertRaisesRegex(RuntimeError, "unsupported deterministic"):
                aux.training_preflight("cpu")
        self.assertTrue(torch.equal(before, torch.random.get_rng_state()))

    def test_synchronization_targets_selected_cuda_device(self):
        with patch.object(torch.cuda, "synchronize") as synchronize:
            aux.synchronize("cuda:2")
            synchronize.assert_called_once_with("cuda:2")


class FakeDetector(nn.Module):
    def __init__(self):
        super().__init__()
        self.model = nn.Sequential(nn.Conv2d(3, 64, 3, stride=2, padding=1), nn.ReLU(),
                                   nn.Sequential(nn.Conv2d(64, 64, 3, stride=2, padding=1), nn.BatchNorm2d(64)),
                                   nn.ReLU(), nn.Conv2d(64, 128, 3, stride=2, padding=1))

    def forward(self, x):
        return self.model(x)


class TrainingTest(unittest.TestCase):
    def test_frozen_weights_bn_modes_and_gradients(self):
        extractor = aux.FrozenYOLOFeatures(FakeDetector())
        before = aux.state_hash(extractor)
        extractor.train(True)
        head = aux.AuxiliaryMarkingHead()
        features = extractor(torch.randn(2, 3, 32, 32))
        self.assertFalse(any(f.requires_grad for f in features))
        loss = head(features).square().mean()
        loss.backward()
        self.assertTrue(any(p.grad is not None for p in head.parameters()))
        self.assertTrue(all(p.grad is None and not p.requires_grad for p in extractor.parameters()))
        self.assertTrue(all(not m.training for m in extractor.modules()))
        self.assertEqual(before, aux.state_hash(extractor))
        self.assertEqual(tuple(head(features).shape), (2, 1, 8, 8))
        self.assertEqual(sum(p.numel() for p in head.parameters()), 3457)

    def test_exact_color_targets_ignore_and_letterbox(self):
        label = np.array([[(255, 193, 37), (128, 0, 255), (255, 0, 255), (96, 69, 143)],
                          [(53, 46, 82), (72, 209, 204), (1, 2, 3), (135, 206, 255)]], np.uint8)
        class_map = {"#ffc125": "Solid line", "#8000ff": "Dashed line", "#ff00ff": "Road",
                     "#60458f": "Blurred", "#352e52": "Rain", "#48d1cc": "Ego", "#87ceff": "Sky"}
        positive, valid = aux.decode_labels(label, class_map)
        np.testing.assert_array_equal(positive, [[1, 1, 0, 0], [0, 0, 0, 0]])
        np.testing.assert_array_equal(valid, [[1, 1, 1, 0], [0, 0, 0, 1]])
        x, transform = aux.letterbox_rgb(label, 8)
        self.assertEqual(transform["padTop"], 2)
        self.assertEqual(transform["resizedHeight"], 4)
        target, mask = aux.letterbox_labels(positive, valid, transform)
        self.assertEqual(int(target.sum()), 8)
        self.assertEqual(int(mask.sum()), 16)
        self.assertEqual(float(mask[:, :2].sum()), 0)
        self.assertTrue(torch.allclose(x[:, :2], torch.full_like(x[:, :2], 114 / 255)))

    def test_ignored_pixels_have_no_loss_gradient(self):
        logits = torch.zeros(1, 1, 2, 2, requires_grad=True)
        target = torch.tensor([[[[1., 0.], [0., 1.]]]])
        valid = torch.tensor([[[[1., 1.], [0., 0.]]]])
        loss = aux.masked_loss(logits, target, valid, 3.)
        loss.backward()
        self.assertTrue(torch.isfinite(loss))
        self.assertLess(float(logits.grad[0, 0, 0, 0]), 0)
        self.assertGreater(float(logits.grad[0, 0, 0, 1]), 0)
        self.assertEqual(float(logits.grad[0, 0, 1].abs().sum()), 0)
        empty = aux.masked_loss(logits, target, torch.zeros_like(valid), 3.)
        self.assertEqual(float(empty.detach()), 0)

    def test_thin_stripe_uses_same_pixel_centers_as_rgb(self):
        rgb = np.zeros((6, 6, 3), np.uint8)
        rgb[:, 1] = 255
        image, transform = aux.letterbox_rgb(rgb, 2)
        positive = rgb[:, :, 0] > 0
        target, _ = aux.letterbox_labels(positive, np.ones((6, 6), bool), transform)
        self.assertTrue(torch.equal(target[0].bool(), image[0] > .5))
        self.assertEqual(int(target.sum()), 2)

    def manifest(self, root):
        objects, pairs = [], []
        def obj(key, content):
            p = root / key
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
            objects.append({"key": key, "local_path": str(p), "sha256": aux.sha256_file(p)})
        for i, split in enumerate(("train", "validation", "test")):
            date = "2018100%d" % (i + 1)
            seq = date + "_120000"
            stem = "camera_lidar_semantic/" + seq
            rgb = stem + "/camera/cam_front_center/" + date + "120000_camera_frontcenter_000000001.png"
            label = stem + "/label/cam_front_center/" + date + "120000_label_frontcenter_000000001.png"
            info = rgb.replace(".png", ".json")
            for key in (rgb, label, info):
                obj(key, key)
            pairs.append({"split": split, "capture_date": date, "sequence": seq,
                          "rgb": rgb, "label": label, "camera_info": info})
        obj("camera_lidar_semantic/class_list.json", json.dumps({"#ffc125": "Solid line", "#8000ff": "Dashed line"}))
        p = root / "manifest.json"
        data = {"dataset": "A2D2", "objects": objects, "pairs": pairs}
        p.write_text(json.dumps(data))
        return p, data

    def test_valid_manifest_and_source_hash_enforcement(self):
        with tempfile.TemporaryDirectory() as directory:
            path, data = self.manifest(Path(directory))
            _, _, splits, _ = aux.validate_manifest(path)
            self.assertEqual({k: len(v) for k, v in splits.items()}, {"train": 1, "validation": 1, "test": 1})
            Path(data["objects"][0]["local_path"]).write_text("changed bytes")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                aux.validate_manifest(path)

    def test_date_and_source_overlap_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path, data = self.manifest(Path(directory))
            data["pairs"][1].update(capture_date=data["pairs"][0]["capture_date"], sequence=data["pairs"][0]["sequence"])
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "overlaps"):
                aux.validate_manifest(path)
        with tempfile.TemporaryDirectory() as directory:
            path, data = self.manifest(Path(directory))
            Path(data["objects"][3]["local_path"]).write_bytes(Path(data["objects"][0]["local_path"]).read_bytes())
            data["objects"][3]["sha256"] = data["objects"][0]["sha256"]
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "hash overlaps"):
                aux.validate_manifest(path)

    def test_binary_metrics(self):
        metrics = aux.metrics_from_counts(3, 1, 2, 4)
        self.assertEqual(metrics["marking"]["precision"], .75)
        self.assertEqual(metrics["marking"]["recall"], .6)
        self.assertEqual(metrics["marking"]["iou"], .5)
        self.assertEqual(metrics["background"]["precision"], 4 / 6)


if __name__ == "__main__":
    unittest.main()
