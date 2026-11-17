#!/usr/bin/env python3
"""Development-only replay of iPhone detector geometry; CUDA is not Core ML.

Preserves the published experiment. Does not train, read test images, or upload.
Pillow sampling and FP32 PyTorch are explicitly approximations of native rendering
and FP16 Core ML. Matching crop geometry alone is NOT native numerical parity.
"""
import argparse
import hashlib
import html
import json
from pathlib import Path

import train_evaluate as base

PHONE_THRESHOLD = .840783
D5_SHA = '65cdd44daad554d7de9512afa832bf71ad17cedf98a4c8d17aaaea2b268372d8'


def windows(width, height, dual=True):
    if width <= 0 or height <= 0:
        raise ValueError('Positive dimensions required')
    whole = (0, 0, width, height)
    if not dual or width <= height:
        return [whole]
    edges = [(0, 0, height, height), (width-height, 0, width, height)]
    return edges + [whole] if width > 2*height else edges


def source_box(box, window):
    x, y, right, bottom = window
    w, h = right-x, bottom-y
    scale = 1024/max(w, h)
    dx, dy = (1024-w*scale)/2, (1024-h*scale)/2
    result = [max(x, min(right, (box[0]-dx)/scale+x)),
              max(y, min(bottom, (box[1]-dy)/scale+y)),
              max(x, min(right, (box[2]-dx)/scale+x)),
              max(y, min(bottom, (box[3]-dy)/scale+y))]
    return result if result[2] > result[0] and result[3] > result[1] else None


def admit(passes, threshold):
    """iPhone caps each pass at 12, then merges WITHOUT a global cap."""
    candidates = []
    truncated = False
    for rows in passes:
        ranked = sorted((r for r in rows if r['score'] >= threshold), key=lambda r: -r['score'])
        truncated |= len(ranked) > 12
        candidates.extend(ranked[:12])
    kept = []
    for row in sorted(candidates, key=lambda r: -r['score']):
        if all(base.iou(row['box'], other['box']) <= .45 for other in kept):
            kept.append(row)
    return kept, truncated


def errors(truth, predictions):
    unused = set(range(len(truth)))
    fp, matched = [], []
    for pred in sorted(predictions, key=lambda r: -r['score']):
        best = max(unused, key=lambda j: (base.iou(truth[j], pred['box']), -j), default=None)
        if best is not None and base.iou(truth[best], pred['box']) >= .5:
            unused.remove(best)
            matched.append(best)
        else:
            fp.append(pred)
    return {'missed_truth_indices': sorted(unused), 'false_positives': fp, 'matched_truth_indices': matched}


def render(image, window):
    from PIL import Image
    x, y, r, b = window
    scale = 1024/max(r-x, b-y)
    dx, dy = (1024-(r-x)*scale)/2, (1024-(b-y)*scale)/2
    return image.crop(window).transform((1024, 1024), Image.Transform.AFFINE,
        (1/scale, 0, -dx/scale, 0, 1/scale, -dy/scale),
        Image.Resampling.BILINEAR, fillcolor=(114, 114, 114))


def visual(image, truth, predictions, destination):
    from PIL import ImageDraw
    result = errors(truth, predictions)
    canvas = image.copy()
    canvas.thumbnail((1600, 1200))
    s = canvas.width/image.width
    draw = ImageDraw.Draw(canvas)
    for i, box in enumerate(truth):
        color = 'yellow' if i in result['missed_truth_indices'] else 'lime'
        coords = [v*s for v in box]
        draw.rectangle(coords, outline=color, width=3)
        draw.text((coords[0], coords[1]), 'GT '+str(i), fill=color)
    for pred in result['false_positives']:
        coords = [v*s for v in pred['box']]
        draw.rectangle(coords, outline='red', width=2)
        draw.text((coords[0], coords[1]), 'FP %.3f'%pred['score'], fill='red')
    canvas.save(destination, quality=90)
    return result


def run(args):
    import torch
    import ultralytics
    from PIL import Image
    from ultralytics import YOLO
    if ultralytics.__version__ != '8.4.56':
        raise ValueError('Use pinned Ultralytics 8.4.56')
    if base.sha(args.manifest) != args.manifest_sha256:
        raise ValueError('Manifest hash mismatch')
    for path, expected in [(args.d4, base.D4_SHA), (args.d5, D5_SHA)]:
        if base.sha(path) != expected:
            raise ValueError('Checkpoint hash mismatch')
    manifest = json.loads(Path(args.manifest).read_text())
    frames = base.partition_manifest(manifest)['validation']
    root, output = Path(args.dataset_root).resolve(), Path(args.output)
    output.mkdir(parents=True, exist_ok=False)
    (output/'images').mkdir()
    summaries, audit, links = {}, [], []
    for name, checkpoint in [('d4', args.d4), ('d5', args.d5)]:
        if name == 'd4':
            reconstructed = base.sign_model('d4', args.coco, args.d4)
            checkpoint = output/'d4-runtime.pt'
            base.save_yolo(checkpoint, reconstructed, 0)
        model = YOLO(checkpoint)
        for mode in ['whole', 'phone_windows']:
            records, sweeps = [], []
            for frame in frames:
                path = base.checked_path(root, frame['image_path'], frame['image_sha256'])
                label = base.checked_path(root, frame['label_path'], frame['label_sha256'])
                with Image.open(path) as src:
                    image = src.convert('RGB')
                if image.size != (frame['width'], frame['height']):
                    raise ValueError('Registered raster dimensions differ')
                truth = base.read_yolo_labels(label, *image.size)
                passes = []
                for window in windows(*image.size, dual=mode=='phone_windows'):
                    result = model.predict(render(image, window), imgsz=1024, conf=.25,
                        iou=.45, max_det=300, rect=False, device=args.device,
                        half=False, verbose=False)[0]
                    rows = []
                    for box, score, cls in zip(result.boxes.xyxy.cpu().tolist(), result.boxes.conf.cpu().tolist(), result.boxes.cls.cpu().tolist()):
                        mapped = source_box(box, window)
                        if cls == 0 and mapped:
                            rows.append({'box': mapped, 'score': score})
                    passes.append(rows)
                predictions, truncated = admit(passes, PHONE_THRESHOLD)
                row = {'image_id': frame['image_id'], 'group_id': frame['group_id'],
                       'truth': truth, 'predictions': predictions,
                       'passes': passes, 'truncated': truncated,
                       'acceptable_extra_candidates': frame.get('acceptable_extra_candidates', [])}
                records.append(row)
                stem = name+'-'+mode+'-'+hashlib.sha256(frame['image_id'].encode()).hexdigest()[:16]
                findings = visual(image, truth, predictions, output/'images'/(stem+'.jpg'))
                audit.append({'model': name, 'mode': mode, 'image_id': frame['image_id'],
                              'adjudication': 'pending_visual_review', **findings})
                links.append('<h3>'+html.escape(name+' '+mode+' '+frame['image_id'])+'</h3><img loading="lazy" width="100%" src="images/'+stem+'.jpg">')
            key = name+'-'+mode
            base.write(output/(key+'-predictions.json'), records)
            for t in [v/100 for v in range(25, 100)]:
                rescored = [{**r, 'predictions': admit(r['passes'], t)[0]} for r in records]
                scored = base.score_frames(rescored, t)
                sweeps.append({k:v for k,v in scored.items() if k!='frames'})
            summaries[key] = {'phone_threshold': base.score_frames(records, PHONE_THRESHOLD),
                              'development_sweep': sweeps}
    base.write(output/'summary.json', {'split':'validation', 'images': len(frames),
        'native_parity_verified': False, 'renderer':'Pillow bilinear approximation',
        'runtime':'PyTorch FP32; not Core ML FP16', 'ultralytics':ultralytics.__version__,
        'torch':torch.__version__, 'threshold':PHONE_THRESHOLD,
        'script_sha256':base.sha(__file__), 'manifest_sha256':args.manifest_sha256,
        'results':summaries})
    base.write(output/'review-queue.json', audit)
    (output/'index.html').write_text('<!doctype html><meta charset="utf-8"><title>d4/d5 development replay</title><body style="max-width:1600px;margin:auto;font:18px sans-serif"><h1>d4/d5 development replay</h1><p>Yellow: missed reference; green: matched reference; red: unmatched proposal. Model-assisted reference labels; adjudication pending. Exact crop/merge rules, approximate raster sampling and PyTorch inference; native parity unverified. No new holdout evaluation.</p>'+''.join(links)+'</body>')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ['manifest', 'manifest-sha256', 'dataset-root', 'd4', 'd5', 'coco', 'output']:
        parser.add_argument('--'+name, required=True)
    parser.add_argument('--device', default='0')
    run(parser.parse_args())
