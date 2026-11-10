import importlib.util
from pathlib import Path
import pytest

path = Path(__file__).resolve().parents[2] / 'scripts/tsr/prepare_de136_native_export.py'
spec = importlib.util.spec_from_file_location('prepare_de136', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def valid():
    classes = [f'class:{i}' for i in range(134)] + ['city:start', 'city:end']
    return classes, {'classes': classes, 'family': 'yolo', 'normalization': 'RGB/255',
                     'initialization_sha256': module.BASELINE, 'state_dict': {'weights': 1}}


def test_preserves_exact_class_order():
    classes, record = valid()
    module.validate_record(record, classes)
    record['classes'] = classes[:-2] + list(reversed(classes[-2:]))
    with pytest.raises(ValueError):
        module.validate_record(record, classes)


@pytest.mark.parametrize('key,value', [('family', 'small'), ('normalization', 'ImageNet'),
                                     ('initialization_sha256', 'unknown'), ('state_dict', {})])
def test_rejects_wrong_model_contract(key, value):
    classes, record = valid()
    record[key] = value
    with pytest.raises(ValueError):
        module.validate_record(record, classes)
