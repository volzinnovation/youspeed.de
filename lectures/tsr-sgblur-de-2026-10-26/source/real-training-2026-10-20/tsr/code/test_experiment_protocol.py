import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
from PIL import Image, ImageOps

HERE=Path(__file__).parent
sys.path.insert(0,str(HERE/'code'))
sys.path.insert(0,str(HERE))
import evaluate_reserved as evaluation
import prepare_experiment as preparation
import combine_predictions as combination


class ProtocolTests(unittest.TestCase):
    def test_joint_precision_counts_city_false_positives_on_old_test_without_inference(self):
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);old=root/'old';new=root/'new';old.mkdir();new.mkdir()
            metadata={'baseline_sha256':'baseline','candidate_sha256':'candidate'}
            for path in [old,new]: (path/'metrics.json').write_text(json.dumps(metadata))
            header='sample_id,group_id,true_label,baseline_label,candidate_label\n'
            (old/'predictions.csv').write_text(header+'o1,g1,arrow:red,arrow:red,city:start\n'+'o2,g2,arrow_left_down,arrow_left_down,arrow_left_down\n')
            (new/'predictions.csv').write_text(header+'c1,g3,city:start,bad,city:start\n')
            output=root/'joint'
            with patch.object(sys,'argv',['combine','--old-report',str(old),'--prospective-report',str(new),'--output',str(output)]):
                combination.main()
            result=json.loads((output/'metrics.json').read_text())
            self.assertFalse(result['new_model_inference'])
            self.assertEqual(result['views'],3)
            self.assertEqual(result['candidate']['per_class'][-2]['precision'],.5)
            self.assertEqual(result['candidate']['per_class'][-2]['recall'],1)

    def test_rare_three_group_class_retains_each_split_and_order_does_not_change_result(self):
        groups={f'{c}-{i}':[{'label':c}] for c in ['rare','common'] for i in range(3 if c=='rare' else 30)}
        a,counts=preparation.grouped_stratification(groups,['rare','common'])
        b,_=preparation.grouped_stratification(dict(reversed(list(groups.items()))),['rare','common'])
        self.assertEqual(a,b)
        for split in ['train','val','test']:
            self.assertGreater(counts[split]['rare'],0)
            self.assertGreater(counts[split]['common'],0)

    def test_duplicate_union_is_transitive(self):
        union=preparation.Union();union.join('c','b');union.join('b','a')
        self.assertEqual(union.find('c'),union.find('a'))

    def test_two_views_do_not_double_site_weight(self):
        rows=[{'site_id':'same'},{'site_id':'same'},{'site_id':'other'}]
        result=evaluation.grouped_summary(rows,[1,1,1],[1,0,1],'site_id')
        self.assertEqual(result['units'],2)
        self.assertEqual(result['mean_within_unit_accuracy'],.75)
        self.assertEqual(result['all_views_correct_units'],1)

    def fixture(self,folder):
        root=Path(folder);source=root/'full.png';crop=root/'crop.png'
        image=Image.new('RGB',(4,3),'red');image.putpixel((1,0),(0,0,255));image.save(source)
        image.crop((1,0,3,2)).save(crop)
        row={'sample_id':'keep','label':'city:start','group_id':'reserved-group','site_id':'site',
             'picture_id':'reserved-picture','subset':'native','review_type':'assistant_visual',
             'human_reviewed':False,'include_primary':True,'crop_absolute_path':str(crop),
             'crop_sha256':evaluation.sha256(crop),'input_image_absolute_path':str(source),
             'input_sha256':evaluation.sha256(source),'bbox_xyxy':[1,0,3,2]}
        # The removed row has no image path: excluded sources must never be opened or predicted.
        document={'frozen_before_candidate_predictions':True,'human_approved':False,
                  'rows':[row,{'sample_id':'excluded'}]}
        test=root/'test.json';test.write_text(json.dumps(document))
        overlay=root/'overlay.json'
        overlay.write_text(json.dumps({'parent_manifest_sha256':evaluation.sha256(test),
                                      'before_any_test_predictions_viewed':True,
                                      'exclusions':[{'sample_id':'excluded','reason':'ambiguous ground-truth label'}]}))
        manifest={'reserved_test_manifest_sha256':evaluation.sha256(test),'samples':[]}
        return test,overlay,manifest,row

    def test_frozen_overlay_filters_before_reading_excluded_pixels(self):
        with tempfile.TemporaryDirectory() as folder:
            test,overlay,manifest,row=self.fixture(folder)
            rows,_,_=evaluation.load_reviewed_rows(test,overlay,manifest,
                ['old']*134+['city:start','city:end'],Image,ImageOps)
            self.assertEqual([r['sample_id'] for r in rows],['keep'])

    def test_mismatched_binding_or_postprediction_exclusion_is_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            test,overlay,manifest,row=self.fixture(folder)
            classes=['old']*134+['city:start','city:end']
            manifest['reserved_test_manifest_sha256']='0'*64
            with self.assertRaises(ValueError): evaluation.load_reviewed_rows(test,overlay,manifest,classes,Image,ImageOps)
            manifest['reserved_test_manifest_sha256']=evaluation.sha256(test)
            value=json.loads(overlay.read_text());value['before_any_test_predictions_viewed']=False
            overlay.write_text(json.dumps(value))
            with self.assertRaises(ValueError): evaluation.load_reviewed_rows(test,overlay,manifest,classes,Image,ImageOps)

    def test_train_overlap_and_wrong_declared_crop_are_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            test,overlay,manifest,row=self.fixture(folder);classes=['old']*134+['city:start','city:end']
            manifest['samples']=[{'split':'train','sha256':row['crop_sha256'],'rgb_sha256':'other','group_id':'development','source_id':'different'}]
            with self.assertRaises(ValueError): evaluation.load_reviewed_rows(test,overlay,manifest,classes,Image,ImageOps)
            manifest['samples']=[]
            document=json.loads(test.read_text());document['rows'][0]['bbox_xyxy']=[0,0,2,2];test.write_text(json.dumps(document))
            manifest['reserved_test_manifest_sha256']=evaluation.sha256(test)
            v=json.loads(overlay.read_text());v['parent_manifest_sha256']=evaluation.sha256(test);overlay.write_text(json.dumps(v))
            with self.assertRaises(ValueError): evaluation.load_reviewed_rows(test,overlay,manifest,classes,Image,ImageOps)


if __name__=='__main__': unittest.main()
