#!/usr/bin/env python3
"""Extract disjoint, upright raw-gray day/dawn clips; never derive truth from detector output."""
import argparse, hashlib, json
from pathlib import Path
import cv2
import numpy as np

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for block in iter(lambda:f.read(1024*1024),b''): h.update(block)
    return h.hexdigest()

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--config',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True);a=p.parse_args()
    config=json.loads(a.config.read_text());out=a.output_dir.resolve();out.mkdir(parents=True,exist_ok=False)
    (out/'frames').mkdir();(out/'annotation-images').mkdir()
    sources={};frames=[];samples=[]
    for sid,source in config['sources'].items():
        path=Path(source['path']).resolve(); actual=sha(path)
        if actual!=source['sha256']: raise ValueError(f'Source changed: {sid}')
        sources[sid]={**source,'path':str(path),'bytes':path.stat().st_size}
    clips=config['clips']
    for i,c in enumerate(clips):
        if c['end']<=c['start']:raise ValueError('empty clip')
        for excluded in config.get('excludeClips',[]):
            if excluded['source']==c['source'] and max(excluded['start'],c['start'])<min(excluded['end'],c['end']):raise ValueError('new interval overlaps previously reviewed footage')
        for other in clips[:i]:
            if other['source']==c['source'] and max(other['start'],c['start'])<min(other['end'],c['end']):raise ValueError('overlapping clip intervals')
    for clip in clips:
        cap=cv2.VideoCapture(sources[clip['source']]['path']);cap.set(cv2.CAP_PROP_ORIENTATION_AUTO,1)
        cap.set(cv2.CAP_PROP_POS_MSEC,clip['start']*1000)
        target=clip['start'];count=0;sample_targets=[clip['start']+v for v in (1,3.5,6,8.5)] if clip['split']=='heldout' else [clip['start']+3,clip['end']-3]
        while target<clip['end']-1e-6:
            ok,bgr=cap.read()
            if not ok:raise RuntimeError(f'Unexpected EOF {clip}')
            pts=cap.get(cv2.CAP_PROP_POS_MSEC)/1000
            if pts+1e-6<target:continue
            h,w=bgr.shape[:2];gray=cv2.cvtColor(bgr,cv2.COLOR_BGR2GRAY)
            # Match the existing replay's center-sampled nearest-neighbor analysis plane.
            ys=np.minimum(h-1,((np.arange(216)+.5)*h/216).astype(int));xs=np.minimum(w-1,((np.arange(384)+.5)*w/384).astype(int))
            luma=gray[np.ix_(ys,xs)];fid=f"{clip['id']}-{count:04d}";raw=out/'frames'/f'{fid}.gray';raw.write_bytes(luma.tobytes())
            f=dict(id=fid,sequenceId=clip['id'],grayPath=str(raw),graySha256=sha(raw),width=384,height=216,decodedWidth=w,decodedHeight=h,time=pts,source=sources[clip['source']]['path'],sourceId=clip['source'],split=clip['split'],sceneTags=clip['tags'])
            frames.append(f)
            if sample_targets and pts+1e-6>=sample_targets[0]:
                sample_targets.pop(0);im=out/'annotation-images'/f'{fid}.jpg';cv2.imwrite(str(im),cv2.resize(bgr,(960,540)),[cv2.IMWRITE_JPEG_QUALITY,92]);samples.append(dict(id=fid,image=str(im),sequenceId=clip['id'],time=pts,split=clip['split'],sceneTags=clip['tags']))
            count+=1;target=clip['start']+count*.1
        cap.release();print(clip['id'],count,flush=True)
    for imported in config.get('importDevelopment',[]):
        old=json.loads(Path(imported).read_text())
        for f in old['frames']:
            f['grayPath']=str(Path(f['grayPath']).resolve());f['priorSplit']=f.get('split');f['split']='development';f['sourceId']=f.get('sourceId') or next((sid for sid,source in sources.items() if Path(source['path']).name==Path(f.get('source','')).name),'unknown');f['sceneTags']=list(dict.fromkeys(f.get('sceneTags',[])+['previously_reviewed']));frames.append(f)
    for split in ('development','heldout'):
        (out/f'{split}.json').write_text(json.dumps(dict(schemaVersion=1,frames=[f for f in frames if f['split']==split]),indent=2)+'\n')
    (out/'all.json').write_text(json.dumps(dict(schemaVersion=1,frames=frames),indent=2)+'\n')
    (out/'samples.json').write_text(json.dumps(samples,indent=2)+'\n')
    (out/'provenance.json').write_text(json.dumps(dict(schemaVersion=1,sources=sources,clips=clips,excludeClips=config.get('excludeClips',[]),importDevelopment=config.get('importDevelopment',[]),fps=10,grayscale='OpenCV BGR-to-gray from encoded video, center-sampled nearest-neighbor; not sensor Y',orientation='MOV metadata honored by OpenCV auto-orientation',splitQualification='Held-out exposure intervals disjoint from development; same drives/mounts, not independent drives; full night unavailable'),indent=2)+'\n')
if __name__=='__main__':main()
