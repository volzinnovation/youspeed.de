#!/usr/bin/env python3
"""Stage additive d9 results after completion, preserving all epoch logs."""
import json,shutil,sys
from pathlib import Path
JOB=Path('/home/raphael/streetshots-d5-20261114');ROOT=JOB/'balanced-v1';sys.path.insert(0,str(JOB/'expanded-v1/recipe'))
from prepare_expanded_publication import sha,write,inventory

def main():
    assert json.loads((ROOT/'comparison-complete.json').read_text())['complete']
    publication=ROOT/'publication';model=publication/'detector/d9/results';dataset=publication/'reviews/detector-balanced-2026-11-15/results'
    model.mkdir(exist_ok=False,parents=True);shutil.copytree(ROOT/'comparison',dataset)
    for path in (ROOT/'comparison').iterdir():
        if path.is_file() and path.suffix!='.html':shutil.copy2(path,model/path.name)
    for arm in ['phone','mixed']:
        src=ROOT/'runs'/arm;target=model/arm;target.mkdir()
        for name in ['initial.pt','selected.pt','configuration.json','history.json','epochs.jsonl','selection.json','seal.json']:shutil.copy2(src/name,target/name)
        for path in src.glob('epoch-*-phone.json'):shutil.copy2(path,target/path.name)
        shutil.copy2(src/'fit/results.csv',target/'ultralytics-results.csv');shutil.copy2(src/'fit/args.yaml',target/'ultralytics-args.yaml')
        for name in ['best.pt','last.pt']:shutil.copy2(src/'fit/weights'/name,target/name)
        shutil.copy2(ROOT/(arm+'.log'),target/'training.log')
    diagnostic='\n## Final trained epoch (diagnostic)\n\nEpoch0 remains eligible for selection. These rows show actual trained epoch40 behavior separately; they do not replace the frozen selected checkpoints.\n\n| Arm | Final epoch | Calibrated threshold | TP / unmatched / missed | Fixed-threshold TP / unmatched / missed |\n|---|---:|---:|---|---|\n'
    for arm in ['phone','mixed']:
        last=json.loads((ROOT/'runs'/arm/'history.json').read_text())[-1];a=last['phone'];b=last['phone_fixed'];diagnostic+=f"| {arm} | {last['epoch']} | {a['threshold']:.2f} | {a['tp']} / {a['fp']} / {a['fn']} | {b['tp']} / {b['fp']} / {b['fn']} |\n"
    diagnostic+='\nActual optimizer updates (AMP can skip overflowing gradients): '
    diagnostic+=', '.join(arm+' '+str(json.loads((ROOT/'runs'/arm/'history.json').read_text())[-1]['optimizer_actual_updates_total'])+' / 2560 calls' for arm in ['phone','mixed'])+'.\n'
    for target in [model,dataset]:
        with (target/'README.md').open('a') as stream:stream.write(diagnostic)
        shutil.copy2(ROOT/'launch.json',target/'launch.json');shutil.copy2(ROOT/'definition.json',target/'definition.json')
    (model/'README.md').write_text((model/'README.md').read_text()+'\n[Private visual report](https://huggingface.co/datasets/loffenauer/streetshots/blob/main/reviews/detector-balanced-2026-11-15/results/README.md) · [Interactive error gallery (download HTML with images)](https://huggingface.co/datasets/loffenauer/streetshots/blob/main/reviews/detector-balanced-2026-11-15/results/index.html)\n\nPer-arm folders include all epoch phone predictions/sweeps, losses, learning rates, improvement CSVs, raw Ultralytics metrics and logs, and selected/best/last checkpoints. `selected.pt` follows the frozen phone-recall rule; `best.pt` follows Ultralytics whole-image AP and is not the chosen phone candidate.\n')
    with (dataset/'README.md').open('a') as stream:
        stream.write('\n## Development error gallery\n\nGreen matched references, yellow misses, red unmatched predictions. All images use each model’s development-calibrated threshold. These are derived from existing private HF images.\n\n')
        for path in sorted((dataset/'images').glob('*.jpg')):stream.write(f'### {path.stem}\n\n![{path.stem}](images/{path.name})\n\n')
    replacements={'completed40':'completed 40','of1024':'of 1024','(40,960 draws and2,560':'(40,960 draws and 2,560','same5,263':'same 5,263','not40':'not 40','after13':'after 13','Only17':'Only 17','images/33':'images / 33','epoch40':'epoch 40','Epoch0':'Epoch 0','threshold0.840783':'threshold 0.840783','by{':'by {'}
    for target in [model,dataset]:
        text=(target/'README.md').read_text()
        for old,new in replacements.items():text=text.replace(old,new)
        (target/'README.md').write_text(text)
    inventory(publication,model,'model','detector/d9/results/summary.json',ROOT/'results-model-inventory.json')
    inventory(publication,dataset,'dataset','reviews/detector-balanced-2026-11-15/results/summary.json',ROOT/'results-dataset-inventory.json')

if __name__=='__main__':main()
