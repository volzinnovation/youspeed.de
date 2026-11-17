#!/usr/bin/env python3
"""Publish numeric comparison/provenance only; raw Mapillary media stay on KI."""
import json,shutil,sys
from pathlib import Path
JOB=Path('/home/raphael/streetshots-d5-20261114');ROOT=JOB/'balanced-v1';sys.path.insert(0,str(JOB/'expanded-v1/recipe'))
from prepare_expanded_publication import sha,write,inventory

def main():
    source=ROOT/'mapillary-benchmark';assert json.loads((source/'complete.json').read_text())['complete']
    publication=ROOT/'publication';target=publication/'detector/d9/mapillary-automatic-benchmark';target.mkdir(parents=True,exist_ok=False)
    for name in ['README.md','summary.json','comparison.csv','definition.json','complete.json','comparison.png']:shutil.copy2(source/name,target/name)
    sample=JOB/'mapillary-auto-v2';manifest=json.loads((sample/'manifest.json').read_text())
    rows=[{k:f[k] for k in ['image_id','source_url','sequence_id','anchor','image_sha256','detection_sha256','width','height','nearest_finetuning_or_dev_m']} for f in manifest['frames']]
    write(target/'sample-provenance.json',{'manifest_sha256':sha(sample/'manifest.json'),'native_manifest_sha256':sha(sample/'native-inputs/manifest.json'),'reference_completeness':False,'media_and_raw_annotations_published':False,'source_images':rows})
    shutil.copy2(sample/'plan.json',target/'sample-plan.json');shutil.copy2(ROOT/'mapillary-benchmark-launch.json',target/'launch.json');(target/'recipe').mkdir()
    for name in ['benchmark_mapillary_auto.py','train_balanced.py','train_latest.py','train_evaluate.py','mobile_replay.py']:
        shutil.copy2(ROOT/'recipe'/name,target/'recipe'/name)
    with (target/'README.md').open('a') as stream:stream.write('\n[Source image links and hashes](sample-provenance.json) · [Metadata-first sampling plan](sample-plan.json). Raw Mapillary photographs, annotation payloads and signed image URLs are not included in this results publication.\n')
    inventory(publication,target,'model','detector/d9/mapillary-automatic-benchmark/summary.json',ROOT/'mapillary-benchmark-inventory.json')
if __name__=='__main__':main()
