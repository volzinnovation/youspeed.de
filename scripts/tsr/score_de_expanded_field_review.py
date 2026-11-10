#!/usr/bin/env python3
"""Score expanded CUDA predictions only after complete explicit human review.

This is a taxonomy-inspected diagnostic comparison, not a fresh confirmatory
test. Silver training proposals can never substitute for the approval file.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
from pathlib import Path
import sys
import json

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.tsr import de_expanded_gpu_reference
from scripts.tsr.de_field_gpu_reference import CHECKPOINTS
from scripts.tsr.score_de_field_review import (
    approved_review, clustered_comparison, point_metrics, read, require, sha,
)

BASELINE = 'primary136'


def validate_review_package(evidence, original, catalog, frozen, repeat_path):
    """Bind expanded vocabulary to unchanged source pixels and original routes."""
    intake = evidence / 'intake'
    package_path = evidence / 'package-provenance.json'
    package = read(package_path)
    parent = read(evidence.parent / 'package-provenance.json')
    require(evidence.name in parent['packages']
            and parent['packages'][evidence.name]['package_provenance_sha256'] == sha(package_path),
            'Expanded package provenance digest mismatch')
    require(catalog.resolve() == (evidence.parent / 'catalog-reference.json').resolve(),
            'Use the expanded review package pinned catalog-reference.json')
    require(sha(catalog) == frozen['catalog_sha256'] == package['catalog_reference_sha256']
            == parent['catalog_reference_sha256'], 'Pinned expanded catalog digest mismatch')
    classes = [c['id'] for c in frozen['classes']]
    class_sha = sha(evidence / 'class-index.json')
    require(class_sha == package['class_index_sha256'] == parent['class_index_sha256']
            and classes == read(evidence.parent / 'class-index.json')['classes'],
            'Expanded class-index digest mismatch')
    old_classes = read(original / 'class-index.json')['classes']
    require(len(old_classes) == 136 and len(classes) > 136 and classes[:136] == old_classes,
            'Expanded vocabulary must preserve original 136 class indices')
    source_files = package['source_files_sha256']
    for relative, archived in [('class-index.json', 'provenance/source-class-index.json'),
                               ('intake/evaluation-blind.json', 'provenance/source-evaluation-blind.json')]:
        require(sha(original / relative) == source_files[relative] == sha(evidence / archived),
                'Archived original review identity mismatch')
    manifest_path = intake / 'benchmark-all120.json'
    require(sha(manifest_path) == frozen['manifest_sha256'] == package['source_manifest_sha256']
            == source_files['intake/benchmark-all120.json']
            == sha(original / 'intake/benchmark-all120.json')
            == parent['packages'][evidence.name]['source_manifest_sha256'],
            'Expanded review must retain original benchmark bytes')
    require(package.get('manifest_preserved_byte_for_byte') is True
            and package.get('diagnostic_comparison_only') is True
            and package.get('previously_taxonomy_inspected') is True
            and package.get('untouched_test_set') is False,
            'Expanded package must disclose taxonomy exposure')
    images = read(manifest_path)['images']
    ids = [r['id'] for r in images]
    require(ids and len(ids) == len(set(ids)) == package['records'], 'Duplicate or missing benchmark image')
    original_blind = read(original / 'intake/evaluation-blind.json')
    blind = read(intake / 'evaluation-blind.json')
    require(blind['classes'] == classes and blind['samples'] == original_blind['samples'],
            'Expanded blind review changed frozen source identities')
    require(blind['selection_sha256'] == original_blind['selection_sha256']
            == sha(original / 'intake/selection-frozen.json'), 'Original frozen selection digest mismatch')
    bound = blind['expanded_review_provenance']
    require(bound['source_evaluation_blind_sha256'] == sha(original / 'intake/evaluation-blind.json')
            and bound['source_manifest_sha256'] == frozen['manifest_sha256']
            and bound['class_index_sha256'] == class_sha, 'Expanded blind provenance mismatch')
    rows = {r['blind_id']: r for r in blind['samples']}
    require(len(rows) == len(blind['samples']) and set(rows) == set(ids), 'Blind IDs do not match benchmark')
    for image in images:
        require(all(rows[image['id']][k] == image[k] for k in ('source', 'sha256', 'canonicalSha256')),
                'Blind image identity mismatch')
    require(repeat_path.resolve() == (original / 'intake/repeat-audit.json').resolve(),
            'Use the original frozen repeat audit')
    repeat = read(repeat_path)
    require(repeat.get('manifest_sha256') == sha(original / 'intake/evaluation-blind.json')
            and repeat.get('labels_or_predictions_used') is False,
            'Repeat audit must be prediction-blind and bound to original intake')
    members, blocks = [], []
    for block in repeat['conservative_route_blocks']:
        require(bool(block['members']), 'Empty route block')
        blocks.append(block['id']); members.extend(block['members'])
    require(len(blocks) == len(set(blocks)) and Counter(members) == Counter(ids),
            'Conservative route blocks must partition every image exactly once')
    quality = read(original / 'intake/data-quality-addendum.json')
    require(quality['selection_sha256'] == original_blind['selection_sha256'],
            'Data-quality addendum belongs to another selection')
    return images, repeat, quality


def validate_predictions(evidence, reference, registry_path, registry_sha256, frozen, images):
    """Open predictions only after the human gate and identity checks succeeded."""
    require(sha(registry_path) == registry_sha256, 'Frozen model registry digest mismatch')
    registry = de_expanded_gpu_reference.validate_registry(read(registry_path))
    classes = [c['id'] for c in frozen['classes']]
    candidate = 'primary' + str(len(classes))
    models = {r['id']: r for r in registry}
    require(set(models) == {BASELINE, candidate}, 'Registry must contain explicit primary136 and expanded candidate')
    require(models[BASELINE]['classes'] == classes[:136]
            and models[BASELINE]['sha256'] == CHECKPOINTS[BASELINE][2], 'Unrecognized primary136 baseline')
    require(models[candidate]['classes'] == classes, 'Candidate class order differs from approved vocabulary')
    prediction_path = reference / 'gpu-reference-predictions.npz'
    provenance_path = reference / 'provenance.json'
    provenance, complete = read(provenance_path), read(reference / 'complete.json')
    require(complete.get('status') == 'complete', 'Expanded CUDA reference is incomplete')
    require(all(r.get('truth_labels_read') is False and r.get('accuracy_or_f1_computed') is False
                for r in [provenance, complete]), 'Reference predictions must precede truth-label access')
    require(sha(provenance_path) == complete['provenance_sha256'], 'CUDA provenance digest mismatch')
    require(sha(prediction_path) == provenance['predictions_sha256'] == complete['predictions_sha256'],
            'CUDA prediction archive digest mismatch')
    require(sha(reference / 'executed-reference.py') == provenance['script_sha256']
            == sha(Path(de_expanded_gpu_reference.__file__)), 'Executed CUDA reference script digest mismatch')
    require(provenance['helper_sha256'] == sha(Path(__file__).with_name('de_field_gpu_reference.py')),
            'CUDA tensor helper digest mismatch')
    require(provenance['registry_sha256'] == registry_sha256
            and provenance['manifest_sha256'] == frozen['manifest_sha256'],
            'CUDA reference registry or benchmark identity mismatch')
    require(provenance.get('execution') == 'CUDA FP32, batch one, TF32/AMP disabled'
            and bool(provenance.get('cuda_device')), 'CUDA execution receipt required')
    require(set(provenance['models']) == set(models), 'CUDA model set differs from registry')
    ids = [r['id'] for r in images]
    tensor_hashes = []
    for row in images:
        path = evidence / 'intake' / row['canonicalPath']
        require(sha(path) == row['canonicalSha256'], 'Canonical PNG digest mismatch')
        with Image.open(path) as image:
            require(image.format == 'PNG' and image.size == (224, 224), 'Invalid canonical PNG')
            values = np.asarray(image.convert('RGB'), dtype=np.float32) / np.float32(255)
        tensor_hashes.append(hashlib.sha256(values.astype('<f4').tobytes()).hexdigest())
    predictions = {}
    with np.load(prediction_path, allow_pickle=False) as archive:
        require(archive['image_ids'].astype(str).tolist() == ids, 'CUDA image order mismatch')
        require(archive['sources'].astype(str).tolist() == [r['source'] for r in images], 'CUDA source order mismatch')
        require(archive['canonical_tensor_sha256'].astype(str).tolist() == tensor_hashes,
                'CUDA canonical tensor digest mismatch')
        for name, model in models.items():
            meta = provenance['models'][name]
            order = archive[name + '_classes'].astype(str).tolist()
            require(order == model['classes'] and meta['class_count'] == len(order)
                    and meta['checkpoint_sha256'] == model['sha256']
                    and meta['canonical_images'] == len(ids), 'CUDA model identity or class order mismatch')
            scores = archive[name + '_canonical_scores']
            require(scores.shape == (len(ids), len(order)) and np.isfinite(scores).all()
                    and (scores >= 0).all() and np.allclose(scores.sum(1), 1, atol=1e-5, rtol=0),
                    'Invalid CUDA probability matrix')
            predictions[name] = np.asarray(order)[scores.argmax(1)]
    return predictions, provenance, models


def summarize_group(truth, predictions, labels, full_metrics, groups, draws, seed):
    """Per-class F1 uses every included crop, preserving cross-group false positives."""
    mask = np.isin(truth, labels)
    measured = bool(mask.any())
    uncertainty = (clustered_comparison(truth, predictions, labels, groups, draws, seed, baseline=BASELINE)
                   if measured else None)
    output = {'class_ids': labels, 'truth_support': int(mask.sum()), 'models': {},
              'metric_scope': 'Per-class precision/recall/F1 use all included crops; only cohort accuracy filters by truth family.'}
    for name, predicted in predictions.items():
        per_class = [r for r in full_metrics[name]['per_class'] if r['class_id'] in labels]
        supported = [r['f1'] for r in per_class if r['support']]
        ci = uncertainty['models'][name]['ci95'] if uncertainty else None
        output['models'][name] = {
            'supported_class_macro_f1': float(np.mean(supported)) if supported else None,
            'supported_class_macro_f1_ci95': ci['supported_class_macro_f1'] if ci else None,
            'truth_cohort_accuracy': float(np.mean(truth[mask] == predicted[mask])) if measured else None,
            'supported_class_ids': [r['class_id'] for r in per_class if r['support']],
            'unsupported_class_ids': [r['class_id'] for r in per_class if not r['support']],
            'per_class': per_class,
        }
    output['paired_macro_f1_delta_vs_primary136'] = {}
    for name in predictions:
        if name == BASELINE:
            continue
        delta = uncertainty['paired_delta_vs_primary136'][name] if uncertainty else None
        output['paired_macro_f1_delta_vs_primary136'][name] = {
            'point': delta['point']['supported_class_macro_f1'] if delta else None,
            'ci95': delta['ci95']['supported_class_macro_f1'] if delta and delta['ci95'] else None,
        }
    return output


def build_report(evidence, original, catalog, approved, reference, registry_path,
                 registry_sha256, repeat_path, draws=2000, seed=20261109):
    # Nothing below this line may be moved above the complete human approval gate.
    frozen, reviewed = approved_review(evidence, catalog, approved)
    images, repeat, quality = validate_review_package(evidence, original, catalog, frozen, repeat_path)
    predictions, provenance, registry = validate_predictions(
        evidence, reference, registry_path, registry_sha256, frozen, images)
    require(draws >= 100, 'At least 100 bootstrap draws are required')
    classes = [c['id'] for c in frozen['classes']]
    decisions = {r['id']: r['decision'] for r in reviewed}
    positions = {r['id']: i for i, r in enumerate(images)}
    sections = {}
    for source in ['all'] + sorted({r['source'] for r in images}):
        rows = [r for r in images if source == 'all' or r['source'] == source]
        included = [r for r in rows if not decisions[r['id']].startswith('@')]
        excluded = [r for r in rows if decisions[r['id']].startswith('@')]
        section = {'reviewed': len(rows), 'included': len(included),
                   'excluded_by_reason': dict(Counter(decisions[r['id']][1:] for r in excluded)),
                   'excluded_ids': [{'id': r['id'], 'reason': decisions[r['id']][1:]} for r in excluded]}
        ids = [r['id'] for r in included]
        lookup = {key: i for i, key in enumerate(ids)}
        groups = [[lookup[key] for key in block['members'] if key in lookup]
                  for block in repeat['conservative_route_blocks']]
        groups = [g for g in groups if g]
        truth = np.asarray([decisions[key] for key in ids])
        selected = {name: pred[[positions[key] for key in ids]] for name, pred in predictions.items()}
        section['models'] = {name: point_metrics(truth, pred, classes) for name, pred in selected.items()}
        section['route_block_uncertainty'] = (clustered_comparison(
            truth, selected, classes, groups, draws, seed, baseline=BASELINE) if included else None)
        section['class_groups'] = {name: summarize_group(
            truth, selected, labels, section['models'], groups, draws, seed)
            for name, labels in [('common136', classes[:136]), ('new_classes', classes[136:])]}
        sections[source] = section
    return {
        'schema': 'youspeed-human-approved-expanded-field-scores-v1',
        'created_at': datetime.now(timezone.utc).isoformat(),
        'status': 'taxonomy_inspected_correlated_crop_diagnostic_after_human_review',
        'baseline': BASELINE, 'class_count': len(classes), 'untouched_confirmatory_test': False,
        'metric_scope': 'Conditional classification of the original reviewed crops; no detection-recall or population-generalization claim.',
        'approval_sha256': sha(approved), 'manifest_sha256': frozen['manifest_sha256'],
        'catalog_sha256': frozen['catalog_sha256'], 'class_index_sha256': sha(evidence / 'class-index.json'),
        'review_package_provenance_sha256': sha(evidence / 'package-provenance.json'),
        'registry_sha256': registry_sha256, 'gpu_provenance_sha256': sha(reference / 'provenance.json'),
        'gpu_predictions_sha256': provenance['predictions_sha256'], 'repeat_audit_sha256': sha(repeat_path),
        'data_quality_addendum_sha256': sha(original / 'intake/data-quality-addendum.json'),
        'scorer_sha256': sha(__file__), 'metrics_helper_sha256': sha(Path(__file__).with_name('score_de_field_review.py')),
        'model_output_classes': {name: row['classes'] for name, row in registry.items()},
        'sections': sections,
        'limitations': [
            'These images were inspected during taxonomy design and are diagnostic, not a new untouched confirmatory evaluation.',
            'Silver training labels are never evaluation ground truth. Every included decision requires new explicit human approval against the pinned expanded catalog.',
            'The primary136 baseline cannot emit any appended class; its new-class recall is structurally zero when such truth is present.',
            'Common136 and new-class F1 use all included rows, retaining cross-family false positives. Model outputs are not renormalized to shared classes.',
            'Unsupported truth classes have null recall and F1. Precision is null without predictions; supported failures have F1 zero.',
            'Paired uncertainty resamples complete conservative route blocks. Rare classes and few routes yield unstable intervals; physical-sign independence is not established.',
            f"Historical route identity is unresolved for {quality['historical_non_uuid_source_records']} imported records; full separation from original HF training routes cannot be certified.",
            'Detector-selected stored crops omit missed detections and cannot reconstruct complete live padded camera ROIs. No end-to-end detection F1 is measured.',
            'The local review file records an explicit UI approval, not a cryptographic proof of reviewer identity.',
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True, help='Expanded field-review/main120 directory')
    parser.add_argument('--original', type=Path, required=True, help='Original 136-class field-evaluation directory')
    parser.add_argument('--catalog', type=Path)
    parser.add_argument('--approved', type=Path)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--registry', type=Path, required=True)
    parser.add_argument('--registry-sha256', required=True)
    parser.add_argument('--repeat-audit', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--bootstrap-draws', type=int, default=2000)
    parser.add_argument('--seed', type=int, default=20261109)
    args = parser.parse_args()
    require(not args.output.exists(), 'Refusing to overwrite an existing score artifact')
    report = build_report(
        args.evidence, args.original, args.catalog or args.evidence.parent / 'catalog-reference.json',
        args.approved or args.evidence / 'intake/blind/review-approved.json', args.reference,
        args.registry, args.registry_sha256, args.repeat_audit or args.original / 'intake/repeat-audit.json',
        args.bootstrap_draws, args.seed)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'status': report['status'], 'output': str(args.output)}))


if __name__ == '__main__':
    main()
