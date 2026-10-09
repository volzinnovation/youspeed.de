import copy
from fractions import Fraction
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'scripts/lanes'))
import evaluate_semantic_guidance as subject
import qualify_semantic_hints as hints
import replay_recorded_pipeline as replay


class SemanticGuidanceTests(unittest.TestCase):
    def setUp(self):
        self.policy = hints.QualificationPolicy('test', 'revision', 64, 64, subject.MAX_AGE_NS)
        self.row = dict(id='frame', sequenceId='sequence', width=64, height=64)
        self.rgb = dict(ptsValue=6000, timeBase='1/600', sourceVideoSha256='a'*64,
                        decodedWidth=1920, decodedHeight=1080, sourceFrameId='encoded-6000')
        self.p = np.zeros((64,64), dtype=np.float32)
        self.p[:, 16] = .9
        self.context, self.hint = subject.envelope(self.row, self.rgb, self.p, self.policy, Fraction(10), 'mapping')
        self.border = dict(points=[[16/63,.58],[16/63,.95]], observedSegments=[])

    def arm(self, name, delay=12., previous=None):
        return subject.apply_variant(name, self.context, self.hint, self.p, delay, previous)

    def test_real_map_roundtrip_and_relative_clock(self):
        values, reason, valid = self.arm('qualified_paint')
        self.assertEqual(reason, 'qualified')
        np.testing.assert_array_equal(values, self.p)
        self.assertTrue(valid.all())
        self.assertEqual(self.context['exposure']['sourceTimeNs'], 0)
        self.assertEqual(self.context['exposure']['capturedAtNs'], 1_000_000_000)
        self.assertNotEqual(self.context['exposure']['sourceClockId'], self.context['now']['clockId'])

    def test_faults_fall_back_without_mutating_inputs(self):
        before = copy.deepcopy(self.hint)
        faults = {'missing':'missing_hint', 'stale':'stale_hint', 'wrong_generation':'scope_mismatch',
                  'declared_shift':'geometry_mismatch', 'wrong_model':'model_mismatch',
                  'malformed_mask':'shape_mismatch', 'mixed_clock':'clock_mismatch'}
        for name, expected in faults.items():
            with self.subTest(name=name):
                values, reason, _ = self.arm(name)
                self.assertIsNone(values)
                self.assertEqual(reason, expected)
        self.assertEqual(self.hint, before)

    def test_no_waiting_for_late_result(self):
        self.assertEqual(self.arm('host_cost_deadline_5ms')[1], 'not_arrived_by_simulated_deadline')
        self.assertEqual(self.arm('host_cost_deadline_20ms')[1], 'qualified')
        self.assertEqual(self.arm('host_cost_deadline_20ms', 21)[1], 'not_arrived_by_simulated_deadline')

    def test_exact_exposure_rejects_previous_result(self):
        previous = dict(self.hint['exposure'], frameId='previous', sourceTimeNs=1)
        self.assertEqual(self.arm('out_of_order', previous=previous)[1], 'exposure_mismatch')
        self.assertEqual(self.arm('out_of_order')[1], 'missing_previous_exposure')

    def test_concealed_alignment_error_is_explicit_blind_spot(self):
        values, reason, valid = self.arm('concealed_shift')
        self.assertEqual(reason, 'qualified')
        self.assertGreater(subject.compatibility(self.border, self.p, valid), .89)
        self.assertEqual(subject.compatibility(self.border, values, valid), 0)

    def test_unknown_pixels_are_not_negative_evidence(self):
        valid = np.zeros_like(self.p, dtype=bool)
        valid[:,16] = True
        self.assertAlmostEqual(subject.compatibility(self.border,self.p,valid), .9, places=6)
        valid[:,:] = False
        self.assertEqual(subject.compatibility(self.border,self.p,valid),0)

    def test_observed_segments_exclude_interpolated_gap(self):
        p = np.zeros_like(self.p)
        p[45:48,16] = 1
        valid = np.ones_like(p,dtype=bool)
        self.assertGreater(subject.compatibility(self.border,p,valid),0)
        segments = dict(self.border, observedSegments=[[[16/63,.58],[16/63,.65]], [[16/63,.82],[16/63,.95]]])
        self.assertEqual(subject.compatibility(segments,p,valid),0)

    def test_uniform_control_has_no_location_preference(self):
        values, _, valid = self.arm('uniform_control')
        a = subject.compatibility(self.border,values,valid)
        b = subject.compatibility(dict(points=[[.8,.58],[.8,.95]]),values,valid)
        self.assertEqual(a,b)

    def test_fallback_equality_includes_publication_and_budget_flags(self):
        baseline = dict(variant='baseline', filterMs=1., overlayPublished=True, deadlineExceeded=False,
                        calibrationDiagnostics=dict(stageMs={'total':1.}, generation=1))
        same = dict(baseline, variant='missing', filterMs=2.)
        self.assertEqual(subject.stable_output(baseline), subject.stable_output(same))
        for key,value in [('overlayPublished',False),('deadlineExceeded',True)]:
            self.assertNotEqual(subject.stable_output(baseline), subject.stable_output(dict(same,**{key:value})))

    def test_guided_replay_cannot_be_relabelled_as_baseline(self):
        subject.require_unguided_source([dict(id='a')])
        for key,value in [('semanticScoreAdjustments', []), ('semanticScoreAdjustments', [0]),
                          ('semanticSourceInputSha256', 'a'*64)]:
            with self.assertRaisesRegex(ValueError, 'already contains semantic'):
                subject.require_unguided_source([dict(id='a'), dict(id='b', **{key:value})])

    def test_replay_requires_bound_score_exposure_and_values(self):
        with tempfile.TemporaryDirectory() as name:
            d=Path(name); gray=d/'frame.gray'; gray.write_bytes(bytes(64*64))
            row=dict(self.row,grayPath=str(gray),graySha256=subject.audit.sha(gray),time=1.,
                     semanticScoreAdjustments=[.1],semanticSourceInputSha256=subject.audit.sha(gray))
            path=d/'manifest.json'
            def load():
                path.write_text(json.dumps(dict(schemaVersion=1,frames=[row])))
                return replay.normalized_manifest(path,'test')
            self.assertEqual(load()['frames'][0]['semanticScoreAdjustments'],[.1])
            for bad in ([.11],[-.01],[True],[0]*7,'bad'):
                row['semanticScoreAdjustments']=bad
                with self.assertRaises(ValueError): load()
            row['semanticScoreAdjustments']=[.1]
            row['semanticSourceInputSha256']='b'*64
            with self.assertRaisesRegex(ValueError,'exposure mismatch'): load()


if __name__ == '__main__':
    unittest.main()
