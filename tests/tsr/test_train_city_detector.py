import importlib.util
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('train_city_detector',Path(__file__).resolve().parents[2]/'scripts/tsr/train_city_detector.py')
subject=importlib.util.module_from_spec(spec);spec.loader.exec_module(subject)

def frame(split,group,**changes):
    return {'split':split,'route_group':group,'exif_orientation':1,'boxes':[{'bbox_source':'manual_geometry','detector_class_id':0}],**changes}

def manifest():
    return {'schema':'youspeed-city-detector-frames-v1','training_mode':'positive_only_frozen_sign_head',
            'training_launch_ready':True,'image_verification_complete':True,
            'class_names':['sign','plate','face'],'detector_checkpoint_sha256':subject.BASELINE_SHA,
            'frames':[frame('train','a'),frame('dev','b'),frame('test','c')]}

def test_reserved_frames_are_never_used_for_optimization_or_selection():
    train,dev,reserved=subject.partition_frames(manifest())
    assert [r['split'] for r in train]==['train']
    assert [r['split'] for r in dev]==['dev']
    assert [r['split'] for r in reserved]==['test']

def test_rejected_machine_box_on_training_route_is_not_a_heldout_leak():
    m=manifest();m['frames'].append(frame('excluded','a',exclusion_reasons=['no_verified_manual_city_geometry']))
    train,dev,reserved=subject.partition_frames(m)
    assert len(train)==len(dev)==1 and len(reserved)==2

@pytest.mark.parametrize('field,value',[('image_id','same'),('image_sha256','a'*64),('rgb_sha256','b'*64),('sequence_ids',['same-sequence'])])
def test_rejects_hidden_identity_overlap_even_with_different_group_names(field,value):
    m=manifest()
    m['frames'][0][field]=value;m['frames'][2][field]=value
    with pytest.raises(ValueError,match='identity overlaps'):subject.partition_frames(m)

@pytest.mark.parametrize('field',['training_launch_ready','image_verification_complete'])
def test_unmaterialized_or_insufficient_splits_cannot_launch_training(field):
    m=manifest();m[field]=False
    with pytest.raises(ValueError,match='Verified images'):subject.partition_frames(m)

@pytest.mark.parametrize('change',['overlap','missing_group','no_dev','machine_box','rotated','wrong_mode'])
def test_refuses_unsafe_partial_label_experiment(change):
    m=manifest()
    if change=='overlap':m['frames'][2]['route_group']='a'
    elif change=='missing_group':del m['frames'][0]['route_group']
    elif change=='no_dev':m['frames'].pop(1)
    elif change=='machine_box':m['frames'][0]['boxes'][0]['bbox_source']='model'
    elif change=='rotated':m['frames'][0]['exif_orientation']=6
    else:m['training_mode']='ordinary_yolo'
    with pytest.raises(ValueError):subject.partition_frames(m)

def test_selection_prioritizes_runtime_usable_recall_then_proposals_then_drift():
    base={'known_targets':10,'matched_at_confirmation_floor':3,'matched_known_targets':8,'mean_best_sign_iou':.7,'mean_sign_probability_drift':0.}
    assert subject.select_key({**base,'matched_at_confirmation_floor':4,'matched_known_targets':7})>subject.select_key(base)
    assert subject.select_key({**base,'matched_known_targets':9})>subject.select_key(base)
    assert subject.select_key({**base,'mean_sign_probability_drift':.1})<subject.select_key(base)

def test_partial_loss_helper_is_pinned(tmp_path):
    source=tmp_path/'helper.py';source.write_text('raise RuntimeError("must not execute")')
    with pytest.raises(ValueError,match='reviewed source'):subject.load_helper(source)
