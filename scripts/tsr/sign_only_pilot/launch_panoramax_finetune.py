#!/usr/bin/env python3
"""Start d10 only after d9 results publication and Mapillary benchmark completion."""
import hashlib,json,subprocess
from pathlib import Path
JOB=Path('/home/raphael/streetshots-d5-20261114');ROOT=JOB/'balanced-v1'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
    receipts={name:json.loads((JOB/'publication-receipts'/name).read_text()) for name in ['d9-balanced-results-model.json','d9-balanced-results-dataset.json','d10-panoramax-definition.json']}
    assert all(r['private'] and r['postverification'] and r['stage']=='complete' for r in receipts.values())
    receipt=receipts['d10-panoramax-definition.json'];definition=ROOT/'panoramax-definition.json';frozen=json.loads(definition.read_text());assert sha(definition)==receipt['manifest']['sha256']
    assert json.loads((ROOT/'mapillary-benchmark/complete.json').read_text())['complete']
    for name,digest in frozen['scripts'].items():assert sha(ROOT/'recipe'/name)==digest
    assert sha(ROOT/'data/corrected-sources.json')==frozen['dataset_manifest_sha256'];assert sha(ROOT/'data/views.json')==frozen['views_sha256'];assert sha(ROOT/'data/schedules.json')==frozen['schedule_sha256']
    command=json.loads((JOB/'expanded-v1/latest-full-launch.json').read_text())['command'];prefix=command[:command.index('/job/expanded-v1/recipe/train_latest.py')];i=prefix.index('--entrypoint');prefix[i:i]=['-v',str(ROOT/'data')+':/job/balanced-v1/data:ro']
    command=prefix+['/job/balanced-v1/recipe/train_balanced.py','--arm','panoramax','--definition-sha256',sha(definition),'--publication-revision',receipt['revision']]
    with (ROOT/'panoramax-launch.json').open('x') as stream:json.dump({'command':command,'definition_revision':receipt['revision'],'definition_sha256':sha(definition),'d9_results_revision':receipts['d9-balanced-results-model.json']['revision'],'d9_visual_report_revision':receipts['d9-balanced-results-dataset.json']['revision'],'mapillary_benchmark_completed':True,'gpu':0},stream,indent=2)
    with (ROOT/'panoramax.log').open('xb') as log:p=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    (ROOT/'panoramax-process.json').write_text(json.dumps({'pid':p.pid}));print(json.dumps({'started':True,'pid':p.pid,'epochs':20,'gpu':0}))
if __name__=='__main__':main()
