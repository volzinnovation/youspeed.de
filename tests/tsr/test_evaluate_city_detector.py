"""Known-box detector scoring preserves window exclusions and partial-label scope."""
from copy import deepcopy
import importlib.util
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

ROOT=Path(__file__).resolve().parents[2]
spec=importlib.util.spec_from_file_location('city_detector',ROOT/'scripts/tsr/evaluate_city_detector.py')
subject=importlib.util.module_from_spec(spec);spec.loader.exec_module(subject)


def box(coords, label='city:start', annotation='a'):
    return dict(annotation_id=annotation,class_id=label,detector_class_id=0,
                bbox_source='manual_geometry',bbox_xyxy=coords)


def test_mobile_window_keeps_full_height_and_reports_all_exclusions():
    image=Image.new('RGB',(3840,2160),(20,30,40))
    rendered,transform=subject.prepare_image(image)
    assert rendered.size==(1024,1024)
    assert transform['offset_x']==pytest.approx(-1680*1024/2160)
    targets=subject.transform_boxes([
        box([1800,1000,2000,1200],annotation='inside'),
        box([1600,1000,1800,1200],annotation='cut'),
        box([100,1000,300,1200],annotation='outside')],transform)
    assert [t['window_status'] for t in targets]==['inside','clipped','outside']
    assert targets[1]['visible_fraction']==pytest.approx(.6)
    assert targets[2]['visible_fraction']==0
    assert targets[0]['bbox_xyxy'][0]==pytest.approx((1800-1680)*1024/2160)
    assert targets[0]['size_bin']=='ge64'
    _,whole=subject.prepare_image(image,'whole_letterbox')
    assert all(t['window_status']=='inside' for t in subject.transform_boxes([box([100,1000,300,1200])],whole))


def test_portrait_right_alignment_padding_and_upright_contract():
    image=Image.new('RGB',(512,1024),(255,0,0))
    rendered,transform=subject.prepare_image(image)
    assert transform['offset_x']==512
    assert rendered.getpixel((0,0))==(114,114,114)
    assert rendered.getpixel((900,500))==(255,0,0)
    image.getexif()[274]=6
    with pytest.raises(ValueError,match='EXIF1'):subject.prepare_image(image)


def raw_fixture():
    value=np.zeros((7,21504),dtype=np.float32)
    def anchor(index,xyxy,score,plate=0):
        x1,y1,x2,y2=xyxy;value[:4,index]=[(x1+x2)/2,(y1+y2)/2,x2-x1,y2-y1]
        value[4,index]=score;value[5,index]=plate
    anchor(0,[10,10,50,50],.8,.99)  # Sign must survive another class's higher score.
    anchor(1,[11,11,51,51],.7)
    anchor(2,[100,100,150,150],.25)
    anchor(3,[200,200,250,250],.249)
    return value


def test_android_sign_channel_threshold_nms_and_cap():
    predictions=subject.decode_sign_predictions(raw_fixture())
    assert [p['anchor_index'] for p in predictions]==[0,2]
    assert subject.decode_sign_predictions(raw_fixture(),maximum_proposals=1)[0]['anchor_index']==0
    with pytest.raises(ValueError,match='raw output'):subject.decode_sign_predictions(np.zeros((6,21504)))


def test_geometry_diagnosis_distinguishes_low_score_from_missing_box_shape():
    raw=raw_fixture()
    _,transform=subject.prepare_image(Image.new('RGB',(1024,1024)))
    targets=subject.transform_boxes([box([200,200,250,250]),box([900,900,1000,1000],annotation='b')],transform)
    geometry=subject.maximum_raw_geometry(raw,targets)
    assert geometry[0]['maximum_raw_box_iou']==1
    assert geometry[0]['maximum_sign_score_at_iou_0_5']==pytest.approx(.249)
    assert geometry[1]['raw_anchors_at_iou_0_5']==0
    assert geometry[1]['maximum_sign_score_at_iou_0_5'] is None
    assert subject.match_known_boxes(targets,subject.decode_sign_predictions(raw))==[]


def test_one_prediction_cannot_match_multiple_targets_and_partial_scope_stays_explicit():
    _,transform=subject.prepare_image(Image.new('RGB',(1024,1024)))
    targets=subject.transform_boxes([box([10,10,50,50]),box([11,11,51,51],annotation='b')],transform)
    predictions=subject.decode_sign_predictions(raw_fixture())
    matches=subject.match_known_boxes(targets,predictions)
    assert len(matches)==1
    rows=[dict(targets=targets,predictions=predictions,matches=matches,split='val')]
    summary=subject.summarize(rows)
    assert summary['metrics']['overall']['inside']==2
    assert summary['metrics']['overall']['matched']==1
    assert summary['metrics']['overall']['known_box_recall_inside_window']==.5
    assert summary['unmatched_proposals_are_not_false_positives']
    assert summary['precision'] is summary['mAP'] is summary['F1'] is None


def manifest_fixture(tmp_path):
    image=tmp_path/'frame.png';Image.new('RGB',(1024,1024)).save(image)
    return {'schema':'youspeed-city-detector-frames-v1','class_names':['sign','plate','face'],
            'frames':[dict(image_id='one',image_path='frame.png',image_sha256=subject.sha(image),
              width=1024,height=1024,exif_orientation=1,sequence_id='sequence',route_group='route',
              split='train',annotation_complete=False,boxes=[box([10,20,30,40])])]}


def test_manifest_checks_pixels_orientation_groups_and_positive_only_scope(tmp_path):
    manifest=manifest_fixture(tmp_path)
    assert len(subject.validate_manifest(manifest,tmp_path,['train']))==1
    with pytest.raises(ValueError,match='No selected'):subject.validate_manifest(manifest,tmp_path,['test'])
    changed=deepcopy(manifest);changed['frames'].append(dict(changed['frames'][0],image_id='two',split='val'))
    with pytest.raises(ValueError,match='crosses splits'):subject.validate_manifest(changed,tmp_path)
    changed=deepcopy(manifest);changed['frames'][0]['boxes']=[]
    with pytest.raises(ValueError,match='verified negatives'):subject.validate_manifest(changed,tmp_path)
    changed=deepcopy(manifest);changed['frames'][0]['image_sha256']='0'*64
    with pytest.raises(ValueError,match='digest'):subject.validate_manifest(changed,tmp_path)
    changed=deepcopy(manifest);changed['frames'][0]['width']=1023
    with pytest.raises(ValueError,match='dimensions'):subject.validate_manifest(changed,tmp_path)


def test_manifest_rejects_other_detector_ontology_and_unregistered_geometry(tmp_path):
    manifest=manifest_fixture(tmp_path)
    changed=deepcopy(manifest);changed['class_names']=['city:start','city:end']
    with pytest.raises(ValueError,match='ontology'):subject.validate_manifest(changed,tmp_path)
    changed=deepcopy(manifest);changed['frames'][0]['exif_orientation']=6
    with pytest.raises(ValueError,match='upright'):subject.validate_manifest(changed,tmp_path)
    changed=deepcopy(manifest);changed['frames'][0]['boxes'][0]['bbox_xyxy']=[-1,20,30,40]
    with pytest.raises(ValueError,match='dimensions'):subject.validate_manifest(changed,tmp_path)


def test_training_only_selection_does_not_open_reserved_pixels(tmp_path):
    manifest=manifest_fixture(tmp_path)
    reserved=dict(deepcopy(manifest['frames'][0]),image_id='reserved',image_path='must-not-open.jpg',
        image_sha256='f'*64,route_group='protected',sequence_id='protected-sequence',split='test')
    manifest['frames'].append(reserved)
    assert len(subject.validate_manifest(manifest,tmp_path,['train']))==1
    with pytest.raises(ValueError,match='unavailable'):subject.validate_manifest(manifest,tmp_path)


def test_plan_only_and_wrong_checkpoint_manifests_cannot_be_evaluated(tmp_path):
    manifest=manifest_fixture(tmp_path)
    manifest['image_verification_complete']=False
    with pytest.raises(ValueError,match='Plan-only'):subject.validate_manifest(manifest,tmp_path)
    manifest['image_verification_complete']=True
    manifest['detector_checkpoint_sha256']='0'*64
    with pytest.raises(ValueError,match='pinned baseline'):subject.validate_manifest(manifest,tmp_path)


def test_confirmation_floor_is_separate_from_detector_admission():
    raw=raw_fixture(); _,transform=subject.prepare_image(Image.new('RGB',(1024,1024)))
    targets=subject.transform_boxes([box([10,10,50,50]),box([100,100,150,150],annotation='b')],transform)
    predictions=subject.decode_sign_predictions(raw)
    rows=[dict(targets=targets,predictions=predictions,split='val',
        matches=subject.match_known_boxes(targets,predictions),
        matches_confirmation_floor=subject.match_known_boxes(targets,[p for p in predictions if p['score']>=.7]))]
    overall=subject.summarize(rows)['metrics']['overall']
    assert overall['known_box_recall_inside_window']==1
    assert overall['known_box_recall_at_confirmation_floor']==.5
