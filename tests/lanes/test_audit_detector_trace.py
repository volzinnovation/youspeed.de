import copy
import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('detector_audit', Path(__file__).resolve().parents[2] / 'scripts/lanes/audit_detector_trace.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

SETTINGS = dict(geometryToleranceX=.035, matchingMinimumOverlapY=.08)
BORDER = dict(geometry=[[.3,.6],[.3,.94]], paintedYIntervals=[[.6,.94]])


def fixture():
    centers = [59,55,51,47,43,39,35,31]
    events = [dict(stage='configuration',schemaVersion=1,width=64,height=64,samplingRows=centers)]
    samples = []
    for row, pixel in enumerate(centers):
        sample = dict(sampleID=row*64+19,row=row,point=[19/63,pixel/63],strength=100.,cue='paint',stripeWidth=1)
        samples.append(sample)
        events.append(dict(stage='row',row=row,y=pixel/63,preCap=[sample],postCap=[sample]))
        events.append(dict(stage='association',outcome='created' if row == 0 else 'assigned',row=row,sampleID=sample['sampleID'],trackID=19))
    events.append(dict(stage='track',trackID=19,samples=samples,outcome='track_span'))
    events.append(dict(stage='completion',status='complete',operationCount=123))
    return dict(width=64,height=64,detectorTrace=events)


class DetectorTraceTests(unittest.TestCase):
    def test_valid_trace_and_rejected_measured_track(self):
        trace=m.validate_trace(fixture())
        result=m.border_diagnostic(trace,BORDER,SETTINGS)
        self.assertEqual(result['stage'],'associated_track_rejected')
        self.assertEqual(result['matchingAssociatedTracks'][0]['outcome'],'track_span')
        self.assertEqual(result['rowsLosingAllNearbyStripesAtCap'],0)
        self.assertEqual(result['tracksTouchingNearbySamples'][0]['totalSampleCount'],8)

    def test_rejects_mutated_post_cap_sample(self):
        row=fixture()
        event=next(e for e in row['detectorTrace'] if e['stage']=='row')
        event['postCap']=copy.deepcopy(event['postCap'])
        event['postCap'][0]['strength']+=1
        with self.assertRaisesRegex(ValueError,'differs from observed'):
            m.validate_trace(row)

    def test_rejects_missing_association_and_unknown_track(self):
        row=fixture()
        row['detectorTrace']=[e for e in row['detectorTrace'] if not(e['stage']=='association' and e['row']==2)]
        with self.assertRaisesRegex(ValueError,'association disposition'):
            m.validate_trace(row)
        row=fixture()
        next(e for e in row['detectorTrace'] if e['stage']=='association' and e['row']==1)['trackID']=999
        with self.assertRaisesRegex(ValueError,'absent track'):
            m.validate_trace(row)

    def test_rejects_missing_rows_and_completed_sample_changes(self):
        row=fixture()
        row['detectorTrace']=[e for e in row['detectorTrace'] if not(e['stage']=='row' and e['row']==2)]
        with self.assertRaisesRegex(ValueError,'sampling rows'):
            m.validate_trace(row)
        row=fixture()
        track=next(e for e in row['detectorTrace'] if e['stage']=='track')
        track['samples']=track['samples'][:-1]
        with self.assertRaisesRegex(ValueError,'association mismatch'):
            m.validate_trace(row)

    def test_cancelled_trace_is_not_complete_evidence(self):
        row=fixture()
        row['detectorTrace'][-1]['status']='budget_or_cancelled'
        with self.assertRaisesRegex(ValueError,'Incomplete'):
            m.validate_trace(row)

    def test_fresh_temporal_loss_and_output_capacity_stay_separate(self):
        trace=m.validate_trace(fixture())
        fresh=dict(origin='measured',points=[[.3,.6],[.3,.94]],outputIndex=0,confidence=.8,cue='paint',supportRows=9)
        trace['fresh']=[fresh]
        self.assertEqual(m.border_diagnostic(trace,BORDER,SETTINGS)['stage'],'fresh_match_lost_or_changed_in_temporal_fusion')
        fresh['outputIndex']=None
        self.assertEqual(m.border_diagnostic(trace,BORDER,SETTINGS)['stage'],'fresh_output_capacity')

    def test_nearby_samples_are_not_invented_into_a_lane(self):
        trace=m.validate_trace(fixture())
        trace['tracks']=[]
        self.assertEqual(m.border_diagnostic(trace,BORDER,SETTINGS)['stage'],'nearby_stripes_without_matching_associated_geometry')
        for row in trace['rows']:
            row['postCap']=[]
        self.assertEqual(m.border_diagnostic(trace,BORDER,SETTINGS)['stage'],'nearby_stripes_removed_by_row_cap')
        for row in trace['rows']:
            row['preCap']=[]
        self.assertEqual(m.border_diagnostic(trace,BORDER,SETTINGS)['stage'],'no_nearby_post_nms_stripes')

    def test_timing_exclusion_keeps_source_time_evidence_age_and_decisions(self):
        value=dict(time=12.,sourcePtsSeconds=12.,evidenceAgeSeconds=.4,deadlineExceeded=False,
                   filterMs=1.,detectorTrace=[{}],calibrationDiagnostics=dict(stageMs={'detector':1.},reason='unchanged'))
        filtered=m.without_trace_and_timing(value)
        self.assertEqual(filtered,dict(time=12.,sourcePtsSeconds=12.,evidenceAgeSeconds=.4,deadlineExceeded=False,
                         calibrationDiagnostics=dict(reason='unchanged')))
        different=copy.deepcopy(value)
        different['evidenceAgeSeconds']=.5
        self.assertNotEqual(filtered,m.without_trace_and_timing(different))


if __name__ == '__main__':
    unittest.main()
