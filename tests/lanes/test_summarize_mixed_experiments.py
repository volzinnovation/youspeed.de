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


def three_arm_fixture(root, seed):
    """Two blank and six positive scenes, with final validation worse than epoch1."""
    root.mkdir()
    (root/"trainer.py").write_text("# synthetic frozen trainer\n")
    write(root/"source-supervision.json", {})
    write(root/"a2d2-manifest.json", dict(pairs=[dict(rgb=f"a{i}", capture_date="train", split="train") for i in range(2)]))
    write(root/"zod-manifest.json", dict(pairs=[dict(frame_id=f"z{i}", group_id="train", split="train") for i in range(4)] +
        [dict(frame_id=f"{i:06d}", group_id=f"group-{i}", split="test",
              statistics=dict(training_input_size=32, training_input_positive_pixels=0 if i < 2 else 20,
                              training_input_valid_pixels=100)) for i in range(8)]))
    arms = ["a2d2", "zod", "a2d2_zod"]
    exposures = {"a2d2": {"A2D2": 16}, "zod": {"ZOD": 16}, "a2d2_zod": {"A2D2": 8, "ZOD": 8}}
    populations = {"A2D2": 2, "ZOD": 4}
    protocol = {key: "same" for key in summary.INVARIANTS}
    protocol.update(seed=seed, arms=arms, selectionPolicy="final-epoch",
        selection="Final epoch; A2D2 validation diagnostics only; threshold0.5",
        inputSize=32, threshold=.5, epochs=2, stepsPerEpoch=2, batchSize=4, detectorSha256="detector",
        execution=dict(seed=seed, torchVersion="fixture", environment={"PYTHONHASHSEED": str(seed)}),
        splitCounts={"A2D2": dict(train=2, validation=0, test=0), "ZOD": dict(train=4, validation=0, test=8)},
        holdoutFrameCounts=True, sourceCodeSha256={"trainer.py": summary.sha(root/"trainer.py")},
        sourceManifestSha256={key: summary.sha(root/(key.lower()+"-manifest.json")) for key in populations},
        computeBudget=dict(optimizerUpdatesPerArm=4, frameExposuresPerArm=16, trainingFramesPerSource=populations,
            sourceFrameExposuresByArm=exposures,
            meanExposuresPerTrainingFrameByArm={arm: {source: count/populations[source] for source,count in counts.items()}
                                              for arm,counts in exposures.items()},
            selectionEvaluationsPerArm=0, diagnosticValidationEvaluationsPerArm=2))
    write(root/"protocol.json", protocol)
    write(root/"detector-preservation.json", dict(stateIdentical=True, probeEqual=True, allParametersFrozen=True,
        allModulesEval=True, stateHashBefore="state", stateHashAfter="state", checkpointHashBefore="detector",
        checkpointHashAfter="detector", probeMaxAbsDifference=0))
    comparison = {}
    offset = seed//10-1
    for a,arm in enumerate(arms):
        out=root/arm;out.mkdir();(out/"auxiliary-marking.pt").write_bytes(b"synthetic checkpoint")
        rows=[]
        for i in range(8):
            positive=0 if i < 2 else 20
            tp=0 if not positive else 5+3*a+i%2+offset
            fp=((a+1)*(i+1)+offset if i < 2 else 2+a+i%3+offset)
            if i==0 and a==0:fp=0
            rows.append(dict(dataset="ZOD", split="test", frame_id=f"{i:06d}", group_id=f"group-{i}",
                             counts=dict(tp=tp,fp=fp,fn=positive-tp,tn=100-positive-fp)))
        counts={key:sum(row["counts"][key] for row in rows) for key in summary.COUNT_KEYS}
        evaluation=dict(frames=8,frameCounts=rows,counts=counts,
            marking=dict(zip(summary.METRICS,summary.paint_metrics([counts[key] for key in summary.COUNT_KEYS]).tolist())))
        distributions={}
        for source,n in populations.items():
            count=exposures[arm].get(source,0)//n
            distributions[source]=dict(trainingFrames=n,sampledFrames=n if count else 0,neverSampledFrames=0 if count else n,
                                       minimum=count,maximum=count,mean=float(count),histogram={str(count):n})
        validation=dict(marking=dict(iou=.1))
        metrics=dict(bestEpoch=2,validation=validation,optimizerUpdates=4,sourceFrameExposures=exposures[arm],
            uniqueSourceFrames={source:populations[source] for source in exposures[arm]},
            sourceFrameExposureDistribution=distributions,checkpointSha256=summary.sha(out/"auxiliary-marking.pt"),
            sourceSupervisionSha256=summary.sha(root/"source-supervision.json"),evaluation={"ZOD/test":evaluation})
        write(out/"config.json",dict(protocol,arm=arm))
        write(out/"curves.json",[dict(epoch=1,validation=dict(marking=dict(iou=.9))),dict(epoch=2,validation=validation)])
        write(out/"metrics.json",metrics);comparison[arm]=metrics
    write(root/"comparison.json",comparison)
    return root


def update_protocol(path, mutation):
    protocol=summary.read(path/"protocol.json")
    mutation(protocol)
    write(path/"protocol.json",protocol)
    for arm in protocol["arms"]:
        write(path/arm/"config.json",dict(protocol,arm=arm))


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


class ThreeArmSummaryTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.root=Path(self.temp.name)
        self.runs=[three_arm_fixture(self.root/str(seed),seed) for seed in (10,20,30)]

    def tearDown(self):self.temp.cleanup()

    def summarize(self):return summary.summarize_runs(self.runs,[10,20,30],100)

    def test_three_arms_final_epoch_and_known_pooled_counts(self):
        result=self.summarize();data=result["evaluations"]["ZOD/test"]
        self.assertEqual(result["schemaVersion"],2)
        self.assertEqual(result["selectionPolicy"],"final-epoch")
        self.assertEqual(set(data["arms"]),{"a2d2","zod","a2d2_zod"})
        self.assertEqual(set(data["contrasts"]),{"zod-a2d2","a2d2_zod-a2d2","a2d2_zod-zod"})
        # First synthetic seed: TP=33, FP=20, GT positive=120 for baseline.
        observed=data["bySeed"][0]["arms"]["a2d2"]
        self.assertAlmostEqual(observed["precision"],33/53)
        self.assertAlmostEqual(observed["recall"],33/120)
        self.assertAlmostEqual(observed["f1"],66/173)
        self.assertAlmostEqual(observed["iou"],33/140)
        for arm in result["arms"]:
            values=[row["arms"][arm]["iou"] for row in data["bySeed"]]
            self.assertEqual(data["arms"][arm]["iou"],dict(mean=sum(values)/3,minimum=min(values),maximum=max(values)))
        self.assertEqual(result,self.summarize())

    def test_ground_truth_subsets_and_false_positive_ranges(self):
        details=self.summarize()["evaluations"]["ZOD/test"]["sceneBreakdown"]
        self.assertEqual((details["negativeFrames"],details["positiveFrames"]),(2,6))
        self.assertEqual(details["negativeFrameIds"],["000000","000001"])
        baseline=details["arms"]["a2d2"]
        self.assertEqual(baseline["negativeFramesWithAnyFP"],dict(mean=1.,minimum=1.,maximum=1.))
        self.assertEqual(baseline["negativeFPPixels"],dict(mean=3.,minimum=2.,maximum=4.))
        self.assertEqual(baseline["negativePixelFPR"],dict(mean=.015,minimum=.01,maximum=.02))
        self.assertEqual(details["arms"]["a2d2_zod"]["negativeFPPixels"],dict(mean=11.,minimum=9.,maximum=13.))
        self.assertIn("no bootstrap",details["qualification"].lower())

    def test_pairwise_intervals_share_independent_scalar_resamples(self):
        result=self.summarize()["evaluations"]["ZOD/test"]
        rng=summary.np.random.default_rng(20261009)
        draws=[rng.integers(0,8,8).tolist() for _ in range(100)]
        files=[summary.read(path/"comparison.json") for path in self.runs]
        def iou(comparison,arm,draw):
            rows=comparison[arm]["evaluation"]["ZOD/test"]["frameCounts"]
            tp=sum(rows[i]["counts"]["tp"] for i in draw)
            fp=sum(rows[i]["counts"]["fp"] for i in draw)
            fn=sum(rows[i]["counts"]["fn"] for i in draw)
            return tp/(tp+fp+fn)
        for key,contrast in result["contrasts"].items():
            left,right=contrast["differenceArm"],contrast["referenceArm"]
            samples=[sum(iou(file,left,draw)-iou(file,right,draw) for file in files)/3 for draw in draws]
            expected=summary.np.quantile(samples,[.025,.975]).tolist()
            self.assertEqual(contrast["metrics"]["iou"]["pairedGroupBootstrap95"],expected,key)

    def test_final_epoch_rejects_better_early_validation_checkpoint(self):
        mutate_metrics(self.runs[0],"zod",lambda m:m.update(bestEpoch=1,validation=dict(marking=dict(iou=.9))))
        with self.assertRaisesRegex(ValueError,"final epoch"):self.summarize()

    def test_wrong_arm_set_is_rejected(self):
        comparison=summary.read(self.runs[0]/"comparison.json");comparison.pop("zod")
        write(self.runs[0]/"comparison.json",comparison)
        with self.assertRaisesRegex(ValueError,"matched arms"):self.summarize()

    def test_unused_a2d2_exposures_in_zod_arm_are_rejected(self):
        def change(metrics):
            metrics["sourceFrameExposureDistribution"]["A2D2"].update(histogram={"0":1,"1":1},
                sampledFrames=1,neverSampledFrames=1,minimum=0,maximum=1,mean=.5)
        mutate_metrics(self.runs[0],"zod",change)
        with self.assertRaisesRegex(ValueError,"exposure distribution"):self.summarize()

    def test_declared_wrong_zod_optimizer_budget_is_rejected(self):
        update_protocol(self.runs[0],lambda p:p["computeBudget"]["sourceFrameExposuresByArm"]["zod"].update(A2D2=16))
        with self.assertRaisesRegex(ValueError,"compute budget"):self.summarize()

    def test_missing_distribution_or_wrong_unique_counts_is_rejected(self):
        for mutation in (lambda m:m.pop("sourceFrameExposureDistribution"),lambda m:m["uniqueSourceFrames"].update(A2D2=1)):
            with self.subTest(mutation=mutation):
                path=three_arm_fixture(self.root/("extra-"+str(len(list(self.root.iterdir())))),10)
                mutate_metrics(path,"zod",mutation)
                with self.assertRaisesRegex(ValueError,"exposure distributions|Unique sampled"):
                    summary.load_run(path)

    def test_selection_policies_cannot_be_pooled(self):
        def change(p):
            p["selectionPolicy"]="a2d2-validation"
            p["selection"]="Maximum A2D2 validation paint IoU, threshold0.5, earliest tie, both arms"
            p["computeBudget"]["selectionEvaluationsPerArm"]=2
            del p["computeBudget"]["diagnosticValidationEvaluationsPerArm"]
        update_protocol(self.runs[1],change)
        for arm in summary.AVAILABLE_ARMS:
            mutate_metrics(self.runs[1],arm,lambda m:m.update(bestEpoch=1,validation=dict(marking=dict(iou=.9))))
        with self.assertRaisesRegex(ValueError,"protocol differs"):self.summarize()

    def test_declared_arm_orders_cannot_be_pooled(self):
        update_protocol(self.runs[1],lambda p:p["arms"].reverse())
        with self.assertRaisesRegex(ValueError,"protocol differs"):self.summarize()

    def test_no_negative_subset_reports_null_rate(self):
        # Legacy fixtures have only positive GT, so incidence has no denominator.
        runs=[fixture(self.root/f"positive-{seed}",seed) for seed in (10,20)]
        details=summary.summarize_runs(runs,[10,20],100)["evaluations"]["ZOD/test"]["sceneBreakdown"]
        self.assertEqual(details["negativeFrames"],0)
        self.assertIsNone(details["arms"]["a2d2"]["negativePixelFPR"]["mean"])


if __name__ == "__main__":
    unittest.main()
