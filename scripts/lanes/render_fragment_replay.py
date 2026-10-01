#!/usr/bin/env python3
"""Render comparable encoded-pixel replay overlays, preserving each actual paint segment."""
import argparse,json
from pathlib import Path
import cv2,numpy as np
from evaluate_fragment_replay import read_replay
p=argparse.ArgumentParser(description=__doc__);p.add_argument('--manifest',type=Path,required=True);p.add_argument('--replay',action='append',required=True);p.add_argument('--output',type=Path,required=True);a=p.parse_args();frames=json.loads(a.manifest.read_text())['frames'];arms={}
for spec in a.replay:
 name,path=spec.split('=',1);arms[name]={r['id']:r for r in read_replay(path)[0]}
if len(arms) not in (2,4,6):raise ValueError('Two, four or six arms required')
a.output.parent.mkdir(parents=True,exist_ok=True);writer=cv2.VideoWriter(str(a.output),cv2.VideoWriter_fourcc(*'avc1'),10,(1280,360*(len(arms)//2)))
if not writer.isOpened():raise RuntimeError('H264 writer unavailable')
for f in frames:
 gray=np.frombuffer(Path(f['grayPath']).read_bytes(),np.uint8).reshape(f['height'],f['width']);tiles=[]
 for name,rows in arms.items():
  r=rows[f['id']];im=cv2.resize(cv2.cvtColor(gray,cv2.COLOR_GRAY2BGR),(640,360))
  for identity,b in zip(r['visibleIDs'],r['confirmedBoundaries']):
   for segment in b.get('observedSegments') or [b['points']]:
    pts=np.array([[round(x*639),round(y*359)] for x,y in segment]);cv2.polylines(im,[pts],False,(0,80,255),2)
    if len(pts):cv2.putText(im,str(identity),tuple(pts[-1]),0,.45,(0,255,255),1)
  cv2.rectangle(im,(0,0),(640,44),(0,0,0),-1);cv2.putText(im,f"{name}: {f['time']:.2f}s | {len(r['confirmedBoundaries'])} visible",(10,18),0,.5,(255,255,255),1);cv2.putText(im,f['sequenceId'],(10,37),0,.45,(255,255,255),1);tiles.append(im)
 writer.write(np.vstack([np.hstack(tiles[i:i+2]) for i in range(0,len(tiles),2)]))
writer.release();cap=cv2.VideoCapture(str(a.output));count=0
while cap.read()[0]:count+=1
cap.release()
if count!=len(frames):raise RuntimeError(f'Video frame count {count} != {len(frames)}')
print(f'{count} fully decoded output frames; 10Hz display cadence, source PTS shown. This is offline visualization, not device output.')
