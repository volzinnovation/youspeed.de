#!/usr/bin/env python3
"""Export first-round device probabilities with IDs, class order and input hashes."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    assert not args.output.exists(), 'Preserve immutable prediction exports'
    read = lambda name: json.loads((args.run / name).read_text())
    complete, config, prep = read('complete.json'), read('configuration.json'), read('input-preparation.json')['images']
    assert complete['status'] == 'complete'
    ids = [r['id'] for r in prep]
    assert ids == [r['id'] for r in config['images']] and len(set(ids)) == len(ids)
    arrays = {'image_ids': np.asarray(ids),
              'canonical_tensor_sha256': np.asarray([r['canonicalTensorSha256'] for r in prep]),
              'native_tensor_sha256': np.asarray([r['nativeTensorSha256'] for r in prep]),
              'native_prepared_paths': np.asarray([r['nativePreparedPng'] for r in prep])}
    for model in config['models']:
        candidates = [read(r['file']) for r in complete['trials'] if r['status'] == 'complete']
        candidates = [r for r in candidates if r['modelId'] == model['id'] and r['round'] == 0]
        assert len(candidates) == 1, 'Use a single GPU mode per reference export'
        trial = candidates[0]
        assert trial['classLabels'] == model['classLabels'] and trial['fallbackReason'] is None
        samples = {r['id']: r for r in trial['samples'] if r['repeat'] == 0}
        assert set(samples) == set(ids)
        arrays[model['id'] + '_classes'] = np.asarray(model['classLabels'])
        for path in ('canonical', 'native'):
            scores = np.asarray([samples[i][path]['scores'] for i in ids], dtype=np.float32)
            assert scores.shape == (len(ids), model['classCount']) and np.isfinite(scores).all()
            assert scores.argmax(1).tolist() == [samples[i][path]['argmax'] for i in ids]
            arrays[model['id'] + '_' + path + '_scores'] = scores
    np.savez_compressed(args.output, **arrays)
    print(json.dumps({'images': len(ids), 'models': len(config['models']), 'sha256': hashlib.sha256(args.output.read_bytes()).hexdigest(),
                      'human_labels_read': False, 'accuracy_or_f1_computed': False}))


if __name__ == '__main__':
    main()
