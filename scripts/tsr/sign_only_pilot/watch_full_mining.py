#!/usr/bin/env python3
"""Current-job supervisor: verify complete mining and assemble, then exit.

No scheduling, publication, credentials or training are involved.
"""
import json
import os
from pathlib import Path
import subprocess
import time

JOB=Path('/home/raphael/streetshots-d5-20261114')
ROOT=JOB/'expanded-v1'


def status(phase, **fields):
    path=ROOT/'assembly-supervisor-status.json'
    temp=path.with_suffix('.tmp');temp.write_text(json.dumps({'phase':phase,**fields})+'\n');temp.replace(path)


def main():
    workers=json.loads((ROOT/'mining-launch.json').read_text())['workers']
    while True:
        try:states=[json.loads((ROOT/f'mining-status-shard{i}.json').read_text()) for i in range(2)]
        except json.JSONDecodeError:
            time.sleep(1);continue
        if all(r['complete'] for r in states):break
        for worker,state in zip(workers,states):
            if not state['complete']:os.kill(worker['pid'],0)
        status('mining',processed=sum(r['processed'] for r in states),total=sum(r['total'] for r in states))
        time.sleep(15)
    status('verifying_mining')
    subprocess.run(['python3','-B',str(ROOT/'recipe/verify_full_mining.py')],check=True)
    status('assembling_dataset')
    cmd=['docker','run','--rm','--network','none','-v',str(JOB)+':/job',
         '-e','PYTHONDONTWRITEBYTECODE=1','--entrypoint','python3',
         'sha256:886be2a4e18d52e587acf3ebfeaa7cbf2da92c1c26d2355e83b94217c474faca',
         '-B','/job/expanded-v1/recipe/assemble_full_pseudo.py']
    subprocess.run(cmd,check=True)
    status('assembled_awaiting_final_spotcheck_and_publication',complete=True)


if __name__=='__main__':
    try:main()
    except BaseException as error:
        status('failed',error=repr(error));raise
