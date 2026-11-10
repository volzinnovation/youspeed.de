#!/usr/bin/env python3
"""Append four audited generic supplementary plates to frozen v2, without relabels."""
from __future__ import annotations
import argparse
from collections import Counter
from copy import deepcopy
from pathlib import Path
import shutil
import de_expanded_classifier as pipeline
import merge_de_expanded_intake_v2 as grouping

PARENT_SHA='46e6a0bb26f02ea58e8f2d83c2f390a49eaf41d0449fce4d4f28b5e4c4fa7b1d'
SUPPLEMENT_SHA='9c2800d95318ad07df7bfccdaa4fed2d3e170411848540df700fc64e819df35c'
PIPELINE_SHA='2c9326287ebf5ac8790bbca66398e0bf0cfcdd63345ea305eb681570ccc2e282'
GROUPING_SHA='2e7220be5124fe78efa86b16ef0991a055e4d8dd3efe914955eaa403d8da672a'
CLASS_SHA='c15f6076f790ca9346c438cf6543f883e4587328d19d746078758c259d978d9b'


def select_plates(rows):
    selected=deepcopy([r for r in rows if r.get('label')=='supplementary:plate'])
    if {r['sample_id'] for r in selected}!={f'municipal-v1-M{i:03}' for i in range(1,5)} or len(selected)!=4:
        raise ValueError('Exactly the four audited municipal plate IDs are required')
    for r in selected:
        if (r.get('class_id')!='supplementary:plate' or r.get('label_origin')!='assistant_visual_silver'
            or r.get('human_approved') is not False or r.get('human_reviewed') is not False
            or not r.get('training_only') or r.get('evaluation_eligible') is not False
            or r.get('exact_code_inferred') is not False or r.get('restriction_semantics')!='unknown'):
            raise ValueError('Preserve generic-family silver TRAIN-only truth scope')
    if len({r['physical_site_group'] for r in selected})!=3 or len({r['physical_sign_id'] for r in selected})!=4:
        raise ValueError('Physical sign/post counts differ')
    return selected


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['parent','supplement','classes','historical','output']:p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--fresh',type=Path,nargs='+',required=True);a=p.parse_args()
    if a.output.exists():raise ValueError('Use a new immutable v3 directory')
    for path,expected in [(a.parent,PARENT_SHA),(a.supplement,SUPPLEMENT_SHA),(a.classes,CLASS_SHA),
                          (Path(pipeline.__file__),PIPELINE_SHA),(Path(grouping.__file__),GROUPING_SHA)]:
        if pipeline.sha(path)!=expected:raise ValueError('Frozen input/helper digest differs: '+str(path))
    parent=pipeline.read(a.parent);supplement=pipeline.read(a.supplement);classes=pipeline.read(a.classes)['classes']
    old=deepcopy(parent['samples']);new=select_plates(supplement['samples'])
    if len(old)!=27 or len(classes)!=142:raise ValueError('Expected frozen27-row parent and142 classes')
    for row in new:
        row['original_local_path']=str((a.supplement.parent/row['path']).resolve())
        row['path']=row['original_local_path'];row['visual_reason']=row['label_evidence']
        row['group_identities']=sorted(pipeline.identity_values(row)|{row['physical_site_group'],row['physical_sign_id']})
    groups=grouping.extend_groups(old,new)
    if old!=parent['samples'] or len({r['group_id'] for r in new})!=3:raise ValueError('Frozen rows or new physical groups differ')
    rows=old+new
    if len({r['sample_id'] for r in rows})!=31:raise ValueError('Sample IDs must be unique')
    a.output.mkdir(parents=True);(a.output/'images').mkdir()
    for i,row in enumerate(rows):
        source=(a.parent.parent/row['path']).resolve() if i<27 else Path(row['path'])
        if pipeline.sha(source)!=row['sha256']:raise ValueError('Source image changed')
        if i>=27:row['path']=f"images/{i:03d}-{row['sha256'][:16]}.png"
        target=a.output/row['path'];shutil.copyfile(source,target)
        if pipeline.sha(target)!=row['sha256']:raise ValueError('Copied bytes differ')
    result={**parent,'samples':rows,'intake_version':3,'parent_manifest_sha256':PARENT_SHA,
      'supplemental_intake_sha256':SUPPLEMENT_SHA,
      'source_manifests':{**parent['source_manifests'],str(a.supplement):SUPPLEMENT_SHA},
      'counts_by_class':dict(Counter(r['label'] for r in rows)),
      'counts_by_origin':dict(Counter(r['label_origin'] for r in rows)),
      'parent_materializer_sha256':parent['script_sha256'],'script_sha256':pipeline.sha(__file__),
      'grouping_helper_sha256':GROUPING_SHA,'excluded_supplement_ids':['municipal-v1-M005','municipal-v1-M006'],
      'comparison_contract':'Same142 taxonomy,10epochs and frozenprimary136 initialization; append only four generic plate training crops to frozenv2.',
      'holdout_exclusion_status':'Fresh193 route/pixel/250m and all historical VAL/TEST checks passed locally; unchanged remote preparation repeats them.'}
    manifest=a.output/'new-intake.json';pipeline.write(manifest,result);verified=pipeline.verify_new_rows(manifest,classes)
    if len(verified)!=31:raise ValueError('Duplicate decoded pixels')
    fresh=[];fresh_receipts=[]
    for path in a.fresh:
        fresh.extend(pipeline.read(path)['samples']);fresh_receipts.append({'path':str(path),'sha256':pipeline.sha(path)})
    historical=pipeline.read(a.historical)['samples'];historical_eval=[r for r in historical if r['split'] in {'val','test'}]
    retained,fresh_audit=pipeline.exclude_groups(verified,fresh)
    retained_eval,historical_audit=pipeline.exclude_groups(verified,historical_eval)
    if len(retained)!=31 or len(retained_eval)!=31:raise ValueError('Protected evaluation overlap')
    _,duplicates=pipeline.deduplicate_existing(verified,[r for r in historical if r['split']=='train'])
    if duplicates:raise ValueError('Historical training duplicate')
    train,dev,selected=pipeline.split_new_rows(verified,classes[136:])
    if len(train)!=31 or dev or selected:raise ValueError('Unapproved silver escaped TRAIN-only policy')
    if rows[:27]!=parent['samples'] or pipeline.sha(a.parent)!=PARENT_SHA:raise ValueError('Frozenv2 changed')
    validation={'status':'local_checks_passed_remote_preparation_pending','manifest_sha256':pipeline.sha(manifest),
      'parent_manifest_sha256':PARENT_SHA,'v2_prefix_rows_exact':27,'v2_image_bytes_exact':27,'samples':31,
      'new_plate_rows':4,'new_physical_signs':4,'new_physical_posts':3,'new_route_groups':3,
      'real_silver_samples':26,'official_artwork_samples':5,'fresh_unique_selected_rows':len({r['sample_id'] for r in fresh}),
      'fresh_identity_pixel_geo_exclusions':sum(r['excluded'] for r in fresh_audit),
      'historical_eval_rows':len(historical_eval),'historical_evaluation_exclusions':sum(r['excluded'] for r in historical_audit),
      'historical_training_duplicates':duplicates,'all_training_only':True,'fresh_pixels_opened':False,
      'historical_eval_pixels_opened':False,'final_f1_computed':False,'historical_manifest_sha256':pipeline.sha(a.historical),
      'fresh_receipts':fresh_receipts,'pipeline_sha256':PIPELINE_SHA,'script_sha256':pipeline.sha(__file__)}
    pipeline.write(a.output/'local-exclusion-validation.json',validation)
    pipeline.write(a.output/'exclusion-audit.json',{'fresh':fresh_audit,'historical_evaluation':historical_audit})
    pipeline.write(a.output/'group-components.json',{'components':groups,'policy':'Frozen27rowgroups preserved; four new physical plates closed into three post/route groups.'})
    shutil.copyfile(__file__,a.output/'executed-materializer.py');print(__import__('json').dumps(validation))


if __name__=='__main__':main()
