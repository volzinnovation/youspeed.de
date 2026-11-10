#!/usr/bin/env python3
"""Score frozen field predictions only after complete explicit human approval.

The local review UI is the approval boundary. This scorer does not approve,
modify or impute labels. All-crop results are correlated-crop diagnostics;
physical-sign independence is not established by candidate repeat clusters.
"""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from scripts.tsr.de_label_review import load_review, validate_submission
from scripts.tsr.de_field_gpu_reference import CHECKPOINTS


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def approved_review(evidence, catalog, approved):
    """Run before opening any prediction archive or computing any metric."""
    require(approved.name == 'review-approved.json' and approved.is_file(),
            'Complete human review-approved.json is required; no F1 was computed')
    data = read(approved)
    require(data.get('status') == 'human_approved'
            and data.get('approval_method') == 'explicit_local_review_ui'
            and data.get('schema') == 'youspeed-human-field-review-v1',
            'Explicit human approval from the local review UI is required')
    saved = datetime.fromisoformat(data.get('saved_at', ''))
    require(saved.tzinfo is not None, 'Approval must have a timezone-aware timestamp')
    frozen = load_review(evidence, catalog)
    records = validate_submission(data, frozen, final=True)
    require(len({r['id'] for r in records}) == len(records), 'Duplicate frozen crop ID')
    classes = [r['id'] for r in frozen['classes']]
    require(len(set(classes)) == len(classes), 'Duplicate class in frozen class index')
    return frozen, records


def validate_inputs(evidence, reference, repeat_path, frozen):
    """Bind review bytes, route audit, original selection and prediction receipt."""
    intake = evidence / 'intake'
    manifest_path = intake / 'benchmark-all120.json'
    manifest = read(manifest_path)
    images = manifest['images']
    ids = [r['id'] for r in images]
    require(len(ids) == len(set(ids)), 'Duplicate image in benchmark manifest')
    require(sha(manifest_path) == frozen['manifest_sha256'], 'Frozen manifest changed')
    blind_path = intake / 'evaluation-blind.json'
    blind = read(blind_path)
    require(sha(intake / 'selection-frozen.json') == blind['selection_sha256'],
            'Frozen selection digest mismatch')
    classes = [c['id'] for c in frozen['classes']]
    require(blind['classes'] == classes, 'Frozen intake class order mismatch')
    rows = {r['blind_id']: r for r in blind['samples']}
    require(len(rows) == len(blind['samples']) and set(rows) == set(ids),
            'Blind audit must cover exactly the frozen images')
    for image in images:
        row = rows[image['id']]
        require(all(row[k] == image[k] for k in ('source', 'sha256', 'canonicalSha256')),
                'Blind audit image identity mismatch')
    repeat = read(repeat_path)
    require(repeat.get('manifest_sha256') == sha(blind_path)
            and repeat.get('labels_or_predictions_used') is False,
            'Repeat audit must be prediction-blind and bound to this intake')
    block_ids, members = [], []
    for block in repeat['conservative_route_blocks']:
        require(bool(block['members']), 'Empty route block')
        block_ids.append(block['id']); members.extend(block['members'])
    require(len(set(block_ids)) == len(block_ids) and Counter(members) == Counter(ids),
            'Conservative route blocks must partition every image exactly once')
    provenance_path = reference / 'provenance-and-android-parity.json'
    prediction_path = reference / 'gpu-reference-predictions.npz'
    provenance, complete = read(provenance_path), read(reference / 'complete.json')
    require(complete.get('status') == 'complete', 'GPU reference is incomplete')
    require(sha(prediction_path) == provenance['predictions_sha256'] == complete['predictions_sha256'],
            'GPU prediction archive digest mismatch')
    require(sha(provenance_path) == complete['provenance_sha256'], 'GPU provenance digest mismatch')
    require(sha(reference / 'executed-de_field_gpu_reference.py') == provenance['script_sha256'],
            'Executed GPU script digest mismatch')
    require(provenance['manifest_sha256'] == frozen['manifest_sha256'],
            'GPU predictions belong to a different frozen intake')
    require(provenance.get('truth_labels_read') is False
            and provenance.get('accuracy_or_f1_computed') is False,
            'GPU predictions must have been frozen without truth labels')
    # Verify the exact float32 RGB/255 tensors, not merely matching crop names.
    tensor_hashes = []
    for image in images:
        with Image.open(intake / image['canonicalPath']) as png:
            require(png.format == 'PNG' and png.size == (224, 224), 'Invalid canonical PNG')
            tensor = np.asarray(png.convert('RGB'), dtype=np.float32) / np.float32(255)
        tensor_hashes.append(hashlib.sha256(tensor.astype('<f4').tobytes()).hexdigest())
    predictions = {}
    with np.load(prediction_path, allow_pickle=False) as archive:
        require(archive['image_ids'].astype(str).tolist() == ids, 'GPU image order mismatch')
        require(archive['sources'].astype(str).tolist() == [r['source'] for r in images],
                'GPU source order mismatch')
        require(archive['canonical_tensor_sha256'].astype(str).tolist() == tensor_hashes,
                'GPU canonical tensor digest mismatch')
        for name, meta in provenance['models'].items():
            require(name in CHECKPOINTS and meta['checkpoint_sha256'] == CHECKPOINTS[name][2],
                    'Unrecognized frozen model checkpoint')
            model_classes = archive[name + '_classes'].astype(str).tolist()
            expected = classes[:134] if name == 'baseline134' else classes
            require(model_classes == expected and len(model_classes) == meta['class_count'],
                    'GPU model class order mismatch')
            require(meta['canonical_images'] == len(ids), 'GPU model image count mismatch')
            scores = archive[name + '_canonical_scores']
            require(scores.shape == (len(ids), len(model_classes)) and np.isfinite(scores).all()
                    and (scores >= 0).all() and np.allclose(scores.sum(1), 1, atol=1e-5, rtol=0),
                    'Invalid GPU probability matrix')
            # NumPy argmax breaks ties by the first frozen class index.
            predictions[name] = np.asarray(model_classes)[scores.argmax(1)]
    require('baseline134' in predictions and 'primary136' in predictions,
            'Baseline and primary candidate predictions are required')
    return images, repeat, predictions, provenance


def point_metrics(truth, predicted, classes):
    truth, predicted = np.asarray(truth), np.asarray(predicted)
    supported = [label for label in classes if np.any(truth == label)]
    per_class = []
    for label in classes:
        tp = int(np.sum((truth == label) & (predicted == label)))
        support, proposed = int(np.sum(truth == label)), int(np.sum(predicted == label))
        precision = tp / proposed if proposed else None
        recall = tp / support if support else None
        # Unsupported truth classes are unmeasured, including classes receiving
        # false-positive predictions. Those predictions still reduce accuracy.
        f1 = 2 * tp / (support + proposed) if support else None
        per_class.append(dict(class_id=label, support=support, predicted=proposed,
                              true_positive=tp, precision=precision, recall=recall, f1=f1,
                              status='measured' if support else 'unmeasured_no_truth_support',
                              included_in_supported_macro=support > 0))
    accuracy = float(np.mean(truth == predicted)) if len(truth) else None
    macro = float(np.mean([r['f1'] for r in per_class if r['support']])) if supported else None
    return dict(crops=len(truth), accuracy=accuracy, micro_f1_all_classes=accuracy,
                supported_class_macro_f1=macro, supported_class_ids=supported,
                unsupported_class_ids=[c for c in classes if c not in supported], per_class=per_class)


def scalar_metrics(truth, predicted, labels, groups):
    correct = truth == predicted
    f1 = []
    for label in labels:
        denominator = np.sum(truth == label) + np.sum(predicted == label)
        f1.append(float(2 * np.sum((truth == label) & (predicted == label)) / denominator)
                  if denominator else 0.0)
    return np.asarray([np.mean(correct), np.mean(f1),
                       np.mean([np.mean(correct[g]) for g in groups])], dtype=float)


METRICS = ('accuracy', 'supported_class_macro_f1', 'route_macro_accuracy')


def clustered_comparison(truth, predictions, classes, groups, draws, seed, baseline='baseline134'):
    """Resample complete route blocks; candidate and baseline share every draw."""
    require(draws >= 100, 'At least 100 bootstrap draws are required')
    require(baseline in predictions, 'Explicit baseline predictions are required')
    truth = np.asarray(truth)
    labels = [c for c in classes if np.any(truth == c)]
    require(bool(labels) and bool(groups), 'No reviewed, in-catalog crops to score')
    groups = [np.asarray(g, dtype=int) for g in groups]
    points = {name: scalar_metrics(truth, pred, labels, groups) for name, pred in predictions.items()}
    samples = {name: np.zeros((draws, len(METRICS))) for name in predictions}
    if len(groups) >= 2:
        rng = np.random.default_rng(seed)
        for iteration in range(draws):
            chosen = [groups[i] for i in rng.integers(0, len(groups), size=len(groups))]
            indices = np.concatenate(chosen)
            offsets = np.cumsum([0] + [len(g) for g in chosen])
            drawn_groups = [np.arange(a, b) for a, b in zip(offsets[:-1], offsets[1:])]
            for name, predicted in predictions.items():
                samples[name][iteration] = scalar_metrics(truth[indices], predicted[indices], labels, drawn_groups)
    def intervals(values):
        if len(groups) < 2:
            return None
        return {metric: [float(x) for x in np.quantile(values[:, i], [.025, .975])]
                for i, metric in enumerate(METRICS)}
    return {
        'method': 'Paired percentile bootstrap of complete conservative route blocks, sampled uniformly with replacement',
        'route_blocks': len(groups), 'draws': draws if len(groups) >= 2 else 0, 'seed': seed,
        'fixed_macro_label_set': labels,
        'macro_zero_division': 'Zero when a fixed supported class has no truth or predictions in a bootstrap replicate',
        'warning': 'Few route blocks and rare classes can make these intervals unstable; selected corpus is not population representative.',
        'models': {name: {'point': dict(zip(METRICS, values.tolist())), 'ci95': intervals(samples[name])}
                   for name, values in points.items()},
        'paired_delta_vs_' + baseline: {
            name: {'point': dict(zip(METRICS, (values - points[baseline]).tolist())),
                   'ci95': intervals(samples[name] - samples[baseline])}
            for name, values in points.items() if name != baseline},
    }


def build_report(evidence, catalog, approved, reference, repeat_path, draws=2000, seed=20261109):
    frozen, reviewed = approved_review(evidence, catalog, approved)
    images, repeat, predictions, provenance = validate_inputs(evidence, reference, repeat_path, frozen)
    quality_path = evidence / 'intake/data-quality-addendum.json'
    quality = read(quality_path)
    require(quality['selection_sha256'] == read(evidence / 'intake/evaluation-blind.json')['selection_sha256'],
            'Data-quality addendum belongs to a different selection')
    decisions = {r['id']: r['decision'] for r in reviewed}
    classes = [c['id'] for c in frozen['classes']]
    index = {r['id']: i for i, r in enumerate(images)}
    sections = {}
    sources = sorted({r['source'] for r in images})
    for source in ['all'] + sources:
        rows = [r for r in images if source == 'all' or r['source'] == source]
        included = [r for r in rows if not decisions[r['id']].startswith('@')]
        excluded = Counter(decisions[r['id']][1:] for r in rows if decisions[r['id']].startswith('@'))
        section = {'reviewed': len(rows), 'included': len(included), 'excluded_by_reason': dict(excluded)}
        if included:
            ids = [r['id'] for r in included]
            position = {key: i for i, key in enumerate(ids)}
            groups = [[position[key] for key in block['members'] if key in position]
                      for block in repeat['conservative_route_blocks']]
            groups = [g for g in groups if g]
            truth = np.asarray([decisions[key] for key in ids])
            subset = {name: pred[[index[key] for key in ids]] for name, pred in predictions.items()}
            section['models'] = {name: point_metrics(truth, pred, classes) for name, pred in subset.items()}
            section['route_block_uncertainty'] = clustered_comparison(truth, subset, classes, groups, draws, seed)
        sections[source] = section
    return {
        'schema': 'youspeed-human-approved-field-scores-v1', 'created_at': datetime.now(timezone.utc).isoformat(),
        'status': 'correlated_crop_diagnostic_after_human_review',
        'metric_scope': 'Conditional classification of reviewed in-catalog stored crops; not end-to-end detection F1, population prevalence or validation of all136 classes',
        'approval_sha256': sha(approved), 'manifest_sha256': frozen['manifest_sha256'],
        'catalog_sha256': frozen['catalog_sha256'], 'class_index_sha256': sha(evidence / 'class-index.json'),
        'gpu_provenance_sha256': sha(reference / 'provenance-and-android-parity.json'),
        'gpu_predictions_sha256': provenance['predictions_sha256'], 'repeat_audit_sha256': sha(repeat_path),
        'data_quality_addendum_sha256': sha(quality_path),
        'script_sha256': sha(__file__), 'sections': sections,
        'repeat_audit': {'conservative_route_blocks': len(repeat['conservative_route_blocks']),
                         'candidate_physical_sign_components': repeat['candidate_physical_sign_component_count'],
                         'candidate_repeat_groups': [g['members'] for g in repeat['candidate_physical_sign_components'] if len(g['members']) > 1],
                         'physical_sign_independence_established': False},
        'limitations': [
            f"Historical route identity is unresolved for {quality['historical_non_uuid_source_records']} imported records; complete route separation from all original HF training data cannot be certified.",
            'Candidate physical-sign repeats are not human-adjudicated; no independent-sign F1 is claimed. Use accepted component representatives only after duplicate adjudication.',
            'Supported-class macro F1 averages only explicitly listed ground-truth-supported classes; unsupported classes remain unvalidated.',
            'Per-class recall and F1 are null without truth support; precision is null without predictions. Supported classes with no correct prediction have F1 zero.',
            'Micro F1 spans the full class catalog and equals single-label accuracy. Predictions outside the supported truth set still count as errors.',
            'All phone timestamps are device_unverified. Eligible current crops are detector/classifier-selected; missed detections are absent.',
            'Main Panoramax selection required uniquely resolved DE source tags. Generic/unresolved signs and the rare-class supplement are a separate cohort.',
            'Stored phone crops cannot reproduce the complete padded live camera ROI. These results use canonical224 sign-window crops.',
            'Local review status is an auditable explicit UI attestation, not a cryptographic proof of reviewer identity.',
        ],
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--evidence', type=Path, required=True)
    parser.add_argument('--catalog', type=Path, default=Path('shared/tsr/prolix-de-class-catalog-v1.json'))
    parser.add_argument('--approved', type=Path)
    parser.add_argument('--reference', type=Path, required=True)
    parser.add_argument('--repeat-audit', type=Path)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--bootstrap-draws', type=int, default=2000)
    parser.add_argument('--seed', type=int, default=20261109)
    args = parser.parse_args()
    report = build_report(args.evidence, args.catalog,
                          args.approved or args.evidence / 'intake/blind/review-approved.json',
                          args.reference, args.repeat_audit or args.evidence / 'intake/repeat-audit.json',
                          args.bootstrap_draws, args.seed)
    require(not args.output.exists(), 'Refusing to overwrite an existing score artifact')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2, allow_nan=False) + '\n')
    print(json.dumps({'status': report['status'], 'output': str(args.output)}))


if __name__ == '__main__':
    main()
