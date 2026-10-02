#!/usr/bin/env python3
"""Exploratory image-flow probe at frozen replay paint anchors, not ground truth.

Uses identical starting exposures/anchors for 0.1 and 0.5 second comparisons.
Pyramidal LK allows vertical displacement beyond the production +/-2px window.
Rejects low texture, failed status, high patch error and forward/backward mismatch.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import cv2
import numpy as np
from audit_lane_runtime import quantiles


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--replay',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args()
    if a.output.exists():p.error('Output exists')
    cv2.setNumThreads(1)
    manifest=json.loads((a.replay/'input.normalized.json').read_text())
    output={r['id']:r for r in map(json.loads,(a.replay/'frames.ndjson').open())}
    sequences=defaultdict(list)
    for f in manifest['frames']:sequences[f['sequenceId']].append(f)
    records=[]
    for seq,frames in sequences.items():
        images=[np.fromfile(f['grayPath'],np.uint8).reshape(f['height'],f['width']) for f in frames]
        for i in range(0,len(frames)-5,5):
            h,w=images[i].shape
            anchors=[]
            for b in output[frames[i]['id']]['rawBoundaries']:
                if b['cue']!='paint':continue
                pts=b['points'];pts=[pts[j*(len(pts)-1)//7] for j in range(8)] if len(pts)>8 else pts
                for x,y in pts:
                    x,y=x*(w-1),y*(h-1);xi,yi=round(x),round(y)
                    if 3<=xi<w-3 and 3<=yi<h-3 and np.ptp(images[i][yi-2:yi+3,xi-2:xi+3])>=24:anchors.append([x,y])
            if not anchors:continue
            start=np.array(anchors,np.float32).reshape(-1,1,2)
            for step in [1,5]:
                end,ok,err=cv2.calcOpticalFlowPyrLK(images[i],images[i+step],start,None,winSize=(15,15),maxLevel=3,
                    criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,30,.01))
                back,reverse,_=cv2.calcOpticalFlowPyrLK(images[i+step],images[i],end,None,winSize=(15,15),maxLevel=3,
                    criteria=(cv2.TERM_CRITERIA_EPS|cv2.TERM_CRITERIA_COUNT,30,.01))
                valid=(ok[:,0]>0)&(reverse[:,0]>0)&(err[:,0]<=18)&(np.linalg.norm(back[:,0]-start[:,0],axis=1)<=1)
                valid &= (end[:,0,0]>=2)&(end[:,0,0]<w-2)&(end[:,0,1]>=2)&(end[:,0,1]<h-2)
                delta=end[:,0]-start[:,0]
                records.append(dict(sequence=seq,time=frames[i]['time'],step=step,
                    dt=frames[i+step]['time']-frames[i]['time'],tested=len(start),
                    flow=delta[valid].tolist()))
    def summary(rs):
        f=[xy for r in rs for xy in r['flow']]
        return dict(pairs=len(rs),testedAnchors=sum(r['tested'] for r in rs),acceptedAnchors=len(f),
            absoluteVerticalPixels=quantiles([abs(xy[1]) for xy in f]),
            absoluteHorizontalPixels=quantiles([abs(xy[0]) for xy in f]),
            verticalOver2Pixels=sum(abs(xy[1])>2 for xy in f),
            horizontalOver12Pixels=sum(abs(xy[0])>12 for xy in f))
    report=dict(method='OpenCV pyramidal LK, 15x15 window, 3 levels, <=18 mean patch error, <=1px forward/back error, >=24 local contrast. Same previous paint anchors for both intervals.',
                qualification='Exploratory encoded-image flow, not labelled correspondence or calibrated vehicle motion. Accepted subsets differ by interval. 384x216 video analysis differs from live 288x216.',
                total={str(step):summary([r for r in records if r['step']==step]) for step in [1,5]},
                sequences={s:{str(step):summary([r for r in records if r['step']==step and r['sequence']==s]) for step in [1,5]} for s in sequences},
                pairs=records)
    a.output.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report['total'],indent=2))


if __name__=='__main__':main()
