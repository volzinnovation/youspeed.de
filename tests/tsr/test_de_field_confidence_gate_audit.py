import importlib.util
from pathlib import Path

import numpy as np
import pytest


path = Path(__file__).resolve().parents[2] / 'scripts/tsr/de_field_confidence_gate_audit.py'
spec = importlib.util.spec_from_file_location('de_field_confidence_gate_audit', path)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def test_threshold_equality_passes_and_crossing_direction_is_preserved():
    row = module.audit(np.array([.899, .9]), np.array([.9, .899]), .9)
    assert row['reference_at_or_above'] == row['device_at_or_above'] == 1
    assert row['crossings_reference_pass_device_fail'] == 1
    assert row['crossings_reference_fail_device_pass'] == 1
    assert row['reference_minimum_absolute_margin'] == 0
    assert row['maximum_top1_confidence_abs_difference'] == pytest.approx(.001)


def test_per_class_thresholds_do_not_use_a_single_global_value():
    row = module.audit(np.array([.8, .8]), np.array([.79, .91]), [.7, .9])
    assert row['reference_at_or_above'] == 1
    assert row['device_at_or_above'] == 2
    assert row['crossings_reference_fail_device_pass'] == 1
