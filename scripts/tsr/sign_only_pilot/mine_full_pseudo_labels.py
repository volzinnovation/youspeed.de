#!/usr/bin/env python3
"""Mine all frozen weak-training frames; explicit pseudo-label provenance.

Unknown classifier outcomes exclude the entire frame from supervised training.
Teacher-empty frames are marked pseudo-negatives, never reviewed negatives.
"""
import argparse
from collections import Counter
import gzip
import hashlib
import json
import math
from pathlib import Path
import time

TEACHER_SHA='a3205e4a92b3acdaa883c02e09dba439c48f6c5bc8c89aff44da7c2e79f140e7'
CLASSIFIER_SHA='b7bb41213631c042d547a7898704e35398e3fb2d909ac65d8d01f89c87e55a2e'


def sha(path):return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def scope(label,confidence):
    if confidence<.90:return 'uncertain'
    if label.startswith('bad') or label in ('exit','supplementary:plate','traffic_signal'):
        return 'excluded'
    if label.startswith('other') or label in ('no:other','no:other:dog'):
        return 'uncertain'
    return 'sign'


def positions(length,side=1536):
    if length<=side:return [0]
    return sorted(set(range(0,length-side+1,1152))|{length-side})


def main(a):
    from PIL import Image
    from ultralytics import YOLO
    import ultralytics
    import numpy as np
    import torch
    from train_evaluate import iou
    if ultralytics.__version__!='8.4.56':raise ValueError('Pinned runtime required')
    if sha(a.teacher)!=TEACHER_SHA or sha(a.classifier)!=CLASSIFIER_SHA:raise ValueError('Weight hash mismatch')
    root=Path(a.root);out=root/'pseudo-labels';out.mkdir(exist_ok=True)
    rows=[r for line in gzip.open(root/'source-membership.jsonl.gz','rt') if (r:=json.loads(line))['expanded_role']=='weak_training']
    hint_path=root.parent/'feasibility-output-backup/image-candidates.jsonl.gz'
    with gzip.open(hint_path,'rt') as handle:
        hints={r['picture_id']:r['candidate_count'] for line in handle if (r:=json.loads(line))}
    config={'schema':'streetshots-full-pseudo-policy-v1','teacher_sha256':TEACHER_SHA,'classifier_sha256':CLASSIFIER_SHA,
            'source_membership_sha256':sha(root/'source-membership.jsonl.gz'),'script_sha256':sha(__file__),
            'teacher_conf':.10,'teacher_iou':.45,'full_imgsz':2048,'tile_size':1536,'tile_stride':1152,
            'teacher_precision':'FP16','tile_batch':4,'teacher_rect':False,
            'classification_confidence':.90,'uncertain_policy':'exclude whole frame','negative_policy':'teacher-empty or confidently excluded candidates only; weak pseudo-negative, not certified absence',
            'mapillary_hints_sha256':sha(hint_path),'mapillary_policy':'class-blind geographic candidate count only; a positive hint blocks pseudo-negative admission; hints never create boxes',
            'source_annotations':'additional proposals; classifier scope filtering still required','classification_input':'exact candidate box, RGB resized224 square, no context enlargement',
            'train_candidates':len(rows),'execution_shards':a.shards,'review_provenance':'teacher_pseudo_labels_not_human_ground_truth'}
    encoded=(json.dumps(config,indent=2)+'\n').encode();policy=root/'pseudo-policy.json'
    if policy.exists() and policy.read_bytes()!=encoded:raise ValueError('Frozen mining policy differs')
    if not policy.exists():policy.write_bytes(encoded)
    policy_sha=sha(policy)
    rows=[r for r in rows if int(hashlib.sha256(r['picture_id'].encode()).hexdigest(),16)%a.shards==a.shard_index]
    status_path=root/('mining-status-shard%d.json'%a.shard_index)
    detector=YOLO(a.teacher);classifier=YOLO(a.classifier).model.float().to(a.device).eval()
    assert detector.names.get(0) in ('sign','traffic_sign')
    counts=Counter();remaining=[]
    for r in rows:
        f=out/(r['picture_id']+'.json')
        if f.exists():
            saved=json.loads(f.read_text());assert saved['policy_sha256']==policy_sha
            counts[saved['status']]+=1
        else:remaining.append(r)
    while remaining:
        progress=False;pending=[]
        for r in remaining:
            path=root/'source-images'/(r['image_sha256']+'.jpg')
            if not path.exists():pending.append(r);continue
            if sha(path)!=r['image_sha256']:raise ValueError('Source image mismatch')
            with Image.open(path) as source:image=source.convert('RGB')
            w,h=image.size;proposals=[]
            views=[((0,0,w,h),2048)]
            if max(w,h)>1536:
                views.extend(((x,y,min(x+1536,w),min(y+1536,h)),1536) for y in positions(h) for x in positions(w))
            for group,size in [(views[:1],2048),(views[1:],1536)]:
                if not group:continue
                results=detector.predict([image.crop(window) for window,_ in group],imgsz=size,
                    conf=.10,iou=.45,max_det=300,device=a.device,half=True,batch=4,rect=False,verbose=False)
                for (window,_),result in zip(group,results,strict=True):
                    for box,score,cls in zip(result.boxes.xyxy.cpu().tolist(),result.boxes.conf.cpu().tolist(),result.boxes.cls.cpu().tolist()):
                        if cls==0:proposals.append({'box':[box[0]+window[0],box[1]+window[1],box[2]+window[0],box[3]+window[1]],'score':score,'origin':'offline_teacher'})
            for ann in r['existing_sign_annotations']:
                b=ann.get('box_xyxy')
                if b and len(b)==4 and 0<=b[0]<b[2]<=w and 0<=b[1]<b[3]<=h:
                    proposals.append({'box':b,'score':1.0 if ann.get('label_origin')=='source_annotation' else .5,'origin':'source_annotation_proposal','annotation_id':ann.get('annotation_id')})
            merged=[]
            for proposal in sorted(proposals,key=lambda v:-v['score']):
                if all(iou(proposal['box'],v['box'])<=.5 for v in merged):merged.append(proposal)
            for start in range(0,len(merged),64):
                batch=merged[start:start+64];pixels=[]
                for row in batch:
                    b=row['box'];crop=image.crop((math.floor(b[0]),math.floor(b[1]),math.ceil(b[2]),math.ceil(b[3])))
                    pixels.append(np.array(crop.resize((224,224),Image.Resampling.BILINEAR),copy=True))
                tensor=torch.from_numpy(np.stack(pixels)).permute(0,3,1,2).float().to(a.device)/255
                with torch.inference_mode():scores=classifier(tensor)
                if isinstance(scores,(tuple,list)):scores=scores[0]
                values,indices=scores.max(1)
                for row,value,index in zip(batch,values.cpu().tolist(),indices.cpu().tolist()):
                    row['class_label']=classifier.names[index];row['class_confidence']=value;row['scope']=scope(row['class_label'],value)
            uncertain=any(row['scope']=='uncertain' for row in merged)
            accepted=[row for row in merged if row['scope']=='sign']
            status='excluded_uncertain_scope' if uncertain else 'pseudo_positive' if accepted else 'pseudo_negative'
            if status=='pseudo_negative' and hints.get(r['picture_id'],0)>0:status='excluded_map_disagreement'
            result={'picture_id':r['picture_id'],'image_sha256':r['image_sha256'],'width':w,'height':h,
                    'policy_sha256':policy_sha,'status':status,'annotation_complete':False,
                    'mapillary_class_blind_candidate_count':hints.get(r['picture_id'],0),
                    'human_verified':False,'accepted_boxes':accepted if not uncertain else [],'all_proposals':merged}
            target=out/(r['picture_id']+'.json');temp=target.with_suffix('.tmp');temp.write_text(json.dumps(result));temp.replace(target)
            counts[status]+=1;progress=True
            status_path.write_text(json.dumps({'processed':sum(counts.values()),'total':len(rows),'counts':counts,'complete':False}))
            if sum(counts.values())%50==0:print(json.dumps({'processed':sum(counts.values()),'counts':counts}),flush=True)
        remaining=pending
        if remaining and not progress:time.sleep(15)
    status_path.write_text(json.dumps({'processed':sum(counts.values()),'total':len(rows),'counts':counts,'complete':True}))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('root','teacher','classifier'):p.add_argument('--'+name,required=True)
    p.add_argument('--device',default='cuda:0')
    p.add_argument('--shards',type=int,default=2)
    p.add_argument('--shard-index',type=int,default=0)
    a=p.parse_args()
    if not 0<=a.shard_index<a.shards:p.error('Invalid shard')
    main(a)
