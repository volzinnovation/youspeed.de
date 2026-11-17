#!/usr/bin/env python3
"""Add HF-renderable side-by-side images to the unpublished d7 visual report."""
import hashlib
import json
from pathlib import Path
import shutil
from prepare_expanded_publication import inventory,sha,write

JOB=Path('/home/raphael/streetshots-d5-20261114');ROOT=JOB/'latest-ultralytics-v1'
PREFIX='reviews/detector-expanded-2026-11-15/latest-tiling'


def main():
    staging=ROOT/'pilot-results-publication/dataset';data=staging/PREFIX
    assert not (JOB/'publication-receipts/d7-results-dataset-v1.json').exists()
    rows=json.loads((data/'phone-whole/d7-phone_windows-predictions.json').read_text())
    parts=['# Phone-input comparison on development images','Green: matched sign reference. Yellow: missed reference. Red: unmatched candidate. Both models use the existing phone threshold 0.840783. Native Swift/Core Image rendering on macOS, inference on KI FP32; not an iOS/Core ML parity test.']
    for row in rows:
        name='d7-phone_windows-'+hashlib.sha256(row['image_id'].encode()).hexdigest()[:16]+'.jpg'
        left='phone-whole/images/'+name;right='phone-tile/images/'+name
        assert (data/left).is_file() and (data/right).is_file()
        parts += ['## '+row['image_id'], '| Whole-image training | Native tiled training |\n|---|---|\n'+f'| ![Whole-image training]({left}) | ![Native tiled training]({right}) |']
    (data/'gallery.md').write_text('\n\n'.join(parts)+'\n')
    with (data/'README.md').open('a') as handle:handle.write('\n[Side-by-side visual review rendered directly on HF](gallery.md)\n')
    shutil.copy2(__file__,data/'recipe/add_markdown_gallery.py')
    old=json.loads((data/'release.json').read_text())
    write(data/'release.json',{'definition_revision':old['definition_revision'],'files':{p.relative_to(data).as_posix():sha(p) for p in data.rglob('*') if p.is_file() and p.name!='release.json'}})
    inventory(staging,data,'dataset',PREFIX+'/release.json',ROOT/'pilot-results-dataset-inventory.json')

if __name__=='__main__':main()
