#!/usr/bin/env python3
"""Validate identity, GPU configuration, order and raw on-device timing rows.

No ground-truth labels are read and no F1 or accuracy is inferred. Full output
vectors support a separate numerical-parity check against frozen references.
"""
import argparse
from collections import Counter, defaultdict
import csv
import hashlib
import json
import math
from pathlib import Path


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def artifact_sha(path):
    path = Path(path)
    if path.is_file():
        return sha(path)
    entries = []
    for child in path.rglob('*'):
        assert not child.is_symlink(), 'Symlinks are not valid model artifacts'
        if child.is_file():
            entries.append((child.relative_to(path).as_posix(), sha(child)))
    assert entries, 'Missing or empty model artifact'
    data = ''.join(name + '\0' + digest + '\n' for name, digest in sorted(entries))
    return hashlib.sha256(data.encode('utf-8')).hexdigest()


def validate_probability_row(vector, labels, top_label, top_score=None):
    assert len(vector) == len(labels) and all(math.isfinite(x) and x >= 0 for x in vector)
    assert abs(sum(vector) - 1) < .002
    assert top_label in labels and vector[labels.index(top_label)] == max(vector)
    if top_score is not None:
        assert math.isfinite(top_score) and abs(top_score - vector[labels.index(top_label)]) < 1e-9


def compute_policy(manifest):
    mode = manifest.get('computeUnits', 'cpuAndGPU')
    assert mode in {'cpuAndGPU', 'all'}, 'Unsupported or unreviewed benchmark compute policy'
    return mode, mode == 'all'


def assert_total_contains_components(total, components):
    assert all(math.isfinite(value) and value >= 0 for value in [total, *components])
    # One picosecond in millisecond units: absorb binary64 summation rounding,
    # far below the nanosecond timer resolution, without hiding real overlap.
    assert total + 1e-9 >= sum(components)


def percentile(values, q):
    ordered = sorted(values)
    point = (len(ordered) - 1) * q
    lo, hi = math.floor(point), math.ceil(point)
    return ordered[lo] + (ordered[hi] - ordered[lo]) * (point - lo)


def stats(values):
    assert values and all(math.isfinite(v) and v >= 0 for v in values)
    return {'samples': len(values), 'p50_ms': percentile(values, .5), 'p95_ms': percentile(values, .95),
            'mean_ms': sum(values) / len(values), 'min_ms': min(values), 'max_ms': max(values)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--result', type=Path, required=True)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    result, manifest = json.loads(a.result.read_text()), json.loads(a.manifest.read_text())
    compute_units, neural_engine_allowed = compute_policy(manifest)
    assert result['status'] == 'complete' and result['manifest_sha256'] == sha(a.manifest)
    assert result['device']['simulator'] is False
    assert result['production_app_modified'] is False
    images = {r['id']: r for r in manifest['images']}
    models = {r['id']: r for r in manifest['models']}
    assert len(images) == len(manifest['images']) and len(models) == len(manifest['models'])
    for image in images.values():
        assert sha(a.manifest.parent / image['path']) == image['sha256']
        assert sha(a.manifest.parent / image['canonicalPath']) == image['canonicalSha256']
    for model in models.values():
        assert len(model['classLabels']) == len(set(model['classLabels'])) == model['classCount']
        assert artifact_sha(a.manifest.parent / model['path']) == model['sha256']
    assert len(result['blocks']) == len(models) * manifest['rounds']
    assert len(result['input_preparation']) == len(images)
    assert {row['image_id'] for row in result['input_preparation']} == set(images)
    for row in result['input_preparation']:
        assert row['canonical_rgb_sha256'] == images[row['image_id']]['canonicalRGBSha256']
    grouped = defaultdict(list)
    actual_order = []
    round_rows = []
    for block in result['blocks']:
        model = models[block['model_id']]
        assert block['requested_compute_units'] == compute_units
        assert block['neural_engine_allowed'] is neural_engine_allowed
        assert block['source_sha256'] == model['sha256'] and block['class_labels'] == model['classLabels']
        assert block['warmup_count'] == manifest['warmupCount']
        round_index = block['benchmark_round']
        assert 0 <= round_index < manifest['rounds']
        actual_order.append((round_index, block['model_id']))
        expected = {(image_id, round_index, rep) for image_id in images for rep in range(manifest['repeatsPerImage'])}
        for key in ['canonical_timings', 'native_timings']:
            assert {(r['image_id'], r['round'], r['repetition']) for r in block[key]} == expected
            assert len(block[key]) == len(expected)
        for row in block['canonical_timings']:
            assert 0 <= row['top1_index'] < model['classCount']
        for row in block['native_timings']:
            assert row['top1_label'] in model['classLabels']
            assert math.isfinite(row['top1_score']) and 0 <= row['top1_score'] <= 1.002
            assert_total_contains_components(row['total_ms'],
                [row['decode_ms'], row['request_setup_ms'], row['vision_scale_fill_and_inference_ms']])
            if round_index == 0 and row['repetition'] == 0:
                validate_probability_row(row['probabilities'], model['classLabels'], row['top1_label'], row['top1_score'])
        pairs = [('canonical_forward_summary', 'canonical_timings', 'forward_ms'),
                 ('native_vision_summary', 'native_timings', 'vision_scale_fill_and_inference_ms'),
                 ('native_decode_summary', 'native_timings', 'decode_ms'),
                 ('native_total_summary', 'native_timings', 'total_ms')]
        for summary, key, field in pairs:
            calculated = stats([r[field] for r in block[key]])
            assert calculated['samples'] == block[summary]['count']
            for measure in ['p50_ms', 'p95_ms', 'mean_ms', 'min_ms', 'max_ms']:
                assert abs(calculated[measure] - block[summary][measure]) < 1e-9
        for row in block['canonical_probabilities']:
            vector = row['probabilities']
            assert row['canonical_rgb_sha256'] == images[row['image_id']]['canonicalRGBSha256']
            assert 0 <= row['top1_index'] < model['classCount']
            validate_probability_row(vector, model['classLabels'], row['top1_label'])
            assert row['top1_label'] == model['classLabels'][row['top1_index']]
        if round_index == 0:
            assert len(block['canonical_probabilities']) == len(images)
            assert {r['image_id'] for r in block['canonical_probabilities']} == set(images)
        plan = block.get('compute_plan', {})
        if plan.get('status') == 'available':
            if not neural_engine_allowed:
                assert not plan['preferred_operation_counts'].get('NeuralEngine', 0)
            assert Counter(r['preferred'] for r in plan['operations']) == plan['preferred_operation_counts']
        grouped[block['model_id']].append(block)
        round_rows.append({'model': block['model_id'], 'round': round_index,
                           'canonical_p50_ms': block['canonical_forward_summary']['p50_ms'],
                           'canonical_p95_ms': block['canonical_forward_summary']['p95_ms'],
                           'vision_p50_ms': block['native_vision_summary']['p50_ms'],
                           'vision_p95_ms': block['native_vision_summary']['p95_ms'],
                           'load_ms': block['model_load_ms'], 'first_forward_ms': block['first_forward_ms'],
                           'thermal_before': block['memory_before_load']['thermal_state'],
                           'thermal_after': block['memory_after']['thermal_state']})
    initial_order = result['model_order']
    assert len(initial_order) == len(models) and set(initial_order) == set(models)
    expected_order = [(r, model) for r in range(manifest['rounds']) for model in (initial_order if r % 2 == 0 else initial_order[::-1])]
    assert actual_order == expected_order
    assert len(set(actual_order)) == len(models) * manifest['rounds']
    summaries = {}
    for model, blocks in grouped.items():
        rows = [r for b in blocks for r in b['canonical_timings']]
        native = [r for b in blocks for r in b['native_timings']]
        snapshots = [s for b in blocks for s in
                     [b['memory_before_load'], b['memory_after']] +
                     [r['snapshot'] for r in b['memory_round_samples']]]
        predictions, native_predictions = defaultdict(set), defaultdict(set)
        for r in rows:
            predictions[r['image_id']].add(r['top1_index'])
        for r in native:
            native_predictions[r['image_id']].add(r['top1_label'])
        summaries[model] = {
            'canonical_forward': stats([r['forward_ms'] for r in rows]),
            'native_vision_preprocess_plus_inference': stats([r['vision_scale_fill_and_inference_ms'] for r in native]),
            'native_request_setup_plus_vision': stats([r['request_setup_ms'] + r['vision_scale_fill_and_inference_ms'] for r in native]),
            'native_decode': stats([r['decode_ms'] for r in native]),
            'native_total': stats([r['total_ms'] for r in native]),
            'maximum_sampled_resident_bytes': max(s['resident_bytes'] for s in snapshots),
            'thermal_states': sorted({s['thermal_state'] for s in snapshots}),
            'unstable_canonical_top1_image_ids': sorted(k for k, v in predictions.items() if len(v) > 1),
            'unstable_native_top1_image_ids': sorted(k for k, v in native_predictions.items() if len(v) > 1),
            'compute_plan': blocks[0].get('compute_plan', {'status': 'unavailable'}),
        }
    a.output.mkdir(parents=True, exist_ok=True)
    with (a.output / 'round-comparison.csv').open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(round_rows[0])); writer.writeheader(); writer.writerows(round_rows)
    output = {'status': 'passed', 'result_sha256': sha(a.result), 'manifest_sha256': sha(a.manifest),
              'validator_sha256': sha(__file__), 'device': result['device'], 'images': len(images),
              'rounds': manifest['rounds'], 'counterbalanced_order': actual_order, 'models': summaries,
              'input_scope': manifest.get('inputScope', 'Supplied native crop bytes; consult fixture provenance'),
              'requested_compute_units': compute_units, 'neural_engine_allowed': neural_engine_allowed,
              'accuracy_or_f1_computed': False,
              'limitations': [
                              ('CoreML all permits CPU, GPU and Neural Engine execution; compute plan is anticipated placement, not an observed hardware trace'
                               if neural_engine_allowed else
                               'CoreML cpuAndGPU permits CPU fallback and excludes Neural Engine; compute plan is anticipated placement, not a GPU kernel trace'),
                              'Classification timing excludes detector, OCR, tracking and camera pipeline',
                              'Canonical forward excludes decoding/buffer preparation; Vision time includes its resize/color conversion',
                              'CoreML canonical prediction includes model-integrated RGB/255; Android canonical input is normalized before its forward timer',
                              'For decode-excluded native comparison, request_setup_plus_vision is closest to Android Canvas/RGB preparation plus inference; APIs and scheduling still differ',
                              'Model load is per-process/per-round, not reboot-cold; filesystem/OS caches may apply',
                              'Resident memory is sampled and is not true peak GPU memory',
                              'Native inputs are supplied crop bytes, not reconstructed live-frame padded ROI']}
    (a.output / 'validation-summary.json').write_text(json.dumps(output, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'status': 'passed', 'images': len(images), 'models': {m: s['canonical_forward'] for m, s in summaries.items()}}))


if __name__ == '__main__':
    main()
