#!/usr/bin/env python3
"""CUDA-only, known-box detector diagnostics on registered full-frame images.

Partial annotations support recall of known boxes, not precision, AP or F1.
The mobile arm mirrors Android's right-window/sign-channel/NMS contract; native
pixel rendering and Apple's embedded NMS remain separate parity checks.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import platform
import time

BASELINE_SHA = '698a70566938d25c3c1eaa49b89fc176fe2f3a20631a9a01fa56035613c7972a'
CLASS_NAMES = ['sign', 'plate', 'face']
SIZE = 1024
MODES = ('mobile_right', 'whole_letterbox')


def sha(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def write(path, value):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')


def prepare_image(image, mode='mobile_right', size=SIZE):
    """Return fixed square RGB raster and its exact mathematical source transform.

    Direct Pillow affine bilinear resampling approximates native Canvas/CoreImage;
    it is not claimed to be bit-exact native preprocessing.
    """
    from PIL import Image
    if mode not in MODES or size <= 0:
        raise ValueError('Unknown image transform or invalid size')
    if image.getexif().get(274, 1) != 1:
        raise ValueError('Boxes require an upright registered raster (EXIF1)')
    width, height = image.size
    if width <= 0 or height <= 0:
        raise ValueError('Empty image')
    scale = size / height if mode == 'mobile_right' else min(size / width, size / height)
    pad_x = size - width * scale if mode == 'mobile_right' else (size - width * scale) / 2
    pad_y = 0.0 if mode == 'mobile_right' else (size - height * scale) / 2
    inverse = (1 / scale, 0, -pad_x / scale, 0, 1 / scale, -pad_y / scale)
    result = image.convert('RGB').transform((size, size), Image.Transform.AFFINE, inverse,
        resample=Image.Resampling.BILINEAR, fillcolor=(114, 114, 114))
    transform = dict(mode=mode, size=size, source_width=width, source_height=height,
        scale=scale, offset_x=pad_x, offset_y=pad_y, source_exif_orientation=1,
        renderer='Pillow affine bilinear; native approximation', padding_rgb=[114, 114, 114])
    return result, transform


def size_bin(box):
    edge = min(box[2] - box[0], box[3] - box[1])
    return 'lt16' if edge < 16 else '16to31' if edge < 32 else '32to63' if edge < 64 else 'ge64'


def transform_boxes(boxes, transform):
    """Do not silently remove labels outside or cut by the mobile window."""
    result = []
    size, scale = transform['size'], transform['scale']
    width, height = transform['source_width'], transform['source_height']
    for index, source in enumerate(boxes):
        original = source['bbox_xyxy']
        if len(original) != 4 or not all(math.isfinite(float(v)) for v in original):
            raise ValueError('Invalid box coordinates')
        x1, y1, x2, y2 = map(float, original)
        if not (0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
            raise ValueError('Box does not fit registered source dimensions')
        box = [x1 * scale + transform['offset_x'], y1 * scale + transform['offset_y'],
               x2 * scale + transform['offset_x'], y2 * scale + transform['offset_y']]
        clipped = [max(0., min(size, box[0])), max(0., min(size, box[1])),
                   max(0., min(size, box[2])), max(0., min(size, box[3]))]
        area = (box[2] - box[0]) * (box[3] - box[1])
        visible = max(0., clipped[2] - clipped[0]) * max(0., clipped[3] - clipped[1])
        inside = box[0] >= -1e-8 and box[1] >= -1e-8 and box[2] <= size + 1e-8 and box[3] <= size + 1e-8
        result.append({**deepcopy(source), 'target_index': index, 'source_bbox_xyxy': list(original),
            'bbox_xyxy': box, 'clipped_bbox_xyxy': clipped, 'visible_fraction': visible / area,
            'window_status': 'inside' if inside else 'outside' if visible == 0 else 'clipped',
            'size_bin': size_bin(box), 'short_edge_pixels': min(box[2]-box[0], box[3]-box[1])})
    return result


def iou(a, b):
    intersection = max(0., min(a[2], b[2])-max(a[0], b[0])) * max(0., min(a[3], b[3])-max(a[1], b[1]))
    union = (a[2]-a[0])*(a[3]-a[1]) + (b[2]-b[0])*(b[3]-b[1]) - intersection
    return intersection / union if union > 0 else 0.


def raw_boxes(raw, size=SIZE):
    import numpy as np
    value = np.asarray(raw)
    if value.shape != (7, 21504):
        raise ValueError(f'Expected original three-class YOLO11n raw output, got {value.shape}')
    centers, dimensions = value[:2].T, value[2:4].T
    boxes = np.concatenate((centers-dimensions/2, centers+dimensions/2), axis=1).astype(np.float64)
    boxes = np.clip(boxes, 0., float(size))
    valid = np.isfinite(value[:5]).all(axis=0) & (dimensions > 0).all(axis=1)
    valid &= (boxes[:,2]>boxes[:,0]) & (boxes[:,3]>boxes[:,1])
    return boxes, value[4].astype(np.float64), valid


def decode_sign_predictions(raw, minimum_score=.25, nms_iou=.45, maximum_proposals=12):
    """Match Android: sign score independently of plate/face argmax, class-only NMS."""
    import numpy as np
    if not (0 <= minimum_score <= 1 and 0 <= nms_iou <= 1 and maximum_proposals > 0):
        raise ValueError('Invalid detector decoder configuration')
    boxes, scores, valid = raw_boxes(raw)
    indices = np.flatnonzero(valid & (scores >= minimum_score))
    # Stable tie order matches Android's sortedByDescending traversal.
    indices = indices[np.argsort(-scores[indices], kind='stable')]
    retained = []
    for index in indices:
        box = boxes[index].tolist()
        if all(iou(box, item['bbox_xyxy']) <= nms_iou for item in retained):
            retained.append({'bbox_xyxy': box, 'score': float(scores[index]), 'anchor_index': int(index)})
            if len(retained) == maximum_proposals:
                break
    return retained


def maximum_raw_geometry(raw, targets):
    """Separate score suppression from frozen-regression geometry limitations."""
    import numpy as np
    boxes, scores, valid = raw_boxes(raw)
    areas = (boxes[:,2]-boxes[:,0]) * (boxes[:,3]-boxes[:,1])
    result = []
    for target in targets:
        t = target['bbox_xyxy']
        overlap = np.maximum(0., np.minimum(boxes[:,2],t[2])-np.maximum(boxes[:,0],t[0])) * np.maximum(0.,np.minimum(boxes[:,3],t[3])-np.maximum(boxes[:,1],t[1]))
        union = areas+(t[2]-t[0])*(t[3]-t[1])-overlap
        values = np.divide(overlap, union, out=np.zeros_like(overlap), where=(union>0)&valid)
        best = int(np.argmax(values))
        compatible = valid & (values >= .5)
        best_score_index = int(np.argmax(np.where(compatible, scores, -np.inf))) if compatible.any() else None
        result.append({'target_index':target['target_index'], 'maximum_raw_box_iou':float(values[best]),
            'best_geometry_anchor_index':best, 'best_geometry_sign_score':float(scores[best]) if valid[best] else None,
            'best_geometry_bbox_xyxy':boxes[best].tolist(),
            'raw_anchors_at_iou_0_5':int(compatible.sum()),
            'maximum_sign_score_at_iou_0_5':float(scores[best_score_index]) if best_score_index is not None else None,
            'maximum_score_anchor_at_iou_0_5':best_score_index})
    return result


def match_known_boxes(targets, predictions, threshold=.5):
    available = {t['target_index']: t for t in targets if t['window_status']=='inside' and t.get('detector_class_id',0)==0}
    matched = []
    for prediction_index, prediction in enumerate(predictions):
        pairs = [(iou(t['bbox_xyxy'],prediction['bbox_xyxy']), index) for index,t in available.items()]
        if not pairs:
            break
        value, index = max(pairs, key=lambda pair: (pair[0],-pair[1]))
        if value >= threshold:
            matched.append(dict(target_index=index,prediction_index=prediction_index,iou=value))
            del available[index]
    return matched


def summarize(rows):
    counts = defaultdict(lambda: dict(known_boxes=0,inside=0,clipped=0,outside=0,matched=0,matched_confirmation_floor=0))
    for row in rows:
        hits = {m['target_index'] for m in row['matches']}
        confirmed = {m['target_index'] for m in row.get('matches_confirmation_floor',[])}
        for target in row['targets']:
            if target.get('detector_class_id',0)!=0:
                continue
            keys=['overall', 'class:'+target['class_id'], 'size:'+target['size_bin'],
                  'split:'+row['split'], 'provenance:'+target.get('bbox_source','unspecified')]
            keys.append('city' if target['class_id'] in ('city:start','city:end','DE:310','DE:311') else 'other_signs')
            for key in keys:
                entry=counts[key];entry['known_boxes']+=1;entry[target['window_status']]+=1
                entry['matched']+=int(target['target_index'] in hits)
                entry['matched_confirmation_floor']+=int(target['target_index'] in confirmed)
    for entry in counts.values():
        entry['known_box_recall_inside_window'] = entry['matched']/entry['inside'] if entry['inside'] else None
        entry['known_box_capture_and_recall'] = entry['matched']/entry['known_boxes'] if entry['known_boxes'] else None
        entry['known_box_recall_at_confirmation_floor'] = entry['matched_confirmation_floor']/entry['inside'] if entry['inside'] else None
    return {'frames':len(rows),'metrics':dict(sorted(counts.items())),
            'proposals':sum(len(r['predictions']) for r in rows),
            'unmatched_proposals_are_not_false_positives':True,
            'precision':None,'mAP':None,'F1':None}


def validate_manifest(manifest, images_root, splits=None):
    if manifest.get('schema') != 'youspeed-city-detector-frames-v1' or manifest.get('class_names') != CLASS_NAMES:
        raise ValueError('Expected full-frame detector manifest and exact sign/plate/face ontology')
    if manifest.get('image_verification_complete') is False:
        raise ValueError('Plan-only manifest: full-frame image verification is incomplete')
    if manifest.get('detector_checkpoint_sha256', BASELINE_SHA) != BASELINE_SHA:
        raise ValueError('Manifest detector checkpoint differs from pinned baseline')
    frames=manifest.get('frames',[])
    if not frames or len({f['image_id'] for f in frames}) != len(frames):
        raise ValueError('Empty or duplicate full-frame identities')
    groups=defaultdict(set)
    image_hash_splits=defaultdict(set)
    sequence_splits=defaultdict(set)
    root=Path(images_root).resolve()
    for frame in frames:
        if frame.get('exif_orientation') != 1 or not frame.get('route_group') or not frame.get('split'):
            raise ValueError('Registered upright raster, split and route group are required')
        groups[frame['route_group']].add(frame['split'])
        image_hash_splits[frame['image_sha256']].add(frame['split'])
        if frame.get('sequence_id'):
            sequence_splits[frame['sequence_id']].add(frame['split'])
        # Split integrity uses metadata only. Do not even open reserved pixels
        # during a training/development-only evaluation.
        if splits is not None and frame['split'] not in splits:
            continue
        path=(root/frame['image_path']).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError('Image path escapes root or is unavailable')
        if sha(path)!=frame['image_sha256']:
            raise ValueError('Image digest mismatch')
        from PIL import Image
        with Image.open(path) as image:
            if image.size != (frame['width'],frame['height']) or image.getexif().get(274,1)!=1:
                raise ValueError('Registered dimensions/orientation differ from image bytes')
            _, transform=prepare_image(image)
        if frame.get('annotation_complete') is not False:
            raise ValueError('This audit requires explicit partial annotation scope')
        if not frame.get('boxes'):
            raise ValueError('Partial annotation images without positive boxes are not verified negatives')
        if len({b['annotation_id'] for b in frame['boxes']})!=len(frame['boxes']):
            raise ValueError('Duplicate annotations in a frame')
        for box in frame['boxes']:
            if not isinstance(box.get('class_id'),str) or not box.get('bbox_source') or box.get('detector_class_id',0)!=0:
                raise ValueError('Expected semantic sign class and explicit box provenance')
        transform_boxes(frame['boxes'],transform)
    if any(len(v)!=1 for v in groups.values()):
        raise ValueError('A route group crosses splits')
    if any(len(v)!=1 for v in image_hash_splits.values()) or any(len(v)!=1 for v in sequence_splits.values()):
        raise ValueError('An image hash or sequence crosses splits')
    selected=[f for f in frames if splits is None or f['split'] in splits]
    if not selected:
        raise ValueError('No selected frames')
    return selected


def load_model(baseline, device, candidate=None):
    import torch
    from ultralytics import YOLO
    if sha(baseline)!=BASELINE_SHA:
        raise ValueError('Baseline checkpoint digest mismatch')
    model=YOLO(str(baseline)).model.float().to(device).eval()
    head=model.model[-1]
    if model.names!={0:'sign',1:'plate',2:'face'} or head.nc!=3 or head.nl!=3 or head.end2end:
        raise ValueError('Expected pinned three-class one-to-many detector')
    proof=None
    if candidate is not None:
        saved=torch.load(candidate,map_location='cpu',weights_only=True)
        if saved.get('format')!='sgblur-frozen-sign-output-v1' or saved.get('baseline_sha256')!=BASELINE_SHA:
            raise ValueError('Expected safe frozen-sign checkpoint format and baseline identity')
        before={k:v.detach().cpu().clone() for k,v in model.state_dict().items()}
        allowed=set()
        names={id(p):name for name,p in model.named_parameters()}
        for branch in head.cv3:
            assert list(branch[-1].weight.shape)==[3,64,1,1]
            allowed.update([names[id(branch[-1].weight)],names[id(branch[-1].bias)]])
        model.load_state_dict(saved['model_state'],strict=True)
        changed=0
        for name, after in model.state_dict().items():
            after=after.detach().cpu()
            if name in allowed:
                if not torch.equal(after[1:],before[name][1:]):raise ValueError('Candidate changes plate/face output rows')
                changed+=int((after[0]!=before[name][0]).sum())
            elif not torch.equal(after,before[name]):raise ValueError('Candidate changes frozen backbone/regression/BN state')
        proof=dict(all_non_sign_state_bitwise_unchanged=True,changed_sign_output_scalars=changed,allowed_sign_output_scalars=195)
    return model,proof


def run(args):
    import numpy as np
    import torch
    import ultralytics
    from PIL import Image
    if not args.device.startswith('cuda:') or not torch.cuda.is_available():
        raise ValueError('CUDA is required; no CPU benchmark fallback is permitted')
    if ultralytics.__version__!='8.4.56':
        raise ValueError('Use the pinned inspected Ultralytics8.4.56 runtime')
    torch.backends.cuda.matmul.allow_tf32=False
    torch.backends.cudnn.allow_tf32=False
    torch.backends.cudnn.benchmark=False
    torch.backends.cudnn.deterministic=True
    if args.output.exists():
        raise FileExistsError('Use a fresh evidence directory')
    manifest=json.loads(args.manifest.read_text())
    frames=validate_manifest(manifest,args.images_root,args.splits)
    if (args.candidate is None)!=(args.candidate_sha256 is None):
        raise ValueError('Candidate path and explicit digest must be supplied together')
    if args.candidate and sha(args.candidate)!=args.candidate_sha256:
        raise ValueError('Candidate checkpoint digest mismatch')
    args.output.mkdir(parents=True)
    report={'schema':'youspeed-city-detector-evaluation-v1','manifest_sha256':sha(args.manifest),
        'script_sha256':sha(Path(__file__)),'source_manifest_scope':manifest.get('scope'),
        'input_exclusions':manifest.get('exclusions'), 'selected_splits':args.splits,
        'unselected_split_pixels_read':False,
        'configuration':dict(imgsz=SIZE,sign_class_index=0,confidence=.25,confirmation_score_floor=.7,nms_iou=.45,max_proposals=12,match_iou=.5,
            coreml_nms_note='Apple export embeds NMS0.7; this runner mirrors Android0.45 and is not native parity.'),
        'environment':dict(torch=torch.__version__,ultralytics=ultralytics.__version__,numpy=np.__version__,
            device=args.device,gpu=torch.cuda.get_device_name(args.device),platform=platform.platform(),
            precision='float32',matmul_tf32=False,cudnn_tf32=False,cudnn_benchmark=False,cudnn_deterministic=True),
        'limitations':['Partial known-box recall only; unmatched proposals are not false positives.',
            'Current manual/source-box provenance is retained per target; no blanket human-reviewed accuracy claim.',
            'Pillow affine rendering approximates native input; independent native export parity is still required.',
            'Whole-image letterbox is diagnostic, not an authorized app geometry change.',
            'GPU forward timing excludes preprocessing, transfer, postprocessing and classification; not phone latency.'],
        'arms':{}}
    arms=[('baseline',args.model,None)]
    if args.candidate:arms.append((args.candidate_name,args.model,args.candidate))
    for name,baseline,candidate in arms:
        model,proof=load_model(baseline,args.device,candidate)
        with torch.inference_mode():
            warm=torch.zeros((1,3,SIZE,SIZE),device=args.device)
            for _ in range(args.warmups):model(warm)
            torch.cuda.synchronize()
            for mode in MODES:
                rows=[]
                for frame in frames:
                    path=args.images_root/frame['image_path']
                    with Image.open(path) as image:rendered,transform=prepare_image(image,mode)
                    pixels=np.asarray(rendered,dtype=np.uint8)
                    tensor=np.ascontiguousarray(pixels.transpose(2,0,1)).astype('<f4')/np.float32(255)
                    device_tensor=torch.from_numpy(tensor).unsqueeze(0).to(args.device)
                    started=torch.cuda.Event(enable_timing=True);ended=torch.cuda.Event(enable_timing=True)
                    started.record(); output=model(device_tensor);ended.record();ended.synchronize()
                    value=output[0] if isinstance(output,tuple) else output
                    if tuple(value.shape)!=(1,7,21504):raise ValueError('Detector raw shape changed')
                    raw=value[0].float().cpu().numpy()
                    if not np.isfinite(raw).all():raise ValueError('Detector produced nonfinite values')
                    targets=transform_boxes(frame['boxes'],transform)
                    predictions=decode_sign_predictions(raw)
                    geometry=maximum_raw_geometry(raw,[t for t in targets if t['window_status']=='inside'])
                    rows.append(dict(image_id=frame['image_id'],image_sha256=frame['image_sha256'],
                        route_group=frame['route_group'],split=frame['split'],sequence_id=frame.get('sequence_id'),
                        transform=transform,rgb_sha256=hashlib.sha256(pixels.tobytes()).hexdigest(),
                        tensor_nchw_float32_sha256=hashlib.sha256(tensor.tobytes()).hexdigest(),
                        raw_output_float32_sha256=hashlib.sha256(raw.astype('<f4').tobytes()).hexdigest(),
                        forward_cuda_ms=started.elapsed_time(ended),targets=targets,predictions=predictions,
                        matches=match_known_boxes(targets,predictions),raw_geometry=geometry,
                        matches_confirmation_floor=match_known_boxes(targets,[p for p in predictions if p['score']>=.7]),
                        proposal_score_counts={str(threshold):sum(p['score']>=threshold for p in predictions) for threshold in (.25,.7,.9,.95)}))
                summary=summarize(rows);timings=[r['forward_cuda_ms'] for r in rows]
                summary.update(gpu_forward_median_ms=float(np.median(timings)),gpu_forward_p95_ms=float(np.quantile(timings,.95)))
                filename=f'{name}-{mode}.json';write(args.output/filename,dict(rows=rows,summary=summary))
                report['arms'][f'{name}:{mode}']={'checkpoint_sha256':sha(candidate or baseline),
                    'frozen_state_proof':proof,'results_file':filename,'results_sha256':sha(args.output/filename),**summary}
                print(json.dumps({'arm':name,'mode':mode,**summary}),flush=True)
        del model
        torch.cuda.empty_cache()
    report['status']='complete';write(args.output/'summary.json',report)
    return report


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest',required=True,type=Path)
    parser.add_argument('--images-root',required=True,type=Path)
    parser.add_argument('--model',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    parser.add_argument('--device',default='cuda:0')
    parser.add_argument('--splits',nargs='+')
    parser.add_argument('--warmups',type=int,default=5)
    parser.add_argument('--candidate',type=Path)
    parser.add_argument('--candidate-sha256')
    parser.add_argument('--candidate-name',default='historical_sign_head')
    args=parser.parse_args()
    if args.warmups<1:parser.error('At least one warmup is required')
    if any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in args.candidate_name):
        parser.error('Unsafe candidate name')
    run(args)


if __name__=='__main__':main()
