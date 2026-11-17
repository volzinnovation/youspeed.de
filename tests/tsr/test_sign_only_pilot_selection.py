import importlib.util
from pathlib import Path
import unittest

PATH = Path(__file__).resolve().parents[2] / "scripts/tsr/sign_only_pilot/select_pilot.py"
spec = importlib.util.spec_from_file_location("select_sign_only_pilot", PATH)
selection = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selection)


def frame(identifier, latitude, *, sequence=None, digest=None):
    return dict(picture_id=identifier, coordinates=[0, latitude],
                sequence_ids=[sequence or identifier], sha256=digest or identifier)


class PilotSeparationTests(unittest.TestCase):
    def test_polygon_scope_handles_holes_boundaries_and_exclaves(self):
        boundary = selection.StateBoundary({"type": "MultiPolygon", "coordinates": [
            [[[0, 0], [2, 0], [2, 2], [0, 2], [0, 0]],
             [[.5, .5], [1.5, .5], [1.5, 1.5], [.5, 1.5], [.5, .5]]],
            [[[3, 0], [4, 0], [4, 1], [3, 1], [3, 0]]],
        ]})
        self.assertTrue(boundary.contains([.2, 1]))
        self.assertFalse(boundary.contains([1, 1]))
        self.assertTrue(boundary.contains([0, 1]))
        self.assertTrue(boundary.contains([.5, 1]))
        self.assertTrue(boundary.contains([3.5, .5]))
        self.assertFalse(boundary.contains([2.5, .5]))

    def test_same_sequence_is_excluded_even_far_away(self):
        self.assertFalse(selection.separated(frame("a", 0, sequence="route"),
                                            [frame("b", 1, sequence="route")], 500))

    def test_same_bytes_cannot_cross_partitions_under_different_ids(self):
        self.assertFalse(selection.separated(frame("a", 0, digest="same"),
                                            [frame("b", 1, digest="same")], 500))

    def test_geographic_buffer_checked_independently_of_sequence(self):
        origin = frame("a", 0)
        self.assertFalse(selection.separated(frame("b", .004), [origin], 500))
        self.assertTrue(selection.separated(frame("c", .005), [origin], 500))

    def test_all_sequence_memberships_are_protected(self):
        row = frame("a", 0)
        row["sequence_ids"] = ["first", "shared"]
        self.assertFalse(selection.separated(row, [frame("b", 1, sequence="shared")], 500))


if __name__ == "__main__":
    unittest.main()
