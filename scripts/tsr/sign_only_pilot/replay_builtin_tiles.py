#!/usr/bin/env python3
"""Development-only built-in tiled inference; explicitly not the phone pipeline."""
import argparse
import json
from pathlib import Path
import time
import train_evaluate as base
import mobile_replay as phone


def main(args):
    from ultralytics import YOLO
    import ultralytics
    from PIL import Image
    assert ultralytics.__version__=='8.4.213'
    assert base.sha(args.manifest)==args.manifest_sha256
    frames=base.partition_manifest(json.loads(Path(args.manifest).read_text()))['validation']
    out=Path(args.output);out.mkdir(parents=True,exist_ok=False);(out/'images').mkdir()
    results={}
    for spec in json.loads(Path(args.models).read_text()):
        assert base.sha(spec['path'])==spec['sha256']
        model=YOLO(spec['path']);records=[];timings=[]
        for i,frame in enumerate(frames):
            image=base.checked_path(Path(args.dataset_root).resolve(),frame['image_path'],frame['image_sha256'])
            label=base.checked_path(Path(args.dataset_root).resolve(),frame['label_path'],frame['label_sha256'])
            start=time.monotonic()
            prediction=model.predict(str(image),tile=True,imgsz=1024,batch=16,quantize=32,channels_last=False,
                       device='0',conf=.25,iou=.45,max_det=300,rect=False,verbose=False)[0]
            timings.append(time.monotonic()-start)
            rows=[{'box':b,'score':s} for b,s,c in zip(prediction.boxes.xyxy.cpu().tolist(),prediction.boxes.conf.cpu().tolist(),prediction.boxes.cls.cpu().tolist()) if c==0]
            truth=base.read_yolo_labels(label,frame['width'],frame['height'])
            record={'image_id':frame['image_id'],'group_id':frame['group_id'],'truth':truth,'predictions':rows,
                    'acceptable_extra_candidates':frame.get('acceptable_extra_candidates',[])}
            records.append(record)
            with Image.open(image) as im:phone.visual(im.convert('RGB'),truth,[r for r in rows if r['score']>=phone.PHONE_THRESHOLD],out/'images'/f'{spec["name"]}-{i:02d}.jpg')
        base.write(out/(spec['name']+'-predictions.json'),records)
        results[spec['name']]={'fixed_threshold':base.score_frames(records,phone.PHONE_THRESHOLD),
            'sweep':[{k:v for k,v in base.score_frames(records,t/100).items() if k!='frames'} for t in range(25,100)],
            'seconds_per_source_image_including_shared_gpu_contention':timings}
    base.write(out/'summary.json',{'split':'validation','images':len(frames),'version':ultralytics.__version__,
        'models':json.loads(Path(args.models).read_text()),'script_sha256':base.sha(__file__),
        'tile':True,'imgsz':1024,'batch':16,'quantize':32,'prediction_floor':.25,'nms_iou':.45,'max_det':300,
        'limitation':'Offline built-in tiling, not the phone two-crop pipeline; no per-pass phone cap. GPU shared timings are not phone latency or controlled throughput. Reused development set only.',
        'results':results})

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for k in ('manifest','manifest-sha256','dataset-root','models','output'):p.add_argument('--'+k,required=True)
    main(p.parse_args())
