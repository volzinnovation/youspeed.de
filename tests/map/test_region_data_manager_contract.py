"""Portable asset-contract checks; native rendering still needs platform tests.

Run with: python3 -m unittest discover -s tests/map -p test_region_data_manager_contract.py
No network, map databases, models, or third-party Python packages are needed.
"""
import json
import math
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]


def load(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def in_ring(x, y, ring):
    inside = False
    for a, b in zip(ring, ring[1:]):
        dx, dy = b[0] - a[0], b[1] - a[1]
        if dx == 0 and dy == 0:
            continue
        cross = (x - a[0]) * dy - (y - a[1]) * dx
        if abs(cross) <= 1e-12 and min(a[0], b[0]) <= x <= max(a[0], b[0]) and min(a[1], b[1]) <= y <= max(a[1], b[1]):
            return True
        if (a[1] > y) != (b[1] > y) and x < dx * (y - a[1]) / dy + a[0]:
            inside = not inside
    return inside


def contains(region, longitude, latitude):
    return any(in_ring(longitude, latitude, polygon[0]) and not any(
        in_ring(longitude, latitude, hole) for hole in polygon[1:]
    ) for polygon in region["polygons"])


class DataManagerAssetContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.official = load("shared/RegionalCoverage/official-regions-v1.json")
        cls.routing = load("shared/RegionalCoverage/catalog-v1.json")

    def test_every_platform_option_has_exactly_one_official_shape(self):
        official_ids = [region["id"] for region in self.official["regions"]]
        self.assertEqual(len(official_ids), len(set(official_ids)))
        self.assertEqual(len(official_ids), 51)
        for path in ("iphone/SpeedConsumerApp/BundleTargets.top10.json", "android/app/src/main/assets/BundleTargets.top10.json"):
            targets = load(path)
            ids = [country["country_id"] + "|" + region["region_id"] for country in targets["countries"] for region in country["regions"]]
            self.assertEqual(len(ids), len(set(ids)))
            self.assertEqual(set(ids), set(official_ids))

    def test_visual_and_routing_boundaries_keep_distinct_semantics(self):
        self.assertEqual(self.official["boundary_kind"], "official_administrative_and_statistical_boundaries")
        self.assertEqual(self.routing["boundary_kind"], "buffered_extract_coverage")
        self.assertEqual({r["id"] for r in self.official["regions"]}, {r["id"] for r in self.routing["regions"]})
        self.assertIn("EuroGeographics", self.official["attribution"])

    def test_geometry_is_finite_closed_and_inside_its_bounds(self):
        for region in self.official["regions"]:
            west, south, east, north = region["bbox"]
            self.assertLess(west, east)
            self.assertLess(south, north)
            self.assertTrue(region["polygons"])
            for polygon in region["polygons"]:
                self.assertTrue(polygon)
                for ring in polygon:
                    self.assertGreaterEqual(len(ring), 4)
                    self.assertEqual(ring[0], ring[-1])
                    for point in ring:
                        self.assertEqual(len(point), 2)
                        self.assertTrue(all(math.isfinite(value) for value in point))
                        self.assertTrue(-180 <= point[0] <= 180 and -90 <= point[1] <= 90)
                        self.assertTrue(west <= point[0] <= east and south <= point[1] <= north)

    def test_tiny_regions_and_overseas_are_present_and_selectable(self):
        cases = [
            ("germany|berlin", 13.405, 52.52),
            ("germany|bremen", 8.807, 53.075),
            ("monaco|monaco", 7.425, 43.7384),
            ("liechtenstein|liechtenstein", 9.52, 47.16),
            ("france|reunion", 55.53, -21.115),
            ("france|mayotte", 45.16, -12.82),
            ("france|martinique", -61.025, 14.675),
            ("france|guadeloupe", -61.68, 16.1),
        ]
        by_id = {region["id"]: region for region in self.official["regions"]}
        for region_id, longitude, latitude in cases:
            with self.subTest(region_id=region_id):
                self.assertTrue(contains(by_id[region_id], longitude, latitude))

    def test_berlin_is_not_hidden_by_brandenburg_administrative_shape(self):
        regions = {region["id"]: region for region in self.official["regions"]}
        self.assertTrue(contains(regions["germany|berlin"], 13.405, 52.52))
        self.assertFalse(contains(regions["germany|brandenburg"], 13.405, 52.52))

    def test_germany_default_bounds_cover_all_states_without_overseas_fit(self):
        west, south, east, north = (5.5, 47.0, 15.8, 55.6)
        german = [r for r in self.official["regions"] if r["id"].startswith("germany|")]
        self.assertEqual(len(german), 16)
        for region in german:
            r_west, r_south, r_east, r_north = region["bbox"]
            with self.subTest(region=region["id"]):
                self.assertTrue(west <= r_west < r_east <= east)
                self.assertTrue(south <= r_south < r_north <= north)
        overseas = {"france|guadeloupe", "france|martinique", "france|mayotte", "france|reunion"}
        self.assertTrue(overseas.issubset({r["id"] for r in self.official["regions"]}))
        for region in self.official["regions"]:
            if region["id"] in overseas:
                r_west, r_south, r_east, r_north = region["bbox"]
                self.assertTrue(r_east < west or r_west > east or r_north < south or r_south > north)


if __name__ == "__main__":
    unittest.main()
