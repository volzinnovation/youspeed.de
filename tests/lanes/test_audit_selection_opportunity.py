import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('opportunity', Path(__file__).resolve().parents[2] / 'scripts/lanes/audit_selection_opportunity.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

SETTINGS = dict(schemaVersion=1, geometryToleranceX=.035, matchingMinimumOverlapY=.08,
                paintToleranceX=.025, paintEndpointToleranceY=.015, qualification='Approximate development fixture',
                reviewer='fixture')


def boundary(x):
    return dict(points=[[x, .60], [x, .94]], observedSegments=[], confidence=.5)


def border(x, side='left'):
    return dict(geometry=[[x, .60], [x, .94]], paintedYIntervals=[[.60, .94]], side=side)


def row(raw, reasons, visible=(), sides=None):
    sides = sides or ['left'] * len(raw)
    decisions = [dict(boundaryIndex=i, reason=reason, side=sides[i] if reason not in m.GATES else 'none',
                      score=.5 if reason not in m.GATES else None) for i, reason in enumerate(reasons)]
    return dict(id='a', sequenceId='drive', time=0., split='development', inputSha256='h',
                sceneTags=['fixture'], width=64, height=64, rawBoundaries=raw,
                confirmedBoundaries=[raw[i] for i in visible], visibleBoundaryIndices=list(visible),
                visibleIDs=[100+i for i in visible], lanePresentation=dict(selectionDecisions=decisions))


def label(borders):
    return dict(id='a', sequenceId='drive', time=0., split='development', inputSha256='h',
                evaluationYRange=[.58, .95], borders=borders, ignoreGeometry=[])


class OpportunityTests(unittest.TestCase):
    def test_missing_candidate_is_not_called_extraction_failure(self):
        result = m.frame_inventory(row([], []), label([border(.3)]), SETTINGS)
        self.assertEqual(result['truthInventory'][0]['stage'], 'no_post_temporal_match')
        self.assertEqual(m.aggregate([result])['looseOptimisticScoreCompetitionMissCeiling'], 0)

    def test_scored_competition_maturity_and_hold_remain_separate(self):
        for reason, expected in [('not_mature', 'not_mature'), ('incumbent_reacquisition_hold', 'temporal_hold'),
                                 ('lower_side_score', 'score_competition'), ('challenger_margin_or_dwell', 'score_margin_or_temporal_dwell'),
                                 ('confidence', 'other_gate')]:
            with self.subTest(reason=reason):
                result = m.frame_inventory(row([boundary(.3)], [reason]), label([border(.3)]), SETTINGS)
                self.assertEqual(result['truthInventory'][0]['stage'], expected)
                self.assertEqual(m.aggregate([result])['looseOptimisticScoreCompetitionMissCeiling'], int(expected == 'score_competition'))

    def test_one_boundary_cannot_recover_two_truth_instances(self):
        result = m.frame_inventory(row([boundary(.31)], ['not_mature']), label([border(.3), border(.32)]), SETTINGS)
        self.assertEqual(sorted(t['stage'] for t in result['truthInventory']), ['candidate_assignment_conflict', 'not_mature'])

    def test_displayed_match_is_not_stolen_by_unselected_duplicate(self):
        r = row([boundary(.3), boundary(.301)], ['selected', 'lower_side_score'], [0])
        result = m.frame_inventory(r, label([border(.3)]), SETTINGS)
        self.assertEqual(result['truthInventory'][0]['stage'], 'visible_match')
        self.assertEqual(result['truthInventory'][0]['assignedBoundaryIndex'], 0)
        self.assertEqual(m.aggregate([result])['looseOptimisticScoreCompetitionMissCeiling'], 0)

    def test_wrong_visible_replacement_requires_same_side_scored_candidate(self):
        r = row([boundary(.7), boundary(.3)], ['selected', 'lower_side_score'], [0], ['right', 'left'])
        result = m.frame_inventory(r, label([border(.3)]), SETTINGS)
        self.assertEqual(result['wrongVisibleSelections'][0]['matchingScoredSameSideAlternatives'], [])
        r['lanePresentation']['selectionDecisions'][0]['side'] = 'left'
        result = m.frame_inventory(r, label([border(.3)]), SETTINGS)
        self.assertEqual(len(result['wrongVisibleSelections'][0]['matchingScoredSameSideAlternatives']), 1)
        self.assertEqual(m.aggregate([result])['wrongSelectionsWithCompetitionAlternative'], 1)

    def test_ignored_geometry_is_not_a_wrong_selection(self):
        l = label([])
        l['ignoreGeometry'] = [dict(points=[[.7,.6],[.7,.94]], tolerance=.02)]
        result = m.frame_inventory(row([boundary(.7)], ['selected'], [0]), l, SETTINGS)
        self.assertEqual(result['wrongVisibleSelections'], [])
        self.assertEqual(result['baseline']['ignoredPredictions'], 1)

    def test_unknown_reason_and_inconsistent_visible_geometry_rejected(self):
        r = row([boundary(.3)], ['selected'], [0])
        m.validate_boundaries(r)
        bad = copy.deepcopy(r)
        bad['confirmedBoundaries'] = [boundary(.5)]
        with self.assertRaisesRegex(ValueError, 'differs from selected'):
            m.validate_boundaries(bad)
        bad = copy.deepcopy(r)
        bad['lanePresentation']['selectionDecisions'][0]['reason'] = 'new_policy'
        with self.assertRaisesRegex(ValueError, 'Unknown selection reason'):
            m.validate_boundaries(bad)

    def test_dense_duration_intersects_segments_not_just_vertices(self):
        r = row([dict(boundary(.3), points=[[.3,.5],[.3,1.]])], ['selected'], [0])
        labels = dict(qualification='fixture', intervals=[dict(sequenceId='drive', startSeconds=0., endSeconds=1.,
            evaluationYRange=[.58,.95], frameIDs=['a'], inputSha256={'a':'h'})])
        result = m.dense_negative([r], labels)
        self.assertAlmostEqual(result['unsupportedVisibleDurationSeconds'], .2)
        r['confirmedBoundaries'][0]['observedSegments'] = [[[.3,.50],[.3,.55]]]
        self.assertEqual(m.dense_negative([r], labels)['unsupportedVisibleDurationSeconds'], 0)
        labels['intervals'][0]['inputSha256']['a'] = 'changed'
        with self.assertRaisesRegex(ValueError, 'identity/hash'):
            m.dense_negative([r], labels)

    def test_negative_missing_or_duplicate_frame_fails(self):
        labels = dict(qualification='fixture', intervals=[dict(sequenceId='drive', startSeconds=0., endSeconds=1.,
            evaluationYRange=[.58,.95], frameIDs=['a'], inputSha256={'a':'h'})])
        with self.assertRaisesRegex(ValueError, 'Missing/duplicate'):
            m.dense_negative([], labels)
        labels['intervals'][0]['frameIDs'].append('a')
        with self.assertRaisesRegex(ValueError, 'Overlapping'):
            m.dense_negative([row([], [])], labels)

    def test_overlapping_negative_time_windows_cannot_double_count(self):
        interval = dict(sequenceId='drive', startSeconds=0., endSeconds=1.,
                        evaluationYRange=[.58,.95], frameIDs=['a'], inputSha256={'a':'h'})
        other = dict(interval, startSeconds=.5, endSeconds=1.5, frameIDs=['b'], inputSha256={'b':'h'})
        with self.assertRaisesRegex(ValueError, 'Overlapping negative time intervals'):
            m.dense_negative([row([], []), dict(row([], []), id='b', time=.5)],
                             dict(qualification='fixture', intervals=[interval, other]))


class BoundReplayTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.replay = self.root/'replay'
        (self.replay/'sources').mkdir(parents=True)
        code = self.replay/'sources'/'fixture.swift'
        code.write_text('// frozen source\n')
        gray = self.root/'frame.gray'
        gray.write_bytes(bytes(64*64))
        self.digest = m.sha(gray)
        f = dict(id='a', sequenceId='drive', split='development', time=0., width=64, height=64,
                 decodedWidth=64, decodedHeight=64, grayPath=str(gray), graySha256=self.digest)
        self.original = self.root/'source.json'
        m.write_json(self.original, dict(schemaVersion=1, frames=[f]))
        self.options = dict(previewMode=True, useSearchBands=False, groupFragments=False,
                            fragmentTracking=False, retainTentativeIdentity=False, jointSelection=False)
        self.normalized = dict(schemaVersion=1, variant='baseline', frames=[f], **self.options)
        m.write_json(self.replay/'input.normalized.json', self.normalized)
        self.metadata = dict(schemaVersion=1, manifest=str(self.original), manifestSha256=m.sha(self.original),
                             normalizedManifestSha256=m.sha(self.replay/'input.normalized.json'),
                             variant='baseline', frameCount=1, sourceHashes={code.name:m.sha(code)}, **self.options)
        m.write_json(self.replay/'metadata.json', self.metadata)
        self.r = row([boundary(.3)], ['selected'], [0])
        self.r.update(schemaVersion=1, variant='baseline', decodedWidth=64, decodedHeight=64, inputSha256=self.digest)
        del self.r['split']  # Real native output obtains split from the bound manifest.
        self.write_rows([self.r])
        self.labels = self.root/'labels.json'
        self.l = label([border(.3)])
        self.l['inputSha256'] = self.digest
        m.write_json(self.labels, dict(SETTINGS, frames=[self.l]))

    def write_rows(self, rows):
        (self.replay/'frames.ndjson').write_text(''.join(json.dumps(r)+'\n' for r in rows))

    def test_full_run_binds_inputs_and_keeps_decision_deferred(self):
        report = m.run(self.replay, self.labels, None, self.root/'audit')
        self.assertEqual(report['decision'], 'DEFER')
        self.assertEqual(report['overall']['truthStages']['visible_match'], 1)
        self.assertIsNone(report['overall']['labelled']['unsupportedVisibleDurationSeconds'])
        self.assertEqual(report['bySplit']['development']['labelled']['truePositive'], 1)
        self.assertTrue((self.root/'audit'/'summary.json').exists())
        with self.assertRaisesRegex(ValueError, 'Output directory exists'):
            m.run(self.replay, self.labels, None, self.root/'audit')

    def test_replay_timestamp_cannot_drift_from_manifest(self):
        self.r['time'] = .01
        self.write_rows([self.r])
        with self.assertRaisesRegex(ValueError, 'identity mismatch: time'):
            m.load_replay(self.replay)

    def test_duplicate_replay_ids_fail(self):
        self.write_rows([self.r, self.r])
        with self.assertRaisesRegex(ValueError, 'Duplicate replay'):
            m.load_replay(self.replay)

    def test_changed_luma_bytes_fail(self):
        (self.root/'frame.gray').write_bytes(bytes([1]) * (64*64))
        with self.assertRaisesRegex(ValueError, 'Luma hash/size mismatch'):
            m.load_replay(self.replay)

    def test_changed_frozen_source_fails(self):
        (self.replay/'sources'/'fixture.swift').write_text('// changed')
        with self.assertRaisesRegex(ValueError, 'Frozen source hash mismatch'):
            m.load_replay(self.replay)

    def test_changed_normalized_manifest_fails(self):
        self.normalized['frames'][0]['time'] = .01
        m.write_json(self.replay/'input.normalized.json', self.normalized)
        with self.assertRaisesRegex(ValueError, 'Normalized manifest hash mismatch'):
            m.load_replay(self.replay)

    def test_changed_label_binding_fails_for_hash_time_split_sequence(self):
        for key, value in [('inputSha256', 'changed'), ('time', .02), ('split', 'test'), ('sequenceId', 'other')]:
            with self.subTest(key=key):
                bad = dict(self.l, **{key:value})
                m.write_json(self.labels, dict(SETTINGS, frames=[bad]))
                with self.assertRaises(ValueError):
                    m.run(self.replay, self.labels, None, self.root/'audit')
                self.assertFalse((self.root/'audit').exists())

    def test_unlabelled_frame_is_excluded_not_assumed_negative(self):
        frame2 = dict(self.normalized['frames'][0], id='b', time=.1)
        self.normalized['frames'].append(frame2)
        m.write_json(self.original, dict(schemaVersion=1, frames=self.normalized['frames']))
        m.write_json(self.replay/'input.normalized.json', self.normalized)
        self.metadata.update(frameCount=2, manifestSha256=m.sha(self.original), normalizedManifestSha256=m.sha(self.replay/'input.normalized.json'))
        m.write_json(self.replay/'metadata.json', self.metadata)
        self.write_rows([self.r, dict(self.r, id='b', time=.1)])
        report = m.run(self.replay, self.labels, None, self.root/'audit')
        self.assertEqual(report['unlabelledFramesExcludedFromAccuracy'], 1)
        self.assertEqual(report['overall']['labelled']['labelledFrames'], 1)


if __name__ == '__main__':
    unittest.main()
