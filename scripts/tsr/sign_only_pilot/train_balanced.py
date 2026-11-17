#!/usr/bin/env python3
"""Paired balanced-view training with exact Swift development inputs, GPU0 only."""
import argparse
from copy import deepcopy
import csv
import json
import math
from pathlib import Path
import time
import random
import train_latest as base
import mobile_replay as phone

ROOT=Path('/job/balanced-v1')
NATIVE_SHA='3e924732f8f4bcbd676a7f46a0c2feed39d8c507994eb1103261b65c2d4a214a'
PANORAMAX_SHA='a3205e4a92b3acdaa883c02e09dba439c48f6c5bc8c89aff44da7c2e79f140e7'


def panoramax_sign_model():
    import torch
    from torch import nn
    from ultralytics import YOLO
    path=Path('/job/weights/yolo11l_panoramax.pt');assert base.sha(path)==PANORAMAX_SHA
    original=YOLO(str(path)).model.float().eval();assert original.names[0] in ['sign','traffic_sign']
    model=deepcopy(original);head=model.model[-1]
    for branch in head.cv3:
        previous=branch[-1];replacement=nn.Conv2d(previous.in_channels,1,1)
        with torch.no_grad():replacement.weight.copy_(previous.weight[:1]);replacement.bias.copy_(previous.bias[:1])
        branch[-1]=replacement
    head.nc=1;head.no=4*head.reg_max+1;model.names={0:'sign'};model.yaml['nc']=1
    pixels=torch.rand((1,3,256,256),generator=torch.Generator().manual_seed(14))
    with torch.inference_mode():expected=original(pixels)[0];actual=model(pixels)[0]
    torch.testing.assert_close(actual,expected[:,:5],rtol=1e-5,atol=1e-5)
    return model


class PhoneDevelopment:
    def __init__(self):
        from PIL import Image
        root=Path('/job/dataset-reviewed-v1');manifest=root/'manifest.json'
        assert base.sha(manifest)=='8d4f939e502b97b98750136d96fa9cc2f89017b236b69f1f57be2b55b9d73e1a'
        self.frames=base.partition_manifest(json.loads(manifest.read_text()))['validation']
        native_root=Path('/job/expanded-v1/native-inputs');assert base.sha(native_root/'manifest.json')==NATIVE_SHA
        native=json.loads((native_root/'manifest.json').read_text());lookup={(r['image_id'],r['mode'],r['pass_index']):r for r in native['frames']}
        self.inputs=[];self.specs=[];self.truth={}
        for f in self.frames:
            label=root/f['label_path'];assert base.sha(label)==f['label_sha256'];self.truth[f['image_id']]=base.read_yolo_labels(label,f['width'],f['height'])
            for i,window in enumerate(phone.windows(f['width'],f['height'])):
                r=lookup[(f['image_id'],'phone_windows',i)];assert r['source_sha256']==f['image_sha256'] and r['window_xyxy']==list(window)
                path=native_root/r['path'];assert base.sha(path)==r['sha256']
                with Image.open(path) as im:self.inputs.append(im.convert('RGB'))
                self.specs.append((f['image_id'],window))

    def measure(self,model,template):
        from ultralytics import YOLO
        import torch
        runtime=YOLO(str(template));runtime.model=deepcopy(model).float().eval();runtime.predictor=None
        results=[]
        for offset in range(0,len(self.inputs),2):
            results.extend(runtime.predict(self.inputs[offset:offset+2],imgsz=1024,batch=2,conf=.25,iou=.45,max_det=300,rect=False,device='0',quantize=32,tile=False,channels_last=False,verbose=False))
        passes={f['image_id']:[] for f in self.frames}
        for result,(identity,window) in zip(results,self.specs):
            rows=[]
            for box,score,cls in zip(result.boxes.xyxy.cpu().tolist(),result.boxes.conf.cpu().tolist(),result.boxes.cls.cpu().tolist()):
                mapped=phone.source_box(box,window)
                if cls==0 and mapped:rows.append({'box':mapped,'score':score})
            passes[identity].append(rows)
        records=[{'image_id':f['image_id'],'group_id':f['group_id'],'truth':self.truth[f['image_id']],'passes':passes[f['image_id']],'acceptable_extra_candidates':f.get('acceptable_extra_candidates',[])} for f in self.frames]
        sweep=[]
        for threshold in [t/100 for t in range(25,100)]:
            rows=[{**r,'predictions':phone.admit(r['passes'],threshold)[0]} for r in records];score=base.score_frames(rows,threshold);score.pop('frames');score['proposals_per_image']=(score['tp']+score['fp'])/len(rows);sweep.append(score)
        selected=max((s for s in sweep if s['proposals_per_image']<=4),key=lambda r:(r['recall'],r['precision'],r['threshold']))
        fixed=base.score_frames([{**r,'predictions':phone.admit(r['passes'],phone.PHONE_THRESHOLD)[0]} for r in records],phone.PHONE_THRESHOLD);fixed.pop('frames')
        del runtime,results;torch.cuda.empty_cache()
        return {'calibrated':selected,'fixed':fixed,'sweep':sweep,'records':records}


def key(measured):
    s=measured['calibrated'];return s['recall'],s['precision'],s['threshold']


def main():
    p=argparse.ArgumentParser();p.add_argument('--arm',choices=['phone','mixed','panoramax'],required=True);p.add_argument('--smoke',action='store_true');p.add_argument('--definition-sha256');p.add_argument('--publication-revision');args=p.parse_args()
    import torch
    from torch.utils.data import DataLoader,Sampler
    from ultralytics.models.yolo.detect import DetectionTrainer
    base.ml_dependencies();torch.set_num_threads(4);torch.manual_seed(14);random.seed(14)
    data=ROOT/'data';summary=json.loads((data/'summary.json').read_text())
    for file in ['views.json','schedules.json','corrected-sources.json','data.yaml']:assert base.sha(data/file)==summary[file+'_sha256']
    definition=ROOT/('panoramax-definition.json' if args.arm=='panoramax' else 'definition.json')
    if not args.smoke:
        assert args.definition_sha256 and base.sha(definition)==args.definition_sha256
        assert args.publication_revision and len(args.publication_revision)==40
    output=ROOT/('smoke-'+args.arm if args.smoke else 'runs/'+args.arm);output.mkdir(parents=True,exist_ok=False)
    schedules=json.loads((data/'schedules.json').read_text());views=json.loads((data/'views.json').read_text());view_lookup={v['view_id']:v for v in views}
    epochs=1 if args.smoke else 20 if args.arm=='panoramax' else 40;draws=32 if args.smoke else 1024;batch=4 if args.arm=='panoramax' else 16
    model=panoramax_sign_model() if args.arm=='panoramax' else base.sign_model('d4','/job/weights/yolo26n.pt','/job/weights/d4.pt')
    base.save_yolo(output/'initial.pt',model,0);base.save_yolo(output/'selected.pt',model,0)
    development=PhoneDevelopment();measured=development.measure(model,output/'initial.pt');history=[];best={'epoch':0,'selection_key':list(key(measured)),'threshold':measured['calibrated']['threshold']}
    base.write(output/'epoch-000-phone.json',measured)
    config={'arm':args.arm,'initialization':'Panoramax YOLO11l pretrained sign channel' if args.arm=='panoramax' else 'd4 YOLO26n','initial_sha256':base.sha(output/'initial.pt'),'epochs':epochs,'draws_per_epoch':draws,'epoch_semantics':'Balanced draws; not full-source passes','batch':batch,'nbs':16,'seed':14,'lr0':.0001 if args.arm=='panoramax' else .0002,'ultralytics':base.ULTRALYTICS_VERSION,'torch':str(torch.__version__),'gpu':torch.cuda.get_device_name(0),'definition_sha256':args.definition_sha256,'definition_publication_revision':args.publication_revision,'native_input_manifest_sha256':NATIVE_SHA,'selection':'Maximum development recall with mean proposals/image <=4, then precision, higher threshold, earlier epoch; thresholds .25:.01:.99; epoch zero eligible','precision':'AMP training; FP32 validation and Swift-Mac input replay, not CoreML numerical parity','data_summary':summary,'script_sha256':base.sha(__file__),'smoke':args.smoke,'consumed_holdout_usage':False}
    base.write(output/'configuration.json',config)
    history.append({'epoch':0,'phone':measured['calibrated'],'phone_fixed':measured['fixed'],'duration_seconds':0,'optimizer_step_calls_total':0,'optimizer_actual_updates_total':0})
    base.write(output/'history.json',history)

    class PairedSampler(Sampler):
        def __init__(self,dataset):
            self.epoch=0;self.mapping={Path(path).stem:i for i,path in enumerate(dataset.im_files)}
            assert set(view_lookup)==set(self.mapping)
        def __len__(self):return draws
        def __iter__(self):
            arm='mixed' if args.arm=='panoramax' else args.arm
            return iter([self.mapping[r[arm]] for r in schedules[self.epoch][:draws]])

    class Trainer(DetectionTrainer):
        def optimizer_step(self):
            before=self.scaler.get_scale();super().optimizer_step();after=self.scaler.get_scale()
            self.step_calls=getattr(self,'step_calls',0)+1;self.actual_updates=getattr(self,'actual_updates',0)+int(after>=before)
        def build_dataset(self,img_path,mode='train',batch=None):
            from ultralytics.data import build_yolo_dataset
            from ultralytics.utils.torch_utils import unwrap_model
            cfg=deepcopy(self.args);cfg.tile=False
            return build_yolo_dataset(cfg,img_path,batch,self.data,mode=mode,rect=False,stride=max(int(unwrap_model(self.model).stride.max()),32))
        def get_dataloader(self,dataset_path,batch_size=16,rank=0,mode='train'):
            if mode!='train':return super().get_dataloader(dataset_path,batch_size,rank,mode)
            dataset=self.build_dataset(dataset_path,mode,batch_size)
            return DataLoader(dataset,batch_size=batch_size,sampler=PairedSampler(dataset),num_workers=4,pin_memory=True,collate_fn=dataset.collate_fn,persistent_workers=False)
        def get_validator(self):
            validator=super().get_validator();validator.args.tile=False;validator.args.channels_last=False;return validator
        def validate(self):
            amp=self.amp;self.amp=False
            try:metrics=self.validator(self)
            finally:self.amp=amp
            metrics.pop('fitness',None);fitness=float(metrics[base.AP_KEY])
            if self.best_fitness is None or fitness>self.best_fitness:self.best_fitness=fitness
            return metrics,fitness
        def final_eval(self):
            # Standard final_eval mutates precision and produces duplicate epoch callbacks.
            # The selected EMA checkpoint has already had the frozen FP32 replay each epoch.
            pass

    trainer=Trainer(overrides={'model':str(output/'initial.pt'),'data':str(data/'data.yaml'),'epochs':epochs,'imgsz':1024,'batch':batch,'nbs':16,'device':'0','workers':4,'seed':14,'deterministic':True,'optimizer':'AdamW','lr0':config['lr0'],'lrf':.1,'weight_decay':.0005,'warmup_epochs':2.,'warmup_bias_lr':config['lr0'],'warmup_momentum':.8,'patience':0,'freeze':None,'amp':True,'rect':False,'tile':False,'cache':False,'channels_last':False,'mosaic':0.,'close_mosaic':0,'mixup':0.,'fliplr':0.,'flipud':0.,'degrees':0.,'translate':0.,'scale':0.,'hsv_h':.01,'hsv_s':.3,'hsv_v':.3,'iou':.45,'max_det':300,'plots':False,'save':True,'save_period':-1,'project':str(output),'name':'fit','exist_ok':False,'val':True,'pretrained':False})
    trainer.model=model;clock={}
    def start(current):
        current.train_loader.sampler.epoch=current.epoch;clock['start']=time.monotonic()
    def record(current):
        epoch=current.epoch+1
        if any(r['epoch']==epoch for r in history):return
        assert current.batch_size==batch
        measured=development.measure(current.ema.ema,output/'initial.pt');values=current.metrics
        row={'epoch':epoch,'phone':measured['calibrated'],'phone_fixed':measured['fixed'],'ap50':float(values['metrics/mAP50(B)']),'ap50_95':float(values[base.AP_KEY]),'train_loss':{k:float(v) for k,v in current.tloss.items()},'validation_loss':{k:float(v) for k,v in values.items() if k.startswith('val/')},'learning_rates':{k:float(v) for k,v in current.lr.items()},'duration_seconds':time.monotonic()-clock['start'],'optimizer_step_calls_total':current.step_calls,'optimizer_actual_updates_total':current.actual_updates,'draws':len(current.train_loader.sampler),'batches':len(current.train_loader),'positive_draws':sum(r['category']!='negative' for r in schedules[epoch-1][:draws])}
        assert all(math.isfinite(v) for v in row['train_loss'].values())
        if key(measured)>tuple(best['selection_key']):
            best.update(epoch=epoch,selection_key=list(key(measured)),threshold=measured['calibrated']['threshold']);base.save_yolo(output/'selected.pt',current.ema.ema,epoch)
        history.append(row);base.write(output/f'epoch-{epoch:03d}-phone.json',measured);base.write(output/'history.json',history);base.write(output/'selection.json',best)
        with (output/'epochs.jsonl').open('a') as stream:stream.write(json.dumps(row,allow_nan=False)+'\n')
        print(json.dumps({'stage':'epoch_complete',**row,'selected_epoch':best['epoch']}),flush=True)
    trainer.add_callback('on_train_epoch_start',start);trainer.add_callback('on_fit_epoch_end',record);trainer.train()
    base.write(output/'selection.json',best);config.update(completed_epochs=len(history)-1,amp_enabled=bool(trainer.amp));base.write(output/'configuration.json',config)
    assert len(history)==epochs+1
    base.write(output/'seal.json',{'complete':True,'selected_epoch':best['epoch'],'threshold':best['threshold'],'checkpoint_sha256':base.sha(output/'selected.pt'),'configuration_sha256':base.sha(output/'configuration.json'),'history_sha256':base.sha(output/'history.json'),'completed_epochs':epochs,'holdout_evaluated':False})

if __name__=='__main__':main()
