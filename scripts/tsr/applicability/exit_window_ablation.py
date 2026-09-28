"""Offline directed exit-window ablation; never imported by either mobile app.

The requested 200 m window means 100 m BEFORE through 100 m AFTER the departure.
This compares a blanket blackout with candidate suppression requiring independent
branch-association evidence. Neither creates TSR authority, refreshes a GPS fix,
derives a governing road from driver speed, or estimates a visual road boundary.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import json
import math
from pathlib import Path


MAINLINES = {"motorway", "trunk"}
RAMPS = {"motorway_link", "trunk_link"}
INDEPENDENT_BRANCH_CUES = {"reviewed_separator", "reviewed_gore", "reviewed_arrow"}


def distance_m(a: dict, b: dict) -> float:
    p1, p2 = math.radians(a["latitude"]), math.radians(b["latitude"])
    dp, dl = p2 - p1, math.radians(b["longitude"] - a["longitude"])
    return 12_742_000 * math.asin(min(1, math.sqrt(
        math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2)))


def project_recorded_coordinate(topology: dict, way_id: str, departure_node: str,
                                latitude: float, longitude: float) -> dict:
    """Offline positional diagnostic on an ALREADY identified way, not a matcher.

    Uses a local tangent plane. It neither supplies a capture/fix time nor proves
    a road choice. Signed distance follows stored node order, so callers must
    check travel direction separately (Brouck's checked way is oneway=yes).
    """
    way = next(w for w in topology["ways"] if w["id"] == way_id)
    nodes = {n["id"]: n for n in topology["nodes"]}
    origin_index = way["nodeIds"].index(departure_node)
    scale = math.cos(math.radians(latitude))

    def xy(lat, lon):
        return (math.radians(lon - longitude) * 6_371_000 * scale,
                math.radians(lat - latitude) * 6_371_000)

    points = [xy(nodes[n]["latitude"], nodes[n]["longitude"]) for n in way["nodeIds"]]
    lengths = [math.dist(a, b) for a, b in zip(points, points[1:])]
    junction_offset = sum(lengths[:origin_index])
    candidates, prefix = [], 0.0
    for index, (a, b, length) in enumerate(zip(points, points[1:], lengths)):
        if length == 0:
            continue
        dx, dy = b[0] - a[0], b[1] - a[1]
        fraction = min(1, max(0, -(a[0] * dx + a[1] * dy) / length ** 2))
        lateral = math.hypot(a[0] + fraction * dx, a[1] + fraction * dy)
        candidates.append({"lateralDistanceM": lateral,
                           "signedDistanceFromDepartureM": prefix + fraction * length - junction_offset,
                           "fromNode": way["nodeIds"][index], "toNode": way["nodeIds"][index + 1]})
        prefix += length
    return min(candidates, key=lambda c: c["lateralDistanceM"])


def build_window(topology: dict, departure_node: str, ramp_way: str,
                 before_m: float = 100, after_m: float = 100) -> dict:
    """Return partial directed mainline edges, preserving original node identity.

    Traverse only a unique mainline continuation in each direction. Ambiguous
    motorway forks/merges and extract boundaries stop coverage explicitly. Ramp
    and service edges are never included, even when physically close to mainline.
    """
    if any(not math.isfinite(x) or not 0 < x <= 500 for x in (before_m, after_m)):
        raise ValueError("Experimental distances must be finite and in (0, 500]")
    ways = {w["id"]: w for w in topology["ways"]}
    nodes = {n["id"]: n for n in topology["nodes"]}
    ramp = ways.get(ramp_way)
    if ramp is None or ramp["tags"].get("highway") not in RAMPS:
        raise ValueError("Departure must name a directed exit ramp, not nearby service")
    edges = topology["directedEdges"]
    if not any(e["wayId"] == ramp_way and e["fromNode"] == departure_node for e in edges):
        raise ValueError("Ramp must depart this exact original OSM node")
    incoming, outgoing = {}, {}
    for edge in edges:
        if ways[edge["wayId"]]["tags"].get("highway") not in MAINLINES:
            continue
        incoming.setdefault(edge["toNode"], []).append(edge)
        outgoing.setdefault(edge["fromNode"], []).append(edge)
    if not incoming.get(departure_node):
        raise ValueError("Departure has no directed incoming mainline")
    intervals, gaps = [], []
    for upstream, limit in ((True, before_m), (False, after_m)):
        node, covered, seen = departure_node, 0.0, set()
        adjacency = incoming if upstream else outgoing
        side = "before" if upstream else "after"
        while covered < limit:
            options = adjacency.get(node, [])
            if len(options) != 1:
                gaps.append({"side": side, "coveredM": covered,
                             "reason": "ambiguous_mainline" if options else "extract_or_mainline_boundary"})
                break
            edge = options[0]
            key = (edge["wayId"], edge["fromNode"], edge["toNode"])
            if key in seen or len(seen) >= 256:
                gaps.append({"side": side, "coveredM": covered, "reason": "loop_or_edge_cap"})
                break
            seen.add(key)
            length = distance_m(nodes[edge["fromNode"]], nodes[edge["toNode"]])
            if length <= 0:
                gaps.append({"side": side, "coveredM": covered, "reason": "zero_length_edge"})
                break
            take = min(length, limit - covered)
            intervals.append({**edge, "edgeLengthM": length,
                              "fromOffsetM": length - take if upstream else 0,
                              "toOffsetM": length if upstream else take,
                              "chainageFromM": -(covered + take) if upstream else covered,
                              "chainageToM": -covered if upstream else covered + take})
            covered += take
            node = edge["fromNode"] if upstream else edge["toNode"]
    return {"schemaVersion": 1, "role": "offline_spatial_window_ablation",
            "departureNode": departure_node, "rampWayId": ramp_way,
            "beforeM": before_m, "afterM": after_m,
            "coveredM": sum(i["toOffsetM"] - i["fromOffsetM"] for i in intervals),
            "intervals": intervals, "coverageGaps": gaps,
            "behavior": "off", "learnedGeometry": "not_run", "mobileEnabled": False}


@dataclass(frozen=True)
class Capture:
    frame_at_ms: int
    road_at_ms: int
    way_id: str
    from_node: str
    to_node: str
    edge_offset_m: float
    direction_verified: bool = True
    matched_edge_unambiguous: bool = True


def in_window(window: dict, capture: Capture) -> bool:
    # No extrapolation, fix-time rewriting, coordinate snapping, or stale hold.
    if (not 0 <= capture.frame_at_ms - capture.road_at_ms <= 1500
            or not capture.direction_verified or not capture.matched_edge_unambiguous
            or not math.isfinite(capture.edge_offset_m)):
        return False
    return any((capture.way_id, capture.from_node, capture.to_node) ==
               (i["wayId"], i["fromNode"], i["toNode"])
               and i["fromOffsetM"] <= capture.edge_offset_m <= i["toOffsetM"]
               for i in window["intervals"])


def candidate_action(window: dict, capture: Capture, *, mode: str,
                     associated_branch: str | None = None,
                     cue: str | None = None) -> str:
    """A pass means only 'leave existing pipeline unchanged', never 'accept'.

    The cue is an EXTERNAL reviewed/synthetic oracle in this experiment. Its
    detection accuracy and cost are unmeasured. Sign value, image x and driving
    speed deliberately are not inputs. Live detection cannot use review labels.
    """
    if mode not in {"blanket", "selective"}:
        raise ValueError("Unknown ablation")
    if not in_window(window, capture):
        return "pass_to_existing_tsr"
    if mode == "blanket":
        return "suppress_candidate"
    if associated_branch == window["rampWayId"] and cue in INDEPENDENT_BRANCH_CUES:
        return "suppress_candidate"
    return "pass_to_existing_tsr"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--topology", type=Path, required=True)
    parser.add_argument("--departure-node", required=True)
    parser.add_argument("--ramp-way", required=True)
    parser.add_argument("--before-m", type=float, default=100)
    parser.add_argument("--after-m", type=float, default=100)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    report = build_window(json.loads(args.topology.read_text()), args.departure_node,
                          args.ramp_way, args.before_m, args.after_m)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({k: report[k] for k in ("coveredM", "coverageGaps")}, sort_keys=True))


if __name__ == "__main__":
    main()
