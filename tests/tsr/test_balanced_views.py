import importlib.util
import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts/tsr/sign_only_pilot'))
from balanced_views import transform_boxes,views_for,paired_schedules

class BalancedViewsTests(unittest.TestCase):
    def test_clipped_sign_rejects_entire_view(self):
        self.assertIsNone(transform_boxes([[95,20,105,40]],(0,0,100,100)))
        self.assertEqual(transform_boxes([[105,20,115,40]],(0,0,100,100)),[])
    def test_coordinate_roundtrip_and_phone_geometry(self):
        import mobile_replay as phone
        box=[1100,800,1140,840];window=[500,300,1500,1300]
        transformed=transform_boxes([box],window)[0]
        for a,b in zip(phone.source_box(transformed,window),box):self.assertAlmostEqual(a,b)
        views=views_for(4096,3072,[box])
        self.assertEqual([v['window'] for v in views if v['kind']=='phone'],[[0,0,3072,3072],[1024,0,4096,3072]])
        self.assertTrue(any(v['kind']=='small' and v['boxes'] for v in views))
    def test_paired_sources_balance_and_coverage(self):
        views=[]
        for i in range(10):
            for kind in ['phone','small']:
                views.append(dict(view_id=f'p{i}-{kind}',picture_id=f'p{i}',kind=kind,boxes=[[0,0,1,1]],parent_positive=True))
            views.append(dict(view_id=f'n{i}',picture_id=f'n{i}',kind='phone',boxes=[],parent_positive=False))
        schedules,pools=paired_schedules(views,epochs=3,draws=40)
        by_id={v['view_id']:v for v in views}
        self.assertEqual(schedules,paired_schedules(views,epochs=3,draws=40)[0])
        for epoch in schedules:
            self.assertEqual(sum(r['category']=='negative' for r in epoch),10)
            self.assertEqual(sum(r['category']=='small' for r in epoch),20)
            for r in epoch:
                self.assertEqual(by_id[r['phone']]['picture_id'],by_id[r['mixed']]['picture_id'])
                self.assertEqual(bool(by_id[r['phone']]['boxes']),bool(by_id[r['mixed']]['boxes']))
        self.assertEqual(len({r['picture_id'] for e in schedules for r in e}),20)

if __name__=='__main__':unittest.main()
