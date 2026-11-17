#!/usr/bin/env python3
"""Run both frozen d9 arms on GPU0 and produce the comparison; no Hub credentials."""
import json,subprocess,hashlib,time
from pathlib import Path
JOB=Path('/home/raphael/streetshots-d5-20261114');ROOT=JOB/'balanced-v1'
def sha(p):
    h=hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
    return h.hexdigest()
def main():
    receipt=json.loads((JOB/'publication-receipts/d9-balanced-definition.json').read_text());data_receipt=json.loads((JOB/'publication-receipts/d9-balanced-dataset.json').read_text())
    assert all(r['private'] and r['postverification'] and r['stage']=='complete' for r in [receipt,data_receipt])
    definition=ROOT/'definition.json';frozen=json.loads(definition.read_text());assert sha(definition)==receipt['manifest']['sha256']
    for name,digest in frozen['scripts'].items():assert sha(ROOT/'recipe'/name)==digest
    for name,digest in frozen['dataset_artifacts'].items():assert sha(ROOT/'data'/name)==digest
    views=json.loads((ROOT/'data/views.json').read_text())
    for v in views:
        p=JOB/Path(v['image_path']).relative_to('/job');assert sha(p)==v['image_sha256'];assert sha(p.parent.parent.parent/'labels/train'/(p.stem+'.txt'))==v['label_sha256']
    command=json.loads((JOB/'expanded-v1/latest-full-launch.json').read_text())['command'];prefix=command[:command.index('/job/expanded-v1/recipe/train_latest.py')];index=prefix.index('--entrypoint');prefix[index:index]=['-v',str(ROOT/'data')+':/job/balanced-v1/data:ro']
    commands={arm:prefix+['/job/balanced-v1/recipe/train_balanced.py','--arm',arm,'--definition-sha256',sha(definition),'--publication-revision',receipt['revision']] for arm in ['phone','mixed']}
    with (ROOT/'launch.json').open('x') as f:json.dump({'definition_sha256':sha(definition),'definition_revision':receipt['revision'],'dataset_revision':data_receipt['revision'],'commands':commands,'gpu':0,'started_at':time.time()},f,indent=2)
    for arm,cmd in commands.items():
        with (ROOT/(arm+'.log')).open('xb') as log:subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT,check=True)
    with (ROOT/'comparison.log').open('xb') as log:subprocess.run(prefix+['/job/balanced-v1/recipe/finish_balanced.py'],stdout=log,stderr=subprocess.STDOUT,check=True)
if __name__=='__main__':main()
