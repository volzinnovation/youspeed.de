#!/usr/bin/env python3
"""Publish an honest immutable start snapshot, not a completion claim."""
import json,shutil,sys
from datetime import datetime,timezone
from pathlib import Path
JOB=Path('/home/raphael/streetshots-d5-20261114');ROOT=JOB/'balanced-v1';sys.path.insert(0,str(JOB/'expanded-v1/recipe'))
from prepare_expanded_publication import sha,write,inventory

def main():
    run=ROOT/'runs/panoramax';history=json.loads((run/'history.json').read_text());assert len(history)>=2
    epoch=history[-1]['epoch'];publication=ROOT/'publication';prefix=f'detector/d10/start-epoch-{epoch:03d}';target=publication/prefix;target.mkdir(parents=True,exist_ok=False)
    write(target/'history.json',history)
    for name in ['configuration.json','selection.json']:shutil.copy2(run/name,target/name)
    for row in history:shutil.copy2(run/f'epoch-{row["epoch"]:03d}-phone.json',target/f'epoch-{row["epoch"]:03d}-phone.json')
    for name in ['panoramax-launch.json','panoramax-definition.json','panoramax-head-check.json']:shutil.copy2(ROOT/name,target/name)
    write(target/'status.json',{'training_started':True,'training_complete':(run/'seal.json').exists(),'snapshot_utc':datetime.now(timezone.utc).isoformat(),'completed_epochs_at_snapshot':epoch,'planned_epochs':20,'history_sha256':sha(target/'history.json'),'gpu':0,'deployed':False})
    (target/'README.md').write_text(f'# Panoramax fine-tuning started\n\nThe pretrained sign-only Panoramax YOLO11l experiment is running on KI GPU0. This immutable snapshot includes{epoch} completed epoch(s) of the planned20, with the epoch0 baseline and per-epoch development phone metrics. It is not a final result or an improvement claim.\n\nTraining began after the d9 comparison and epoch logs were verified on private HF and the separate Mapillary automatic-reference benchmark completed. The Mapillary sample is not used for training or threshold/checkpoint selection. No phone model was deployed.\n\n[Epoch history](history.json) · [Current selection at snapshot](selection.json) · [Training definition](panoramax-definition.json) · [Launch provenance](panoramax-launch.json)\n')
    inventory(publication,target,'model',prefix+'/status.json',ROOT/'panoramax-start-inventory.json')
if __name__=='__main__':main()
