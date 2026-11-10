import hashlib
import importlib.util
from pathlib import Path

import pytest


path = Path(__file__).resolve().parents[2] / 'scripts/iphone/validate_classifier_benchmark.py'
spec = importlib.util.spec_from_file_location('iphone_classifier_benchmark_validation', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_model_digest_uses_relative_paths_independent_of_root_alias(tmp_path):
    model = tmp_path / 'model.mlmodelc'
    (model / 'weights').mkdir(parents=True)
    (model / 'weights/weight.bin').write_bytes(b'frozen weights')
    (model / 'metadata.json').write_text('{}')
    alias = tmp_path / 'alias.mlmodelc'
    alias.symlink_to(model, target_is_directory=True)
    expected = 'metadata.json\0' + hashlib.sha256(b'{}').hexdigest() + '\nweights/weight.bin\0' + hashlib.sha256(b'frozen weights').hexdigest() + '\n'
    assert module.artifact_sha(model) == module.artifact_sha(alias) == hashlib.sha256(expected.encode()).hexdigest()


def test_native_vector_rejects_wrong_label_or_score():
    module.validate_probability_row([.1, .9], ['a', 'b'], 'b', .9)
    with pytest.raises(AssertionError):
        module.validate_probability_row([.1, .9], ['a', 'b'], 'a', .1)
    with pytest.raises(AssertionError):
        module.validate_probability_row([.1, .9], ['a', 'b'], 'b', .8)


def test_raw_timing_percentiles_and_invalid_values():
    assert module.stats([10, 20, 30, 100])['p95_ms'] == pytest.approx(89.5)
    for values in ([], [float('nan')], [-1]):
        with pytest.raises(AssertionError):
            module.stats(values)


def test_compute_policy_is_explicit_and_rejects_unrequested_modes():
    assert module.compute_policy({}) == ('cpuAndGPU', False)
    assert module.compute_policy({'computeUnits': 'cpuAndGPU'}) == ('cpuAndGPU', False)
    assert module.compute_policy({'computeUnits': 'all'}) == ('all', True)
    for mode in ('cpuOnly', 'cpuAndNeuralEngine', 'gpu', None, ''):
        with pytest.raises(AssertionError):
            module.compute_policy({'computeUnits': mode})


def test_timing_containment_tolerates_only_sub_clock_rounding():
    module.assert_total_contains_components(4.46775, [4.467750000000001])
    with pytest.raises(AssertionError):
        module.assert_total_contains_components(4.46775, [4.467751])
    with pytest.raises(AssertionError):
        module.assert_total_contains_components(4.46775, [float('nan')])
