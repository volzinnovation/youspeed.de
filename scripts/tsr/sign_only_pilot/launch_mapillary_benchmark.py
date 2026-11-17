#!/usr/bin/env python3
import hashlib,json,subprocess,time,os
from pathlib import Path
JOB=Path('/home/raphael/streetshots-d5-20261114');ROOT=JOB/'balanced-v1';SAMPLE=JOB/'mapillary-auto-v2'
def main():
    while not (ROOT/'comparison-complete.json').exists():
        pid=json.loads((ROOT/'process.json').read_text())['pid'];os.kill(pid,0);time.sleep(5)
    manifest=SAMPLE/'manifest.json';digest=hashlib.sha256(manifest.read_bytes()).hexdigest();assert digest=='022f5420b45e2a83178deac332fa6a5cff687398913a30cf689f8a8a9824c172'
    source=json.loads((JOB/'expanded-v1/latest-full-launch.json').read_text())['command'];prefix=source[:source.index('/job/expanded-v1/recipe/train_latest.py')];i=prefix.index('--entrypoint');prefix[i:i]=['-v',str(SAMPLE)+':/job/mapillary-auto-v2:ro']
    command=prefix+['/job/balanced-v1/recipe/benchmark_mapillary_auto.py','--sample-sha256',digest]
    with (ROOT/'mapillary-benchmark-launch.json').open('x') as stream:json.dump({'command':command,'sample_manifest_sha256':digest,'script_sha256':hashlib.sha256((ROOT/'recipe/benchmark_mapillary_auto.py').read_bytes()).hexdigest(),'frozen_before_sample_inference':True},stream,indent=2)
    with (ROOT/'mapillary-benchmark.log').open('xb') as log:subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,check=True)
if __name__=='__main__':main()
