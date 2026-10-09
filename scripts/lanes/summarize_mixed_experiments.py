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
    if set(comparison) != set(ARMS):
        raise ValueError("Incomplete matched arms")
    for arm in ARMS:
        metrics = comparison[arm]
        if (read(path/arm/"config.json") != dict(protocol, arm=arm)
                or read(path/arm/"metrics.json") != metrics
                or sha(path/arm/"auxiliary-marking.pt") != metrics["checkpointSha256"]
                or sha(path/"source-supervision.json") != metrics["sourceSupervisionSha256"]):
            raise ValueError("Finalized arm artifact/provenance mismatch")
        curves = read(path/arm/"curves.json")
        if len(curves) != protocol["epochs"] or [r["epoch"] for r in curves] != list(range(1, protocol["epochs"]+1)):
            raise ValueError("Missing training epochs")
        selected = max(curves, key=lambda row: row["validation"]["marking"]["iou"])
        if selected["epoch"] != metrics["bestEpoch"] or selected["validation"] != metrics["validation"]:
            raise ValueError("Selection differs from earliest maximum A2D2 validation IoU")
        updates = protocol["epochs"] * protocol["stepsPerEpoch"]
        exposures = updates * protocol["batchSize"]
        expected = {"A2D2": exposures} if arm == "a2d2" else {"A2D2": exposures//2, "ZOD": exposures//2}
        if metrics["optimizerUpdates"] != updates or metrics["sourceFrameExposures"] != expected:
            raise ValueError("Matched update/exposure budget mismatch")
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


def summarize_runs(runs, expected_seeds, bootstrap_draws=2000, bootstrap_seed=20261009):
    if len(expected_seeds) < 2 or len(set(expected_seeds)) != len(expected_seeds) or not 100 <= bootstrap_draws <= 100000:
        raise ValueError("Require distinct predeclared seeds and 100..100000 bootstrap draws")
    loaded = [(Path(p), *load_run(p)) for p in runs]
    seeds = [p["seed"] for _, p, _ in loaded]
    if len(seeds) != len(expected_seeds) or set(seeds) != set(expected_seeds):
        raise ValueError("Require exactly all predeclared seeds; no duplicates or favorable subset")
    loaded.sort(key=lambda row: row[1]["seed"])
    first = loaded[0][1]
    for _, protocol, _ in loaded:
        if (any(protocol[k] != first[k] for k in INVARIANTS)
                or runtime_identity(protocol) != runtime_identity(first)):
            raise ValueError("Source/model/protocol differs across seeds")
    source_splits = set(loaded[0][2][ARMS[0]]["evaluation"])
    if any(set(c[arm]["evaluation"]) != source_splits for _, _, c in loaded for arm in ARMS):
        raise ValueError("Evaluation partitions differ across arms/seeds")
    output = dict(schemaVersion=1, seeds=sorted(seeds), evaluations={},
                  protocol={k: first[k] for k in INVARIANTS}, runtime=runtime_identity(first),
                  runs=[dict(path=str(p.resolve()), seed=config["seed"], comparisonSha256=sha(p/"comparison.json"))
                        for p, config, _ in loaded],
                  bootstrap=dict(draws=bootstrap_draws, seed=bootstrap_seed,
                      method="Paired resampling of complete held-out groups; mean difference across all fixed fitted seeds",
                      interpretation="Conditional descriptive interval; does not cover label error, cohort filtering, seed-population or deployment uncertainty"),
                  qualification="Report all seeds. No model promotion or selected best seed. Previously exposed A2D2 remains descriptive.")
    rng = np.random.default_rng(bootstrap_seed)
    for source_split in sorted(source_splits):
        rows = [[checked_rows(comparison[arm]["evaluation"][source_split], source_split) for arm in ARMS]
                for _, _, comparison in loaded]
        reference = rows[0][0]
        groups = sorted({group for group, _ in reference.values()})
        indices = {group: i for i, group in enumerate(groups)}
        grouped = np.zeros((len(loaded), 2, len(groups), 4), dtype=np.int64)
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
        delta = measured[:, 1] - measured[:, 0]
        per_metric = {}
        samples = None
        if len(groups) >= 8:
            samples = np.empty((bootstrap_draws, len(METRICS)))
            for draw in range(bootstrap_draws):
                sample = rng.integers(0, len(groups), len(groups))
                values = paint_metrics(grouped[:, :, sample, :].sum(axis=2))
                samples[draw] = (values[:, 1] - values[:, 0]).mean(axis=0)
        for i, metric in enumerate(METRICS):
            per_metric[metric] = dict(baselineMean=float(measured[:, 0, i].mean()),
                mixedMean=float(measured[:, 1, i].mean()), pairedDeltaMean=float(delta[:, i].mean()),
                pairedDeltaStd=float(delta[:, i].std(ddof=1)),
                pairedDeltaMin=float(delta[:, i].min()), pairedDeltaMax=float(delta[:, i].max()),
                pairedGroupBootstrap95=None if samples is None else np.quantile(samples[:, i], [.025, .975]).tolist())
        output["evaluations"][source_split] = dict(frames=len(reference), groups=len(groups),
            metrics=per_metric, groupIntervalAvailable=samples is not None,
            bySeed=[dict(seed=entry[1]["seed"], baseline=dict(zip(METRICS, measured[i, 0].tolist())),
                         mixed=dict(zip(METRICS, measured[i, 1].tolist())), delta=dict(zip(METRICS, delta[i].tolist())))
                    for i, entry in enumerate(loaded)])
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
