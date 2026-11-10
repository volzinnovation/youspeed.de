#!/usr/bin/env python3
"""Freeze an unresolved-label review supplement without classifier predictions."""
from collections import Counter,defaultdict
from datetime import datetime
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.tsr import prepare_de_field_evaluation as base


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--intake',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--supplement',type=Path,required=True)
    args=parser.parse_args();out=args.output;out.mkdir(parents=True,exist_ok=True)
    assert not (out/'selection-frozen.json').exists()
    data=json.loads((args.intake/'snapshot.json').read_text());selection=json.loads((args.intake/'selection-frozen.json').read_text())
    old=json.loads((args.intake/'historical-manifest.json').read_text());extra=json.loads(args.supplement.read_text())
    catalog,models=base.load_catalogs()
    known_pictures={str(r['source_id']) for r in old['samples'] if r.get('source_id')}|{r['picture_id'] for r in extra['samples']}
    known_hashes={r['sha256'] for r in old['samples']+extra['samples']}
    known_routes={c for r in extra['samples'] for c in r['collection_ids']+r['sequence_ids']}
    positions=[]
    for r in data['exposed_picture_metadata']:
        known_routes.update(base.collections(r['collections']))
        if base.coord(r['gps']):positions.append(base.coord(r['gps']))
    # Preserve every previously disallowed route, then propagate exclusions from
    # all unresolved records before sampling any of them.
    blocked={x for r in json.loads((args.intake/'excluded-candidates.json').read_text()) for x in r['route_tokens']}
    candidates=[];excluded=Counter();parents={}
    def find(x):
        while parents[x]!=x:parents[x]=parents[parents[x]];x=parents[x]
        return x
    def union(a,b):parents[find(b)]=find(a)
    for r in data['panoramax']:
        if r.get('geographic_country')!='DE':continue
        q=base.resolve_crop_labels(r['labels'],catalog,model_labels=models)
        if q['status']=='unique' and q.get('country')=='DE':continue
        routes=['collection:'+x for x in base.collections(r['collections'])]
        for route in routes:parents.setdefault(route,route)
        for route in routes[1:]:union(routes[0],route)
        pos=base.coord(r['gps']);reasons=[]
        if not routes:reasons.append('missing_route')
        if not pos:reasons.append('missing_position')
        if r['picture_id'] in known_pictures or r['digest'] in known_hashes:reasons.append('known_identity')
        if any(x.removeprefix('collection:') in known_routes or x in blocked for x in routes):reasons.append('known_excluded_route')
        if pos and any(base.distance(pos,x)<=base.BUFFER_M for x in positions):reasons.append('within_200m_exposure')
        if datetime.fromisoformat(r['captured_at'].replace('Z','+00:00'))<datetime.fromisoformat(base.CUTOFF):reasons.append('before_cutoff')
        if reasons:blocked.update(routes)
        row={'source':'panoramax','crop_id':r['crop_id'],'picture_id':r['picture_id'],
             'digest':r['digest'],'captured_at':r['captured_at'],'coordinates':pos,'route_tokens':routes,
             'width':r['width'],'height':r['height'],'sign_box':r['geometry']['sign_in_crop'],
             'geometry':r['geometry'],'fingerprint':r['fingerprint'],'item_fingerprint':r['item_fingerprint'],
             'proposed_label':None,'label_provenance':'unresolved_or_ambiguous_source_tags_hidden',
             'truth_label':None,'truth_status':'unadjudicated','resolution_status':q['status']}
        candidates.append((row,reasons))
    members=defaultdict(set)
    for route in parents:members[find(route)].add(route)
    blocked_components={find(route) for route in parents if route in blocked}
    eligible=[]
    for row,reasons in candidates:
        if row['route_tokens'] and find(row['route_tokens'][0]) in blocked_components:reasons.append('connected_route_excluded')
        if reasons:excluded.update(set(reasons));continue
        group=members[find(row['route_tokens'][0])]
        row['route_component']='open-route-'+base.stable(*sorted(group))[:24]
        row['route_component_members']=sorted(group);eligible.append(row)
    def sample(rows,n,tag):
        groups=defaultdict(list)
        for row in rows:groups[row['route_component']].append(row)
        for group in groups:groups[group].sort(key=lambda r:base.stable(tag,'crop',r['crop_id']))
        order=sorted(groups,key=lambda r:base.stable(tag,'route',r));result=[];depth=0
        while len(result)<n:
            before=len(result)
            for group in order:
                if depth<len(groups[group]) and len(result)<n:result.append(groups[group][depth])
            if len(result)==before:break
            depth+=1
        return result
    random=sample(eligible,24,'open-random-v1');chosen={r['crop_id'] for r in random}
    wide=[]
    for row in eligible:
        b=row['sign_box'];w,h=b[2]-b[0],b[3]-b[1]
        if row['crop_id'] not in chosen and 1.15<=w/h<=5 and w>=24 and h>=16:wide.append(row)
    screen=sample(wide,96,'yellow-wide-screen-v1')
    selected=[]
    for prefix,rows,reason in [('R',random,'deterministic_route_diverse_random_unresolved'),('Y',screen,'geometry_only_wide_rectangle_screen')]:
        for index,row in enumerate(rows,1):
            item=dict(row,blind_id=f'{prefix}{index:03d}',sample_id='open-'+base.stable(row['crop_id'])[:20],selection_reason=reason)
            selected.append(item)
    payload={'schema':'de-open-set-selection-v1','classes':selection['classes'],'samples':selected,
        'snapshot_sha256':base.sha(args.intake/'snapshot.json'),'historical_manifest_sha256':base.sha(args.intake/'historical-manifest.json'),
        'source_supplement_sha256':base.sha(args.supplement),'fresh_capture_cutoff':base.CUTOFF,
        'known_exposure_buffer_m':base.BUFFER_M,'eligible_unresolved_crops':len(eligible),
        'eligible_unresolved_routes':len({r['route_component'] for r in eligible}),
        'eligible_wide_crops':len(wide),'random_review_count':len(random),'geometry_screen_count':len(screen),
        'selection_uses_predictions':False,'no_candidate_models_run':True,
        'yellow_screen_rule_frozen_before_pixels':'After retrieval, RGB sign pixels resized64x64: fraction with R>=100,G>=90,B<=0.8*min(R,G),R/G in[0.7,1.6] >=0.15. All passes are review candidates, never automatic city labels.',
        'excluded_record_reason_counts_nonexclusive':dict(excluded),'script_sha256':base.sha(__file__),
        'limitations':['Geographic-DE unresolved source labels selected independently of classifier outputs, but detector/capture selection remains.',
            'Random24 is route-diverse conditional on eligibility, not an unbiased road prevalence sample.',
            'Yellow-wide selection enriches possible town/direction signs and cannot estimate prevalence.',
            'All labels require user adjudication; no town class is inferred from color or shape.',
            'Original120 and benchmark96 remain byte-for-byte unchanged.']}
    base.dump(out/'selection-frozen.json',payload);base.dump(out/'eligible-unresolved-crops.json',eligible)
    print(json.dumps({k:payload[k] for k in ['eligible_unresolved_crops','eligible_unresolved_routes','eligible_wide_crops','random_review_count','geometry_screen_count']},indent=2))


if __name__=='__main__':main()
