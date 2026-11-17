import copy
import unittest

from assemble_blind_references import covered, valid_box, validate_decisions
from evaluate_geographic_audit import paired_intervals
from train_evaluate import score_frames


class BlindAuditTests(unittest.TestCase):
    def test_review_tiles_must_cover_every_pixel(self):
        self.assertTrue(covered([[0, 0, 6, 8], [4, 0, 10, 8]], 10, 8))
        self.assertFalse(covered([[0, 0, 4, 8], [5, 0, 10, 8]], 10, 8))
        self.assertFalse(covered([[0, 0, 10, 7]], 10, 8))

    def test_box_bounds_reject_invalid_coordinates(self):
        for box in ([1, 1, 1, 2], [-1, 0, 2, 2], [0, 0, 11, 2], [0, 0, float('nan'), 2]):
            with self.assertRaises(AssertionError):
                valid_box(box, 10, 10)

    def test_unresolved_or_unreviewed_proposals_cannot_enter_references(self):
        f = dict(picture_id='a', proposals=[dict(proposal_id='p1', box_xyxy=[1, 1, 3, 3])],
                 canonical=dict(dimensions=[10, 10]))
        d = dict(picture_id='a', admitted=True, annotation_complete=True,
                 reviewer='assistant_model_assisted', student_predictions_seen=False, note='review',
                 proposal_decisions=[dict(proposal_id='p1', decision='accepted', reason='front face')],
                 added_boxes=[], acceptable_extra_candidates=[])
        self.assertEqual(validate_decisions(f, d), [[1, 1, 3, 3]])
        for mutation in ('unresolved', 'missing', 'student_seen', 'incomplete'):
            bad = copy.deepcopy(d)
            if mutation == 'unresolved': bad['proposal_decisions'][0]['decision'] = 'unresolved'
            if mutation == 'missing': bad['proposal_decisions'] = []
            if mutation == 'student_seen': bad['student_predictions_seen'] = True
            if mutation == 'incomplete': bad['annotation_complete'] = False
            with self.assertRaises(AssertionError): validate_decisions(f, bad)

    def test_traffic_lights_remain_raw_false_positives(self):
        r = dict(image_id='a', group_id='a', truth=[[1, 1, 3, 3]],
                 predictions=[dict(box=[1, 1, 3, 3], score=.9), dict(box=[5, 5, 8, 8], score=.9)],
                 acceptable_extra_candidates=[dict(kind='traffic_light', box_xyxy=[5, 5, 8, 8])])
        v = score_frames([r], .5)
        self.assertEqual((v['tp'], v['fp'], v['fn'], v['fp_on_reviewed_traffic_lights']), (1, 1, 0, 1))
        self.assertEqual(v['precision'], .5)

    def test_paired_bootstrap_preserves_pairs_and_delta_direction(self):
        a = dict(frames=[dict(group_id='a', tp=1, fp=0, fn=1), dict(group_id='b', tp=1, fp=0, fn=1)])
        b = dict(frames=[dict(group_id='a', tp=2, fp=0, fn=0), dict(group_id='b', tp=2, fp=0, fn=0)])
        self.assertEqual(paired_intervals(a, a)['intervals']['recall'], [0, 0])
        self.assertEqual(paired_intervals(a, b)['intervals']['recall'], [.5, .5])
        bad = copy.deepcopy(b); bad['frames'][1]['group_id'] = 'a'
        with self.assertRaises(AssertionError): paired_intervals(a, bad)


if __name__ == '__main__':
    unittest.main()
