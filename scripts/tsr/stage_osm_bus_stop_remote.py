#!/usr/bin/env python3
"""Stage bounded public imagery on KI and return small, hash-checked previews."""
import argparse
import base64
import json
from pathlib import Path
import subprocess
import collect_osm_bus_stop_crops as c

REMOTE = r'''
import base64,hashlib,io,json,pathlib,urllib.request
from PIL import Image,ImageOps
def read(url,limit):
    with urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'YouSpeed-DE224-bounded-research/1.0'}),timeout=30) as r:
        b=r.read(limit+1)
        if len(b)>limit:raise ValueError('byte limit')
        return b
def sha(b):return hashlib.sha256(b).hexdigest()
out=[];root=pathlib.Path('/tmp/youspeed-osm-de224-staged');root.mkdir(exist_ok=True)
for item in PLAN:
    try:
        rawmeta=read(item['source_url'],4*1024**2);meta=json.loads(rawmeta);prop=meta['properties']
        assert str(meta['id'])==item['source_id'] and str(meta['collection'])==item['sequence_id']
        assert meta['geometry']['coordinates'][:2]==item['coordinates']
        assert prop.get('geovisio:visibility')=='anyone' and prop.get('geovisio:status')=='ready'
        url=meta['assets']['hd']['href'];raw=read(url,25*1024**2)
        after=json.loads(read(item['source_url'],4*1024**2))
        assert after['properties'].get('geovisio:visibility')=='anyone'
        assert after['properties'].get('updated')==prop.get('updated') and after['assets']==meta['assets']
        path=root/(item['source_id']+'.jpg');path.write_bytes(raw)
        with Image.open(io.BytesIO(raw)) as im:
            assert im.width*im.height<=70000000
            im=ImageOps.exif_transpose(im).convert('RGB');rgb=sha(str(im.size).encode()+b'\0'+im.tobytes());size=list(im.size)
            im.thumbnail((1280,640));buf=io.BytesIO();im.save(buf,format='JPEG',quality=72)
        out.append({'source_id':item['source_id'],'sha256':sha(raw),'rgb_sha256':rgb,'dimensions':size,
                    'source_metadata':meta,'source_metadata_sha256':sha(rawmeta),'remote_path':str(path),
                    'source_asset_url':url,'preview_base64':base64.b64encode(buf.getvalue()).decode()})
    except Exception as exc:out.append({'source_id':item['source_id'],'error_type':type(exc).__name__})
print(json.dumps(out))
'''


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--candidates',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--holdouts',type=Path,nargs='+',required=True)
    p.add_argument('--max-images',type=int,default=4);a=p.parse_args()
    if not 1<=a.max_images<=8:raise ValueError('Bounded stage must contain 1..8 images')
    protected=c.protection(a.holdouts);doc=json.loads(a.candidates.read_text());rows=[];sites=set();routes=set()
    for r in sorted(doc['candidates'],key=lambda r:r['selection_score']):
        site=(r['osm_anchor']['osm_type'],r['osm_anchor']['osm_id'])
        if r['provider']=='mapillary' or r.get('exclusion_reasons') or c.excluded(r,protected):continue
        if site in sites or set(r['route_tokens'])&routes:continue
        rows.append(r);sites.add(site);routes.update(r['route_tokens'])
        if len(rows)>=a.max_images:break
    a.output.mkdir(parents=True,exist_ok=True)
    plan={'samples':rows,'source_sha256':c.sha(a.candidates.read_bytes()),'holdout_receipts':protected['receipts'],
          'script_sha256':c.sha(Path(__file__).read_bytes()),'helper_sha256':c.sha(Path(c.__file__).read_bytes())}
    c.write(a.output/'selection-frozen.json',plan)
    program='PLAN = '+repr([{k:r[k] for k in ['source_id','source_url','sequence_id','coordinates']} for r in rows])+'\n'+REMOTE
    response=subprocess.run(['ssh','-i',str(Path.home()/'.ssh/id_ed25519'),'-o','BatchMode=yes','-o','ConnectTimeout=30',
                             'raphael@141.47.5.55','python3 -'],input=program.encode(),capture_output=True,check=True,timeout=300)
    returned=json.loads(response.stdout);byid={r['source_id']:r for r in rows};accepted=[];failures=[]
    for result in returned:
        if result.get('error_type'):failures.append(result);continue
        if result['source_id'] not in byid:raise ValueError('Unexpected returned identity')
        if result['sha256'] in protected['pixels'] or result['rgb_sha256'] in protected['pixels']:
            failures.append({'source_id':result['source_id'],'error_type':'ProtectedPixels'});continue
        preview=base64.b64decode(result.pop('preview_base64'));n=len(accepted)+1
        path=a.output/f'R{n:03}.jpg';path.write_bytes(preview)
        accepted.append({**byid[result['source_id']],**result,'preview_path':str(path.resolve()),
                         'preview_sha256':c.sha(preview),'display_id':f'R{n:03}',
                         'download_transport':'authorized_KI_public_https','label':None,'human_approved':False,
                         'training_only':True,'evaluation_eligible':False})
    c.write(a.output/'staged-candidates.json',{'samples':accepted,'failures':failures,
             'selection_sha256':c.sha((a.output/'selection-frozen.json').read_bytes()),'labels_assigned':False,
             'raw_images_location':'hash-pinned temporary files on authorized KI; previews retained locally'})
    print(json.dumps({'staged':len(accepted),'failed':len(failures)}))


if __name__=='__main__':main()
