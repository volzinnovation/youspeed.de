#!/usr/bin/env python3
"""Audit real Android GPU run outputs without access to evaluation labels."""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import re

import numpy as np
from PIL import Image


def read(path):
    return json.loads(path.read_text())


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def summary(values):
    value = np.asarray(values, dtype=np.float64)
    assert value.ndim == 1 and len(value) and np.isfinite(value).all() and (value >= 0).all()
    return dict(n=len(value), p50Ms=float(np.quantile(value, .5)), p95Ms=float(np.quantile(value, .95)),
                meanMs=float(value.mean()), minimumMs=float(value.min()), maximumMs=float(value.max()))


def compare_stats(actual, recorded):
    assert actual.keys() == recorded.keys()
    for key in actual:
        assert math.isclose(actual[key], recorded[key], rel_tol=1e-10, abs_tol=1e-8), (key, actual[key], recorded[key])


def tensor_hash(path):
    with Image.open(path) as image:
        assert image.size == (224, 224)
        array = np.asarray(image.convert('RGB'), dtype=np.float32) / np.float32(255)
    return hashlib.sha256(array.astype('<f4').tobytes()).hexdigest()


def delegation(log_text):
    result = {}
    active = None
    for line in log_text.splitlines():
        begin = re.search(r'YouSpeedClassifierBench: BEGIN (\S+)', line)
        if begin:
            active = begin.group(1)
            result[active] = {'partitions': [], 'opencl_initialized': False, 'gpu_kernel_count': None}
        if active:
            if 'Initialized OpenCL-based API.' in line:
                result[active]['opencl_initialized'] = True
            match = re.search(r'Replacing (\d+) out of (\d+) node\(s\) with delegate \(TfLiteGpuDelegateV2\) node, yielding (\d+) partitions for subgraph (\d+)', line)
            if match:
                n, total, partitions, subgraph = map(int, match.groups())
                result[active]['partitions'].append(dict(delegated_nodes=n, total_nodes=total, partitions=partitions, subgraph=subgraph))
            kernel = re.search(r'Created (\d+) GPU delegate kernels', line)
            if kernel:
                result[active]['gpu_kernel_count'] = int(kernel.group(1))
        if 'YouSpeedClassifierBench: END ' in line:
            active = None
    for row in result.values():
        nodes = row['partitions']
        row['status'] = ('fully_delegated' if all(p['delegated_nodes'] == p['total_nodes'] for p in nodes)
                         else 'partially_delegated') if nodes else 'unknown_missing_native_log'
    return result


def validate(run, inputs):
    config = read(run / 'configuration.json')
    complete = read(run / 'complete.json')
    assert complete['status'] == 'complete'
    assert complete['manifestSha256'] == sha(inputs / 'manifest.json')
    assert config == read(inputs / 'manifest.json')
    assert config['schemaVersion'] == 1
    image_ids = [r['id'] for r in config['images']]
    assert len(image_ids) == len(set(image_ids))
    models = {m['id']: m for m in config['models']}
    assert len(models) == len(config['models'])
    for model in models.values():
        assert sha(inputs / model['path']) == model['sha256']
        assert len(model['classLabels']) == model['classCount']
    preparations = read(run / 'input-preparation.json')['images']
    assert [r['id'] for r in preparations] == image_ids
    for prepared, source in zip(preparations, config['images']):
        assert sha(inputs / source['path']) == source['sha256']
        assert sha(inputs / source['canonicalPath']) == source['canonicalSha256']
        assert tensor_hash(inputs / source['canonicalPath']) == prepared['canonicalTensorSha256']
        native_path = run / prepared['nativePreparedPng']
        assert sha(native_path) == prepared['nativePreparedPngSha256']
        assert tensor_hash(native_path) == prepared['nativeTensorSha256']

    coverage = delegation((run / 'logcat.txt').read_text())
    modes = config.get('modes', ['gpu'])
    rounds = config.get('rounds', 3)
    repeats = config.get('repeatsPerImage', 1)
    assert len(complete['trials']) == len(modes) * len(models) * rounds
    groups = defaultdict(lambda: defaultdict(list))
    expected_combinations = {(m, mode, r) for m in models for mode in modes for r in range(rounds)}
    found_combinations = set()
    trial_rows = []
    hashes = {}
    prediction_trace = defaultdict(list)
    for receipt in complete['trials']:
        assert receipt['status'] == 'complete', receipt
        file = run / receipt['file']; hashes[file.name] = sha(file)
        trial = read(file)
        assert trial['status'] == 'complete'
        key = trial['modelId'], trial['requestedMode'], trial['round']
        assert key in expected_combinations and key not in found_combinations
        found_combinations.add(key)
        assert trial['actualBackend'] == trial['requestedMode'] and trial['actualBackend'].startswith('gpu')
        assert trial['fallbackReason'] is None
        model = models[key[0]]
        assert trial['modelSha256'] == model['sha256'] and trial['classLabels'] == model['classLabels']
        assert trial['warmupCount'] == config.get('warmupCount', 20)
        assert len(trial['samples']) == len(image_ids) * repeats
        seen = set(); measured = defaultdict(list)
        for sample in trial['samples']:
            pair = sample['id'], sample['repeat']
            assert pair not in seen and pair[0] in image_ids and 0 <= pair[1] < repeats
            seen.add(pair)
            for path in ('canonical', 'native'):
                metric = sample[path]
                assert 0 <= metric['argmax'] < model['classCount']
                if trial['round'] == 0 and sample['repeat'] == 0:
                    vector = np.asarray(metric['scores'], dtype=np.float64)
                    assert vector.shape == (model['classCount'],) and np.isfinite(vector).all()
                    assert int(vector.argmax()) == metric['argmax']
                    assert math.isclose(float(vector.sum()), metric['scoreSum'], abs_tol=1e-7)
                    assert math.isclose(float(vector.max()), metric['maxScore'], abs_tol=1e-7)
                prediction_trace[(key[0], key[1], path, sample['id'])].append(metric['argmax'])
            measured['canonicalForward'].append(sample['canonical']['forwardMs'])
            measured['nativeForward'].append(sample['native']['forwardMs'])
            measured['nativePreprocess'].append(sample['native']['preprocessMs'])
            measured['nativePreprocessAndForward'].append(sample['native']['preprocessAndForwardMs'])
            assert sample['native']['preprocessAndForwardMs'] >= sample['native']['forwardMs'] + sample['native']['preprocessMs']
        for scope, values in measured.items():
            compare_stats(summary(values), trial[scope])
            groups[key[:2]][scope].extend(values)
        row = {k: trial[k] for k in ['trialId', 'modelId', 'round', 'requestedMode', 'actualBackend', 'loadMs', 'firstInferenceMs']}
        row['delegation'] = coverage.get(trial['trialId'], {'status': 'unknown_missing_native_log'})
        row['thermal_statuses'] = [trial[k]['thermalStatus'] for k in ['deviceStart', 'deviceAfterWarmup', 'deviceEnd']]
        row['pss_kb'] = [trial[k]['totalPssKb'] for k in ['deviceStart', 'deviceAfterWarmup', 'deviceEnd']]
        row.update({scope: trial[scope] for scope in measured})
        trial_rows.append(row)
    assert found_combinations == expected_combinations
    pooled = [{'modelId': key[0], 'mode': key[1], **{scope: summary(values) for scope, values in measures.items()}}
              for key, measures in groups.items()]
    changed = [{'modelId': key[0], 'mode': key[1], 'path': key[2], 'imageId': key[3], 'argmax_sequence': guesses}
               for key, guesses in prediction_trace.items() if len(set(guesses)) > 1]
    return {'status': 'passed', 'schemaVersion': 1, 'manifestSha256': complete['manifestSha256'],
            'device': read(run / 'device-start.json'), 'imageCount': len(image_ids),
            'trials': trial_rows, 'pooled': pooled, 'repeated_argmax_changes': changed,
            'all_graphs_fully_gpu_delegated': all(r['delegation']['status'] == 'fully_delegated' for r in trial_rows),
            'native_input_tensor_hashes_verified': True, 'canonical_input_tensor_hashes_verified': True,
            'trial_sha256': hashes, 'logcatSha256': sha(run / 'logcat.txt'),
            'limitations': ['Real device classifier-only timings; detector/camera/OCR excluded',
                            'Native totals exclude file decoding, measured separately during input loading',
                            'Fresh interpreter does not imply flushed OS file caches',
                            'No human labels used and no accuracy/F1 is calculated',
                            'No native screen interaction or production modelpack change'],
            'human_labels_used': False, 'production_deployment': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run', type=Path, required=True)
    parser.add_argument('--inputs', type=Path, required=True)
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    result = validate(args.run, args.inputs)
    output = args.output or args.run / 'independent-validation.json'
    output.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'status': result['status'], 'images': result['imageCount'], 'trials': len(result['trials']),
                      'fully_gpu_delegated': result['all_graphs_fully_gpu_delegated']}))


if __name__ == '__main__':
    main()
