#!/usr/bin/env python3
"""Stream verified HF image bytes to KI; credentials remain on this Mac.

No disk cache and no authentication data are sent to the server. Retry is safe:
the receiver validates existing immutable content-addressed files before skipping.
"""
import concurrent.futures
import hashlib
import json
import shlex
import subprocess
import threading
import time
from huggingface_hub import hf_hub_url
from huggingface_hub.utils import build_hf_headers
import requests

ROOT='/home/raphael/streetshots-d5-20261114/expanded-v1'
REVISION='d2c5cc44716166e2604655d7fd8cad93a8dd9468'
RECEIVER=r'''
import sys,json,pathlib,hashlib,re
p=pathlib.Path('/home/raphael/streetshots-d5-20261114/expanded-v1')
(p/'source-images').mkdir(exist_ok=True)
count=0;total=0
with (p/'transfer-receipts.jsonl').open('a') as log:
 while line:=sys.stdin.buffer.readline():
  row=json.loads(line);sha=row['image_sha256'];size=row['bytes']
  assert re.fullmatch('[0-9a-f]{64}',sha) and 0<size<100_000_000
  data=bytearray()
  while len(data)<size:
   part=sys.stdin.buffer.read(min(1024*1024,size-len(data)))
   if not part:raise RuntimeError('Interrupted image stream')
   data.extend(part)
  assert hashlib.sha256(data).hexdigest()==sha
  f=p/'source-images'/(sha+'.jpg')
  if f.exists():assert hashlib.sha256(f.read_bytes()).hexdigest()==sha
  else:
   temp=f.with_suffix('.part');temp.write_bytes(data);temp.replace(f)
  log.write(json.dumps({**row,'stored_path':str(f),'verified':True})+'\n');log.flush()
  count+=1;total+=size
  if count%100==0:print(json.dumps({'received':count,'bytes':total}),flush=True)
print(json.dumps({'transfer_stream_complete':True,'received':count,'bytes':total}),flush=True)
'''


def main():
    inventory=json.loads(subprocess.check_output(['ssh','wingki01','cat '+ROOT+'/download-inventory.json']))
    inventory=[r for r in inventory if r['expanded_role']=='weak_training']
    existing=json.loads(subprocess.check_output(['ssh','wingki01','python3 -c '+shlex.quote(
        "import pathlib,json; p=pathlib.Path('"+ROOT+"/source-images'); print(json.dumps({f.stem:f.stat().st_size for f in p.glob('*.jpg')}))")]))
    # Existing paths are content-addressed and created only after receiver hash checks.
    pending=[r for r in inventory if existing.get(r['image_sha256'])!=r['bytes']]
    print(json.dumps({'source_images':len(inventory),'already_received':len(inventory)-len(pending),'pending':len(pending)}),flush=True)
    headers=build_hf_headers(token=True);local=threading.local()
    def fetch(row):
        if not hasattr(local,'session'):
            local.session=requests.Session();local.session.headers.update(headers)
        url=hf_hub_url('loffenauer/streetshots',row['image_path'],repo_type='dataset',revision=REVISION)
        for attempt in range(6):
            try:
                response=local.session.get(url,timeout=(30,180))
                if response.status_code in (429,500,502,503,504):
                    delay=min(60,float(response.headers.get('Retry-After',2**attempt)))
                    time.sleep(delay);continue
                response.raise_for_status();data=response.content
                if len(data)!=row['bytes'] or hashlib.sha256(data).hexdigest()!=row['image_sha256']:
                    raise ValueError('Source hash/size mismatch: '+row['picture_id'])
                return row,data
            except (requests.Timeout,requests.ConnectionError):
                if attempt==5:raise
                time.sleep(min(30,2**attempt))
        raise RuntimeError('HTTP retries exhausted: '+row['picture_id'])
    process=subprocess.Popen(['ssh','-T','-o','BatchMode=yes','wingki01','python3 -u -c '+shlex.quote(RECEIVER)],stdin=subprocess.PIPE)
    iterator=iter(pending)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
            active={pool.submit(fetch,r) for r in [next(iterator,None) for _ in range(6)] if r}
            while active:
                done,active=concurrent.futures.wait(active,return_when=concurrent.futures.FIRST_COMPLETED)
                for future in done:
                    row,data=future.result()
                    process.stdin.write((json.dumps(row)+'\n').encode());process.stdin.write(data);process.stdin.flush()
                    following=next(iterator,None)
                    if following:active.add(pool.submit(fetch,following))
        process.stdin.close()
        if process.wait()!=0:raise RuntimeError('KI receiver failed')
    except BaseException:
        process.stdin.close();process.wait();raise


if __name__=='__main__':main()
