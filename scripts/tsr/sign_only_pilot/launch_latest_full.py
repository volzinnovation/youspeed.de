#!/usr/bin/env python3
"""Launch one frozen d8 job after private HF data and definition verification."""
import json
from pathlib import Path
import subprocess
from prepare_expanded_publication import sha

JOB=Path('/home/raphael/streetshots-d5-20261114');ROOT=JOB/'expanded-v1';LATEST=JOB/'latest-ultralytics-v1'


def main():
    receipt=json.loads((JOB/'publication-receipts/d8-definition-v1.json').read_text())
    definition=LATEST/'full-definition-publication/detector/d8/definition.json'
    assert receipt['private'] and receipt['postverification'] and receipt['prefix']=='detector/d8/'
    assert receipt['manifest']['sha256']==sha(definition)
    frozen=json.loads(definition.read_text())
    data_receipt=json.loads((JOB/'publication-receipts/expanded-dataset-v1.json').read_text())
    assert data_receipt['revision']==frozen['dataset_revision'] and data_receipt['postverification']
    manifest=ROOT/'dataset'/frozen['manifest_path']
    assert sha(manifest)==frozen['manifest_sha256']
    assert sha(ROOT/'recipe/train_latest.py')==frozen['script_sha256']
    assert sha(Path(__file__))==frozen['launcher_sha256']
    assert sha(ROOT/'recipe/pseudo_admission.py')==frozen['admission_recipe_sha256']
    assert json.loads((ROOT/'mining-status.json').read_text())['complete']
    assert not (ROOT/'latest-full-launch.json').exists() and not (ROOT/'latest-full').exists()
    prefix=['docker','run','--rm','--network','none','--gpus','device=0','--shm-size','4g','--workdir','/job/weights',
         '-v',str(JOB)+':/job','-v',str(ROOT/'dataset')+':/job/expanded-v1/dataset:ro','-e','PYTHONPATH=/job/latest-ultralytics-v1/vendor','-e','PYTHONDONTWRITEBYTECODE=1',
         '-e','YOLO_CONFIG_DIR=/job/latest-ultralytics-v1/config','-e','OMP_NUM_THREADS=4','-e','MKL_NUM_THREADS=4',
         '--entrypoint','python3',frozen['runtime']['image'],'-B']
    # Independently verify the training-budget window count in the exact wheel.
    source="import json;from ultralytics.data.utils import tile_windows;from pathlib import Path;m=json.loads(Path("+repr('/job/expanded-v1/dataset/'+frozen['manifest_path'])+").read_text());print(sum(len(tile_windows((r['height'],r['width']),1024)) for r in m['frames'] if r['split']=='train'))"
    output=subprocess.check_output(prefix+['-c',source],text=True)
    assert int(output.strip().splitlines()[-1])==frozen['training_budget']['native_tiles_per_epoch']
    command=prefix+['/job/expanded-v1/recipe/train_latest.py','train',
         '--manifest','/job/expanded-v1/dataset/'+frozen['manifest_path'],
         '--manifest-sha256',frozen['manifest_sha256'],'--dataset-root','/job/expanded-v1/dataset',
         '--dataset-revision',frozen['dataset_revision'],'--output','/job/expanded-v1/latest-full','--initialization','d4',
         '--epochs',str(frozen['epochs']),'--batch',str(frozen['batch']),'--imgsz',str(frozen['image_size']),
         '--seed',str(frozen['seed']),'--lr',str(frozen['lr0']),'--amp','--cache',frozen['cache'],
         '--tile' if frozen['tile'] else '--no-tile','--no-channels-last',
         '--coco','/job/weights/yolo26n.pt','--d4','/job/weights/d4.pt','--device','0']
    launch={'definition_revision':receipt['revision'],'definition_sha256':sha(definition),
            'dataset_revision':frozen['dataset_revision'],'manifest_sha256':frozen['manifest_sha256'],
            'command':command,'training_images':frozen['training_images'],'planned_epochs':frozen['epochs'],
            'expected_training_samples_per_epoch':frozen['expected_training_samples_per_epoch'],'tile':frozen['tile']}
    with (ROOT/'latest-full-launch.json').open('x') as handle:handle.write(json.dumps(launch,indent=2)+'\n')
    with (ROOT/'latest-full.log').open('xb') as log:process=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
    (ROOT/'latest-full-process.json').write_text(json.dumps({'pid':process.pid})+'\n')
    print(json.dumps({'launched':True,'pid':process.pid,**launch}))

if __name__=='__main__':main()
