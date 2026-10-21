import importlib.util
from pathlib import Path
import unittest

spec=importlib.util.spec_from_file_location('mobidata_review',Path(__file__).resolve().parents[2]/'scripts/tsr/mobidata_review.py')
review=importlib.util.module_from_spec(spec);spec.loader.exec_module(review)


def annotation(code, box):
    x,y,X,Y=box
    return {'id':'source-id','shape':{'type':'Polygon','coordinates':[[[x,y],[X,y],[X,Y],[x,Y],[x,y]]]},
            'semantics':[{'key':'osm|traffic_sign','value':code}]}


class TargetReviewTests(unittest.TestCase):
    def test_wrong_label_on_a_neighbour_does_not_become_a_town_sign_error(self):
        r=review.source_target_assessment([annotation('FR:J5',[30,30,40,40])],[0,0,10,10],'DE:311')
        self.assertEqual(r['source_target_status'],'no_stored_target_box')
        self.assertEqual(r['source_target_original_codes'],[])
    def test_wrong_label_requires_box_overlap(self):
        r=review.source_target_assessment([annotation('FR:C50',[0,0,10,10])],[0,0,10,10],'DE:310')
        self.assertEqual(r['source_target_status'],'detected_but_wrong_code_proposal')
        self.assertEqual(r['source_target_annotation_id'],'source-id')
    def test_unclassified_and_correct_class_are_distinguished(self):
        for code,status in [('yes','detected_but_unclassified_yes'),('DE:310','classified_expected_code')]:
            self.assertEqual(review.source_target_assessment([annotation(code,[0,0,10,10])],[0,0,10,10],'DE:310')['source_target_status'],status)
    def test_detector_confusion_is_separate_from_a_missing_sign(self):
        box=[0,0,10,10]
        self.assertEqual(review.baseline_target_assessment([[0,0,10,10,.9,1]],box)['sgblur_yolo11n_target_issue'],'wrong_object_class')
        self.assertEqual(review.baseline_target_assessment([],box)['sgblur_yolo11n_target_issue'],'missed_sign')
        self.assertEqual(review.baseline_target_assessment([[0,0,10,10,.9,0]],box)['sgblur_yolo11n_target_issue'],'detected_sign')
        self.assertEqual(review.iou(box,[0,0,float('nan'),10]),0)


if __name__=='__main__':unittest.main()
