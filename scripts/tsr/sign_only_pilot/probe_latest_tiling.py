#!/usr/bin/env python3
"""Checkpoint compatibility and native tile seam checks on KI GPU0."""
import hashlib
import json
from pathlib import Path
import time
import train_evaluate as base

ROOT=Path('/job/latest-ultralytics-v1')
JOB=Path('/job')


def main():
    import torch
    import ultralytics
    from ultralytics import YOLO
    from ultralytics.data.utils import tile_windows
    from ultralytics.utils.ops import merge_tiles
    from PIL import Image,ImageDraw
    assert ultralytics.__version__=='8.4.213'
    assert base.sha(ROOT/'ultralytics-8.4.213-py3-none-any.whl')=='f785d4505a1f4d55f1f46c6ff27d8ff28154c857c964323c5bf610da7f389a97'
    out=ROOT/'probe';out.mkdir(exist_ok=False)
    def payload(boxes,confidence):
        return {'bboxes':torch.tensor(boxes,dtype=torch.float32).reshape(-1,4),
                'conf':torch.tensor(confidence),'cls':torch.zeros(len(confidence))}
    windows=[(0,0,1536,1536),(1152,0,2688,1536)]
    partial=payload([[1500,1200,1536,1300]],[.95])
    full=payload([[348,1200,448,1300]],[.8])
    merged=merge_tiles([partial,full],windows,(3000,4000),.5,False,300)
    assert merged['bboxes'].tolist()==[[1500.,1200.,1600.,1300.]]
    lone=merge_tiles([partial,payload([],[])],windows,(3000,4000),.5,False,300)
    assert len(lone['bboxes'])==1
    report={'version':ultralytics.__version__,'torch':torch.__version__,
            'seam_checks':{'covered_fragment_dropped':True,'uncovered_fragment_retained':True},
            'tile1024_count_for_4096x3072':len(tile_windows((3072,4096),1024)),
            'script_sha256':base.sha(__file__),'checkpoint_compatibility':{}}
    native=JOB/'expanded-v1/native-inputs';entry=json.loads((native/'manifest.json').read_text())['frames'][0]
    image=native/entry['path'];assert base.sha(image)==entry['sha256']
    reconstructed=base.sign_model('d4',JOB/'weights/yolo26n.pt',JOB/'weights/d4.pt')
    base.save_yolo(out/'d4-runtime.pt',reconstructed,0);del reconstructed
    for name,path in [('d4',out/'d4-runtime.pt'),('d5',JOB/'runs/d4/selected.pt'),('d6',JOB/'followup-v1/control-150/selected.pt')]:
        model=YOLO(path)
        result=model.predict(str(image),imgsz=1024,conf=.25,iou=.45,max_det=300,
                             quantize=32,tile=False,channels_last=False,device='0',verbose=False)[0]
        report['checkpoint_compatibility'][name]={'classes':model.names,'detections':len(result.boxes),
            'checkpoint_sha256':base.sha(path),'input_sha256':entry['sha256']}
        del model
    torch.cuda.empty_cache()
    uid='02e2f08c-f5d0-4e96-8f52-441275cf3fdf'
    previous=json.loads((JOB/'expanded-v1/pseudo-labels'/(uid+'.json')).read_text())
    source=JOB/'expanded-v1/source-images'/(previous['image_sha256']+'.jpg')
    assert base.sha(source)==previous['image_sha256']
    teacher=YOLO(JOB/'weights/yolo11l_panoramax.pt');outputs={}
    for mode,size,tile in [('whole2048',2048,False),('builtin_tile1536',1536,True)]:
        started=time.monotonic()
        result=teacher.predict(str(source),imgsz=size,tile=tile,batch=1,conf=.1,iou=.45,max_det=300,
                               classes=[0],quantize=16,channels_last=False,device='0',verbose=False)[0]
        outputs[mode]={'seconds_including_shared_gpu_contention':time.monotonic()-started,
            'boxes':[{'box':b,'score':s} for b,s in zip(result.boxes.xyxy.cpu().tolist(),result.boxes.conf.cpu().tolist())]}
        with Image.open(source) as original:
            crop=original.crop((1400,1190,1720,1490)).convert('RGB');draw=ImageDraw.Draw(crop)
            for row in outputs[mode]['boxes']:
                x1,y1,x2,y2=row['box']
                if x2>=1400 and x1<=1720 and y2>=1190 and y1<=1490:
                    draw.rectangle((x1-1400,y1-1190,x2-1400,y2-1190),outline='lime',width=2)
            crop.save(out/(mode+'-seam-case.png'))
    report['seam_case']={'picture_id':uid,'image_sha256':previous['image_sha256'],'results':outputs}
    base.write(out/'report.json',report);print(json.dumps(report))


if __name__=='__main__':main()
