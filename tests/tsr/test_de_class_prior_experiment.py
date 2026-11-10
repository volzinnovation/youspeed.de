"""Numerical boundaries for observation-prior experiments."""
from __future__ import annotations

import importlib.util
import csv
import json
from pathlib import Path
import sys

import numpy as np
import pytest

SPEC = importlib.util.spec_from_file_location(
    "de_class_prior_experiment",
    Path(__file__).resolve().parents[2] / "scripts/tsr/de_class_prior_experiment.py",
)
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_zero_observed_count_keeps_positive_probability():
    train = module.smoothed_prior([10, 20, 30])
    prior = module.target_prior([0, 1000, 0], train)
    assert np.all(prior > 0)
    np.testing.assert_allclose(prior.sum(), 1)
    assert np.all(prior >= .75 * train)


def test_alpha_zero_leaves_logits_except_temperature():
    logits = np.array([[0, 1, -2], [2, 0, -4]], dtype=float)
    actual = module.corrected_logits(logits, [.2, .3, .5], [.7, .2, .1], 0, 2)
    np.testing.assert_array_equal(actual, logits / 2)


def test_equal_priors_leave_probabilities_unchanged():
    logits = np.array([[1, 2], [5, -1]], dtype=float)
    actual = module.corrected_logits(logits, [.2, .8], [.2, .8], 1)
    np.testing.assert_allclose(module.softmax(actual), module.softmax(logits))


def test_prior_ratio_divides_training_prior_not_multiply_target_only():
    source_prior = np.array([.8, .2])
    target_prior = np.array([.6, .4])
    # An uninformative feature gives source posterior=source prior. Correcting
    # label priors must yield the target prior, not source*target normalized.
    logits = np.log(source_prior)[None, :]
    actual = module.softmax(module.corrected_logits(logits, source_prior, target_prior, 1))
    np.testing.assert_allclose(actual[0], target_prior)


def test_zero_trust_returns_training_prior():
    prior = module.smoothed_prior([10, 1, 0])
    np.testing.assert_allclose(module.target_prior([0, 100, 90], prior, trust=0), prior)


def test_recipe_effective_prior_power_avoids_double_correction():
    counts = [80, 20]
    natural = module.smoothed_prior(counts)
    expected = natural ** .75
    expected /= expected.sum()
    np.testing.assert_allclose(module.effective_count_prior(counts, .75), expected)
    np.testing.assert_allclose(module.effective_count_prior(counts, 0), [.5, .5])
    with pytest.raises(ValueError):
        module.effective_count_prior(counts, -1)


def test_structurally_unobservable_city_prior_is_not_penalized():
    prior = np.array([.4, .5, .06, .04])
    result = module.censored_target_prior([1000, 5, 0, 0], prior, [True, True, False, False])
    np.testing.assert_allclose(result[2:], prior[2:])
    np.testing.assert_allclose(result.sum(), 1)
    assert result[0] > prior[0]
    assert result[1] < prior[1]


def test_structurally_unobservable_rejection_classes_keep_their_mass():
    prior = np.array([.05, .03, .4, .52])
    result = module.censored_target_prior([0, 0, 1000, 5], prior, [False, False, True, True])
    np.testing.assert_allclose(result[:2], prior[:2])
    np.testing.assert_allclose(result.sum(), 1)
    with pytest.raises(ValueError):
        module.censored_target_prior([0, 0, 1, 2], prior, [False, False, True, True], trust=2)


def test_confidence_gate_preserves_strong_visual_evidence():
    logits = np.array([[8, 0], [.1, 0]], dtype=float)
    prior = [.5, .5]
    result = module.corrected_logits(logits, prior, [.01, .99], 1, confidence_gate=.95)
    np.testing.assert_array_equal(result[0], logits[0])
    assert np.argmax(result[1]) == 1


def test_missing_model_output_remains_a_miss_in_global_label_space():
    result = module.metrics(np.array([0, 2]), np.array([[.8, .2], [.7, .3]]),
                            ["a", "b", "city:start"], [0, 1])
    assert result["accuracy"] == .5
    assert result["per_class"][2]["support"] == 1
    assert result["per_class"][2]["fn"] == 1
    assert result["per_class"][2]["recall"] == 0
    assert np.isfinite(result["nll_clipped_at_1e_minus12"])


def test_model_class_order_is_mapped_to_global_order():
    result = module.metrics(np.array([1, 0]), np.array([[.9, .1], [.1, .9]]),
                            ["a", "b"], [1, 0])
    assert result["predictions"] == [1, 0]
    assert result["accuracy"] == 1


def test_partitions_reject_group_leakage():
    with pytest.raises(ValueError, match="Group crosses"):
        module.validate_partitions([0, 1], [2, 3], np.array(["a", "b", "a", "c"]), 4)


def test_partitions_require_complete_disjoint_coverage():
    for dev, report in [([0], [2]), ([0, 1], [1, 2]), ([0, 0], [1, 2])]:
        with pytest.raises(ValueError):
            module.validate_partitions(dev, report, np.array(["a", "b", "c"]), 3)


def test_critical_guard_rejects_new_false_positive_even_without_class_support():
    names = ["other", "city:start"]
    baseline = module.metrics(np.array([0]), np.array([[.9, .1]]), names, [0, 1])
    changed = module.metrics(np.array([0]), np.array([[.1, .9]]), names, [0, 1])
    assert not module.passes_critical_guard(baseline, changed)
    assert module.passes_critical_guard(baseline, baseline)


def test_critical_guard_rejects_new_false_negative():
    names = ["other", "maxspeed:30"]
    baseline = module.metrics(np.array([1]), np.array([[.1, .9]]), names, [0, 1])
    changed = module.metrics(np.array([1]), np.array([[.9, .1]]), names, [0, 1])
    assert not module.passes_critical_guard(baseline, changed)


@pytest.mark.parametrize("counts", [[-1, 2], [np.nan, 2], [], [[1, 2]]])
def test_invalid_counts_rejected(counts):
    with pytest.raises(ValueError):
        module.smoothed_prior(counts)


def test_softmax_handles_large_finite_logits_without_overflow():
    result = module.softmax(np.array([[10000, 9999]], dtype=float))
    assert np.all(np.isfinite(result))
    np.testing.assert_allclose(result.sum(axis=1), 1)


def test_metric_precision_recall_macro_and_weighted_f1():
    truth = np.array([0, 0, 0, 1])
    probabilities = np.array([[.9, .1], [.9, .1], [.1, .9], [.9, .1]])
    result = module.metrics(truth, probabilities, ["a", "b"], [0, 1])
    assert result["micro_f1"] == .5
    assert result["per_class"][0]["precision"] == pytest.approx(2 / 3)
    assert result["per_class"][0]["recall"] == pytest.approx(2 / 3)
    assert result["macro_f1_supported"] == pytest.approx(1 / 3)
    assert result["weighted_f1"] == pytest.approx(.5)


def test_report_labels_cannot_choose_temperature_or_prior(tmp_path, monkeypatch):
    counts = tmp_path / "counts.csv"
    columns = ["class_id", *module.SOURCE_COLUMNS.values()]
    with counts.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=columns)
        writer.writeheader()
        for name, count in [("other", 100), ("maxspeed:30", 20), ("city:start", 0)]:
            writer.writerow({"class_id": name, **{field: count for field in module.SOURCE_COLUMNS.values()}})
    common = {
        "class_names": np.array(["other", "maxspeed:30", "city:start"]),
        "train_labels": np.array([0] * 30 + [1] * 20 + [2] * 10),
        "val_logits": np.array([[2, .1, .1], [.1, 2, .1], [.1, .1, 2], [1.2, 1, 0],
                                [2, .1, .1], [.1, 2, .1], [.1, .1, 2], [1.1, 1, 0]]),
        "val_group_ids": np.array([f"group-{i}" for i in range(8)]),
        "val_sample_ids": np.array([f"sample-{i}" for i in range(8)]),
        "dev_indices": np.array([0, 1, 2, 3]),
        "report_indices": np.array([4, 5, 6, 7]),
    }
    selected = []
    observed_selected = []
    for index, report in enumerate(([0, 1, 2, 0], [2, 0, 1, 2])):
        archive = tmp_path / f"logits-{index}.npz"
        np.savez(archive, **common, val_labels=np.array([0, 1, 2, 0, *report]))
        output = tmp_path / f"result-{index}"
        monkeypatch.setattr(sys, "argv", ["prior", "--input", str(archive), "--counts", str(counts), "--output", str(output)])
        module.main()
        selected.append(json.loads((output / "selected.json").read_text()))
        observed_selected.append(json.loads((output / "observed-selected.json").read_text()))
        grid = json.loads((output / "development-grid.json").read_text())
        assert all(not row["eligible_for_selection"] for row in grid if row["source"] == "pooled")
        assert selected[-1]["source"] != "pooled"
        assert observed_selected[-1]["source"] not in {"pooled", "uniform_control"}
    assert selected[0] == selected[1]
    assert observed_selected[0] == observed_selected[1]


def test_uniform_control_winner_does_not_hide_observed_prior_result(tmp_path, monkeypatch):
    counts = tmp_path / "counts.csv"
    with counts.open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=["class_id", *module.SOURCE_COLUMNS.values()])
        writer.writeheader()
        for name, count in [("other", 90), ("no_parking", 10)]:
            writer.writerow({"class_id": name, **{field: count for field in module.SOURCE_COLUMNS.values()}})
    archive = tmp_path / "logits.npz"
    np.savez(archive, class_names=np.array(["other", "no_parking"]),
             train_labels=np.array([0] * 90 + [1] * 10),
             val_labels=np.array([0, 1, 0, 1]),
             val_logits=np.array([[5., 0], [1., 0], [5., 0], [1., 0]]),
             val_group_ids=np.array(["a", "b", "c", "d"]),
             val_sample_ids=np.array(["a", "b", "c", "d"]),
             dev_indices=np.array([0, 1]), report_indices=np.array([2, 3]))
    output = tmp_path / "output"
    monkeypatch.setattr(sys, "argv", ["prior", "--input", str(archive), "--counts", str(counts), "--output", str(output)])
    module.main()
    overall = json.loads((output / "selected.json").read_text())
    observed = json.loads((output / "observed-selected.json").read_text())
    score = json.loads((output / "metrics.json").read_text())
    assert overall["source"] == "uniform_control"
    assert observed["source"] == "none"
    assert score["selected_report"]["accuracy"] == 1
    assert score["observed_selected_report"]["accuracy"] == .5
    assert (output / "observed-report-per-class.csv").exists()
