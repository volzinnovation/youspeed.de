import copy
import importlib.util
from pathlib import Path

import pytest


PATH = Path(__file__).resolve().parents[2] / 'scripts/tsr/sign_only_pilot/assemble_reviews.py'
spec = importlib.util.spec_from_file_location('pilot_reviews', PATH)
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def evidence():
    frame = {'picture_id': 'image', 'original': {'sha256': 'original'},
             'canonical': {'sha256': 'canonical'}, 'dimensions': [100, 100],
             'proposals': [{'proposal_id': 'p1', 'box_xyxy': [10, 10, 20, 20]}],
             'existing_truth_boxes': [{'box_xyxy': [10, 10, 20, 20]}],
             'review_pack': {'clean': 'clean.jpg', 'overlay': 'proposals.jpg',
                             'contact_sheets': ['crops-001.jpg'],
                             'clean_native_tiles': [{'path': 'clean-native-000.jpg'}]}}
    names = ['clean.jpg', 'proposals.jpg', 'crops-001.jpg', 'clean-native-000.jpg']
    review = {'picture_id': 'image', 'reviewer_role': 'model_assisted_assistant',
              'selection_sha256': 'selection', 'original_sha256': 'original',
              'canonical_sha256': 'canonical', 'prepared_sha256': 'snapshot',
              'policy_sha256': 'policy', 'accepted_proposal_ids': ['p1'],
              'rejected_proposal_ids': [], 'rejection_reasons': {}, 'corrected_boxes': [],
              'additional_boxes': [], 'uncertain_regions': [],
              'existing_truth_decisions': [{'index': 0, 'decision': 'reuse', 'reason': 'Viewed'}],
              'annotation_complete': {'sign': True}, 'frame_disposition': 'include',
              'reviewed_assets': [{'path': n, 'sha256': 'a' * 64} for n in names]}
    return review, frame, 'selection', {'snapshot': {'image': copy.deepcopy(frame)}}, {
        'image/' + name: 'a' * 64 for name in names}, 'policy'


def test_historical_truth_not_double_appended():
    boxes = module.validate_review(*evidence())
    assert len(boxes) == 1
    assert module.yolo_text(boxes, [100, 100]) == '0 0.1500000000 0.1500000000 0.1000000000 0.1000000000\n'


def test_partial_snapshot_must_match_final_frame():
    args = evidence()
    args[1]['proposals'][0]['box_xyxy'][0] = 9
    with pytest.raises(ValueError, match='prepared evidence changed'):
        module.validate_review(*args)


def test_missing_native_tile_cannot_claim_completeness():
    args = evidence()
    args[0]['reviewed_assets'].pop()
    with pytest.raises(ValueError, match='must be reviewed'):
        module.validate_review(*args)


def test_wrong_asset_hash_rejected():
    args = evidence()
    args[0]['reviewed_assets'][0]['sha256'] = 'b' * 64
    with pytest.raises(ValueError, match='hash mismatch'):
        module.validate_review(*args)


def test_uncertainty_requires_exclusion():
    args = evidence()
    args[0]['uncertain_regions'] = [{'box_xyxy': [40, 40, 50, 50], 'reason': 'Unresolved'}]
    with pytest.raises(ValueError, match='unresolved uncertainty'):
        module.validate_review(*args)
    args[0]['annotation_complete']['sign'] = False
    args[0]['frame_disposition'] = 'exclude_pending_adjudication'
    assert len(module.validate_review(*args)) == 1


def test_duplicate_decisions_rejected():
    args = evidence()
    args[0]['corrected_boxes'] = [{'proposal_id': 'p1', 'box_xyxy': [10, 10, 21, 21]}]
    with pytest.raises(ValueError, match='exactly one decision'):
        module.validate_review(*args)


def test_negative_scene_requires_rejection_of_proposal():
    args = evidence()
    args[0]['accepted_proposal_ids'] = []
    args[0]['rejected_proposal_ids'] = ['p1']
    args[0]['rejection_reasons'] = {'p1': 'Supplementary panel excluded by scope'}
    args[0]['existing_truth_decisions'][0]['decision'] = 'reject'
    assert module.validate_review(*args) == []
    assert module.yolo_text([], [100, 100]) == ''


@pytest.mark.parametrize('value', [[0, 0, float('nan'), 1], [0, 0, 101, 1], [0, 0, 0, 1]])
def test_invalid_boxes_rejected(value):
    with pytest.raises(ValueError):
        module.box(value, [100, 100])
