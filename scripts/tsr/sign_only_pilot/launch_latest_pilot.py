#!/usr/bin/env python3
"""Run the two frozen d7 arms sequentially on KI GPU0."""
import json
from pathlib import Path
import subprocess
from prepare_expanded_publication import sha

JOB=Path('/home/raphael/streetshots-d5-20261114')
ROOT=JOB/'latest-ultralytics-v1'


def main():
    receipt=json.loads((JOB/'publication-receipts/d7-definition-v1.json').read_text())
    definition=ROOT/'pilot-definition-publication/detector/d7/definition.json'
    assert receipt['private'] and receipt['postverification'] and receipt['manifest']['sha256']==sha(definition)
    frozen=json.loads(definition.read_text())
    assert sha(JOB/'expanded-v1/recipe/train_latest.py')==frozen['script_sha256']
    assert sha(JOB/'dataset-reviewed-v1/manifest.json')==frozen['manifest_sha256']
    assert sha(ROOT/'ultralytics-8.4.213-py3-none-any.whl')==frozen['runtime']['ultralytics_wheel_sha256']
    commands=[]
    for arm in frozen['arms']:
        name='pilot-'+arm['name']
        assert not (ROOT/name).exists()
        command=['docker','run','--rm','--name','streetshots-d7-'+arm['name'],'--network','none','--gpus','device=0',
             '--shm-size','4g','--workdir','/job/weights','-v',str(JOB)+':/job',
             '-e','PYTHONPATH=/job/latest-ultralytics-v1/vendor','-e','PYTHONDONTWRITEBYTECODE=1',
             '-e','YOLO_CONFIG_DIR=/job/latest-ultralytics-v1/config','-e','OMP_NUM_THREADS=4','-e','MKL_NUM_THREADS=4',
             '--entrypoint','python3',frozen['runtime']['image'],'-B','/job/expanded-v1/recipe/train_latest.py','train',
             '--manifest','/job/dataset-reviewed-v1/manifest.json','--manifest-sha256',frozen['manifest_sha256'],
             '--dataset-root','/job/dataset-reviewed-v1','--dataset-revision',frozen['dataset_revision'],
             '--output','/job/latest-ultralytics-v1/'+name,'--initialization','d4',
             '--epochs',str(frozen['epochs']),'--batch',str(frozen['batch']),'--imgsz',str(frozen['image_size']),
             '--seed',str(frozen['seed']),'--lr',str(frozen['lr0']),'--amp','--cache',frozen['cache'],
             '--tile' if arm['tile'] else '--no-tile','--no-channels-last',
             '--coco','/job/weights/yolo26n.pt','--d4','/job/weights/d4.pt','--device','0']
        commands.append({'name':name,'command':command})
    runner=ROOT/'run-pilot-arms.py'
    runner.write_text('import subprocess,json\nfrom pathlib import Path\nr=Path('+repr(str(ROOT))+')\ncommands='+repr(commands)+'\nfor item in commands:\n with (r/(item["name"]+".log")).open("xb") as log:\n  subprocess.run(item["command"],stdout=log,stderr=subprocess.STDOUT,check=True)\n (r/(item["name"]+"-complete.json")).write_text(json.dumps(item))\n')
    with (ROOT/'pilot-runner.log').open('xb') as log:
        process=subprocess.Popen(['python3','-B',str(runner)],stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    launch={'pid':process.pid,'definition_revision':receipt['revision'],'definition_sha256':sha(definition),'commands':commands}
    with (ROOT/'pilot-launch.json').open('x') as handle:handle.write(json.dumps(launch,indent=2)+'\n')
    print(json.dumps(launch))

if __name__=='__main__':main()
