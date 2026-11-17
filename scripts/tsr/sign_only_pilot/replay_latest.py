#!/usr/bin/env python3
"""Post-selection development replay using the audited phone-window helpers."""
import argparse
import hashlib
import html
import json
from pathlib import Path
import re
import train_evaluate as base
import mobile_replay as phone


def run(args):
    import torch
    import ultralytics
    from PIL import Image
    from ultralytics import YOLO
    assert ultralytics.__version__=='8.4.213'
    assert base.sha(args.manifest)==args.manifest_sha256
    specs=json.loads(Path(args.models).read_text())
    assert len({s['name'] for s in specs})==len(specs)
    for spec in specs:
        assert re.fullmatch('d[0-9]+',spec['name'])
        assert re.fullmatch('[0-9a-f]{64}',spec['sha256']) and base.sha(spec['path'])==spec['sha256']
    manifest=json.loads(Path(args.manifest).read_text())
    frames=base.partition_manifest(manifest)['validation']
    native=None
    if args.native_inputs:
        native=json.loads((Path(args.native_inputs)/'manifest.json').read_text())
        assert native['schema']=='streetshots-native-detector-inputs-v1'
        assert native['source_images']==len(frames)
        native_rows={(r['image_id'],r['mode'],r['pass_index']):r for r in native['frames']}
        assert len(native_rows)==len(native['frames'])
    root=Path(args.dataset_root).resolve();out=Path(args.output);out.mkdir(parents=True,exist_ok=False)
    (out/'images').mkdir();summaries={};links=[]
    for spec in specs:
        name=spec['name'];checkpoint=spec['path']
        if spec.get('format')=='d4_state_dict':
            assert spec['sha256']==base.D4_SHA
            checkpoint=out/'d4-runtime.pt'
            base.save_yolo(checkpoint,base.sign_model('d4',args.coco,spec['path']),0)
        model=YOLO(checkpoint)
        for mode in ('whole','phone_windows'):
            records=[]
            for frame in frames:
                path=base.checked_path(root,frame['image_path'],frame['image_sha256'])
                label=base.checked_path(root,frame['label_path'],frame['label_sha256'])
                with Image.open(path) as source:image=source.convert('RGB')
                assert image.size==(frame['width'],frame['height'])
                truth=base.read_yolo_labels(label,*image.size);passes=[]
                for index,window in enumerate(phone.windows(*image.size,dual=mode=='phone_windows')):
                    if native:
                        row=native_rows[(frame['image_id'],mode,index)]
                        assert row['source_sha256']==frame['image_sha256'] and row['window_xyxy']==list(window)
                        png=base.checked_path(Path(args.native_inputs).resolve(),row['path'],row['sha256'])
                        with Image.open(png) as raster:rendered=raster.convert('RGB')
                        assert rendered.size==(1024,1024)
                    else:rendered=phone.render(image,window)
                    result=model.predict(rendered,imgsz=1024,conf=.25,iou=.45,
                        max_det=300,rect=False,device=args.device,quantize=32,tile=False,channels_last=False,verbose=False)[0]
                    rows=[]
                    for box,score,cls in zip(result.boxes.xyxy.cpu().tolist(),result.boxes.conf.cpu().tolist(),result.boxes.cls.cpu().tolist()):
                        mapped=phone.source_box(box,window)
                        if cls==0 and mapped:rows.append({'box':mapped,'score':score})
                    passes.append(rows)
                predictions,truncated=phone.admit(passes,phone.PHONE_THRESHOLD)
                records.append({'image_id':frame['image_id'],'group_id':frame['group_id'],
                    'truth':truth,'passes':passes,'predictions':predictions,'truncated':truncated,
                    'acceptable_extra_candidates':frame.get('acceptable_extra_candidates',[])})
                stem=name+'-'+mode+'-'+hashlib.sha256(frame['image_id'].encode()).hexdigest()[:16]
                phone.visual(image,truth,predictions,out/'images'/(stem+'.jpg'))
                links.append(f'<h3>{html.escape(name+" "+mode+" "+frame["image_id"])}</h3><img loading="lazy" width="100%" src="images/{stem}.jpg">')
            key=name+'-'+mode;base.write(out/(key+'-predictions.json'),records)
            sweep=[]
            for t in [v/100 for v in range(25,100)]:
                rescored=[{**r,'predictions':phone.admit(r['passes'],t)[0]} for r in records]
                sweep.append({k:v for k,v in base.score_frames(rescored,t).items() if k!='frames'})
            summaries[key]={'phone_threshold':base.score_frames(records,phone.PHONE_THRESHOLD),'development_sweep':sweep}
    base.write(out/'summary.json',{'split':'validation','images':len(frames),'models':specs,
        'native_parity_verified':False,'renderer':native['renderer'] if native else 'Pillow bilinear approximation',
        'native_input_manifest_sha256':base.sha(Path(args.native_inputs)/'manifest.json') if native else None,
        'runtime':'Ultralytics 8.4.213 / PyTorch FP32; not Core ML FP16','threshold':phone.PHONE_THRESHOLD,
        'script_sha256':base.sha(__file__),'phone_helper_sha256':base.sha(phone.__file__),
        'manifest_sha256':args.manifest_sha256,'results':summaries})
    renderer=native['renderer'] if native else 'Pillow bilinear approximation'
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>Selected candidates: development replay</title><body style="max-width:1600px;margin:auto;font:18px sans-serif"><h1>Development replay</h1><p>Green: matched reference; yellow: missed reference; red: unmatched proposal. Model-assisted labels. '+html.escape(renderer)+'. FP32 inference on KI; Core ML numerical parity and phone latency unverified. No fresh holdout score.</p>'+''.join(links)+'</body>')


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('manifest','manifest-sha256','dataset-root','models','coco','output'):p.add_argument('--'+name,required=True)
    p.add_argument('--device',default='0')
    p.add_argument('--native-inputs')
    run(p.parse_args())
