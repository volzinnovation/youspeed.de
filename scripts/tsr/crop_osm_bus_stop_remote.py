#!/usr/bin/env python3
"""Retrieve declared native-pixel crops from hash-pinned public originals on KI."""
import argparse
import base64
import json
from pathlib import Path
import subprocess
import collect_osm_bus_stop_crops as c

REMOTE=r'''
import base64,hashlib,io,json,pathlib
from PIL import Image,ImageOps
out=[]
for row in PLAN:
    raw=pathlib.Path(row['remote_path']).read_bytes();assert hashlib.sha256(raw).hexdigest()==row['source_sha256']
    im=ImageOps.exif_transpose(Image.open(io.BytesIO(raw))).convert('RGB');x1,y1,x2,y2=row['bbox_xyxy']
    assert 0<=x1<x2<=im.width and 0<=y1<y2<=im.height
    crop=im.crop((x1,y1,x2,y2));buf=io.BytesIO();crop.save(buf,format='PNG');rawcrop=buf.getvalue()
    assert len(rawcrop)<2*1024**2
    out.append({**row,'sha256':hashlib.sha256(rawcrop).hexdigest(),'dimensions':list(crop.size),
        'rgb_sha256':hashlib.sha256(str(crop.size).encode()+b'\0'+crop.tobytes()).hexdigest(),
        'png_base64':base64.b64encode(rawcrop).decode()})
print(json.dumps(out))
'''


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--regions',type=Path,required=True)
    p.add_argument('--staged-manifest',type=Path,required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args()
    regions=json.loads(a.regions.read_text());sources={r['source_id']:r for r in json.loads(a.staged_manifest.read_text())['samples']}
    if not 1<=len(regions)<=12:raise ValueError('Bounded crop retrieval must contain 1..12 regions')
    rows=[]
    for r in regions:
        source=sources[r['source_id']]
        if len(r['bbox_xyxy'])!=4 or any(not isinstance(v,int) for v in r['bbox_xyxy']):raise ValueError('Integer native-pixel box required')
        rows.append({**r,'remote_path':source['remote_path'],'source_sha256':source['sha256']})
    program='PLAN = '+repr(rows)+'\n'+REMOTE
    response=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/id_ed25519'),'-o','BatchMode=yes','-o','ConnectTimeout=30',
        'raphael@141.47.5.55','python3 -'],input=program.encode(),capture_output=True,check=True,timeout=180)
    a.output.mkdir(parents=True,exist_ok=True);receipts=[]
    for result in json.loads(response.stdout):
        raw=base64.b64decode(result.pop('png_base64'));assert c.sha(raw)==result['sha256']
        name=result['region_id']
        if not name.replace('-','').replace('_','').isalnum():raise ValueError('Invalid region ID')
        path=a.output/(name+'.png');path.write_bytes(raw);receipts.append({**result,'path':str(path.resolve())})
    c.write(a.output/'crop-receipts.json',{'crops':receipts,'regions_sha256':c.sha(a.regions.read_bytes()),
          'staged_manifest_sha256':c.sha(a.staged_manifest.read_bytes()),'script_sha256':c.sha(Path(__file__).read_bytes()),
          'transform':'EXIF transpose, RGB, exact native-pixel rectangle; no enhancement or inference-generated pixels'})
    print(json.dumps({'crops':len(receipts)}))


if __name__=='__main__':main()
