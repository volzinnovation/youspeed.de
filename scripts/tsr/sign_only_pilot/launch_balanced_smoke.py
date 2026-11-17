#!/usr/bin/env python3
import json,subprocess,time
from pathlib import Path
JOB=Path('/home/raphael/streetshots-d5-20261114');ROOT=JOB/'balanced-v1'
while not (ROOT/'data/summary.json').exists():
    time.sleep(5)
command=json.loads((JOB/'expanded-v1/latest-full-launch.json').read_text())['command'];prefix=command[:command.index('/job/expanded-v1/recipe/train_latest.py')]
for arm in ['phone','mixed']:
    with (ROOT/f'smoke-{arm}.log').open('xb') as stream:
        subprocess.run(prefix+['/job/balanced-v1/recipe/train_balanced.py','--arm',arm,'--smoke'],stdout=stream,stderr=subprocess.STDOUT,check=True)
(ROOT/'smoke-complete.json').write_text(json.dumps({'complete':True,'arms':['phone','mixed']}))
