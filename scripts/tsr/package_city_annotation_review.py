#!/usr/bin/env python3
"""Build an offline DE:310/311 review package separate from benchmark outputs."""

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import tempfile

from PIL import Image


CODES = {'DE:310', 'DE:311'}
TEMPLATE = Path(__file__).with_name('city_annotation_review.html')


def digest(path):
    checksum = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            checksum.update(block)
    return checksum.hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def checked_image(root, path, expected_sha):
    image = (root / path).resolve()
    if not image.is_relative_to(root) or digest(image) != expected_sha:
        raise ValueError(f'Invalid image path or digest: {path}')
    return image


def preview(image, path, size):
    thumbnail = image.convert('RGB')
    thumbnail.thumbnail(size, Image.Resampling.LANCZOS)
    thumbnail.save(path, quality=92, optimize=True)


def build_record(row, root, assets):
    record = {key: row.get(key) for key in (
        'id', 'source', 'class_code', 'source_url', 'picture_id', 'annotation_id',
        'provenance', 'exposure', 'author', 'license', 'source_references',
        'frame_sha256', 'crop_sha256', 'bbox_xyxy', 'bbox_source', 'split',
        'route_group', 'crossing_id', 'source_photo_url', 'crop_role',
    )}
    if not isinstance(row['id'], str) or not row['id'] or row['class_code'] not in CODES:
        raise ValueError('A review record requires an ID and a DE:310/311 proposal')
    record.update(frame_preview=None, crop_preview=None, frame_size=None, reviewed=False)
    box = row.get('bbox_xyxy')
    if row.get('frame_path') or row.get('frame_preview_path'):
        width, height = row['frame_size']
        if box is not None and (not isinstance(box, list) or len(box) != 4
                or any(type(v) not in (float, int) or not math.isfinite(v) for v in box)
                or not (0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height)):
            raise ValueError(f'Invalid registered source box: {row["id"]}')
        record['frame_size'] = [width, height]
    if row.get('frame_path'):
        path = checked_image(root, row['frame_path'], row['frame_sha256'])
        with Image.open(path) as frame:
            if frame.getexif().get(274, 1) != 1 or frame.size != (width, height):
                raise ValueError(f'Source raster mismatch: {row["id"]}')
            frame_preview = f'frame-{row["frame_sha256"]}.jpg'
            if not (assets / frame_preview).exists():
                preview(frame, assets / frame_preview, (1800, 1200))
            record['frame_preview'] = 'images/' + frame_preview
            if box is not None and not row.get('crop_path'):
                left, top, right, bottom = box
                crop = frame.crop((math.floor(left), math.floor(top), math.ceil(right), math.ceil(bottom)))
                name = hashlib.sha256(json.dumps([row['frame_sha256'], box]).encode()).hexdigest()
                path = assets / f'box-{name}.png'
                crop.convert('RGB').save(path)
                record.update(crop_preview='images/' + path.name, crop_sha256=digest(path))
    elif row.get('frame_preview_path'):
        path = checked_image(root, row['frame_preview_path'], row['frame_preview_sha256'])
        name = f'frame-{row["frame_preview_sha256"]}.jpg'
        if not (assets / name).exists():
            with Image.open(path) as frame:
                if (frame.getexif().get(274, 1) != 1
                        or abs(frame.width * height - frame.height * width) > max(width, height)):
                    raise ValueError(f'Frame preview is not aligned: {row["id"]}')
                preview(frame, assets / name, (1800, 1200))
        record['frame_preview'] = 'images/' + name
    elif box is not None:
        raise ValueError(f'Full-frame box requires its registered source raster: {row["id"]}')
    if row.get('crop_path'):
        path = checked_image(root, row['crop_path'], row['crop_sha256'])
        name = f'crop-{row["crop_sha256"]}.jpg'
        if not (assets / name).exists():
            with Image.open(path) as crop:
                preview(crop, assets / name, (720, 720))
        record['crop_preview'] = 'images/' + name
    if not (record['crop_preview'] or record['frame_preview']):
        raise ValueError(f'Missing verified review image: {row["id"]}')
    return record


def build(inputs, output):
    if output.exists():
        raise ValueError('Use a new output directory to preserve existing reviews')
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(dir=output.parent, prefix='.city-review-') as temporary:
        stage = Path(temporary) / 'review'
        assets = stage / 'images'
        assets.mkdir(parents=True)
        records = []
        input_digests = []
        for path in inputs:
            input_digests.append(digest(path))
            data = json.loads(path.read_text())
            records.extend(build_record(row, path.resolve().parent, assets) for row in data['records'])
        if not records or len({r['id'] for r in records}) != len(records):
            raise ValueError('Review IDs must be nonempty and unique')
        counts = Counter((r['source'], r['class_code'], r['bbox_xyxy'] is not None) for r in records)
        manifest = {
            'schema': 'youspeed-city-annotation-review-v1',
            'status': 'pending_human_review', 'human_approved': False,
            'annotation_completeness': 'partial', 'benchmark_predictions_included': False,
            'input_manifest_sha256': input_digests,
            'counts': [{'source': source, 'class_code': code, 'has_registered_box': box, 'count': count}
                       for (source, code, box), count in sorted(counts.items())],
            'records': records,
        }
        write_json(stage / 'manifest.json', manifest)
        page_data = {**manifest, 'manifest_sha256': digest(stage / 'manifest.json')}
        embedded = json.dumps(page_data, ensure_ascii=False, allow_nan=False).replace('<', '\\u003c')
        (stage / 'review.html').write_text(TEMPLATE.read_text().replace('__REVIEW_DATA__', embedded))
        stage.rename(output)
    return manifest['counts']


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.input, args.output), indent=2))
