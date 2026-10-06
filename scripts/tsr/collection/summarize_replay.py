#!/usr/bin/env python3
"""Compare first-frame crops with later native-resolution samples, using sign area.

Pixel area measures available sign detail, not sharpness or recognition accuracy.
Timing is an unpaced Mac replay measurement, not phone CPU/battery/thermal cost.
"""
import argparse
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path


def area(crop):
    x0, y0, x1, y1 = crop["original_box"]
    return (x1 - x0) * (y1 - y0)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path)
    args = parser.parse_args()
    report = json.loads(args.report.read_text())
    baseline = [c for c in report["crops"] if c["variant"] == "baseline"]
    sequence = [c for c in report["crops"] if c["variant"] == "sequence"]
    groups = defaultdict(list)
    for crop in sequence:
        groups[crop["observation_id"]].append(crop)
    comparisons, later = [], []
    for first in baseline:
        samples = groups[first["observation_id"]]
        if not samples:
            comparisons.append(dict(observation_id=first["observation_id"], label=first["label"],
                first_file=first["file"], largest_file=None, first_box=first["original_box"],
                largest_box=None, sign_area_ratio=None, samples=0))
            continue
        best = max(samples, key=area)
        later.extend(c for c in samples if c["frame_seconds"] != first["frame_seconds"])
        comparisons.append(dict(observation_id=first["observation_id"], label=first["label"],
            first_file=first["file"], largest_file=best["file"], first_box=first["original_box"],
            largest_box=best["original_box"], sign_area_ratio=area(best) / area(first), samples=len(samples)))
    ratios = [c["sign_area_ratio"] for c in comparisons if c["sign_area_ratio"] is not None]
    metrics = dict(frames=report["frames"], duration_seconds=report["duration_seconds"], interval_seconds=report["interval_seconds"],
        sightings=len(report["sightings"]), baseline_crops=len(baseline), sequence_crops=len(sequence), additional_crops=len(later),
        baseline_bytes=sum(c["byte_length"] for c in baseline), sequence_bytes=sum(c["byte_length"] for c in sequence),
        encounters_with_more_sign_pixels=sum(r > 1 for r in ratios), encounters_with_at_least_1_5x_sign_area=sum(r >= 1.5 for r in ratios),
        comparable_encounters=len(ratios), baseline_encounters_without_sequence_crop=sum(c["samples"] == 0 for c in comparisons),
        median_largest_sign_area_ratio=statistics.median(ratios) if ratios else None,
        maximum_largest_sign_area_ratio=max(ratios, default=None), crops_per_encounter=dict(Counter(len(g) for g in groups.values())),
        replay_wall_seconds=report["wall_seconds"],
        median_additional_crop_ms=statistics.median(c["capture_ms"] for c in later) if later else None,
        additional_crop_wall_ms=sum(c["capture_ms"] for c in later),
        limitations=report["limitations"] + ["Largest sign pixel area is a geometric detail proxy; no sharpness or accuracy conclusion."])
    (args.report.parent / "metrics.json").write_text(json.dumps(metrics, indent=2) + "\n")
    (args.report.parent / "comparisons.json").write_text(json.dumps(comparisons, indent=2) + "\n")
    print(json.dumps(metrics, indent=2))


if __name__ == "__main__":
    main()
