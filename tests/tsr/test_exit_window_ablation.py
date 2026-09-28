"""Counterexamples for an offline ablation, not fitted accuracy or device tests."""
from dataclasses import replace
import json
import math
from pathlib import Path

import pytest

from scripts.tsr.applicability.exit_window_ablation import (
    Capture, build_window, candidate_action, distance_m, in_window, project_recorded_coordinate,
)


def topology():
    # Mainline has an INTERNAL exit node and a way split 60 m after it.
    points = {"a": (-250, 0), "b": (-150, 0), "c": (-50, 0), "j": (0, 0),
              "d": (60, 0), "e": (200, 0), "r": (70, -70),
              "near-j": (0, 0), "s": (100, -5)}
    ways = [("m1", "motorway", ["a", "b", "c", "j", "d"]),
            ("m2", "motorway", ["d", "e"]),
            ("ramp", "motorway_link", ["j", "r"]),
            ("service", "service", ["near-j", "s"])]
    return {"nodes": [{"id": key, "latitude": math.degrees(y / 6371000),
                       "longitude": math.degrees(x / 6371000)} for key, (x, y) in points.items()],
            "ways": [{"id": key, "tags": {"highway": kind}, "nodeIds": nodes}
                     for key, kind, nodes in ways],
            "directedEdges": [{"wayId": key, "fromNode": a, "toNode": b}
                              for key, _, nodes in ways for a, b in zip(nodes, nodes[1:])]}


def frame(x=10):
    if x < -50:
        return Capture(10_000, 9_000, "m1", "b", "c", x + 150)
    if x < 0:
        return Capture(10_000, 9_000, "m1", "c", "j", x + 50)
    if x <= 60:
        return Capture(10_000, 9_000, "m1", "j", "d", x)
    return Capture(10_000, 9_000, "m2", "d", "e", x - 60)


def test_200_m_means_minus_100_to_plus_100_crossing_partial_edges_and_way_split():
    w = build_window(topology(), "j", "ramp")
    assert w["coveredM"] == pytest.approx(200)
    assert not w["coverageGaps"]
    assert {i["wayId"] for i in w["intervals"]} == {"m1", "m2"}
    assert min(i["chainageFromM"] for i in w["intervals"]) == -100
    assert max(i["chainageToM"] for i in w["intervals"]) == 100
    assert in_window(w, frame(-99)) and in_window(w, frame(99))
    assert not in_window(w, frame(-101)) and not in_window(w, frame(101))
    assert build_window(topology(), "j", "ramp", 100, 200)["coveredM"] == pytest.approx(300)


def test_whole_way_identity_never_extends_window_or_disables_entered_ramp():
    w = build_window(topology(), "j", "ramp")
    assert not in_window(w, replace(frame(), way_id="ramp", from_node="j", to_node="r"))
    assert not in_window(w, frame(-140))  # Same way as departure, outside interval.


def test_unconnected_coordinate_coincidence_and_emergency_service_are_not_departures():
    with pytest.raises(ValueError, match="directed exit ramp"):
        build_window(topology(), "near-j", "service")
    with pytest.raises(ValueError, match="exact original OSM node"):
        build_window(topology(), "near-j", "ramp")


@pytest.mark.parametrize("change", [
    {"road_at_ms": 8499}, {"road_at_ms": 10001}, {"direction_verified": False},
    {"matched_edge_unambiguous": False}, {"from_node": "d", "to_node": "j"},
    {"edge_offset_m": float("nan")},
])
def test_stale_future_wrong_direction_or_ambiguous_context_never_activates_window(change):
    assert not in_window(build_window(topology(), "j", "ramp"), replace(frame(), **change))


def test_ambiguous_mainline_fork_stops_coverage_instead_of_masking_both_roads():
    t = topology()
    t["ways"].append({"id": "fork", "tags": {"highway": "motorway"}, "nodeIds": ["j", "r"]})
    t["directedEdges"].append({"wayId": "fork", "fromNode": "j", "toNode": "r"})
    w = build_window(t, "j", "ramp")
    assert w["coveredM"] == pytest.approx(100)
    assert w["coverageGaps"] == [{"side": "after", "coveredM": 0.0, "reason": "ambiguous_mainline"}]


# Ground truth below is used only for assertions. Branch cues are independent
# synthetic oracle inputs: the production vision feature does not yet exist.
CASES = [
    ("exit sign beyond gore", "other", 10, "ramp", "reviewed_gore", True, True),
    ("service sign beyond separator", "other", 10, "ramp", "reviewed_separator", True, True),
    ("ramp sign with associated arrow", "other", -30, "ramp", "reviewed_arrow", True, True),
    ("mainline work-zone left paired sign", "ego", 10, None, None, True, False),
    ("mainline work-zone right paired sign", "ego", 10, None, None, True, False),
    ("mainline overhead sign", "ego", 10, None, None, True, False),
    ("mainline right shoulder only sign", "ego", 10, None, None, True, False),
    ("real sign before activation window", "ego", -140, None, None, False, False),
    ("exit sign already visible before window", "other", -140, "ramp", "reviewed_gore", False, False),
    ("unrelated disconnected service sign", "other", 10, "service", "reviewed_separator", True, False),
    ("unresolved nearby sign", "unknown", 10, None, None, True, False),
    ("different exit's branch cue", "unknown", 10, "another-ramp", "reviewed_arrow", True, False),
    ("right image position alone", "unknown", 10, "ramp", "image_right", True, False),
    ("not slowing down alone", "unknown", 10, "ramp", "driver_not_slowing", True, False),
]


@pytest.mark.parametrize("name,truth,x,branch,cue,blanket,selective", CASES, ids=[c[0] for c in CASES])
def test_blanket_and_selective_counterexamples(name, truth, x, branch, cue, blanket, selective):
    w = build_window(topology(), "j", "ramp")
    for mode, suppressed in (("blanket", blanket), ("selective", selective)):
        result = candidate_action(w, frame(x), mode=mode, associated_branch=branch, cue=cue)
        assert (result == "suppress_candidate") is suppressed


def test_entering_exit_releases_mainline_quarantine_even_for_previously_dismissed_branch():
    w = build_window(topology(), "j", "ramp")
    on_ramp = replace(frame(), way_id="ramp", from_node="j", to_node="r")
    for mode in ("blanket", "selective"):
        assert candidate_action(w, on_ramp, mode=mode, associated_branch="ramp",
                                cue="reviewed_arrow") == "pass_to_existing_tsr"


def test_current_brouck_partial_way_and_issoire_short_way_counterexamples():
    base = Path(__file__).resolve().parents[2] / "shared/tsr/applicability/fixtures/corrected-exit-topology-v1"
    brouck = json.loads((base / "brouck.json").read_text())
    w = build_window(brouck, "10532395", "4683712")
    assert w["coveredM"] == pytest.approx(200)
    assert not w["coverageGaps"]
    assert {i["wayId"] for i in w["intervals"]} == {"216220089"}
    way = next(way for way in brouck["ways"] if way["id"] == "216220089")
    nodes = {n["id"]: n for n in brouck["nodes"]}
    length = sum(distance_m(nodes[a], nodes[b]) for a, b in zip(way["nodeIds"], way["nodeIds"][1:]))
    assert length == pytest.approx(4593.9292, abs=.01)
    issoire = json.loads((base / "issoire.json").read_text())
    for junction, ramp, covered in (("5278217783", "546168667", 200),
                                     ("637042785", "493957359", 160.742596)):
        w = build_window(issoire, junction, ramp)
        assert w["coveredM"] == pytest.approx(covered)
        if junction == "637042785":
            # The bounded public extract lacks the preceding way: never invent it.
            assert w["coverageGaps"][0]["reason"] == "extract_or_mainline_boundary"
        else:
            assert not w["coverageGaps"]
        assert len({i["wayId"] for i in w["intervals"]}) >= 3


@pytest.mark.parametrize("value", [0, -100, float("inf"), float("nan"), 501])
def test_unbounded_interval_rejected(value):
    with pytest.raises(ValueError, match="finite"):
        build_window(topology(), "j", "ramp", before_m=value)


def test_positional_diagnostic_projects_only_onto_explicit_way_and_preserves_side_distance():
    t = topology()
    result = project_recorded_coordinate(t, "m1", "j", math.degrees(5 / 6371000),
                                        math.degrees(-30 / 6371000))
    assert result["signedDistanceFromDepartureM"] == pytest.approx(-30)
    assert result["lateralDistanceM"] == pytest.approx(5)
    assert result["fromNode"] == "c" and result["toNode"] == "j"
    with pytest.raises(ValueError):
        project_recorded_coordinate(t, "m1", "near-j", 0, 0)
