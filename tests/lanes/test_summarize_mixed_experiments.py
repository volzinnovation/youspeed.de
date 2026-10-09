import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

SPEC = importlib.util.spec_from_file_location("lane_summary", Path(__file__).parents[2] / "scripts/lanes/summarize_mixed_experiments.py")
summary = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(summary)


def write(path, value):
    path.write_text(json.dumps(value))


def fixture(root, seed, groups=8):
    root.mkdir()
    for name in ("a2d2-manifest.json", "zod-manifest.json", "trainer.py", "source-supervision.json"):
        (root/name).write_text('{}')
    write(root/"a2d2-manifest.json", dict(pairs=[]))
    write(root/"zod-manifest.json", dict(pairs=[dict(frame_id=f"{i:06d}", group_id=f"group-{i}", split="test",
          statistics=dict(training_input_size=32, training_input_positive_pixels=15, training_input_valid_pixels=118)) for i in range(groups)]))
    protocol = {key: "same" for key in summary.INVARIANTS}
    protocol.update(seed=seed, inputSize=32, epochs=2, stepsPerEpoch=1, batchSize=2, detectorSha256="detector",
                    execution=dict(seed=seed, torchVersion="fixture", environment={"PYTHONHASHSEED": str(seed)}),
                    splitCounts={"A2D2": dict(train=0, validation=0, test=0), "ZOD": dict(train=0, validation=0, test=groups)},
                    holdoutFrameCounts=True, sourceCodeSha256={"trainer.py": summary.sha(root/"trainer.py")},
                    sourceManifestSha256={key: summary.sha(root/(key.lower()+"-manifest.json")) for key in ("A2D2", "ZOD")})
    write(root/"protocol.json", protocol)
    proof = dict(stateIdentical=True, probeEqual=True, allParametersFrozen=True, allModulesEval=True,
                 stateHashBefore="state", stateHashAfter="state", checkpointHashBefore="detector",
                 checkpointHashAfter="detector", probeMaxAbsDifference=0)
    write(root/"detector-preservation.json", proof)
    comparison = {}
    for arm_index, arm in enumerate(summary.ARMS):
        out = root/arm
        out.mkdir()
        (out/"auxiliary-marking.pt").write_bytes(b"fixture checkpoint")
        rows = []
        for i in range(groups):
            tp = 5+i % 3+arm_index
            counts = dict(tp=tp, fp=3-arm_index, fn=15-tp, tn=100+arm_index)
            rows.append(dict(dataset="ZOD", split="test", frame_id=f"{i:06d}", group_id=f"group-{i}", group_kind="group_id", counts=counts))
        total = {k: sum(r["counts"][k] for r in rows) for k in summary.COUNT_KEYS}
        evaluation = dict(frames=len(rows), frameCounts=rows, counts=total,
                          marking=dict(zip(summary.METRICS, summary.paint_metrics(list(total.values())).tolist())))
        validation = dict(marking=dict(iou=.1))
        metrics = dict(bestEpoch=1, validation=validation, optimizerUpdates=2,
                       sourceFrameExposures={"A2D2": 4} if arm_index == 0 else {"A2D2": 2, "ZOD": 2},
                       checkpointSha256=summary.sha(out/"auxiliary-marking.pt"),
                       sourceSupervisionSha256=summary.sha(root/"source-supervision.json"), evaluation={"ZOD/test": evaluation})
        write(out/"config.json", dict(protocol, arm=arm))
        write(out/"curves.json", [dict(epoch=i, validation=validation) for i in (1, 2)])
        write(out/"metrics.json", metrics)
        comparison[arm] = metrics
    write(root/"comparison.json", comparison)
    return root


def mutate_metrics(path, arm, mutation):
    comparison = summary.read(path/"comparison.json")
    mutation(comparison[arm])
    write(path/arm/"metrics.json", comparison[arm])
    write(path/"comparison.json", comparison)


class SummaryTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.runs = [fixture(self.root/str(seed), seed) for seed in (10, 20)]

    def tearDown(self):
        self.temp.cleanup()

    def summarize(self):
        return summary.summarize_runs(self.runs, [10, 20], 100)

    def test_all_seeds_paired_group_interval_and_deterministic_output(self):
        result = self.summarize()
        data = result["evaluations"]["ZOD/test"]
        self.assertEqual(result["seeds"], [10, 20])
        self.assertEqual((data["frames"], data["groups"]), (8, 8))
        self.assertGreater(data["metrics"]["iou"]["pairedDeltaMean"], 0)
        self.assertEqual(data["metrics"]["iou"]["pairedDeltaStd"], 0)
        self.assertGreater(data["metrics"]["iou"]["pairedGroupBootstrap95"][0], 0)
        self.assertEqual(result, self.summarize())

    def test_missing_seed_or_duplicate_run_is_rejected(self):
        for runs in (self.runs[:1], [self.runs[0], self.runs[0]]):
            with self.assertRaisesRegex(ValueError, "predeclared seeds"):
                summary.summarize_runs(runs, [10, 20], 100)

    def test_selection_must_use_earliest_tie(self):
        mutate_metrics(self.runs[0], "a2d2", lambda m: m.update(bestEpoch=2))
        with self.assertRaisesRegex(ValueError, "earliest maximum"):
            self.summarize()

    def test_checkpoint_tampering_is_rejected(self):
        (self.runs[0]/"a2d2/auxiliary-marking.pt").write_bytes(b"changed")
        with self.assertRaisesRegex(ValueError, "artifact/provenance"):
            self.summarize()

    def test_confusion_rows_must_sum_to_published_counts(self):
        mutate_metrics(self.runs[0], "a2d2", lambda m: m["evaluation"]["ZOD/test"]["frameCounts"][0]["counts"].update(tp=99))
        with self.assertRaisesRegex(ValueError, "sum to aggregate"):
            self.summarize()

    def test_truth_or_validity_must_match_between_arms(self):
        def mutate(m):
            e = m["evaluation"]["ZOD/test"]
            e["frameCounts"][0]["counts"]["fn"] += 1
            e["counts"]["fn"] += 1
            e["marking"] = dict(zip(summary.METRICS, summary.paint_metrics([e["counts"][k] for k in summary.COUNT_KEYS]).tolist()))
        mutate_metrics(self.runs[0], "a2d2_zod", mutate)
        with self.assertRaisesRegex(ValueError, "truth/validity"):
            self.summarize()

    def test_changed_detector_proof_is_rejected(self):
        p = self.runs[0]/"detector-preservation.json"
        d = summary.read(p)
        d["probeEqual"] = False
        write(p, d)
        with self.assertRaisesRegex(ValueError, "preservation"):
            self.summarize()

    def test_changed_protocol_is_not_pooled(self):
        p = self.runs[1]/"protocol.json"
        d = summary.read(p)
        d["threshold"] = .6
        write(p, d)
        for arm in summary.ARMS:
            write(self.runs[1]/arm/"config.json", dict(d, arm=arm))
        with self.assertRaisesRegex(ValueError, "protocol differs"):
            self.summarize()

    def test_too_few_groups_does_not_produce_interval(self):
        runs = [fixture(self.root/f"small-{s}", s, groups=2) for s in (10, 20)]
        result = summary.summarize_runs(runs, [10, 20], 100)
        self.assertIsNone(result["evaluations"]["ZOD/test"]["metrics"]["iou"]["pairedGroupBootstrap95"])

    def test_different_runtime_is_not_pooled(self):
        p = self.runs[1]/"protocol.json"
        d = summary.read(p)
        d["execution"]["torchVersion"] = "different"
        write(p, d)
        for arm in summary.ARMS:
            write(self.runs[1]/arm/"config.json", dict(d, arm=arm))
        with self.assertRaisesRegex(ValueError, "protocol differs"):
            self.summarize()

    def test_unanimously_changed_group_ids_are_rejected(self):
        for run in self.runs:
            for arm in summary.ARMS:
                mutate_metrics(run, arm, lambda m: m["evaluation"]["ZOD/test"]["frameCounts"][0].update(group_id="invented-group"))
        with self.assertRaisesRegex(ValueError, "held-out manifest"):
            self.summarize()

    def test_unanimously_missing_frame_is_rejected(self):
        def drop(m):
            e = m["evaluation"]["ZOD/test"]
            dropped = e["frameCounts"].pop()
            e["frames"] -= 1
            for key in summary.COUNT_KEYS:
                e["counts"][key] -= dropped["counts"][key]
            e["marking"] = dict(zip(summary.METRICS, summary.paint_metrics([e["counts"][k] for k in summary.COUNT_KEYS]).tolist()))
        for run in self.runs:
            for arm in summary.ARMS:
                mutate_metrics(run, arm, drop)
        with self.assertRaisesRegex(ValueError, "held-out manifest"):
            self.summarize()


if __name__ == "__main__":
    unittest.main()
