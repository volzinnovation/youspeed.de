import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

SCRIPTS=Path(__file__).resolve().parents[2]/'scripts/lanes'
sys.path.insert(0,str(SCRIPTS))
import compare_still_lane_platforms as comparison


class StillContractTests(unittest.TestCase):
    def setUp(self):
        self.temporary=tempfile.TemporaryDirectory();self.root=Path(self.temporary.name)
        raw=bytes([40])*(192*108);(self.root/'frame.gray').write_bytes(raw)
        self.frame=dict(id='one',sequenceId='one',time=0.0,grayPath='frame.gray',graySha256=hashlib.sha256(raw).hexdigest(),width=192,height=108,decodedWidth=1920,decodedHeight=1080)
    def tearDown(self):self.temporary.cleanup()
    def normalize(self,frames=None,mode='preview',**extra):
        path=self.root/'input.json';path.write_text(json.dumps(dict(schemaVersion=1,frames=frames or [self.frame],**extra)))
        return comparison.normalized_manifest(path,mode)
    def test_independent_stills_preserve_order_hash_and_source_metadata(self):
        frames=[dict(self.frame,id=name,sequenceId=name,dataset='A2D2',groupId='source-day') for name in ('one','two')]
        result=self.normalize(frames)
        self.assertEqual([f['id'] for f in result['frames']],['one','two'])
        self.assertTrue(all(f['time']==0 and f['sequenceId']==f['id'] for f in result['frames']))
        self.assertEqual(result['frames'][0]['graySha256'],self.frame['graySha256'])
        self.assertEqual(result['frames'][0]['groupId'],'source-day')
        self.assertTrue(Path(result['frames'][0]['grayPath']).is_absolute())
    def test_repeated_sequence_or_synthetic_later_time_cannot_create_confirmation(self):
        for changes in ({'sequenceId':'sequence'},{'time':0.1},{'time':False}):
            with self.subTest(changes=changes),self.assertRaisesRegex(ValueError,'Each still'):
                self.normalize([dict(self.frame,**changes)])
        with self.assertRaisesRegex(ValueError,'unique'):self.normalize([self.frame,self.frame])
    def test_semantic_scores_require_same_pixels_and_preview_session(self):
        candidate=dict(self.frame,semanticScoreAdjustments=[0,.1],semanticSourceInputSha256=self.frame['graySha256'])
        self.assertEqual(self.normalize([candidate])['frames'][0]['semanticScoreAdjustments'],[0,.1])
        for changed in (dict(candidate,semanticSourceInputSha256='0'*64),dict(candidate,semanticScoreAdjustments=[.1001]),dict(candidate,semanticScoreAdjustments=[True])):
            with self.assertRaises(ValueError):self.normalize([changed])
        with self.assertRaisesRegex(ValueError,'preview-only'):self.normalize([candidate],mode='tsr')
    def test_original_pixel_geometry_and_no_invented_metadata(self):
        for changes in ({'graySha256':'0'*64},{'decodedWidth':100},{'calibration':{'fx':1}},{'locationFixes':[{'time':0}]},{'variant':'paint_mask'}):
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.normalize([dict(self.frame,**changes)])
        with self.assertRaisesRegex(ValueError,'app callsite'):self.normalize(useSearchBands=True)
    def test_comparison_retains_all_semantic_flags_and_exact_numbers(self):
        original={'visible':[0],'count':1,'accepted':False,'value':.1}
        self.assertEqual(comparison.differences(original,copy.deepcopy(original)),[])
        for changed in (dict(original,accepted=True),dict(original,value=.100000000000001),dict(original,visible=[])):
            self.assertTrue(comparison.differences(original,changed))
        self.assertEqual(comparison.differences({'count':1},{'count':1.0}),[])

if __name__=='__main__':unittest.main()
