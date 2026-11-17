#!/usr/bin/env python3
"""Measure retained teacher proposal additions and render a qualitative gallery."""
import gzip
import hashlib
import json
import math
from pathlib import Path
from PIL import Image, ImageDraw
from train_mixed import iou

ROOT=Path('/home/raphael/streetshots-d5-20261114/expanded-v1')
PREFIX='reviews/detector-expanded-2026-11-15'


def main():
    overlay=ROOT/'dataset'/PREFIX
    manifest=json.loads((overlay/'manifest.json').read_text())
    source={r['picture_id']:r for line in gzip.open(ROOT/'source-membership.jsonl.gz','rt') if (r:=json.loads(line))}
    additions=[];retained=0;positive_frames=0;map_cued=set()
    for frame in manifest['frames']:
        if frame.get('supervision')!='teacher_pseudo':continue
        r=json.loads((ROOT/'pseudo-labels'/(frame['picture_id']+'.json')).read_text())
        valid=[]
        for annotation in source[frame['picture_id']]['existing_sign_annotations']:
            b=annotation.get('box_xyxy')
            if b and len(b)==4 and 0<=b[0]<b[2]<=r['width'] and 0<=b[1]<b[3]<=r['height']:valid.append(b)
        positive_frames+=bool(r['accepted_boxes']);retained+=len(r['accepted_boxes'])
        for box in r['accepted_boxes']:
            if all(iou(box['box'],prior)<.5 for prior in valid):
                assert box['origin']=='offline_teacher'
                additions.append({'picture_id':frame['picture_id'],'image_sha256':frame['image_sha256'],
                                  'box':box['box'],'teacher_score':box['score'],
                                  'scope_label':box['class_label'],'scope_confidence':box['class_confidence'],
                                  'existing_source_box_count':len(valid),
                                  'mapillary_candidate_count':r['mapillary_class_blind_candidate_count']})
                if r['mapillary_class_blind_candidate_count']>0:map_cued.add(frame['picture_id'])
    report={'manifest_sha256':hashlib.sha256((overlay/'manifest.json').read_bytes()).hexdigest(),'script_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),'schema':'streetshots-retained-teacher-additions-v1','retained_pseudo_boxes':retained,
            'retained_pseudo_positive_frames':positive_frames,'additional_proposal_boxes':len(additions),
            'frames_with_additional_proposals':len({r['picture_id'] for r in additions}),
            'additional_frames_with_mapillary_candidates':len(map_cued),
            'definition':'Retained teacher box has IoU below0.5 with every valid existing source sign box.',
            'limitation':'Proposal-level novelty, not a count of verified new physical signs; includes localization changes and possible label errors. Map cues do not establish causal discovery or visibility.',
            'boxes':additions}
    (overlay/'teacher-additions.json').write_text(json.dumps(report,indent=2)+'\n')
    selected=sorted(additions,key=lambda r:hashlib.sha256((r['picture_id']+json.dumps(r['box'])).encode()).hexdigest())[:24]
    out=overlay/'teacher-additions-review';out.mkdir(exist_ok=False)
    for start in range(0,len(selected),12):
        sheet=Image.new('RGB',(1200,1200),'#202020');draw=ImageDraw.Draw(sheet)
        for j,row in enumerate(selected[start:start+12]):
            with Image.open(ROOT/'source-images'/(row['image_sha256']+'.jpg')) as source_image:
                x1,y1,x2,y2=row['box'];pad=max(12,(x2-x1)*.35,(y2-y1)*.35)
                bounds=(max(0,math.floor(x1-pad)),max(0,math.floor(y1-pad)),min(source_image.width,math.ceil(x2+pad)),min(source_image.height,math.ceil(y2+pad)))
                crop=source_image.crop(bounds).convert('RGB');crop.thumbnail((380,250))
                sx=crop.width/(bounds[2]-bounds[0]);sy=crop.height/(bounds[3]-bounds[1])
                ImageDraw.Draw(crop).rectangle(((x1-bounds[0])*sx,(y1-bounds[1])*sy,(x2-bounds[0])*sx,(y2-bounds[1])*sy),outline='lime',width=2)
                x=j%3*400;y=j//3*300;sheet.paste(crop,(x,y))
                draw.text((x+4,y+255),str(start+j)+' '+row['scope_label'],fill='white')
                draw.text((x+4,y+275),row['picture_id'][:22],fill='white')
        sheet.save(out/f'additions-{start//12:02d}.jpg',quality=94)
    (out/'index.json').write_text(json.dumps({'selection':'First24 retained additions by fixed hash; not a certified precision/recall sample','entries':selected},indent=2)+'\n')
    print(json.dumps({k:v for k,v in report.items() if k!='boxes'}))


if __name__=='__main__':main()
