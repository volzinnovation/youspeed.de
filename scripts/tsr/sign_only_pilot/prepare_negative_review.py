#!/usr/bin/env python3
"""Inspect classifier-rejected negative proposals plus a fixed teacher-empty sample."""
import hashlib
import json
import math
from pathlib import Path
from PIL import Image, ImageDraw

from prepare_teacher import render_review, sha256, write_json

JOB = Path('/job')
ROOT = JOB / 'balanced-v1'
OLD = JOB / 'expanded-v1'


def main():
    source = OLD / 'dataset/reviews/detector-expanded-2026-11-15/manifest.json'
    assert sha256(source) == '818457fffae759e6366fbc4946a40bf1386f51c0a5e326143904247a1488c71e'
    frames = json.loads(source.read_text())['frames']
    negatives = [f for f in frames if f['split'] == 'train' and f.get('pseudo_label_status') == 'pseudo_negative']
    assert len(negatives) == 2777
    rejected, empty, cases = [], [], []
    for frame in negatives:
        path = OLD / 'pseudo-labels' / (frame['picture_id'] + '.json')
        pseudo = json.loads(path.read_text())
        assert pseudo['status'] == 'pseudo_negative' and pseudo['image_sha256'] == frame['image_sha256']
        if pseudo['all_proposals']:
            rejected.append(frame)
            for i, proposal in enumerate(pseudo['all_proposals']):
                cases.append({'case_id': f'n{len(cases):04d}', 'picture_id': frame['picture_id'],
                              'proposal_index': i, 'box_xyxy': proposal['box'],
                              'prior_proposal': proposal, 'pseudo_record_sha256': sha256(path)})
        else:
            empty.append(frame)
    selected, groups = [], set()
    for frame in sorted(empty, key=lambda f: hashlib.sha256(('negative-review-v1:' + f['picture_id']).encode()).hexdigest()):
        if frame['group_id'] in groups:
            continue
        groups.add(frame['group_id']); selected.append(frame)
        if len(selected) == 16: break
    output = ROOT / 'negative-review'
    output.mkdir(parents=True, exist_ok=False)
    (output / 'crops').mkdir()
    selection = {'schema': 'streetshots-negative-review-selection-v1', 'parent_manifest_sha256': sha256(source),
        'parent_dataset_revision': '5e51cd9333ec07a88d212de479d1d2139f007495', 'negative_pool': 2777,
        'selection_rule': 'All137 negatives containing classifier-rejected proposals, plus16 fixed-hash teacher-empty frames, at most one per existing geographic group. Training split only.',
        'proposal_review_frames': rejected, 'teacher_empty_full_review_frames': selected,
        'claim': 'Targeted proposal review and small full-frame sample; not exhaustive certification of the2777 pseudo-negatives.',
        'script_sha256': sha256(Path(__file__))}
    write_json(output / 'selection.json', selection)
    by_id = {f['picture_id']: f for f in negatives}
    cells = []
    for row in cases:
        frame = by_id[row['picture_id']]
        path = OLD / 'dataset' / frame['image_path']
        assert sha256(path) == frame['image_sha256']
        with Image.open(path) as source_image:
            image = source_image.convert('RGB')
            assert image.size == (frame['width'], frame['height']) and source_image.getexif().get(274, 1) == 1
        x1, y1, x2, y2 = row['box_xyxy']
        pad = max(24, .25 * max(x2 - x1, y2 - y1))
        region = [max(0, math.floor(x1-pad)), max(0, math.floor(y1-pad)), min(image.width, math.ceil(x2+pad)), min(image.height, math.ceil(y2+pad))]
        crop = image.crop(region)
        row['context_xyxy'] = region
        crop.save(output / 'crops' / (row['case_id'] + '.png'))
        row['crop_sha256'] = sha256(output / 'crops' / (row['case_id'] + '.png'))
        scale = min(460 / crop.width, 280 / crop.height, 4)
        display = crop.resize((round(crop.width*scale), round(crop.height*scale)))
        draw = ImageDraw.Draw(display)
        draw.rectangle([(x1-region[0])*scale,(y1-region[1])*scale,(x2-region[0])*scale,(y2-region[1])*scale], outline='red', width=2)
        cell = Image.new('RGB', (480, 340), 'white')
        draw = ImageDraw.Draw(cell)
        draw.text((8, 5), row['case_id'] + ' ' + frame['picture_id'][:8], fill='black')
        draw.text((8, 22), f'{x2-x1:.1f}x{y2-y1:.1f} source pixels; display {scale:.2f}x', fill='black')
        cell.paste(display, (8, 52)); cells.append(cell)
    for offset in range(0, len(cells), 12):
        sheet = Image.new('RGB', (1440, 1360), '#ddd')
        for i, cell in enumerate(cells[offset:offset+12]): sheet.paste(cell, ((i%3)*480, (i//3)*340))
        sheet.save(output / f'proposals-{offset//12:02d}.jpg', quality=95)
    write_json(output / 'cases.json', cases)
    for frame in selected:
        path = OLD / 'dataset' / frame['image_path']
        assert sha256(path) == frame['image_sha256']
        with Image.open(path) as source_image: image = source_image.convert('RGB')
        record = {**frame, 'proposals': []}
        render_review(image, record, output / 'teacher-empty' / frame['picture_id'])
    write_json(output / 'complete.json', {'complete': True, 'proposal_cases': len(cases),
        'proposal_frames': len(rejected), 'teacher_empty_full_review_frames': len(selected),
        'selection_sha256': sha256(output / 'selection.json')})
    print((output / 'complete.json').read_text())


if __name__ == '__main__': main()
