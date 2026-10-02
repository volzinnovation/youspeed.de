import json
from pathlib import Path
import tempfile
import unittest

from compare_sustained_platforms import compare_runs, sha


class SustainedParityTests(unittest.TestCase):
    def fixture(self, root):
        manifest=root/'input.json'
        manifest.write_text(json.dumps({'frames':[{'id':'a','time':1.0},{'id':'b','time':1.1}]}))
        frame={'arm':'fragments','id':'a','sequenceId':'clip','index':0,'sourcePtsSeconds':1.0,
               'thermalPaused':False,'componentMs':3,'residentBytes':100,'visibleIds':[1],
               'selectedIndices':[0],'boundaries':[],'selectedBoundaries':[],'operationCount':20,
               'temporalOperationCount':2,'operationBudgetExceeded':False,'selectionDecisions':[],
               'lanePreparationDiagnostics':{}}
        second=dict(frame,id='b',index=1,sourcePtsSeconds=1.1)
        android=root/'android.ndjson'; iphone=root/'iphone.ndjson'
        for path in [android,iphone]:
            path.write_text('\n'.join(json.dumps(row) for row in [frame,second])+'\n')
            path.with_suffix('.json').write_text(json.dumps({'manifestSha256':sha(manifest)}))
        return android,iphone,manifest

    def test_platform_metadata_is_ignored_but_selection_difference_is_not(self):
        with tempfile.TemporaryDirectory() as directory:
            android,iphone,manifest=self.fixture(Path(directory))
            rows=[json.loads(line) for line in iphone.read_text().splitlines()]
            rows[0]['componentMs']=1000; rows[0]['residentBytes']=9999
            rows[0]['lanePresentation']={'selectionDecisions':rows[0].pop('selectionDecisions')}
            iphone.write_text('\n'.join(json.dumps(row) for row in rows))
            self.assertTrue(compare_runs(android,iphone,manifest)['matchingComparedPairs'])
            rows[1]['visibleIds']=[2]
            iphone.write_text('\n'.join(json.dumps(row) for row in rows))
            self.assertEqual(compare_runs(android,iphone,manifest)['mismatchedPairs'],1)

    def test_later_cycle_cannot_fill_a_thermally_paused_first_cycle(self):
        with tempfile.TemporaryDirectory() as directory:
            android,iphone,manifest=self.fixture(Path(directory))
            rows=[json.loads(line) for line in iphone.read_text().splitlines()]
            later=dict(rows[0],index=2)
            rows[0]['thermalPaused']=True
            iphone.write_text('\n'.join(json.dumps(row) for row in rows+[later]))
            report=compare_runs(android,iphone,manifest)
            self.assertTrue(report['matchingComparedPairs'])
            self.assertEqual(report['comparedPairs'],1)
            self.assertFalse(report['completeFirstCycleCoverage'])

    def test_manifest_mismatch_prevents_parity_claim(self):
        with tempfile.TemporaryDirectory() as directory:
            android,iphone,manifest=self.fixture(Path(directory))
            iphone.with_suffix('.json').write_text(json.dumps({'manifestSha256':'incorrect'}))
            self.assertFalse(compare_runs(android,iphone,manifest)['matchingComparedPairs'])


if __name__=='__main__':
    unittest.main()
