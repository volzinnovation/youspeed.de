#!/usr/bin/env python3
"""Freeze final d8 weights and development-only thresholds before audit inference."""
import json
from pathlib import Path
import shutil

from prepare_expanded_publication import inventory, sha, write

JOB = Path('/home/raphael/streetshots-d5-20261114')
AUDIT = JOB / 'geographic-audit-v1'
EXP = JOB / 'expanded-v1'
PREFIX = 'reviews/detector-expanded-2026-11-15/geographic-audit-v1/evaluation-definition'


def main():
    assert not (AUDIT / 'evaluation').exists()
    receipt = json.loads((JOB / 'publication-receipts/geographic-audit-references-v1.json').read_text())
    assert receipt['private'] and receipt['postverification'] and receipt['repo_type'] == 'dataset'
    reference = AUDIT / 'references/manifest.json'
    assert sha(reference) == receipt['manifest']['sha256'] == '3c88d89a34212d88dd97e3291269480e0d555f0e8e1d390dc94c83ba94d3a9cb'
    manifest = json.loads(reference.read_text())
    assert manifest['complete'] and manifest['student_predictions_seen'] is False
    assert manifest['counts'] == dict(selected=24, admitted=18, excluded=6, positive_images=8, reference_boxes=13)
    seal_path = EXP / 'latest-full/seal.json'
    seal = json.loads(seal_path.read_text())
    history = json.loads((EXP / 'latest-full/history.json').read_text())
    assert sha(EXP / 'latest-full/history.json') == seal['history_sha256']
    assert [r['epoch'] for r in history] == list(range(151))
    assert max(history, key=lambda r: (r['ap50_95'], -r['epoch']))['epoch'] == seal['selected_epoch']
    assert sha(EXP / 'latest-full/selected.pt') == seal['checkpoint_sha256']
    dev_path = EXP / 'latest-full-development/summary.json'
    dev = json.loads(dev_path.read_text())
    assert dev['split'] == 'validation' and dev['images'] == 17
    assert dev['native_input_manifest_sha256'] == '3e924732f8f4bcbd676a7f46a0c2feed39d8c507994eb1103261b65c2d4a214a'
    specs = []
    for name in ('d4', 'd8'):
        spec = next(r for r in dev['models'] if r['name'] == name)
        host_path = JOB / Path(spec['path']).relative_to('/job')
        assert sha(host_path) == spec['sha256']
        if name == 'd8': assert spec['sha256'] == seal['checkpoint_sha256']
        sweep = dev['results'][name + '-phone_windows']['development_sweep']
        assert [r['threshold'] for r in sweep] == [i / 100 for i in range(25, 100)]
        best = max(sweep, key=lambda r: (r['f2'], r['recall'], r['precision'], r['threshold']))
        specs.append({**spec, 'development_phone_threshold': best['threshold'],
                      'development_selected_metrics': best})
    native = AUDIT / 'native-inputs/manifest.json'
    assert sha(native) == 'fede3d99168203406e4509ea1cac5bd38749be2d47e0d88f03fc07e363d5ae79'
    natives = json.loads(native.read_text())
    assert natives['source_images'] == 18
    for row in natives['frames']:
        assert sha(AUDIT / 'native-inputs' / row['path']) == row['sha256']
    recipe = AUDIT / 'recipe'
    scripts = {name: sha(recipe / name) for name in
               ('evaluate_geographic_audit.py', 'train_evaluate.py', 'mobile_replay.py',
                'freeze_geographic_evaluation.py', 'test_blind_audit.py', 'assemble_blind_references.py')}
    definition = dict(schema='streetshots-geographic-evaluation-v1', status='frozen_before_student_inference',
        reference_manifest='references/manifest.json', reference_manifest_sha256=sha(reference),
        reference_dataset_revision=receipt['revision'], protocol_dataset_revision=manifest['protocol_dataset_revision'],
        native_directory='native-inputs', native_manifest_sha256=sha(native),
        models=specs, development_summary_sha256=sha(dev_path), selected_epoch=seal['selected_epoch'],
        training_seal_sha256=sha(seal_path), training_definition_revision='144ddf04c6771cad25b1a6c8770e214ab35b0e1e',
        threshold_selection='Separate maximum development phone F2; then recall, precision, higher threshold. No audit search.',
        fixed_phone_threshold=.840783, matching_iou=.5, inference_floor=.25, source_nms_iou=.45,
        per_pass_proposal_cap=12, ultralytics='8.4.213', quantize=32, tile=False, scripts=scripts,
        native_source_sha256=natives['app_source_sha256'], native_wrapper_sha256=natives['wrapper_sha256'],
        bootstrap=dict(iterations=2000, seed=14, unit='geographic group', paired=True),
        human_certified=False, ios_coreml_parity_verified=False, student_predictions_seen=False)
    root = AUDIT / 'evaluation-definition-publication'
    out = root / PREFIX
    out.mkdir(parents=True, exist_ok=False)
    write(out / 'definition.json', definition)
    for path in (reference, dev_path, seal_path, native):
        name = {reference: 'references.json', dev_path: 'development-summary.json',
                seal_path: 'training-seal.json', native: 'native-input-manifest.json'}[path]
        shutil.copy2(path, out / name)
    (out / 'recipe').mkdir()
    for name in scripts: shutil.copy2(recipe / name, out / 'recipe' / name)
    inventory(root, out, 'dataset', PREFIX + '/definition.json', AUDIT / 'evaluation-definition-inventory.json')
    print(json.dumps({'definition_sha256': sha(out / 'definition.json'), 'models': specs}))


if __name__ == '__main__':
    main()
