import importlib.util
from pathlib import Path
import sys
import pytest

ROOT=Path(__file__).parents[2]
sys.path.insert(0,str(ROOT/'scripts/tsr'))
spec=importlib.util.spec_from_file_location('historical_comparison',ROOT/'scripts/tsr/compare_de_expanded_historical_gpu.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)


def test_only_compatible_old_historical_rows_enter_requested_scope():
    def row(key,split='dev',index=0,**extra):
        return {'sample_id':key,'split':split,'class_index':index,**extra}
    doc={'ontology_conflict_ids':['conflict'],'samples':[
        row('valid'),row('conflict'),row('silver',index=136),row('intake',is_new_intake=True),
        row('train_only',training_only=True),row('ineligible',evaluation_eligible=False),
        row('training',split='train'),row('reserved',split='test'),row('report',split='report')]}
    assert [r['sample_id'] for r in module.compatible(doc,'dev')]==['valid']
    assert [r['sample_id'] for r in module.compatible(doc,'report')]==['report']
    with pytest.raises(ValueError,match='Only historical dev/report'):
        module.compatible(doc,'test')


def test_scope_signature_binds_pixels_labels_and_crop_not_just_ids():
    row={'sample_id':'same','sha256':'a','class_index':2,'label':'stop','training_crop_box':[0,0,8,8]}
    original=module.signatures([row])
    for change in [{'sha256':'b'},{'class_index':3},{'training_crop_box':[0,0,7,8]}]:
        assert module.signatures([{**row,**change}])!=original
