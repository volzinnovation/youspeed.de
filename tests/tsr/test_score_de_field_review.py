"""Synthetic fixtures only: no real field labels are approved or scored here."""
from datetime import datetime, timezone
import hashlib
import json

import numpy as np
from PIL import Image
import pytest

from scripts.tsr import score_de_field_review as scorer
from scripts.tsr.de_label_review import load_review


def write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value))


@pytest.fixture
def corpus(tmp_path):
    evidence = tmp_path / 'evidence'
    intake, reference = evidence / 'intake', tmp_path / 'reference'
    classes = ['stop', 'city:start', 'other']
    catalog = tmp_path / 'catalog.json'
    write(catalog, {'signs': [{'class_id': c, 'label': {'en': c}} for c in classes]})
    write(evidence / 'class-index.json', {'classes': classes})
    images, proposals, samples, tensors = [], [], [], []
    for i, (key, source) in enumerate([('A001', 'android'), ('A002', 'android'),
                                       ('P001', 'panoramax'), ('P002', 'panoramax')]):
        path = intake / 'native' / (key + '.png')
        path.parent.mkdir(parents=True, exist_ok=True)
        Image.new('RGB', (224, 224), (10 + i, 20, 30)).save(path)
        digest = scorer.sha(path)
        images.append({'id': key, 'source': source, 'path': f'native/{key}.png',
                       'canonicalPath': f'native/{key}.png', 'sha256': digest, 'canonicalSha256': digest})
        samples.append({**images[-1], 'blind_id': key})
        proposals.append({'id': key, 'proposed_class_id': 'stop', 'confidence': 'clear',
                          'visual_reason': 'Synthetic fixture; no real crop labels'})
        values = np.asarray(Image.open(path), dtype=np.float32) / np.float32(255)
        tensors.append(hashlib.sha256(values.astype('<f4').tobytes()).hexdigest())
    write(intake / 'benchmark-all120.json', {'schemaVersion': 1, 'images': images})
    write(intake / 'blind/proposed-phone-labels.json', {'labels': proposals[:2]})
    write(intake / 'blind/proposed-panoramax-labels.json', {'labels': proposals[2:]})
    write(intake / 'selection-frozen.json', {'test_fixture': True})
    selection = scorer.sha(intake / 'selection-frozen.json')
    write(intake / 'evaluation-blind.json', {'classes': classes, 'selection_sha256': selection, 'samples': samples})
    blocks = [{'id': 'route-a', 'members': ['A001', 'A002']}, {'id': 'route-b', 'members': ['P001']},
              {'id': 'route-c', 'members': ['P002']}]
    repeat = intake / 'repeat-audit.json'
    write(repeat, {'manifest_sha256': scorer.sha(intake / 'evaluation-blind.json'),
                   'labels_or_predictions_used': False, 'conservative_route_blocks': blocks,
                   'candidate_physical_sign_component_count': 4,
                   'candidate_physical_sign_components': [{'members': [r['id']]} for r in images]})
    write(intake / 'data-quality-addendum.json', {'selection_sha256': selection,
                                                 'historical_non_uuid_source_records': 254})
    frozen = load_review(evidence, catalog)
    approval = {**frozen, 'status': 'human_approved', 'approval_method': 'explicit_local_review_ui',
                'saved_at': datetime.now(timezone.utc).isoformat()}
    for row, decision in zip(approval['records'], ['stop', 'city:start', 'city:start', '@unreadable']):
        row.update(reviewed=True, decision=decision)
    approved = intake / 'blind/review-approved.json'
    write(approved, approval)
    reference.mkdir()
    script = reference / 'executed-de_field_gpu_reference.py'
    script.write_text('# Synthetic fixture only; no model or real crop evaluated.\n')
    values = {'image_ids': np.asarray([r['id'] for r in images]),
              'sources': np.asarray([r['source'] for r in images]),
              'canonical_tensor_sha256': np.asarray(tensors),
              'baseline134_classes': np.asarray(classes), 'primary136_classes': np.asarray(classes),
              'baseline134_canonical_scores': np.eye(3)[[0, 0, 2, 2]],
              'primary136_canonical_scores': np.eye(3)[[0, 1, 0, 2]]}
    prediction_path = reference / 'gpu-reference-predictions.npz'
    np.savez_compressed(prediction_path, **values)
    provenance = {'predictions_sha256': scorer.sha(prediction_path), 'script_sha256': scorer.sha(script),
                  'manifest_sha256': frozen['manifest_sha256'], 'truth_labels_read': False,
                  'accuracy_or_f1_computed': False,
                  'models': {name: {'checkpoint_sha256': scorer.CHECKPOINTS[name][2],
                                    'class_count': 3, 'canonical_images': 4}
                             for name in ('baseline134', 'primary136')}}
    write(reference / 'provenance-and-android-parity.json', provenance)
    write(reference / 'complete.json', {'status': 'complete', 'predictions_sha256': scorer.sha(prediction_path),
                                       'provenance_sha256': scorer.sha(reference / 'provenance-and-android-parity.json')})
    return dict(evidence=evidence, catalog=catalog, approved=approved, reference=reference, repeat_path=repeat)


def test_missing_approval_stops_before_loading_truth_or_predictions(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('Must not read prediction or proposal inputs before approval gate')
    monkeypatch.setattr(scorer, 'load_review', forbidden)
    monkeypatch.setattr(np, 'load', forbidden)
    with pytest.raises(ValueError, match='human review-approved'):
        scorer.build_report(tmp_path, tmp_path, tmp_path / 'review-approved.json', tmp_path, tmp_path)


@pytest.mark.parametrize('change', [{'status': 'in_progress'}, {'status': 'assistant_approved'},
                                    {'approval_method': 'automated'}, {'schema': 'unknown'}])
def test_nonhuman_or_draft_approval_is_refused(corpus, change, monkeypatch):
    data = scorer.read(corpus['approved']); data.update(change); write(corpus['approved'], data)
    monkeypatch.setattr(np, 'load', lambda *a, **kw: pytest.fail('Prediction archive read before gate'))
    with pytest.raises(ValueError, match='Explicit human approval'):
        scorer.build_report(**corpus)


def test_incomplete_human_review_is_refused(corpus, monkeypatch):
    data = scorer.read(corpus['approved']); data['records'][1]['reviewed'] = False
    write(corpus['approved'], data)
    monkeypatch.setattr(np, 'load', lambda *a, **kw: pytest.fail('Prediction archive read before complete review'))
    with pytest.raises(ValueError, match='Every crop'):
        scorer.build_report(**corpus)


@pytest.mark.parametrize('target', ['crop', 'prediction', 'route'])
def test_tampered_inputs_are_refused(corpus, target):
    if target == 'crop':
        (corpus['evidence'] / 'intake/native/A001.png').write_bytes(b'changed')
        message = 'Crop digest mismatch'
    elif target == 'prediction':
        (corpus['reference'] / 'gpu-reference-predictions.npz').write_bytes(b'changed')
        message = 'archive digest mismatch'
    else:
        data = scorer.read(corpus['repeat_path'])
        data['conservative_route_blocks'][1]['members'] = ['A001']
        write(corpus['repeat_path'], data)
        message = 'partition every image'
    with pytest.raises(ValueError, match=message):
        scorer.build_report(**corpus)


def test_approved_synthetic_report_counts_exclusions_and_supported_macro(corpus):
    report = scorer.build_report(**corpus, draws=100)
    section = report['sections']['all']
    assert (section['reviewed'], section['included'], section['excluded_by_reason']) == (4, 3, {'unreadable': 1})
    primary = section['models']['primary136']
    assert primary['accuracy'] == pytest.approx(2 / 3)
    assert primary['micro_f1_all_classes'] == primary['accuracy']
    assert primary['supported_class_macro_f1'] == pytest.approx(2 / 3)
    assert primary['supported_class_ids'] == ['stop', 'city:start']
    assert primary['unsupported_class_ids'] == ['other']
    assert section['route_block_uncertainty']['models']['primary136']['point']['route_macro_accuracy'] == .5
    assert report['sections']['panoramax']['excluded_by_reason'] == {'unreadable': 1}
    assert report['sections']['panoramax']['route_block_uncertainty']['models']['primary136']['ci95'] is None
    assert not report['repeat_audit']['physical_sign_independence_established']


@pytest.mark.parametrize('target,message', [('primary136_classes', 'class order mismatch'),
                                           ('canonical_tensor_sha256', 'tensor digest mismatch')])
def test_rehashed_archive_still_requires_class_order_and_exact_tensor_binding(corpus, target, message):
    path = corpus['reference'] / 'gpu-reference-predictions.npz'
    with np.load(path, allow_pickle=False) as archive:
        data = {key: archive[key] for key in archive.files}
    data[target] = data[target][::-1]
    np.savez_compressed(path, **data)
    provenance_path = corpus['reference'] / 'provenance-and-android-parity.json'
    provenance = scorer.read(provenance_path); provenance['predictions_sha256'] = scorer.sha(path)
    write(provenance_path, provenance)
    receipt_path = corpus['reference'] / 'complete.json'
    receipt = scorer.read(receipt_path)
    receipt.update(predictions_sha256=scorer.sha(path), provenance_sha256=scorer.sha(provenance_path))
    write(receipt_path, receipt)
    with pytest.raises(ValueError, match=message):
        scorer.build_report(**corpus)


def test_macro_ignores_unsupported_classes_but_accuracy_counts_their_errors():
    result = scorer.point_metrics(['stop', 'stop'], ['stop', 'other'], ['stop', 'other', 'city:start'])
    assert result['supported_class_macro_f1'] == pytest.approx(2 / 3)
    assert result['micro_f1_all_classes'] == .5
    assert result['supported_class_ids'] == ['stop']
    by_class = {r['class_id']: r for r in result['per_class']}
    assert by_class['other']['precision'] == 0
    assert by_class['other']['recall'] is None
    assert by_class['other']['f1'] is None
    assert by_class['other']['status'] == 'unmeasured_no_truth_support'
    assert by_class['city:start']['precision'] is None
    assert by_class['city:start']['recall'] is None
    assert by_class['city:start']['f1'] is None


def test_paired_identical_predictions_have_exact_zero_delta():
    truth = np.asarray(['a', 'b', 'b', 'a'])
    predicted = np.asarray(['a', 'a', 'b', 'b'])
    result = scorer.clustered_comparison(truth, {'baseline134': predicted, 'primary136': predicted.copy()},
                                        ['a', 'b'], [[0, 1], [2], [3]], draws=100, seed=17)
    delta = result['paired_delta_vs_baseline134']['primary136']
    assert all(value == 0 for value in delta['point'].values())
    assert all(value == [0, 0] for value in delta['ci95'].values())


def test_whole_route_bootstrap_cannot_split_a_two_crop_route():
    truth = np.asarray(['a', 'a', 'a'])
    predicted = np.asarray(['a', 'a', 'b'])
    result = scorer.clustered_comparison(truth, {'baseline134': predicted, 'primary136': predicted},
                                        ['a', 'b'], [[0, 1], [2]], draws=100, seed=1)
    point = result['models']['primary136']['point']
    assert point['accuracy'] == pytest.approx(2 / 3)
    assert point['route_macro_accuracy'] == .5
    assert result['models']['primary136']['ci95']['accuracy'] == [0, 1]
