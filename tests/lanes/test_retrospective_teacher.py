"""Regression checks for weak-label provenance, temporal isolation and abstention."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np


SCRIPT = Path(__file__).resolve().parents[2] / "scripts/lanes/retrospective_teacher.py"
SPEC = importlib.util.spec_from_file_location("retrospective_teacher", SCRIPT)
teacher = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = teacher
SPEC.loader.exec_module(teacher)


def picture(paint=True):
    rng = np.random.RandomState(71)
    image = rng.randint(24, 40, (96, 128)).astype(np.uint8)
    if paint:
        # Separate, textured paint intervals; the dark dash gap must remain unknown.
        for lo, hi in [(30, 46), (64, 84)]:
            image[lo:hi+1, 47:50] = rng.randint(165, 225, (hi-lo+1, 3))
    return image


def boundary(provenance="fresh", segments=True):
    return dict(cue="paint", provenance=provenance, evidenceAgeSeconds=0,
        points=[[48/127, 30/95], [48/127, 84/95]],
        observedSegments=[[[48/127, 31/95], [48/127, 44/95]],
            [[48/127, 66/95], [48/127, 82/95]]] if segments else [])


def replay(root, no_target_hypothesis=False, empty_target=False, tracked=False, empty_segments=False,
           times=None, splits=None):
    root.mkdir()
    times = times or [0, .1, .2, .3, .4]
    frames, rows = [], []
    for index, time in enumerate(times):
        fid = "f" + str(index)
        data = picture(not (empty_target and index == 0)).tobytes()
        path = root / (fid + ".gray")
        path.write_bytes(data)
        digest = teacher.sha_bytes(data)
        frames.append(dict(id=fid, sequenceId="clip", split=splits[index] if splits else "development",
            time=time, width=128, height=96, grayPath=str(path), graySha256=digest, source="one-video"))
        b = boundary("tracked" if tracked else "fresh", not empty_segments)
        b["lastFreshTimestampSeconds"] = time
        raw = [] if no_target_hypothesis and index == 0 else [b]
        rows.append(dict(id=fid, sequenceId="clip", time=time, width=128, height=96,
            inputSha256=digest, rawBoundaries=raw, confirmedBoundaries=[]))
    teacher.write_json(root / "input.normalized.json", dict(schemaVersion=1, frames=frames, variant="fixture"))
    (root / "frames.ndjson").write_text("".join(json.dumps(r)+"\n" for r in rows))
    return frames, rows


def annotations(directory):
    return [json.loads(line) for line in (directory / "annotations.ndjson").read_text().splitlines()]


class RetrospectiveTeacherTests(unittest.TestCase):
    def test_lk_backprojects_translated_visible_paint(self):
        source = picture()
        target = np.roll(np.roll(source, 3, axis=1), 2, axis=0)
        config = teacher.Config()
        anchors = teacher.sampled_anchors([("dash", [[48/127, 31/95], [48/127, 44/95]])], source, config)
        aligned = teacher.align_anchors(source, target, anchors, config)
        self.assertGreater(len(aligned), 3)
        self.assertTrue(all(abs(point[0]-51) < .4 for point, _, _, _ in aligned))
        self.assertTrue(all(error <= config.consistency_pixels for _, _, error, _ in aligned))

    def test_future_support_recovers_visible_points_without_target_hypothesis(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            replay(root / "replay", no_target_hypothesis=True)
            output = root / "out"
            teacher.run(root / "replay", output, teacher.Config(), bootstrap=True)
            rows = annotations(output)
            self.assertGreater(len(rows[0]["positivePoints"]), 0)
            self.assertTrue(rows[0]["usesFutureFrames"])
            self.assertTrue(all(p["futureSupportCount"] >= 2 for p in rows[0]["positivePoints"]))
            self.assertTrue(all(len(set(p["sourceFrameIds"])) >= 2 for p in rows[0]["positivePoints"]))
            self.assertEqual(rows[-1]["status"], "unknown")
            self.assertEqual(rows[0]["diagnosticAgreement"]["prePresentationGeometryPoints"], 0)
            # Do not rasterize the fitted model's gap as paint.
            self.assertFalse(any(48 <= p["pixel"][1] <= 62 for p in rows[0]["positivePoints"]))
            self.assertEqual(rows[0]["negativePixelCount"], 0)

    def test_same_frame_many_anchors_cannot_supply_multiple_exposures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            replay(root / "replay", times=[0])
            teacher.run(root / "replay", root / "out", teacher.Config(), bootstrap=True)
            self.assertEqual(annotations(root / "out")[0]["status"], "unknown")

    def test_target_without_local_paint_abstains(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            replay(root / "replay", no_target_hypothesis=True, empty_target=True)
            teacher.run(root / "replay", root / "out", teacher.Config(), bootstrap=True)
            self.assertEqual(annotations(root / "out")[0]["positivePoints"], [])

    def test_tracked_and_empty_observed_segments_cannot_seed(self):
        for options, diagnostic in [(dict(tracked=True), "tracked_or_unknown_provenance"),
                (dict(empty_segments=True), "empty_observed_segments")]:
            with self.subTest(options=options), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                replay(root / "replay", **options)
                report = teacher.run(root / "replay", root / "out", teacher.Config(), bootstrap=True)
                self.assertEqual(report["total"]["positivePoints"], 0)
                self.assertEqual(report["seedDiagnostics"][diagnostic], 5)

    def test_causal_ablation_never_consumes_future_sources(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            replay(root / "replay", no_target_hypothesis=True)
            teacher.run(root / "replay", root / "out", teacher.Config(mode="causal"), bootstrap=True)
            rows = annotations(root / "out")
            self.assertEqual(rows[0]["positivePoints"], [])
            self.assertGreater(sum(len(r["positivePoints"]) for r in rows[2:]), 0)
            for row in rows:
                self.assertFalse(row["usesFutureFrames"])
                self.assertTrue(all(s["time"] <= row["time"] for s in row["supportSources"]))

    def test_split_and_temporal_discontinuities_bound_propagation(self):
        config = teacher.Config()
        frames = [dict(sequenceId="s", split=split, time=t, width=128, height=96, source="a")
            for split, t in [("development", 0), ("validation", .1), ("validation", .5), ("validation", .6)]]
        ids = teacher.partitions(frames, config)
        self.assertEqual(ids, [0, 1, 2, 2])
        self.assertEqual(teacher.source_indices(frames, ids, 0, config), [0])
        self.assertEqual(teacher.source_indices(frames, ids, 2, config), [2, 3])
        frames[-1]["sequenceId"] = "other"
        self.assertEqual(teacher.partitions(frames, config), [0, 1, 2, 3])

    def test_wrong_replay_pts_and_sparse_reviewed_future_support_abstain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frames, rows = replay(root / "replay")
            labels = dict(frames=[dict(id="f2", sequenceId="clip", split="development", time=.2,
                inputSha256=frames[2]["graySha256"],
                borders=[dict(geometry=boundary()["points"], paintedYIntervals=[[31/95, 44/95]])])])
            teacher.write_json(root / "labels.json", labels)
            report = teacher.run(root / "replay", root / "out", teacher.Config(), root / "labels.json")
            self.assertEqual(report["total"]["positivePoints"], 0)
            rows[0]["time"] = .01
            (root / "replay/frames.ndjson").write_text("".join(json.dumps(r)+"\n" for r in rows))
            with self.assertRaisesRegex(ValueError, "alignment mismatch"):
                teacher.read_replay(root / "replay")

    def test_reviewed_intervals_are_primary_and_do_not_need_detector_output(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frames, _ = replay(root / "replay", tracked=True)
            geometry = boundary()["points"]
            labels = dict(reviewer="synthetic fixture", qualification="test only", frames=[dict(
                id=f["id"], sequenceId="clip", split="development", time=f["time"], inputSha256=f["graySha256"],
                borders=[dict(geometry=geometry, paintedYIntervals=[[31/95, 44/95], [66/95, 82/95]])])
                for f in frames[1:3]])
            teacher.write_json(root / "labels.json", labels)
            report = teacher.run(root / "replay", root / "out", teacher.Config(), root / "labels.json")
            self.assertGreater(len(annotations(root / "out")[0]["positivePoints"]), 0)
            self.assertEqual(report["seedDiagnostics"]["source_frames_with_anchors"], 2)
            inputs = json.loads((root / "out/student-inputs.json").read_text())
            self.assertEqual(set(inputs["frames"][0]), {"id", "sequenceId", "split", "time", "grayPath", "graySha256", "width", "height"})

    def test_bootstrap_review_guard_quarantines_stable_wrong_paint_on_reviewed_unmarked_scene(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frames, _ = replay(root / "replay")
            labels = dict(reviewer="fixture reviewer", frames=[dict(id=f["id"], sequenceId="clip",
                split="development", time=f["time"], inputSha256=f["graySha256"], borders=[])
                for f in frames])
            teacher.write_json(root / "review.json", labels)
            report = teacher.run(root / "replay", root / "out", teacher.Config(), bootstrap=True,
                reviewed_anchor_labels_path=root / "review.json")
            self.assertGreater(report["total"]["positivePointsBeforeReviewedGuard"], 0)
            self.assertEqual(report["total"]["positivePoints"], 0)
            self.assertEqual(report["total"]["rejectedByReviewedAnchorGuard"], report["total"]["positivePointsBeforeReviewedGuard"])
            for row in annotations(root / "out"):
                self.assertEqual(row["positivePoints"], [])
                self.assertEqual(row["negativePixelCount"], 0)
                self.assertTrue(row["reviewedAnchorGuardEnabled"])

    def test_review_guard_adds_provenance_but_no_temporal_support_votes(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            frames, _ = replay(root / "replay", no_target_hypothesis=True)
            f = frames[0]
            labels = dict(frames=[dict(id=f["id"], sequenceId="clip", split="development", time=f["time"],
                inputSha256=f["graySha256"], borders=[dict(geometry=boundary()["points"],
                    paintedYIntervals=[[31/95, 44/95]])])])
            teacher.write_json(root / "review.json", labels)
            teacher.run(root / "replay", root / "guarded", teacher.Config(), bootstrap=True,
                reviewed_anchor_labels_path=root / "review.json")
            teacher.run(root / "replay", root / "plain", teacher.Config(), bootstrap=True)
            guarded = annotations(root / "guarded")[0]
            plain = {tuple(p["pixel"]): p for p in annotations(root / "plain")[0]["positivePoints"]}
            self.assertGreater(len(guarded["positivePoints"]), 0)
            self.assertGreater(guarded["rejectedByReviewedAnchorGuard"], 0)
            for point in guarded["positivePoints"]:
                old = plain[tuple(point["pixel"])]
                self.assertEqual(point["futureSupportCount"], old["futureSupportCount"])
                self.assertEqual(point["sourceFrameIds"], old["sourceFrameIds"])
                self.assertEqual(point["reviewedAnchorFrameIds"], ["f0"])
                self.assertTrue(point["reviewedAnchorSegmentIds"])
                self.assertLessEqual(point["minimumReviewedAnchorDistancePixels"], 2)
                self.assertLess(point["pixel"][1], 48)

    def test_reviewed_seed_requires_explicit_hash_time_sequence_and_split(self):
        for missing in ("inputSha256", "time", "sequenceId", "split"):
            with self.subTest(missing=missing), tempfile.TemporaryDirectory() as tmp:
                root = Path(tmp)
                frames, _ = replay(root / "replay")
                f = frames[0]
                label = dict(id=f["id"], sequenceId="clip", split="development", time=f["time"],
                    inputSha256=f["graySha256"], borders=[])
                del label[missing]
                teacher.write_json(root / "review.json", dict(frames=[label]))
                with self.assertRaisesRegex(ValueError, "missing explicit identity fields"):
                    teacher.run(root / "replay", root / "out", teacher.Config(), bootstrap=True,
                        reviewed_anchor_labels_path=root / "review.json")
                self.assertFalse((root / "out").exists())

    def test_hash_mismatch_rejected_before_export(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            replay(root / "replay")
            (root / "replay/f0.gray").write_bytes(bytes(128*96))
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                teacher.run(root / "replay", root / "out", teacher.Config(), bootstrap=True)
            self.assertFalse((root / "out").exists())

    def test_repeat_annotation_and_masks_are_deterministic_and_outputs_not_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            replay(root / "replay")
            for name in ("a", "b"):
                teacher.run(root / "replay", root / name, teacher.Config(), bootstrap=True)
            self.assertEqual((root / "a/annotations.ndjson").read_bytes(), (root / "b/annotations.ndjson").read_bytes())
            for mask in (root / "a/masks").iterdir():
                self.assertEqual(mask.read_bytes(), (root / "b/masks" / mask.name).read_bytes())
            with self.assertRaisesRegex(ValueError, "already exists"):
                teacher.run(root / "replay", root / "a", teacher.Config(), bootstrap=True)


if __name__ == "__main__":
    unittest.main()
