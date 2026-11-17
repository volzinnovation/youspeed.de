#!/usr/bin/env python3
"""Validate completed blinded decisions and freeze geographic reference labels."""
import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import shutil


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write(path, value):
    path.write_text(json.dumps(value, indent=2, allow_nan=False) + '\n')


def valid_box(box, width, height):
    assert len(box) == 4 and all(math.isfinite(x) for x in box)
    x1, y1, x2, y2 = box
    assert 0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height, box


def covered(rects, width, height):
    """Check the exact union of reviewed rectangular regions, including thin gaps."""
    for box in rects:
        valid_box(box, width, height)
    xs = sorted({0, width, *(x for r in rects for x in (r[0], r[2]))})
    for left, right in zip(xs, xs[1:]):
        spans = sorted((r[1], r[3]) for r in rects if r[0] <= left and r[2] >= right)
        end = 0
        for lo, hi in spans:
            if lo > end:
                return False
            end = max(end, hi)
        if end != height:
            return False
    return True


def validate_decisions(frame, decision):
    assert decision['picture_id'] == frame['picture_id']
    assert decision['student_predictions_seen'] is False
    assert decision['reviewer'] == 'assistant_model_assisted' and decision['note']
    proposals = {p['proposal_id']: p for p in frame['proposals']}
    rows = decision['proposal_decisions']
    assert len(rows) == len(proposals) and {d['proposal_id'] for d in rows} == set(proposals)
    boxes = []
    for row in rows:
        assert row['decision'] in ('accepted', 'corrected', 'rejected', 'unresolved') and row['reason']
        if row['decision'] == 'unresolved':
            assert not decision['admitted']
        if row['decision'] in ('accepted', 'corrected'):
            boxes.append(row.get('box_xyxy', proposals[row['proposal_id']]['box_xyxy']))
            if row['decision'] == 'corrected':
                assert 'box_xyxy' in row
    for row in decision['added_boxes']:
        assert row['reason']
        boxes.append(row['box_xyxy'])
    width, height = frame['canonical']['dimensions']
    for box in boxes:
        valid_box(box, width, height)
    assert len({tuple(b) for b in boxes}) == len(boxes)
    for row in decision['acceptable_extra_candidates']:
        assert row['kind'] == 'traffic_light'
        valid_box(row['box_xyxy'], width, height)
    if decision['admitted']:
        assert decision['annotation_complete'] is True
    return boxes


def main(root):
    selection = json.loads((root / 'selection.json').read_text())
    prepared_path = root / 'prepared/prepared.json'
    prepared = json.loads(prepared_path.read_text())
    assert prepared['complete'] and prepared['student_models_loaded'] == []
    assert prepared['source_annotations_loaded'] is False
    assert sha(root / 'selection.json') == prepared['selection_sha256']
    assert len(prepared['frames']) == selection['selected_images'] == 24
    assert len({f['picture_id'] for f in prepared['frames']}) == 24
    assert len(list((root / 'decisions').glob('*.json'))) == 24
    frames, excluded, validations = [], [], []
    for frame in prepared['frames']:
        uid = frame['picture_id']
        path = root / 'decisions' / (uid + '.json')
        decision = json.loads(path.read_text())
        boxes = validate_decisions(frame, decision)
        review_root = root / 'prepared/review' / uid
        review = json.loads((review_root / 'review.json').read_text())
        assets = decision['reviewed_assets']
        for name, digest in assets.items():
            assert '/' not in name and sha(review_root / name) == digest
        native = review['clean_native_tiles']
        required = {'clean.jpg', 'proposals.jpg',
                    *(Path(t['path']).name for t in native),
                    *(p.name for p in review_root.glob('crops-*.jpg'))}
        all_assets = required.issubset(assets)
        if decision['admitted']:
            assert all_assets, uid
        if all_assets:
            assert covered([t['source_region_xyxy'] for t in native], *frame['canonical']['dimensions'])
            for tile in native:
                assert assets[Path(tile['path']).name] == tile['sha256']
        image_path = Path('prepared/canonical') / (uid + '.png')
        assert sha(root / image_path) == frame['canonical']['sha256']
        validations.append({'image_id': uid, 'decision_sha256': sha(path),
                            'all_review_assets_verified': all_assets,
                            'reviewed_assets': len(assets), 'admitted': decision['admitted']})
        if not decision['admitted']:
            excluded.append({'image_id': uid, 'group_id': frame['group_id'],
                             'reason': decision['note'], 'annotation_complete': False})
            continue
        frames.append({'image_id': uid, 'group_id': frame['group_id'],
                       'image_path': image_path.as_posix(), 'image_sha256': frame['canonical']['sha256'],
                       'original_hf_path': frame['image_path'], 'original_sha256': frame['image_sha256'],
                       'rgb_sha256': frame['canonical']['rgb_sha256'],
                       'dimensions': frame['canonical']['dimensions'], 'boxes_xyxy': boxes,
                       'acceptable_extra_candidates': decision['acceptable_extra_candidates'],
                       'annotation_complete': True, 'admitted': True,
                       'decision_path': 'decisions/' + uid + '.json', 'decision_sha256': sha(path)})
    assert len({f['group_id'] for f in frames}) == len(frames)
    out = root / 'references'
    out.mkdir(exist_ok=False)
    manifest = {'schema': 'streetshots-blind-audit-references-v1', 'complete': True,
                'student_predictions_seen': False, 'human_certified': False,
                'annotation_method': 'Assistant visual review of clean overview, every native tile, teacher overlays and all proposal crops; missed signs added; unresolved frames excluded.',
                'protocol_dataset_revision': '4281ed055df1cd25873bfa0cbc974721cbc018e7',
                'selection_sha256': sha(root / 'selection.json'), 'prepared_sha256': sha(prepared_path),
                'assembler_sha256': sha(Path(__file__)), 'frames': frames, 'excluded': excluded,
                'counts': {'selected': 24, 'admitted': len(frames), 'excluded': len(excluded),
                           'positive_images': sum(bool(f['boxes_xyxy']) for f in frames),
                           'reference_boxes': sum(len(f['boxes_xyxy']) for f in frames)},
                'limitations': ['Small assistant-reviewed reference set, not human-certified.',
                                'Excluding unresolved blurry frames biases evaluation toward interpretable scenes.',
                                'Detector-export sampling is not a random sample of roads.',
                                'Known sequence/500m separation does not prove unknown upstream pretraining was disjoint.']}
    write(out / 'manifest.json', manifest)
    write(out / 'validation.json', validations)
    shutil.copytree(root / 'decisions', out / 'decisions')
    print(json.dumps({'manifest_sha256': sha(out / 'manifest.json'), 'counts': manifest['counts']}))


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    main(parser.parse_args().root)
