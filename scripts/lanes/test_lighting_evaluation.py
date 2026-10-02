#!/usr/bin/env python3
"""Focused regression checks for the offline evaluation's interpretation rules."""
import unittest
from audit_lane_runtime import summarize
from evaluate_lighting_sequences import interval_metrics
from make_lighting_experiment import replace_once


class LightingEvaluationTests(unittest.TestCase):
    def test_duration_uses_pts_and_does_not_extend_window(self):
        self.assertEqual(interval_metrics([0,.5,1,1.5],[False,True,True,False]),
                         dict(estimatedSeconds=1.,longestObservedSpanSeconds=.5,transitions=2))
        self.assertEqual(interval_metrics([0,.7],[True,True])['estimatedSeconds'],.7)
        self.assertEqual(interval_metrics([0,.7],[False,False])['estimatedSeconds'],0)

    def test_missing_timing_is_unknown_and_android_sampling_is_separate(self):
        result=summarize([('timestamp',dict(frameId='a',preprocessingMs=4,laneFilterMs=5,
            laneFilter='top-hat',boundaries=[],geometryDeadlineExceeded=True))],
            [dict(frameId='a',source='live_frame',inferenceMs=20)])
        self.assertEqual(result['samplingMs']['p50'],4)
        self.assertEqual(result['preparationMs'],dict(n=0))
        self.assertEqual(result['inferenceDespiteGeometryDeadline'],1)
        self.assertEqual(result['inferenceWithExplicitEmptyBoundaries'],1)

    def test_missing_boundaries_are_not_an_empty_boundary_list(self):
        result=summarize([('timestamp',dict(frameId='a'))],
                         [dict(frameId='a',source='live_frame',inferenceMs=20)])
        self.assertEqual(result['inferenceWithExplicitEmptyBoundaries'],0)

    def test_source_patch_fails_closed_on_changed_or_ambiguous_anchor(self):
        for original in ['xx','absent']:
            with self.assertRaises(ValueError):replace_once(original,'x','y')
        self.assertEqual(replace_once('axb','x','y'),'ayb')


if __name__=='__main__':unittest.main()
