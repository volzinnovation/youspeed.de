import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('selector', Path(__file__).parents[2] / 'scripts/tsr/select_panoramax_end_signs.py')
selector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(selector)

class EndSignSelectionTests(unittest.TestCase):
    def feature(self):
        return {'id': 'picture', 'collection': 'sequence', 'properties': {
            'pers:interior_orientation': {'sensor_array_dimensions': [5760, 2880], 'field_of_view': 360},
            'annotations': [{'id': 'annotation', 'semantics': [
                {'key': 'osm|traffic_sign', 'value': 'FR:B33[50]'},
                {'key': 'classification_confidence[osm|traffic_sign=FR:B33[50]]', 'value': '1.0'}],
                'shape': {'type': 'Polygon', 'coordinates': [[[100, 200], [140, 200], [140, 260], [100, 200]]]}}]}}

    def test_exact_filter_escapes_literals(self):
        self.assertEqual(selector.tag_filter('FR:B33[50]'), '\"semantics.osm|traffic_sign\" = \'FR:B33[50]\'')
        self.assertIn("a''b", selector.tag_filter("a'b"))

    def test_machine_labels_are_review_candidates_with_original_pixel_coordinates(self):
        records = selector.select_annotations(self.feature(), {'FR:B33[50]'})
        self.assertEqual(records[0]['bbox_pixels'], [100, 200, 140, 260])
        self.assertFalse(records[0]['eligible_for_training'])
        self.assertTrue(records[0]['requires_perspective_projection'])
        self.assertEqual(records[0]['sequence_id'], 'sequence')
        self.assertEqual(records[0]['review_status'], 'unreviewed')

    def test_picture_tags_alone_and_other_signs_are_not_box_labels(self):
        f = self.feature()
        f['properties']['semantics'] = [{'key': 'osm|traffic_sign', 'value': 'FR:B31'}]
        self.assertEqual(selector.select_annotations(f, {'FR:B31'}), [])

    def test_invalid_boxes_are_rejected(self):
        for value in [-1, float('nan'), 6000]:
            f = copy.deepcopy(self.feature())
            f['properties']['annotations'][0]['shape']['coordinates'][0][0][0] = value
            self.assertEqual(selector.select_annotations(f, {'FR:B33[50]'}), [])

    def test_deduplicates_annotations_and_reports_sampling_not_complete_inventory(self):
        feature = self.feature()
        class Response:
            url = 'https://example.test/api/search'
            def raise_for_status(self): pass
            def json(self): return {'type': 'FeatureCollection', 'features': [feature]}
        class Session:
            headers = {}
            def get(self, *args, **kwargs): return Response()
        result = selector.collect('https://example.test/api/search', ['FR:B31', 'FR:B33[50]'], 1, session=Session())
        self.assertEqual(len(result['records']), 1)
        self.assertFalse(result['complete_inventory'])
        self.assertTrue(result['queries'][0]['possibly_truncated'])
        self.assertEqual(result['training_ready_count'], 0)
