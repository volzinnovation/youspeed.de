#!/usr/bin/env python3
"""Read-only 10/20/30m sign-window counterfactual from logged fixes and a coverage report.

Selection reproduces the iPhone nearest eligible non-speed slot rule. Counts are
candidate states, never claims that a pictogram was painted or seen by a driver.
The source DB and mobile geofence defaults are not edited.
"""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import statistics

from profile_bw_sign_route import angle, distance, load_track, route_segments


def distribution(values):
    values = sorted(values)
    return dict(count=len(values), min_s=min(values) if values else None,
                median_s=statistics.median(values) if values else None,
                max_s=max(values) if values else None,
                under_1s=sum(v < 1 for v in values), under_2s=sum(v < 2 for v in values),
                under_3s=sum(v < 3 for v in values))


def circle_interval(sign, a, b, radius):
    if a["timestamp"] is None or b["timestamp"] is None:
        return None
    scale = math.pi / 180 * 6371008.8
    cosine = math.cos(math.radians(sign["lat"]))
    ax, ay = (a["lon"] - sign["lon"]) * scale * cosine, (a["lat"] - sign["lat"]) * scale
    dx, dy = (b["lon"] - a["lon"]) * scale * cosine, (b["lat"] - a["lat"]) * scale
    aa = dx * dx + dy * dy
    if aa == 0:
        lo, hi = (0, 1) if ax * ax + ay * ay <= radius * radius else (1, 0)
    else:
        bb, cc = 2 * (ax * dx + ay * dy), ax * ax + ay * ay - radius * radius
        discriminant = bb * bb - 4 * aa * cc
        if discriminant < 0:
            return None
        root = math.sqrt(discriminant)
        lo, hi = max(0, (-bb - root) / (2 * aa)), min(1, (-bb + root) / (2 * aa))
    if lo > hi:
        return None
    elapsed = b["timestamp"] - a["timestamp"]
    return [a["timestamp"] + lo * elapsed, a["timestamp"] + hi * elapsed]


def merge_intervals(intervals):
    merged = []
    for start, end in sorted(intervals):
        if merged and start <= merged[-1][1] + .001:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return merged


def fix_runs(indices, fixes):
    runs, current = [], []
    for index in indices:
        if current and (index != current[-1] + 1 or fixes[index]["timestamp"] - fixes[current[-1]]["timestamp"] > 15):
            runs.append(current)
            current = []
        current.append(index)
    if current:
        runs.append(current)
    result = []
    for run in runs:
        first, last = fixes[run[0]]["timestamp"], fixes[run[-1]]["timestamp"]
        following = fixes[run[-1] + 1]["timestamp"] if run[-1] + 1 < len(fixes) else last + 3
        result.append(dict(first_fix=run[0], last_fix=run[-1], fixes=len(run),
                           first_at=first, last_at=last, recorded_fix_span_s=last - first,
                           next_fix_or_expiry_upper_s=last - first + max(0, min(3, following - last))))
    return result


def target_matches(sign, fix):
    if not sign["requires_directed_evidence"]:
        return True
    return (sign["association_status"] == "accepted" and sign["associated_way_id"] is not None
            and fix["way_id"] is not None and str(sign["associated_way_id"]) == str(fix["way_id"])
            and sign["associated_direction"] is not None and sign["associated_direction"] == fix["direction"])


def analyze_windows(coverage, fixes):
    if not fixes or any(fix["timestamp"] is None for fix in fixes):
        raise ValueError("Window analysis requires timestamped fixes")
    if any(b["timestamp"] < a["timestamp"] for a, b in zip(fixes, fixes[1:])):
        raise ValueError("Window analysis requires fixes in timestamp order")
    segments, _ = route_segments(fixes, coverage["max_join_gap_m"], coverage["max_join_gap_s"])
    signs = coverage["signs"]
    signs_by_id = {s["sign_id"]: s for s in signs}
    variants = {}
    for radius in (10, 20, 30):
        observed = {s["sign_id"]: dict(sample_indices=[], eligible_indices=[], selected_indices=[],
                                       geometric_intervals=[], radius_m=30 if s["kind"] == "settlement_boundary" else radius)
                    for s in signs}
        for i, fix in enumerate(fixes):
            accuracy = fix["accuracy"]
            usable = accuracy is not None and 0 <= accuracy <= 25
            choices = []
            for sign in signs:
                state = observed[sign["sign_id"]]
                d = distance(fix["lat"], fix["lon"], sign["lat"], sign["lon"])
                if d > state["radius_m"]:
                    continue
                state["sample_indices"].append(i)
                if usable and target_matches(sign, fix):
                    state["eligible_indices"].append(i)
                    if sign["kind"] != "speed_limit":
                        choices.append((d, sign["sign_id"]))
            if choices:
                observed[min(choices)[1]]["selected_indices"].append(i)
        for sign in signs:
            state = observed[sign["sign_id"]]
            if sign["min_route_distance_m"] > state["radius_m"]:
                continue
            intervals = [interval for a, b in segments if (interval := circle_interval(sign, a, b, state["radius_m"])) is not None]
            state["geometric_intervals"] = merge_intervals(intervals)
        records = []
        for sign_id, state in observed.items():
            if not state["geometric_intervals"] and not state["sample_indices"]:
                continue
            sign = signs_by_id[sign_id]
            state.update(sign_id=sign_id, code=sign["sign_code"], kind=sign["kind"],
                         source_id=sign["source_id"], association_status=sign["association_status"],
                         sampled_visits=fix_runs(state["sample_indices"], fixes),
                         selected_slot_runs=fix_runs(state["selected_indices"], fixes))
            state["geometric_durations_s"] = [end - start for start, end in state["geometric_intervals"]]
            state["sample_fix_count"] = len(state.pop("sample_indices"))
            state["eligible_fix_count"] = len(state.pop("eligible_indices"))
            state["selected_slot_fix_count"] = len(state.pop("selected_indices"))
            records.append(state)
        sampled = [s for s in records if s["sample_fix_count"]]
        geometric = [s for s in records if s["geometric_intervals"]]
        selected = [s for s in records if s["selected_slot_fix_count"]]
        ordinary = [s for s in records if s["kind"] == "secondary"]
        summary = dict(sampled_sign_records=len(sampled), continuous_intersection_records=len(geometric),
                       continuous_but_no_sample_records=sum(bool(s["geometric_intervals"]) and not s["sample_fix_count"] for s in records),
                       sampled_by_kind=dict(Counter(s["kind"] for s in sampled)),
                       eligible_sign_records=sum(bool(s["eligible_fix_count"]) for s in records),
                       selected_secondary_slot_sign_records=len(selected),
                       selected_secondary_slot_by_kind=dict(Counter(s["kind"] for s in selected)),
                       selected_secondary_slot_fix_states=sum(s["selected_slot_fix_count"] for s in records),
                       eligible_non_speed_records=sum(bool(s["eligible_fix_count"]) and s["kind"] != "speed_limit" for s in records),
                       ordinary_secondary_geometric_durations=distribution([d for s in ordinary for d in s["geometric_durations_s"]]),
                       selected_slot_recorded_fix_spans=distribution([run["recorded_fix_span_s"] for s in selected for run in s["selected_slot_runs"]]),
                       selected_slot_next_fix_or_expiry_upper=distribution([run["next_fix_or_expiry_upper_s"] for s in selected for run in s["selected_slot_runs"]]))
        variants[str(radius)] = dict(summary=summary, signs=records)
    baseline = {s["sign_id"] for s in variants["10"]["signs"] if s["sample_fix_count"]}
    for radius in (20, 30):
        added = [s for s in variants[str(radius)]["signs"] if s["sample_fix_count"] and s["sign_id"] not in baseline]
        flags = Counter()
        cases = []
        for state in added:
            sign = signs_by_id[state["sign_id"]]
            flags[sign["kind"]] += 1
            nearest = sign["nearest_fix"]
            different_way = (nearest["way_id"] is not None and sign["associated_way_id"] is not None
                             and str(nearest["way_id"]) != str(sign["associated_way_id"]))
            known_opposite = sign["route_heading_error_deg"] is not None and sign["route_heading_error_deg"] > 90
            if sign["kind"] == "secondary":
                flags["secondary_different_associated_way"] += int(different_way)
                flags["secondary_opposite_route_heading"] += int(known_opposite)
                flags["secondary_association_unverified"] += int(sign["association_status"] != "accepted")
            cases.append(dict(sign_id=sign["sign_id"], code=sign["sign_code"], kind=sign["kind"],
                              min_fix_distance_m=sign["min_fix_distance_m"], association_status=sign["association_status"],
                              different_associated_way=different_way, opposite_route_heading=known_opposite,
                              eligible_fix_count=state["eligible_fix_count"], selected_slot_fix_count=state["selected_slot_fix_count"]))
        variants[str(radius)]["additional_vs_10m"] = dict(records=len(added), flags=dict(flags), signs=cases)
    return dict(format="youspeed.bw.sign-window-counterfactual.v1", default_changed=False,
                method="iPhone nearest eligible non-speed slot replay from logged way/direction, usable accuracy, source geofences; circle intersections interpolate between joined fixes.",
                limits=["Selected candidates are conditional states, not painted UI or observed physical signs",
                        "Actual UI freshness, global pictogram toggle and catalog rendering are not telemetered here",
                        "Direction comes from logged inventory lookup; missing direction fails closed",
                        "Geometric durations assume linear movement between fixes; excludes >15s/200m gaps",
                        "Source records may be duplicate poles/faces; IDs are not independent physical encounters"],
                variants=variants)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--coverage", type=Path, required=True)
    parser.add_argument("--track", type=Path, required=True)
    parser.add_argument("--out-json", type=Path, required=True)
    parser.add_argument("--update-map", type=Path)
    args = parser.parse_args()
    coverage = json.loads(args.coverage.read_text())
    fixes, _ = load_track(args.track)
    report = analyze_windows(coverage, fixes)
    args.out_json.write_text(json.dumps(report, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    if args.update_map:
        data = json.loads(args.update_map.read_text())
        states = {radius: {s["sign_id"]: s for s in variant["signs"]} for radius, variant in report["variants"].items()}
        for feature in data["features"]:
            properties = feature["properties"]
            if properties["layer"] != "sign":
                continue
            for radius, signs in states.items():
                state = signs.get(properties["sign_id"], {})
                for name in ("sample_fix_count", "eligible_fix_count", "selected_slot_fix_count"):
                    properties[f"r{radius}_{name}"] = state.get(name, 0)
            properties["visible_ui"] = "unknown"
        args.update_map.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":"), allow_nan=False) + "\n")
    print(json.dumps({radius: {key: value for key, value in variant.items() if key != "signs"} for radius, variant in report["variants"].items()}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
