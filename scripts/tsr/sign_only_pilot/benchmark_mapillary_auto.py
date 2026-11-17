#!/usr/bin/env python3
"""Compare fixed models against incomplete Mapillary automatic references."""
import argparse,csv,json,math
from pathlib import Path
from copy import deepcopy
from PIL import Image
import train_latest as base
import mobile_replay as phone
from train_balanced import PhoneDevelopment
JOB=Path('/job');ROOT=JOB/'balanced-v1';SAMPLE=JOB/'mapillary-auto-v2'


def deduplicate(rows):
    kept=[]
    # Classified boxes take priority over generic segmentation boxes of the same face.
    for r in sorted(rows,key=lambda r:(r['scope']!='classified_primary_candidate',r['id'])):
        if all(base.iou(r['box'],k['box'])<.8 for k in kept):kept.append(r)
    return kept


def reference_boxes(frame,tier):
    scopes={'classified_primary_candidate'}
    if tier=='broad_front':scopes.add('generic_front_scope_unknown')
    return [r['box'] for r in deduplicate([r for r in frame['proposals'] if r['scope'] in scopes])]


def size_bin(box,frame):
    values=[]
    for x,y,r,b in phone.windows(frame['width'],frame['height']):
        if box[0]>=x and box[1]>=y and box[2]<=r and box[3]<=b:values.append(min(box[2]-box[0],box[3]-box[1])*1024/max(r-x,b-y))
    if not values:return 'clipped_in_all_phone_crops'
    value=max(values)
    for bound in [8,16,32,64]:
        if value<bound:return f'under_{bound}px'
    return '64px_plus'


def measure(frames,raw,threshold,tier):
    matched=missed=unmatched=positives=all_refs_found=0;bins={};per_frame=[]
    for f,r in zip(frames,raw):
        assert f['image_id']==r['image_id'];truth=reference_boxes(f,tier);predictions=phone.admit(r['passes'],threshold)[0];error=phone.errors(truth,predictions)
        n=len(error['matched_truth_indices']);miss=len(error['missed_truth_indices']);extra=len(error['false_positives']);matched+=n;missed+=miss;unmatched+=extra
        positives+=bool(truth);all_refs_found+=bool(truth) and miss==0
        for i,box in enumerate(truth):
            key=size_bin(box,f);bucket=bins.setdefault(key,{'references':0,'matched':0});bucket['references']+=1;bucket['matched']+=i in error['matched_truth_indices']
        per_frame.append({'image_id':f['image_id'],'group_id':f['group_id'],'anchor':f['anchor'],'references':len(truth),'matched':n,'missed':miss,'unmatched_predictions':extra})
    for v in bins.values():v['reference_coverage']=v['matched']/v['references']
    return {'threshold':threshold,'images':len(frames),'reference_boxes':matched+missed,'matched_references':matched,'missed_references':missed,'reference_coverage':matched/(matched+missed) if matched+missed else None,'unmatched_predictions':unmatched,'unmatched_per_image':unmatched/len(frames),'images_with_references':positives,'images_with_all_available_references_matched':all_refs_found,'all_available_reference_image_rate':all_refs_found/positives if positives else None,'images_without_references':len(frames)-positives,'size_bins':bins,'frames':per_frame,'interpretation':'Agreement with incomplete automatic references; unmatched predictions are not verified false positives. All available references found does not mean all visible signs found.'}


def main():
    import torch
    from ultralytics import YOLO
    p=argparse.ArgumentParser();p.add_argument('--sample-sha256',required=True);args=p.parse_args();torch.set_num_threads(4);base.ml_dependencies()
    assert base.sha(SAMPLE/'manifest.json')==args.sample_sha256
    manifest=json.loads((SAMPLE/'manifest.json').read_text());frames=manifest['frames'];assert frames and all(not f['annotation_complete'] and not f['training_allowed'] for f in frames)
    out=ROOT/'mapillary-benchmark';out.mkdir(exist_ok=False);development=PhoneDevelopment()
    specs=[('d4',ROOT/'runs/phone/initial.pt'),('d5',JOB/'runs/d4/selected.pt'),('d6',JOB/'followup-v1/control-150/selected.pt'),('d7-whole',JOB/'latest-ultralytics-v1/pilot-whole/selected.pt'),('d7-tile',JOB/'latest-ultralytics-v1/pilot-tile/selected.pt'),('d8',JOB/'expanded-v1/latest-full/selected.pt'),('d9-phone',ROOT/'runs/phone/selected.pt'),('d9-mixed',ROOT/'runs/mixed/selected.pt'),('d9-phone-last',ROOT/'runs/phone/fit/weights/last.pt'),('d9-mixed-last',ROOT/'runs/mixed/fit/weights/last.pt'),('Panoramax-original',JOB/'weights/yolo11l_panoramax.pt')]
    calibration=[]
    for name,path in specs:
        model=YOLO(str(path)).model.float().eval();dev=development.measure(model,path);base.write(out/(name+'-development-calibration.json'),dev)
        calibration.append({'name':name,'path':str(path),'sha256':base.sha(path),'threshold':dev['calibrated']['threshold'],'development':dev['calibrated'],'fixed_threshold':phone.PHONE_THRESHOLD});del model;torch.cuda.empty_cache()
    definition={'schema':'mapillary-automatic-benchmark-definition-v1','sample_manifest_sha256':args.sample_sha256,'native_manifest_sha256':base.sha(SAMPLE/'native-inputs/manifest.json'),'calibration':'Fixed17-image development set only; maximize recall with <=4 proposals/image, then precision,higher threshold. No Mapillary threshold/checkpoint tuning. d9 checkpoints frozen before this benchmark.','models':calibration,'fixed_threshold':phone.PHONE_THRESHOLD,'primary_reference_tier':'Automatic classified regulatory/warning/information candidates after frozen scope filtering. Deduplicate IoU>=.8.','secondary_reference_tier':'Classified candidates plus generic front masks, same deduplication. Generic masks can include excluded supplementary/direction signs: this is broader proposal agreement only.','geometry':'Actual SwiftMac phone crops,1024,FP32 KI,sign class0,per-pass cap12,NMS.45,confidence floor.25; not CoreML numerical/latency parity.','match_iou':.5,'zero_reference_images':'Retained; never certified negative','test_labels':'Automatic incomplete references; no complete-sign recall or true precision claim','pretraining_overlap':manifest['pretraining_overlap'],'script_sha256':base.sha(__file__)}
    base.write(out/'definition.json',definition) # frozen before any inference on sample pixels
    native=json.loads((SAMPLE/'native-inputs/manifest.json').read_text());lookup={(r['image_id'],r['mode'],r['pass_index']):r for r in native['frames']};images=[];mapping=[]
    for f in frames:
        assert base.sha(SAMPLE/f['image_path'])==f['image_sha256']
        for index,window in enumerate(phone.windows(f['width'],f['height'])):
            r=lookup[(f['image_id'],'phone_windows',index)];assert r['window_xyxy']==list(window) and r['source_sha256']==f['image_sha256'];path=SAMPLE/'native-inputs'/r['path'];assert base.sha(path)==r['sha256']
            with Image.open(path) as im:images.append(im.convert('RGB'))
            mapping.append((f['image_id'],window))
    results={}
    for spec in calibration:
        name=spec['name'];assert base.sha(spec['path'])==spec['sha256'];model=YOLO(spec['path']);passes={f['image_id']:[] for f in frames}
        for offset in range(0,len(images),2):
            predictions=model.predict(images[offset:offset+2],imgsz=1024,batch=2,conf=.25,iou=.45,max_det=300,rect=False,device='0',quantize=32,tile=False,channels_last=False,verbose=False)
            for prediction,(identity,window) in zip(predictions,mapping[offset:offset+2]):
                rows=[]
                for box,score,cls in zip(prediction.boxes.xyxy.cpu().tolist(),prediction.boxes.conf.cpu().tolist(),prediction.boxes.cls.cpu().tolist()):
                    mapped=phone.source_box(box,window)
                    if cls==0 and mapped:rows.append({'box':mapped,'score':score})
                passes[identity].append(rows)
        raw=[{'image_id':f['image_id'],'passes':passes[f['image_id']]} for f in frames];base.write(out/(name+'-sample-predictions.json'),raw)
        results[name]={mode:{tier:measure(frames,raw,t,tier) for tier in ['classified_primary','broad_front']} for mode,t in [('fixed',phone.PHONE_THRESHOLD),('development_calibrated',spec['threshold'])]}
        print(json.dumps({'model_complete':name,'fixed':{k:v for k,v in results[name]['fixed']['classified_primary'].items() if k not in ['frames','size_bins']},'calibrated':{k:v for k,v in results[name]['development_calibrated']['classified_primary'].items() if k not in ['frames','size_bins']}}),flush=True)
        del model,predictions;torch.cuda.empty_cache()
    summary={'schema':'mapillary-automatic-benchmark-results-v1','sample_images':len(frames),'sequence_groups':len({f['sequence_id'] for f in frames}),'location_blocks':len({f['anchor'] for f in frames}),'minimum_distance_to_finetuning_or_dev_m':min(f['nearest_finetuning_or_dev_m'] for f in frames),'sample_manifest_sha256':args.sample_sha256,'definition_sha256':base.sha(out/'definition.json'),'results':results,'claim':definition['test_labels']};base.write(out/'summary.json',summary)
    rows=[]
    for name,modes in results.items():
        for mode,tiers in modes.items():
            for tier,value in tiers.items():rows.append({'model':name,'operating_point':mode,'reference_tier':tier,**{k:v for k,v in value.items() if k not in ['frames','size_bins','interpretation']}})
    with (out/'comparison.csv').open('w') as stream:w=csv.DictWriter(stream,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    names=list(results);fig,axes=plt.subplots(1,2,figsize=(13,7),constrained_layout=True)
    for i,name in enumerate(names):
        a=results[name]['development_calibrated']['classified_primary'];b=results[name]['fixed']['classified_primary']
        axes[0].barh(i-.18,a['reference_coverage'] or 0,height=.34,color='#187c91',label='Dev-calibrated' if i==0 else None)
        axes[0].barh(i+.18,b['reference_coverage'] or 0,height=.34,color='#9bbac0',label='Fixed phone threshold' if i==0 else None)
        axes[1].barh(i,a['unmatched_per_image'],height=.6,color='#ad723b')
    for ax in axes:ax.set_yticks(range(len(names)),names);ax.invert_yaxis();ax.grid(axis='x',alpha=.2);ax.set_axisbelow(True)
    axes[0].set_xlim(0,1);axes[0].set_xlabel('Fraction of available classified references matched');axes[0].legend(loc='lower right')
    axes[1].set_xlabel('Unmatched predictions per image (not verified false positives)')
    fig.suptitle('Mapillary automatic-reference agreement · incomplete labels');fig.savefig(out/'comparison.png',dpi=150);plt.close(fig)
    text=f'# Mapillary automatic-reference benchmark\n\n{len(frames)} metadata-selected images from{summary["sequence_groups"]} distinct sequences and{summary["location_blocks"]} location blocks, at least{summary["minimum_distance_to_finetuning_or_dev_m"]:.0f}m from the current fine-tuning/development images. This is a bounded convenience sample, not a representative or exhaustively annotated holdout. Images were selected before querying their detections; images with no references remain in the sample. Upstream pretrained-model exposure is unknown.\n\n'
    text+='| Model | Dev threshold | Classified reference matched / total | Coverage | Unmatched predictions/image | Broad front matched / total | Fixed-threshold classified coverage |\n|---|---:|---|---:|---:|---|---:|\n'
    for spec in calibration:
        name=spec['name'];a=results[name]['development_calibrated']['classified_primary'];b=results[name]['development_calibrated']['broad_front'];fixed=results[name]['fixed']['classified_primary'];fmt=lambda v:'n/a' if v is None else f'{v:.1%}'
        text+=f"| {name} | {spec['threshold']:.2f} | {a['matched_references']} / {a['reference_boxes']} | {fmt(a['reference_coverage'])} | {a['unmatched_per_image']:.2f} | {b['matched_references']} / {b['reference_boxes']} | {fmt(fixed['reference_coverage'])} |\n"
    text+='\n**Interpretation:** these percentages measure agreement with Mapillary automatic boxes. They are not recall over all visible signs. Unmatched predictions can be real signs omitted or misclassified by Mapillary, so they are not counted as verified false positives. Generic-front masks may contain excluded supplementary/direction panels and are reported separately. Mapillary classes are used only for the automatic reference scope filter; all retained target classes are collapsed to sign.\n\n'
    text+='All models use the same actual SwiftMac phone crops at1024, KI FP32 inference, sign class0, per-pass cap12 and NMS0.45. Thresholds were calibrated exclusively on the existing17 development images before sample inference. The fixed phone threshold0.840783 is also reported. Panoramax-original retains its published checkpoint, with only its sign outputs scored. The d9 selected checkpoints may retain epoch0; the two d9-last rows separately diagnose the fixed final epoch40, without selecting on Mapillary. No model was trained on this sample. No iPhone latency or CoreML parity was measured.\n\n'
    text+='The initial API transport probe was a previously reviewed image and is excluded from this sample. That probe showed a duplicated generic/classified town-exit box and another town-exit labeled as a direction sign, illustrating why these references need later review.\n\n![Automatic-reference comparison](comparison.png)\n\n[Complete numeric comparison](comparison.csv) · [Metric details and size bins](summary.json) · [Frozen model/threshold definition](definition.json)\n\nNext: review all visible primary signs and unmatched predictions, resolve duplicate/incomplete annotations, then freeze a separate fully reviewed test set. Reusing these results to change models makes this sample development evidence.\n'
    (out/'README.md').write_text(text);base.write(out/'complete.json',{'complete':True,'models':len(specs),'summary_sha256':base.sha(out/'summary.json')})
if __name__=='__main__':main()
