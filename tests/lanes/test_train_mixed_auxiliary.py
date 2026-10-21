import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import cv2
import numpy as np
import torch

SPEC = importlib.util.spec_from_file_location("mixed", Path(__file__).parents[2] / "scripts/lanes/train_mixed_auxiliary.py")
mixed = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(mixed)


class MixedTrainingTest(unittest.TestCase):
    def manifest(self, root):
        objects, pairs = [], []
        for index, split in enumerate(("train", "test")):
            for kind in ("rgb", "label", "valid"):
                key = "%d-%s.png" % (index, kind)
                if kind == "rgb":
                    pixels = np.full((4, 8, 3), index * 20, np.uint8)
                else:
                    pixels = np.full((4, 8), 255 if kind == "valid" else 0, np.uint8)
                    if kind == "label":
                        pixels[:, 2] = 255
                cv2.imwrite(str(root / key), pixels)
                objects.append(dict(key=key, local_path=str(root / key), sha256=mixed.aux.sha256_file(root / key)))
            pairs.append(dict(frame_id=str(index), rgb="%d-rgb.png" % index,
                              label="%d-label.png" % index, valid="%d-valid.png" % index,
                              split=split, official_split="train" if index == 0 else "val",
                              group_id="group-%d" % index, width=8, height=4))
        data = dict(dataset="ZOD", target_kind="paint", license="CC BY-SA 4.0",
                    source_revision="test-fixture", training_eligible=True, objects=objects, pairs=pairs)
        path = root / "manifest.json"
        path.write_text(json.dumps(data))
        return path, data

    def test_accepts_repeated_empty_or_identical_masks_but_verifies_source_bytes(self):
        with tempfile.TemporaryDirectory() as folder:
            path, data = self.manifest(Path(folder))
            _, _, partitions = mixed.validate_zod_manifest(path)
            self.assertEqual({k: len(v) for k, v in partitions.items()}, {"train": 1, "validation": 0, "test": 1})
            Path(data["objects"][0]["local_path"]).write_bytes(b"changed")
            with self.assertRaisesRegex(ValueError, "SHA-256"):
                mixed.validate_zod_manifest(path)

    def test_unqualified_geometry_or_coverage_cannot_train(self):
        with tempfile.TemporaryDirectory() as folder:
            path, data = self.manifest(Path(folder))
            data["training_eligible"] = False
            path.write_text(json.dumps(data))
            with self.assertRaisesRegex(ValueError, "qualified"):
                mixed.validate_zod_manifest(path)

    def test_official_validation_leak_and_group_overlap_rejected(self):
        for mode in ("official", "group", "image"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                path, data = self.manifest(Path(folder))
                if mode == "official":
                    data["pairs"][0]["official_split"] = "val"
                elif mode == "group":
                    data["pairs"][1]["group_id"] = data["pairs"][0]["group_id"]
                else:
                    source, destination = data["objects"][0], data["objects"][3]
                    Path(destination["local_path"]).write_bytes(Path(source["local_path"]).read_bytes())
                    destination["sha256"] = source["sha256"]
                path.write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    mixed.validate_zod_manifest(path)

    def test_mask_shape_binary_and_validity_invariants(self):
        for mode in ("shape", "nonbinary", "ignored_positive"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as folder:
                path, data = self.manifest(Path(folder))
                obj = data["objects"][2 if mode == "ignored_positive" else 1]
                pixels = np.zeros((4, 8), np.uint8)
                if mode == "shape":
                    pixels = np.zeros((3, 8), np.uint8)
                if mode == "nonbinary":
                    pixels[0, 0] = 1
                cv2.imwrite(obj["local_path"], pixels)
                obj["sha256"] = mixed.aux.sha256_file(obj["local_path"])
                path.write_text(json.dumps(data))
                with self.assertRaises(ValueError):
                    mixed.validate_zod_manifest(path)

    def test_sampler_matches_compute_balances_each_batch_and_is_reproducible(self):
        a, z = ["a%d" % i for i in range(128)], ["z%d" % i for i in range(20)]
        options = dict(seed=20261008, epoch=1, steps=16, batch_size=8)
        baseline = list(mixed.sampled_batches(a, z, arm="a2d2", **options))
        mixture = list(mixed.sampled_batches(a, z, arm="a2d2_zod", **options))
        self.assertEqual(len(baseline), len(mixture))
        self.assertEqual(len(set(x for b in baseline for x in b)), 128)
        for batch in mixture:
            self.assertEqual(sum(x.startswith("a") for x in batch), 4)
            self.assertEqual(sum(x.startswith("z") for x in batch), 4)
        self.assertEqual(mixture, list(mixed.sampled_batches(a, z, arm="a2d2_zod", **options)))
        self.assertNotEqual(mixture, list(mixed.sampled_batches(a, z, arm="a2d2_zod", **dict(options, epoch=2))))
        flat_z = [x for b in mixture for x in b if x.startswith("z")]
        self.assertEqual(len(set(flat_z[:20])), 20)

    def test_sampler_rejects_missing_source(self):
        with self.assertRaisesRegex(ValueError, "Empty"):
            list(mixed.sampled_batches([1], [], arm="a2d2_zod", seed=1, epoch=1, steps=1, batch_size=2))

    def test_supervision_that_disappears_on_resize_rejected(self):
        valid = np.zeros((6, 6), bool)
        valid[0, 0] = True
        _, transform = mixed.aux.letterbox_rgb(np.zeros((6, 6, 3), np.uint8), 2)
        with self.assertRaisesRegex(ValueError, "after letterboxing"):
            mixed.aligned_targets(np.zeros_like(valid), valid, transform)

    def test_nonfinite_evaluation_rejected(self):
        with patch.object(mixed.aux, "evaluate", return_value={"loss": float("nan"), "marking": {"iou": 0.}}):
            with self.assertRaisesRegex(ValueError, "Non-finite"):
                mixed.checked_evaluate(None)

    def test_checkpoints_require_and_embed_preservation_proof(self):
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder)
            config = {"detectorSha256": "source-checkpoint-hash"}
            (output / "config.json").write_text(json.dumps(config))
            checkpoint = {"headState": {}, "config": config, "provenance": {}}
            proof = dict(stateIdentical=True, probeEqual=True, allParametersFrozen=True,
                         allModulesEval=True, checkpointHashBefore="source-checkpoint-hash",
                         checkpointHashAfter="changed-hash")
            with self.assertRaisesRegex(ValueError, "preservation"):
                mixed.finalize_arm(output, {}, checkpoint, proof)
            self.assertFalse((output / "auxiliary-marking.pt").exists())
            proof["checkpointHashAfter"] = "source-checkpoint-hash"
            mixed.finalize_arm(output, {}, checkpoint, proof)
            loaded = torch.load(output / "auxiliary-marking.pt", weights_only=True)
            self.assertEqual(loaded["provenance"]["detectorPreservation"], proof)

    def test_tiny_training_selects_only_a2d2_validation_then_scores_holdouts(self):
        torch.set_num_threads(1)
        torch.manual_seed(42)

        def record(source, identity):
            target = torch.zeros(1, 32, 32)
            target[:, 10:20, 10:12] = 1
            return dict(dataset=source, identity=identity,
                        features=(torch.randn(64, 8, 8), torch.randn(128, 4, 4)),
                        target=target, valid=torch.ones_like(target))

        cache = {source: {split: [record(source, source + split)]
                          for split in ("train", "validation", "test")} for source in ("A2D2", "ZOD")}
        initial = mixed.aux.AuxiliaryMarkingHead().state_dict()
        config = dict(seed=1, epochs=2, stepsPerEpoch=1, batchSize=2, positiveWeight=20., inputSize=32)
        calls = []

        def evaluate(head, rows, *args):
            identity = rows[0]["identity"]
            calls.append(identity)
            # External holdouts would select a different epoch if accidentally used.
            value = .8 if len(calls) == 1 else .4 if len(calls) == 2 else .99
            return {"marking": {"iou": value}}

        with tempfile.TemporaryDirectory() as folder, patch.object(mixed.aux, "evaluate", side_effect=evaluate):
            metrics, checkpoint = mixed.train_arm("a2d2_zod", cache, initial, config, Path(folder) / "mixed", "cpu")
            self.assertEqual(metrics["bestEpoch"], 1)
            self.assertEqual(metrics["optimizerUpdates"], 2)
            self.assertEqual(metrics["sourceFrameExposures"], {"A2D2": 2, "ZOD": 2})
            self.assertEqual(calls, ["A2D2validation", "A2D2validation", "A2D2test", "ZODvalidation", "ZODtest"])
            self.assertFalse((Path(folder) / "mixed" / "auxiliary-marking.pt").exists())
            self.assertEqual(checkpoint["provenance"]["bestEpoch"], 1)
            with self.assertRaisesRegex(ValueError, "preservation"):
                mixed.finalize_arm(Path(folder) / "mixed", metrics, checkpoint, {})

    def test_identical_source_rows_produce_identical_heads_and_earliest_tie(self):
        torch.set_num_threads(1)
        torch.manual_seed(51)
        features = (torch.randn(64, 8, 8), torch.randn(128, 4, 4))
        # A legitimate fully supervised zero-paint scene remains a training row.
        target = torch.zeros(1, 32, 32)
        cache = {source: {split: [dict(dataset=source, identity=source + split,
                                      features=features, target=target, valid=torch.ones_like(target))]
                          for split in ("train", "validation", "test")} for source in ("A2D2", "ZOD")}
        initial = {k: v.clone() for k, v in mixed.aux.AuxiliaryMarkingHead().state_dict().items()}
        config = dict(seed=1, epochs=2, stepsPerEpoch=2, batchSize=2, positiveWeight=20., inputSize=32)
        selected, starts, states = {}, [], []
        real_optimizer = torch.optim.AdamW

        def optimizer(parameters, **kwargs):
            parameters = list(parameters)
            starts.append([p.detach().clone() for p in parameters])
            return real_optimizer(parameters, **kwargs)

        def evaluate(head, rows, *args):
            states.append({k: v.detach().cpu().clone() for k, v in head.state_dict().items()})
            return {"marking": {"iou": 0.}}

        with tempfile.TemporaryDirectory() as folder, patch.object(mixed.aux, "evaluate", side_effect=evaluate), patch.object(torch.optim, "AdamW", side_effect=optimizer):
            for arm in ("a2d2", "a2d2_zod"):
                states.clear()
                metrics, checkpoint = mixed.train_arm(arm, cache, initial, config, Path(folder) / arm, "cpu")
                self.assertEqual(metrics["bestEpoch"], 1)
                self.assertEqual(metrics["optimizerUpdates"], 4)
                self.assertEqual(metrics["sourceFrameExposures"], {"A2D2": 8} if arm == "a2d2" else {"A2D2": 4, "ZOD": 4})
                selected[arm] = checkpoint["headState"]
                for key in checkpoint["headState"]:
                    self.assertTrue(torch.equal(checkpoint["headState"][key], states[0][key]))
        self.assertTrue(all(torch.equal(a, b) for a, b in zip(*starts)))
        self.assertTrue(all(torch.equal(selected["a2d2"][k], selected["a2d2_zod"][k]) for k in selected["a2d2"]))


if __name__ == "__main__":
    unittest.main()
