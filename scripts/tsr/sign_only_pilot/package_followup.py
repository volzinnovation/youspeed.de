#!/usr/bin/env python3
"""Package completed follow-up audit/replay and the150-epoch control separately."""
import csv
import hashlib
import io
import json
from pathlib import Path
import shutil

ROOT=Path('/home/raphael/streetshots-d5-20261114')
FOLLOW=ROOT/'followup-v1'
DATA_PREFIX='reviews/detector-followup-2026-11-14'


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(root,kind,manifest,destination):
    rows=[]
    for p in sorted(root.rglob('*')):
        if not p.is_file():continue
        b=p.read_bytes()
        rows.append({'source_path':str(p),'path_in_repo':p.relative_to(root).as_posix(),
                     'size':len(b),'sha256':hashlib.sha256(b).hexdigest(),
                     'git_blob_sha1':hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()})
    destination.write_text(json.dumps({'schema':'streetshots-ki-publish-inventory-v1','repository':'loffenauer/streetshots',
        'repo_type':kind,'manifest_path_in_repo':manifest,'files':rows},indent=2)+'\n')
    return {'inventory':str(destination),'sha256':digest(destination),'files':len(rows),'bytes':sum(r['size'] for r in rows)}


def main():
    staging=FOLLOW/'publication-v1';staging.mkdir(exist_ok=False)
    data=staging/'dataset'/DATA_PREFIX;data.mkdir(parents=True)
    report=json.loads((FOLLOW/'audit-adjudication.json').read_text())
    assert report['all_saved_errors_inspected'] and len(report['entries'])==58
    replay=json.loads((FOLLOW/'replay/summary.json').read_text())
    assert replay['split']=='validation' and replay['images']==17
    for name in ['audit-student','audit-d4']:
        shutil.copytree(FOLLOW/name,data/name)
    for name in ['audit-adjudication.json','audit-contact-index.json']:
        shutil.copy2(FOLLOW/name,data/name)
    for p in FOLLOW.glob('audit-marked-*.jpg'):shutil.copy2(p,data/p.name)
    shutil.copytree(FOLLOW/'replay',data/'development',ignore=shutil.ignore_patterns('*.pt'))
    shutil.copytree(FOLLOW/'sources',data/'source-code')
    shutil.copytree(FOLLOW/'recipe',data/'recipe')
    table='| Model / input | TP | FP | FN | Recall | Precision |\n|---|---:|---:|---:|---:|---:|\n'
    for name,result in replay['results'].items():
        r=result['phone_threshold'];table+=f"| {name} | {r['tp']} | {r['fp']} | {r['fn']} | {r['recall']:.1%} | {r['precision']:.1%} |\n"
    rows=[]
    for name,result in replay['results'].items():
        for r in result['development_sweep']:rows.append({'configuration':name,**{k:r[k] for k in ['threshold','tp','fp','fn','precision','recall','f2','fp_per_image']}})
    with (data/'development-thresholds.csv').open('w') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    text='''# Detector follow-up: visual error audit and phone-window development replay

All58 saved error instances were visually assessed by the assistant: d5 has26 false positives and7 misses; d4 has18 false positives and7 misses. These are model-assisted references, not human-certified ground truth. Original results and labels are preserved. No new holdout inference was performed.

## Development comparison

The same17 development images contain33 reference signs. Both models use the phone threshold0.840783, with12 proposals per pass and source-coordinate NMS0.45. Two square edge crops are used for landscape images, one whole-frame pass for portrait images, and an additional whole-frame pass for width>2*height. The export confidence floor is0.25.

'''+table+'''
The crop and admission rules reproduce the iPhone source. Pixel rendering uses Pillow bilinear sampling and inference uses PyTorch FP32 on KI; Core Image/Core ML FP16 numerical parity and phone latency are NOT established. This is a detector proposal comparison, not the downstream classifier or temporal app pipeline. Development threshold sweeps are exploratory and do not establish held-out performance.

## Visual findings

| False-positive category | d4 | d5 |
|---|---:|---:|
| Vegetation |9|14|
| Truck rear lamps |6|7|
| Roof texture |1|2|
| Excluded direction boards |2|2|
| Road delineator |0|1|

The two models miss the same7 references:3 primary sign faces and4 red/white hazard panels. Their short edges are about10–28 source pixels. Small size is directly observable; this audit does not isolate a causal explanation for every miss. Truck rear lamps are not the tolerated traffic-light category.

The original holdout has18 images,10 sign instances and2 sequence-connected groups. Its scope includes red/white hazard panels, excludes direction boards and separate supplements, and does not count traffic lights as positive training labels.

## Complete marked error sheets

Red rectangles identify the exact audited target. FN means a missed reference box; FP means an unmatched proposal at the original model-specific development threshold (d4:0.49, d5:0.47). These differ from the phone-threshold development comparison above.

'''
    for p in sorted(data.glob('audit-marked-*.jpg')):text+=f'![{p.stem}]({p.name})\n\n'
    text+='[Per-error assessment and evidence hashes](audit-adjudication.json) · [Development metrics](development/summary.json) · [Threshold CSV](development-thresholds.csv)\n'
    (data/'README.md').write_text(text)
    manifest={'schema':'streetshots-followup-report-v1','source_dataset_revision':'e428e4cff9b179934ffa5bb7609973178c8c18e8',
              'source_model_revision':'8b3b546b508b1b778ddaca07a98a49cb45509368','visual_review':'assistant','human_verified':False,
              'files':{p.relative_to(data).as_posix():digest(p) for p in data.rglob('*') if p.is_file()}}
    (data/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    print(json.dumps(inventory(staging/'dataset','dataset',DATA_PREFIX+'/manifest.json',staging/'dataset-inventory.json')))

    control=FOLLOW/'control-150';history=json.loads((control/'history.json').read_text());seal=json.loads((control/'seal.json').read_text())
    assert [r['epoch'] for r in history]==list(range(151))
    assert digest(control/'selected.pt')==seal['checkpoint_sha256']
    winner=max(history,key=lambda r:r['ap50_95']);assert winner['epoch']==seal['selected_epoch']
    model=staging/'model/detector/d6';model.mkdir(parents=True)
    for name in ['history.json','epochs.jsonl','configuration.json','seal.json','selection.json','development-threshold-sweep.json','learning-curves.png']:
        shutil.copy2(control/name,model/name)
    (model/'artifacts').mkdir()
    for src,dst in [('selected.pt','d6.pt'),('fit/weights/best.pt','ultralytics-best.pt'),('fit/weights/last.pt','last.pt')]:
        shutil.copy2(control/src,model/'artifacts'/dst)
    shutil.copy2(control/'fit/results.csv',model/'epochs.csv')
    shutil.copy2(FOLLOW/'control-150.log',model/'training.log')
    shutil.copy2(FOLLOW/'control-launch.json',model/'launch.json')
    shutil.copy2(FOLLOW/'control-state-comparison.json',model/'d5-state-comparison.json')
    summary={'schema':'streetshots-d6-control-results-v1','epochs':150,'training_images':48,'development_images':17,
             'full_source_training':False,'selected_epoch':seal['selected_epoch'],'selected_development_ap50_95':seal['development_ap50_95'],
             'final_development_ap50_95':history[-1]['ap50_95'],'new_holdout_evaluation':False,
             'definition_revision':'c17103f5e02bb3738c3ade6a3df508eb3a2f3547','selected_checkpoint_sha256':seal['checkpoint_sha256']}
    (model/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    (model/'README.md').write_text(f'''# d6:150-epoch reviewed-data control

This isolates longer training on the same48 training/17 development images. It is **not full-source training**. The separate expanded weakly supervised experiment is still being prepared.

The development rule selected epoch{seal['selected_epoch']} with AP50–95 {seal['development_ap50_95']:.2%}. Epoch150 reached {history[-1]['ap50_95']:.2%}. No new holdout evaluation was run. Labels remain model-assisted.

[Epoch CSV](epochs.csv) · [Complete epoch history](history.json) · [Training log](training.log) · [Selected weights](artifacts/d6.pt) · [d5 state comparison](d5-state-comparison.json)

![Learning curves](learning-curves.png)

The selected checkpoint is bound by seal.json. Ultralytics best/last files are retained for provenance and do not define the selected candidate. Native export accuracy and phone latency are unmeasured.

Visual audit and d4/d5 development crop comparison: [dataset report](https://huggingface.co/datasets/loffenauer/streetshots/tree/main/{DATA_PREFIX}).
''')
    (model/'release.json').write_text(json.dumps({'schema':'streetshots-d6-release-v1','definition_revision':summary['definition_revision'],
        'files':{p.relative_to(model).as_posix():digest(p) for p in model.rglob('*') if p.is_file()}},indent=2)+'\n')
    print(json.dumps(inventory(staging/'model','model','detector/d6/release.json',staging/'model-inventory.json')))


if __name__=='__main__':main()
