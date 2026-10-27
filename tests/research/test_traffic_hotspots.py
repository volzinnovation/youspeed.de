"""Source/geometry admission regressions for the research hotspot matcher."""
from __future__ import annotations

import importlib.util
import csv
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[2] / "scripts/research/rank_traffic_hotspots.py"
spec = importlib.util.spec_from_file_location("traffic_hotspots", MODULE)
m = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = m
spec.loader.exec_module(m)


def road(identifier, start, end, tags=None, *, forward=True, backward=True, start_node=None, end_node=None):
    return m.Road(identifier, {"highway": "secondary", "street_name": "Study Road"}, [start, end],
                  {"maxspeed": "50"} if tags is None else tags, forward, backward,
                  start_node or m.coord_key(start), end_node or m.coord_key(end))


def traffic(start, end, **properties):
    return dict(type="Feature", id="traffic1", geometry=dict(type="LineString", coordinates=[start, end]),
                properties=dict(XDSegID="123", RoadName="Study Road", speed=75, score=30, c_value=90,
                                observed_at="2026-10-27T20:00:00", **properties))


class TrafficHotspotTests(unittest.TestCase):
    def setUp(self):
        self.projection = m.Projection(0, 0)
        self.a, self.b, self.c = [0, 0], [.001, 0], [.002, 0]

    def match(self, feature, roads):
        return m.match_feature(feature, m.RoadIndex(roads, self.projection), self.projection, speed_field="speed")

    def test_direction_is_not_folded(self):
        r = road(1, self.a, self.b, {"maxspeed:forward": "50", "maxspeed:backward": "30"})
        east, west = self.match(traffic(self.a, self.b), [r]), self.match(traffic(self.b, self.a), [r])
        self.assertTrue(east["eligible"])
        self.assertTrue(west["eligible"])
        self.assertEqual((east["osm_limit_kmh"], west["osm_limit_kmh"]), (50, 30))
        self.assertEqual((east["direction"], west["direction"]), ("E", "W"))

    def test_entire_traffic_link_is_checked_for_mixed_limits(self):
        result = self.match(traffic(self.a, self.c), [road(1, self.a, self.b), road(2, self.b, self.c, {"maxspeed": "30"})])
        self.assertFalse(result["eligible"])
        self.assertIn("mixed_osm_limits", result["reasons"])
        self.assertEqual({row["osm_limit_kmh"] for row in result["match_limit_breakdown"]}, {30, 50})

    def test_conditional_and_variable_uncertainty_block(self):
        for tags in ({"maxspeed": "50", "maxspeed:conditional": "30 @ (wet)"},
                     {"maxspeed": "50", "maxspeed:variable": "traffic"},
                     {"maxspeed": "50", "maxspeed:lanes": "30|50"}):
            with self.subTest(tags=tags):
                result = self.match(traffic(self.a, self.b), [road(1, self.a, self.b, tags)])
                self.assertIn("unresolved_osm_limit", result["reasons"])
                self.assertFalse(result["eligible"])

    def test_opposite_condition_and_advisory_metadata_do_not_mask(self):
        tags = {"maxspeed": "50", "maxspeed:backward:conditional": "30 @ (wet)", "maxspeed:advisory": "30"}
        east, west = self.match(traffic(self.a, self.b), [road(1, self.a, self.b, tags)]), self.match(traffic(self.b, self.a), [road(1, self.a, self.b, tags)])
        self.assertTrue(east["eligible"])
        self.assertFalse(west["eligible"])

    def test_unknown_and_unlimited_are_not_guessed(self):
        for tags in ({}, {"maxspeed": "none"}, {"maxspeed": "50foo"}, {"maxspeed:type": "DE:urban"}):
            self.assertFalse(self.match(traffic(self.a, self.b), [road(1, self.a, self.b, tags)])["eligible"])

    def test_historical_fallback_is_not_measured(self):
        feature = traffic(self.a, self.b)
        feature["properties"]["score"] = 20
        self.assertIn("not_measured_source_score30", self.match(feature, [road(1, self.a, self.b)])["reasons"])

    def test_low_c_value_is_excluded_without_probability_claim(self):
        feature = traffic(self.a, self.b)
        feature["properties"]["c_value"] = 60
        result = self.match(feature, [road(1, self.a, self.b)])
        self.assertEqual(result["c_value"], 60)
        self.assertIn("insufficient_provider_c_value", result["reasons"])

    def test_nearby_parallel_roads_are_ambiguous(self):
        parallel = road(2, [0, .000009], [.001, .000009])
        result = self.match(traffic(self.a, self.b), [road(1, self.a, self.b), parallel])
        self.assertIn("ambiguous_parallel_road", result["reasons"])

    def test_oneway_reverse_traffic_cannot_match(self):
        result = self.match(traffic(self.b, self.a), [road(1, self.a, self.b, backward=False)])
        self.assertIn("road_alignment_gap", result["reasons"])

    def test_route_gate_rejects_opposite_direction_and_nearby_links(self):
        roads = [road(1, self.a, self.b)]
        index = m.RoadIndex(roads, self.projection)
        gate = m.RouteGate(dict(type="LineString", coordinates=[self.a, self.b]), self.projection, index)
        east = self.match(traffic(self.a, self.b), roads)
        west = self.match(traffic(self.b, self.a), roads)
        gate.evaluate(east)
        gate.evaluate(west)
        self.assertTrue(east["eligible"])
        self.assertIn("outside_directed_gpx_corridor", west["reasons"])
        self.assertEqual(east["route_overlap_pct"], 100)

    def test_disconnected_source_path_is_excluded(self):
        result = self.match(traffic(self.a, self.c), [road(1, self.a, self.b, end_node="a"), road(2, self.b, self.c, start_node="b")])
        self.assertIn("disconnected_osm_path", result["reasons"])

    def test_route_gate_does_not_admit_a_parallel_diversion(self):
        roads = [road(1, self.a, self.b), road(2, self.b, self.c),
                 road(3, self.b, [.002, .00018])]
        index = m.RoadIndex(roads, self.projection)
        gate = m.RouteGate(dict(type="LineString", coordinates=[self.a, self.b, self.c]), self.projection, index)
        candidate = self.match(traffic(self.a, self.c), roads)
        # Keep geometry aligned, but expose a matched branch after the shared
        # first way. Mere single-way overlap must not satisfy route membership.
        candidate["match"]["directed_path"] = [dict(way_id=1, direction=1), dict(way_id=3, direction=1)]
        gate.evaluate(candidate)
        self.assertIn("partial_directed_osm_route_overlap", candidate["reasons"])

    def test_late_bridge_unions_existing_hotspot_groups(self):
        points = [[i * .001, 0] for i in range(4)]
        candidates = []
        for i, excess in enumerate([30, 10, 20]):
            item = self.match(traffic(points[i], points[i + 1]), [road(i + 1, points[i], points[i + 1])])
            item.update(id=str(i), excess_kmh=excess, excess_pct=2 * excess)
            candidates.append(item)
        clustered = m.cluster_candidates(candidates, self.projection)
        self.assertEqual(len(clustered), 1)
        self.assertEqual(clustered[0]["cluster_member_count"], 3)
        self.assertEqual(clustered[0]["id"], "0")

    def test_route_coverage_is_a_union_and_not_extended_past_link_end(self):
        roads = [road(1, self.a, self.c)]
        index = m.RoadIndex(roads, self.projection)
        gate = m.RouteGate(dict(type="LineString", coordinates=[self.a, self.c]), self.projection, index)
        first = self.match(traffic(self.a, self.b), roads)
        second = self.match(traffic(self.a, self.b), roads)
        first["id"], second["id"] = "a", "b"
        for candidate in (first, second):
            gate.evaluate(candidate)
        coverage = gate.coverage([first, second], speed_field="speed")
        self.assertAlmostEqual(coverage["measured_traffic_coverage_pct"], 50, delta=2)
        self.assertLess(coverage["measured_traffic_length_m"], 115)
        self.assertEqual(len(coverage["measured_intervals_m"]), 1)

    def test_historical_and_opposite_flow_do_not_count_as_measured_route_coverage(self):
        roads = [road(1, self.a, self.c)]
        index = m.RoadIndex(roads, self.projection)
        gate = m.RouteGate(dict(type="LineString", coordinates=[self.a, self.c]), self.projection, index)
        historical_feature = traffic(self.a, self.c)
        historical_feature["properties"]["score"] = 20
        historical = self.match(historical_feature, roads)
        reverse = self.match(traffic(self.c, self.a), roads)
        for candidate in (historical, reverse):
            gate.evaluate(candidate)
        self.assertEqual(gate.coverage([historical, reverse], speed_field="speed")["measured_traffic_coverage_pct"], 0)

    def test_malformed_geometry_fails_closed_without_crashing(self):
        for geometry in (None, {}, {"type": "LineString", "coordinates": [[0, 0], ["bad", 1]]},
                         {"type": "LineString", "coordinates": [[0, 0], [1, 91]]}):
            feature = traffic(self.a, self.b)
            feature["geometry"] = geometry
            result = self.match(feature, [road(1, self.a, self.b)])
            self.assertIn("invalid_geometry", result["reasons"])
            self.assertFalse(result["eligible"])

    def test_invalid_bounds_are_rejected(self):
        for bbox in ((0, 0, 0, 1), (0, 0, 1, 91), (float("nan"), 0, 1, 1), (1, 0, 0, 1)):
            with self.assertRaises(ValueError):
                m.validate_bbox(bbox)

    def test_report_separates_route_exclusions_from_bbox_and_preserves_raw_time(self):
        roads = [road(1, self.a, self.b)]
        forward, fallback, reverse = traffic(self.a, self.b), traffic(self.a, self.b), traffic(self.b, self.a)
        fallback["properties"].update(XDSegID="fallback", score=20)
        reverse["properties"]["XDSegID"] = "reverse"
        source = dict(type="FeatureCollection", features=[forward, fallback, reverse])
        with patch.object(m, "load_roads", return_value=(roads, {})):
            report = m.analyze("unused.sqlite", source, (-.001, -.001, .002, .001),
                               route_geometry=dict(type="LineString", coordinates=[self.a, self.b]), speed_field="speed")
        self.assertEqual(report["summary"]["fetched_traffic_segments"], 3)
        self.assertEqual(report["summary"]["on_route_segments"], 2)
        self.assertEqual(report["summary"]["route_excluded_segments"], 1)
        self.assertEqual(report["route_exclusions"], {"not_measured_source_score30": 1})
        self.assertEqual(report["observation_time"], "2026-10-27T20:00:00")
        self.assertAlmostEqual(report["summary"]["route_measured_coverage_pct"], 100, delta=1)

    def test_report_does_not_invent_a_single_timestamp_for_mixed_source_times(self):
        first, second = traffic(self.a, self.b), traffic(self.b, self.a)
        second["properties"].update(XDSegID="second", observed_at="2026-10-27T20:01:00")
        with patch.object(m, "load_roads", return_value=([road(1, self.a, self.b)], {})):
            report = m.analyze("unused.sqlite", dict(type="FeatureCollection", features=[first, second]),
                               (-.001, -.001, .002, .001), speed_field="speed")
        self.assertIsNone(report["observation_time"])
        self.assertEqual(len(report["observation_times"]), 2)

    def test_average_default_ignores_current_score_confidence_closure_and_timestamp_gates(self):
        feature = traffic(self.a, self.b)
        feature["properties"].update(average_speed=55, speed=None, score=20, c_value=None,
                                     segment_closed=True, observed_at=None)
        result = m.match_feature(feature, m.RoadIndex([road(1, self.a, self.b)], self.projection), self.projection)
        self.assertTrue(result["eligible"])
        self.assertEqual(result["speed_field"], "average_speed")
        self.assertEqual((result["speed_kmh"], result["excess_kmh"]), (55, 5))
        self.assertEqual(result["confidence_basis"], "not_supplied_for_average_speed")
        self.assertIsNone(result["source_score"])
        self.assertIsNone(result["c_value"])
        self.assertEqual(result["current_source_score"], 20)
        self.assertIn("missing_export_timestamp", result["provenance_warnings"])
        self.assertEqual(result["observed_at_role"], "snapshot_export_timestamp")

    def test_missing_or_invalid_average_never_falls_back_to_current_speed(self):
        for average in (None, 0, -1, "bad", float("inf")):
            with self.subTest(average=average):
                feature = traffic(self.a, self.b)
                feature["properties"]["average_speed"] = average
                result = m.match_feature(feature, m.RoadIndex([road(1, self.a, self.b)], self.projection), self.projection)
                self.assertFalse(result["eligible"])
                self.assertIn("missing_or_invalid_average_speed", result["reasons"])
                self.assertNotEqual(result["speed_kmh"], result["current_speed_kmh"])

    def average_report(self, features, route_geometry=None):
        with patch.object(m, "load_roads", return_value=([road(1, self.a, self.b)], {})):
            return m.analyze("unused.sqlite", dict(type="FeatureCollection", features=features),
                             (-.001, -.001, .002, .001), route_geometry=route_geometry)

    def test_average_ranking_can_reverse_current_ranking_and_keeps_negative_comparisons(self):
        current_fast, average_fast = traffic(self.a, self.b), traffic(self.b, self.a)
        current_fast["properties"].update(XDSegID="current_fast", speed=95, average_speed=45, c_value=100)
        average_fast["properties"].update(XDSegID="average_fast", speed=60, average_speed=65, score=20, c_value=None)
        report = self.average_report([current_fast, average_fast])
        self.assertEqual(report["speed_basis"]["field"], "average_speed")
        self.assertEqual(report["speed_basis"]["label"], "Durchschnitt")
        self.assertEqual([row["id"] for row in report["top5_eligible"]], ["average_fast", "current_fast"])
        self.assertEqual([row["excess_kmh"] for row in report["top5_eligible"]], [15, -5])
        self.assertEqual([row["id"] for row in report["top10"]], ["average_fast"])
        self.assertEqual(report["summary"]["eligible_comparison_count"], 2)
        self.assertTrue(report["top10"][0]["substantial"])

    def test_current_confidence_is_context_only_and_does_not_break_average_ties(self):
        first, second = traffic(self.a, self.b), traffic(self.b, self.a)
        first["properties"].update(XDSegID="z", average_speed=60, c_value=100)
        second["properties"].update(XDSegID="a", average_speed=60, c_value=0, score=20)
        report = self.average_report([first, second])
        self.assertEqual([row["id"] for row in report["top5_eligible"]], ["a", "z"])
        selected = report["top5_eligible"][0]
        self.assertIsNone(selected["source_score"])
        self.assertIsNone(selected["c_value"])
        self.assertEqual((selected["current_source_score"], selected["current_c_value"], selected["current_speed_kmh"]), (20, 0, 75))

    def test_average_route_coverage_is_availability_and_does_not_claim_measured_confidence(self):
        feature = traffic(self.a, self.b)
        feature["properties"].update(average_speed=14, score=20, c_value=None, segment_closed=True)
        report = self.average_report([feature], route_geometry=dict(type="LineString", coordinates=[self.a, self.b]))
        self.assertEqual(report["summary"]["eligible_segments"], 1)
        self.assertEqual(report["route_coverage"]["coverage_basis"], "historical_average_availability")
        self.assertAlmostEqual(report["summary"]["route_average_source_coverage_pct"], 100, delta=1)
        self.assertNotIn("measured_traffic_coverage_pct", report["route_coverage"])
        self.assertNotIn("route_measured_coverage_pct", report["summary"])
        self.assertEqual(report["observation_time_role"], "snapshot_export_timestamp")

    def test_average_csv_keeps_confidence_blank_and_current_context_separate(self):
        feature = traffic(self.a, self.b)
        feature["properties"].update(average_speed=60)
        report = self.average_report([feature])
        with tempfile.TemporaryDirectory() as directory:
            m.write_outputs(report, directory)
            with (Path(directory) / "candidates.csv").open() as source:
                row = next(csv.DictReader(source))
        self.assertEqual(row["speed_field"], "average_speed")
        self.assertEqual(row["c_value"], "")
        self.assertEqual(row["source_score"], "")
        self.assertEqual(row["confidence_basis"], "not_supplied_for_average_speed")
        self.assertEqual(row["current_c_value"], "90.0")


if __name__ == "__main__":
    unittest.main()
