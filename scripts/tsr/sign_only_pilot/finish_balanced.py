#!/usr/bin/env python3
"""Compare selected d9 arms on development; create inspectable visual/epoch reports."""
from copy import deepcopy
import csv,json,html,shutil
from pathlib import Path
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from PIL import Image
from ultralytics import YOLO
import train_latest as base
import mobile_replay as phone
from train_balanced import PhoneDevelopment,ROOT


def main():
    out=ROOT/'comparison';out.mkdir(exist_ok=False);(out/'images').mkdir();development=PhoneDevelopment();results={};histories={}
    specs=[('d4',ROOT/'runs/phone/initial.pt',None),('d8',Path('/job/expanded-v1/latest-full/selected.pt'),None)]
    for arm in ['phone','mixed']:
        run=ROOT/'runs'/arm;seal=json.loads((run/'seal.json').read_text());assert seal['complete'] and seal['completed_epochs']==40 and base.sha(run/'selected.pt')==seal['checkpoint_sha256']
        history=json.loads((run/'history.json').read_text());assert len(history)==41 and history[-1]['optimizer_step_calls_total']==2560
        assert all(r['draws']==1024 and r['batches']==64 and r['positive_draws']==768 for r in history[1:])
        histories[arm]=history;specs.append(('d9-'+arm,run/'selected.pt',seal))
    assert histories['phone'][0]['phone_fixed']==histories['mixed'][0]['phone_fixed']
    links=[]
    for name,path,seal in specs:
        model=YOLO(str(path)).model.float().eval();measured=development.measure(model,path);base.write(out/(name+'-phone.json'),measured)
        selected_threshold=seal['threshold'] if seal else measured['calibrated']['threshold']
        selected_records=[{**r,'predictions':phone.admit(r['passes'],selected_threshold)[0]} for r in measured['records']]
        selected=base.score_frames(selected_records,selected_threshold);selected.pop('frames');selected['proposals_per_image']=(selected['tp']+selected['fp'])/17
        if seal:
            original=histories[name.removeprefix('d9-')][seal['selected_epoch']]['phone']
            assert [selected[k] for k in ['tp','fp','fn']]==[original[k] for k in ['tp','fp','fn']]
        results[name]={'checkpoint_sha256':base.sha(path),'selected_epoch':seal['selected_epoch'] if seal else None,'fixed':measured['fixed'],'calibrated':selected,'threshold_origin':'Frozen checkpoint selection on development' if seal else 'Current development calibration of fixed baseline checkpoint'}
        for i,(frame,record) in enumerate(zip(development.frames,selected_records)):
            assert frame['image_id']==record['image_id']
            source=Path('/job/dataset-reviewed-v1')/frame['image_path'];assert base.sha(source)==frame['image_sha256']
            with Image.open(source) as raster:image=raster.convert('RGB')
            stem=f'{name}-{i:02d}.jpg';findings=phone.visual(image,record['truth'],record['predictions'],out/'images'/stem)
            links.append(f'<section><h2>{html.escape(name)} · image {i+1} · threshold {selected_threshold:.2f}</h2><p>{html.escape(frame["picture_id"])} · missed {len(findings["missed_truth_indices"])} · unmatched {len(findings["false_positives"])}</p><img loading="lazy" src="images/{stem}" style="width:100%"></section>')
        del model
    summary={'split':'development','images':17,'reference_faces':33,'results':results,'native_input_manifest_sha256':'3e924732f8f4bcbd676a7f46a0c2feed39d8c507994eb1103261b65c2d4a214a','runtime':'Ultralytics8.4.213 PyTorchFP32 GPU0 with actual SwiftMac inputs','fresh_holdout':False,'claim':'Exploratory comparison on reused small development set; not CoreML parity, phone latency, statistical significance or deployment approval.'};base.write(out/'summary.json',summary)
    fig,axes=plt.subplots(2,2,figsize=(12,8),constrained_layout=True)
    for arm,history in histories.items():
        epochs=[r['epoch'] for r in history]
        axes[0,0].plot(epochs,[r['phone']['recall'] for r in history],label=arm)
        axes[0,1].plot(epochs,[r['phone']['fp_per_image'] for r in history],label=arm)
        axes[1,0].plot(epochs,[r['phone_fixed']['recall'] for r in history],label=arm)
        axes[1,1].plot(epochs[1:],[r['ap50_95'] for r in history[1:]],label=arm)
        rows=[];initial=history[0];previous=initial
        for r in history:
            rows.append({'epoch':r['epoch'],'phone_threshold':r['phone']['threshold'],'phone_tp':r['phone']['tp'],'phone_fp':r['phone']['fp'],'phone_fn':r['phone']['fn'],'phone_recall':r['phone']['recall'],'phone_precision':r['phone']['precision'],'recall_change_from_initial':r['phone']['recall']-initial['phone']['recall'],'recall_change_from_previous':r['phone']['recall']-previous['phone']['recall'],'fixed_tp':r['phone_fixed']['tp'],'fixed_fp':r['phone_fixed']['fp'],'fixed_fn':r['phone_fixed']['fn'],'whole_ap50_95':r.get('ap50_95'),'optimizer_calls':r['optimizer_step_calls_total'],'actual_optimizer_updates':r['optimizer_actual_updates_total'],'seconds':r['duration_seconds'],'train_losses_json':json.dumps(r.get('train_loss',{}))});previous=r
        with (out/(arm+'-epoch-improvements.csv')).open('w') as stream:w=csv.DictWriter(stream,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    for ax,title in zip(axes.flat,['Development recall at proposal budget','Unmatched proposals per image at budget','Recall at fixed phone threshold0.840783','Whole-image AP50–95 (secondary)']):ax.set_title(title);ax.set_xlabel('Balanced epoch (1024 draws)');ax.grid(alpha=.2);ax.legend()
    fig.suptitle('d9: same parents, positive balance and optimizer budget');fig.savefig(out/'learning-curves.png',dpi=150);plt.close(fig)
    text='# Balanced phone crops and small-sign tiles: d9\n\n'
    text+='Both arms completed40 epochs of1024 draws (40,960 draws and2,560 optimizer calls each), covering the same5,263 source parents. These are balanced sampling epochs, not40 full-data passes. Labels remain weak after13 reviewed sign-region corrections.\n\n'
    text+='| Model | Selected epoch | Fixed threshold TP / FP / FN | Development threshold | Calibrated TP / FP / FN | Recall | Precision |\n|---|---:|---|---:|---|---:|---:|\n'
    for name,r in results.items():
        a,b=r['fixed'],r['calibrated'];text+=f"| {name} | {r['selected_epoch']} | {a['tp']} / {a['fp']} / {a['fn']} | {b['threshold']:.2f} | {b['tp']} / {b['fp']} / {b['fn']} | {b['recall']:.3f} | {b['precision']:.3f} |\n"
    text+='\nSelection maximized development recall at mean proposals/image<=4, then precision,threshold and earlier epoch. Each candidate could retain epoch0. d4/d8 baseline checkpoints were freshly replayed and calibrated by the same rule. Traffic-light candidates remain included in raw unmatched counts; no face/plate classes are trained.\n\n'
    p,m=results['d9-phone']['calibrated'],results['d9-mixed']['calibrated'];text+=f"The mixed view recipe changes recovered development faces by{m['tp']-p['tp']:+d} and unmatched proposals by{m['fp']-p['fp']:+d} relative to the matched phone-only control. This compares view geometry within the corrected/balanced recipe; it cannot separate the benefit of correction or balancing from earlier d8 training.\n\n"
    text+='Only17 repeatedly used development images/33 reference faces support this result. The consumed geographic audit and original test were not rerun. No statistical or fresh geographic-generalization claim is made. Training used Pillow phone geometry; evaluation used actual SwiftMac PNG inputs and KI FP32. iPhone CoreML parity and phone latency remain unmeasured. No detector was deployed.\n\n![Epoch curves](learning-curves.png)\n\n[Phone epoch improvements](phone-epoch-improvements.csv) · [Mixed epoch improvements](mixed-epoch-improvements.csv) · [Exact comparison](summary.json)\n'
    (out/'README.md').write_text(text)
    (out/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>d9 development error comparison</title><body style="max-width:1400px;margin:auto;font:17px sans-serif"><h1>d9 development error comparison</h1><p>Green: matched reference. Yellow: missed reference. Red: unmatched proposal. Development-selected thresholds. Reused17-image development set; no fresh holdout claim; FP32 is not CoreML parity.</p><img src="learning-curves.png" style="width:100%">'+''.join(links)+'</body>')
    base.write(ROOT/'comparison-complete.json',{'complete':True,'summary_sha256':base.sha(out/'summary.json'),'published':False});print(json.dumps(summary),flush=True)

if __name__=='__main__':main()
