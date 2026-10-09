import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

import cv2
import numpy as np

SCRIPTS = Path(__file__).parents[2] / 'scripts/lanes'
sys.path.insert(0,str(SCRIPTS))
import prepare_zod_lane_corpus as zod
import select_zod_lane_cohort as cohort


def row(identity, lat, split='train'):
    return {'frame_id':identity,'official_split':split,'latitude':lat,'longitude':10.,
            'collection_car':identity,'capture_date':'2020-01-01'}


class CohortTest(unittest.TestCase):
    def test_direct_day_purge_uses_outside_frames_without_transitive_closure(self):
        rows=[row('000001',0.,'val'),row('000002',.002,'blacklisted'),row('000003',.004),
              row('000004',30.,'val'),row('000005',40.),row('000006',50.),row('000007',.001,'blacklisted')]
        rows[-1]['collection_car']=rows[-2]['collection_car']
        selected,details,graph=cohort.choose_day_cohort(rows,['000005'],train_count=2,test_count=2,
            min_test_groups=2,target_test_groups=2)
        self.assertEqual({i for i,s in selected.items() if s=='train'},{'000003','000005'})
        self.assertNotIn('000006',selected)  # Daymate outside cohort is near holdout.
        self.assertEqual({i for i,s in selected.items() if s=='test'},{'000001','000004'})
        self.assertTrue(all(e['spherical_distance_m']<=250.000001 for e in graph['edges']))
        expected=set()
        for i,a in enumerate(rows):
            for b in rows[:i]:
                if a['group_id']!=b['group_id'] and zod.distance_m(a,b)<=250.:
                    expected.add(tuple(sorted((a['group_id'],b['group_id']))))
        self.assertEqual(expected,{tuple(e['nodes']) for e in graph['edges']})

    def test_outside_bridge_and_exposure_components_cannot_leak_into_holdout(self):
        rows=[row('000001',1.,'val'),row('000002',1.002,'blacklisted'),row('000003',1.004,'val'),
              row('000004',3.),row('000005',5.,'val'),row('000006',5.001),
              row('000007',7.,'val'),row('000008',9.),row('000009',11.)]
        args=dict(exposure_ids=['000001'],train_count=2,test_count=2,min_test_groups=2,target_test_groups=2,
                  excluded_train_ids=['000008'])
        selected, details=cohort.choose_cohort(copy.deepcopy(rows),**args)
        self.assertNotIn('000003',selected)
        self.assertNotIn('000006',selected)
        self.assertNotIn('000008',selected)
        self.assertEqual({i for i,s in selected.items() if s=='test'},{'000005','000007'})
        reverse,_=cohort.choose_cohort(list(reversed(copy.deepcopy(rows))),**args)
        self.assertEqual(selected,reverse)
        self.assertEqual(details['full_source_count'],9)

    def test_insufficient_groups_fails_instead_of_weakening_protocol(self):
        rows=[row('000001',1.),row('000002',3.,'val'),row('000003',5.)]
        with self.assertRaisesRegex(ValueError,'Insufficient disjoint fresh cohort'):
            cohort.choose_cohort(rows,['000001'],train_count=1,test_count=2,min_test_groups=2,target_test_groups=2)

    def fixture(self, base, grouping_mode='components-v1'):
        source=base/'source'; source.mkdir()
        data={'train':[],'val':[]}
        for i in range(16):
            identity=f'{i:06d}'; split='train' if i<8 else 'val'
            prefix=f'single_frames/{identity}'
            path=source/prefix; path.mkdir(parents=True)
            timestamp='2020-01-01T12:00:00+00:00'
            metadata={'frame_id':identity,'collection_car':identity,'time':timestamp,'latitude':20.+i,'longitude':10.}
            (path/'metadata.json').write_text(json.dumps(metadata))
            data[split].append({'id':identity,'metadata_path':prefix+'/metadata.json','keyframe_time':timestamp,
                'annotations':{'lane_markings':{'project':'lane_markings','filepath':prefix+'/lanes.json'}},
                'camera_frames':{'front_blur':[{'filepath':prefix+'/image.jpg','time':timestamp,'width':12,'height':12}]}})
        full=source/'full.json';full.write_text(json.dumps(data))
        exposed=base/'exposed.json'; exposed.write_text(json.dumps({'schemaVersion':1,'frame_ids':['000000']}))
        output=base/'cohort'
        selected=cohort.select(source,full,exposed,output,train_count=4,test_count=4,
            min_test_groups=2,target_test_groups=2,full_review_train_count=2,expected_source_frames=16,grouping_mode=grouping_mode)
        # Full metadata suffice for selection; download only selected assets later.
        for r in selected['selected']:
            path=source/'single_frames'/r['frame_id']
            cv2.imwrite(str(path/'image.jpg'),np.full((12,12,3),int(r['frame_id'])+20,np.uint8))
            (path/'lanes.json').write_text(json.dumps([{'geometry':{'coordinates':[[1,1],[3,1],[3,3],[1,3]]},
                'properties':{'annotation_uuid':r['frame_id'],'class':'lm_dashed'}}]))
        receipt=base/'receipt.json'
        qa=[]
        for r in selected['selected']:
            path=source/'single_frames'/r['frame_id']
            qa.append({'frame_id':r['frame_id'],'decision':'accept' if r['split']=='test' else 'positive_only',
                'reason':'Synthetic predeclared QA fixture','rgb_sha256':zod.sha256_file(path/'image.jpg'),
                'annotation_sha256':zod.sha256_file(path/'lanes.json')})
        receipt.write_text(json.dumps({'schemaVersion':1,'dataset':'ZOD','source_revision':'fixture',
            'source_url':'https://example.invalid/fixture','license':'CC BY-SA 4.0','geometry':'original-pixel-polygons',
            'annotation_coverage':'per_frame','coverage_evidence':'Synthetic scoped fixture',
            'cohort_selection_sha256':zod.sha256_file(output/'cohort.json'),
            'frame_qa':{'trainval_sha256':zod.sha256_file(output/'selected-trainval.json'),'frames':qa}}))
        return source,output,receipt,selected

    def test_full_metadata_selection_import_and_positive_only_train(self):
        with tempfile.TemporaryDirectory() as directory:
            base=Path(directory);source,selection,receipt,chosen=self.fixture(base)
            result=zod.prepare(source,selection/'selected-trainval.json',receipt,base/'prepared',cohort_selection_path=selection/'cohort.json')
            self.assertTrue(result['training_eligible'])
            self.assertEqual(result['partition_counts'],{'train':4,'validation':0,'test':4})
            self.assertEqual(result['coverage_counts']['train']['positive_only']['negative_pixels'],0)
            self.assertEqual(result['cohort_selection']['grouping']['full_source_count'],16)
            self.assertEqual(len(chosen['qa_plan']['full_review_train_ids']),2)
            self.assertTrue(result['cohort_post_qa_gate']['passed'])

    def test_v2_cohort_import_rebuilds_complete_day_graph_and_checks_proof(self):
        for tamper in (False,True):
            with self.subTest(tamper=tamper),tempfile.TemporaryDirectory() as directory:
                base=Path(directory);source,selection,receipt,chosen=self.fixture(base,'vehicle-day-direct-v2')
                if tamper:
                    path=selection/'full-source-day-graph.json'
                    graph=json.loads(path.read_text())
                    graph['edges'].append({'nodes':[graph['nodes'][0]['day_id'],graph['nodes'][1]['day_id']],
                        'witness_frame_ids':['000000','000001'],'spherical_distance_m':1.})
                    path.write_text(json.dumps(graph))
                    chosen['full_source_graph_sha256']=zod.sha256_file(path)
                    (selection/'cohort.json').write_text(json.dumps(chosen))
                    d=json.loads(receipt.read_text());d['cohort_selection_sha256']=zod.sha256_file(selection/'cohort.json');receipt.write_text(json.dumps(d))
                    with self.assertRaisesRegex(ValueError,'proof mismatch'):
                        zod.prepare(source,selection/'selected-trainval.json',receipt,base/'prepared',cohort_selection_path=selection/'cohort.json')
                else:
                    result=zod.prepare(source,selection/'selected-trainval.json',receipt,base/'prepared',cohort_selection_path=selection/'cohort.json')
                    self.assertTrue(result['training_eligible'])
                    self.assertEqual(result['cohort_selection']['kind'],'predeclared-full-source-day-cohort-v2')

    def test_cohort_sidecar_hash_metadata_and_qa_binding_fail_closed(self):
        for mutation in ('groups','metadata','receipt'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                base=Path(directory);source,selection,receipt,chosen=self.fixture(base)
                if mutation=='groups':
                    with (selection/'full-source-groups.json').open('a') as stream: stream.write(' ')
                elif mutation=='metadata':
                    p=source/'single_frames'/chosen['selected'][0]['frame_id']/'metadata.json'
                    d=json.loads(p.read_text());d['latitude']+=.5;p.write_text(json.dumps(d))
                else:
                    d=json.loads(receipt.read_text());d['cohort_selection_sha256']='0'*64;receipt.write_text(json.dumps(d))
                with self.assertRaisesRegex(ValueError,'hash|bind'):
                    zod.prepare(source,selection/'selected-trainval.json',receipt,base/'prepared',cohort_selection_path=selection/'cohort.json')

    def test_qa_cannot_promote_unplanned_training_frame_or_leave_too_few_holdout_groups(self):
        for mutation in ('unplanned_accept','excluded_holdout'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as directory:
                base=Path(directory);source,selection,receipt,chosen=self.fixture(base)
                data=json.loads(receipt.read_text())
                if mutation=='unplanned_accept':
                    identity=next(r['frame_id'] for r in chosen['selected'] if r['split']=='train'
                        and r['frame_id'] not in chosen['qa_plan']['full_review_train_ids'])
                    next(r for r in data['frame_qa']['frames'] if r['frame_id']==identity)['decision']='accept'
                    receipt.write_text(json.dumps(data))
                    with self.assertRaisesRegex(ValueError,'predeclared visual QA'):
                        zod.prepare(source,selection/'selected-trainval.json',receipt,base/'prepared',cohort_selection_path=selection/'cohort.json')
                else:
                    for item in [r for r in data['frame_qa']['frames'] if r['decision']=='accept'][1:]:
                        item['decision']='exclude';item['reason']='Synthetic negative coverage uncertainty'
                    receipt.write_text(json.dumps(data))
                    result=zod.prepare(source,selection/'selected-trainval.json',receipt,base/'prepared',cohort_selection_path=selection/'cohort.json')
                    self.assertFalse(result['cohort_post_qa_gate']['passed'])
                    self.assertFalse(result['training_eligible'])


if __name__=='__main__':
    unittest.main()
