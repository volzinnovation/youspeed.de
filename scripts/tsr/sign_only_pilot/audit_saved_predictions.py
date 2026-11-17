#!/usr/bin/env python3
"""Visualize existing sealed holdout predictions; never run holdout inference."""
import argparse
import hashlib
import html
import json
from pathlib import Path
from PIL import Image
import train_evaluate as base
from mobile_replay import visual


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('manifest','dataset-root','predictions','predictions-sha256','output'):
        p.add_argument('--'+name,required=True)
    p.add_argument('--threshold',type=float,required=True)
    a=p.parse_args()
    if base.sha(a.predictions)!=a.predictions_sha256:
        raise ValueError('Saved prediction hash mismatch')
    root=Path(a.dataset_root).resolve()
    frames={r['image_id']:r for r in json.loads(Path(a.manifest).read_text())['frames']}
    records=json.loads(Path(a.predictions).read_text())
    out=Path(a.output);out.mkdir(parents=True,exist_ok=False)
    rows=[]; pages=[]
    for r in records:
        frame=frames[r['image_id']]
        path=base.checked_path(root,frame['image_path'],frame['image_sha256'])
        label=base.checked_path(root,frame['label_path'],frame['label_sha256'])
        truth=base.read_yolo_labels(label,frame['width'],frame['height'])
        if truth != r['truth']:
            raise ValueError('Saved ground truth changed')
        predictions=[v for v in r['predictions'] if v['score']>=a.threshold]
        stem=hashlib.sha256(r['image_id'].encode()).hexdigest()[:20]
        with Image.open(path) as source:
            image=source.convert('RGB')
        finding=visual(image,truth,predictions,out/(stem+'.jpg'))
        details=[]
        targets=[('FN',str(i),truth[i]) for i in finding['missed_truth_indices']]
        targets += [('FP',str(i),r['box']) for i,r in enumerate(finding['false_positives'])]
        for kind,index,box in targets:
            cx,cy=(box[0]+box[2])/2,(box[1]+box[3])/2
            side=max(256,2*max(box[2]-box[0],box[3]-box[1]))
            window=(max(0,int(cx-side/2)),max(0,int(cy-side/2)),
                    min(image.width,int(cx+side/2)),min(image.height,int(cy+side/2)))
            file=stem+'-'+kind+'-'+index+'.png'
            image.crop(window).save(out/file)
            details.append({'kind':kind,'index':index,'image':file,'window_xyxy':window,
                            'reason':'unadjudicated','reference_box_xyxy':box})
        rows.append({'image_id':r['image_id'],'adjudication':'pending_visual_review',**finding})
        rows[-1]['native_error_crops']=details
        pages.append('<h2>'+html.escape(r['image_id'])+'</h2><img width="100%" src="'+stem+'.jpg">')
        pages.extend('<p>'+d['kind']+' '+d['index']+'</p><img style="max-width:100%" src="'+d['image']+'">' for d in details)
    base.write(out/'review-queue.json',{'predictions_sha256':a.predictions_sha256,'threshold':a.threshold,
        'new_inference':False,'reviewed':False,'frames':rows})
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Sealed holdout error audit</title><body style="max-width:1600px;margin:auto;font:18px sans-serif"><h1>Existing holdout predictions</h1><p>Yellow: missed reference; green: matched reference; red: unmatched proposal. Model-assisted labels. Visual adjudication pending. No new holdout inference.</p>'+''.join(pages)+'</body>')


if __name__=='__main__':main()
