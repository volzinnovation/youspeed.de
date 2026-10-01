import tempfile,gzip,hashlib,json,unittest
from pathlib import Path
from evaluate_fragment_replay import score_frame,aggregate_labelled,geometry_error,negative_duration,read_replay
from replay_recorded_pipeline import normalized_manifest
SETTINGS=dict(matchingMinimumOverlapY=.08,geometryToleranceX=.035,paintToleranceX=.025,paintEndpointToleranceY=0)
class FragmentEvaluationTests(unittest.TestCase):
 def test_gzip_archive_preserves_rows_and_original_content_hash(self):
  content=b'{"id":"a","points":[[0.3,0.7]]}\n\n{"id":"b"}\n'
  with tempfile.TemporaryDirectory() as d:
   plain=Path(d)/'frames.ndjson';archive=Path(d)/'frames.ndjson.gz';plain.write_bytes(content)
   with gzip.open(archive,'wb') as f:f.write(content)
   self.assertEqual(read_replay(plain),read_replay(archive))
   rows,digest=read_replay(archive);self.assertEqual([r['id'] for r in rows],['a','b']);self.assertEqual(digest,hashlib.sha256(content).hexdigest())
 def test_model_geometry_and_paint_support_are_separate(self):
  truth=dict(split='heldout',evaluationYRange=[.6,.95],borders=[dict(side='left',geometry=[[.3,.6],[.3,.95]],paintedYIntervals=[[.6,.7],[.85,.95]])])
  boundary=dict(points=[[.3,.6],[.3,.95]],observedSegments=[[[.3,.6],[.3,.7]],[[.3,.85],[.3,.95]]])
  row=dict(id='f',sequenceId='s',width=384,height=216,confirmedBoundaries=[boundary])
  sparse=score_frame(row,truth,SETTINGS);self.assertEqual(sparse['truePositive'],1);self.assertEqual(sparse['unsupportedLengthPixels'],0)
  boundary['observedSegments']=[];dense=score_frame(row,truth,SETTINGS);self.assertEqual(dense['truePositive'],1);self.assertGreater(dense['unsupportedLengthPixels'],20)
 def test_duplicate_prediction_is_false_positive(self):
  truth=dict(split='heldout',evaluationYRange=[.6,.95],borders=[dict(side='left',geometry=[[.3,.6],[.3,.95]],paintedYIntervals=[[.6,.95]])]);b=dict(points=[[.3,.6],[.3,.95]])
  r=score_frame(dict(id='f',sequenceId='s',width=384,height=216,confirmedBoundaries=[b,b]),truth,SETTINGS);self.assertEqual((r['truePositive'],r['falsePositive']),(1,1));self.assertIsNone(aggregate_labelled([r])['unsupportedVisibleDurationSeconds'])
 def test_dense_negative_duration_uses_only_reviewed_hashed_exposures(self):
  b=dict(points=[[.3,.6],[.3,.95]])
  rows=[dict(id='a',time=1,inputSha256='aa',confirmedBoundaries=[b]),dict(id='b',time=1.1,inputSha256='bb',confirmedBoundaries=[])]
  labels=dict(qualification='fixture',intervals=[dict(frameIDs=['a','b'],inputSha256={'a':'aa','b':'bb'},startSeconds=1,endSeconds=1.2,evaluationYRange=[.58,.95])])
  r=negative_duration(rows,labels);self.assertAlmostEqual(r['unsupportedVisibleDurationSeconds'],.1);self.assertAlmostEqual(r['reviewedDurationSeconds'],.2)
  rows[0]['inputSha256']='changed'
  with self.assertRaisesRegex(ValueError,'changed'):negative_duration(rows,labels)
 def test_no_geometry_extrapolation(self):self.assertIsNone(geometry_error([[.3,.6],[.3,.7]],[[.3,.8],[.3,.9]]))
 def test_optional_metadata_is_preserved_and_must_be_causal(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d);(p/'f.gray').write_bytes(bytes(64*64));f=dict(id='f',sequenceId='s',grayPath='f.gray',width=64,height=64,time=1,visualCalibration={'revision':'r'},metadataProvenance='fixture',locationFixes=[dict(time=.9)]);manifest=p/'manifest.json';manifest.write_text(json.dumps(dict(schemaVersion=1,frames=[f])))
   self.assertEqual(normalized_manifest(manifest,'x')['frames'][0]['visualCalibration'],{'revision':'r'})
   f['locationFixes'][0]['time']=1.1;manifest.write_text(json.dumps(dict(schemaVersion=1,frames=[f])))
   with self.assertRaisesRegex(ValueError,'causal'):normalized_manifest(manifest,'x')
if __name__=='__main__':unittest.main()
