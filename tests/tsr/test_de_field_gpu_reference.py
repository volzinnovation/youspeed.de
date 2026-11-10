import importlib.util
from pathlib import Path

import numpy as np
import pytest


path = Path(__file__).resolve().parents[2] / 'scripts/tsr/de_field_gpu_reference.py'
spec = importlib.util.spec_from_file_location('de_field_gpu_reference', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_probability_drift_and_near_tie_switch_are_distinct():
    reference = np.array([[.51, .49], [.1, .9]], dtype=np.float32)
    device = np.array([[.49, .51], [.09, .91]], dtype=np.float32)
    result = module.comparison(reference, device, ['a', 'b'], ['city:start', 'other'])
    assert result['argmax_changes'] == 1
    assert result['changes_affecting_critical_predicted_classes'] == 1
    assert result['max_probability_abs_error'] == pytest.approx(.02, abs=1e-6)
    assert result['changes'][0]['reference_top1_top2_margin'] == pytest.approx(.02, abs=1e-6)
    assert result['per_predicted_class'][0]['switches_away_from_reference_class'] == 1
    assert result['per_predicted_class'][1]['switches_into_device_class'] == 1
    assert 'no truth labels' in result['interpretation']


def test_identical_predictions_have_no_error_or_switches():
    values = np.array([[.1, .2, .7]], dtype=np.float32)
    result = module.comparison(values, values, ['a'], ['one', 'two', 'three'])
    assert result['argmax_changes'] == 0
    assert result['p99_probability_abs_error'] == 0
    assert result['changes'] == []


def test_invalid_reference_probabilities_are_rejected():
    for values in ([[.2, .2]], [[float('nan'), .5]], [[-.1, 1.1]]):
        with pytest.raises(AssertionError):
            module.comparison(np.asarray(values), np.array([[.5, .5]]), ['a'], ['one', 'two'])


def test_topk_probability_ties_have_explicit_reproducible_ordering():
    values = np.full((1, 6), 1 / 6, dtype=np.float32)
    result = module.comparison(values, values, ['a'], list('abcdef'))
    assert 'lower class index first' in result['topk_tie_policy']
    assert result['topk']['3']['set_changes'] == result['topk']['5']['ordered_list_changes'] == 0
