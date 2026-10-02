#!/usr/bin/env python3
"""Render frozen manual paint labels (green) against each replay's actual visible segments (red)."""
import argparse,json
from pathlib import Path
import cv2,numpy as np
from evaluate_fragment_replay import x_at,read_replay
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--labels',type=Path,required=True);p.add_argument('--replay',action='append',required=True,help='name=/path/frames.ndjson');p.add_argument('--output-dir',type=Path,required=True);a=p.parse_args();a.output_dir.mkdir(parents=True,exist_ok=True)
labels=json.loads(a.labels.read_text());arms={}
for specification in a.replay:
 name,file=specification.split('=',1);arms[name]={r['id']:r for r in read_replay(file)[0]}
for f in labels['frames']:
 if not all(f['id'] in rows for rows in arms.values()):continue
 tiles=[]
 for name,rows in arms.items():
  im=cv2.imread(f['image']);h,w=im.shape[:2]
  def pts(values):return np.array([[round(x*w),round(y*h)] for x,y in values])
  for b in f['borders']:
   for lo,hi in b['paintedYIntervals']:
    v=[[x_at(b['geometry'],float(y)),float(y)] for y in np.linspace(lo,hi,60)];v=[q for q in v if q[0] is not None]
    if len(v)>1:cv2.polylines(im,[pts(v)],False,(0,220,0),5)
  r=rows[f['id']]
  for b in r['confirmedBoundaries']:
   for seg in b.get('observedSegments') or [b['points']]:cv2.polylines(im,[pts(seg)],False,(20,20,255),3)
  cv2.rectangle(im,(0,0),(w,48),(0,0,0),-1);cv2.putText(im,f"{name} | {f['id']} | visible {len(r['confirmedBoundaries'])}",(12,31),0,.65,(255,255,255),2);tiles.append(im)
 while len(tiles)%2:tiles.append(np.zeros_like(tiles[0]))
 cv2.imwrite(str(a.output_dir/f"{f['id']}.jpg"),np.vstack([np.hstack(tiles[i:i+2]) for i in range(0,len(tiles),2)]),[cv2.IMWRITE_JPEG_QUALITY,90])
