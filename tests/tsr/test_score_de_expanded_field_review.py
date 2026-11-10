"""Synthetic pixels and labels only; never approves or scores actual field crops."""
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

import numpy as np
from PIL import Image
import pytest

from scripts.tsr import de_expanded_gpu_reference
from scripts.tsr import score_de_expanded_field_review as scorer
from scripts.tsr.de_label_review import load_review


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


def reseal_predictions(corpus, values):
    reference = corpus['reference']
    path = reference / 'gpu-reference-predictions.npz'
    np.savez_compressed(path, **values)
    provenance = scorer.read(reference / 'provenance.json')
    provenance['predictions_sha256'] = scorer.sha(path)
    write(reference / 'provenance.json', provenance)
    complete = scorer.read(reference / 'complete.json')
    complete.update(predictions_sha256=scorer.sha(path), provenance_sha256=scorer.sha(reference / 'provenance.json'))
    write(reference / 'complete.json', complete)


@pytest.fixture
def corpus(tmp_path):
    original = tmp_path / 'original'
    evidence = tmp_path / 'review/main120'
    reference = tmp_path / 'reference'
    classes = [f'c{i:03}' for i in range(136)] + [
        'bus:stop', 'supplementary:plate', 'maxspeed:90', 'DE:156-10', 'DE:325.1', 'DE:325.2']
    for path, values in [(original, classes[:136]), (evidence, classes), (evidence.parent, classes)]:
        write(path / 'class-index.json', {'classes': values})
    catalog = evidence.parent / 'catalog-reference.json'
    write(catalog, {'signs': [{'class_id': c, 'label': {'en': c}} for c in classes]})
    write(original / 'intake/selection-frozen.json', {'synthetic_fixture': True})
    selection = scorer.sha(original / 'intake/selection-frozen.json')
    images, proposals, samples, tensor_hashes = [], [], [], []
    for i, (key, source) in enumerate([('A001', 'android'), ('A002', 'android'), ('P001', 'panoramax'), ('P002', 'panoramax')]):
        path = evidence / f'intake/native/{key}.png'
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new('RGB', (224, 224), (i + 2, 5, 9)).save(path)
        images.append({'id': key, 'source': source, 'path': f'native/{key}.png',
                       'canonicalPath': f'native/{key}.png', 'sha256': scorer.sha(path), 'canonicalSha256': scorer.sha(path)})
        samples.append({**images[-1], 'blind_id': key})
        proposals.append({'id': key, 'proposed_class_id': 'c000', 'confidence': 'clear', 'visual_reason': 'Synthetic fixture'})
        pixels = np.asarray(Image.open(path), dtype=np.float32) / np.float32(255)
        tensor_hashes.append(hashlib.sha256(pixels.astype('<f4').tobytes()).hexdigest())
    for root in [evidence, original]:
        write(root / 'intake/benchmark-all120.json', {'schemaVersion': 1, 'images': images})
    write(original / 'intake/evaluation-blind.json', {'classes': classes[:136], 'selection_sha256': selection, 'samples': samples})
    old_blind = original / 'intake/evaluation-blind.json'
    write(original / 'intake/data-quality-addendum.json', {'selection_sha256': selection, 'historical_non_uuid_source_records': 0})
    repeat = original / 'intake/repeat-audit.json'
    write(repeat, {'manifest_sha256': scorer.sha(old_blind), 'labels_or_predictions_used': False,
                   'conservative_route_blocks': [{'id': 'r1', 'members': ['A001', 'A002']},
                                                {'id': 'r2', 'members': ['P001']}, {'id': 'r3', 'members': ['P002']}]})
    write(evidence / 'intake/blind/proposed-phone-labels.json', {'labels': proposals[:2]})
    write(evidence / 'intake/blind/proposed-panoramax-labels.json', {'labels': proposals[2:]})
    manifest_sha = scorer.sha(evidence / 'intake/benchmark-all120.json')
    class_sha = scorer.sha(evidence / 'class-index.json')
    blind = scorer.read(old_blind)
    blind.update(classes=classes, expanded_review_provenance={
        'source_evaluation_blind_sha256': scorer.sha(old_blind),
        'source_manifest_sha256': manifest_sha, 'class_index_sha256': class_sha})
    write(evidence / 'intake/evaluation-blind.json', blind)
    (evidence / 'provenance').mkdir()
    shutil.copyfile(original / 'class-index.json', evidence / 'provenance/source-class-index.json')
    shutil.copyfile(old_blind, evidence / 'provenance/source-evaluation-blind.json')
    package = {'records': 4, 'catalog_reference_sha256': scorer.sha(catalog), 'class_index_sha256': class_sha,
               'source_manifest_sha256': manifest_sha, 'manifest_preserved_byte_for_byte': True,
               'diagnostic_comparison_only': True, 'previously_taxonomy_inspected': True, 'untouched_test_set': False,
               'source_files_sha256': {name: scorer.sha(original / name) for name in
                                      ['class-index.json', 'intake/benchmark-all120.json', 'intake/evaluation-blind.json']}}
    write(evidence / 'package-provenance.json', package)
    write(evidence.parent / 'package-provenance.json', {
        'catalog_reference_sha256': scorer.sha(catalog), 'class_index_sha256': class_sha,
        'packages': {'main120': {'package_provenance_sha256': scorer.sha(evidence / 'package-provenance.json'),
                                'source_manifest_sha256': manifest_sha}}})
    frozen = load_review(evidence, catalog)
    approval = {**frozen, 'status': 'human_approved', 'approval_method': 'explicit_local_review_ui',
                'saved_at': datetime.now(timezone.utc).isoformat()}
    for row, decision in zip(approval['records'], ['c000', 'bus:stop', 'c000', '@unreadable']):
        row.update(reviewed=True, decision=decision)
    approved = evidence / 'intake/blind/review-approved.json'
    write(approved, approval)
    registry_path = tmp_path / 'model-registry.json'
    models = [{'id': name, 'classes': order, 'sha256': digest, 'path': name + '.pt',
               'normalization': 'RGB/255', 'input_shape': [1, 3, 224, 224]}
              for name, order, digest in [('primary136', classes[:136], scorer.CHECKPOINTS['primary136'][2]),
                                          ('primary142', classes, 'b' * 64)]]
    write(registry_path, {'schemaVersion': 1, 'models': models})
    reference.mkdir()
    shutil.copyfile(de_expanded_gpu_reference.__file__, reference / 'executed-reference.py')
    values = {'image_ids': np.asarray([r['id'] for r in images]), 'sources': np.asarray([r['source'] for r in images]),
              'canonical_tensor_sha256': np.asarray(tensor_hashes), 'primary136_classes': np.asarray(classes[:136]),
              'primary142_classes': np.asarray(classes), 'primary136_canonical_scores': np.eye(136)[[0, 0, 0, 0]],
              'primary142_canonical_scores': np.eye(142)[[136, 136, 0, 0]]}
    np.savez_compressed(reference / 'gpu-reference-predictions.npz', **values)
    provenance = {'script_sha256': scorer.sha(reference / 'executed-reference.py'),
                  'helper_sha256': scorer.sha(Path(scorer.__file__).with_name('de_field_gpu_reference.py')),
                  'registry_sha256': scorer.sha(registry_path), 'manifest_sha256': manifest_sha,
                  'predictions_sha256': scorer.sha(reference / 'gpu-reference-predictions.npz'),
                  'truth_labels_read': False, 'accuracy_or_f1_computed': False,
                  'execution': 'CUDA FP32, batch one, TF32/AMP disabled', 'cuda_device': 'SYNTHETIC FIXTURE, NO INFERENCE',
                  'models': {r['id']: {'checkpoint_sha256': r['sha256'], 'class_count': len(r['classes']), 'canonical_images': 4}
                             for r in models}}
    write(reference / 'provenance.json', provenance)
    write(reference / 'complete.json', {'status': 'complete', 'predictions_sha256': provenance['predictions_sha256'],
                                       'provenance_sha256': scorer.sha(reference / 'provenance.json'),
                                       'truth_labels_read': False, 'accuracy_or_f1_computed': False})
    return dict(evidence=evidence, original=original, catalog=catalog, approved=approved,
                reference=reference, registry_path=registry_path, registry_sha256=scorer.sha(registry_path), repeat_path=repeat)


def test_missing_approval_never_opens_predictions_or_registry(tmp_path, monkeypatch):
    monkeypatch.setattr(np, 'load', lambda *a, **k: pytest.fail('Prediction opened before approval'))
    monkeypatch.setattr(scorer, 'validate_review_package', lambda *a: pytest.fail('Package opened before approval'))
    with pytest.raises(ValueError, match='human review-approved'):
        scorer.build_report(tmp_path, tmp_path, tmp_path, tmp_path / 'review-approved.json',
                            tmp_path, tmp_path, 'a' * 64, tmp_path)


@pytest.mark.parametrize('change', [{'status': 'assistant_approved'}, {'status': 'in_progress'}, {'approval_method': 'automated'}])
def test_silver_or_draft_approval_refused(corpus, change, monkeypatch):
    approval = scorer.read(corpus['approved']); approval.update(change); write(corpus['approved'], approval)
    monkeypatch.setattr(np, 'load', lambda *a, **k: pytest.fail('Prediction opened before approval'))
    with pytest.raises(ValueError, match='Explicit human approval'):
        scorer.build_report(**corpus)


def test_incomplete_approval_refused_before_predictions(corpus, monkeypatch):
    approval = scorer.read(corpus['approved']); approval['records'][0]['reviewed'] = False
    write(corpus['approved'], approval)
    monkeypatch.setattr(np, 'load', lambda *a, **k: pytest.fail('Prediction opened before approval'))
    with pytest.raises(ValueError, match='Every crop'):
        scorer.build_report(**corpus)


def test_group_f1_retains_false_positives_outside_truth_group(corpus):
    report = scorer.build_report(**corpus, draws=100)
    section = report['sections']['all']
    assert report['baseline'] == 'primary136' and report['untouched_confirmatory_test'] is False
    assert section['excluded_by_reason'] == {'unreadable': 1}
    assert section['models']['primary142']['accuracy'] == pytest.approx(2 / 3)
    group = section['class_groups']['new_classes']['models']['primary142']
    assert group['truth_cohort_accuracy'] == 1
    assert group['supported_class_macro_f1'] == pytest.approx(2 / 3)
    assert group['per_class'][0]['predicted'] == 2  # Includes incorrect bus-stop prediction on old-class truth.
    assert group['per_class'][1]['f1'] is None and group['per_class'][1]['recall'] is None
    assert section['class_groups']['new_classes']['models']['primary136']['supported_class_macro_f1'] == 0
    assert report['sections']['panoramax']['route_block_uncertainty']['models']['primary142']['ci95'] is None
    assert report['sections']['panoramax']['class_groups']['new_classes']['models']['primary142']['supported_class_macro_f1'] is None
    json.dumps(report, allow_nan=False)


@pytest.mark.parametrize('target,message', [('registry', 'registry digest'), ('catalog', 'different class catalog'),
                                           ('route', 'partition every image'), ('prediction', 'archive digest')])
def test_changed_frozen_input_refused(corpus, target, message):
    if target == 'registry':
        corpus['registry_path'].write_text('{}')
    elif target == 'catalog':
        corpus['catalog'].write_text(json.dumps({'signs': []}))
    elif target == 'prediction':
        (corpus['reference'] / 'gpu-reference-predictions.npz').write_bytes(b'changed')
    else:
        repeat = scorer.read(corpus['repeat_path']); repeat['conservative_route_blocks'][1]['members'] = ['A001']
        write(corpus['repeat_path'], repeat)
    with pytest.raises(ValueError, match=message):
        scorer.build_report(**corpus, draws=100)


@pytest.mark.parametrize('target,message', [('canonical_tensor_sha256', 'tensor digest'),
                                           ('primary142_classes', 'class order'), ('sources', 'source order'),
                                           ('image_ids', 'image order'), ('primary142_canonical_scores', 'probability matrix')])
def test_rehashed_archive_must_still_match_inputs(corpus, target, message):
    with np.load(corpus['reference'] / 'gpu-reference-predictions.npz', allow_pickle=False) as archive:
        values = {k: archive[k] for k in archive.files}
    if target.endswith('_scores'):
        values[target][0, 0] = np.nan
    else:
        values[target] = values[target][::-1]
    reseal_predictions(corpus, values)
    with pytest.raises(ValueError, match=message):
        scorer.build_report(**corpus, draws=100)


def test_new_baseline_paired_identical_predictions_have_zero_delta():
    truth = np.asarray(['a', 'b', 'a'])
    pred = np.asarray(['a', 'a', 'b'])
    result = scorer.clustered_comparison(truth, {'primary136': pred, 'primary142': pred.copy()},
                                        ['a', 'b'], [[0, 1], [2]], 100, 7, baseline='primary136')
    delta = result['paired_delta_vs_primary136']['primary142']
    assert all(x == 0 for x in delta['point'].values())
    assert all(x == [0, 0] for x in delta['ci95'].values())
