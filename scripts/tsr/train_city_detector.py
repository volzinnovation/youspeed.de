#!/usr/bin/env python3
"""CUDA-only, positive-only city-sign adaptation of the deployed SGBlur detector.

Only 195 sign-output scalars can change. Partial manual annotations never
become hard background labels; all other anchors retain soft baseline targets.
No runtime pack or production service is modified by this experiment.
"""
from __future__ import annotations
import argparse
import copy
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import random
import sys

ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT/'lectures/tsr-sgblur-de-2026-10-26/source/real-training-2026-10-20/sgblur/frozen_sign_adapt.py'
HELPER_SHA = '4d8d9b6480cddbdd3357776d133b5eafa972a3dcca668378abaf8ca0b5d0d0a1'
BASELINE_SHA = '698a70566938d25c3c1eaa49b89fc176fe2f3a20631a9a01fa56035613c7972a'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False)+'\n')


def load_helper(path):
    if sha(path) != HELPER_SHA:
        raise ValueError('Partial-label loss helper differs from its independently reviewed source')
    spec=importlib.util.spec_from_file_location('city_partial_loss',path)
    result=importlib.util.module_from_spec(spec); spec.loader.exec_module(result)
    return result


def partition_frames(manifest):
    if manifest.get('schema') != 'youspeed-city-detector-frames-v1':
        raise ValueError('Expected frozen full-frame detector manifest')
    mode=manifest.get('training_mode',manifest.get('permitted_training_mode'))
    if mode != 'positive_only_frozen_sign_head':
        raise ValueError('Partial-label training mode must be explicitly enabled in the manifest')
    if (manifest.get('training_launch_ready') is not True or manifest.get('image_verification_complete') is not True
            or manifest.get('class_names')!=['sign','plate','face']
            or manifest.get('detector_checkpoint_sha256')!=BASELINE_SHA):
        raise ValueError('Verified images, all city split supports and pinned detector ontology are required')
    frames=manifest['frames']
    training=[f for f in frames if f['split']=='train']
    validation=[f for f in frames if f['split'] in ('dev','val','validation')]
    reserved=[f for f in frames if f['split'] not in ('train','dev','val','validation')]
    if not training or not validation:
        raise ValueError('Separate nonempty training and development groups are required')
    group=lambda f:f.get('route_group',f.get('group_id'))
    heldout=[f for f in reserved if f['split'] in ('test','reserved')
             or 'protected_holdout_component' in f.get('exclusion_reasons',[])]
    sets=[{group(f) for f in subset} for subset in (training,validation,heldout)]
    if None in set.union(*sets) or any(sets[i]&sets[j] for i in range(3) for j in range(i)):
        raise ValueError('Route components overlap or are missing')
    owners={}
    for partition,subset in enumerate((training,validation,heldout)):
        for frame in subset:
            tokens=[('image',frame.get('image_id')),('bytes',frame.get('image_sha256')),
                    ('rgb',frame.get('rgb_sha256')),('sequence',frame.get('sequence_id'))]
            tokens.extend(('sequence',value) for value in frame.get('sequence_ids',[]))
            for kind,value in tokens:
                if not value:continue
                key=(kind,value)
                if key in owners and owners[key]!=partition:
                    raise ValueError('Image, pixel or sequence identity overlaps across partitions')
                owners[key]=partition
    for frame in training+validation:
        if frame.get('exif_orientation')!=1:
            raise ValueError('Only verified upright registered rasters are supported')
        if not frame.get('boxes'):
            raise ValueError('A partial-label training frame must contain verified positive boxes')
        for box in frame['boxes']:
            if box.get('bbox_source')!='manual_geometry' or box.get('detector_class_id',0)!=0:
                raise ValueError('Only verified manual sign geometry can supervise this pilot')
    return training,validation,reserved


def select_key(report):
    # Chosen before any predictions; baseline epoch0 remains eligible.
    return (report['matched_at_confirmation_floor']/report['known_targets'],
            report['matched_known_targets']/report['known_targets'],
            report['mean_best_sign_iou'],-report['mean_sign_probability_drift'])


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',type=Path,required=True)
    p.add_argument('--manifest-sha256',required=True)
    p.add_argument('--images-root',type=Path,required=True)
    p.add_argument('--baseline',type=Path,required=True)
    p.add_argument('--helper',type=Path,default=HELPER)
    p.add_argument('--output',type=Path,required=True)
    p.add_argument('--epochs',type=int,default=20)
    p.add_argument('--seed',type=int,default=20261110)
    p.add_argument('--batch',type=int,default=2)
    p.add_argument('--lr',type=float,default=.001)
    p.add_argument('--device',default='cuda:0')
    args=p.parse_args()
    if args.epochs<1 or args.batch<1 or not 0<args.lr<=.01:
        p.error('Positive epochs/batch and learning rate in (0,.01] are required')
    if sha(args.manifest)!=args.manifest_sha256 or sha(args.baseline)!=BASELINE_SHA:
        raise ValueError('Frozen input/checkpoint digest mismatch')
    if args.output.exists(): raise ValueError('Use a fresh experiment output directory')
    training,validation,reserved=partition_frames(json.loads(args.manifest.read_text()))
    if not args.device.startswith('cuda:'): raise ValueError('This experiment requires an NVIDIA GPU')
    os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG',':4096:8')
    helper=load_helper(args.helper);helper.dependencies()
    torch,np=helper.torch,helper.np
    if not torch.cuda.is_available(): raise RuntimeError('CUDA unavailable; no CPU fallback')
    torch.set_num_threads(4)
    torch.set_num_interop_threads(2)
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    import evaluate_city_detector as evaluator
    from PIL import Image
    random.seed(args.seed);torch.manual_seed(args.seed)
    torch.backends.cudnn.benchmark=False;torch.backends.cudnn.deterministic=True
    torch.backends.cuda.matmul.allow_tf32=False;torch.backends.cudnn.allow_tf32=False
    torch.use_deterministic_algorithms(True,warn_only=True)
    args.output.mkdir(parents=True)
    config={'schema':'youspeed-city-detector-training-v1','manifest_sha256':args.manifest_sha256,
        'script_sha256':sha(__file__),'helper_sha256':HELPER_SHA,'evaluator_sha256':sha(evaluator.__file__),
        'baseline_sha256':BASELINE_SHA,'epochs':args.epochs,'seed':args.seed,'lr':args.lr,'batch':args.batch,
        'imgsz':1024,'geometry':'mobile_right','torch':str(torch.__version__),
        'device':args.device,'gpu':torch.cuda.get_device_name(torch.device(args.device)),
        'cpu_threads':4,'cpu_interop_threads':2,
        'matmul_tf32':False,'cudnn_tf32':False,'cublas_workspace_config':os.environ['CUBLAS_WORKSPACE_CONFIG'],
        'train_frames':len(training),'development_frames':len(validation),'reserved_frames_never_loaded':len(reserved),
        'train_groups':sorted({f['route_group'] for f in training}),
        'development_groups':sorted({f['route_group'] for f in validation}),
        'trainable_scalars':195,'frozen':'Backbone, box regression, plate/face outputs, BatchNorm; all non-sign rows',
        'loss':'Positive known anchors=1; all other sign anchors retain soft baseline scores, equal term weights; L2 sign delta .0001; no hard negatives inferred',
        'selection':'Development known-target recall at detector score .7, then .25, then best sign IoU, then least mean score drift; baseline epoch0 eligible',
        'human_field_f1':False,'full_image_precision_or_ap':False,'deployed':False}
    config=json.loads(json.dumps(config,allow_nan=False))
    write(args.output/'configuration.json',config)
    data_root=args.images_root.resolve()
    def prepare(frame):
        path=(data_root/frame['image_path']).resolve()
        if not path.is_relative_to(data_root) or sha(path)!=frame['image_sha256']:
            raise ValueError('Image path or SHA mismatch')
        with Image.open(path) as im:
            if im.size!=(frame['width'],frame['height']) or im.getexif().get(274,1)!=1:
                raise ValueError('Unverified source raster geometry')
            image,transform=evaluator.prepare_image(im,mode='mobile_right',size=1024)
        targets=evaluator.transform_boxes(frame['boxes'],transform)
        inside=[t for t in targets if t['window_status']=='inside']
        tensor=torch.from_numpy(np.ascontiguousarray(np.asarray(image).transpose(2,0,1))).float()/255
        return frame,tensor,inside,targets
    data=[prepare(f) for f in training];dev=[prepare(f) for f in validation]
    excluded=[{'image_id':f['image_id'],'reason':'no fully visible manual target in current mobile window'} for f,_,targets,_ in data if not targets]
    data=[row for row in data if row[2]]
    if not data or not sum(len(row[2]) for row in dev): raise ValueError('Current mobile window has no train/development target support')
    write(args.output/'window-training-exclusions.json',excluded)
    model=helper.load_model(args.baseline,args.device); teacher=copy.deepcopy(model).eval()
    for parameter in teacher.parameters(): parameter.requires_grad_(False)
    before={k:v.detach().cpu().clone() for k,v in model.state_dict().items()}
    parameters,allowed=helper.freeze_sign_only(model);initial=[p[0].detach().clone() for p in parameters]
    assignable=[]
    with torch.no_grad():
        for row in data:
            frame,tensor,targets,_=row
            try:
                helper.partial_loss(model,teacher,tensor.unsqueeze(0).to(args.device),[[t['bbox_xyxy'] for t in targets]])
            except AssertionError as error:
                if str(error)!='No assignable known positive anchors in batch':raise
                excluded.append({'image_id':frame['image_id'],'reason':'no assignable positive baseline anchors; no background supervision substituted'})
            else:
                assignable.append(row)
    data=assignable
    write(args.output/'window-training-exclusions.json',excluded)
    if not data:raise ValueError('No assignable positive training frames; frozen sign head cannot learn this set')
    write(args.output/'training-preflight.json',{'usable_training_frames':len(data),
        'positive_targets':sum(len(r[2]) for r in data),'excluded_frames':excluded,
        'rule':'Known positives must be fully inside the mobile window and have assignable baseline anchors; excluded pixels never receive hard background targets.'})
    optimizer=torch.optim.AdamW(parameters,lr=args.lr,weight_decay=0.)
    def evaluate():
        total=matched=confirmed=0;best_sum=drift_sum=0.;drift_n=0;rows=[]
        with torch.inference_mode():
            for frame,tensor,targets,all_targets in dev:
                image=tensor.unsqueeze(0).to(args.device)
                output,raw=helper.raw_forward(model,image);_,original=helper.raw_forward(teacher,image)
                assert torch.equal(raw['boxes'],original['boxes'])
                assert torch.equal(raw['scores'][:,1:],original['scores'][:,1:])
                delta=(raw['scores'][:,0].sigmoid()-original['scores'][:,0].sigmoid()).abs()
                drift_sum+=float(delta.sum());drift_n+=delta.numel()
                detections=evaluator.decode_sign_predictions(output[0].detach().cpu().numpy(),minimum_score=.25,nms_iou=.45,maximum_proposals=12)
                matches=evaluator.match_known_boxes(targets,detections)
                confirmation_matches=evaluator.match_known_boxes(targets,[d for d in detections if d['score']>=.7])
                total+=len(targets);matched+=len(matches)
                confirmed+=len(confirmation_matches)
                best_sum+=sum(max((helper.box_iou(t['bbox_xyxy'],d['bbox_xyxy']) for d in detections),default=0.) for t in targets)
                rows.append({'image_id':frame['image_id'],'known_targets':len(targets),'matched':len(matches),'matched_at_confirmation_floor':len(confirmation_matches),'sign_proposals':len(detections),'outside_or_clipped_targets':len(all_targets)-len(targets)})
        return {'known_targets':total,'matched_known_targets':matched,'matched_at_confirmation_floor':confirmed,'mean_best_sign_iou':best_sum/total,'mean_sign_probability_drift':drift_sum/drift_n,'rows':rows,'metric':'Partial-label known-target recall, not precision/AP/F1'}
    baseline=evaluate();write(args.output/'development-epoch-00.json',baseline)
    best_key=select_key(baseline);best_epoch=0;history=[]
    helper.save_checkpoint(args.output/'best.pt',model,0,config)
    initial_saved=torch.load(args.output/'best.pt',map_location='cpu',weights_only=True)
    assert initial_saved['format']==helper.FORMAT and initial_saved['baseline_sha256']==BASELINE_SHA
    del initial_saved
    for epoch in range(1,args.epochs+1):
        order=list(range(len(data)));random.shuffle(order);losses=[]
        for start in range(0,len(order),args.batch):
            batch=[data[i] for i in order[start:start+args.batch]]
            images=torch.stack([r[1] for r in batch]).to(args.device)
            boxes=[[t['bbox_xyxy'] for t in r[2]] for r in batch]
            optimizer.zero_grad(set_to_none=True)
            loss,detail=helper.partial_loss(model,teacher,images,boxes)
            loss=loss+.0001*sum((p[0]-old).square().mean() for p,old in zip(parameters,initial))
            assert torch.isfinite(loss);loss.backward();optimizer.step();losses.append(float(loss.detach()))
        proof=helper.frozen_proof(model,before,allowed)
        result=evaluate();write(args.output/f'development-epoch-{epoch:02d}.json',result)
        if select_key(result)>best_key:
            best_key=select_key(result);best_epoch=epoch;helper.save_checkpoint(args.output/'best.pt',model,epoch,config)
        history.append({'epoch':epoch,'loss':sum(losses)/len(losses),'matched':result['matched_known_targets'],'matched_at_confirmation_floor':result['matched_at_confirmation_floor'],'targets':result['known_targets'],'sign_probability_drift':result['mean_sign_probability_drift'],'selected_epoch':best_epoch})
        write(args.output/'history.json',history);print(json.dumps(history[-1]),flush=True)
    helper.save_checkpoint(args.output/'last.pt',model,args.epochs,config)
    selected=torch.load(args.output/'best.pt',map_location='cpu',weights_only=True)
    model.load_state_dict(selected['model_state'],strict=True)
    proof=helper.frozen_proof(model,before,allowed)
    proof.update(checkpoint_sha256=sha(args.output/'best.pt'),selected_epoch=best_epoch)
    write(args.output/'frozen-state-proof.json',proof)
    write(args.output/'complete.json',{'status':'complete','selected_epoch':best_epoch,'checkpoint_sha256':sha(args.output/'best.pt'),'baseline_development':baseline,'selection_key':best_key,'reserved_test_pixels_loaded_during_training':False,'deployed':False})

if __name__=='__main__':main()
