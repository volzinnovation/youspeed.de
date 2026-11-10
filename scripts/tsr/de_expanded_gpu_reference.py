#!/usr/bin/env python3
"""Freeze CUDA predictions for hash-pinned expanded classifiers; never read labels."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import re
import shutil
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
try:
    from scripts.tsr.de_field_gpu_reference import comparison, tensor
except ModuleNotFoundError:
    # Remote qualification bundles keep the two scripts together in code/.
    from de_field_gpu_reference import comparison, tensor


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def read(path):
    return json.loads(Path(path).read_text())


def validate_registry(registry):
    rows = registry.get('models')
    if registry.get('schemaVersion') != 1 or not isinstance(rows, list) or not rows:
        raise ValueError('Expected a frozen model registry')
    ids = set()
    for row in rows:
        key, classes = row['id'], row['classes']
        if not re.fullmatch(r'[A-Za-z0-9_-]+', key) or key in ids:
            raise ValueError('Duplicate or invalid model ID')
        ids.add(key)
        if not re.fullmatch(r'[0-9a-f]{64}', row['sha256']):
            raise ValueError('Every model requires its exact checkpoint digest')
        if not isinstance(classes, list) or not classes or not all(isinstance(c, str) and c for c in classes):
            raise ValueError('Missing ordered model classes')
        if len(set(classes)) != len(classes):
            raise ValueError('Duplicate model class')
        if row.get('normalization') != 'RGB/255' or row.get('input_shape') != [1, 3, 224, 224]:
            raise ValueError('Unexpected input contract')
    longest = max((r['classes'] for r in rows), key=len)
    if any(longest[:len(r['classes'])] != r['classes'] for r in rows):
        raise ValueError('Models must share the unchanged class-index prefix')
    return rows


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--registry', type=Path, required=True)
    p.add_argument('--registry-sha256', required=True)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--manifest-sha256', required=True)
    p.add_argument('--android', type=Path)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    if a.output.exists() or sha(a.registry) != a.registry_sha256 or sha(a.manifest) != a.manifest_sha256:
        raise ValueError('Require new output and exact frozen registry/manifest')
    models = validate_registry(read(a.registry))
    images = read(a.manifest)['images']
    ids = [r['id'] for r in images]
    if not ids or len(ids) != len(set(ids)):
        raise ValueError('Image IDs must be nonempty and unique')
    canonical, hashes = [], []
    for row in images:
        value, digest = tensor(a.manifest.parent / row['canonicalPath'], row['canonicalSha256'])
        canonical.append(value); hashes.append(digest)
    canonical = np.stack(canonical)
    arrays = {'image_ids': np.asarray(ids), 'sources': np.asarray([r['source'] for r in images]),
              'canonical_tensor_sha256': np.asarray(hashes)}
    android, native, android_ids = None, None, []
    if a.android:
        android = dict(np.load(a.android / 'device-predictions.npz', allow_pickle=False))
        android_ids = android['image_ids'].astype(str).tolist()
        if len(android_ids) != len(set(android_ids)) or not set(android_ids).issubset(ids):
            raise ValueError('Android image identity differs')
        selected = [ids.index(i) for i in android_ids]
        if android['canonical_tensor_sha256'].astype(str).tolist() != [hashes[i] for i in selected]:
            raise ValueError('Android canonical pixels differ')
        prep = read(a.android / 'input-preparation.json')['images']
        if [r['id'] for r in prep] != android_ids:
            raise ValueError('Android native ordering differs')
        native_values, native_hashes = [], []
        for row in prep:
            value, digest = tensor(a.android / row['nativePreparedPng'], row['nativePreparedPngSha256'])
            if digest != row['nativeTensorSha256']:
                raise ValueError('Android native pixels differ')
            native_values.append(value); native_hashes.append(digest)
        if native_hashes != android['native_tensor_sha256'].astype(str).tolist():
            raise ValueError('Android native tensor digest mismatch')
        native = np.stack(native_values)
        arrays.update(android_image_ids=np.asarray(android_ids), android_native_tensor_sha256=np.asarray(native_hashes))
    import torch
    import ultralytics
    if not torch.cuda.is_available():
        raise RuntimeError('CUDA GPU is required; no CPU inference fallback')
    torch.set_num_threads(1)
    torch.set_num_interop_threads(1)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.backends.cudnn.benchmark = False
    torch.backends.cudnn.deterministic = True
    torch.use_deterministic_algorithms(True)
    a.output.mkdir(parents=True)
    shutil.copyfile(__file__, a.output / 'executed-reference.py')
    shutil.copyfile(Path(__file__).with_name('de_field_gpu_reference.py'), a.output / 'reference-helper.py')
    result = {'created_at': datetime.now(timezone.utc).isoformat(), 'script_sha256': sha(__file__),
              'helper_sha256': sha(Path(__file__).with_name('de_field_gpu_reference.py')),
              'registry_sha256': sha(a.registry), 'manifest_sha256': sha(a.manifest),
              'cuda_device': torch.cuda.get_device_name(0), 'torch': str(torch.__version__),
              'ultralytics': ultralytics.__version__, 'execution': 'CUDA FP32, batch one, TF32/AMP disabled',
              'truth_labels_read': False, 'accuracy_or_f1_computed': False, 'models': {}, 'comparisons': {}}
    if a.android:
        result['android_predictions_sha256'] = sha(a.android / 'device-predictions.npz')
        result['android_input_preparation_sha256'] = sha(a.android / 'input-preparation.json')
    for row in models:
        path = a.registry.parent / row['path']
        if sha(path) != row['sha256']:
            raise ValueError('Checkpoint digest mismatch')
        name, classes = row['id'], row['classes']
        model = ultralytics.YOLO(str(path), task='classify').model.float().eval().to('cuda:0')
        if [model.names[i] for i in range(len(model.names))] != classes:
            raise ValueError('Checkpoint class order differs')

        def infer(values):
            scores = []
            with torch.inference_mode():
                for value in values:
                    raw = model(torch.from_numpy(value[None]).to('cuda:0'))
                    out = raw[0] if isinstance(raw, tuple) else raw
                    prob = out.detach().float().cpu().numpy()[0]
                    if prob.shape != (len(classes),) or not np.isfinite(prob).all() or (prob < 0).any() or abs(float(prob.sum()) - 1) > 1e-5:
                        raise ValueError('Invalid model probability vector')
                    scores.append(prob)
            return np.stack(scores)

        scores = infer(canonical)
        arrays[name + '_classes'] = np.asarray(classes)
        arrays[name + '_canonical_scores'] = scores
        result['models'][name] = {'checkpoint_sha256': row['sha256'], 'class_count': len(classes), 'canonical_images': len(ids)}
        if android is not None:
            if android[name + '_classes'].astype(str).tolist() != classes:
                raise ValueError('Device class order differs')
            native_scores = infer(native)
            arrays[name + '_android_native_scores'] = native_scores
            result['comparisons'][name] = {
                'canonical_same_pixels': comparison(scores[selected], android[name + '_canonical_scores'], android_ids, classes),
                'native_same_pixels': comparison(native_scores, android[name + '_native_scores'], android_ids, classes),
                'preprocessing_native_vs_canonical': comparison(scores[selected], native_scores, android_ids, classes)}
        del model
        torch.cuda.empty_cache()
    prediction_path = a.output / 'gpu-reference-predictions.npz'
    np.savez_compressed(prediction_path, **arrays)
    result['predictions_sha256'] = sha(prediction_path)
    provenance_path = a.output / 'provenance.json'
    provenance_path.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    (a.output / 'complete.json').write_text(json.dumps({'status': 'complete', 'predictions_sha256': sha(prediction_path),
        'provenance_sha256': sha(provenance_path), 'truth_labels_read': False, 'accuracy_or_f1_computed': False}, indent=2) + '\n')
    print(json.dumps({'status': 'complete', 'models': len(models), 'images': len(ids)}))


if __name__ == '__main__':
    main()
