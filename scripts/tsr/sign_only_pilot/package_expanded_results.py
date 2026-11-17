#!/usr/bin/env python3
"""Package completed d7 epochs and post-selection development comparisons."""
import csv
import gzip
import json
from pathlib import Path
import shutil
from prepare_expanded_publication import ROOT, JOB, PREFIX, inventory, sha, write


def main():
    run=ROOT/'full-150';history=json.loads((run/'history.json').read_text())
    seal=json.loads((run/'seal.json').read_text());config=json.loads((run/'configuration.json').read_text())
    assert [r['epoch'] for r in history]==list(range(151))
    assert seal['checkpoint_sha256']==sha(run/'selected.pt')
    assert seal['history_sha256']==sha(run/'history.json')
    assert seal['configuration_sha256']==sha(run/'configuration.json')
    assert max(history,key=lambda r:(r['ap50_95'],-r['epoch']))['epoch']==seal['selected_epoch']
    assert config['script_sha256']==sha(ROOT/'recipe/train_mixed.py')
    launch=json.loads((ROOT/'training-launch.json').read_text())
    replay=ROOT/'development-coreimage';comparison=json.loads((replay/'summary.json').read_text())
    assert comparison['split']=='validation' and comparison['images']==17
    d7=next(r for r in comparison['models'] if r['name']=='d7')
    assert d7['sha256']==seal['checkpoint_sha256']
    staging=ROOT/'results-publication';staging.mkdir(exist_ok=False)
    data=staging/'dataset'/PREFIX/'results';data.mkdir(parents=True)
    shutil.copytree(replay,data/'development',ignore=shutil.ignore_patterns('*.pt'))
    shutil.copytree(ROOT/'native-inputs',data/'native-inputs')
    native_manifest=json.loads((ROOT/'native-inputs/manifest.json').read_text())
    shutil.copytree(ROOT/'native-source',data/'native-source')
    table='| Model / input | TP | FP | FN | Recall | Precision |\n|---|---:|---:|---:|---:|---:|\n'
    sweep=[]
    for name,result in comparison['results'].items():
        r=result['phone_threshold']
        table+=f"| {name} | {r['tp']} | {r['fp']} | {r['fn']} | {r['recall']:.1%} | {r['precision']:.1%} |\n"
        sweep.extend({'configuration':name,**{k:r[k] for k in ('threshold','tp','fp','fn','precision','recall','f2','fp_per_image')}} for r in result['development_sweep'])
    with (data/'development-thresholds.csv').open('w') as handle:
        writer=csv.DictWriter(handle,fieldnames=list(sweep[0]));writer.writeheader();writer.writerows(sweep)
    (data/'README.md').write_text('# d7: selected-candidate development replay\n\nThe same 17 development images contain 33 reference signs. This post-selection comparison uses the actual iPhone Swift input/geometry source compiled unchanged on macOS, then PyTorch FP32 inference on KI. Core ML numerical parity and phone latency remain unverified. No fresh geographic holdout was scored.\n\nAll models use threshold 0.840783, the per-pass cap of 12 and source-coordinate NMS 0.45. The confidence floor is 0.25.\n\n'+table+'\n[Visual report](development/index.html) · [Raw results](development/summary.json) · [Threshold sweep](development-thresholds.csv) · [Native input provenance](native-inputs/manifest.json)\n\nThis is a proposal-detector comparison, not the downstream classifier or temporal app behavior. Repeated development use limits generalization claims. The earlier Pillow-rendered report remains unchanged; it should not be conflated with this renderer.\n')
    write(data/'manifest.json',{'schema':'streetshots-d7-development-report-v1','selected_checkpoint_sha256':seal['checkpoint_sha256'],
         'training_definition_revision':launch['definition_revision'],'training_dataset_revision':launch['dataset_revision'],
         'native_input_manifest_sha256':sha(ROOT/'native-inputs/manifest.json'),
         'files':{p.relative_to(data).as_posix():sha(p) for p in data.rglob('*') if p.is_file()}})
    inventory(staging/'dataset',data,'dataset',PREFIX+'/results/manifest.json',ROOT/'results-dataset-inventory.json')

    model=staging/'model/detector/d7';model.mkdir(parents=True);(model/'artifacts').mkdir()
    for name in ('history.json','epochs.jsonl','configuration.json','seal.json','selection.json','development-threshold-sweep.json','learning-curves.png'):
        shutil.copy2(run/name,model/name)
    shutil.copy2(run/'fit/results.csv',model/'epochs.csv')
    shutil.copy2(ROOT/'training-launch.json',model/'launch.json')
    for source,name in [('selected.pt','d7.pt'),('fit/weights/best.pt','ultralytics-best.pt'),('fit/weights/last.pt','last.pt')]:
        shutil.copy2(run/source,model/'artifacts'/name)
    with (model/'training.log.gz').open('wb') as raw:
        with gzip.GzipFile(filename='',fileobj=raw,mode='wb',mtime=0) as out:
            with (ROOT/'full-150.log').open('rb') as source:shutil.copyfileobj(source,out)
    fields=('epoch','ap50_95','delta_previous_epoch','delta_epoch_zero','best_ap50_95_so_far','ap50','precision','recall','duration_seconds')
    best=-1;previous=history[0]['ap50_95']
    with (model/'epoch-improvements.csv').open('w') as handle:
        writer=csv.DictWriter(handle,fieldnames=fields);writer.writeheader()
        for r in history:
            best=max(best,r['ap50_95'])
            writer.writerow({**{k:r[k] for k in ('epoch','ap50_95','ap50','precision','recall','duration_seconds')},
                             'delta_previous_epoch':r['ap50_95']-previous,'delta_epoch_zero':r['ap50_95']-history[0]['ap50_95'],
                             'best_ap50_95_so_far':best})
            previous=r['ap50_95']
    counts=json.loads((ROOT/'dataset'/PREFIX/'training-counts.json').read_text())
    summary={'schema':'streetshots-d7-full-results-v1','epochs':150,'training_counts':counts,
             'selected_epoch':seal['selected_epoch'],'selected_development_ap50_95':seal['development_ap50_95'],
             'epoch_zero_development_ap50_95':history[0]['ap50_95'],'final_development_ap50_95':history[-1]['ap50_95'],
             'selected_checkpoint_sha256':seal['checkpoint_sha256'],'definition_revision':launch['definition_revision'],
             'dataset_revision':launch['dataset_revision'],'new_holdout_evaluation':False,'amp_enabled':config['amp_enabled'],
             'phone_pipeline_native_parity_verified':False,'deployment':False}
    write(model/'summary.json',summary)
    (model/'README.md').write_text(f'''# d7: full eligible weak-data expansion

The run completed 150 epochs from d4 using {counts['train']['images']} training images. Labels mix reviewed pilot scenes and explicitly weak teacher pseudo-labels; see the frozen dataset for all admissions and exclusions. Source inventory covered all 35,147 images; geographic and label-quality filters define eligibility. This is not training on every source image.

Development selection chose epoch {seal['selected_epoch']} at AP50–95 **{seal['development_ap50_95']:.2%}**. Epoch zero measured {history[0]['ap50_95']:.2%}; epoch 150 measured {history[-1]['ap50_95']:.2%}. The d6 reviewed-data control reached 23.122%. These values use the same small, reused whole-frame development set; they do not prove a fresh-holdout improvement.

[Per-epoch improvements](epoch-improvements.csv) · [Epoch metrics](epochs.csv) · [Complete history](history.json) · [Training log](training.log.gz) · [Selected weights](artifacts/d7.pt)

![Learning curves](learning-curves.png)

The selected weights are bound by `seal.json`. Ultralytics best/last files are provenance copies and do not replace the selection rule. Batch 16, native AMP checks, 1024 input and the complete frozen recipe are recorded in the definition and configuration.

[Core Image development comparison and visual report](https://huggingface.co/datasets/loffenauer/streetshots/tree/main/{PREFIX}/results) uses the actual Swift crop code on macOS and inference on KI. iOS/Core ML numerical parity and phone latency remain unmeasured. No model was deployed.

An additional 93 metadata-qualified geographic images remain reserved and unreviewed. Recovered baseline exposure is incomplete, and upstream/classifier exposure is unknown. No new holdout result is claimed.
''')
    write(model/'release.json',{'schema':'streetshots-d7-release-v1','definition_revision':launch['definition_revision'],
          'files':{p.relative_to(model).as_posix():sha(p) for p in model.rglob('*') if p.is_file()}})
    inventory(staging/'model',model,'model','detector/d7/release.json',ROOT/'results-model-inventory.json')


if __name__=='__main__':main()
