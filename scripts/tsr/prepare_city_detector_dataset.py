#!/usr/bin/env python3
"""Prepare route-separated city-sign detector data from a pinned source audit.

The supported audit is produced from Panoramax current annotations AND source
history. A city class tag alone is not evidence of a manually drawn rectangle.
The adapter rechecks the unique current rectangle, city semantics, contributor
and the earliest shape-matched history event. This is source provenance, not
independent human approval or an exhaustive full-frame annotation claim.

Default full_labels_yolo mode requires exhaustive human review of all three
SGBlur classes. positive_only_frozen_sign_head explicitly admits partial frames
for the preservation-loss trainer; it NEVER writes YOLO labels or data.yaml.
Raw JPEG/PNG bytes are copied unchanged after SHA, dimensions, EXIF and decoded
pixel checks. --plan-only writes metadata without claiming image verification.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime
import hashlib
from itertools import combinations
import json
import math
from pathlib import Path
import re
import shutil

from PIL import Image

AUDIT_SCHEMA = 'youspeed-city-source-provenance-audit-v1'
SCHEMA = 'youspeed-city-detector-frames-v1'
CHECKPOINT_SHA256 = '698a70566938d25c3c1eaa49b89fc176fe2f3a20631a9a01fa56035613c7972a'
CLASS_NAMES = ['sign', 'plate', 'face']
CITY_CODES = {'city:start': 'DE:310', 'city:end': 'DE:311'}
MODES = ('full_labels_yolo', 'positive_only_frozen_sign_head')
SHA = re.compile(r'[a-f0-9]{64}\Z')
ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]*\Z')


class DatasetError(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise DatasetError(reason)


def digest(path):
    result = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            result.update(chunk)
    return result.hexdigest()


def json_digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def rectangle(shape):
    require(isinstance(shape, dict) and shape.get('type') == 'Polygon', 'shape_not_polygon')
    rings = shape.get('coordinates')
    require(isinstance(rings, list) and len(rings) == 1, 'shape_not_single_ring')
    points = rings[0]
    require(isinstance(points, list) and len(points) == 5 and points[0] == points[-1], 'shape_not_closed_rectangle')
    require(all(isinstance(p, list) and len(p) == 2 and all(type(x) in (float, int) and math.isfinite(x) for x in p) for p in points), 'shape_nonfinite')
    x1, y1 = min(p[0] for p in points), min(p[1] for p in points)
    x2, y2 = max(p[0] for p in points), max(p[1] for p in points)
    require(x1 < x2 and y1 < y2 and set(map(tuple, points[:-1])) == {(x1,y1),(x1,y2),(x2,y1),(x2,y2)}, 'shape_not_axis_aligned_rectangle')
    return [x1, y1, x2, y2]


def manual_box(record, verified_human_actor_ids=None):
    """Validate source-history manual geometry; do not elevate it to human QA."""
    require(record.get('class_id') in CITY_CODES, 'not_city_class')
    code = CITY_CODES[record['class_id']]
    require(record.get('source_code') == code, 'source_code_conflict')
    contract = record.get('coordinate_contract', {})
    require(contract == {'transform':'registered-raster-identity', 'exif_orientation':1, 'projection':'flat', 'wrap':False}, 'ambiguous_coordinate_contract')
    require(record.get('geometry_provenance') == 'source_history_manual_box', 'geometry_not_source_history_manual')
    require(record.get('bbox_matches_original_box') is True, 'not_original_annotation_box')
    annotation_id = record.get('annotation_id')
    require(isinstance(annotation_id, str) and annotation_id, 'missing_annotation_id')
    require(record.get('current_shape_annotation_ids') == [annotation_id], 'nonunique_shape_binding')
    current = [a for a in record.get('all_current_annotations', []) if a.get('id') == annotation_id]
    require(len(current) == 1, 'current_annotation_missing_or_duplicated')
    bbox = rectangle(current[0].get('shape'))
    require(bbox == record.get('bbox_xyxy'), 'bbox_differs_from_current_annotation')
    size = record.get('registered_dimensions')
    require(isinstance(size, list) and len(size) == 2 and all(type(n) is int and n > 0 for n in size), 'invalid_registered_dimensions')
    require(0 <= bbox[0] < bbox[2] <= size[0] and 0 <= bbox[1] < bbox[3] <= size[1], 'bbox_outside_registered_raster')
    semantics = current[0].get('semantics', [])
    require({s.get('value') for s in semantics if s.get('key') == 'osm|traffic_sign'} == {code}, 'current_city_semantics_conflict')
    machine_key = lambda key: isinstance(key, str) and ('detection_model' in key or 'classification_model' in key)
    require(not any(machine_key(s.get('key')) for s in semantics), 'current_model_qualified_annotation')
    require(not record.get('machine_origin_events'), 'machine_geometry_history')
    history = record.get('matched_source_history', [])
    require(isinstance(history, list) and history, 'manual_history_missing')
    require(all(isinstance(h.get('ts'), str) and h['ts'] for h in history), 'history_timestamp_missing')
    def timestamp(event):
        try:
            raw=event['ts'].replace('Z','+00:00')
            # PostgreSQL removes trailing fractional zeros; Python3.9 only
            # accepts three or six fractional digits in fromisoformat.
            raw=re.sub(r'\.(\d{1,6})(?=[+-]\d\d:\d\d$)',lambda m:'.'+m.group(1).ljust(6,'0'),raw)
            value=datetime.fromisoformat(raw)
            require(value.tzinfo is not None,'history_timestamp_without_timezone')
            return value.timestamp()
        except (ValueError,TypeError) as error:
            raise DatasetError('invalid_history_timestamp') from error
    earliest = min(history, key=timestamp)
    updates = earliest.get('updates', [])
    require(updates and all(rectangle(u.get('annotation_shape')) == bbox for u in updates), 'history_shape_conflict')
    require(not any(machine_key(u.get('key')) for u in updates), 'earliest_event_is_model_qualified')
    require(any(u.get('action') == 'add' and u.get('key') == 'osm|traffic_sign' and u.get('value') == code for u in updates), 'earliest_event_not_manual_city_creation')
    actor = earliest.get('account_id')
    contributor_match=(record.get('manual_box_actor_matches_picture_contributor') is True
                       and actor and actor == record.get('picture_contributor', {}).get('id'))
    actor_verified=contributor_match if verified_human_actor_ids is None else actor in verified_human_actor_ids
    require(actor_verified, 'manual_actor_not_verified_contributor')
    return {'annotation_id':annotation_id, 'class_id':record['class_id'], 'detector_class_id':0,
            'bbox_xyxy':bbox, 'bbox_source':'manual_geometry', 'source_code':code,
            'independent_human_review':False,
            'provenance':{'origin':'source_history_manual_box', 'actor_id':actor, 'history_timestamp':earliest['ts'],
                          'history_sha256':json_digest(history), 'current_annotation_sha256':json_digest(current[0]),
                          'method':'unique_current_rectangle_and_earliest_shape_matched_city_creation'}}


def frames_from_audit(audit, image_path_template=None, actor_evidence=None):
    require(audit.get('schema') == AUDIT_SCHEMA, 'unsupported_source_audit_schema')
    require(SHA.fullmatch(audit.get('source_snapshot_sha256', '')) is not None, 'unpinned_source_snapshot')
    actors=None
    if actor_evidence is not None:
        require(actor_evidence.get('schema')=='youspeed-city-manual-actor-evidence-v1', 'unsupported_actor_evidence')
        require(SHA.fullmatch(actor_evidence.get('source_sha256','')) is not None, 'unpinned_actor_source')
        actors=set(actor_evidence.get('verified_human_actor_ids',[]))
        accounts={a['id'] for a in actor_evidence.get('accounts',[]) if isinstance(a,dict) and a.get('id') and a.get('name')}
        require(actors and actors <= accounts,'verified_actor_not_in_source_accounts')
        require(actor_evidence.get('machine_annotation_account',{}).get('id') not in actors,'machine_account_declared_human')
    frames = {}
    for row in audit.get('records', []):
        picture = row.get('picture_id')
        require(isinstance(picture, str) and ID.fullmatch(picture) is not None, 'invalid_picture_id')
        asset = row.get('source_asset') or {}
        sha = row.get('source_asset_sha256')
        require(isinstance(sha, str) and SHA.fullmatch(sha) is not None and sha == asset.get('sha256'), 'source_image_hash_missing_or_conflicting')
        dimensions = row.get('registered_dimensions')
        require(isinstance(dimensions, list) and len(dimensions) == 2 and all(type(x) is int and x > 0 for x in dimensions), 'invalid_registered_dimensions')
        sequences = row.get('sequence_ids')
        require(isinstance(sequences, list) and sequences and all(isinstance(s, str) and s for s in sequences), 'missing_route_identity')
        path = image_path_template.format(picture_id=picture, sha256=sha) if image_path_template else asset.get('relative_path')
        require(isinstance(path, str) and path and not Path(path).is_absolute() and '..' not in Path(path).parts, 'unsafe_source_image_path')
        frame = frames.setdefault(picture, {'image_id':picture, 'picture_id':picture, 'image_path':path,
            'image_sha256':sha, 'width':dimensions[0], 'height':dimensions[1], 'exif_orientation':1,
            'sequence_id':sorted(sequences)[0], 'sequence_ids':sorted(set(sequences)),
            'gps':row.get('gps'), 'physical_sign_ids':[], 'annotation_complete':False,
            'independent_human_review':False, 'boxes':[], 'rejected_boxes':[],
            'source_snapshot_sha256':audit['source_snapshot_sha256']})
        require((frame['image_sha256'],frame['width'],frame['height'],frame['image_path']) == (sha,*dimensions,path), 'same_picture_has_conflicting_source_rasters')
        frame['sequence_ids'] = sorted(set(frame['sequence_ids']) | set(sequences))
        frame['physical_sign_ids'] = sorted(set(frame['physical_sign_ids']) | set(row.get('physical_sign_ids', [])))
        try:
            box = manual_box(row,actors)
            require(box['annotation_id'] not in {b['annotation_id'] for b in frame['boxes']}, 'duplicate_annotation_record')
            frame['boxes'].append(box)
        except DatasetError as error:
            frame['rejected_boxes'].append({'annotation_id':row.get('annotation_id'), 'class_id':row.get('class_id'),
                'bbox_xyxy':row.get('bbox_xyxy'), 'geometry_provenance':row.get('geometry_provenance'), 'reason':str(error)})
        # The audit cannot establish all-sign/plate/face completeness. Do not
        # accept a copied approval/completeness boolean as new human evidence.
    require(frames, 'empty_source_audit')
    return [frames[key] for key in sorted(frames)]


def identities(frame):
    tokens = set()
    for key in ('picture_id', 'image_id'):
        if frame.get(key): tokens.add('picture:' + str(frame[key]))
    for key in ('image_sha256', 'source_image_sha256', 'rgb_sha256'):
        if frame.get(key): tokens.add(('rgb:' if key == 'rgb_sha256' else 'bytes:') + str(frame[key]))
    for key in ('sequence_id', 'collection_id'):
        if frame.get(key): tokens.add('sequence:' + str(frame[key]))
    for key in ('sequence_ids', 'collection_ids'):
        tokens.update('sequence:' + str(value) for value in frame.get(key, []))
    for key in ('route_group', 'group_id'):
        if frame.get(key): tokens.add('route:' + str(frame[key]))
    tokens.update('route:' + str(value) for value in frame.get('route_ids', []))
    for value in frame.get('route_tokens', []):
        tokens.add('sequence:' + value.split(':',1)[1] if value.startswith('collection:') else 'route:' + value)
    for key in ('physical_sign_id',):
        if frame.get(key): tokens.add('sign:' + str(frame[key]))
    tokens.update('sign:' + str(value) for value in frame.get('physical_sign_ids', []))
    return tokens


def position(frame):
    coordinates = (frame.get('gps') or {}).get('coordinates') if isinstance(frame.get('gps'), dict) else frame.get('coordinates')
    if coordinates is None:
        if frame.get('longitude') is not None and frame.get('latitude') is not None:
            coordinates = [frame['longitude'], frame['latitude']]
        else:
            return None
    require(isinstance(coordinates, (list,tuple)) and len(coordinates) >= 2, 'invalid_coordinates')
    lon, lat = coordinates[:2]
    require(type(lon) in (int,float) and type(lat) in (int,float) and math.isfinite(lon) and math.isfinite(lat) and -180 <= lon <= 180 and -90 <= lat <= 90, 'invalid_coordinates')
    return lon, lat


def distance(a,b):
    lon1,lat1,lon2,lat2 = map(math.radians, (*a,*b))
    t=math.sin((lat2-lat1)/2)**2+math.cos(lat1)*math.cos(lat2)*math.sin((lon2-lon1)/2)**2
    return 6371000*2*math.asin(min(1,math.sqrt(t)))


class Components:
    def __init__(self,n): self.parents=list(range(n))
    def find(self,i):
        while self.parents[i] != i:
            self.parents[i]=self.parents[self.parents[i]];i=self.parents[i]
        return i
    def union(self,a,b): self.parents[self.find(b)]=self.find(a)


def verify_image(frame, images_root):
    root=Path(images_root).resolve(); path=(root/frame['image_path']).resolve()
    require(path.is_relative_to(root) and path.is_file() and not (root/frame['image_path']).is_symlink(), 'missing_or_unsafe_source_image')
    require(path.stat().st_size <= 128*1024*1024, 'source_image_too_large')
    require(digest(path) == frame['image_sha256'], 'source_image_sha256_mismatch')
    with Image.open(path) as image:
        require(image.format in ('JPEG','PNG'), 'unsupported_image_format')
        require(image.size == (frame['width'],frame['height']), 'registered_raster_dimensions_mismatch')
        require(image.getexif().get(274,1) == frame['exif_orientation'] == 1, 'source_image_not_upright')
        require(image.width*image.height <= 100_000_000, 'source_image_pixel_limit')
        pixels=image.convert('RGB')
        frame['rgb_sha256']=hashlib.sha256(pixels.tobytes()).hexdigest()
        frame['image_format']=image.format
    frame['image_verified']=True


def connect_groups(frames, protected, proximity_m):
    combined=frames+protected;components=Components(len(combined));seen={};coordinates=[]
    for i,frame in enumerate(combined):
        for token in identities(frame):
            if token in seen: components.union(i,seen[token])
            else: seen[token]=i
        coordinates.append(position(frame))
    for i,point in enumerate(coordinates):
        if point is None: continue
        for j in range(i):
            if coordinates[j] is not None and distance(point,coordinates[j]) <= proximity_m:
                components.union(i,j)
    protected_components={components.find(i) for i in range(len(frames),len(combined))}
    return combined,components,protected_components


def stratified_assignment(frames, seed):
    """Choose whole groups using annotation counts only, before model inference.

    Minimal one/two-group covers reserve both city types in each holdout; the
    remaining training groups must also cover both types. We choose the best
    80/10/10 frame/class proportion, then improve it by whole-group moves.
    Hash rank is only a deterministic tie breaker, never a seed search.
    """
    groups=defaultdict(lambda:Counter())
    for frame in frames:
        if frame['exclusion_reasons']: continue
        group=groups[frame['route_group']];group['frames']+=1
        group.update(b['class_id'] for b in frame['boxes'])
    ordered=sorted(groups,key=lambda g:hashlib.sha256((seed+'\0'+g).encode()).hexdigest())
    rank={g:i for i,g in enumerate(ordered)}
    totals=sum(groups.values(),Counter());cities=set(CITY_CODES)
    covered=lambda selected: {c for g in selected for c in cities if groups[g][c]}
    covers=[frozenset([g]) for g in ordered if covered([g])==cities]
    pure=[g for g in ordered if covered([g])!=cities]
    covers += [frozenset(pair) for pair in combinations(pure,2) if covered(pair)==cities]
    all_groups=set(groups)
    def cost(val,test):
        score=0.0
        for selected in (val,test):
            counts=sum((groups[g] for g in selected),Counter())
            score += abs(counts['frames']/totals['frames']-.1)
            score += sum(abs(counts[c]/totals[c]-.1) for c in cities)*.5
        return score
    def tie(selected):return tuple(sorted(rank[g] for g in selected))
    best=None
    for val in covers:
        for test in covers:
            if val & test or covered(all_groups-val-test)!=cities: continue
            candidate=(cost(val,test),tie(val),tie(test),val,test)
            if best is None or candidate[:3]<best[:3]:best=candidate
    if best is None:
        return {g:'train' for g in ordered},False
    _,_,_,val,test=best;val=set(val);test=set(test)
    while True:
        current=cost(val,test);moves=[]
        for group in ordered:
            if group in val or group in test:continue
            if covered(all_groups-val-test-{group})!=cities:continue
            for split in ('val','test'):
                v=val|{group} if split=='val' else val
                t=test|{group} if split=='test' else test
                score=cost(v,t)
                if score < current-1e-12:moves.append((score,rank[group],split,group))
        if not moves:break
        _,_,split,group=min(moves);(val if split=='val' else test).add(group)
    return {g:'val' if g in val else 'test' if g in test else 'train' for g in ordered},True


def prepare(audit, protected, *, mode='full_labels_yolo', seed='city-detector-v1',
            images_root=None, output=None, image_path_template=None, plan_only=False,
            proximity_m=250.0, allow_empty_protected=False, actor_evidence=None, frozen_plan=None):
    require(mode in MODES, 'unsupported_training_mode')
    require(type(proximity_m) in (float,int) and math.isfinite(proximity_m) and proximity_m >= 0, 'invalid_proximity_radius')
    protected_frames=deepcopy(protected.get('frames', protected.get('records', []))) if isinstance(protected,dict) else deepcopy(protected)
    require(isinstance(protected_frames,list) and (protected_frames or allow_empty_protected), 'protected_holdouts_required')
    require(all(isinstance(p,dict) and identities(p) for p in protected_frames), 'protected_frame_has_no_identity')
    require(mode!='positive_only_frozen_sign_head' or actor_evidence is not None,'manual_actor_evidence_required_for_partial_training')
    frames=frames_from_audit(audit,image_path_template,actor_evidence)
    _, preliminary, preliminary_protected=connect_groups(frames,protected_frames,proximity_m)
    if not plan_only:
        require(images_root is not None, 'images_root_required')
        for i,frame in enumerate(frames):
            # Do not fetch/open protected pictures merely to prepare training.
            if preliminary.find(i) not in preliminary_protected and frame['boxes'] and (
                    mode=='positive_only_frozen_sign_head' or frame['annotation_complete']):
                verify_image(frame,images_root)
    # Decoded RGB identities can reveal leakage across differently encoded files.
    combined,components,protected_components=connect_groups(frames,protected_frames,proximity_m)
    members=defaultdict(list)
    for i in range(len(combined)): members[components.find(i)].append(i)
    group_tokens={key:sorted(set().union(*(identities(combined[i]) for i in indexes))) for key,indexes in members.items()}
    # RGB hashes add duplicate links, not a new random seed for otherwise
    # unchanged groups when moving from metadata planning to byte verification.
    group_names={key:'city-route-'+json_digest([t for t in tokens if not t.startswith('rgb:')])[:24] for key,tokens in group_tokens.items()}
    pixel_groups=defaultdict(list)
    for frame in frames:
        pixel_groups[frame.get('rgb_sha256',frame['image_sha256'])].append(frame)
    for duplicates in pixel_groups.values():
        signatures={json_digest(sorted([(b['class_id'],b['bbox_xyxy']) for b in f['boxes']])) for f in duplicates}
        conflict=len(signatures)>1
        for i,frame in enumerate(sorted(duplicates,key=lambda f:f['image_id'])):
            frame['duplicate_of']=None if i==0 else min(f['image_id'] for f in duplicates)
            frame['duplicate_annotation_conflict']=conflict
    eligible_groups=set()
    for i,frame in enumerate(frames):
        component=components.find(i); reasons=[]
        if component in protected_components: reasons.append('protected_holdout_component')
        if frame['duplicate_annotation_conflict']: reasons.append('identical_pixels_have_conflicting_manual_boxes')
        if frame['duplicate_of']: reasons.append('duplicate_pixels')
        if not frame['boxes']: reasons.append('no_verified_manual_city_geometry')
        if mode=='full_labels_yolo' and not frame['annotation_complete']: reasons.append('partial_frame_not_safe_for_standard_yolo')
        frame.update(route_group=group_names[component],exclusion_reasons=reasons,training_mode=mode)
        if not reasons: eligible_groups.add(frame['route_group'])
    assignment,stratified_coverage_possible=stratified_assignment(frames,seed)
    n=len(eligible_groups)
    for frame in frames:
        frame['split']=assignment.get(frame['route_group'],'review') if not frame['exclusion_reasons'] else 'excluded'
        frame['boxes'].sort(key=lambda b:b['annotation_id'])
    if frozen_plan is not None:
        require(frozen_plan.get('schema')==SCHEMA and frozen_plan.get('mode')==mode and frozen_plan.get('seed')==seed,'frozen_plan_contract_mismatch')
        before={f['image_id']:(f['route_group'],f['split']) for f in frozen_plan['frames']}
        after={f['image_id']:(f['route_group'],f['split']) for f in frames}
        require(before==after,'verified_pixels_change_frozen_group_split_requires_new_pretraining_plan')
    counts={split:Counter(b['class_id'] for f in frames if f['split']==split for b in f['boxes']) for split in ('train','val','test')}
    report={'schema':SCHEMA,'mode':mode,'training_mode':mode,'seed':seed,'detector_checkpoint_sha256':CHECKPOINT_SHA256,'class_names':CLASS_NAMES,
        'source_audit_sha256':json_digest(audit),'source_snapshot_sha256':audit['source_snapshot_sha256'],
        'manual_actor_evidence_sha256':json_digest(actor_evidence) if actor_evidence is not None else None,
        'frozen_plan_sha256':json_digest(frozen_plan) if frozen_plan is not None else None,
        'protected_manifest_sha256':json_digest(protected),'proximity_exclusion_and_grouping_m':proximity_m,
        'split_policy':'deterministic whole-group city-class coverage; minimize 80/10/10 frame/class proportion error; hash-ranked ties; no model outputs',
        'stratified_class_coverage_possible':stratified_coverage_possible,
        'image_verification_complete':not plan_only,'standard_yolo_partial_frames_exported':False,
        'independent_human_review':False,'source_annotation_completeness':'partial',
        'training_launch_ready':not plan_only and all(counts[s][c]>0 for s in ('train','val','test') for c in CITY_CODES),
        'group_count':n,'groups_by_split':dict(Counter(assignment.values())),
        'frames_by_split':dict(Counter(f['split'] for f in frames)),
        'city_boxes_by_split':{k:dict(v) for k,v in counts.items()},
        'exclusion_counts':dict(Counter(r for f in frames for r in f['exclusion_reasons'])),
        'annotation_rejection_counts':dict(Counter(r['reason'] for f in frames for r in f['rejected_boxes'])),
        'frames_missing_coordinates':sum(position(f) is None for f in frames),
        'limitations':['Source history supports manual geometry but does not establish independent human QA.',
          'Partial annotations support known-box recall, not false-positive counts, precision, AP or F1.',
          'Positive-only mode requires the separate frozen-sign-head preservation-loss trainer; never standard YOLO training.',
          'A new dataset version can change hash-ranked splits; freeze this manifest before experiments.',
          'Unknown physical identities/coordinates and absent historical records limit independence claims.'],
        'frames':frames}
    if output is not None:
        output=Path(output);require(not output.exists(),'output_must_be_new')
        output.mkdir(parents=True)
        if not plan_only:
            for frame in frames:
                if frame['split'] not in ('train','val','test'): continue
                relative=Path('images')/frame['split']/(frame['image_id']+('.jpg' if frame['image_format']=='JPEG' else '.png'))
                destination=output/relative;destination.parent.mkdir(parents=True,exist_ok=True)
                shutil.copyfile(Path(images_root)/frame['image_path'],destination)
                require(digest(destination)==frame['image_sha256'],'copy_hash_mismatch')
                frame['source_image_path']=frame['image_path'];frame['image_path']=relative.as_posix()
                if mode=='full_labels_yolo':
                    # This source adapter never asserts completeness. Retained
                    # for an eventual separately verified exhaustive adapter.
                    require(frame['annotation_complete'] is True,'partial_frame_yolo_export_refused')
                    labels=[]
                    for b in frame['boxes']:
                        x1,y1,x2,y2=b['bbox_xyxy'];w,h=frame['width'],frame['height']
                        labels.append(f"{b['detector_class_id']} {(x1+x2)/(2*w):.9f} {(y1+y2)/(2*h):.9f} {(x2-x1)/w:.9f} {(y2-y1)/h:.9f}")
                    label=output/'labels'/frame['split']/(frame['image_id']+'.txt');label.parent.mkdir(parents=True,exist_ok=True);label.write_text('\n'.join(labels)+'\n')
        write(output/'manifest.json',report)
        for split in ('train','val','test'):
            write(output/(split+'.json'),{k:v for k,v in report.items() if k!='frames'} | {'frames':[f for f in frames if f['split']==split]})
        if mode=='full_labels_yolo' and report['training_launch_ready']:
            (output/'data.yaml').write_text('path: '+json.dumps(str(output.resolve()))+'\ntrain: images/train\nval: images/val\ntest: images/test\nnames: [sign, plate, face]\n')
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--audit',type=Path,required=True);p.add_argument('--audit-sha256',required=True)
    p.add_argument('--protected',type=Path,required=True);p.add_argument('--protected-sha256',required=True)
    p.add_argument('--actor-evidence',type=Path);p.add_argument('--actor-evidence-sha256')
    p.add_argument('--frozen-plan',type=Path);p.add_argument('--frozen-plan-sha256')
    p.add_argument('--images-root',type=Path);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--mode',choices=MODES,default=MODES[0]);p.add_argument('--seed',default='city-detector-v1')
    p.add_argument('--image-path-template',help='Optional path e.g. {picture_id}.jpg; source bytes still SHA verified')
    p.add_argument('--plan-only',action='store_true');p.add_argument('--proximity-m',type=float,default=250)
    a=p.parse_args();require(digest(a.audit)==a.audit_sha256,'audit_file_hash_mismatch');require(digest(a.protected)==a.protected_sha256,'protected_file_hash_mismatch')
    require(bool(a.actor_evidence)==bool(a.actor_evidence_sha256),'actor_evidence_requires_path_and_digest')
    actors=None
    if a.actor_evidence:
        require(digest(a.actor_evidence)==a.actor_evidence_sha256,'actor_evidence_hash_mismatch')
        actors=json.loads(a.actor_evidence.read_text())
    require(bool(a.frozen_plan)==bool(a.frozen_plan_sha256),'frozen_plan_requires_path_and_digest')
    frozen=None
    if a.frozen_plan:
        require(digest(a.frozen_plan)==a.frozen_plan_sha256,'frozen_plan_hash_mismatch');frozen=json.loads(a.frozen_plan.read_text())
    report=prepare(json.loads(a.audit.read_text()),json.loads(a.protected.read_text()),mode=a.mode,seed=a.seed,images_root=a.images_root,output=a.output,image_path_template=a.image_path_template,plan_only=a.plan_only,proximity_m=a.proximity_m,actor_evidence=actors,frozen_plan=frozen)
    report['input_files']={'audit':{'sha256':a.audit_sha256},'protected':{'sha256':a.protected_sha256},'script_sha256':digest(Path(__file__))}
    write(a.output/'manifest.json',report)
    print(json.dumps({k:v for k,v in report.items() if k not in ('frames','limitations')},indent=2))


if __name__=='__main__': main()
