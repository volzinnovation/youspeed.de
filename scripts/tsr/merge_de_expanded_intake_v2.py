#!/usr/bin/env python3
"""Append audited Panoramax crops to a byte-preserved v1 training intake."""
from __future__ import annotations
import argparse
from collections import Counter
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import de_expanded_classifier as pipeline


def extend_groups(original, additions):
    rows=original+additions
    components=[{i} for i in range(len(rows))]
    identities=[pipeline.identity_values(r) for r in rows]
    changed=True
    while changed:
        changed=False
        for i in range(len(rows)):
            for j in range(i):
                if identities[i]&identities[j] and components[i]!=components[j]:
                    component=components[i]|components[j]
                    tokens=set().union(*(identities[k] for k in component))
                    for k in component:components[k]=component;identities[k]=tokens
                    changed=True
    audit=[]
    for component in sorted({tuple(sorted(c)) for c in components}):
        old_groups={rows[i]['group_id'] for i in component if i<len(original)}
        if len(old_groups)>1:
            raise ValueError('New identity links two frozen v1 groups; explicit reconciliation required')
        tokens=set().union(*(identities[i] for i in component))
        group=next(iter(old_groups)) if old_groups else 'expanded-route-'+hashlib.sha256('\n'.join(sorted(tokens)).encode()).hexdigest()[:24]
        for i in component:
            if i>=len(original):rows[i]['group_id']=group;rows[i]['group_identities']=sorted(tokens)
        audit.append({'group_id':group,'sample_ids':[rows[i]['sample_id'] for i in component],
                      'contains_frozen_v1':bool(old_groups),'identities':sorted(tokens)})
    return audit


def main():
    p=argparse.ArgumentParser(description=__doc__)
    for name in ['parent','supplement','classes','historical','output']:
        p.add_argument('--'+name,type=Path,required=True)
    p.add_argument('--fresh',type=Path,nargs='+',required=True);a=p.parse_args()
    if a.output.exists():raise ValueError('Use a fresh immutable v2 directory')
    parent_sha=pipeline.sha(a.parent);parent=pipeline.read(a.parent);supplement=pipeline.read(a.supplement)
    classes=pipeline.read(a.classes)['classes'];historical=pipeline.read(a.historical)['samples']
    if len(parent['samples'])!=22 or len(supplement['samples'])!=5:raise ValueError('Expected frozen22 + audited5')
    if parent['class_index_sha256']!=pipeline.sha(a.classes) or len(classes)!=142:
        raise ValueError('Frozen142-class index differs')
    old=deepcopy(parent['samples']);new=deepcopy(supplement['samples'])
    for row in new:
        if row['label']!='bus:stop' or row.get('human_approved') is not False or not row.get('training_only') or row.get('evaluation_eligible') is not False:
            raise ValueError('New rows must remain unapproved bus-stop TRAIN-only silver')
        row.update(label_origin='assistant_visual_silver',label_source='assistant_visual_silver',human_reviewed=False,
                   visual_reason=row['label_evidence'],label_confidence='clear_visual',original_local_path=row['path'])
        row['group_identities']=sorted(pipeline.identity_values(row)|{row['physical_site_group']})
    groups=extend_groups(old,new)
    if old!=parent['samples']:raise ValueError('Frozen v1 row content changed')
    ids=[r['sample_id'] for r in old+new]
    if len(set(ids))!=27:raise ValueError('Duplicate sample identities')
    # Copy identical v1 relative names/bytes. Only new rows receive new paths.
    a.output.mkdir(parents=True);(a.output/'images').mkdir()
    for i,row in enumerate(old+new):
        source=(a.parent.parent/row['path']).resolve() if i<len(old) else Path(row['path']).resolve()
        if pipeline.sha(source)!=row['sha256']:raise ValueError('Input image digest differs')
        if i>=len(old):row['path']=f"images/{i:03d}-{row['sha256'][:16]}.png"
        target=a.output/row['path'];target.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(source,target)
        if pipeline.sha(target)!=row['sha256']:raise ValueError('Copied image differs')
    result={**parent,'samples':old+new,'intake_version':2,'parent_manifest_sha256':parent_sha,
            'supplemental_intake_sha256':pipeline.sha(a.supplement),
            'source_manifests':{**parent['source_manifests'],str(a.supplement):pipeline.sha(a.supplement)},
            'counts_by_class':dict(Counter(r['label'] for r in old+new)),
            'counts_by_origin':dict(Counter(r['label_origin'] for r in old+new)),
            'parent_materializer_sha256':parent['script_sha256'],'script_sha256':pipeline.sha(__file__),
            'holdout_exclusion_status':'Local fresh193 identity/pixel/250m and all historical VAL/TEST exclusions passed; remote preparation must repeat.',
            'comparison_contract':'Same142 taxonomy and frozen136 initialization as v1; only five audited bus-stop training crops appended.'}
    manifest=a.output/'new-intake.json';pipeline.write(manifest,result)
    verified=pipeline.verify_new_rows(manifest,classes)
    if len(verified)!=27:raise ValueError('Decoded duplicate pixels removed a row')
    fresh=[];fresh_receipts=[]
    for path in a.fresh:
        fresh.extend(pipeline.read(path)['samples']);fresh_receipts.append({'path':str(path),'sha256':pipeline.sha(path)})
    kept,fresh_audit=pipeline.exclude_groups(verified,fresh)
    historical_eval=[r for r in historical if r['split'] in {'val','test'}]
    kept_eval,historical_audit=pipeline.exclude_groups(verified,historical_eval)
    if len(kept)!=27 or len(kept_eval)!=27:raise ValueError('Protected evaluation overlap; v2 not eligible')
    _,duplicate_ids=pipeline.deduplicate_existing(verified,[r for r in historical if r['split']=='train'])
    if duplicate_ids:raise ValueError('Historical TRAIN duplicate detected')
    newtrain,newdev,selected=pipeline.split_new_rows(verified,classes[136:])
    if len(newtrain)!=27 or newdev or selected:raise ValueError('Unapproved silver escaped TRAIN-only policy')
    if result['samples'][:22]!=parent['samples'] or pipeline.sha(a.parent)!=parent_sha:
        raise ValueError('Frozen v1 changed during merge')
    validation={'status':'local_checks_passed_remote_preparation_pending','manifest_sha256':pipeline.sha(manifest),
      'parent_manifest_sha256':parent_sha,'v1_prefix_rows_exact':22,'v1_image_bytes_exact':22,
      'samples':27,'new_bus_stop_crops':5,'real_silver_samples':22,'official_artwork_samples':5,
      'fresh_unique_selected_rows':len({r['sample_id'] for r in fresh}),'fresh_pixel_manifest_rows':len(fresh),
      'fresh_identity_pixel_geo_exclusions':sum(r['excluded'] for r in fresh_audit),
      'historical_eval_rows':len(historical_eval),'historical_evaluation_exclusions':sum(r['excluded'] for r in historical_audit),
      'existing_historical_training_duplicates':duplicate_ids,'all_training_only':True,
      'fresh_pixels_opened':False,'historical_eval_pixels_opened':False,'final_f1_computed':False,
      'historical_manifest_sha256':pipeline.sha(a.historical),'fresh_receipts':fresh_receipts,
      'pipeline_sha256':pipeline.sha(Path(pipeline.__file__)),'script_sha256':pipeline.sha(__file__)}
    pipeline.write(a.output/'local-exclusion-validation.json',validation)
    pipeline.write(a.output/'group-components.json',{'components':groups,'policy':'Frozen22rowgroups preserved; new identities closed transitively through physical-site, source and route links.'})
    pipeline.write(a.output/'exclusion-audit.json',{'fresh':fresh_audit,'historical_evaluation':historical_audit})
    shutil.copyfile(__file__,a.output/'executed-materializer.py')
    print(json.dumps(validation))


if __name__=='__main__':main()
