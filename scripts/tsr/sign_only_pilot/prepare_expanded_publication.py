#!/usr/bin/env python3
"""Prepare additive d7 datasets/definitions from verified KI artifacts.

This script has no Hub credentials or network access and does not start training.
The Mac publisher handles the separately authorized private HF publication.
"""
import argparse
from collections import Counter
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import sys

JOB=Path('/home/raphael/streetshots-d5-20261114')
ROOT=JOB/'expanded-v1'
PREFIX='reviews/detector-expanded-2026-11-15'


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, obj):
    path.write_text(json.dumps(obj, indent=2, allow_nan=False)+'\n')


def inventory(root, subtree, kind, manifest, destination):
    rows=[]
    for path in sorted(subtree.rglob('*')):
        if not path.is_file():continue
        data=path.read_bytes()
        rows.append({'source_path':str(path), 'path_in_repo':path.relative_to(root).as_posix(),
                     'size':len(data), 'sha256':hashlib.sha256(data).hexdigest(),
                     'git_blob_sha1':hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()})
    write(destination, {'schema':'streetshots-ki-publish-inventory-v1','repository':'loffenauer/streetshots',
                        'repo_type':kind,'manifest_path_in_repo':manifest,'files':rows})
    print(json.dumps({'inventory':str(destination),'sha256':sha(destination),
                      'files':len(rows),'bytes':sum(r['size'] for r in rows)}))


def dataset():
    sys.path.insert(0,str(ROOT/'recipe'))
    from train_mixed import partition_manifest, checked_path, read_yolo_labels
    from full_source_eligibility import distance
    root=ROOT/'dataset';overlay=root/PREFIX
    manifest=json.loads((overlay/'manifest.json').read_text());parts=partition_manifest(manifest)
    images=[];counts={}
    for split,frames in parts.items():
        positives=boxes=0
        for frame in frames:
            image=checked_path(root,frame['image_path'],frame['image_sha256'])
            label=checked_path(root,frame['label_path'],frame['label_sha256'])
            # Retain the consumed test labels only as bytes; do not parse them.
            if split!='test':
                n=len(read_yolo_labels(label,frame['width'],frame['height']))
                positives+=bool(n);boxes+=n
            data=image.read_bytes()
            images.append({'path_in_repo':frame['image_path'],'sha256':frame['image_sha256'],
                           'size':len(data),'git_blob_sha1':hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()})
        counts[split]={'images':len(frames),'positive_images':positives if split!='test' else None,
                       'sign_boxes':boxes if split!='test' else None,
                       'supervision':dict(Counter(f['supervision'] for f in frames))}
    assert len({r['path_in_repo'] for r in images})==len(images)
    write(overlay/'image-reference-inventory.json', {'repository':'loffenauer/streetshots',
          'repo_type':'dataset','manifest_sha256':sha(overlay/'manifest.json'),'files':images})
    write(overlay/'training-counts.json',counts)
    reserve=json.loads((ROOT/'final-geographic-reserve.json').read_text())['frames']
    geographic={}
    train_sequences={s for r in parts['train'] for s in r['sequence_ids']}
    for name,reference in [('development',parts['validation']),('consumed_test',parts['test']),('qualified_reserve',reserve)]:
        assert not train_sequences.intersection(s for r in reference for s in r['sequence_ids'])
        minimum=min(distance(a['coordinates'],b['coordinates']) for a in parts['train'] for b in reference)
        assert minimum>=500, (name,minimum)
        geographic[name]={'minimum_training_distance_m':minimum,'shared_training_sequences':0,'reference_images':len(reference)}
    write(overlay/'geographic-verification.json',geographic)
    exclusions=json.loads((overlay/'exclusions.json').read_text())
    reasons=Counter(r['reason'] for r in exclusions)
    write(overlay/'exclusion-counts.json',dict(reasons))
    with (overlay/'README.md').open('a') as handle:
        handle.write('\n## Frozen membership\n\n| Split | Images | Positive images | Sign boxes |\n|---|---:|---:|---:|\n')
        for split,count in counts.items():
            handle.write(f"| {split} | {count['images']} | {count['positive_images']} | {count['sign_boxes']} |\n")
        handle.write('\nThe consumed test labels were not parsed for this expansion. See [training counts](training-counts.json), [exclusion counts](exclusion-counts.json) and [exact membership](manifest.json).\n\n')
        handle.write('Pseudo-positive frames with a potentially tile-clipped accepted sign box are excluded entirely. The raw mining JSON remains in `pseudo-records.jsonl.gz`; hash each line without its newline to recover the recorded per-frame digest. A boundary coincidence may conservatively exclude a valid full-view box. This filter cannot recover a full box suppressed by a higher-scoring fragment.\n\n')
        handle.write('The broad classifier `lanes` category is also excluded at frame admission: a targeted visual check found a lane-layout board. This conservatively follows the requested exclusion of direction boards.\n\n')
        handle.write('## Early visual quality spot-check\n\nThe assistant inspected 48 positive crops and 12 pseudo-negative scenes. One positive crop exposed the tile-boundary defect addressed above. These checks do not certify complete labels, pseudo-label precision or missed-sign recall.\n\n')
        for path in sorted((overlay/'early-quality-review').glob('*-0*.jpg')):
            handle.write(f'![{path.stem}](early-quality-review/{path.name})\n\n')
    additions=json.loads((overlay/'teacher-additions.json').read_text())
    scope=json.loads((overlay/'final-scope-review/assessment.json').read_text())
    with (overlay/'README.md').open('a') as handle:
        handle.write('\n## Final scope and localization audit\n\nA 24-crop sample of teacher additions exposed a supplementary plate misclassified as a town sign, a partial multi-chevron board, and a primary sign combined with a lower plate. The assistant then inspected all 112 retained proposals in the implicated town/rectangular categories and contextual crops. The audited admission list excludes 61 complete frames rather than turning missing positives into background labels. Some ambiguous town-exit/direction cases are conservatively withheld; this does not redefine the product taxonomy. Other pseudo-labels remain weak and incompletely reviewed.\n\n')
        handle.write('[Initial sample and assessments](pre-admission-additions-review/assessment.json) · [Focused audit decisions](final-scope-review/assessment.json) · [Frozen frame exclusions](recipe/manual_scope_exclusions.json)\n\n')
        for path in sorted((overlay/'final-scope-review').glob('scope-*.jpg')):
            handle.write(f'![Focused scope audit: {path.stem}](final-scope-review/{path.name})\n\n')
        handle.write(f"After admission, {additions['additional_proposal_boxes']} retained teacher boxes on {additions['frames_with_additional_proposals']} images have IoU below 0.5 with every valid existing source sign box. {additions['additional_frames_with_mapillary_candidates']} of those images also have class-blind Mapillary candidates. These are additional proposals, not a verified count of new physical signs or evidence that Mapillary caused their discovery. See [proposal audit](teacher-additions.json).\n")
    inventory(root,overlay,'dataset',PREFIX+'/manifest.json',ROOT/'dataset-publication-inventory.json')


def definition():
    receipt=json.loads((JOB/'publication-receipts/expanded-dataset-v1.json').read_text())
    assert receipt['postverification'] and receipt['private'] and receipt['repo_type']=='dataset'
    assert receipt['prefix']==PREFIX+'/'
    overlay=ROOT/'dataset'/PREFIX;manifest=json.loads((overlay/'manifest.json').read_text())
    assert receipt['manifest']['sha256']==sha(overlay/'manifest.json')
    closure=json.loads((ROOT/'image-reference-verification.json').read_text())
    assert closure['postverification'] and closure['revision']==receipt['revision']
    assert closure['verified_images']==len(manifest['frames'])
    assert closure['inventory_sha256']==sha(overlay/'image-reference-inventory.json')
    parent=ROOT/'parent-d6-definition.json'
    assert sha(parent)=='64c6190da298fdc0825e51563feb16d0b29f4e27a4bd0402518c122f89d9c7fa'
    value=deepcopy(json.loads(parent.read_text()))
    counts=json.loads((overlay/'training-counts.json').read_text())
    value.update(build='d7',status='frozen_before_training',
        experiment='150-epoch full eligible source expansion with explicit teacher pseudo-labels',
        definition_frozen_at_utc=datetime.now(timezone.utc).isoformat(),
        parent={'build':'d6','revision':'c17103f5e02bb3738c3ade6a3df508eb3a2f3547','definition_sha256':sha(parent)},
        dataset_revision=receipt['revision'],manifest_path=PREFIX+'/manifest.json',
        manifest_sha256=sha(overlay/'manifest.json'),batch=16,
        script_sha256=sha(ROOT/'recipe/train_mixed.py'),amp=True,
        training_images=counts['train']['images'],development_images=counts['validation']['images'],
        training_counts=counts,
        initialization='d4',scratch=False,
        initialization_rationale='Preserve the sign-pretrained YOLO26n lineage and isolate expanded data. d4 transfer was the selected pilot initialization; no evidence justifies discarding pretrained features.',
        test_usage='Consumed pilot test retained as provenance only; no new inference. Additional93 metadata-qualified geographic images and sequence/500m buffers are reserved and unreviewed.',
        pseudo_policy_sha256=sha(ROOT/'pseudo-policy.json'),
        admission_recipe_sha256=sha(ROOT/'recipe/pseudo_admission.py'),
        geographic_reserve_sha256=sha(ROOT/'final-geographic-reserve.json'),
        source_image_closure_sha256=sha(ROOT/'image-reference-verification.json'),
        optimizer='AdamW',weight_decay=.0005,warmup_epochs=2,final_lr_fraction=.1,
        augmentation={'mosaic':.25,'close_mosaic':5,'mixup':0,'fliplr':0,'flipud':0,'degrees':2,'translate':.05,'scale':.25,'hsv_h':.01,'hsv_s':.3,'hsv_v':.3},
        runtime={'image':'sha256:886be2a4e18d52e587acf3ebfeaa7cbf2da92c1c26d2355e83b94217c474faca','ultralytics':'8.4.56','torch':'2.6.0+cu126','gpu':'KI GPU0 RTX A5000','network':'none','amp_check':'native Ultralytics check using pinned local yolo26n.pt'},
        limitations=['Pseudo-labels are neither exhaustive nor human-certified.','Development set has only17 model-assisted images and has been reused.','Core Image/Core ML numerical parity and phone latency remain unmeasured.','Recovered baseline exposure is incomplete; upstream and classifier exposure are unknown.','Whole-frame development AP selects the checkpoint; phone-window comparison is post-selection.'],
        deployment='No native model export or device/production deployment.')
    root=ROOT/'definition-publication';model=root/'detector/d7';model.mkdir(parents=True,exist_ok=False)
    write(model/'definition.json',value)
    (model/'recipe').mkdir();(model/'provenance').mkdir()
    for file in sorted((ROOT/'recipe').glob('*.py')):shutil.copy2(file,model/'recipe'/file.name)
    for path in [parent,ROOT/'image-reference-verification.json',ROOT/'final-geographic-reserve.json',ROOT/'pseudo-policy.json']:
        shutil.copy2(path,model/'provenance'/path.name)
    shutil.copy2(overlay/'manifest.json',model/'provenance/training-manifest.json')
    smoke=ROOT/'synthetic-amp-final-recipe'
    smoke_config=json.loads((smoke/'configuration.json').read_text())
    assert smoke_config['script_sha256']==value['script_sha256'] and smoke_config['amp_enabled'] is True
    shutil.copy2(smoke/'configuration.json',model/'provenance/synthetic-amp-smoke-configuration.json')
    shutil.copy2(smoke/'seal.json',model/'provenance/synthetic-amp-smoke-seal.json')
    inventory(root,model,'model','detector/d7/definition.json',ROOT/'definition-publication-inventory.json')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation',choices=['dataset','definition'])
    globals()[parser.parse_args().operation]()
