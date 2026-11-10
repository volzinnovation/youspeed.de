import importlib.util
from pathlib import Path

import numpy as np
import pytest


path = Path(__file__).resolve().parents[2] / 'scripts/android/validate_classifier_benchmark.py'
spec = importlib.util.spec_from_file_location('android_benchmark_validator', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_partial_gpu_is_not_reported_as_full_gpu():
    text = '''YouSpeedClassifierBench: BEGIN candidate-r0
tflite: Replacing 530 out of 546 node(s) with delegate (TfLiteGpuDelegateV2) node, yielding 2 partitions for subgraph 0.
tflite: Initialized OpenCL-based API.
tflite: Created 2 GPU delegate kernels.
YouSpeedClassifierBench: END candidate-r0 status=complete'''
    row = module.delegation(text)['candidate-r0']
    assert row['status'] == 'partially_delegated'
    assert row['partitions'][0]['total_nodes'] == 546
    assert row['gpu_kernel_count'] == 2


def test_log_coverage_cannot_be_inferred_from_gpu_creation_only():
    row = module.delegation('YouSpeedClassifierBench: BEGIN run\ntflite: Created 1 GPU delegate kernels.\nYouSpeedClassifierBench: END run status=complete')['run']
    assert row['status'] == 'unknown_missing_native_log'


def test_repeated_trial_log_boundaries_are_separate():
    text = '''YouSpeedClassifierBench: BEGIN baseline
tflite: Replacing 546 out of 546 node(s) with delegate (TfLiteGpuDelegateV2) node, yielding 1 partitions for subgraph 0.
YouSpeedClassifierBench: END baseline status=complete
YouSpeedClassifierBench: BEGIN candidate
YouSpeedClassifierBench: END candidate status=failed'''
    rows = module.delegation(text)
    assert rows['baseline']['status'] == 'fully_delegated'
    assert rows['candidate']['status'] == 'unknown_missing_native_log'


def test_percentiles_are_calculated_from_raw_samples():
    result = module.summary([10, 20, 30, 100])
    assert result['p50Ms'] == 25
    assert result['p95Ms'] == pytest.approx(89.5)
    assert result['meanMs'] == 40
    with pytest.raises(AssertionError):
        module.compare_stats(result, {**result, 'p95Ms': 100})


def test_invalid_timing_samples_are_rejected():
    for value in ([], [-1, 1], [np.nan, 1], [np.inf, 1]):
        with pytest.raises(AssertionError):
            module.summary(value)
