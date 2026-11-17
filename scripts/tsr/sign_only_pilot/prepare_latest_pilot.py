#!/usr/bin/env python3
"""Freeze an Ultralytics 8.4.213 tiling comparison before real-image training."""
import json
from pathlib import Path
import shutil
from datetime import datetime, timezone
from prepare_expanded_publication import inventory, sha, write

JOB=Path('/home/raphael/streetshots-d5-20261114')
ROOT=JOB/'latest-ultralytics-v1'
RECIPE=JOB/'expanded-v1/recipe'


def main():
    probe=json.loads((ROOT/'probe/report.json').read_text())
    assert probe['version']=='8.4.213' and all(probe['seam_checks'].values())
    for name in ('smoke-whole','smoke-wide-tile'):
        config=json.loads((ROOT/name/'configuration.json').read_text())
        assert config['script_sha256']==sha(RECIPE/'train_latest.py')
        assert config['amp_enabled'] and config['completed_epochs']==1
        if name=='smoke-wide-tile':assert config['training_samples_per_epoch']>config['split_frames']['train']
    manifest=JOB/'dataset-reviewed-v1/manifest.json'
    assert sha(manifest)=='8d4f939e502b97b98750136d96fa9cc2f89017b236b69f1f57be2b55b9d73e1a'
    runtime={'image':'sha256:886be2a4e18d52e587acf3ebfeaa7cbf2da92c1c26d2355e83b94217c474faca',
             'ultralytics':'8.4.213','ultralytics_wheel_sha256':'f785d4505a1f4d55f1f46c6ff27d8ff28154c857c964323c5bf610da7f389a97',
             'torch':'2.6.0+cu126','gpu':'KI GPU0 RTX A5000','network':'none','channels_last':False}
    value={'build':'d7','status':'frozen_before_training','definition_frozen_at_utc':datetime.now(timezone.utc).isoformat(),
        'experiment':'Native tile=True versus whole-image training under the same latest runtime',
        'dataset_repository':'loffenauer/streetshots','dataset_revision':'e428e4cff9b179934ffa5bb7609973178c8c18e8',
        'manifest_path':'reviews/detector-pilot-2026-11-14/manifest.json','manifest_sha256':sha(manifest),
        'training_images':48,'training_boxes':85,'development_images':17,'development_boxes':33,
        'review_provenance':'model-assisted reviewed pilot; not human-certified',
        'initialization':'d4','initial_checkpoint_sha256':'f02bf99483c5ad2b79f254b1623b18593ed780c8f3c2df7051331633bb1a2a36',
        'scratch':False,'initialization_rationale':'Retain the sign-pretrained mobile YOLO26n architecture and weights; compare tiling without discarding pretrained features.',
        'arms':[{'name':'whole','tile':False},{'name':'tile','tile':True}],
        'epochs':40,'batch':16,'image_size':1024,'seed':14,'lr0':.0002,'amp':True,'cache':'disk','patience':0,
        'runtime':runtime,'script_sha256':sha(RECIPE/'train_latest.py'),
        'validation':'Whole-image FP32, tile=False, rect=False, IoU0.45, max_det300; same17 development images each epoch.',
        'checkpoint_selection':'Maximum development AP50-95, earliest epoch wins ties; epoch zero eligible.',
        'arm_recommendation':'Compare selected checkpoints using actual Swift/Core Image phone inputs; best development F2 on fixed0.25..0.99 grid, then recall, precision, AP50-95. This reuses development and is not an independent estimate.',
        'optimizer':'AdamW','weight_decay':.0005,'warmup_epochs':2,'final_lr_fraction':.1,
        'augmentation':{'mosaic':.25,'close_mosaic':5,'mixup':0,'fliplr':0,'flipud':0,'degrees':2,'translate':.05,'scale':.25,'hsv_h':.01,'hsv_s':.3,'hsv_v':.3},
        'scope':'Sign only; direction boards and supplementary plates excluded; traffic lights are acceptable extra candidates, not a trained class.',
        'test_usage':'No new consumed-test or qualified-reserve image decoding, inference or label parsing.',
        'limitations':['Small reused development set; no fresh holdout result.','Equal source epochs produce different tile sample counts and optimizer budgets; both are logged.','Native tiling is a Python training/inference feature, not part of exported phone execution.','Core Image inputs are rendered on macOS; KI FP32 is not iOS/Core ML numerical parity.'],
        'deployment':'None'}
    root=ROOT/'pilot-definition-publication';dest=root/'detector/d7';dest.mkdir(parents=True,exist_ok=False)
    write(dest/'definition.json',value)
    (dest/'recipe').mkdir();(dest/'provenance').mkdir()
    for name in ('train_latest.py','train_evaluate.py','mobile_replay.py','replay_latest.py','probe_latest_tiling.py','prepare_latest_pilot.py'):
        shutil.copy2(RECIPE/name,dest/'recipe'/name)
    for name in ('smoke-whole','smoke-wide-tile'):
        for file in ('configuration.json','seal.json','history.json'):
            shutil.copy2(ROOT/name/file,dest/'provenance'/(name+'-'+file))
    for path in [ROOT/'pypi-release.json',ROOT/'base-dependency-audit.json',ROOT/'probe/report.json']:
        shutil.copy2(path,dest/'provenance'/path.name)
    write(dest/'provenance/runtime-wheels.json', [{'filename':p.name,'sha256':sha(p)} for p in [*ROOT.glob('*.whl'),*(ROOT/'dependencies').glob('*.whl')]])
    (dest/'README.md').write_text('# d7: latest Ultralytics native tiling comparison\n\nDefinition frozen before training. Two40-epoch d4-initialized arms use the same48 reviewed training images and17 development images under Ultralytics8.4.213. One uses `tile=True`; the other whole images. Results will be added after completion. This is a reviewed-data feature comparison, not the full-source expansion. No deployment or fresh holdout claim.\n')
    inventory(root,dest,'model','detector/d7/definition.json',ROOT/'pilot-definition-inventory.json')

if __name__=='__main__':main()
