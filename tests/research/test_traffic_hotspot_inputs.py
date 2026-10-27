"""Input-boundary checks for the traffic/OSM study adapter."""
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "scripts/research"))
import prepare_traffic_hotspot_inputs as prepare
import rank_traffic_hotspots as rank


class InputAdapterTests(unittest.TestCase):
    def test_osm_coordinates_direction_and_condition_survive_database_adapter(self):
        raw = dict(osm3s=dict(timestamp_osm_base="2026-10-27T19:00:00Z"), elements=[
            dict(type="way", id=123, nodes=[10, 11],
                 geometry=[dict(lon=8.5, lat=48.8), dict(lon=8.501, lat=48.8)],
                 tags={"highway": "secondary", "oneway": "-1", "maxspeed": "70",
                       "maxspeed:backward": "50", "maxspeed:backward:conditional": "30 @ (wet)"})])
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "study.sqlite"
            prepare.build_osm_database(raw, path, "source-hash")
            roads, metadata = rank.load_roads(path, [8.499, 48.799, 8.502, 48.801])
            self.assertEqual(len(roads), 1)
            road = roads[0]
            self.assertEqual(road.coordinates, [[8.5, 48.8], [8.501, 48.8]])
            self.assertEqual((road.forward_allowed, road.backward_allowed), (False, True))
            self.assertEqual((road.start_node, road.end_node), ("10", "11"))
            self.assertIn("conditional_limit", road.limit(-1)[2])
            self.assertEqual(metadata["source_osm_timestamp"], "2026-10-27T19:00:00Z")
            self.assertEqual(rank.load_roads(path, [9.0, 49.0, 9.1, 49.1])[0], [])

    def test_partial_overpass_response_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            with self.assertRaisesRegex(ValueError, "partial response"):
                prepare.build_osm_database(dict(remark="runtime error: timeout", elements=[]),
                                           Path(directory) / "study.sqlite", "hash")

    def test_window_bounds_use_maplibre_zoom_convention(self):
        scope = prepare.map_scope("https://verkehrsinfo-bw.de/?loc=48.80602,8.53271,13.41z", 1280, 800)
        west, south, east, north = scope["bbox"]
        self.assertAlmostEqual((west + east) / 2, 8.53271, places=8)
        self.assertTrue(south < 48.80602 < north)
        self.assertAlmostEqual(east - west, 0.08268567338, places=8)


if __name__ == "__main__":
    unittest.main()
