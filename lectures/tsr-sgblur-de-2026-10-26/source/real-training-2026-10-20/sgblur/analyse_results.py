#!/usr/bin/env python3
"""Read saved predictions only; no inference, training or checkpoint selection."""
from pathlib import Path
from collections import Counter, defaultdict
import csv
import hashlib
import json

BASE = Path(__file__).resolve().parent


def read(path):
    return json.loads(Path(path).read_text())


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def weighted(rows, field):
    groups = defaultdict(list)
    for row in rows:
        groups[row[field]].append(row)
    result = {'unit': field, 'units': len(groups), 'views': len(rows),
              'definition': 'Each grouping unit receives equal weight; within-unit score is mean of matched known target views. Group IDs are conservative candidates, not certified independence.',
              'groups': []}
    for group, values in sorted(groups.items()):
        result['groups'].append({'id': group, 'views': len(values),
                                 'baseline_recall': sum(x['baseline_matched'] for x in values)/len(values),
                                 'candidate_recall': sum(x['candidate_matched'] for x in values)/len(values)})
    result['baseline_macro_target_recall'] = sum(g['baseline_recall'] for g in result['groups'])/len(groups) if groups else None
    result['candidate_macro_target_recall'] = sum(g['candidate_recall'] for g in result['groups'])/len(groups) if groups else None
    return result


def summary(rows):
    return {'targets': len(rows), 'baseline_matched': sum(r['baseline_matched'] for r in rows),
            'candidate_matched': sum(r['candidate_matched'] for r in rows),
            'gained': sum(r['transition'] == 'gained' for r in rows),
            'lost': sum(r['transition'] == 'lost' for r in rows),
            'retained': sum(r['transition'] == 'retained' for r in rows),
            'still_missed': sum(r['transition'] == 'still_missed' for r in rows)}


def main():
    gt_file = BASE.parent/'review-test/reviewed-test.json'
    assert sha(gt_file) == '01f6701be9fcc86f089709a24901a91285386467413224a290c8f97e245fcddc'
    gt = read(gt_file)
    baseline = read(BASE/'test-01/baseline-target-recall.json')
    candidate = read(BASE/'test-01/candidate-target-recall.json')
    old_exclusions_path = BASE.parent/'review-test/tsr-label-exclusions-v3.json'
    excluded = {r['sample_id']: r for r in read(old_exclusions_path)['exclusions']}
    before = {r['sample_id']: r for r in baseline['predictions']}
    after = {r['sample_id']: r for r in candidate['predictions']}
    assert len(before) == len(after) == len(gt['rows']) == 47
    joint = []
    for r in gt['rows']:
        b, a = before[r['sample_id']], after[r['sample_id']]
        bm, am = b['matched'], a['matched']
        transition = 'retained' if bm and am else 'gained' if am else 'lost' if bm else 'still_missed'
        joint.append({'sample_id': r['sample_id'], 'picture_id': r['picture_id'],
                      'sequence_id': r['sequence_id'], 'site_candidate_id': r.get('site_id') or r['group_id'],
                      'conservative_group_id': r['group_id'], 'subset': r['subset'],
                      'frozen_subclass_label': r['label'], 'detector_target_class': 'sign', 'detector_class_id': 0,
                      'verified_subclass_label': 'known_sign_subclass_unresolved' if r['sample_id'] in excluded else r['label'],
                      'subclass_claim_withdrawn': r['sample_id'] in excluded,
                      'gt_bbox_xyxy': r['bbox_xyxy'], 'input_image_sha256': r['input_sha256'],
                      'gt_review_type': r['review_type'], 'human_reviewed': r['human_reviewed'],
                      'all_objects_complete': r['all_objects_complete'],
                      'baseline_matched': bm, 'candidate_matched': am,
                      'baseline_best_sign_iou': b['best_sign_iou'], 'candidate_best_sign_iou': a['best_sign_iou'],
                      'transition': transition, 'tsr_subclass_excluded_but_generic_sign_valid': r['sample_id'] in excluded})
    city = [r for r in joint if r['frozen_subclass_label'] in ['city:start', 'city:end']]
    old = [r for r in joint if r not in city]
    result = {'schema_version': 'sgblur-known-target-analysis-v1', 'no_additional_inference': True,
              'test_manifest_sha256': sha(gt_file),
              'classification_review_overlay': {'path': str(old_exclusions_path.resolve()),
                    'sha256': sha(old_exclusions_path), 'withdrawn_subclass_count': len(excluded),
                    'scope': 'Reporting metadata only; frozen generic sign boxes and saved predictions unchanged.'},
              'metric': 'one-to-one known-target recall at IoU0.5/conf0.25/NMS0.7, RGB letterbox1280',
              'overall': summary(joint), 'city_all': summary(city), 'old_sign_all': summary(old),
              'by_verified_subclass_label': {label: summary([r for r in joint if r['verified_subclass_label'] == label]) for label in sorted({r['verified_subclass_label'] for r in joint})},
              'city_by_native_or_projected': {s: summary([r for r in city if r['subset'] == s]) for s in sorted({r['subset'] for r in city})},
              'city_by_class_and_source_type': {label: {s: summary([r for r in city if r['frozen_subclass_label'] == label and r['subset'] == s]) for s in sorted({r['subset'] for r in city})} for label in ['city:start', 'city:end']},
              'city_site_balanced': weighted(city, 'site_candidate_id'),
              'city_conservative_group_balanced': weighted(city, 'conservative_group_id'),
              'city_class_site_balanced': {label: weighted([r for r in city if r['frozen_subclass_label'] == label], 'site_candidate_id') for label in ['city:start', 'city:end']},
              'city_class_group_balanced': {label: weighted([r for r in city if r['frozen_subclass_label'] == label], 'conservative_group_id') for label in ['city:start', 'city:end']},
              'tsr_subclass_exclusions_retained_for_detector': [{'sample_id': r['sample_id'], 'source_index': r['source_index'], 'generic_class': 'sign', 'reason': r['reason']} for r in excluded.values()],
              'all_non_sign_state_bitwise_unchanged': read(BASE/'test-01/frozen-state-proof.json')['all_non_sign_state_bitwise_unchanged'],
              'all_test_pre_nms_boxes_face_plate_logits_bitwise_unchanged': candidate['pre_nms_regression_and_face_plate_logits_bitwise_unchanged'],
              'post_nms_plate_face_changed_test_frames': len(candidate['post_nms_plate_face_changed_frames']),
              'limitations': ['Assistant-reviewed known targets, not human-approved exhaustive GT.',
                              'Raw frozen subclass names are preserved only for provenance. Five TSR-subclass claims are withdrawn and grouped as known_sign_subclass_unresolved; all remain valid generic sign targets.',
                              'Full-frame precision/AP and unmasked face/plate regression are not measurable.',
                              'No claim of universal non-regression or certified physical/journey independence.',
                              'Small purposively selected dataset; projected, native, own-native and grouping support reported separately.'],
              'samples': joint}
    for key, values in [('overall', joint), ('city_all', city), ('old_sign_all', old)]:
        expected = baseline['overall' if key == 'overall' else 'city_all' if key == 'city_all' else 'old_sign_targets']
        assert result[key]['baseline_matched'] == expected['matched']
    (BASE/'results-analysis.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    with (BASE/'known-target-comparison.csv').open('w', newline='', encoding='utf-8') as stream:
        fields = list(joint[0]); writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader()
        writer.writerows({**r, 'gt_bbox_xyxy': json.dumps(r['gt_bbox_xyxy'])} for r in joint)
    print(json.dumps({k: result[k] for k in ['overall', 'city_all', 'old_sign_all', 'city_by_class_and_source_type', 'city_site_balanced', 'city_conservative_group_balanced']}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
