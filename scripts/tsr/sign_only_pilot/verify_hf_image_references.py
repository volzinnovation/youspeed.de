#!/usr/bin/env python3
"""Verify inherited HF image bytes at the new overlay's immutable revision.

Runs on the authenticated Mac; only a non-secret verification receipt goes to KI.
"""
import hashlib
import json
import shlex
import subprocess
import sys
from publish_expanded import call_hub, remote_matches

JOB='/home/raphael/streetshots-d5-20261114'
ROOT=JOB+'/expanded-v1'
PREFIX='reviews/detector-expanded-2026-11-15'


def read(path):
    return subprocess.check_output(['ssh','wingki01','cat '+shlex.quote(path)])


def main():
    if sys.platform!='darwin':raise RuntimeError('HF credentials must remain on the Mac')
    receipt=json.loads(read(JOB+'/publication-receipts/expanded-dataset-v1.json'))
    assert receipt['private'] and receipt['postverification'] and receipt['repo_type']=='dataset'
    raw=read(ROOT+'/dataset/'+PREFIX+'/image-reference-inventory.json')
    inventory_sha=hashlib.sha256(raw).hexdigest()
    assert receipt['paths'][PREFIX+'/image-reference-inventory.json']['sha256']==inventory_sha
    rows=json.loads(raw)['files'];revision=receipt['revision']
    from huggingface_hub import HfApi
    api=HfApi();info=call_hub(api.repo_info,'loffenauer/streetshots',repo_type='dataset',revision=revision)
    assert info.private and info.sha==revision
    for start in range(0,len(rows),200):
        batch=rows[start:start+200]
        found={r.path:r for r in call_hub(api.get_paths_info,'loffenauer/streetshots',
            [r['path_in_repo'] for r in batch],repo_type='dataset',revision=revision)}
        assert set(found)=={r['path_in_repo'] for r in batch}
        assert all(remote_matches(found[r['path_in_repo']],r) for r in batch)
    out={'schema':'streetshots-inherited-image-closure-v1','repository':'loffenauer/streetshots',
         'repo_type':'dataset','revision':revision,'private':True,'postverification':True,
         'inventory_sha256':inventory_sha,'verified_images':len(rows),
         'method':'All inherited image sizes and LFS SHA-256 or Git blob hashes checked at the newly published immutable dataset revision.'}
    target=ROOT+'/image-reference-verification.json'
    code='import pathlib,sys; p=pathlib.Path('+repr(target)+'); p.open("xb").write(sys.stdin.buffer.read())'
    subprocess.run(['ssh','wingki01','python3 -B -c '+shlex.quote(code)],input=(json.dumps(out,indent=2)+'\n').encode(),check=True)
    print(json.dumps(out))


if __name__=='__main__':main()
