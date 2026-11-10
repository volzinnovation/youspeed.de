#!/usr/bin/env python3
"""Compare exact-pixel CoreML device vectors with a frozen CUDA reference.

No truth labels are read. This computes numerical agreement, not F1/accuracy.
The complete per-crop outputs belong outside the blind annotation package.
"""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
from PIL import Image


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--result', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--reference-sha256', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert sha(args.reference) == args.reference_sha256
    result = json.loads(args.result.read_text())
    manifest = json.loads(args.manifest.read_text())
    compute_units = manifest.get('computeUnits', 'cpuAndGPU')
    assert compute_units in {'cpuAndGPU', 'all'}, 'Unsupported or unreviewed benchmark compute policy'
    neural_engine_allowed = compute_units == 'all'
    assert result['status'] == 'complete'
    assert result['manifest_sha256'] == sha(args.manifest)
    assert result['device']['simulator'] is False
    reference = np.load(args.reference, allow_pickle=False)
    reference_ids = reference['image_ids'].astype(str).tolist()
    assert len(set(reference_ids)) == len(reference_ids)
    selected_ids = [row['id'] for row in manifest['images']]
    assert len(set(selected_ids)) == len(selected_ids)
    selected = [reference_ids.index(i) for i in selected_ids]
    prepared = {row['image_id']: row for row in result['input_preparation']}
    for row, reference_index in zip(manifest['images'], selected):
        path = args.manifest.parent / row['canonicalPath']
        assert sha(path) == row['canonicalSha256']
        with Image.open(path) as image:
            assert image.size == (224, 224) and image.format == 'PNG'
            pixels = np.asarray(image.convert('RGB'), dtype=np.uint8)
        rgb_sha = hashlib.sha256(pixels.tobytes()).hexdigest()
        assert rgb_sha == row['canonicalRGBSha256'] == prepared[row['id']]['canonical_rgb_sha256']
        tensor = pixels.astype(np.float32) / np.float32(255)
        tensor_sha = hashlib.sha256(tensor.astype('<f4').tobytes()).hexdigest()
        assert tensor_sha == str(reference['canonical_tensor_sha256'][reference_index])
    summaries, diagnostics = {}, {}
    for model in manifest['models']:
        blocks = [b for b in result['blocks'] if b['model_id'] == model['id'] and b['benchmark_round'] == 0]
        assert len(blocks) == 1
        block = blocks[0]
        assert block['source_sha256'] == model['sha256']
        assert block['requested_compute_units'] == compute_units
        assert block['neural_engine_allowed'] is neural_engine_allowed
        assert block['class_labels'] == model['classLabels'] == reference[model['id'] + '_classes'].astype(str).tolist()
        by_id = {r['image_id']: r for r in block['canonical_probabilities']}
        assert len(by_id) == len(selected_ids) and set(by_id) == set(selected_ids)
        device = np.asarray([by_id[i]['probabilities'] for i in selected_ids], dtype=np.float64)
        expected = reference[model['id'] + '_canonical_scores'][selected].astype(np.float64)
        assert device.shape == expected.shape == (len(selected_ids), model['classCount'])
        assert np.isfinite(device).all() and np.isfinite(expected).all()
        assert (device >= 0).all() and (expected >= 0).all()
        assert np.allclose(device.sum(axis=1), 1, atol=.002)
        assert np.allclose(expected.sum(axis=1), 1, atol=1e-5)
        delta = np.abs(device - expected)
        top_device, top_expected = device.argmax(axis=1), expected.argmax(axis=1)
        changes = np.flatnonzero(top_device != top_expected)
        top5_device = np.argsort(-device, axis=1, kind='stable')[:, :5]
        top5_expected = np.argsort(-expected, axis=1, kind='stable')[:, :5]
        top5_intersection = [len(set(a) & set(b)) for a, b in zip(top5_device, top5_expected)]
        summaries[model['id']] = {
            'images': len(selected_ids), 'class_count': model['classCount'], 'class_order_matches': True,
            'exact_rgb_and_reference_tensor_hashes_match': True,
            'top1_agree_count': int((top_device == top_expected).sum()),
            'top1_disagree_count': len(changes),
            'device_tied_top1_count': int(((device == device.max(axis=1, keepdims=True)).sum(axis=1) > 1).sum()),
            'reference_tied_top1_count': int(((expected == expected.max(axis=1, keepdims=True)).sum(axis=1) > 1).sum()),
            'top5_set_exact_agree_count': sum(n == 5 for n in top5_intersection),
            'top5_mean_set_intersection': float(np.mean(top5_intersection)),
            'max_probability_absolute_error': float(delta.max()),
            'mean_probability_absolute_error': float(delta.mean()),
            'p99_probability_absolute_error': float(np.quantile(delta, .99)),
            'p99_image_max_probability_absolute_error': float(np.quantile(delta.max(axis=1), .99)),
            'reference_top1_min_margin': float(np.min(np.sort(expected, axis=1)[:, -1] - np.sort(expected, axis=1)[:, -2])),
        }
        diagnostics[model['id']] = [
            {'image_id': selected_ids[i], 'reference_class': model['classLabels'][int(top_expected[i])],
             'device_class': model['classLabels'][int(top_device[i])],
             'reference_top1_probability': float(expected[i, top_expected[i]]),
             'device_top1_probability': float(device[i, top_device[i]]),
             'maximum_probability_absolute_error': float(delta[i].max())}
            for i in changes]
    output = {
        'status': 'compared', 'script_sha256': sha(__file__), 'result_sha256': sha(args.result),
        'manifest_sha256': sha(args.manifest), 'reference_sha256': sha(args.reference),
        'comparison': f'CoreML iPhone {compute_units} FP16 export versus frozen CUDA FP32, identical canonical RGB224 pixels and RGB/255',
        'requested_compute_units': compute_units, 'neural_engine_allowed': neural_engine_allowed,
        'ranking_policy': 'Descending probability with ascending frozen class index as the deterministic tie break',
        'native_input_scope': manifest.get('inputScope', 'Supplied native crop bytes; consult fixture provenance'),
        'models': summaries, 'truth_labels_read': False, 'accuracy_or_f1_computed': False,
        'limitations': ['Numerical agreement does not establish correctness or F1.',
                        ('CoreML all permits CPU, GPU and Neural Engine; no accelerator-exclusive execution assertion.'
                         if neural_engine_allowed else 'CoreML cpuAndGPU permits CPU fallback; no GPU-only placement assertion.'),
                        'Differences combine export, FP16 weights and runtime arithmetic; individual causes are not separated.',
                        'Native Vision vectors are excluded from exact-pixel reference parity: Vision owns internal resize/color conversion and its resulting tensor was not captured.',
                        'For aligned sign-window fixtures, native/canonical differences combine preprocessing and runtime; for whole stored-crop fixtures they also include ROI/context differences.']}
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'numerical-parity-summary.json').write_text(json.dumps(output, indent=2, allow_nan=False) + '\n')
    (args.output / 'numerical-parity-differences.json').write_text(json.dumps(diagnostics, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'status': 'compared', 'models': summaries}))


if __name__ == '__main__':
    main()
