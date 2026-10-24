import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts/research"))
import profile_bw_sign_route as route
import profile_bw_sign_windows as windows


def fix(index, lon, at):
    return dict(index=index, lat=48, lon=lon, part=0, timestamp=at, accuracy=2,
                heading=90, heading_accuracy=None, way_id="1", direction=1)


def sign(identifier="a"):
    return dict(sign_id=identifier, source_id="test", sign_code="DE:205", kind="secondary", lat=48, lon=8,
                min_route_distance_m=0, association_status="accepted", associated_way_id=1,
                associated_direction=1, requires_directed_evidence=False, route_heading_error_deg=0,
                nearest_fix=fix(1, 8, 1), min_fix_distance_m=0)


class RouteResearchTests(unittest.TestCase):
    def test_gaps_are_not_connected(self):
        fixes = [fix(0, 8, 0), fix(1, 8.0001, 1), fix(2, 8.0002, 100)]
        segments, gaps = route.route_segments(fixes)
        self.assertEqual(len(gaps), 1)
        self.assertEqual(gaps[0]["reasons"], ["time_gap"])
        self.assertEqual([(a["index"], b["index"]) for a, b in segments], [(0, 1), (2, 2)])

    def test_route_projection_and_heading(self):
        d, fraction, heading = route.project_to_segment(48, 8, fix(0, 7.999, 0), fix(1, 8.001, 2))
        self.assertAlmostEqual(d, 0)
        self.assertAlmostEqual(fraction, .5)
        self.assertAlmostEqual(heading, 90)

    def test_platform_log_field_aliases(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "route.json"
            path.write_text(json.dumps([dict(timestamp="2026-10-21T19:00:00Z", lat=48, lon=8, accuracy_m=2,
                                            bearing_deg=90, matched_way="7", inventory_direction=-1)]))
            fixes, report = route.load_track(path)
            self.assertEqual(report["valid_fixes"], 1)
            self.assertEqual((fixes[0]["accuracy"], fixes[0]["heading"], fixes[0]["way_id"], fixes[0]["direction"]), (2, 90, "7", -1))


class WindowResearchTests(unittest.TestCase):
    def coverage(self, signs):
        return dict(signs=signs, max_join_gap_m=200, max_join_gap_s=15)

    def test_continuous_intersection_is_not_a_recorded_fix(self):
        fixes = [fix(0, 7.9995, 0), fix(1, 8.0005, 4)]
        report = windows.analyze_windows(self.coverage([sign()]), fixes)
        for variant in report["variants"].values():
            self.assertEqual(variant["summary"]["sampled_sign_records"], 0)
            self.assertEqual(variant["summary"]["continuous_but_no_sample_records"], 1)
        durations = [report["variants"][str(radius)]["signs"][0]["geometric_durations_s"][0] for radius in (10, 20, 30)]
        self.assertAlmostEqual(durations[1], durations[0] * 2)
        self.assertAlmostEqual(durations[2], durations[0] * 3)

    def test_window_analysis_requires_ordered_timestamps(self):
        missing = fix(0, 8, None)
        with self.assertRaisesRegex(ValueError, "timestamped"):
            windows.analyze_windows(self.coverage([sign()]), [missing])
        with self.assertRaisesRegex(ValueError, "timestamp order"):
            windows.analyze_windows(self.coverage([sign()]), [fix(0, 8, 2), fix(1, 8, 1)])

    def test_single_slot_can_hide_a_colocated_candidate(self):
        fixes = [fix(0, 7.9995, 0), fix(1, 8, 1), fix(2, 8.0005, 2)]
        variant = windows.analyze_windows(self.coverage([sign("a"), sign("b")]), fixes)["variants"]["10"]
        self.assertEqual(variant["summary"]["eligible_non_speed_records"], 2)
        self.assertEqual(variant["summary"]["selected_secondary_slot_sign_records"], 1)
        selected = next(s for s in variant["signs"] if s["selected_slot_fix_count"])
        self.assertEqual(selected["sign_id"], "a")
        self.assertEqual(selected["selected_slot_runs"][0]["recorded_fix_span_s"], 0)
        self.assertEqual(selected["selected_slot_runs"][0]["next_fix_or_expiry_upper_s"], 1)

    def test_primary_requires_logged_direction_and_never_occupies_secondary_slot(self):
        primary = sign()
        primary.update(kind="speed_limit", sign_code="DE:274-30", requires_directed_evidence=True)
        fixes = [fix(0, 8, 1)]
        report = windows.analyze_windows(self.coverage([primary]), fixes)
        self.assertEqual(report["variants"]["10"]["summary"]["eligible_sign_records"], 1)
        self.assertEqual(report["variants"]["10"]["summary"]["selected_secondary_slot_sign_records"], 0)
        fixes[0]["direction"] = None
        report = windows.analyze_windows(self.coverage([primary]), fixes)
        self.assertEqual(report["variants"]["10"]["summary"]["eligible_sign_records"], 0)


if __name__ == "__main__":
    unittest.main()
