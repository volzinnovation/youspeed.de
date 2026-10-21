import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'scripts/lanes'))
import score_native_paint_support as subject


class NativePaintSupportTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.gray = self.root/'gray'; self.gray.write_bytes(bytes(64*64))
        self.frame = dict(id='frame', sequenceId='frame', time=0., width=64, height=64,
            decodedWidth=128, decodedHeight=128, grayPath=str(self.gray), graySha256=subject.paint.sha(self.gray),
            dataset='ZOD', split='test', groupId='day', sourceFrameId='source')
        self.truth = np.zeros((64, 64), bool); self.truth[:, 16] = True
        self.valid = np.ones((64, 64), bool)
        self.boundary = dict(cue='paint', points=[[16/63, .58], [16/63, .95]], observedSegments=[], confidence=.8)
        self.row = dict(id='frame', sequenceId='frame', time=0., width=64, height=64,
            inputSha256=self.frame['graySha256'], rawBoundaries=[self.boundary],
            visibleBoundaryIndices=[], visibleIDs=[], confirmedBoundaries=[],
            lanePresentation=dict(items=[dict(observationCount=1, state='tentative')], selectionDecisions=[]),
            overlayPublished=False, geometryBudgetExceeded=False)
        self.target = dict(id='frame', dataset='ZOD', split='test', groupId='day', captureGroup='day',
            sourceFrameId='source', inputSha256=self.frame['graySha256'], width=64, height=64,
            imageSha256='b'*64, labelSha256='c'*64)
        self.write_masks()
        self.manifest = self.root/'manifest.json'; self.targets = self.root/'targets.json'
        self.write_inputs()
        self.native = self.root/'native.ndjson'; self.native.write_text(json.dumps(self.row)+'\n')
        self.prob = self.root/'prob.npy'; np.save(self.prob, self.truth.astype(np.float32)*.9)
        self.model = dict(id='a2d2-seed-1', arm='a2d2', seed=1, checkpointSha256='d'*64, sourceMetricsSha256='e'*64)
        self.index = self.root/'probability-index.json'
        self.prediction = dict(id='frame', modelId=self.model['id'], inputSha256=self.frame['graySha256'],
            imageSha256='b'*64, width=64, height=64, probabilityPath=str(self.prob), probabilitySha256=subject.paint.sha(self.prob))
        self.write_index()

    def write_masks(self):
        for name, a in [('paint', self.truth), ('valid', self.valid)]:
            path = self.root/(name+'.png'); cv2.imwrite(str(path), a.astype(np.uint8)*255)
            self.target[name+'MaskPath'] = str(path); self.target[name+'MaskSha256'] = subject.paint.sha(path)

    def write_inputs(self):
        self.manifest.write_text(json.dumps(dict(schemaVersion=1, frames=[self.frame])))
        self.targets.write_text(json.dumps(dict(schemaVersion=1, targets=[self.target])))

    def write_index(self):
        self.index.write_text(json.dumps(dict(schemaVersion=1, models=[self.model], predictions=[self.prediction])))

    def test_known_counts_and_fixed_tolerance(self):
        pred = np.zeros_like(self.truth); pred[40:50, 18] = True
        exact = subject.support_counts(pred, self.truth, self.valid, 0)
        tolerant = subject.support_counts(pred, self.truth, self.valid, 2)
        self.assertEqual(exact['predictedCenterlinePixels'], 10)
        self.assertEqual(exact['supportedCenterlinePixels'], 0)
        self.assertEqual(tolerant['supportedCenterlinePixels'], 10)
        self.assertEqual(tolerant['coveredPaintPixels'], 12)  # Fixed OpenCV ellipse includes end-adjacent rows.
        with self.assertRaisesRegex(ValueError, 'Unfrozen'):
            subject.support_counts(pred, self.truth, self.valid, 1)

    def test_unknown_predictions_never_cover_truth(self):
        pred = np.zeros_like(self.truth); pred[40:50, 17] = True
        self.valid[:, 17] = False
        c = subject.support_counts(pred, self.truth, self.valid)
        self.assertEqual(c['predictedCenterlinePixels'], 0)
        self.assertEqual(c['ignoredUnknownCenterlinePixels'], 10)
        self.assertEqual(c['coveredPaintPixels'], 0)

    def test_unknown_truth_never_supports_predictions(self):
        pred = np.zeros_like(self.truth); pred[40:50, 17] = True
        self.valid[:, 16] = False
        c = subject.support_counts(pred, self.truth, self.valid)
        self.assertEqual(c['annotatedPaintPixels'], 0)
        self.assertEqual(c['supportedCenterlinePixels'], 0)

    def test_empty_observed_does_not_fall_back_to_fitted_geometry(self):
        masks = {'frame': (self.truth, self.valid)}
        r = subject.score_rows([self.row], [self.target], masks)
        geom = r['raw.geometry.radius2']['byDataset']['ZOD']
        observed = r['raw.observed.radius2']['byDataset']['ZOD']
        self.assertGreater(geom['predictedCenterlinePixels'], 0)
        self.assertEqual(observed['predictedCenterlinePixels'], 0)
        self.assertIsNone(observed['centerlineSupportPrecision'])
        self.assertEqual(r['visible.geometry.radius2']['byDataset']['ZOD']['predictedCenterlinePixels'], 0)

    def test_explicit_observation_gaps_are_not_filled(self):
        b = dict(self.boundary, observedSegments=[[[16/63, .58], [16/63, .65]], [[16/63, .85], [16/63, .95]]])
        fitted = subject.paint.rasterize([b], 64, 64, 'geometry')
        observed = subject.paint.rasterize([b], 64, 64, 'observed')
        self.assertTrue(fitted[47, 16]); self.assertFalse(observed[47, 16])

    def test_reject_changed_input_unknown_label_and_duplicate_ids(self):
        subject.load_inputs(self.manifest, self.targets)
        self.gray.write_bytes(bytes([1])*(64*64))
        with self.assertRaisesRegex(ValueError, 'Input bytes'):
            subject.load_inputs(self.manifest, self.targets)
        self.gray.write_bytes(bytes(64*64))
        self.valid[:, 16] = False; self.write_masks(); self.write_inputs()
        with self.assertRaisesRegex(ValueError, 'Paint outside valid'):
            subject.load_inputs(self.manifest, self.targets)
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            subject.unique([self.frame, self.frame], 'test')

    def test_native_order_exposure_visibility_are_bound(self):
        subject.load_native(self.native, [self.frame])
        for patch in [dict(inputSha256='f'*64), dict(visibleBoundaryIndices=[0]), dict(time=1)]:
            self.native.write_text(json.dumps(dict(self.row, **patch))+'\n')
            with self.assertRaises(ValueError): subject.load_native(self.native, [self.frame])

    def test_probability_hash_range_shape_and_exposure_are_verified(self):
        subject.load_probabilities(self.index, [self.frame], [self.target])
        self.prediction['inputSha256'] = 'f'*64; self.write_index()
        with self.assertRaisesRegex(ValueError, 'exposure'):
            subject.load_probabilities(self.index, [self.frame], [self.target])
        self.prediction['inputSha256'] = self.frame['graySha256']
        np.save(self.prob, np.full((64,64), np.nan, np.float32))
        self.prediction['probabilitySha256'] = subject.paint.sha(self.prob); self.write_index()
        with self.assertRaisesRegex(ValueError, 'Invalid probability'):
            subject.load_probabilities(self.index, [self.frame], [self.target])

    def test_qualification_rejects_faults_and_binds_full_values(self):
        p = self.truth.astype(np.float32)*.9
        for kind, reason in [('missing','missing_hint'), ('stale','stale_hint'), ('wrong_generation','scope_mismatch')]:
            scores, why, _ = subject.qualify_scores(self.frame, [self.boundary], p, self.valid, 'model', 'revision', kind)
            self.assertIsNone(scores); self.assertEqual(why, reason)
        scores, why, compat = subject.qualify_scores(self.frame, [self.boundary], p, self.valid, 'model', 'revision', 'learned')
        self.assertEqual(why, 'qualified'); self.assertAlmostEqual(scores[0], .09, places=7)
        self.assertAlmostEqual(compat[0], .9, places=7)

    def test_uniform_control_has_same_scores_at_different_locations(self):
        p = np.full((64,64), .6, np.float32)
        b = dict(self.boundary, points=[[.8, .58], [.8, .95]])
        scores, _, _ = subject.qualify_scores(self.frame, [self.boundary, b], p, self.valid, 'm', 'r', 'uniform')
        self.assertEqual(scores[0], scores[1])

    def test_variant_manifests_exclude_truth_validity_from_learned_guidance(self):
        first, second = self.root/'variants1', self.root/'variants2'
        subject.prepare_variants(self.manifest, self.targets, self.index, self.native, first)
        # Remove all reviewed truth; the learned and uniform inputs must remain identical.
        self.truth[:] = False; self.valid[:] = False; self.write_masks(); self.write_inputs()
        subject.prepare_variants(self.manifest, self.targets, self.index, self.native, second)
        for kind in ('learned-', 'uniform-'):
            name = kind+self.model['id']+'.json'
            self.assertEqual((first/name).read_bytes(), (second/name).read_bytes())
        for kind in subject.FALLBACK:
            value = subject.read(first/(kind+'.json'))
            self.assertEqual(value['frames'], [self.frame])
        self.assertNotEqual((first/'reviewed-mask-oracle.json').read_bytes(), (second/'reviewed-mask-oracle.json').read_bytes())
        with self.assertRaisesRegex(ValueError, 'already exists'):
            subject.prepare_variants(self.manifest, self.targets, self.index, self.native, first)

    def test_fallback_checks_publication_budget_and_temporal_maturity(self):
        subject.assert_guidance_invariants([self.row], [self.row], True)
        for field in ('overlayPublished', 'geometryBudgetExceeded'):
            with self.assertRaisesRegex(ValueError, 'Rejected hint'):
                subject.assert_guidance_invariants([self.row], [dict(self.row, **{field:True})], True)
        changed = copy.deepcopy(self.row); changed['lanePresentation']['items'][0]['observationCount'] = 2
        with self.assertRaisesRegex(ValueError, 'maturity'):
            subject.assert_guidance_invariants([self.row], [changed])

    def test_roi_mask_metrics_exclude_unknown_and_outside_roi(self):
        p = np.zeros_like(self.truth, dtype=np.float32); p[:10] = 1; p[40:50,16] = 1
        self.valid[40:45,16] = False
        c = subject.segmentation_counts(p, self.truth, self.valid, roi=True)
        self.assertEqual(c['tp'], 5); self.assertEqual(c['fp'], 0)
        self.assertEqual(c['precision'], 1)
        self.assertGreater(subject.segmentation_counts(p, self.truth, self.valid)['fp'], 0)

    def test_suppression_probe_reports_discarded_supported_length(self):
        # A correct candidate with probability .49 is removed under the predeclared rule.
        np.save(self.prob, np.full((64,64), .49, np.float32))
        self.prediction['probabilitySha256'] = subject.paint.sha(self.prob); self.write_index()
        out = self.root/'probe.json'
        subject.probe_models(self.manifest, self.targets, self.index, self.native, out)
        result = subject.read(out)['models'][0]
        self.assertEqual(result['candidates'][0]['retainedPaintCandidates'], 0)
        self.assertEqual(result['candidates'][0]['rejectedPaintCandidates'], 1)
        discarded = result['rejected']['raw.geometry.radius2']['byDataset']['ZOD']
        self.assertGreater(discarded['supportedCenterlinePixels'], 0)
        self.assertEqual(result['retained']['raw.geometry.radius2']['byDataset']['ZOD']['predictedCenterlinePixels'], 0)


if __name__ == '__main__':
    unittest.main()
