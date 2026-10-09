#!/usr/bin/env python3
"""Summarize every predeclared seed of a completed matched lane experiment.

Paired group bootstrap intervals condition on the fitted seeds and the retained
source cohort. They do not include annotation error, data filtering or deployment
uncertainty. No checkpoint, threshold or favorable seed is selected here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

ARMS = ("a2d2", "a2d2_zod")
AVAILABLE_ARMS = ("a2d2", "zod", "a2d2_zod")
COUNT_KEYS = ("tp", "fp", "fn", "tn")
METRICS = ("precision", "recall", "f1", "iou")
INVARIANTS = ("inputSize", "threshold", "featureLayers", "featureChannels",
              "hiddenChannels", "headParameters", "detectorSha256", "epochs",
              "stepsPerEpoch", "batchSize", "positiveWeight", "selection",
              "sampling", "loss", "transform", "sourceManifestSha256",
              "sourceCodeSha256", "splitCounts", "holdoutFrameCounts",
              "computeBudget", "featureCache")


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def experiment_identity(protocol):
    """Older two-arm artifacts predate explicit arm and selection declarations."""
    explicit = "arms" in protocol or "selectionPolicy" in protocol
    arms = protocol.get("arms", list(ARMS))
    policy = protocol.get("selectionPolicy", "a2d2-validation")
    if (not isinstance(arms, list) or not 2 <= len(arms) <= len(AVAILABLE_ARMS)
            or any(arm not in AVAILABLE_ARMS for arm in arms) or len(set(arms)) != len(arms)
            or policy not in ("a2d2-validation", "final-epoch")
            or (explicit and not {"arms", "selectionPolicy"} <= protocol.keys())):
        raise ValueError("Invalid declared arms or selection policy")
    return tuple(arms), policy


def expected_exposures(arm, frames):
    if arm == "a2d2":
        return {"A2D2": frames}
    if arm == "zod":
        return {"ZOD": frames}
    return {"A2D2": frames//2, "ZOD": frames//2}


def checked_exposures(protocol, metrics, arm):
    updates = protocol["epochs"] * protocol["stepsPerEpoch"]
    frames = updates * protocol["batchSize"]
    expected = expected_exposures(arm, frames)
    if metrics["optimizerUpdates"] != updates or metrics["sourceFrameExposures"] != expected:
        raise ValueError("Matched update/exposure budget mismatch")
    distribution = metrics.get("sourceFrameExposureDistribution")
    # Preserve support for legacy artifacts without the later sampling audit.
    if distribution is None and "arms" not in protocol:
        return
    if not isinstance(distribution, dict) or set(distribution) != {"A2D2", "ZOD"}:
        raise ValueError("Missing complete source exposure distributions")
    sampled = {}
    for source, observed in distribution.items():
        population = protocol["splitCounts"][source]["train"]
        histogram = observed.get("histogram", {})
        if (not histogram or any(not isinstance(k, str) or not k.isascii() or not k.isdecimal()
                or str(int(k)) != k or type(v) is not int or v <= 0 for k, v in histogram.items())):
            raise ValueError("Invalid source exposure histogram")
        histogram = {int(k): v for k, v in histogram.items()}
        total = sum(count * frequency for count, frequency in histogram.items())
        used = sum(frequency for count, frequency in histogram.items() if count > 0)
        if (population <= 0 or sum(histogram.values()) != population
                or total != expected.get(source, 0)
                or observed.get("trainingFrames") != population or observed.get("sampledFrames") != used
                or observed.get("neverSampledFrames") != histogram.get(0, 0)
                or observed.get("minimum") != min(histogram) or observed.get("maximum") != max(histogram)
                or observed.get("mean") != total/population):
            raise ValueError("Source exposure distribution differs from population/budget")
        if used:
            sampled[source] = used
    if metrics.get("uniqueSourceFrames") != sampled:
        raise ValueError("Unique sampled source frames differ from exposure distributions")


def checked_budget(protocol, arms, policy):
    if "arms" not in protocol:
        return
    budget = protocol["computeBudget"]
    updates = protocol["epochs"] * protocol["stepsPerEpoch"]
    frames = updates * protocol["batchSize"]
    populations = {name: protocol["splitCounts"][name]["train"] for name in ("A2D2", "ZOD")}
    if any(type(count) is not int or count <= 0 for count in populations.values()):
        raise ValueError("Declared training populations must be positive")
    exposures = {arm: expected_exposures(arm, frames) for arm in arms}
    means = {arm: {source: count/populations[source] for source, count in counts.items()}
             for arm, counts in exposures.items()}
    if (budget.get("optimizerUpdatesPerArm") != updates or budget.get("frameExposuresPerArm") != frames
            or budget.get("trainingFramesPerSource") != populations
            or budget.get("sourceFrameExposuresByArm") != exposures
            or budget.get("meanExposuresPerTrainingFrameByArm") != means
            or budget.get("selectionEvaluationsPerArm") != (0 if policy == "final-epoch" else protocol["epochs"])
            or (policy == "final-epoch" and budget.get("diagnosticValidationEvaluationsPerArm") != protocol["epochs"])):
        raise ValueError("Declared arm/selection compute budget differs")


def runtime_identity(protocol):
    runtime = json.loads(json.dumps(protocol["execution"]))
    runtime.pop("seed", None)
    runtime.get("environment", {}).pop("PYTHONHASHSEED", None)
    # Initialization depends on seed; a synthetic loss may legitimately differ.
    runtime.get("trainingPreflight", {}).pop("loss", None)
    return runtime


def paint_metrics(counts):
    tp, fp, fn, _ = np.moveaxis(np.asarray(counts, dtype=np.float64), -1, 0)
    return np.stack((tp / np.maximum(1, tp+fp), tp / np.maximum(1, tp+fn),
                     2*tp / np.maximum(1, 2*tp+fp+fn), tp / np.maximum(1, tp+fp+fn)), axis=-1)


def checked_rows(evaluation, source_split):
    rows = evaluation.get("frameCounts")
    if not rows or len(rows) != evaluation["frames"]:
        raise ValueError("Missing complete held-out frame counts")
    identities, result = set(), {}
    for row in rows:
        frame, group = row["frame_id"], row["group_id"]
        if (not isinstance(frame, str) or not frame or frame in identities
                or not isinstance(group, str) or not group
                or row["dataset"] + "/" + row["split"] != source_split):
            raise ValueError("Invalid or duplicate held-out identity")
        counts = row["counts"]
        if set(counts) != set(COUNT_KEYS) or any(type(counts[k]) is not int or counts[k] < 0 for k in COUNT_KEYS):
            raise ValueError("Confusion counts must be nonnegative integers")
        identities.add(frame)
        result[frame] = (group, tuple(counts[k] for k in COUNT_KEYS))
    total = np.array([value[1] for value in result.values()], dtype=np.int64).sum(axis=0)
    if dict(zip(COUNT_KEYS, map(int, total))) != evaluation["counts"]:
        raise ValueError("Frame counts do not sum to aggregate counts")
    if not np.allclose(paint_metrics(total), [evaluation["marking"][k] for k in METRICS], rtol=0, atol=1e-12):
        raise ValueError("Reported paint metrics disagree with confusion counts")
    return result


def load_run(path):
    path = Path(path)
    protocol, comparison, proof = (read(path/name) for name in
        ("protocol.json", "comparison.json", "detector-preservation.json"))
    arms, policy = experiment_identity(protocol)
    checked_budget(protocol, arms, policy)
    required = ("stateIdentical", "probeEqual", "allParametersFrozen", "allModulesEval")
    if (not all(proof.get(k) is True for k in required)
            or proof["stateHashBefore"] != proof["stateHashAfter"]
            or proof["checkpointHashBefore"] != proof["checkpointHashAfter"]
            or proof["checkpointHashBefore"] != protocol["detectorSha256"]
            or proof["probeMaxAbsDifference"] != 0):
        raise ValueError("Invalid frozen detector preservation proof")
    expected_rows = {}
    for source in ("A2D2", "ZOD"):
        manifest_path = path/(source.lower()+"-manifest.json")
        if sha(manifest_path) != protocol["sourceManifestSha256"][source]:
            raise ValueError("Source manifest hash mismatch")
        pairs = read(manifest_path)["pairs"]
        split_counts = {split: sum(row["split"] == split for row in pairs) for split in ("train", "validation", "test")}
        if split_counts != protocol["splitCounts"][source]:
            raise ValueError("Manifest populations differ from declared split counts")
        for split in ("validation", "test"):
            if (source == "A2D2" and split == "validation") or not split_counts[split]:
                continue
            frame_key, group_key = ("rgb", "capture_date") if source == "A2D2" else ("frame_id", "group_id")
            selected = [row for row in pairs if row["split"] == split]
            expected = {row[frame_key]: row for row in selected}
            if len(expected) != len(selected):
                raise ValueError("Duplicate held-out manifest identity")
            expected_rows[source+"/"+split] = (expected, group_key)
    for name, digest in protocol["sourceCodeSha256"].items():
        if Path(name).name != name or sha(path/name) != digest:
            raise ValueError("Saved trainer source hash mismatch")
    if set(comparison) != set(arms):
        raise ValueError("Incomplete matched arms")
    for arm in arms:
        metrics = comparison[arm]
        if (read(path/arm/"config.json") != dict(protocol, arm=arm)
                or read(path/arm/"metrics.json") != metrics
                or sha(path/arm/"auxiliary-marking.pt") != metrics["checkpointSha256"]
                or sha(path/"source-supervision.json") != metrics["sourceSupervisionSha256"]):
            raise ValueError("Finalized arm artifact/provenance mismatch")
        curves = read(path/arm/"curves.json")
        if len(curves) != protocol["epochs"] or [r["epoch"] for r in curves] != list(range(1, protocol["epochs"]+1)):
            raise ValueError("Missing training epochs")
        selected = curves[-1] if policy == "final-epoch" else max(curves, key=lambda row: row["validation"]["marking"]["iou"])
        if selected["epoch"] != metrics["bestEpoch"] or selected["validation"] != metrics["validation"]:
            rule = "declared final epoch" if policy == "final-epoch" else "earliest maximum A2D2 validation IoU"
            raise ValueError("Selection differs from " + rule)
        checked_exposures(protocol, metrics, arm)
        if metrics["evaluation"].keys() != expected_rows.keys():
            raise ValueError("Evaluated partitions differ from held-out manifests")
        for partition, (expected, group_key) in expected_rows.items():
            actual = checked_rows(metrics["evaluation"][partition], partition)
            if actual.keys() != expected.keys() or any(actual[key][0] != row[group_key] for key, row in expected.items()):
                raise ValueError("Evaluated frame/group population differs from held-out manifest")
            for key, row in expected.items():
                stats = row.get("statistics", {})
                if "training_input_size" in stats:
                    counts = actual[key][1]
                    if (stats["training_input_size"] != protocol["inputSize"]
                            or counts[0]+counts[2] != stats["training_input_positive_pixels"]
                            or sum(counts) != stats["training_input_valid_pixels"]):
                        raise ValueError("Evaluated truth/validity differs from source-qualified input pixels")
    return protocol, comparison


def range_summary(values):
    if all(value is None for value in values):
        return dict(mean=None, minimum=None, maximum=None)
    return dict(mean=float(np.mean(values)), minimum=float(min(values)), maximum=float(max(values)))


def scene_breakdown(rows, arms, seeds):
    """GT-only subsets; any FP pixel is descriptive, never a lane-alarm threshold."""
    reference = rows[0][0]
    negative = sorted(frame for frame, (_, counts) in reference.items() if counts[0]+counts[2] == 0)
    positive = sorted(set(reference)-set(negative))
    by_seed = []
    for seed, paired in zip(seeds, rows):
        arm_values = {}
        for arm, current in zip(arms, paired):
            neg = [current[frame][1] for frame in negative]
            pos = [current[frame][1] for frame in positive]
            neg_fp = sum(c[1] for c in neg)
            neg_pixels = sum(c[1]+c[3] for c in neg)
            pos_fp = sum(c[1] for c in pos)
            pos_background = sum(c[1]+c[3] for c in pos)
            any_fp = sum(c[1] > 0 for c in neg)
            arm_values[arm] = dict(negativeFramesWithAnyFP=any_fp,
                negativeFrameAnyFPFraction=any_fp/len(neg) if neg else None,
                negativeFPPixels=neg_fp, negativePixelFPR=neg_fp/neg_pixels if neg_pixels else None,
                positiveFPPixels=pos_fp, positivePixelFPR=pos_fp/pos_background if pos_background else None)
        by_seed.append(dict(seed=seed, arms=arm_values))
    return dict(negativeFrames=len(negative), positiveFrames=len(positive),
        negativeFrameIds=negative, positiveFrameIds=positive,
        negativeValidPixels=sum(reference[frame][1][1]+reference[frame][1][3] for frame in negative),
        positiveBackgroundPixels=sum(reference[frame][1][1]+reference[frame][1][3] for frame in positive),
        definition="Negative iff ground-truth tp+fn=0; positive iff tp+fn>0. Pixel FPR is pooled fp/(fp+tn) within each subset.",
        qualification="Descriptive only, no bootstrap intervals. Any-pixel incidence is sensitive to a single FP pixel; "
                      "it is not a lane-level false-alarm rate. No new FP size cutoff or threshold; no blank-scene F1 averaging.",
        bySeed=by_seed,
        arms={arm: {name: range_summary([row["arms"][arm][name] for row in by_seed])
                    for name in by_seed[0]["arms"][arm]} for arm in arms})


def summarize_runs(runs, expected_seeds, bootstrap_draws=2000, bootstrap_seed=20261009):
    if len(expected_seeds) < 2 or len(set(expected_seeds)) != len(expected_seeds) or not 100 <= bootstrap_draws <= 100000:
        raise ValueError("Require distinct predeclared seeds and 100..100000 bootstrap draws")
    loaded = [(Path(p), *load_run(p)) for p in runs]
    seeds = [p["seed"] for _, p, _ in loaded]
    if len(seeds) != len(expected_seeds) or set(seeds) != set(expected_seeds):
        raise ValueError("Require exactly all predeclared seeds; no duplicates or favorable subset")
    loaded.sort(key=lambda row: row[1]["seed"])
    seeds = [row[1]["seed"] for row in loaded]
    first = loaded[0][1]
    arms, policy = experiment_identity(first)
    for _, protocol, _ in loaded:
        if (any(protocol[k] != first[k] for k in INVARIANTS)
                or experiment_identity(protocol) != (arms, policy)
                or runtime_identity(protocol) != runtime_identity(first)):
            raise ValueError("Source/model/protocol differs across seeds")
    source_splits = set(loaded[0][2][arms[0]]["evaluation"])
    if any(set(c[arm]["evaluation"]) != source_splits for _, _, c in loaded for arm in arms):
        raise ValueError("Evaluation partitions differ across arms/seeds")
    legacy_layout = arms == ARMS
    output = dict(schemaVersion=1 if legacy_layout else 2, seeds=seeds, evaluations={},
                  protocol={k: first[k] for k in INVARIANTS}, runtime=runtime_identity(first),
                  runs=[dict(path=str(p.resolve()), seed=config["seed"], comparisonSha256=sha(p/"comparison.json"))
                        for p, config, _ in loaded],
                  bootstrap=dict(draws=bootstrap_draws, seed=bootstrap_seed,
                      method="Paired resampling of complete held-out groups; mean difference across all fixed fitted seeds; "
                             "the same sampled groups are used for every arm and contrast",
                      interpretation="Conditional descriptive intervals, not adjusted for multiple comparisons; "
                          "do not cover label error, cohort filtering, cross-day spatial correlation, seed-population or deployment uncertainty"),
                  qualification="Report all seeds and arms. No model promotion or selected best seed. "
                      "Previously scored holdouts remain exposed developmental evidence; these summaries cannot establish a fresh evaluation.")
    if "arms" in first:
        output["protocol"].update(arms=list(arms), selectionPolicy=policy)
    if not legacy_layout:
        output.update(arms=list(arms), selectionPolicy=policy)
    # Scientific direction is fixed by source composition, independent of CLI order.
    ordered_arms = [arm for arm in AVAILABLE_ARMS if arm in arms]
    contrasts = [(arms.index(left), arms.index(right)) for i, right in enumerate(ordered_arms)
                 for left in ordered_arms[i+1:]]
    rng = np.random.default_rng(bootstrap_seed)
    for source_split in sorted(source_splits):
        rows = [[checked_rows(comparison[arm]["evaluation"][source_split], source_split) for arm in arms]
                for _, _, comparison in loaded]
        reference = rows[0][0]
        groups = sorted({group for group, _ in reference.values()})
        indices = {group: i for i, group in enumerate(groups)}
        grouped = np.zeros((len(loaded), len(arms), len(groups), 4), dtype=np.int64)
        for seed_index, paired in enumerate(rows):
            for arm_index, current in enumerate(paired):
                if current.keys() != reference.keys():
                    raise ValueError("Held-out frame identities differ across arms/seeds")
                for frame, (group, counts) in current.items():
                    ref_group, truth = reference[frame]
                    if (group != ref_group or counts[0]+counts[2] != truth[0]+truth[2]
                            or counts[1]+counts[3] != truth[1]+truth[3]):
                        raise ValueError("Held-out group/truth/validity differs across arms/seeds")
                    grouped[seed_index, arm_index, indices[group]] += counts
        measured = paint_metrics(grouped.sum(axis=2))
        deltas = np.stack([measured[:, left]-measured[:, right] for left, right in contrasts], axis=1)
        samples = None
        if len(groups) >= 8:
            samples = np.empty((bootstrap_draws, len(contrasts), len(METRICS)))
            for draw in range(bootstrap_draws):
                sample = rng.integers(0, len(groups), len(groups))
                values = paint_metrics(grouped[:, :, sample, :].sum(axis=2))
                for contrast, (left, right) in enumerate(contrasts):
                    samples[draw, contrast] = (values[:, left]-values[:, right]).mean(axis=0)
        comparison_metrics = []
        for contrast in range(len(contrasts)):
            comparison_metrics.append({metric: dict(pairedDeltaMean=float(deltas[:, contrast, i].mean()),
                pairedDeltaStd=float(deltas[:, contrast, i].std(ddof=1)),
                pairedDeltaMin=float(deltas[:, contrast, i].min()), pairedDeltaMax=float(deltas[:, contrast, i].max()),
                pairedGroupBootstrap95=None if samples is None else np.quantile(samples[:, contrast, i], [.025, .975]).tolist())
                for i, metric in enumerate(METRICS)})
        evaluation = dict(frames=len(reference), groups=len(groups), groupIntervalAvailable=samples is not None,
                          sceneBreakdown=scene_breakdown(rows, arms, seeds))
        if legacy_layout:
            # Keep the schema-1 keys and calculation order for existing consumers.
            evaluation["metrics"] = {metric: dict(baselineMean=float(measured[:, 0, i].mean()),
                mixedMean=float(measured[:, 1, i].mean()), **comparison_metrics[0][metric])
                for i, metric in enumerate(METRICS)}
            evaluation["bySeed"] = [dict(seed=seed, baseline=dict(zip(METRICS, measured[i, 0].tolist())),
                mixed=dict(zip(METRICS, measured[i, 1].tolist())), delta=dict(zip(METRICS, deltas[i, 0].tolist())))
                for i, seed in enumerate(seeds)]
        else:
            evaluation["arms"] = {arm: {metric: range_summary(measured[:, a, i].tolist())
                                         for i, metric in enumerate(METRICS)} for a, arm in enumerate(arms)}
            evaluation["bySeed"] = [dict(seed=seed, arms={arm: dict(zip(METRICS, measured[i, a].tolist()))
                                                        for a, arm in enumerate(arms)}) for i, seed in enumerate(seeds)]
            evaluation["contrasts"] = {arms[left]+"-"+arms[right]: dict(differenceArm=arms[left], referenceArm=arms[right],
                metrics=comparison_metrics[contrast], bySeed=[dict(seed=seed, delta=dict(zip(METRICS, deltas[i, contrast].tolist())))
                                                             for i, seed in enumerate(seeds)])
                for contrast, (left, right) in enumerate(contrasts)}
        output["evaluations"][source_split] = evaluation
    return output


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run", type=Path, action="append", required=True)
    parser.add_argument("--expected-seeds", type=int, nargs="+", required=True)
    parser.add_argument("--bootstrap-draws", type=int, default=2000)
    parser.add_argument("--bootstrap-seed", type=int, default=20261009)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Preserve summaries: choose a new output file")
    result = summarize_runs(args.run, args.expected_seeds, args.bootstrap_draws, args.bootstrap_seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, sort_keys=True, allow_nan=False)+"\n")
    print(json.dumps(dict(output=str(args.output), seeds=result["seeds"])))


if __name__ == "__main__":
    main()
