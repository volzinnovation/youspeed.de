import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts/tsr/sign_only_pilot'))
from benchmark_mapillary_auto import measure,reference_boxes
class PartialReferenceTests(unittest.TestCase):
    def test_duplicate_reference_and_unknown_scope(self):
        frame={'image_id':'one','group_id':'s','anchor':'a','width':2000,'height':1000,'proposals':[{'id':'1','scope':'classified_primary_candidate','box':[100,100,120,120]},{'id':'2','scope':'generic_front_scope_unknown','box':[100,100,120,120]},{'id':'3','scope':'generic_front_scope_unknown','box':[500,500,540,540]},{'id':'4','scope':'excluded_direction','box':[900,100,950,150]}]}
        self.assertEqual(len(reference_boxes(frame,'classified_primary')),1);self.assertEqual(len(reference_boxes(frame,'broad_front')),2)
        raw=[{'image_id':'one','passes':[[{'box':[100,100,120,120],'score':.9},{'box':[500,500,540,540],'score':.9}]]}]
        a=measure([frame],raw,.5,'classified_primary');self.assertEqual(a['reference_coverage'],1);self.assertEqual(a['unmatched_predictions'],1)
        b=measure([frame],raw,.5,'broad_front');self.assertEqual(b['unmatched_predictions'],0)
    def test_empty_reference_is_not_certified_negative(self):
        f={'image_id':'none','group_id':'s','anchor':'a','width':1000,'height':1000,'proposals':[]};r={'image_id':'none','passes':[[{'box':[1,1,10,10],'score':.9}]]}
        score=measure([f],[r],.5,'classified_primary');self.assertIsNone(score['reference_coverage']);self.assertIsNone(score['all_available_reference_image_rate']);self.assertEqual(score['images_without_references'],1);self.assertEqual(score['unmatched_predictions'],1)
if __name__=='__main__':unittest.main()
