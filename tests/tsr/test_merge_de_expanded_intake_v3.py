import importlib.util
from pathlib import Path
import sys
import pytest

ROOT=Path(__file__).parents[2]
sys.path.insert(0,str(ROOT/'scripts/tsr'))
spec=importlib.util.spec_from_file_location('intake_v3',ROOT/'scripts/tsr/merge_de_expanded_intake_v3.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def fixture_rows():
    return [{'sample_id':f'municipal-v1-M{i:03}','label':'supplementary:plate','class_id':'supplementary:plate',
             'label_origin':'assistant_visual_silver','human_approved':False,'human_reviewed':False,
             'training_only':True,'evaluation_eligible':False,'exact_code_inferred':False,'restriction_semantics':'unknown',
             'physical_site_group':f'post:{max(1,i-1)}','physical_sign_id':f'sign:{i}'} for i in range(1,5)]


def test_only_four_generic_plates_are_admitted_not_parking_or_oneway():
    rows=fixture_rows()+[{'sample_id':'municipal-v1-M005','label':'parking'},
                         {'sample_id':'municipal-v1-M006','label':'oneway'}]
    assert [r['sample_id'] for r in module.select_plates(rows)]==[f'municipal-v1-M{i:03}' for i in range(1,5)]


@pytest.mark.parametrize('change',[{'human_approved':True},{'evaluation_eligible':True},
                                  {'restriction_semantics':'parking_permitted'},{'exact_code_inferred':True}])
def test_silver_or_generic_semantics_cannot_be_promoted(change):
    rows=fixture_rows();rows[0].update(change)
    with pytest.raises(ValueError,match='truth scope'):
        module.select_plates(rows)
