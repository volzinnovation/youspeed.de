from copy import deepcopy

import pytest

from scripts.tsr.de_expanded_gpu_reference import validate_registry


def registry():
    return {'schemaVersion': 1, 'models': [
        {'id': 'predecessor', 'classes': ['old:one', 'old:two'], 'sha256': 'a' * 64,
         'normalization': 'RGB/255', 'input_shape': [1, 3, 224, 224]},
        {'id': 'expanded', 'classes': ['old:one', 'old:two', 'bus:stop'], 'sha256': 'b' * 64,
         'normalization': 'RGB/255', 'input_shape': [1, 3, 224, 224]}]}


def test_expanded_model_prefix_is_preserved():
    assert len(validate_registry(registry())) == 2


def test_reordered_classes_rejected():
    r = registry()
    r['models'][1]['classes'][:2] = ['old:two', 'old:one']
    with pytest.raises(ValueError, match='prefix'):
        validate_registry(r)


def test_duplicate_model_identity_rejected():
    r = registry()
    r['models'].append(deepcopy(r['models'][0]))
    with pytest.raises(ValueError, match='model ID'):
        validate_registry(r)


def test_missing_exact_checkpoint_pin_rejected():
    r = registry()
    r['models'][1]['sha256'] = 'latest'
    with pytest.raises(ValueError, match='digest'):
        validate_registry(r)


def test_different_normalization_rejected():
    r = registry()
    r['models'][1]['normalization'] = 'ImageNet'
    with pytest.raises(ValueError, match='input contract'):
        validate_registry(r)


def test_duplicated_class_rejected():
    r = registry()
    r['models'][1]['classes'].append('bus:stop')
    with pytest.raises(ValueError, match='Duplicate model class'):
        validate_registry(r)
