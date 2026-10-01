#!/usr/bin/env python3
"""Render a paired encoded-video replay review; polylines, not a recording of app UI."""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import cv2
import numpy as np


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dataset',type=Path,required=True)
    p.add_argument('--dense',type=Path,required=True)
    p.add_argument('--sparse',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--dense-label',default='10 Hz, unchanged lane pipeline')
    p.add_argument('--sparse-label',default='2 Hz, held until next sample')
    a=p.parse_args()
    if a.output.exists():p.error('Output exists')
    dense={r['id']:r for r in map(json.loads,a.dense.open())}
    sparse={r['id']:r for r in map(json.loads,a.sparse.open())}
    groups=defaultdict(list)
    for f in json.loads(a.dataset.read_text())['frames']:groups[f['sequenceId']].append(f)
    writer=cv2.VideoWriter(str(a.output),cv2.VideoWriter_fourcc(*'avc1'),10,(1280,444))
    if not writer.isOpened():raise RuntimeError('H.264 video writer unavailable')
    try:
        for seq,frames in groups.items():
            held=None
            for f in frames:
                if f['id'] in sparse:held=sparse[f['id']]
                rgb=cv2.resize(cv2.imread(f['rgbPath']),(640,360))
                panels=[]
                for label,r in [(a.sparse_label,held),(a.dense_label,dense[f['id']])]:
                    panel=np.zeros((444,640,3),np.uint8);panel[50:410]=rgb
                    if r:
                        visible=set(r['visibleBoundaryIndices'])
                        for i,b in enumerate(r['rawBoundaries']):
                            pts=np.array([[round(x*639),round(y*359)+50] for x,y in b['points']],np.int32)
                            cv2.polylines(panel,[pts],False,(40,240,40) if i in visible else (60,60,200),2 if i in visible else 1,cv2.LINE_AA)
                        cv2.putText(panel,'IDs '+str(r['visibleIDs']),(8,432),cv2.FONT_HERSHEY_SIMPLEX,.5,(240,240,240),1)
                    cv2.putText(panel,label,(8,21),cv2.FONT_HERSHEY_SIMPLEX,.57,(255,255,255),1)
                    cv2.putText(panel,f'{seq} | original PTS {f["time"]:.3f}s | green=visible red=other',(8,42),cv2.FONT_HERSHEY_SIMPLEX,.43,(200,200,200),1)
                    panels.append(panel)
                writer.write(np.hstack(panels))
    finally:
        writer.release()
    print('Wrote 60-second diagnostic comparison; encoded-video geometry only, no GPS/calibration or live UI reproduction.')


if __name__=='__main__':main()
