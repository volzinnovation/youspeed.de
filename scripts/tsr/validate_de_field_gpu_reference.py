#!/usr/bin/env python3
"""Independently validate frozen reference artifacts and emit label-blind aggregates."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path

import numpy as np


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--android', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    read = lambda path: json.loads(path.read_text())
    receipt = read(args.reference / 'complete.json')
    provenance = read(args.reference / 'provenance-and-android-parity.json')
    assert receipt['status'] == 'complete'
    assert sha(args.reference / 'gpu-reference-predictions.npz') == receipt['predictions_sha256'] == provenance['predictions_sha256']
    assert sha(args.reference / 'provenance-and-android-parity.json') == receipt['provenance_sha256']
    assert sha(args.reference / 'executed-de_field_gpu_reference.py') == provenance['script_sha256']
    assert sha(args.android / 'device-predictions.npz') == provenance['android_predictions_sha256']
    assert provenance['truth_labels_read'] is False and provenance['accuracy_or_f1_computed'] is False
    reference = np.load(args.reference / 'gpu-reference-predictions.npz', allow_pickle=False)
    android = np.load(args.android / 'device-predictions.npz', allow_pickle=False)
    ids = reference['image_ids'].tolist()
    assert len(ids) == len(set(ids)) == 120
    native_ids = reference['android_image_ids'].tolist()
    assert native_ids == android['image_ids'].tolist() and len(native_ids) == 96
    selected = np.asarray([ids.index(value) for value in native_ids])
    assert np.array_equal(reference['canonical_tensor_sha256'][selected], android['canonical_tensor_sha256'])
    assert np.array_equal(reference['android_native_tensor_sha256'], android['native_tensor_sha256'])
    assert np.array_equal(reference['baseline134_classes'], reference['primary136_classes'][:134])
    assert np.array_equal(reference['primary136_classes'], reference['source136_classes'])
    assert reference['primary136_classes'][-2:].tolist() == ['city:start', 'city:end']
    result = {'status': 'passed', 'human_labels_read': False, 'accuracy_or_f1_computed': False,
              'canonical_images': 120, 'android_images': 96, 'canonical_source_counts': dict(Counter(reference['sources'].tolist())),
              'reference_predictions_sha256': receipt['predictions_sha256'],
              'android_predictions_sha256': provenance['android_predictions_sha256'],
              'class_order_and_input_tensor_hashes_verified': True,
              'native_scope': provenance.get('android_native_input_scope', 'Whole stored crop versus sign-window canonical crop; context differs.'),
              'models': {}, 'comparisons': {}}
    for model, classes in [('baseline134', 134), ('primary136', 136), ('source136', 136)]:
        values = reference[model + '_canonical_scores']
        assert values.shape == (120, classes) and np.isfinite(values).all() and (values >= 0).all()
        assert np.allclose(values.sum(1), 1, atol=1e-5)
        result['models'][model] = provenance['models'][model]
        if model == 'source136':
            continue
        assert np.array_equal(reference[model + '_classes'], android[model + '_classes'])
        contrasts = {
            'canonical_same_pixels_export_gpu_difference': (values[selected], android[model + '_canonical_scores']),
            'android_native_same_pixels_export_gpu_difference': (reference[model + '_android_native_scores'], android[model + '_native_scores']),
            'pytorch_preprocessing_only_native_vs_canonical': (values[selected], reference[model + '_android_native_scores']),
        }
        result['comparisons'][model] = {}
        for name, (a, b) in contrasts.items():
            assert a.shape == b.shape == (96, classes)
            assert np.isfinite(b).all() and (b >= 0).all() and np.allclose(b.sum(1), 1, atol=.02)
            difference = np.abs(a.astype(np.float64) - b.astype(np.float64))
            recorded = provenance['comparisons'][model][name]
            metrics = {'max_probability_abs_error': float(difference.max()),
                       'p99_probability_abs_error': float(np.percentile(difference, 99)),
                       'mean_probability_abs_error': float(difference.mean()),
                       'argmax_changes': int((a.argmax(1) != b.argmax(1)).sum())}
            for key, value in metrics.items():
                assert np.isclose(value, recorded[key], rtol=1e-12, atol=1e-12), (model, name, key)
            metrics['images'] = 96
            metrics['changes_affecting_critical_predicted_classes'] = recorded['changes_affecting_critical_predicted_classes']
            metrics['topk'] = {}
            for k in (3, 5):
                x = np.argsort(-a, axis=1, kind='stable')[:, :k]
                y = np.argsort(-b, axis=1, kind='stable')[:, :k]
                metrics['topk'][str(k)] = {'effective_k': k,
                    'ordered_list_changes': int(np.any(x != y, axis=1).sum()),
                    'set_changes': int(np.any(np.sort(x, axis=1) != np.sort(y, axis=1), axis=1).sum())}
                if 'topk_tie_policy' in recorded:
                    assert metrics['topk'][str(k)] == recorded['topk'][str(k)]
                changed_member_probabilities = []
                for index, (left, right) in enumerate(zip(x, y)):
                    changed_members = list(set(left) ^ set(right))
                    if changed_members:
                        changed_member_probabilities.append(float(max(a[index, changed_members].max(), b[index, changed_members].max())))
                metrics['topk'][str(k)].update(
                    largest_probability_of_changed_member=max(changed_member_probabilities, default=0.0),
                    set_changes_with_member_probability_at_least_0_0001=sum(value >= .0001 for value in changed_member_probabilities))
            metrics['topk_tie_policy'] = 'Descending probability; equal probabilities use lower class index first.'
            result['comparisons'][model][name] = metrics
    result['limitations'] = ['Numerical parity is not accuracy or F1.',
        'Same-pixel export differences combine export conversion, FP16 weights and device arithmetic.',
        'Canonical versus native differences also include the stated crop/resize scope.',
        'Stored crops cannot reconstruct the original live padded camera ROI.']
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'status': 'passed', 'reference_models': 3, 'same_pixel_arms_validated': 4, 'human_labels_read': False}))


if __name__ == '__main__':
    main()
