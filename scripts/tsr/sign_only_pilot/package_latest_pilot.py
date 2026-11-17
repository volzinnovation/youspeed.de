#!/usr/bin/env python3
"""Package completed d7 training and native-input/tiled development evidence."""
import csv
import gzip
import json
from pathlib import Path
import shutil
from prepare_expanded_publication import inventory,sha,write
from train_latest import verified_run

JOB=Path('/home/raphael/streetshots-d5-20261114');ROOT=JOB/'latest-ultralytics-v1'
PREFIX='reviews/detector-expanded-2026-11-15/latest-tiling'


def epoch_table(history,path):
    fields=['epoch','ap50_95','delta_previous_epoch','delta_epoch_zero','best_ap50_95_so_far','ap50','precision','recall','duration_seconds','training_samples_per_epoch','training_batches_per_epoch','optimizer_step_calls_total']
    best=-1;previous=history[0]['ap50_95']
    with path.open('w') as handle:
        writer=csv.DictWriter(handle,fieldnames=fields);writer.writeheader()
        for row in history:
            best=max(best,row['ap50_95'])
            writer.writerow({**{k:row.get(k) for k in fields if k in row},'delta_previous_epoch':row['ap50_95']-previous,
                'delta_epoch_zero':row['ap50_95']-history[0]['ap50_95'],'best_ap50_95_so_far':best})
            previous=row['ap50_95']


def main():
    assert (ROOT/'pilot-replays-complete.json').exists()
    launch=json.loads((ROOT/'pilot-launch.json').read_text())
    staging=ROOT/'pilot-results-publication';staging.mkdir(exist_ok=False)
    data=staging/'dataset'/PREFIX;data.mkdir(parents=True)
    model=staging/'model/detector/d7/results';model.mkdir(parents=True)
    baseline=json.loads((ROOT/'native-baselines/summary.json').read_text())
    table='| Model / training | Selected epoch | Whole-image dev AP50–95 | Phone TP | FP | FN | Phone recall |\n|---|---:|---:|---:|---:|---:|---:|\n'
    for name in ('d4','d5','d6'):
        c=baseline['results'][name+'-phone_windows']['phone_threshold']
        table+=f'| {name} | — | — | {c["tp"]} | {c["fp"]} | {c["fn"]} | {c["recall"]:.1%} |\n'
    arm_results={}
    for arm in ('whole','tile'):
        run=ROOT/('pilot-'+arm);seal,config,history=verified_run(run)
        assert config['ultralytics']=='8.4.213' and config['epochs']==40 and config['split_frames']['train']==48
        replay=ROOT/('replay-'+arm);comparison=json.loads((replay/'summary.json').read_text())
        assert comparison['models'][0]['sha256']==seal['checkpoint_sha256']
        r=comparison['results']['d7-phone_windows'];c=r['phone_threshold']
        best=max(r['development_sweep'],key=lambda p:(p['f2'],p['recall'],p['precision'],p['threshold']))
        arm_results[arm]={'seal':seal,'configuration':config,'phone_threshold':{k:v for k,v in c.items() if k!='frames'},'phone_development_best':best}
        table+=f'| d7 {arm} | {seal["selected_epoch"]} | {seal["development_ap50_95"]:.2%} | {c["tp"]} | {c["fp"]} | {c["fn"]} | {c["recall"]:.1%} |\n'
        target=model/arm;target.mkdir()
        for name in ('history.json','epochs.jsonl','configuration.json','seal.json','selection.json','development-threshold-sweep.json','learning-curves.png'):
            shutil.copy2(run/name,target/name)
        shutil.copy2(run/'fit/results.csv',target/'epochs.csv');epoch_table(history,target/'epoch-improvements.csv')
        (target/'artifacts').mkdir()
        for src,dst in [('selected.pt','selected.pt'),('fit/weights/last.pt','last.pt'),('fit/weights/best.pt','ultralytics-best.pt')]:shutil.copy2(run/src,target/'artifacts'/dst)
        with (target/'training.log.gz').open('wb') as raw:
            with gzip.GzipFile(filename='',fileobj=raw,mode='wb',mtime=0) as compressed:
                with (ROOT/('pilot-'+arm+'.log')).open('rb') as log:shutil.copyfileobj(log,compressed)
        shutil.copytree(replay,data/('phone-'+arm),ignore=shutil.ignore_patterns('*.pt'))
    winner=max(arm_results,key=lambda arm:(arm_results[arm]['phone_development_best']['f2'],arm_results[arm]['phone_development_best']['recall'],arm_results[arm]['phone_development_best']['precision'],arm_results[arm]['seal']['development_ap50_95']))
    phone_choice=max(arm_results,key=lambda arm:(arm_results[arm]['phone_development_best']['recall'],arm_results[arm]['phone_threshold']['recall'],arm_results[arm]['phone_development_best']['f2']))
    practical={'arm':phone_choice,'status':'post-hoc engineering recommendation, not the prespecified F2 ranking','reason':'The user tolerates extra candidates for downstream classification. Prefer higher development recall and retain visibility of the fixed-phone-threshold regression. A tiny F2 gain does not establish a drop-in phone improvement.'}
    summary={'phone_recall_recommendation':practical,'schema':'streetshots-d7-latest-tiling-results-v1','definition_revision':launch['definition_revision'],
             'ultralytics':'8.4.213','arms':arm_results,'recommended_training_arm_from_reused_development':winner,
             'new_holdout_evaluation':False,'deployed':False}
    write(model/'summary.json',summary);write(data/'summary.json',summary)
    shutil.copytree(ROOT/'native-baselines',data/'baseline-latest',ignore=shutil.ignore_patterns('*.pt'))
    shutil.copytree(ROOT/'builtin-inference',data/'builtin-inference')
    shutil.copytree(ROOT/'probe',data/'compatibility-probe',ignore=shutil.ignore_patterns('*.pt'))
    shutil.copy2(ROOT/'runtime-replay-delta.json',data/'runtime-replay-delta.json')
    (data/'recipe').mkdir()
    for name in ('replay_latest.py','replay_builtin_tiles.py','finish_latest_pilot.py','package_latest_pilot.py'):
        shutil.copy2(JOB/'expanded-v1/recipe'/name,data/'recipe'/name)
    text='# Ultralytics 8.4.213: native tiling test\n\nBoth d7 arms completed 40 epochs on 48 reviewed training images / 85 sign boxes. The same 17 development images / 33 sign references select checkpoints and compare phone inputs. These are model-assisted labels and reused development evidence, not a new holdout estimate.\n\n'+table
    text+='\nThe fixed phone threshold is 0.840783, with 12 proposals per pass and source NMS 0.45. Inputs use the unchanged iPhone Swift/Core Image code rendered on macOS, then KI FP32 inference. This does not establish iOS/Core ML numerical parity or phone latency.\n\n'
    text+='| Training arm | Samples per epoch | Total optimizer-step calls | Best exploratory phone F2 | Threshold | TP / FP / FN |\n|---|---:|---:|---:|---:|---|\n'
    for arm,r in arm_results.items():
        h=json.loads((ROOT/('pilot-'+arm)/'history.json').read_text());b=r['phone_development_best']
        text+=f'| {arm} | {r["configuration"]["training_samples_per_epoch"]} | {h[-1]["optimizer_step_calls_total"]} | {b["f2"]:.3f} | {b["threshold"]:.2f} | {b["tp"]} / {b["fp"]} / {b["fn"]} |\n'
    text+=f'\nThe prespecified development F2 rule ranks **{winner}** first. The post-hoc engineering recommendation for the next full-data run is **{phone_choice}**, prioritizing sign recall because downstream classification can filter extra candidates. Equal source epochs do not imply equal compute: tiling expands samples and optimizer steps. Threshold tuning here is exploratory and needs independent validation. No model or threshold was deployed.\n\n'
    text+='The new runtime loads d4/d5/d6. Fixed-threshold native-input counts match 8.4.56, although individual coordinates/scores differ. The synthetic seam fixture drops a covered partial box and retains an uncovered fragment. Visual review of the previously clipped no-entry sign confirms a complete box with native tiled inference in that case; this is not a universal seam guarantee.\n\n![Native tiled teacher seam example](compatibility-probe/builtin_tile1536-seam-case.png)\n\n'
    text+='[Whole-trained phone visual report](phone-whole/index.html) · [Tile-trained phone visual report](phone-tile/index.html) · [Latest-runtime baseline report](baseline-latest/index.html) · [Separate built-in tiled inference results](builtin-inference/summary.json) · [Runtime differences](runtime-replay-delta.json)\n\nBuilt-in tiled inference uses 1024-pixel windows, 20% overlap and up to 300 proposals. It does not apply the phone per-pass cap and is not the phone two-crop pipeline. The feature runs in Python and is not embedded in model exports.\n'
    (data/'README.md').write_text(text)
    modeltext='# d7 completed native-tiling comparison\n\n'+table+'\nBoth arms completed 40 epochs using Ultralytics 8.4.213, d4 initialization, batch 16 and AMP. The frozen definition preceded training. The experiment tests the latest training feature on the reviewed pilot; it is not the expanded full-data run.\n\n'
    for arm in ('whole','tile'):
        modeltext+=f'## {arm.capitalize()} training\n\n[Per-epoch improvements]({arm}/epoch-improvements.csv) · [History]({arm}/history.json) · [Training log]({arm}/training.log.gz) · [Selected checkpoint]({arm}/artifacts/selected.pt)\n\n![Learning curves]({arm}/learning-curves.png)\n\n'
    modeltext+=f'The prespecified development phone F2 rule ranks **{winner}** first. The post-hoc recommendation for full-data training is **{phone_choice}** because it retains more signs for the downstream classifier and avoids the larger fixed-threshold regression. See [raw summary](summary.json) and [visual comparison](https://huggingface.co/datasets/loffenauer/streetshots/tree/main/{PREFIX}). Thresholds and model quality remain unvalidated on a fresh holdout; no deployment.\n'
    (model/'README.md').write_text(modeltext)
    for dest,kind,prefix,name in [(data,'dataset',PREFIX,'pilot-results-dataset-inventory.json'),(model,'model','detector/d7/results','pilot-results-model-inventory.json')]:
        write(dest/'release.json',{'definition_revision':launch['definition_revision'],'files':{p.relative_to(dest).as_posix():sha(p) for p in dest.rglob('*') if p.is_file()}})
        inventory(staging/kind,dest,kind,prefix+'/release.json',ROOT/name)
    print(json.dumps({'nominal_f2_winner':winner,'phone_recall_recommendation':practical,'arms':{k:{'epoch':v['seal']['selected_epoch'],'ap':v['seal']['development_ap50_95'],'phone':v['phone_threshold'],'best_phone':v['phone_development_best']} for k,v in arm_results.items()}}))

if __name__=='__main__':main()
