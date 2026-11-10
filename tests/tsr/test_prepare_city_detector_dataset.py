"""Partial manual city boxes cannot become background labels or leaked holdouts."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path

from PIL import Image, PngImagePlugin
import pytest

from scripts.tsr import prepare_city_detector_dataset as subject


PROTECTED={'frames':[{'image_id':'unrelated-protected','sequence_id':'reserved-route'}]}

ACTORS={'schema':'youspeed-city-manual-actor-evidence-v1','source_sha256':'a'*64,
    'verified_human_actor_ids':['human-contributor'],'accounts':[{'id':'human-contributor','name':'student'}],
    'machine_annotation_account':{'id':'automated-account'}}

def prepare(*args, **kwargs):
    kwargs.setdefault('actor_evidence', ACTORS)
    return subject.prepare(*args, **kwargs)


def box_shape(box):
    x1,y1,x2,y2=box
    return {'type':'Polygon','coordinates':[[[x1,y1],[x1,y2],[x2,y2],[x2,y1],[x1,y1]]]}


def record(image_id='scene-0', index=0, *, digest='a'*64, sequence=None, class_id='city:start', bbox=None):
    bbox=bbox or ([1,1,3,4] if class_id=='city:start' else [4,1,7,4])
    annotation_id=f'{image_id}-annotation-{index}'
    code=subject.CITY_CODES[class_id];shape=box_shape(bbox)
    return {'picture_id':image_id,'annotation_id':annotation_id,'class_id':class_id,'source_code':code,
        'bbox_xyxy':bbox,'registered_dimensions':[8,6],'bbox_matches_original_box':True,
        'padded_crop_box_not_for_training':[bbox[0],bbox[1],bbox[2],6],
        'coordinate_contract':{'transform':'registered-raster-identity','exif_orientation':1,'projection':'flat','wrap':False},
        'source_asset':{'sha256':digest,'relative_path':image_id+'.png','rendition':'hd'},'source_asset_sha256':digest,
        'sequence_ids':[sequence or 'sequence-'+image_id],'gps':None,
        'current_shape_annotation_ids':[annotation_id], 'geometry_provenance':'source_history_manual_box',
        'matched_source_history':[{'ts':'2026-11-01T00:00:00+00:00','account_id':'human-contributor','updates':[
            {'key':'osm|traffic_sign','value':code,'action':'add','annotation_shape':shape},
            {'key':'osm|name','value':'Exampletown','action':'add','annotation_shape':shape}]}],
        'machine_origin_events':[], 'manual_box_actor_matches_picture_contributor':True,
        'picture_contributor':{'id':'human-contributor'},
        'all_current_annotations':[{'id':annotation_id,'shape':shape,'semantics':[{'key':'osm|traffic_sign','value':code}]}],
        'annotation_complete':False,'human_review_approval':False}


def audit(records):
    return {'schema':subject.AUDIT_SCHEMA,'source_snapshot_sha256':'e'*64,'records':records}


def example(tmp_path, n=3):
    images=tmp_path/'sources';images.mkdir()
    records=[]
    for i in range(n):
        image_id='scene-'+str(i);p=images/(image_id+'.png')
        Image.new('RGB',(8,6),(20*i,80,120)).save(p)
        sha=hashlib.sha256(p.read_bytes()).hexdigest()
        records.extend(record(image_id,k,digest=sha,class_id=c) for k,c in enumerate(subject.CITY_CODES))
    return audit(records), images


def test_partial_frames_default_excluded_without_opening_images(tmp_path):
    data,images=example(tmp_path)
    result=prepare(data,PROTECTED,images_root=tmp_path/'does-not-exist',output=tmp_path/'result')
    assert result['frames_by_split']=={'excluded':3}
    assert result['exclusion_counts']['partial_frame_not_safe_for_standard_yolo']==3
    assert result['training_launch_ready'] is False
    assert not (tmp_path/'result/data.yaml').exists()
    assert not (tmp_path/'result/images').exists()


def test_positive_only_preserves_bytes_boxes_three_classes_and_route_splits(tmp_path):
    data,images=example(tmp_path);unchanged=deepcopy(data);out=tmp_path/'result'
    result=prepare(data,PROTECTED,images_root=images,output=out,mode=subject.MODES[1])
    assert data==unchanged
    assert result['schema']==subject.SCHEMA and result['training_mode']==subject.MODES[1]
    assert result['class_names']==['sign','plate','face']
    assert result['detector_checkpoint_sha256']==subject.CHECKPOINT_SHA256
    assert result['training_launch_ready'] is True and result['image_verification_complete'] is True
    assert result['frames_by_split']=={'train':1,'val':1,'test':1}
    assert not (out/'labels').exists() and not (out/'data.yaml').exists()
    assert len({f['route_group'] for f in result['frames']})==3
    for f in result['frames']:
        assert (out/f['image_path']).read_bytes()==(images/f['source_image_path']).read_bytes()
        assert f['annotation_complete'] is False and f['independent_human_review'] is False
        assert all(b['bbox_source']=='manual_geometry' and b['detector_class_id']==0 for b in f['boxes'])
        assert f['boxes'][0]['bbox_xyxy']==[1,1,3,4] # Not the padded crop rectangle.


def test_plan_cannot_claim_verified_training_ready_or_export_pixels(tmp_path):
    data,_=example(tmp_path)
    result=prepare(data,PROTECTED,mode=subject.MODES[1],plan_only=True,output=tmp_path/'plan')
    assert result['image_verification_complete'] is False
    assert result['training_launch_ready'] is False
    assert not (tmp_path/'plan/images').exists()


@pytest.mark.parametrize('change,reason',[
    ('machine_geometry','geometry_not_source_history_manual'),
    ('shape_binding','nonunique_shape_binding'),
    ('padded_box','bbox_differs_from_current_annotation'),
    ('wrong_city','current_city_semantics_conflict'),
    ('missing_history','manual_history_missing'),
    ('machine_history','machine_geometry_history'),
    ('model_qualifier','earliest_event_is_model_qualified'),
    ('unknown_actor','manual_actor_not_verified_contributor'),
    ('orientation','ambiguous_coordinate_contract'),
    ('projection','ambiguous_coordinate_contract'),
])
def test_manual_provenance_and_coordinate_fail_closed(change,reason):
    r=record()
    if change=='machine_geometry':r['geometry_provenance']='manual_label_on_machine_box'
    elif change=='shape_binding':r['current_shape_annotation_ids'].append('another')
    elif change=='padded_box':r['bbox_xyxy']=r['padded_crop_box_not_for_training']
    elif change=='wrong_city':r['all_current_annotations'][0]['semantics'][0]['value']='DE:311'
    elif change=='missing_history':r['matched_source_history']=[]
    elif change=='machine_history':r['machine_origin_events']=[{'key':'detection_model[sgblur]'}]
    elif change=='model_qualifier':r['matched_source_history'][0]['updates'][1]['key']='detection_model[sgblur]'
    elif change=='unknown_actor':r['matched_source_history'][0]['account_id']='unverified-actor'
    elif change=='orientation':r['coordinate_contract']['exif_orientation']=6
    elif change=='projection':r['coordinate_contract']['projection']='equirectangular'
    with pytest.raises(subject.DatasetError,match=reason):subject.manual_box(r)


def test_false_copied_completeness_or_approval_flags_do_not_create_ground_truth(tmp_path):
    data,images=example(tmp_path)
    for r in data['records']:r['annotation_complete']=True;r['human_review_approval']=True
    result=prepare(data,PROTECTED,images_root=images)
    assert all(not f['annotation_complete'] and not f['independent_human_review'] for f in result['frames'])
    assert result['training_launch_ready'] is False


def test_protected_picture_exclusion_propagates_through_route_transitively_before_pixels(tmp_path):
    rows=[record('a',sequence='route-a'),record('bridge',sequence='route-a'),record('c',sequence='route-c')]
    rows[1]['sequence_ids'].append('route-c')
    protected={'frames':[{'picture_id':'c','sequence_id':'protected-route'}]}
    result=prepare(audit(rows),protected,images_root=tmp_path/'no-images',mode=subject.MODES[1])
    assert all('protected_holdout_component' in f['exclusion_reasons'] for f in result['frames'])
    assert len({f['route_group'] for f in result['frames']})==1


def test_geographic_protected_and_same_physical_sign_propagation():
    rows=[record('a'),record('b'),record('c')]
    rows[0]['gps']={'type':'Point','coordinates':[8.4,48.9]}
    rows[0]['physical_sign_ids']=['same-sign'];rows[1]['physical_sign_ids']=['same-sign']
    protected={'frames':[{'image_id':'nearby','coordinates':[8.4001,48.9]}]}
    result=prepare(audit(rows),protected,plan_only=True,mode=subject.MODES[1])
    assert all('protected_holdout_component' in f['exclusion_reasons'] for f in result['frames'][:2])
    # c shares the fixture byte hash, so byte grouping conservatively excludes it too.
    assert result['frames_by_split']=={'excluded':3}


def test_pixel_duplicates_across_encodings_do_not_cross_split_or_inflate_count(tmp_path):
    data,images=example(tmp_path)
    p=images/'scene-1.png'
    meta=PngImagePlugin.PngInfo();meta.add_text('encoding','different bytes')
    with Image.open(images/'scene-0.png') as image:image.save(p,pnginfo=meta)
    sha=hashlib.sha256(p.read_bytes()).hexdigest()
    for r in data['records']:
        if r['picture_id']=='scene-1':r['source_asset_sha256']=sha;r['source_asset']['sha256']=sha
    result=prepare(data,PROTECTED,images_root=images,mode=subject.MODES[1])
    fs={f['image_id']:f for f in result['frames']}
    assert fs['scene-0']['image_sha256']!=fs['scene-1']['image_sha256']
    assert fs['scene-0']['rgb_sha256']==fs['scene-1']['rgb_sha256']
    assert fs['scene-0']['route_group']==fs['scene-1']['route_group']
    assert fs['scene-1']['exclusion_reasons']==['duplicate_pixels']
    assert result['training_launch_ready'] is False # Fewer than3 independent groups.


@pytest.mark.parametrize('change,reason', [('hash','source_image_sha256_mismatch'),('dimensions','registered_raster_dimensions_mismatch'),('orientation','source_image_not_upright')])
def test_source_bytes_orientation_dimensions_verified(tmp_path,change,reason):
    data,images=example(tmp_path);f=subject.frames_from_audit(data)[0]
    if change=='hash':f['image_sha256']='f'*64
    elif change=='dimensions':f['width']=100
    else:
        p=images/f['image_path'];image=Image.new('RGB',(8,6));exif=Image.Exif();exif[274]=6;image.save(p,exif=exif);f['image_sha256']=subject.digest(p)
    with pytest.raises(subject.DatasetError,match=reason):subject.verify_image(f,images)


def test_splits_stable_under_input_order_and_route_repeats(tmp_path):
    data,images=example(tmp_path,8)
    a=prepare(data,PROTECTED,images_root=images,mode=subject.MODES[1])
    data['records'].reverse()
    b=prepare(data,PROTECTED,images_root=images,mode=subject.MODES[1])
    assert {f['image_id']:(f['route_group'],f['split']) for f in a['frames']}=={f['image_id']:(f['route_group'],f['split']) for f in b['frames']}


def test_empty_or_unidentified_protected_manifest_rejected():
    for protected in ({'frames':[]},{'frames':[{}]}):
        with pytest.raises(subject.DatasetError,match='protected_'):
            prepare(audit([record()]),protected,plan_only=True)


def test_same_image_conflicting_annotated_class_is_not_training(tmp_path):
    data,images=example(tmp_path)
    p=images/'scene-1.png';p.write_bytes((images/'scene-0.png').read_bytes());sha=subject.digest(p)
    for r in data['records']:
        if r['picture_id']=='scene-1':
            r['source_asset_sha256']=sha;r['source_asset']['sha256']=sha
            r['class_id']='city:end' if r['class_id']=='city:start' else 'city:start'
            r['source_code']=subject.CITY_CODES[r['class_id']]
            r['all_current_annotations'][0]['semantics'][0]['value']=r['source_code']
            r['matched_source_history'][0]['updates'][0]['value']=r['source_code']
    result=prepare(data,PROTECTED,images_root=images,mode=subject.MODES[1])
    assert result['exclusion_counts']['identical_pixels_have_conflicting_manual_boxes']==2


def test_repeated_output_refused(tmp_path):
    data,images=example(tmp_path);out=tmp_path/'result'
    prepare(data,PROTECTED,images_root=images,output=out,mode=subject.MODES[1])
    with pytest.raises(subject.DatasetError,match='output_must_be_new'):
        prepare(data,PROTECTED,images_root=images,output=out,mode=subject.MODES[1])


def test_verified_cross_contributor_human_annotation_is_preserved():
    r=record();r['manual_box_actor_matches_picture_contributor']=False;r['picture_contributor']['id']='image-owner'
    evidence={'schema':'youspeed-city-manual-actor-evidence-v1','source_sha256':'a'*64,
        'verified_human_actor_ids':['human-contributor'],'accounts':[{'id':'human-contributor','name':'student'}],
        'machine_annotation_account':{'id':'automated-account'}}
    frames=subject.frames_from_audit(audit([r]),actor_evidence=evidence)
    assert len(frames[0]['boxes'])==1
    evidence['machine_annotation_account']['id']='human-contributor'
    with pytest.raises(subject.DatasetError,match='machine_account_declared_human'):
        subject.frames_from_audit(audit([r]),actor_evidence=evidence)


def test_postgresql_fractional_history_timestamp_and_offset_ordering():
    r=record();r['matched_source_history'][0]['ts']='2026-11-01T00:00:00.12345+00:00'
    assert subject.manual_box(r)['class_id']=='city:start'
    older=deepcopy(r['matched_source_history'][0]);older['ts']='2026-11-01T01:00:00+02:00'
    older['updates'][0]['key']='detection_model[sgblur]'
    r['matched_source_history'].append(older)
    with pytest.raises(subject.DatasetError,match='earliest_event_is_model_qualified'):subject.manual_box(r)


def test_metadata_split_is_frozen_before_decode_and_preserved_after_verification(tmp_path):
    data,images=example(tmp_path,8)
    plan=prepare(data,PROTECTED,plan_only=True,mode=subject.MODES[1])
    verified=prepare(data,PROTECTED,images_root=images,mode=subject.MODES[1],frozen_plan=plan)
    assert verified['training_launch_ready']
    assert [(f['route_group'],f['split']) for f in plan['frames']]==[(f['route_group'],f['split']) for f in verified['frames']]
    plan['frames'][0]['split']='test' if plan['frames'][0]['split']!='test' else 'train'
    with pytest.raises(subject.DatasetError,match='change_frozen_group_split'):
        prepare(data,PROTECTED,images_root=images,mode=subject.MODES[1],frozen_plan=plan)


def test_class_stratification_finds_disjoint_whole_group_covers():
    fs=[]
    for city in subject.CITY_CODES:
        for i in range(3):
            fs.append({'route_group':city+str(i),'exclusion_reasons':[], 'boxes':[{'class_id':city}]})
    assignment,possible=subject.stratified_assignment(fs,'fixed-seed')
    assert possible
    for split in ('train','val','test'):
        assert {f['boxes'][0]['class_id'] for f in fs if assignment[f['route_group']]==split}==set(subject.CITY_CODES)


def test_partial_training_requires_independent_actor_account_evidence():
    with pytest.raises(subject.DatasetError,match='manual_actor_evidence_required'):
        subject.prepare(audit([record()]),PROTECTED,mode=subject.MODES[1],plan_only=True)
