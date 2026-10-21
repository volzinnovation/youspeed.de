import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import cv2
import numpy as np

spec = importlib.util.spec_from_file_location('audit', Path(__file__).resolve().parents[2] / 'scripts/lanes/audit_teacher_labels.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class TeacherAuditTests(unittest.TestCase):
    def test_support_ignore_and_outside_are_distinct(self):
        settings = dict(paintToleranceX=.025, paintEndpointToleranceY=.015)
        label = dict(evaluationYRange=[.58, .95], borders=[dict(geometry=[[.4,.6],[.4,.9]], paintedYIntervals=[[.65,.75]])],
                     ignoreGeometry=[dict(points=[[.7,.6],[.7,.9]], tolerance=.03)])
        self.assertEqual(m.classify([.41,.70], label, settings), 'supportedByReviewedBorder')
        self.assertEqual(m.classify([.4,.76], label, settings), 'supportedByReviewedBorder')
        self.assertEqual(m.classify([.4,.80], label, settings), 'unsupportedByReviewedBorders')
        self.assertEqual(m.classify([.7,.70], label, settings), 'ignoredGeometry')
        self.assertEqual(m.classify([.4,.50], label, settings), 'outsideEvaluationRange')

    def test_reviewed_identity_cannot_default_missing_hash(self):
        row = dict(id='a', sequenceId='s', split='development', time=0., inputSha256='hash')
        label = dict(row, evaluationYRange=[.58,.95], borders=[])
        m.bind_label(label, row)
        del label['inputSha256']
        with self.assertRaises(ValueError):
            m.bind_label(label, row)

    def test_negative_duration_caps_gaps_and_resets_runs(self):
        rows = [dict(id=str(i), sequenceId='s', time=t, inputSha256='hash', positivePoints=[dict(point=[.4,.7])]) for i,t in enumerate([0.,.1,.8])]
        labels = dict(qualification='fixture', intervals=[dict(sequenceId='s', startSeconds=0., endSeconds=1., evaluationYRange=[.58,.95],
                     frameIDs=['0','1','2'], inputSha256={str(i):'hash' for i in range(3)})])
        result = m.negative_scores(rows, labels)
        self.assertAlmostEqual(result['candidatePositiveDurationSeconds'], .5)
        self.assertAlmostEqual(result['longestPositiveRunSeconds'], .3)
        labels['intervals'][0]['inputSha256']['1'] = 'wrong'
        with self.assertRaises(ValueError):
            m.negative_scores(rows, labels)

    def test_negative_missing_frame_is_not_silently_skipped(self):
        labels = dict(qualification='fixture', intervals=[dict(sequenceId='s', startSeconds=0., endSeconds=1., evaluationYRange=[.58,.95], frameIDs=['missing'], inputSha256={'missing':'hash'})])
        with self.assertRaises(ValueError):
            m.negative_scores([], labels)

    def test_verified_mask_must_equal_declared_points(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            gray = root/'frame.gray'; gray.write_bytes(bytes(64*64))
            digest = hashlib.sha256(gray.read_bytes()).hexdigest()
            frame = dict(id='a', sequenceId='s', split='development', time=0., width=64, height=64, grayPath=str(gray), graySha256=digest)
            mask_path = root/'mask.png'; mask = np.zeros((64,64),np.uint8); mask[20,20] = 1
            cv2.imwrite(str(mask_path),mask)
            row = {k:frame[k] for k in ('id','sequenceId','split','time','width','height')}
            row.update(inputSha256=digest, maskPath='mask.png', maskSha256=m.sha(mask_path), negativePixelCount=0, unknownPixelCount=64*64,
                       positivePoints=[], supportSources=[])
            m.write_json(root/'metadata.json',dict(usesFutureFrames=False))
            m.write_json(root/'student-inputs.json',dict(frames=[frame]))
            (root/'annotations.ndjson').write_text(json.dumps(row)+'\n')
            with self.assertRaisesRegex(ValueError, 'mask/declared'):
                m.load_teacher(root)


if __name__ == '__main__':
    unittest.main()
