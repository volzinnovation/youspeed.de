#!/usr/bin/env python3
"""Deterministic paired view geometry and balanced schedules; no ML dependency."""
import math
import random
from collections import defaultdict
from mobile_replay import windows


def transform_boxes(boxes, window):
    """Reject a view containing a clipped known sign; never silently erase it."""
    x,y,r,b=window;scale=1024/max(r-x,b-y);dx=(1024-(r-x)*scale)/2;dy=(1024-(b-y)*scale)/2
    result=[]
    for box in boxes:
        a,c,d,e=box
        if min(r,d)<=max(x,a) or min(b,e)<=max(y,c):continue
        if a<x-1e-4 or c<y-1e-4 or d>r+1e-4 or e>b+1e-4:return None
        result.append([(a-x)*scale+dx,(c-y)*scale+dy,(d-x)*scale+dx,(e-y)*scale+dy])
    return result


def views_for(width,height,boxes):
    result=[]
    for window in windows(width,height):
        labels=transform_boxes(boxes,window)
        if labels is not None:result.append({'kind':'phone','window':list(window),'boxes':labels})
    for index,box in enumerate(boxes):
        if min(box[2]-box[0],box[3]-box[1])*1024/min(width,height)>=24:continue
        size=min(width,height,max(512,min(1536,math.ceil(min(box[2]-box[0],box[3]-box[1])*1024/48))))
        cx,cy=(box[0]+box[2])/2,(box[1]+box[3])/2
        x=max(0,min(width-size,round(cx-size/2)));y=max(0,min(height-size,round(cy-size/2)))
        window=[x,y,x+size,y+size];labels=transform_boxes(boxes,window)
        if labels and window not in [r['window'] for r in result]:result.append({'kind':'small','window':window,'boxes':labels,'target_box_index':index})
    return result


def paired_schedules(views,epochs=40,draws=1024,seed=14):
    assert draws%4==0
    groups=defaultdict(lambda:defaultdict(list))
    for v in views:
        key='small' if v['kind']=='small' else 'positive' if v['boxes'] else 'negative'
        # Empty phone crops from positive parents are deliberately not sampled as verified negatives.
        if key=='negative' and v['parent_positive']:continue
        groups[key][v['picture_id']].append(v['view_id'])
    small_parents=set(groups['small']) & set(groups['positive'])
    groups['small']={k:v for k,v in groups['small'].items() if k in small_parents}
    assert all(groups[k] for k in ('positive','negative','small'))
    rng=random.Random(seed);queues={k:[] for k in groups};schedules=[]
    def draw_parent(key):
        if not queues[key]:queues[key]=sorted(groups[key]);rng.shuffle(queues[key])
        return queues[key].pop()
    for epoch in range(epochs):
        categories=['positive']*(draws//4)+['negative']*(draws//4)+['small']*(draws//2);rng.shuffle(categories);rows=[]
        for cat in categories:
            parent=draw_parent(cat);base=rng.choice(groups['positive' if cat=='small' else cat][parent]);mixed=rng.choice(groups['small'][parent]) if cat=='small' else base
            rows.append({'picture_id':parent,'category':cat,'phone':base,'mixed':mixed})
        schedules.append(rows)
    return schedules,{k:len(v) for k,v in groups.items()}
