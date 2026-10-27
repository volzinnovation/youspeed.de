"""Small graph tests; real checkpoint/export checks live in the external report."""
from pathlib import Path
import copy
import json
import sys
import tempfile
import unittest
from unittest import mock

import cv2
import numpy as np
import torch
from torch import nn

sys.path.insert(0, str(Path(__file__).parents[2]))
from scripts.lanes import export_auxiliary_model as export
from scripts.lanes import export_auxiliary_litert as lite
from scripts.lanes import train_a2d2_auxiliary as training
from scripts.lanes import train_mixed_auxiliary as mixed


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


class TrainingProvenanceTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.a2d2 = self.root / "a2d2-manifest.json"
        self.zod = self.root / "zod-manifest.json"
        training.write_json(self.a2d2, {"dataset": "A2D2"})
        training.write_json(self.zod, dict(dataset="ZOD", training_eligible=True,
            target_kind="paint", license="CC BY-SA 4.0", source_revision="original-mini-archive-sha"))
        self.config = dict(schemaVersion=1, arm="a2d2_zod", detectorSha256=training.DETECTOR_SHA256,
            sourceManifestSha256={"A2D2": training.sha256_file(self.a2d2), "ZOD": training.sha256_file(self.zod)})
        self.proof = dict(stateHashBefore="a" * 64, stateHashAfter="a" * 64, stateIdentical=True,
            probeEqual=True, allParametersFrozen=True, allModulesEval=True, probeMaxAbsDifference=0.,
            checkpointHashBefore=training.DETECTOR_SHA256, checkpointHashAfter=training.DETECTOR_SHA256)
        training.write_json(self.root / "config.json", self.config)
        self.checkpoint = dict(config=self.config, headState={"weight": torch.zeros(1)}, provenance={})
        # Exercise the real trainer finalizer's checkpoint format, not a fabricated
        # legacy alias for a mixed experiment.
        mixed.finalize_arm(self.root, {}, self.checkpoint, self.proof)
        self.path = self.root / "auxiliary-marking.pt"

    def validate(self, **kwargs):
        return export.validate_training_provenance(self.path, self.a2d2,
            zod_manifest=self.zod, detector_state_hash="a" * 64, **kwargs)

    def test_finalized_mixed_checkpoint_retains_both_sources_and_detector_proof(self):
        result = self.validate()
        self.assertEqual(result["schema"], "mixed-v1")
        self.assertEqual(result["sourceManifestSha256"], self.config["sourceManifestSha256"])
        self.assertEqual(result["detectorPreservation"], self.proof)
        self.assertEqual(result["zodSourceRevision"], "original-mini-archive-sha")
        self.assertEqual(result["configSha256"], training.sha256_file(self.root / "config.json"))
        for source, path in (("A2D2", self.a2d2), ("ZOD", self.zod)):
            self.assertEqual(result["sourceManifests"][source],
                             dict(path=str(path.resolve()), sha256=training.sha256_file(path)))
        result["detectorPreservation"]["probeEqual"] = False
        self.assertTrue(self.validate()["detectorPreservation"]["probeEqual"])

    def test_compute_matched_a2d2_arm_still_binds_zod_experiment_source(self):
        self.config["arm"] = "a2d2"
        training.write_json(self.root / "config.json", self.config)
        mixed.finalize_arm(self.root, {}, self.checkpoint, self.proof)
        self.assertEqual(self.validate()["arm"], "a2d2")
        with self.assertRaisesRegex(ValueError, "zod-manifest"):
            export.validate_training_provenance(self.path, self.a2d2)

    def test_both_original_manifest_bytes_are_required(self):
        for source, path in (("A2D2", self.a2d2), ("ZOD", self.zod)):
            with self.subTest(source=source):
                original = path.read_bytes()
                path.write_bytes(original + b"\n")
                with self.assertRaisesRegex(ValueError, source + " manifest differs"):
                    self.validate()
                path.write_bytes(original)

    def test_mixed_config_cannot_be_rewritten_after_finalization(self):
        altered = copy.deepcopy(self.checkpoint)
        altered["config"]["arm"] = "a2d2"
        torch.save(altered, self.path)
        with self.assertRaisesRegex(ValueError, "configuration differs"):
            self.validate()

    def test_missing_failed_or_inconsistent_preservation_is_rejected(self):
        mutations = [
            ("missing", lambda p: p.pop("detectorPreservation")),
            ("integer flag", lambda p: p["detectorPreservation"].update(probeEqual=1)),
            ("unfrozen", lambda p: p["detectorPreservation"].update(allParametersFrozen=False)),
            ("training mode", lambda p: p["detectorPreservation"].update(allModulesEval=False)),
            ("state mismatch", lambda p: p["detectorPreservation"].update(stateHashAfter="b" * 64)),
            ("missing state", lambda p: p["detectorPreservation"].update(stateHashBefore=None, stateHashAfter=None)),
            ("checkpoint mismatch", lambda p: p["detectorPreservation"].update(checkpointHashAfter="b" * 64)),
            ("changed probe", lambda p: p["detectorPreservation"].update(probeMaxAbsDifference=.001)),
            ("nonfinite probe", lambda p: p["detectorPreservation"].update(probeMaxAbsDifference=float("nan"))),
            ("boolean probe", lambda p: p["detectorPreservation"].update(probeMaxAbsDifference=False)),
        ]
        for name, mutate in mutations:
            with self.subTest(name=name):
                altered = copy.deepcopy(self.checkpoint)
                mutate(altered["provenance"])
                torch.save(altered, self.path)
                with self.assertRaises(ValueError):
                    self.validate()

    def test_loaded_detector_must_match_the_recorded_training_state(self):
        with self.assertRaisesRegex(ValueError, "Loaded detector state differs"):
            export.validate_training_provenance(self.path, self.a2d2, zod_manifest=self.zod,
                                                detector_state_hash="b" * 64)

    def test_incomplete_or_ambiguous_source_maps_are_rejected(self):
        variants = [dict(self.config, sourceManifestSha256={"A2D2": "a" * 64}),
                    dict(self.config, sourceManifestSha256={"A2D2": "a" * 64, "ZOD": ""}),
                    dict(self.config, sourceManifestSha256=None),
                    dict(self.config, datasetManifestSha256="a" * 64),
                    dict(self.config, arm="unknown"),
                    {k: v for k, v in self.config.items() if k != "sourceManifestSha256"}]
        for config in variants:
            with self.subTest(config=config), self.assertRaises(ValueError):
                export.source_manifest_hashes(config)

    def test_legacy_a2d2_hash_contract_is_preserved(self):
        checkpoint = dict(config=dict(detectorSha256=training.DETECTOR_SHA256,
            datasetManifestSha256=training.sha256_file(self.a2d2)), headState={"weight": torch.zeros(1)})
        torch.save(checkpoint, self.path)
        result = export.validate_training_provenance(self.path, self.a2d2)
        self.assertEqual(result["schema"], "a2d2-legacy")
        self.assertEqual(result["sourceManifestSha256"], {"A2D2": training.sha256_file(self.a2d2)})
        with self.assertRaisesRegex(ValueError, "does not bind a ZOD"):
            self.validate()
        self.a2d2.write_text("changed")
        with self.assertRaisesRegex(ValueError, "A2D2 manifest differs"):
            export.validate_training_provenance(self.path, self.a2d2)

    def test_mixed_validation_sampling_uses_only_bound_a2d2_validation(self):
        objects, pairs = {}, []
        for index in range(3):
            path = self.root / (str(index) + ".png")
            cv2.imwrite(str(path), np.full((4, 6, 3), index * 30, np.uint8))
            objects[str(index)] = dict(local_path=str(path), sha256=training.sha256_file(path))
            pairs.append(dict(rgb=str(index)))
        with mock.patch.object(export.training, "validate_manifest",
                return_value=({}, objects, {"validation": pairs}, {})):
            records = export.sample_validation(self.a2d2, self.config, 2, 32)
        self.assertEqual([row["key"] for row in records], ["0", "2"])
        self.assertTrue(all(row["tensor"].shape == (1, 3, 32, 32) for row in records))


if __name__ == "__main__":
    unittest.main()
