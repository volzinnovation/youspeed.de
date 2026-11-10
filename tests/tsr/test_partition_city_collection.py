"""Regression checks for metadata-only collection planning and exposure collisions."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'scripts/tsr'))
from partition_city_collection import make_plan


GUARD = {'frames': [{'picture_id': 'prior-photo', 'sequence_id': 'prior-route',
                     'coordinates': [3, 49], 'rgb_sha256': '1'*64}]}


def frame(photo, route, longitude, code='DE:311', **fields):
    return {'picture_id': photo, 'sequence_id': route, 'coordinates': [longitude, 49],
            'expected_class': code, 'crossing_id': f'site-{photo}', **fields}


def by_picture(plan):
    return {photo: group for group in plan['components'] for photo in group['pictures']}


def test_crossing_pairs_and_complete_sequences_never_split():
    rows = [frame('entry', 'journey-a', 6, 'DE:310'), frame('exit', 'journey-b', 7),
            frame('further-site', 'journey-b', 8)]
    rows[0]['crossing_id'] = rows[1]['crossing_id'] = 'same-crossing-both-faces'
    plan = make_plan([{'frames': rows}], GUARD)
    assert len(plan['components']) == 1
    assert plan['components'][0]['sequences'] == ['journey-a', 'journey-b']


def test_sparse_pool_retains_test_dev_and_train_components():
    rows = [frame(str(i), f'route-{i}', 6+i/10, 'DE:310' if i == 0 else 'DE:311') for i in range(3)]
    plan = make_plan([{'frames': rows}], GUARD)
    assert {group['split'] for group in plan['components']} == {'test', 'dev', 'train'}
    assert sum(len(queue['target_slots']) for queue in plan['queues'].values()) == 3
    assert all(queue['registered_box_proposals'] == 0 for queue in plan['queues'].values())
    assert not plan['training_launch_ready']


def test_prior_route_and_its_transitive_neighborhood_are_blocked():
    rows = [frame('route-match', 'prior-route', 6), frame('near-route-match', 'new-route', 6.001),
            frame('farther-same-route', 'new-route', 7)]
    plan = make_plan([{'frames': rows}], GUARD)
    assert len(plan['components']) == 1
    assert plan['components'][0]['exclusion_reasons'] == ['historical_exposure_component']


def test_photo_shared_between_distinct_crossing_hypotheses_does_not_count_twice():
    rows = [frame('a', 'journey', 6), {**frame('a', 'journey', 6), 'crossing_id': 'other'}]
    plan = make_plan([{'frames': rows}], GUARD)
    assert plan['candidate_picture_count'] == 1
    assert all(queue['target_slots'] == [] for queue in plan['queues'].values())


def test_nearby_cross_source_anchors_share_one_face_slot():
    rows = [frame('a', 'route-a', 6, crossing_coordinates=[6, 49]),
            frame('b', 'route-b', 6.0001, crossing_coordinates=[6.0001, 49])]
    plan = make_plan([{'frames': rows}], GUARD)
    assert plan['map_anchor_aliases'] == {'site-b': 'site-a'}
    target, = plan['queues']['test']['target_slots']
    assert target['mapped_crossing_id'] == 'site-a'
    assert {view['picture_id'] for view in target['views']} == {'a', 'b'}


def test_reaudit_excludes_exact_duplicate_and_does_not_reassign_test_slots():
    rows = [frame(str(i), f'route-{i}', 6+i/10) for i in range(3)]
    initial = make_plan([{'frames': rows}], GUARD)
    old = by_picture(initial)
    pictures = [next(photo for photo in old if old[photo]['split'] == split) for split in ('test', 'train')]
    receipt = {'frames': [{'picture_id': picture, 'image_verification_complete': True, 'exif_orientation': 1,
                           'image_sha256': '2'*64, 'rgb_sha256': '3'*64, 'width': 1920, 'height': 1080}
                          for picture in pictures]}
    audit = make_plan([{'frames': rows}], GUARD, initial, receipt)
    assert audit['verified_receipt_pictures'] == 2
    for picture in pictures:
        group = by_picture(audit)[picture]
        assert group['split'] == 'excluded'
        assert 'cross_split_identity_or_route_merge' in group['exclusion_reasons']
    assert not audit['queues']['test']['target_slots']
    assert audit['queues']['dev']['target_slots'] == initial['queues']['dev']['target_slots']


def test_verified_rgb_identity_matches_prior_frame_even_with_new_encoded_bytes():
    rows = [frame('different-encoded-image', 'different-sequence', 6)]
    initial = make_plan([{'frames': rows}], GUARD)
    receipt = {'frames': [{'picture_id': 'different-encoded-image', 'image_verification_complete': True,
                           'exif_orientation': 1, 'image_sha256': 'f'*64, 'rgb_sha256': '1'*64,
                           'width': 1920, 'height': 1080}]}
    audit = make_plan([{'frames': rows}], GUARD, initial, receipt)
    assert audit['components'][0]['exclusion_reasons'] == ['historical_exposure_component']
    assert not audit['queues']['test']['target_slots']
