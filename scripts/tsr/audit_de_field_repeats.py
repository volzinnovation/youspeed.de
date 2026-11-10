#!/usr/bin/env python3
"""Audit repeat encounters without labels or classifier predictions.

Conservative route blocks are not a count of independent physical signs.
Appearance+GPS edges are candidates requiring human duplicate adjudication.
"""
from collections import Counter,defaultdict
import argparse
import hashlib
import json
from pathlib import Path
import sys
from PIL import Image,ImageOps

ROOT=Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from scripts.tsr.prepare_de_field_evaluation import distance


class Components:
    def __init__(self, ids):self.parent={x:x for x in ids}
    def find(self,x):
        while self.parent[x]!=x:self.parent[x]=self.parent[self.parent[x]];x=self.parent[x]
        return x
    def union(self,a,b):self.parent[self.find(b)]=self.find(a)
    def groups(self):
        result=defaultdict(list)
        for x in self.parent:result[self.find(x)].append(x)
        return sorted([sorted(v) for v in result.values()],key=lambda x:x[0])


def dhash(path):
    with Image.open(path) as im:
        values=list(ImageOps.grayscale(im).resize((9,8),Image.Resampling.BILINEAR).getdata())
    result=0
    for y in range(8):
        for x in range(8):result=(result<<1)|int(values[y*9+x]>values[y*9+x+1])
    return result


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('intake',type=Path);args=parser.parse_args()
    manifest=args.intake/'evaluation-blind.json';data=json.loads(manifest.read_text())
    rows={r['blind_id']:r for r in data['samples']};ids=sorted(rows)
    assert len(ids)==120
    route=Components(ids);physical=Components(ids);visual=Components(ids)
    hashes={i:dhash(args.intake/rows[i]['blind_path']) for i in ids}
    edges=[];route_edges=[];exact=[]
    for n,a in enumerate(ids):
        for b in ids[n+1:]:
            ra,rb=rows[a],rows[b];meters=distance(ra['coordinates'],rb['coordinates'])
            ham=(hashes[a]^hashes[b]).bit_count()
            same_route=ra['route_component']==rb['route_component']
            same_pixels=ra['sign_rgb_sha256']==rb['sign_rgb_sha256']
            if same_route or meters<=60 or same_pixels:
                route.union(a,b)
                if not same_route:route_edges.append({'a':a,'b':b,'distance_m':meters,'same_pixels':same_pixels})
            if same_pixels:physical.union(a,b);visual.union(a,b);exact.append([a,b])
            if meters<=60 and ham<=12:
                physical.union(a,b)
                edges.append({'a':a,'b':b,'distance_m':meters,'dhash_hamming64':ham,
                              'status':'candidate_same_sign_requires_human_confirmation'})
    # Visual observations supplied by independent review of blinded sheets.
    visual_observations=[['A001','A007','A011'],['I003','I004','I012']]
    for group in visual_observations:
        for item in group[1:]:visual.union(group[0],item);physical.union(group[0],item)
    route_groups=route.groups();candidate_groups=physical.groups();visual_groups=visual.groups()
    def named(groups,prefix):
        return [{'id':prefix+'-'+hashlib.sha256('|'.join(g).encode()).hexdigest()[:16],
                 'members':g,'representative':g[0],
                 'sources':dict(Counter(rows[i]['source'] for i in g))} for g in groups]
    report={'schema':'de-field-repeat-audit-v1','manifest_sha256':hashlib.sha256(manifest.read_bytes()).hexdigest(),
        'labels_or_predictions_used':False,'frozen_images_changed':False,'crops':120,
        'original_collection_session_components':len({r['route_component'] for r in rows.values()}),
        'conservative_route_blocks':named(route_groups,'route-block'),
        'conservative_route_block_count':len(route_groups),
        'conservative_route_blocks_by_source':{s:len({route.find(i) for i in ids if rows[i]['source']==s}) for s in ['panoramax','ios','android']},
        'route_block_rule':'Union shared collection/session, exact sign pixels, or camera/sign GPS separation<=60m. Transitive, deliberately conservative; not proof of same physical sign.',
        'cross_route_spatial_edges':route_edges,
        'exact_sign_pixel_duplicate_pairs':exact,
        'visual_repeat_observations':visual_observations,
        'visual_observation_components':named(visual_groups,'visual-component'),
        'unique_count_after_only_visual_observations':len(visual_groups),
        'candidate_physical_sign_components':named(candidate_groups,'candidate-sign'),
        'candidate_physical_sign_component_count':len(candidate_groups),
        'candidate_pair_edges':edges,
        'candidate_rule':'GPS<=60m AND grayscale horizontal64-bit dHash Hamming<=12, plus explicit blind visual repeat observations. These are candidate clusters, not certified physical-sign identities.',
        'metric_policy':[
            'Do not describe120crops as120independent signs.',
            'After user label and duplicate adjudication, report one stable representative per accepted physical-sign component, with all120 crop results only as a correlated diagnostic.',
            'Any conflicting adjudicated labels inside a candidate component require reviewing/splitting it; do not silently collapse them.',
            'Use conservative route blocks for clustered uncertainty or per-route aggregation; never count correlated routes as independent.',
            'Report per-source coverage and unsupported classes. No F1 before user approves labels.'],
        'limitations':['GPS is camera position for Panoramax and mostly vehicle position for mobile; a repeated sign may be captured beyond60m.',
            'GPS proximity can connect distinct neighboring signs; dHash can confuse similar sign classes.',
            'An independent-sign count is not established before duplicate adjudication.',
            'All phone clocks are device_unverified; historical HF route provenance remains incomplete.']}
    (args.intake/'repeat-audit.json').write_text(json.dumps(report,indent=2,allow_nan=False)+'\n')
    print(json.dumps({k:report[k] for k in ['crops','original_collection_session_components','conservative_route_block_count','conservative_route_blocks_by_source','unique_count_after_only_visual_observations','candidate_physical_sign_component_count']}))


if __name__=='__main__':main()
