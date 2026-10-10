import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import numpy as np
import torch
from torch import nn

SPEC = importlib.util.spec_from_file_location("auxiliary", Path(__file__).parents[2] / "scripts/lanes/train_a2d2_auxiliary.py")
aux = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(aux)


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
