#!/usr/bin/env python3
"""Package completed d8 epochs and post-selection development comparisons."""
import csv
import gzip
import hashlib
import json
from pathlib import Path
import shutil
from prepare_expanded_publication import ROOT, JOB, PREFIX, inventory, sha, write


def main():
    run=ROOT/'latest-full';history=json.loads((run/'history.json').read_text())
    seal=json.loads((run/'seal.json').read_text());config=json.loads((run/'configuration.json').read_text())
    assert [r['epoch'] for r in history]==list(range(config['epochs']+1))
    assert config['training_samples_per_epoch']==json.loads((ROOT/'latest-full-launch.json').read_text())['expected_training_samples_per_epoch']
    assert seal['checkpoint_sha256']==sha(run/'selected.pt')
    assert seal['history_sha256']==sha(run/'history.json')
    assert seal['configuration_sha256']==sha(run/'configuration.json')
    assert max(history,key=lambda r:(r['ap50_95'],-r['epoch']))['epoch']==seal['selected_epoch']
    assert config['script_sha256']==sha(ROOT/'recipe/train_latest.py')
    launch=json.loads((ROOT/'latest-full-launch.json').read_text())
    replay=ROOT/'latest-full-development';comparison=json.loads((replay/'summary.json').read_text())
    assert comparison['split']=='validation' and comparison['images']==17
    d8=next(r for r in comparison['models'] if r['name']=='d8')
    assert d8['sha256']==seal['checkpoint_sha256']
    staging=ROOT/'latest-full-results-publication';staging.mkdir(exist_ok=False)
    data=staging/'dataset'/PREFIX/'d8-results';data.mkdir(parents=True)
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
    (data/'README.md').write_text('# d8: selected-candidate development replay\n\nThe same 17 development images contain 33 reference signs. This post-selection comparison uses the actual iPhone Swift input/geometry source compiled unchanged on macOS, then PyTorch FP32 inference on KI. Core ML numerical parity and phone latency remain unverified. No fresh geographic holdout was scored.\n\nAll models use threshold 0.840783, the per-pass cap of 12 and source-coordinate NMS 0.45. The confidence floor is 0.25.\n\n'+table+'\n[Visual report](development/index.html) · [Raw results](development/summary.json) · [Threshold sweep](development-thresholds.csv) · [Native input provenance](native-inputs/manifest.json)\n\nThis is a proposal-detector comparison, not the downstream classifier or temporal app behavior. Repeated development use limits generalization claims. The earlier Pillow-rendered report remains unchanged; it should not be conflated with this renderer.\n')
    gallery=['# d4 versus d8 on native phone inputs','Green: matched reference; yellow: missed reference; red: unmatched proposal. Existing threshold0.840783. Swift/Core Image on macOS plus KI FP32; no fresh holdout or iOS/Core ML parity claim.']
    for frame in json.loads((replay/'d8-phone_windows-predictions.json').read_text()):
        suffix=hashlib.sha256(frame['image_id'].encode()).hexdigest()[:16]+'.jpg'
        left='development/images/d4-phone_windows-'+suffix;right='development/images/d8-phone_windows-'+suffix
        assert (data/left).is_file() and (data/right).is_file()
        gallery+=['## '+frame['image_id'],'| d4 | d8 |\n|---|---|\n'+f'| ![d4]({left}) | ![d8]({right}) |']
    (data/'gallery.md').write_text('\n\n'.join(gallery)+'\n')
    with (data/'README.md').open('a') as handle:handle.write('\n[Side-by-side d4/d8 visual review](gallery.md)\n')
    write(data/'manifest.json',{'schema':'streetshots-d8-development-report-v1','selected_checkpoint_sha256':seal['checkpoint_sha256'],
         'training_definition_revision':launch['definition_revision'],'training_dataset_revision':launch['dataset_revision'],
         'native_input_manifest_sha256':sha(ROOT/'native-inputs/manifest.json'),
         'files':{p.relative_to(data).as_posix():sha(p) for p in data.rglob('*') if p.is_file()}})
    inventory(staging/'dataset',data,'dataset',PREFIX+'/d8-results/manifest.json',ROOT/'latest-full-results-dataset-inventory.json')

    model=staging/'model/detector/d8/results';model.mkdir(parents=True);(model/'artifacts').mkdir()
    for name in ('history.json','epochs.jsonl','configuration.json','seal.json','selection.json','development-threshold-sweep.json','learning-curves.png'):
        shutil.copy2(run/name,model/name)
    shutil.copy2(run/'fit/results.csv',model/'epochs.csv')
    shutil.copy2(ROOT/'latest-full-launch.json',model/'launch.json')
    for source,name in [('selected.pt','d8.pt'),('fit/weights/best.pt','ultralytics-best.pt'),('fit/weights/last.pt','last.pt')]:
        shutil.copy2(run/source,model/'artifacts'/name)
    with (model/'training.log.gz').open('wb') as raw:
        with gzip.GzipFile(filename='',fileobj=raw,mode='wb',mtime=0) as out:
            with (ROOT/'latest-full.log').open('rb') as source:shutil.copyfileobj(source,out)
    fields=('epoch','ap50_95','delta_previous_epoch','delta_epoch_zero','best_ap50_95_so_far','ap50','precision','recall','duration_seconds','training_samples_per_epoch','training_batches_per_epoch','optimizer_step_calls_total')
    best=-1;previous=history[0]['ap50_95']
    with (model/'epoch-improvements.csv').open('w') as handle:
        writer=csv.DictWriter(handle,fieldnames=fields);writer.writeheader()
        for r in history:
            best=max(best,r['ap50_95'])
            writer.writerow({**{k:r.get(k) for k in ('epoch','ap50_95','ap50','precision','recall','duration_seconds','training_samples_per_epoch','training_batches_per_epoch','optimizer_step_calls_total')},
                             'delta_previous_epoch':r['ap50_95']-previous,'delta_epoch_zero':r['ap50_95']-history[0]['ap50_95'],
                             'best_ap50_95_so_far':best})
            previous=r['ap50_95']
    counts=json.loads((ROOT/'dataset'/PREFIX/'training-counts.json').read_text())
    summary={'schema':'streetshots-d8-full-results-v1','epochs':config['epochs'],'tile_training':config['tile_training'],'training_samples_per_epoch':config['training_samples_per_epoch'],'training_counts':counts,
             'selected_epoch':seal['selected_epoch'],'selected_development_ap50_95':seal['development_ap50_95'],
             'epoch_zero_development_ap50_95':history[0]['ap50_95'],'final_development_ap50_95':history[-1]['ap50_95'],
             'selected_checkpoint_sha256':seal['checkpoint_sha256'],'definition_revision':launch['definition_revision'],
             'dataset_revision':launch['dataset_revision'],'new_holdout_evaluation':False,'amp_enabled':config['amp_enabled'],
             'phone_pipeline_native_parity_verified':False,'deployment':False}
    write(model/'summary.json',summary)
    (model/'README.md').write_text(f'''# d8: full eligible weak-data expansion

The run completed {config['epochs']} epochs from d4 using {counts['train']['images']} training images. Labels mix reviewed pilot scenes and explicitly weak teacher pseudo-labels; see the frozen dataset for all admissions and exclusions. Source inventory covered all 35,147 images; geographic and label-quality filters define eligibility. This is not training on every source image.

Development selection chose epoch {seal['selected_epoch']} at AP50–95 **{seal['development_ap50_95']:.2%}**. Epoch zero measured {history[0]['ap50_95']:.2%}; the final epoch measured {history[-1]['ap50_95']:.2%}. The d6 reviewed-data control reached 23.122%. These values use the same small, reused whole-frame development set; they do not prove a fresh-holdout improvement.

[Per-epoch improvements](epoch-improvements.csv) · [Epoch metrics](epochs.csv) · [Complete history](history.json) · [Training log](training.log.gz) · [Selected weights](artifacts/d8.pt)

![Learning curves](learning-curves.png)

The selected weights are bound by `seal.json`. Ultralytics best/last files are provenance copies and do not replace the selection rule. Ultralytics {config['ultralytics']}, batch 16, native AMP checks and 1024 input are recorded in the frozen recipe. Native training tiling: {config['tile_training']}; samples per epoch: {config['training_samples_per_epoch']}. Actual complete epochs and sample presentations are reported explicitly; tiled epochs must not be conflated with whole-image epochs.

[Core Image development comparison and visual report](https://huggingface.co/datasets/loffenauer/streetshots/tree/main/{PREFIX}/d8-results) uses the actual Swift crop code on macOS and inference on KI. iOS/Core ML numerical parity and phone latency remain unmeasured. No model was deployed.

An additional 93 metadata-qualified images were reserved before training. A separate blinded audit protocol selects one image from each of their 24 geographic groups; its reference review and evaluation are reported separately. Recovered baseline exposure is incomplete, and upstream/classifier exposure is unknown. This development report claims no new holdout result.
''')
    write(model/'release.json',{'schema':'streetshots-d8-release-v1','definition_revision':launch['definition_revision'],
          'files':{p.relative_to(model).as_posix():sha(p) for p in model.rglob('*') if p.is_file()}})
    inventory(staging/'model',model,'model','detector/d8/results/release.json',ROOT/'latest-full-results-model-inventory.json')


if __name__=='__main__':main()
