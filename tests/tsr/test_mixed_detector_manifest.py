from copy import deepcopy
import sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'scripts/tsr/sign_only_pilot'))
import train_mixed as mixed


def fixture():
    frames=[{'image_id':s,'group_id':s,'split':s,'image_sha256':str(i)*64,'width':100,'height':100,
             'annotation_complete':True,'supervision':'model_assisted_review'} for i,s in enumerate(['train','validation','test'],1)]
    frames[0].update(supervision='teacher_pseudo',annotation_complete=False,human_verified=False,
                     pseudo_label_status='pseudo_positive',pseudo_label_policy_sha256='a'*64)
    return {'schema':mixed.MANIFEST_SCHEMA,'dataset_revision':'b'*40,'review_provenance':'mixed_reviewed_and_pseudo',
            'pseudo_policy_sha256':'a'*64,'frames':frames}


def test_explicit_pseudo_training_supported():
    assert len(mixed.partition_manifest(fixture())['train'])==1


@pytest.mark.parametrize('change',[{'annotation_complete':True},{'human_verified':True},
    {'pseudo_label_policy_sha256':'c'*64},{'pseudo_label_status':'excluded_uncertain_scope'}])
def test_reject_misrepresented_or_uncertain_pseudo_labels(change):
    value=fixture();value['frames'][0].update(change)
    with pytest.raises(ValueError):mixed.partition_manifest(value)


def test_pseudo_validation_is_not_allowed():
    value=fixture();value['frames'][1].update(supervision='teacher_pseudo',annotation_complete=False)
    with pytest.raises(ValueError):mixed.partition_manifest(value)


def test_cross_split_duplicate_rejected():
    value=fixture();value['frames'][0]['image_sha256']=value['frames'][1]['image_sha256']
    with pytest.raises(ValueError):mixed.partition_manifest(value)
