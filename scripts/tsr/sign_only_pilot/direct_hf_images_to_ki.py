#!/usr/bin/env python3
"""File-scoped, temporary download URLs; no HF account credential leaves Mac.

URLs exist only in process memory/stdin and are never logged or saved. KI verifies
each source's pinned SHA256 and size before atomically publishing its image file.
"""
import concurrent.futures
import json
import shlex
import subprocess
import threading
import time
from urllib.parse import urlparse
import requests
from huggingface_hub import hf_hub_url
from huggingface_hub.utils import build_hf_headers

ROOT='/home/raphael/streetshots-d5-20261114/expanded-v1'
RECEIVER=r'''
import concurrent.futures,sys,json,pathlib,hashlib,re,urllib.request,time,os
p=pathlib.Path('/home/raphael/streetshots-d5-20261114/expanded-v1');(p/'source-images').mkdir(exist_ok=True)
def receive(row):
 sha=row['image_sha256'];size=row['bytes'];assert re.fullmatch('[0-9a-f]{64}',sha)
 f=p/'source-images'/(sha+'.jpg')
 if f.exists() and f.stat().st_size==size and hashlib.sha256(f.read_bytes()).hexdigest()==sha:
  return {k:v for k,v in row.items() if k!='temporary_url'}
 for attempt in range(5):
  try:
   with urllib.request.urlopen(row['temporary_url'],timeout=120) as response:b=response.read()
   assert len(b)==size and hashlib.sha256(b).hexdigest()==sha
   temp=f.with_suffix('.'+str(os.getpid())+'.part');temp.write_bytes(b);temp.replace(f)
   return {k:v for k,v in row.items() if k!='temporary_url'}
  except Exception:
   if attempt==4:raise RuntimeError('Direct download failed for '+row['picture_id']) from None
   time.sleep(min(15,2**attempt))
count=0
with concurrent.futures.ThreadPoolExecutor(max_workers=12) as pool,(p/'direct-transfer-receipts.jsonl').open('a') as log:
 active=set()
 def finish(done):
  global count
  for future in done:
   r=future.result();log.write(json.dumps({**r,'verified':True})+chr(10));log.flush();count+=1
   if count%100==0:print(json.dumps({'direct_received':count}),flush=True)
 for line in sys.stdin:
  active.add(pool.submit(receive,json.loads(line)))
  if len(active)>=48:
   done,active=concurrent.futures.wait(active,return_when=concurrent.futures.FIRST_COMPLETED);finish(done)
 finish(active)
print(json.dumps({'direct_stream_complete':True,'received':count}),flush=True)
'''


def main():
    rows=json.loads(subprocess.check_output(['ssh','wingki01','cat '+ROOT+'/download-inventory.json']))
    existing=json.loads(subprocess.check_output(['ssh','wingki01','python3 -c '+shlex.quote("import pathlib,json; p=pathlib.Path('"+ROOT+"/source-images');print(json.dumps({f.stem:f.stat().st_size for f in p.glob('*.jpg')}))")]))
    rows=[r for r in rows if r['expanded_role']=='weak_training' and existing.get(r['image_sha256'])!=r['bytes']]
    print(json.dumps({'pending_direct':len(rows)}),flush=True)
    headers=build_hf_headers(token=True);local=threading.local()
    def resolve(row):
        if not hasattr(local,'session'):
            local.session=requests.Session();local.session.headers.update(headers)
        url=hf_hub_url('loffenauer/streetshots',row['image_path'],repo_type='dataset',revision='d2c5cc44716166e2604655d7fd8cad93a8dd9468')
        for attempt in range(6):
            try:
                r=local.session.get(url,allow_redirects=False,stream=True,timeout=(15,45))
                if r.status_code in (429,500,502,503,504):
                    delay=min(60,float(r.headers.get('Retry-After',2**attempt)));r.close();time.sleep(delay);continue
                r.raise_for_status();signed=r.headers.get('Location');r.close()
                if not signed:raise ValueError('No scoped redirect')
                parsed=urlparse(signed);host=parsed.hostname or ''
                assert parsed.scheme=='https' and (host.endswith('.hf.co') or host.endswith('.huggingface.co') or host.endswith('.amazonaws.com'))
                return {**row,'temporary_url':signed}
            except (requests.Timeout,requests.ConnectionError):
                if attempt==5:raise RuntimeError('Resolve failed for '+row['picture_id']) from None
                time.sleep(min(30,2**attempt))
        raise RuntimeError('Resolve retries exhausted for '+row['picture_id'])
    process=subprocess.Popen(['ssh','-T','wingki01','python3 -u -c '+shlex.quote(RECEIVER)],stdin=subprocess.PIPE)
    iterator=iter(rows)
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
            active={pool.submit(resolve,r) for r in [next(iterator,None) for _ in range(8)] if r}
            while active:
                done,active=concurrent.futures.wait(active,return_when=concurrent.futures.FIRST_COMPLETED)
                for future in done:
                    process.stdin.write((json.dumps(future.result())+'\n').encode());process.stdin.flush()
                    following=next(iterator,None)
                    if following:active.add(pool.submit(resolve,following))
        process.stdin.close()
        if process.wait()!=0:raise RuntimeError('KI receiver failed')
    except BaseException:
        process.stdin.close();process.wait();raise


if __name__=='__main__':main()
