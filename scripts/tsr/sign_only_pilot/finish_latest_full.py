#!/usr/bin/env python3
"""After the current d8 job finishes, replay development and package results."""
import json
import os
from pathlib import Path
import subprocess
import time
from prepare_expanded_publication import sha,write

JOB=Path('/home/raphael/streetshots-d5-20261114');ROOT=JOB/'expanded-v1'


def main():
    launch=json.loads((ROOT/'latest-full-launch.json').read_text())
    pid=json.loads((ROOT/'latest-full-process.json').read_text())['pid']
    while not (ROOT/'latest-full/seal.json').exists():
        os.kill(pid,0);time.sleep(15)
    seal=json.loads((ROOT/'latest-full/seal.json').read_text())
    assert sha(ROOT/'latest-full/selected.pt')==seal['checkpoint_sha256']
    models=json.loads((ROOT/'baseline-native-models.json').read_text())
    models.append({'name':'d8','path':'/job/expanded-v1/latest-full/selected.pt','sha256':seal['checkpoint_sha256']})
    write(ROOT/'latest-full-models.json',models)
    command=launch['command'];prefix=command[:command.index('/job/expanded-v1/recipe/train_latest.py')]
    args=['/job/expanded-v1/recipe/replay_latest.py','--manifest','/job/dataset-reviewed-v1/manifest.json',
          '--manifest-sha256','8d4f939e502b97b98750136d96fa9cc2f89017b236b69f1f57be2b55b9d73e1a',
          '--dataset-root','/job/dataset-reviewed-v1','--models','/job/expanded-v1/latest-full-models.json',
          '--coco','/job/weights/yolo26n.pt','--output','/job/expanded-v1/latest-full-development',
          '--native-inputs','/job/expanded-v1/native-inputs']
    with (ROOT/'latest-full-development.log').open('xb') as log:subprocess.run(prefix+args,stdout=log,stderr=subprocess.STDOUT,check=True)
    subprocess.run(['python3','-B',str(ROOT/'recipe/package_latest_full.py')],check=True)
    write(ROOT/'latest-full-complete.json',{'complete':True,'packaged':True,'published':False,'new_holdout_evaluation':False})

if __name__=='__main__':main()
