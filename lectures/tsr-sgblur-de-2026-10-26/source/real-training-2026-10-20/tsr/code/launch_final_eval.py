#!/usr/bin/env python3
"""Launch exactly one final evaluation sequence after successful 20-epoch training."""
import argparse
import csv
import datetime
import hashlib
import json
from pathlib import Path
import subprocess

ROOT=Path('/home/raphael/youspeed-training-20261020/tsr')
SOURCE=Path('/home/raphael/youspeed-lecture-download-test-20261020-f1a2266d/run-fixed')
TRAINING='youspeed-course-tsr-20261020-v1'
EVALUATION='youspeed-course-tsr-eval-20261020-v1'
IMAGE='sha256:886be2a4e18d52e587acf3ebfeaa7cbf2da92c1c26d2355e83b94217c474faca'
PINS={'reviewed-test.json':'01f6701be9fcc86f089709a24901a91285386467413224a290c8f97e245fcddc',
      'tsr-label-exclusions-v3.json':'b719af8f1a29b378ddd946cdc0d340405157e0fce206f038438760b94e94a17c',
      'final-label-qa.json':'58430cb5760fee0fb1dd6e47a1ad2edab61e426152eaf127cbe3a5a27310981e',
      'data/dataset-v1/manifest.json':'e67c8699a705371b79d68ea534371e2ae0c5e74ce83be7fd62fce671a1cac9eb'}


def check(value,reason):
    if not value: raise ValueError(reason)


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--execute',action='store_true');a=p.parse_args()
    if not a.execute:
        print(json.dumps({'status':'PLAN','training':TRAINING,'evaluation':EVALUATION,
                          'old_test_crops':3029,'prospective_primary':42,'city':15,'joint_crops':3071,
                          'retrospective_exit3_is_quality_failure_not_execution_failure':True}));return
    state=json.loads(subprocess.run(['docker','inspect',TRAINING],check=True,capture_output=True,text=True).stdout)[0]
    check(state['State']['Status']=='exited' and state['State']['ExitCode']==0,'Training not successfully completed')
    check(state['Config']['Image']==IMAGE,'Training image changed')
    check(subprocess.run(['docker','inspect',EVALUATION],capture_output=True).returncode!=0,'Evaluation already exists; no repeat')
    with (ROOT/'runs/versuch-01/progress.csv').open() as stream:progress=list(csv.DictReader(stream))
    check(len(progress)==20 and int(progress[-1]['epoch'])==20,'Training has not completed20 epochs')
    for name,expected in PINS.items():check(sha(ROOT/name)==expected,'Pinned input changed: '+name)
    metadata=json.loads((ROOT/'runs/versuch-01/checkpoint-hashes.json').read_text())
    check(sha(ROOT/'runs/versuch-01/weights/best.pt')==metadata['best.pt'],'Best checkpoint changed')
    review=json.loads((ROOT/'reviewed-test.json').read_text());overlay=json.loads((ROOT/'tsr-label-exclusions-v3.json').read_text())
    peer=json.loads((ROOT/'final-label-qa.json').read_text())
    check(peer['predictions_viewed'] is False,'Peer review was not blind')
    excluded={r['sample_id'] for r in overlay['exclusions']}
    primary={r['sample_id']:r['label'] for r in review['rows'] if r['sample_id'] not in excluded and r.get('include_primary',True)}
    check(primary==peer['primary_label_by_id'] and len(primary)==42,'Final peer labels/IDs differ')
    for name in ['retrospective-old','prospective-final','joint-final']:
        check(not (ROOT/'reports'/name).exists(),'Report already exists; no repeat')
    script='''set -uo pipefail
python evaluate_retrospective.py --data /experiment/tsr/data/dataset-v1 --baseline /experiment/tsr/models/baseline.pt --candidate /experiment/tsr/runs/versuch-01/weights/best.pt --split test --batch-size 64 --device cuda:0 --output /experiment/tsr/reports/retrospective-old
old_code=$?
if [ "$old_code" -ne 0 ] && [ "$old_code" -ne 3 ]; then exit "$old_code"; fi
python evaluate_reserved.py --data /experiment/tsr/data/dataset-v1 --baseline /experiment/tsr/models/baseline.pt --candidate /experiment/tsr/runs/versuch-01/weights/best.pt --test-manifest /experiment/tsr/reviewed-test.json --exclusion-overlay /experiment/tsr/tsr-label-exclusions-v3.json --batch-size 64 --device cuda:0 --output /experiment/tsr/reports/prospective-final || exit $?
python combine_predictions.py --old-report /experiment/tsr/reports/retrospective-old --prospective-report /experiment/tsr/reports/prospective-final --output /experiment/tsr/reports/joint-final || exit $?
'''
    cmd=['docker','run','--detach','--name',EVALUATION,'--network','none','--read-only','--cpus','8','--memory','16g','--shm-size','1g',
         '--tmpfs','/tmp:rw,size=512m','--gpus','device=GPU-58a2466e-517c-8d67-8aba-02f8a22b96b0',
         '--mount',f'type=bind,src={ROOT},dst=/experiment/tsr',
         '--mount',f'type=bind,src={SOURCE},dst={SOURCE},readonly',
         '--workdir','/experiment/tsr/code','--env','YOLO_CONFIG_DIR=/experiment/tsr/cache/ultralytics',
         '--env','MPLCONFIGDIR=/experiment/tsr/cache/matplotlib','--env','CUDA_CACHE_PATH=/experiment/tsr/cache/cuda',
         '--env','TORCH_HOME=/experiment/tsr/cache/torch','--env','PYTHONDONTWRITEBYTECODE=1',
         '--env','CUDA_VISIBLE_DEVICES=0','--entrypoint','bash',IMAGE,'-c',script]
    result=subprocess.run(cmd,check=True,capture_output=True,text=True)
    record={'started_at':datetime.datetime.now(datetime.timezone.utc).isoformat(),'container_id':result.stdout.strip(),
            'container_name':EVALUATION,'command':cmd,'pins':PINS,'candidate_sha256':metadata['best.pt'],
            'selected_epoch_by_validation':max(progress,key=lambda r:float(r['val_macro_f1']))['epoch'],
            'expected_primary_rows':42,'expected_joint_rows':3071,
            'human_reviewed':False,'ground_truth_source':'assistant blind visual peer review'}
    (ROOT/'evaluation-launch.json').write_text(json.dumps(record,indent=2)+'\n')
    print(json.dumps(record),flush=True)


if __name__=='__main__':main()
