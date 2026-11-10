#!/usr/bin/env python3
"""Frozen GPU predictions and Android export parity, without loading truth labels."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
from PIL import Image


CHECKPOINTS = {
    'baseline134': ('course', 'models/baseline.pt', 'f8277a3790fd3357b3ca31a086c7dc9f365785c7fa44bfd3b5c68834555699c7'),
    'primary136': ('root', 'models/primary/de136-primary.pt', '2918071223bc115ae1341cd2ce363dad04b3ba3d377112e79340ed1a12964005'),
    'source136': ('root', 'models/source-adaptation/de136-source-adaptation.pt', '0bf9a9f070a6525e66bd2b79cc7a33eba843346e2c5716a973004059738a26a6'),
}


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def write(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def critical(label):
    return label.startswith(('maxspeed:', 'priority:')) or label in {
        'city:start', 'city:end', 'zone:30', 'zone:30:end', 'zone:end', 'no:end',
        'motorway:end', 'trunk:end', 'no_overtaking:end', 'give_way', 'stop',
    }


def tensor(path, expected_file_sha):
    assert sha(path) == expected_file_sha, str(path)
    with Image.open(path) as image:
        assert image.format == 'PNG' and image.size == (224, 224), str(path)
        value = np.asarray(image.convert('RGB'), dtype=np.float32) / np.float32(255)
    digest = hashlib.sha256(value.astype('<f4').tobytes()).hexdigest()
    return np.ascontiguousarray(value.transpose(2, 0, 1)), digest


def comparison(reference, device, ids, classes):
    assert reference.shape == device.shape == (len(ids), len(classes))
    assert np.isfinite(reference).all() and np.isfinite(device).all()
    assert (reference >= 0).all() and (device >= 0).all()
    assert np.allclose(reference.sum(1), 1, atol=1e-5)
    assert np.allclose(device.sum(1), 1, atol=.02)
    delta = np.abs(reference.astype(np.float64) - device.astype(np.float64))
    ref_best, dev_best = reference.argmax(1), device.argmax(1)
    changed = np.flatnonzero(ref_best != dev_best)
    rows = []
    for i in changed:
        ref_order = np.argsort(reference[i])[::-1]
        dev_order = np.argsort(device[i])[::-1]
        a, b = int(ref_best[i]), int(dev_best[i])
        rows.append({'image_id': str(ids[i]), 'reference_class': classes[a], 'device_class': classes[b],
                     'reference_top1_probability': float(reference[i, a]), 'device_top1_probability': float(device[i, b]),
                     'reference_top1_top2_margin': float(reference[i, ref_order[0]] - reference[i, ref_order[1]]),
                     'device_top1_top2_margin': float(device[i, dev_order[0]] - device[i, dev_order[1]]),
                     'reference_probability_of_device_choice': float(reference[i, b]),
                     'device_probability_of_reference_choice': float(device[i, a]),
                     'max_probability_abs_error': float(delta[i].max()),
                     'affects_critical_predicted_class': critical(classes[a]) or critical(classes[b])})
    class_rows = [{'class_id': label, 'critical': critical(label),
                   'reference_predictions': int((ref_best == index).sum()),
                   'device_predictions': int((dev_best == index).sum()),
                   'switches_away_from_reference_class': int(((ref_best == index) & (dev_best != index)).sum()),
                   'switches_into_device_class': int(((dev_best == index) & (ref_best != index)).sum())}
                  for index, label in enumerate(classes)]
    topk = {}
    for k in (3, 5):
        effective = min(k, len(classes))
        # Equal probabilities use lower class index first across NumPy versions.
        ref_order = np.argsort(-reference, axis=1, kind='stable')[:, :effective]
        dev_order = np.argsort(-device, axis=1, kind='stable')[:, :effective]
        topk[str(k)] = {
            'effective_k': effective,
            'ordered_list_changes': int(np.any(ref_order != dev_order, axis=1).sum()),
            'set_changes': int(np.any(np.sort(ref_order, axis=1) != np.sort(dev_order, axis=1), axis=1).sum()),
        }
    return {'images': len(ids), 'classes': len(classes), 'max_probability_abs_error': float(delta.max()),
            'p99_probability_abs_error': float(np.quantile(delta, .99)),
            'p99_image_max_probability_abs_error': float(np.quantile(delta.max(1), .99)),
            'mean_probability_abs_error': float(delta.mean()), 'argmax_changes': len(rows),
            'changes_affecting_critical_predicted_classes': sum(r['affects_critical_predicted_class'] for r in rows),
            'changes': rows, 'per_predicted_class': class_rows, 'topk': topk,
            'topk_tie_policy': 'Descending probability; equal probabilities use lower class index first.',
            'interpretation': 'Numerical/reference prediction differences only; no truth labels, no FP/FN or F1'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--course', type=Path, required=True)
    parser.add_argument('--android', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists(), 'Use a new immutable output directory'
    import torch
    import ultralytics
    assert torch.cuda.is_available(), 'GPU reference required; no CPU inference fallback'
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    torch.use_deterministic_algorithms(True)
    args.output.mkdir(parents=True)
    shutil.copyfile(__file__, args.output / 'executed-de_field_gpu_reference.py')
    crop_root = args.root / 'inputs/fresh-crops'
    manifest_path = crop_root / 'benchmark-all120.json'
    manifest = read(manifest_path)
    assert manifest['schemaVersion'] == 1 and len(manifest['images']) == 120
    ids = [r['id'] for r in manifest['images']]
    assert len(set(ids)) == 120
    canonical, canonical_hashes = [], []
    for row in manifest['images']:
        value, digest = tensor(crop_root / row['canonicalPath'], row['canonicalSha256'])
        canonical.append(value); canonical_hashes.append(digest)
    canonical = np.stack(canonical)
    android = {k: v for k, v in np.load(args.android / 'device-predictions.npz', allow_pickle=False).items()}
    android_ids = android['image_ids'].astype(str).tolist()
    assert len(android_ids) == len(set(android_ids)) == 96
    selected = np.asarray([ids.index(i) for i in android_ids])
    assert android['canonical_tensor_sha256'].astype(str).tolist() == [canonical_hashes[i] for i in selected]
    prep = read(args.android / 'input-preparation.json')['images']
    assert [p['id'] for p in prep] == android_ids
    native, native_hashes = [], []
    for row in prep:
        value, digest = tensor(args.android / row['nativePreparedPng'], row['nativePreparedPngSha256'])
        assert digest == row['nativeTensorSha256']
        native.append(value); native_hashes.append(digest)
    native = np.stack(native)
    assert native_hashes == android['native_tensor_sha256'].astype(str).tolist()
    arrays = {'image_ids': np.asarray(ids), 'sources': np.asarray([r['source'] for r in manifest['images']]),
              'canonical_tensor_sha256': np.asarray(canonical_hashes), 'android_image_ids': np.asarray(android_ids),
              'android_native_tensor_sha256': np.asarray(native_hashes)}
    classes136 = read(args.root / 'models/primary/provenance.json')['classes']
    assert len(classes136) == 136 and classes136[-2:] == ['city:start', 'city:end']
    provenance = {
        'created_at': datetime.now(timezone.utc).isoformat(), 'script_sha256': sha(__file__),
        'manifest_sha256': sha(manifest_path), 'android_predictions_sha256': sha(args.android / 'device-predictions.npz'),
        'torch': str(torch.__version__), 'ultralytics': ultralytics.__version__,
        'cuda_device': torch.cuda.get_device_name(0), 'execution': 'GPU0 CUDA FP32 batch1; TF32 and AMP disabled; deterministic algorithms',
        'pixel_inputs': 'Exact224RGB PNG bytes; RGB/255 NHWC hashes verified before NCHW transpose. No resize in reference.',
        'android_native_input_scope': read(args.android / 'configuration.json').get('inputScope',
            'Whole stored capture crop; canonical input uses frozen sign_box. This contrast includes crop context, not just resize.'),
        'truth_labels_read': False, 'accuracy_or_f1_computed': False, 'cpu_inference_benchmark': False,
        'models': {}, 'comparisons': {},
        'limitations': ['Same-pixel Android comparisons combine export/FP16-weight/GPU-arithmetic differences; those mechanisms are not individually identified.',
                        'PyTorch native-vs-canonical comparison isolates supplied preprocessing/crop differences. Consult android_native_input_scope: the first run used whole stored crops, not sign windows.',
                        'No predicted class difference is a confirmed label error before human review.',
                        'Frozen predictions may be scored only after the independent review labels are approved.'],
    }
    for name, (namespace, relative, expected) in CHECKPOINTS.items():
        path = (args.course if namespace == 'course' else args.root) / relative
        assert sha(path) == expected, name
        model = ultralytics.YOLO(str(path), task='classify').model.float().eval().to('cuda:0')
        model_names = model.names
        classes = [model_names[i] for i in range(len(model_names))] if isinstance(model_names, dict) else list(model_names)
        expected_classes = classes136[:134] if name == 'baseline134' else classes136
        assert classes == expected_classes, name
        arrays[name + '_classes'] = np.asarray(classes)
        def infer(values):
            rows = []
            with torch.inference_mode():
                for value in values:
                    raw = model(torch.from_numpy(value[None]).to('cuda:0'))
                    probabilities = raw[0] if isinstance(raw, tuple) else raw
                    probability = probabilities.detach().float().cpu().numpy()[0]
                    assert probability.shape == (len(classes),) and np.isfinite(probability).all()
                    assert (probability >= 0).all() and abs(float(probability.sum()) - 1) < 1e-5
                    rows.append(probability)
            return np.stack(rows)
        scores = infer(canonical)
        arrays[name + '_canonical_scores'] = scores
        model_meta = {'checkpoint_sha256': expected, 'class_count': len(classes), 'canonical_images': 120}
        if namespace == 'root':
            meta_path = path.parent / 'provenance.json'
            meta = read(meta_path)
            assert meta['artifact_sha256'] == expected and meta['classes'] == classes
            model_meta.update(source_checkpoint_sha256=meta['source_checkpoint_sha256'], packaging_provenance_sha256=sha(meta_path))
        if name != 'source136':
            assert android[name + '_classes'].astype(str).tolist() == classes
            native_scores = infer(native)
            arrays[name + '_android_native_scores'] = native_scores
            provenance['comparisons'][name] = {
                'canonical_same_pixels_export_gpu_difference': comparison(scores[selected], android[name + '_canonical_scores'], android_ids, classes),
                'android_native_same_pixels_export_gpu_difference': comparison(native_scores, android[name + '_native_scores'], android_ids, classes),
                'pytorch_preprocessing_only_native_vs_canonical': comparison(scores[selected], native_scores, android_ids, classes),
            }
        provenance['models'][name] = model_meta
        del model
        torch.cuda.empty_cache()
        print(json.dumps({'model': name, 'canonical_images': 120, 'native_images': 0 if name == 'source136' else 96}), flush=True)
    np.savez_compressed(args.output / 'gpu-reference-predictions.npz', **arrays)
    provenance['predictions_sha256'] = sha(args.output / 'gpu-reference-predictions.npz')
    write(args.output / 'provenance-and-android-parity.json', provenance)
    write(args.output / 'complete.json', {'status': 'complete', 'predictions_sha256': provenance['predictions_sha256'],
                                         'provenance_sha256': sha(args.output / 'provenance-and-android-parity.json'),
                                         'truth_labels_read': False, 'accuracy_or_f1_computed': False})
    print(json.dumps({'status': 'complete', 'models': 3, 'canonical_images_each': 120, 'android_native_images_each': 96}))


if __name__ == '__main__':
    main()
