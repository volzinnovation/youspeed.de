#!/usr/bin/env python3
"""Launch one frozen d7 run only after both private HF publications verify."""
import hashlib
import json
from pathlib import Path
import subprocess

JOB=Path('/home/raphael/streetshots-d5-20261114')
ROOT=JOB/'expanded-v1'


def sha(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    receipt=json.loads((JOB/'publication-receipts/d7-definition-v1.json').read_text())
    assert receipt['private'] and receipt['postverification'] and receipt['prefix']=='detector/d7/'
    definition=ROOT/'definition-publication/detector/d7/definition.json'
    assert receipt['manifest']['sha256']==sha(definition)
    frozen=json.loads(definition.read_text())
    data_receipt=json.loads((JOB/'publication-receipts/expanded-dataset-v1.json').read_text())
    assert data_receipt['revision']==frozen['dataset_revision'] and data_receipt['postverification']
    manifest=ROOT/'dataset'/frozen['manifest_path']
    assert sha(manifest)==frozen['manifest_sha256']
    assert sha(ROOT/'recipe/train_mixed.py')==frozen['script_sha256']
    assert sha(ROOT/'recipe/pseudo_admission.py')==frozen['admission_recipe_sha256']
    assert not (ROOT/'training-launch.json').exists() and not (ROOT/'full-150').exists()
    command=['docker','run','--rm','--name','streetshots-d7-full-150','--network','none','--gpus','device=0',
             '--shm-size','4g','--workdir','/job/weights','-v',str(JOB)+':/job',
             '-v','/home/raphael/youspeed-training-20261020/tsr/vendor/ultralytics-8.4.56:/ultralytics:ro',
             '-e','PYTHONPATH=/ultralytics','-e','PYTHONDONTWRITEBYTECODE=1',
             '-e','YOLO_CONFIG_DIR=/job/ultralytics-config','-e','OMP_NUM_THREADS=4','-e','MKL_NUM_THREADS=4',
             '--entrypoint','python3',frozen['runtime']['image'],'-B','/job/expanded-v1/recipe/train_mixed.py','train',
             '--manifest','/job/expanded-v1/dataset/'+frozen['manifest_path'],
             '--manifest-sha256',frozen['manifest_sha256'],'--dataset-root','/job/expanded-v1/dataset',
             '--dataset-revision',frozen['dataset_revision'],
             '--output','/job/expanded-v1/full-150','--initialization','d4',
             '--epochs',str(frozen['epochs']),'--batch',str(frozen['batch']),'--imgsz',str(frozen['image_size']),
             '--seed',str(frozen['seed']),'--lr',str(frozen['lr0']),'--amp',
             '--coco','/job/weights/yolo26n.pt','--d4','/job/weights/d4.pt','--device','0']
    launch={'definition_revision':receipt['revision'],'definition_sha256':sha(definition),
            'dataset_revision':frozen['dataset_revision'],'manifest_sha256':frozen['manifest_sha256'],
            'command':command,'training_images':frozen['training_images'],'planned_epochs':frozen['epochs']}
    with (ROOT/'training-launch.json').open('x') as handle:handle.write(json.dumps(launch,indent=2)+'\n')
    with (ROOT/'full-150.log').open('xb') as log:
        process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    (ROOT/'training-process.json').write_text(json.dumps({'pid':process.pid})+'\n')
    print(json.dumps({'launched':True,'pid':process.pid,**launch}))


if __name__=='__main__':main()
