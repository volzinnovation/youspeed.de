#!/usr/bin/env python3
"""Wait for this frozen experiment, then replay only its development split."""
import json
import os
from pathlib import Path
import subprocess
import time
from prepare_expanded_publication import sha, write

JOB=Path('/home/raphael/streetshots-d5-20261114');ROOT=JOB/'latest-ultralytics-v1'


def main():
    launch=json.loads((ROOT/'pilot-launch.json').read_text())
    while not all((ROOT/('pilot-'+arm)/'seal.json').exists() for arm in ('whole','tile')):
        os.kill(launch['pid'],0)
        time.sleep(15)
    command=launch['commands'][0]['command']
    prefix=command[:command.index('/job/expanded-v1/recipe/train_latest.py')]
    prefix.remove('--name');prefix.remove('streetshots-d7-whole')
    for arm in ('whole','tile'):
        run=ROOT/('pilot-'+arm);seal=json.loads((run/'seal.json').read_text())
        assert seal['checkpoint_sha256']==sha(run/'selected.pt')
        spec=[{'name':'d7','path':'/job/latest-ultralytics-v1/pilot-'+arm+'/selected.pt','sha256':seal['checkpoint_sha256']}]
        write(ROOT/('replay-'+arm+'-models.json'),spec)
        args=['/job/expanded-v1/recipe/replay_latest.py','--manifest','/job/dataset-reviewed-v1/manifest.json',
              '--manifest-sha256','8d4f939e502b97b98750136d96fa9cc2f89017b236b69f1f57be2b55b9d73e1a',
              '--dataset-root','/job/dataset-reviewed-v1','--models','/job/latest-ultralytics-v1/replay-'+arm+'-models.json',
              '--coco','/job/weights/yolo26n.pt','--output','/job/latest-ultralytics-v1/replay-'+arm,
              '--native-inputs','/job/expanded-v1/native-inputs']
        with (ROOT/('replay-'+arm+'.log')).open('xb') as log:subprocess.run(prefix+args,stdout=log,stderr=subprocess.STDOUT,check=True)
    models=[]
    for name,path in [('d4',ROOT/'probe/d4-runtime.pt'),('d5',JOB/'runs/d4/selected.pt'),('d7-whole',ROOT/'pilot-whole/selected.pt'),('d7-tile',ROOT/'pilot-tile/selected.pt')]:
        models.append({'name':name,'path':'/job/'+path.relative_to(JOB).as_posix(),'sha256':sha(path)})
    write(ROOT/'builtin-models.json',models)
    args=['/job/expanded-v1/recipe/replay_builtin_tiles.py','--manifest','/job/dataset-reviewed-v1/manifest.json',
          '--manifest-sha256','8d4f939e502b97b98750136d96fa9cc2f89017b236b69f1f57be2b55b9d73e1a',
          '--dataset-root','/job/dataset-reviewed-v1','--models','/job/latest-ultralytics-v1/builtin-models.json',
          '--output','/job/latest-ultralytics-v1/builtin-inference']
    with (ROOT/'builtin-inference.log').open('xb') as log:subprocess.run(prefix+args,stdout=log,stderr=subprocess.STDOUT,check=True)
    write(ROOT/'pilot-replays-complete.json',{'complete':True,'native_split':'validation','images':17,'test_inference':False})

if __name__=='__main__':main()
