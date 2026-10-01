#!/usr/bin/env python3
"""Render only manual labels; useful for auditing annotation errors without model output."""
import argparse,json
from pathlib import Path
import cv2,numpy as np
from evaluate_fragment_replay import x_at
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--labels',type=Path,required=True);p.add_argument('--output-dir',type=Path,required=True);a=p.parse_args();labels=json.loads(a.labels.read_text());a.output_dir.mkdir(parents=True,exist_ok=True)
for split in sorted({f['split'] for f in labels['frames']}):
 tiles=[]
 for f in labels['frames']:
  if f['split']!=split:continue
  im=cv2.imread(f['image']);h,w=im.shape[:2]
  def pts(values):return np.array([[round(x*w),round(y*h)] for x,y in values])
  for b in f['borders']:
   cv2.polylines(im,[pts(b['geometry'])],False,(0,255,255),2)
   for lo,hi in b['paintedYIntervals']:
    v=[[x_at(b['geometry'],float(y)),float(y)] for y in np.linspace(lo,hi,60)];v=[q for q in v if q[0] is not None]
    if len(v)>1:cv2.polylines(im,[pts(v)],False,(0,220,0),6)
  for b in f.get('ignoreGeometry',[]):cv2.polylines(im,[pts(b['points'])],False,(200,0,200),10)
  cv2.putText(im,f['id'],(15,28),0,.65,(255,255,0),2);tiles.append(cv2.resize(im,(640,360)))
 while len(tiles)%2:tiles.append(np.zeros_like(tiles[0]))
 cv2.imwrite(str(a.output_dir/f'{split}-manual-labels.jpg'),np.vstack([np.hstack(tiles[i:i+2]) for i in range(0,len(tiles),2)]))
