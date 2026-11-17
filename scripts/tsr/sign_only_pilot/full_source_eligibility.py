#!/usr/bin/env python3
"""Inventory every source detector frame; never infer negative labels from absence."""
import argparse
from collections import Counter
import gzip
import hashlib
import json
import math
from pathlib import Path


def distance(a,b):
    lon1,lat1,lon2,lat2=map(math.radians,(*a,*b))
    v=math.sin((lat2-lat1)/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6371000*2*math.asin(min(1,math.sqrt(v)))


def run(plan,selection,output,metadata):
    import re
    with gzip.open(metadata,'rt') as handle:
        media={r['picture_id']:r for line in handle if (r:=json.loads(line)).get('task')=='detector'}
    selected=json.loads(Path(selection).read_text())
    outside={r['picture_id'] for r in selected['outside_boundary_exclusions']}
    protected=[r for r in selected['frames'] if r['split'] in ('validation','test')]
    protected_ids={r['picture_id'] for r in protected}
    protected_sequences={s for r in protected for s in r['sequence_ids']}
    protected_hashes={r.get('sha256',r.get('image_sha256')) for r in protected}
    seen={};counts=Counter();origins=Counter();files=[]
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    with gzip.open(plan,'rt') as src,gzip.open(output/'membership.jsonl.gz','wt') as out:
        for line in src:
            record=json.loads(line);row=record.get('row',{})
            if row.get('task')!='detector':continue
            annotation=record['annotation'];meta=annotation['source_metadata']
            coords=meta['picture']['geometry']['coordinates']
            sequences=[r['id'] for r in meta.get('collections',[])]
            uid=row['picture_id'];verified_media=media[uid];digest=verified_media['sha256']
            if not isinstance(digest,str) or not re.fullmatch('[0-9a-f]{64}',digest):
                raise ValueError('Missing verified image digest: '+uid)
            reasons=[]
            if uid in outside:reasons.append('outside_bw')
            if uid in protected_ids or digest in protected_hashes:reasons.append('protected_identity')
            if protected_sequences.intersection(sequences):reasons.append('protected_sequence')
            if not reasons and any(distance(coords,r['coordinates'])<500 for r in protected):reasons.append('protected_500m_buffer')
            if digest in seen:reasons.append('duplicate_bytes')
            # Prefer eligible members when identical bytes occur in several records.
            if not reasons:seen[digest]=uid
            signs=[a for a in annotation.get('annotations',[]) if a.get('label')=='sign']
            for a in signs:origins[a.get('label_origin','unknown')]+=1
            item={'picture_id':uid,'image_path':verified_media['path'],'image_sha256':digest,
                  'bytes':verified_media['bytes'],'coordinates':coords,'sequence_ids':sequences,
                  'exclusion_reasons':reasons,'candidate_for_pseudo_labeling':not reasons,
                  'fully_supervised_eligible':False,
                  'annotation_complete':annotation.get('annotation_complete',{}).get('sign',False),
                  'existing_sign_annotations':signs,
                  'label_status':'incomplete_source_annotations_not_negative_ground_truth'}
            out.write(json.dumps(item)+'\n');counts['all_source_images']+=1
            counts['in_bw']+=uid not in outside;counts['candidate_for_pseudo_labeling']+=not reasons
            counts['source_sign_boxes']+=len(signs);counts['source_complete_images']+=bool(item['annotation_complete'])
            for reason in reasons:counts[reason]+=1
    summary={'counts':dict(counts),'box_origins':dict(origins),
             'policy':'All source rows inventoried; candidate status is geographic eligibility, NOT reviewed training eligibility.',
             'protected_selection_sha256':hashlib.sha256(Path(selection).read_bytes()).hexdigest(),
             'source_plan_sha256':hashlib.sha256(Path(plan).read_bytes()).hexdigest(),
             'next_requirement':'scope-filtered teacher pseudo-labels or complete visual review; fresh holdout must be reserved before expanded training'}
    (output/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary))


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in ('plan','selection','output','metadata'):p.add_argument('--'+name,required=True)
    a=p.parse_args();run(a.plan,a.selection,a.output,a.metadata)
