#!/usr/bin/env python3
"""Prepare 20 source-annotation proposals for full-frame review, without approval."""
import collections
import hashlib
import json
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

OUT = Path(__file__).resolve().parent
LECTURE = OUT.parents[2]
SOURCE = LECTURE / '.build/student-collection-2026-10-19/collection'


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def split(group):
    value = int.from_bytes(hashlib.sha256(('20261026\0' + group).encode()).digest()[:8], 'big') / (1 << 64)
    return 'train' if value < .70 else 'val' if value < .85 else 'test'


def main():
    source = json.loads((SOURCE / 'manifest.json').read_text())
    items = {r['picture_id']: r for r in source['items']}
    candidates = [c for c in source['crops'] if c.get('suggested_label') in ['city:start', 'city:end']]
    chosen, used = [], set()
    for phase, city in [('train', 'city:start'), ('train', 'city:end'), ('val', 'city:start'), ('val', 'city:end')]:
        pool = [c for c in candidates if split(c['group_id']) == phase and c['suggested_label'] == city]
        def size(c):
            x1, y1, x2, y2 = c['bbox_xyxy']
            i = items[c['picture_id']]
            return min(x2-x1, y2-y1) * 1280 / max(i['width'], i['height'])
        pool.sort(key=lambda c: (-size(c), c['sample_id']))
        selected, groups = [], collections.Counter()
        for cap in [1, 2, 5]:
            for c in pool:
                if len(selected) == 5:
                    break
                if c['picture_id'] not in used and groups[c['group_id']] < cap:
                    selected.append(c)
                    used.add(c['picture_id'])
                    groups[c['group_id']] += 1
        if len(selected) != 5:
            raise ValueError(f'Not enough distinct frames for {phase}/{city}')
        chosen.extend(selected)
    review_dir = OUT / 'review'
    review_dir.mkdir(parents=True, exist_ok=True)
    frames, previews = [], []
    font_path = '/System/Library/Fonts/Supplemental/Arial.ttf'
    def font(size):
        return ImageFont.truetype(font_path, size) if Path(font_path).exists() else ImageFont.load_default()
    for number, target in enumerate(chosen, 1):
        item = items[target['picture_id']]
        path = SOURCE / item['bundle_path'] / 'image.png'
        assert sha(path) == item['image_sha256']
        boxes = []
        for annotation in item['annotations']:
            crop = next(c for c in source['crops'] if c['annotation_id'] == annotation['annotation_id'])
            boxes.append({'source_annotation_id': annotation['annotation_id'],
                          'class_id': {'sign': 0, 'plate': 1, 'face': 2}[annotation['detector_class']],
                          'bbox_xyxy': annotation['bbox_xyxy'],
                          'city_label_proposal': crop.get('suggested_label'),
                          'city_label_verified': False, 'box_source': 'unchanged_source_annotation'})
        frame = {'review_number': number, 'picture_id': item['picture_id'],
                 'sequence_id': item['sequence_id'], 'group_id': item['group_id'],
                 'split': split(item['group_id']), 'image_path': str(path.resolve()),
                 'image_sha256': item['image_sha256'], 'width': item['width'], 'height': item['height'],
                 'source_url': item['source_url'], 'asset_url': item['asset_url'],
                 'license': item['license'], 'author': item['author'],
                 'target_annotation_id': target['annotation_id'], 'target_city_label_proposal': target['suggested_label'],
                 'boxes': boxes, 'review_status': 'pending', 'reviewer': '',
                 'complete_all_visible_classes': False, 'source_is_public_blurred_derivative': True,
                 'review_note': '', 'preview_path': f'review/frame-{number:02d}.jpg'}
        frames.append(frame)
        with Image.open(path) as original:
            image = original.convert('RGB')
        image.thumbnail((1600, 1200))
        scale = image.width / item['width']
        draw = ImageDraw.Draw(image)
        for k, box in enumerate(boxes, 1):
            xy = [round(v * scale) for v in box['bbox_xyxy']]
            colour = '#ff3030' if box['source_annotation_id'] == target['annotation_id'] else '#1cff5c'
            draw.rectangle(xy, outline=colour, width=3)
            draw.text((xy[0], max(0, xy[1]-24)), f'{k}: sign', fill=colour, font=font(22), stroke_width=1, stroke_fill='black')
        canvas = Image.new('RGB', (1600, 1280), '#eeeeee')
        canvas.paste(image, ((1600-image.width)//2, 55))
        d = ImageDraw.Draw(canvas)
        d.text((15, 8), f'{number:02d} {frame["split"]} {target["suggested_label"]} {item["picture_id"]}', fill='black', font=font(24))
        d.text((15, 1242), 'Quellboxen: UNGEPRUEFT. Alle sign / plate / face pruefen; fehlende Boxen ergaenzen.', fill='black', font=font(23))
        canvas.save(OUT / frame['preview_path'], quality=92)
        previews.append(canvas)
    doc = {'schema_version': 'sgblur-fullframe-review-v1',
           'source_manifest': str((SOURCE / 'manifest.json').resolve()), 'source_manifest_sha256': sha(SOURCE / 'manifest.json'),
           'seed': '20261026', 'class_names': ['sign', 'plate', 'face'],
           'selection': 'Five largest source-city-sign proposals per train/val and city label, round-robin sequence diversity. No seed or original split change.',
           'public_masking_limit': 'Public images may already mask faces/plates. Evaluation cannot establish performance on unmasked originals.',
           'frames': frames}
    (OUT / 'review-candidates.json').write_text(json.dumps(doc, ensure_ascii=False, indent=2)+'\n')
    for start in range(0, len(previews), 4):
        sheet = Image.new('RGB', (1600, 1280), 'white')
        for k, im in enumerate(previews[start:start+4]):
            cell = im.resize((800, 640), Image.Resampling.LANCZOS)
            sheet.paste(cell, ((k % 2)*800, (k // 2)*640))
        sheet.save(review_dir / f'contact-{start//4+1:02d}.jpg', quality=92)
    print(json.dumps({'frames': len(frames), 'splits': dict(collections.Counter(f['split'] for f in frames)),
                      'class_proposals': dict(collections.Counter(f['target_city_label_proposal'] for f in frames)),
                      'groups': len({f['group_id'] for f in frames}),
                      'existing_boxes': sum(len(f['boxes']) for f in frames), 'output': str(OUT)}, ensure_ascii=False))


if __name__ == '__main__':
    main()
