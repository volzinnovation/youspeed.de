#!/usr/bin/env python3
"""Create blinded audit assets using only the independent Panoramax teacher."""
import hashlib
import json
from pathlib import Path
import time

from PIL import Image, ImageOps
from prepare_teacher import (TEACHER, checked_box, nms_groups, render_review,
                             review_groups, sha256, sign_index, write_json)

JOB = Path('/job')
ROOT = JOB / 'geographic-audit-v1'
PREFIX = 'reviews/detector-expanded-2026-11-15/geographic-audit-v1/protocol'


def main():
    import ultralytics
    import torch
    from ultralytics import YOLO
    assert ultralytics.__version__ == '8.4.213'
    selection = ROOT / 'protocol-publication' / PREFIX / 'selection.json'
    assert sha256(selection) == '2ac4f6f6afa4bc7179e47ec8f88edf8dad9fabae65cbe491a4ab44acf836b0ff'
    checkpoint = JOB / 'weights/yolo11l_panoramax.pt'
    assert sha256(checkpoint) == TEACHER['sha256']
    teacher = YOLO(str(checkpoint))
    channel = sign_index(teacher.names)
    output = ROOT / 'prepared'
    output.mkdir(exist_ok=False)
    (output / 'canonical').mkdir()
    records = []
    metadata = {'schema': 'streetshots-blind-audit-prepared-v1',
                'selection_sha256': sha256(selection), 'teacher_sha256': sha256(checkpoint),
                'script_sha256': sha256(Path(__file__)),
                'render_helper_sha256': sha256(Path(__file__).with_name('prepare_teacher.py')),
                'ultralytics': ultralytics.__version__, 'torch': torch.__version__,
                'student_models_loaded': [], 'source_annotations_loaded': False,
                'frames': records, 'complete': False}
    for frame in json.loads(selection.read_text())['frames']:
        uid = frame['picture_id']
        source = ROOT / 'originals' / (uid + '.jpg')
        assert sha256(source) == frame['image_sha256']
        with Image.open(source) as original:
            orientation = original.getexif().get(274)
            upright = ImageOps.exif_transpose(original).convert('RGB')
            image = Image.new('RGB', upright.size)
            image.paste(upright)
        path = output / 'canonical' / (uid + '.png')
        image.save(path, optimize=False)
        canonical = {'path': str(path), 'sha256': sha256(path),
                     'rgb_sha256': hashlib.sha256(image.tobytes()).hexdigest(),
                     'dimensions': list(image.size), 'original_exif_orientation': orientation,
                     'transform': 'EXIF transpose; RGB conversion; lossless PNG; no EXIF or ICC'}
        observations, timings = [], []
        for view, size, tile in [('full', 2048, False), ('native_tiles', 1536, True)]:
            start = time.monotonic()
            result = teacher.predict(image, imgsz=size, tile=tile, device=0, batch=1,
                                     conf=.1, iou=.5, classes=[channel], max_det=1000,
                                     quantize=16, rect=False, channels_last=False,
                                     verbose=False, save=False)[0]
            torch.cuda.synchronize()
            timings.append({'view': view, 'imgsz': size, 'tile': tile,
                            'seconds': time.monotonic() - start,
                            'proposals': len(result.boxes), 'max_det_reached': len(result.boxes) >= 1000})
            for index, (box, score) in enumerate(zip(result.boxes.xyxy.cpu().tolist(), result.boxes.conf.cpu().tolist())):
                observations.append({'observation_id': f'teacher:{view}:{index:04d}',
                                     'source': 'teacher', 'view_id': view, 'score': score,
                                     'box_xyxy': checked_box(box, image.size)})
        proposals = review_groups([], nms_groups(observations, .5), [], .5)
        record = {**frame, 'split': 'geographic_audit', 'canonical': canonical,
                  'proposals': proposals, 'observations': observations, 'timings': timings}
        record['review_assets'] = render_review(image, record, output / 'review' / uid)
        records.append(record)
        write_json(output / 'prepared.json', metadata)
        print(json.dumps({'completed': len(records), 'picture_id': uid, 'proposals': len(proposals)}), flush=True)
    metadata['complete'] = True
    write_json(output / 'prepared.json', metadata)


if __name__ == '__main__':
    main()
