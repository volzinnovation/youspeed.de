#!/usr/bin/env python3
"""Diagnostic CUDA comparison on identical ontology-compatible historical rows."""
from __future__ import annotations
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys
import time
import de_expanded_classifier as pipeline

PREPARATIONS = {'v1':'8cdc65590173d8788eeba47674f44e304429e9d6c8aaaf5666f04b6753f05913',
                'v2':'eb44b161c93267d8f38a97b96859f4b6438b3e720a8409dcadaa8a8d185ae4ca'}
MODEL_HASHES = {'primary136':'2918071223bc115ae1341cd2ce363dad04b3ba3d377112e79340ed1a12964005',
                'v1':'90ae2e7f61f6ef83ddb799f65dc8c2f50850de4714262fd40297805c4c60a241',
                'v2':'34fc00c4b227325168319740431d2ecc819e61932aec898ad46395834889a95a'}
PIPELINE_HASH='2c9326287ebf5ac8790bbca66398e0bf0cfcdd63345ea305eb681570ccc2e282'


def signatures(rows):
    return [{k:r.get(k) for k in ['sample_id','group_id','sha256','class_index','label',
                                 'training_crop_box','label_origin','resolved_path']} for r in rows]


def compatible(doc, split):
    if split not in {'dev','report'}:raise ValueError('Only historical dev/report are allowed')
    rows=pipeline.historical_selection_rows([r for r in doc['samples'] if r['split']==split],
                                           set(doc.get('ontology_conflict_ids',[])))
    if not rows or any(r['class_index']>=136 or r.get('is_new_intake') or r.get('training_only') for r in rows):
        raise ValueError('Incompatible evaluation scope')
    return rows


def delta(base, candidate):
    result={k:candidate[k]-base[k] for k in ['accuracy','macro_f1_supported','old_class_macro_f1_supported']}
    changes=[]
    for a,b in zip(base['per_class'],candidate['per_class']):
        if a['label']!=b['label'] or a['support']!=b['support']:raise ValueError('Metric scope differs')
        if a['support']:
            changes.append({'class_id':a['label'],'support':a['support'],'baseline_f1':a['f1'],
                            'candidate_f1':b['f1'],'delta_f1':b['f1']-a['f1'],
                            'baseline_correct':a['tp'],'candidate_correct':b['tp']})
    result['supported_class_regressions']=sorted([r for r in changes if r['delta_f1']<0],key=lambda r:r['delta_f1'])
    result['supported_class_improvements']=sorted([r for r in changes if r['delta_f1']>0],key=lambda r:-r['delta_f1'])
    return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['experiment','course-code','primary','historical','output']:
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--batch-size',type=int,default=64);p.add_argument('--workers',type=int,default=4)
    a=p.parse_args();started=time.monotonic()
    if a.output.exists():raise ValueError('Use a fresh immutable diagnostic output directory')
    if pipeline.sha(Path(pipeline.__file__))!=PIPELINE_HASH:raise ValueError('Frozen training helper differs')
    if pipeline.sha(a.course_code/'model_utils.py')!=pipeline.HELPER_SHA:raise ValueError('Pinned course helper differs')
    docs={}
    for version,expected in PREPARATIONS.items():
        path=a.experiment/f'results/preparation-{version}/manifest.json'
        if pipeline.sha(path)!=expected:raise ValueError('Frozen preparation differs')
        docs[version]=pipeline.read(path)
    classes=docs['v2']['classes'];pipeline.validate_classes(docs['v2']['base_classes'],classes)
    if docs['v1']['classes']!=classes:raise ValueError('Class orders differ')
    scopes={split:compatible(docs['v2'],split) for split in ['dev','report']}
    for split,rows in scopes.items():
        if signatures(rows)!=signatures(compatible(docs['v1'],split)):
            raise ValueError('v1/v2 compatible historical scopes differ')
        if len(rows)!={'dev':1548,'report':1522}[split]:raise ValueError('Unexpected diagnostic support')
    historical=pipeline.read(a.historical)['samples'];reserved=[r for r in historical if r['split']=='test']
    fresh=[];fresh_receipts=[]
    for name in ['protected-main120.json','protected-open73.json','protected-main120-pixels.json','protected-open71-pixels.json']:
        path=a.experiment/'inputs/training-metadata'/name
        fresh.extend(pipeline.read(path)['samples']);fresh_receipts.append({'path':str(path),'sha256':pipeline.sha(path)})
    for rows in scopes.values():
        kept,audit=pipeline.exclude_groups(rows,reserved+fresh)
        if len(kept)!=len(rows):raise ValueError('Evaluation selection intersects reserved test/fresh data')
        for row in rows:
            if '/test/' in row['resolved_path'] or pipeline.sha(row['resolved_path'])!=row['sha256']:
                raise ValueError('Forbidden or changed historical input')
    model_paths={'primary136':a.primary,**{v:a.experiment/f'results/training-{v}/expanded-native.pt' for v in ['v1','v2']}}
    for key,path in model_paths.items():
        if pipeline.sha(path)!=MODEL_HASHES[key]:raise ValueError('Frozen checkpoint differs')
    sys.path.insert(0,str(a.course_code));import model_utils as mu
    torch,ultralytics,np,Image,ImageOps=mu.dependencies()
    if not torch.cuda.is_available():raise RuntimeError('CUDA required; no CPU inference fallback')
    torch.set_num_threads(4);torch.set_num_interop_threads(1)
    torch.backends.cudnn.benchmark=False;torch.backends.cuda.matmul.allow_tf32=False;torch.backends.cudnn.allow_tf32=False
    torch.manual_seed(20261109);torch.cuda.manual_seed_all(20261109);np.random.seed(20261109)
    a.output.mkdir(parents=True);shutil.copyfile(__file__,a.output/'executed-comparison.py')
    scope_doc={split:signatures(rows) for split,rows in scopes.items()}
    pipeline.write(a.output/'scope-frozen.json',scope_doc)
    class Crops(torch.utils.data.Dataset):
        def __init__(self,rows):self.rows=rows
        def __len__(self):return len(self.rows)
        def __getitem__(self,i):
            row=self.rows[i]
            with Image.open(row['resolved_path']) as raw:
                im=pipeline.training_image_rgb(raw,row.get('label_origin')=='official_pictogram')
                if row.get('training_crop_box'):im=im.crop(row['training_crop_box'])
                im=im.resize((224,224),Image.Resampling.BILINEAR)
                value=np.asarray(im,dtype=np.float32).copy()/255
            digest=hashlib.sha256(value.astype('<f4').tobytes()).hexdigest()
            return torch.from_numpy(value).permute(2,0,1),row['class_index'],digest
    loaders={split:torch.utils.data.DataLoader(Crops(rows),batch_size=a.batch_size,shuffle=False,
                 num_workers=a.workers,pin_memory=True,generator=torch.Generator().manual_seed(20261109))
             for split,rows in scopes.items()}
    all_metrics={};all_predictions={};tensor_hashes={};reproduction={}
    for key,path in model_paths.items():
        model=ultralytics.YOLO(str(path),task='classify').model.float().eval().to('cuda:0')
        expected=classes[:136] if key=='primary136' else classes
        if [model.names[i] for i in range(len(model.names))]!=expected:raise ValueError('Model class order differs')
        all_metrics[key]={};all_predictions[key]={}
        for split,loader in loaders.items():
            truth=[];predictions=[];digests=[]
            with torch.inference_mode():
                for images,targets,hashes in loader:
                    images=images.to('cuda:0')
                    if not images.is_cuda or not next(model.parameters()).is_cuda:raise RuntimeError('GPU inference required')
                    with torch.autocast('cuda',dtype=torch.float16):scores=mu.logits_from_output(model(images))
                    truth.extend(targets.tolist());predictions.extend(scores.argmax(1).cpu().tolist());digests.extend(hashes)
            if truth!=[r['class_index'] for r in scopes[split]]:raise ValueError('Evaluation order differs')
            if split in tensor_hashes and tensor_hashes[split]!=digests:raise ValueError('Models received different tensors')
            tensor_hashes[split]=digests
            metrics=pipeline.normalize_expanded_metrics(mu.metrics_from_predictions(truth,predictions,classes))
            all_metrics[key][split]=metrics;all_predictions[key][split]=predictions
            if key!='primary136':
                filename='dev-metrics.json' if split=='dev' else 'ontology-compatible-report-metrics.json'
                existing_path=a.experiment/f'results/training-{key}'/filename;existing=pipeline.read(existing_path)
                reproduction[f'{key}_{split}']={'metric_file_sha256':pipeline.sha(existing_path),
                    'confusion_identical':metrics['confusion']==existing['confusion'],
                    'macro_f1_delta':metrics['macro_f1_supported']-existing['macro_f1_supported']}
            print(json.dumps({'model':key,'split':split,'samples':len(truth),'accuracy':metrics['accuracy'],
                              'macro_f1_supported':metrics['macro_f1_supported']}),flush=True)
        del model;torch.cuda.empty_cache()
    summary={'models':{key:{split:{k:m[k] for k in ['samples','accuracy','macro_f1_supported','old_class_macro_f1_supported',
                 'city_macro_f1_supported','new_class_macro_f1_supported','supported_classes']} for split,m in values.items()}
                 for key,values in all_metrics.items()},
             'deltas_vs_primary136':{key:{split:delta(all_metrics['primary136'][split],all_metrics[key][split])
                                         for split in scopes} for key in ['v1','v2']},
             'v2_minus_v1':{split:delta(all_metrics['v1'][split],all_metrics['v2'][split]) for split in scopes},
             'existing_metric_reproduction':reproduction,'historical_reused_diagnostic':True,
             'final_field_f1':False,'new_class_generalization_measured':False,'model_selection_action':'none'}
    pipeline.write(a.output/'metrics.json',all_metrics);pipeline.write(a.output/'predictions.json',all_predictions)
    pipeline.write(a.output/'tensor-hashes.json',tensor_hashes);pipeline.write(a.output/'summary.json',summary)
    provenance={'created_at':datetime.now(timezone.utc).isoformat(),'scope':'Previously reused historical ontology-compatible dev/report; diagnostic only',
      'preparations':PREPARATIONS,'models':MODEL_HASHES,'script_sha256':pipeline.sha(__file__),
      'pipeline_sha256':PIPELINE_HASH,'course_helper_sha256':pipeline.HELPER_SHA,'historical_manifest_sha256':pipeline.sha(a.historical),
      'fresh_exclusion_receipts':fresh_receipts,'scope_sha256':pipeline.sha(a.output/'scope-frozen.json'),
      'tensor_hashes_sha256':pipeline.sha(a.output/'tensor-hashes.json'),'metrics_sha256':pipeline.sha(a.output/'metrics.json'),
      'predictions_sha256':pipeline.sha(a.output/'predictions.json'),'summary_sha256':pipeline.sha(a.output/'summary.json'),
      'execution':'CUDA FP16 autocast, FP32 stored weights, batch64; identical training evaluation settings, TF32 disabled',
      'gpu':torch.cuda.get_device_name(0),'torch':str(torch.__version__),'ultralytics':ultralytics.__version__,
      'preprocessing':'EXIF transpose, RGB, training_crop_box when present, Pillow bilinear224x224, float32 RGB/255',
      'batch_size':a.batch_size,'workers':a.workers,'inference_pixels_by_split':{k:len(v) for k,v in scopes.items()},
      'test_pixels_opened':False,'fresh_pixels_opened':False,'prepared_training_pixels_opened':False,
      'original_historical_train_rows_now_in_diagnostic_scope':sum(
          r['sample_id'] in {h['sample_id'] for h in historical if h['split']=='train'}
          for rows in scopes.values() for r in rows),
      'truth_scope':'Historical labels only; unapproved fresh reviews not scored','model_selection_action':'none',
      'new_class_generalization_measured':False,'unsupported_class_f1_and_recall':'null','seconds':time.monotonic()-started}
    pipeline.write(a.output/'provenance.json',provenance)
    pipeline.write(a.output/'complete.json',{'status':'complete','summary_sha256':pipeline.sha(a.output/'summary.json'),
      'provenance_sha256':pipeline.sha(a.output/'provenance.json'),'all_existing_metrics_reproduced':all(v['confusion_identical'] for v in reproduction.values()),
      'fresh_field_f1_computed':False,'model_selection_action':'none'})


if __name__=='__main__':main()
