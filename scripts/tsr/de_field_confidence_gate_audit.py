#!/usr/bin/env python3
"""Static classifier confidence checks against pinned native source, without labels."""
import argparse
import hashlib
import json
from pathlib import Path

import numpy as np


def audit(reference, device, thresholds):
    thresholds = np.broadcast_to(np.asarray(thresholds, dtype=np.float64), reference.shape)
    a, b = reference - thresholds, device - thresholds
    return {'images': len(reference), 'reference_at_or_above': int((a >= 0).sum()),
            'device_at_or_above': int((b >= 0).sum()),
            'crossings_reference_pass_device_fail': int(((a >= 0) & (b < 0)).sum()),
            'crossings_reference_fail_device_pass': int(((a < 0) & (b >= 0)).sum()),
            'reference_minimum_absolute_margin': float(np.abs(a).min()) if len(a) else None,
            'device_minimum_absolute_margin': float(np.abs(b).min()) if len(b) else None,
            'reference_within_one_percentage_point': int((np.abs(a) <= .01).sum()),
            'device_within_one_percentage_point': int((np.abs(b) <= .01).sum()),
            'maximum_top1_confidence_abs_difference': float(np.abs(reference - device).max()) if len(a) else None}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--android', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    source_paths = {
        'iphone_manifest': 'iphone/SpeedConsumerApp/TSRModelPacks/DE.panoramax-bootstrap.tsrmodelpack/manifest.json',
        'android_manifest': 'android/app/src/main/assets/tsr/DE.panoramax-bootstrap.tsrmodelpack/manifest.json',
        'iphone_shadow': 'iphone/SpeedConsumerApp/TSRModelPacks/DE.panoramax-bootstrap.tsrmodelpack/shadow-runtime-v2.json',
        'iphone_classifier': 'iphone/SpeedConsumerApp/TrafficSignRuntime.swift',
        'iphone_qualification': 'iphone/SpeedConsumerApp/TrafficSignRecognition.swift',
        'iphone_presentation': 'iphone/SpeedConsumerApp/TrafficSignPresentation.swift',
        'iphone_inventory': 'iphone/SpeedConsumerApp/DriveSessionViewModel.swift',
        'android_classifier': 'android/app/src/main/java/de/youspeed/android/alpha/AndroidTrafficSignRuntime.kt',
        'android_qualification': 'android/app/src/main/java/de/youspeed/android/alpha/TrafficSignFusionEngine.kt',
        'android_inventory': 'android/app/src/main/java/de/youspeed/android/alpha/ConsumerSessionController.kt',
    }
    raw = {key: (args.root / path).read_bytes() for key, path in source_paths.items()}
    iphone, android, shadow = (json.loads(raw[k]) for k in ('iphone_manifest', 'android_manifest', 'iphone_shadow'))
    assert iphone['thresholds'] == android['thresholds']
    assert iphone['calibration']['runtime_output'] == android['calibration']['runtime_output'] == 'raw_score'
    iphone_classes = {row['class_id']: row['threshold'] for row in iphone['class_mapping']}
    android_classes = {row['class_id']: row['threshold'] for row in android['class_mapping']}
    assert iphone_classes == android_classes and len(iphone_classes) == 134
    assert 'max(0.9,$0.classThreshold)' in raw['iphone_inventory'].decode()
    assert '(0.9...1).contains(score)' in raw['iphone_presentation'].decode()
    assert 'maxOf(0.9, threshold)' in raw['android_inventory'].decode()
    levels = {
        'unknown_floor': iphone['thresholds']['unknown'],
        'provisional_fused_score_level_classifier_bound_only': iphone['thresholds']['provisional'],
        'confirmed_fused_score_level_classifier_bound_only': iphone['thresholds']['confirmed'],
        'shadow_classifier_confirmation': shadow['thresholds']['classifier_confirmed'],
        'presentation_inventory_classifier_floor': .9,
    }
    sha = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
    reference = np.load(args.reference / 'gpu-reference-predictions.npz', allow_pickle=False)
    device = np.load(args.android / 'device-predictions.npz', allow_pickle=False)
    indices = np.asarray([reference['image_ids'].tolist().index(value) for value in device['image_ids']])
    result = {'status': 'complete', 'human_labels_read': False, 'accuracy_or_f1_computed': False,
              'scope': 'Static classifier component only, at current repository bundled DE thresholds; no state-machine or pack changes.',
              'reference_predictions_sha256': sha(args.reference / 'gpu-reference-predictions.npz'),
              'device_predictions_sha256': sha(args.android / 'device-predictions.npz'),
              'sources': {key: {'path': path, 'sha256': hashlib.sha256(raw[key]).hexdigest()} for key, path in source_paths.items()},
              'levels': levels, 'mapped_class_thresholds': sorted(set(iphone_classes.values())),
              'native_platform_thresholds_match': True, 'comparisons': {},
              'limitations': [
                  'Both native pipelines combine classifier and detector scores using their minimum; detector scores are absent from classifier fixtures.',
                  'Confirmation also depends on frame count, timing, physical tracks, semantics, road context and runtime state; this is not an end-to-end acceptance replay.',
                  'The provisional0.45 and confirmed0.70 levels apply to fused/temporal scores; their classifier-only checks are necessary confidence bounds, not sufficient runtime decisions.',
                  'Current bundled packs have134 class mappings. Candidate city classes require an explicitly prepared136-class mapping/threshold package before deployment; no per-class thresholds are invented here.',
                  'Downloaded active model-pack/settings state was not inspected; source hashes identify the exact bundled configuration checked.',
                  'A zero crossing count on96 crops is not a general guarantee for values closer to a threshold or different live ROI.']}
    for model in ('baseline134', 'primary136'):
        classes = reference[model + '_classes'].tolist()
        assert classes == device[model + '_classes'].tolist()
        result['comparisons'][model] = {}
        for path in ('canonical', 'native'):
            a = reference[model + ('_canonical_scores' if path == 'canonical' else '_android_native_scores')]
            if path == 'canonical':
                a = a[indices]
            b = device[model + '_' + path + '_scores']
            assert np.array_equal(a.argmax(1), b.argmax(1)), 'Report top1 changes separately before threshold audit'
            amax, bmax = a.max(1).astype(np.float64), b.max(1).astype(np.float64)
            checks = {name: audit(amax, bmax, value) for name, value in levels.items()}
            labels = [classes[index] for index in a.argmax(1)]
            mapped = np.asarray([label in iphone_classes for label in labels])
            threshold = [max(iphone['thresholds']['unknown'], iphone_classes[label]) for label in labels if label in iphone_classes]
            checks['mapped_class_qualification_classifier_component'] = audit(amax[mapped], bmax[mapped], threshold)
            checks['predictions_without_current_deployed_class_mapping'] = int((~mapped).sum())
            result['comparisons'][model][path] = checks
    args.output.write_text(json.dumps(result, indent=2, allow_nan=False) + '\n')
    crossings = sum(row['crossings_reference_pass_device_fail'] + row['crossings_reference_fail_device_pass']
                    for paths in result['comparisons'].values() for checks in paths.values()
                    for row in checks.values() if isinstance(row, dict))
    print(json.dumps({'status': 'complete', 'static_crossings': crossings, 'human_labels_read': False, 'end_to_end_gate_replay': False}))


if __name__ == '__main__':
    main()
