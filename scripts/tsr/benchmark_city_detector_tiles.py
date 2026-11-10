#!/usr/bin/env python3
"""CUDA-only exploratory tile benchmark; no training, export or app changes.

Reference rectangles may be partial and awaiting review. This measures known-box
recall and proposal workload, never precision, AP or F1. The original evaluator
is SHA-pinned and remains unmodified for reproducibility of the first experiment.
"""
from __future__ import annotations

import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import platform
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
import evaluate_city_detector as base

HELPER_SHA = 'af69b5c37914915a6acc7826fe9550361adb46f777713227b658aa1871e795fd'
STRATEGIES = ('mobile_right', 'whole_letterbox', 'full_height_2', 'full_height_3', 'square_grid_6')
MINIMUM_OVERLAP = .20
CONFIDENCE = .25
CONFIRMATION = .7
NMS_IOU = .45
MAX_PROPOSALS = 12


def axis_starts(length, side, count):
    if side >= length:
        return [(length-side)/2]
    if count < 2:
        raise ValueError('Multiple windows are required to cover the source axis')
    return [(length-side)*i/(count-1) for i in range(count)]


def square_transform(width, height, left, top, side, tile_index):
    scale = base.SIZE / side
    return {'mode':'square_tile', 'size':base.SIZE, 'source_width':width, 'source_height':height,
            'scale':scale, 'offset_x':-left*scale, 'offset_y':-top*scale,
            'source_exif_orientation':1, 'renderer':'Pillow affine bilinear; native approximation',
            'padding_rgb':[114,114,114], 'tile_index':tile_index,
            'source_window_xyxy':[left,top,left+side,top+side]}


def tile_transforms(width, height, strategy):
    """Frozen geometry, independent of annotations and detector predictions."""
    if width <= 0 or height <= 0 or strategy not in STRATEGIES:
        raise ValueError('Invalid image dimensions or strategy')
    if strategy in ('mobile_right','whole_letterbox'):
        scale = base.SIZE/height if strategy=='mobile_right' else min(base.SIZE/width,base.SIZE/height)
        x = base.SIZE-width*scale if strategy=='mobile_right' else (base.SIZE-width*scale)/2
        y = 0. if strategy=='mobile_right' else (base.SIZE-height*scale)/2
        return [{'mode':strategy,'size':base.SIZE,'source_width':width,'source_height':height,
                 'scale':scale,'offset_x':x,'offset_y':y,'source_exif_orientation':1,
                 'renderer':'Pillow affine bilinear; native approximation','padding_rgb':[114,114,114],
                 'tile_index':0,'source_window_xyxy':[-x/scale,-y/scale,(base.SIZE-x)/scale,(base.SIZE-y)/scale]}]
    if strategy.startswith('full_height_'):
        count = int(strategy[-1])
        # Portrait rasters already fit one full-height window. Repeating identical
        # inputs adds no coverage; preserve the current right-aligned input once.
        starts = [width-height] if width<=height else axis_starts(width,height,count)
        return [square_transform(width,height,x,0.,height,i) for i,x in enumerate(starts)]
    columns,rows = (3,2) if width>=height else (2,3)
    side = max(width/(columns-(columns-1)*MINIMUM_OVERLAP),
               height/(rows-(rows-1)*MINIMUM_OVERLAP))
    positions = [(x,y) for y in axis_starts(height,side,rows) for x in axis_starts(width,side,columns)]
    return [square_transform(width,height,x,y,side,i) for i,(x,y) in enumerate(positions)]


def render(image, transform):
    from PIL import Image
    s = transform['scale']
    inverse = (1/s,0,-transform['offset_x']/s,0,1/s,-transform['offset_y']/s)
    return image.transform((base.SIZE,base.SIZE),Image.Transform.AFFINE,inverse,
                           resample=Image.Resampling.BILINEAR,fillcolor=(114,114,114))


def source_predictions(predictions, transform):
    width,height = transform['source_width'],transform['source_height']
    result=[]
    for prediction in predictions:
        b=prediction['bbox_xyxy'];s=transform['scale'];x=transform['offset_x'];y=transform['offset_y']
        native=[max(0.,min(width,(b[0]-x)/s)),max(0.,min(height,(b[1]-y)/s)),
                max(0.,min(width,(b[2]-x)/s)),max(0.,min(height,(b[3]-y)/s))]
        if native[2]>native[0] and native[3]>native[1]:
            result.append({**prediction,'bbox_xyxy':native,'tile_index':transform['tile_index'],
                           'tile_bbox_xyxy':list(b)})
    return result


def merge_predictions(predictions, maximum=MAX_PROPOSALS):
    """Stable score-ordered source-coordinate NMS; measure cap pressure separately."""
    ranked=sorted(predictions,key=lambda p:-p['score'])
    deduplicated=[]
    for prediction in ranked:
        if all(base.iou(prediction['bbox_xyxy'],other['bbox_xyxy'])<=NMS_IOU for other in deduplicated):
            deduplicated.append(prediction)
    return deduplicated[:maximum], {'source_proposals_before_merge':len(predictions),
        'duplicates_suppressed':len(predictions)-len(deduplicated),
        'deduplicated_before_global_cap':len(deduplicated),
        'global_cap_dropped':max(0,len(deduplicated)-maximum)}


def union_area(rectangles):
    if not rectangles:return 0.
    edges=sorted({x for r in rectangles for x in (r[0],r[2])})
    area=0.
    for left,right in zip(edges,edges[1:]):
        intervals=sorted((r[1],r[3]) for r in rectangles if r[0]<right and r[2]>left)
        if not intervals:continue
        low,high=intervals[0];length=0.
        for a,b in intervals[1:]:
            if a>high:length+=high-low;low,high=a,b
            else:high=max(high,b)
        area+=(right-left)*(length+high-low)
    return area


def coverage_targets(boxes, transforms):
    result=[]
    for index,source in enumerate(boxes):
        transformed=[base.transform_boxes([source],t)[0] for t in transforms]
        fully_visible=[i for i,t in enumerate(transformed) if t['window_status']=='inside']
        visible=[i for i,t in enumerate(transformed) if t['visible_fraction']>0]
        original=source['bbox_xyxy'];rectangles=[]
        for t in transforms:
            w=t['source_window_xyxy']
            clip=[max(original[0],w[0]),max(original[1],w[1]),min(original[2],w[2]),min(original[3],w[3])]
            if clip[2]>clip[0] and clip[3]>clip[1]:rectangles.append(clip)
        area=(original[2]-original[0])*(original[3]-original[1])
        edge=max(t['short_edge_pixels'] for t in transformed)
        result.append({**source,'target_index':index,'bbox_xyxy':list(original),
            'window_status':'inside' if fully_visible else 'clipped' if visible else 'outside',
            'fully_visible_tile_indices':fully_visible,'visible_tile_indices':visible,
            'union_visible_fraction':min(1.,union_area(rectangles)/area),
            'short_edge_pixels':edge,'size_bin':base.size_bin([0,0,edge,edge])})
    return result


def validate_manifest(manifest, images_root, splits):
    from PIL import Image
    if manifest.get('schema')!='youspeed-city-detector-frames-v1' or manifest.get('class_names')!=base.CLASS_NAMES:
        raise ValueError('Expected registered full-image manifest with exact sign/plate/face ontology')
    if manifest.get('image_verification_complete') is not True:
        raise ValueError('Materialized image verification must be complete')
    if manifest.get('detector_checkpoint_sha256')!=base.BASELINE_SHA:
        raise ValueError('Manifest baseline checkpoint differs')
    root=images_root.resolve();selected=[];identities=set()
    for frame in manifest['frames']:
        if frame['split'] not in splits:continue
        if frame['image_id'] in identities:raise ValueError('Duplicate selected image identity')
        identities.add(frame['image_id'])
        if frame.get('exif_orientation')!=1 or frame.get('annotation_complete') is not False:
            raise ValueError('Only upright registered images with explicit partial/unlabelled scope are supported')
        path=(root/frame['image_path']).resolve()
        if not path.is_relative_to(root) or base.sha(path)!=frame['image_sha256']:
            raise ValueError('Source path or digest mismatch')
        with Image.open(path) as image:
            if image.size!=(frame['width'],frame['height']) or image.getexif().get(274,1)!=1:
                raise ValueError('Source raster geometry differs')
        boxes=frame.get('boxes',[])
        if len({b['annotation_id'] for b in boxes})!=len(boxes):raise ValueError('Duplicate reference rectangles')
        for box in boxes:
            if not isinstance(box.get('class_id'),str) or box.get('detector_class_id',0)!=0 or not box.get('bbox_source'):
                raise ValueError('Reference rectangles require semantic sign class and explicit provenance')
        base.transform_boxes(boxes,tile_transforms(frame['width'],frame['height'],'whole_letterbox')[0])
        selected.append(frame)
    if not selected:raise ValueError('No selected diagnostic images')
    return selected


def summarize(rows):
    import numpy as np
    summary=base.summarize(rows)
    summary.update(total_tiles=sum(len(r['tiles']) for r in rows),
        mean_tiles_per_frame=float(np.mean([len(r['tiles']) for r in rows])),
        input_megapixels_per_frame=float(np.mean([len(r['tiles'])*base.SIZE**2/1e6 for r in rows])),
        gpu_forward_frame_median_ms=float(np.median([r['gpu_forward_frame_median_ms'] for r in rows])),
        gpu_forward_frame_p95_ms=float(np.quantile([r['gpu_forward_frame_median_ms'] for r in rows],.95)),
        render_transfer_forward_decode_merge_wall_median_ms=float(np.median([r['processing_wall_ms'] for r in rows])),
        proposals_above_070=sum(sum(p['score']>=CONFIRMATION for p in r['predictions']) for r in rows),
        tile_proposals_before_merge=sum(r['tile_proposals_before_merge'] for r in rows),
        deduplicated_before_global_cap=sum(r['merge']['deduplicated_before_global_cap'] for r in rows),
        global_cap_dropped=sum(r['merge']['global_cap_dropped'] for r in rows),
        frames_at_global_cap=sum(len(r['predictions'])==MAX_PROPOSALS for r in rows))
    left_targets=left_inside=left_hits25=left_hits70=0
    for row in rows:
        hits25={m['target_index'] for m in row['matches']};hits70={m['target_index'] for m in row['matches_confirmation_floor']}
        for target in row['targets']:
            if target['outside_current_mobile_window']:
                left_targets+=1;left_inside+=target['window_status']=='inside'
                left_hits25+=target['target_index'] in hits25;left_hits70+=target['target_index'] in hits70
    summary['targets_outside_current_mobile_window']={'known':left_targets,'fully_inside_any_tile':left_inside,
        'matched_025':left_hits25,'matched_070':left_hits70}
    return summary


def run(args):
    import numpy as np
    import torch
    import ultralytics
    from PIL import Image
    if base.sha(base.__file__)!=HELPER_SHA:raise ValueError('Original evaluator helper changed')
    if base.sha(args.manifest)!=args.manifest_sha256:raise ValueError('Frozen manifest digest mismatch')
    if args.output.exists():raise ValueError('Use a fresh benchmark evidence directory')
    if not args.device.startswith('cuda:') or not torch.cuda.is_available():raise ValueError('CUDA required; no CPU fallback')
    if ultralytics.__version__!='8.4.56':raise ValueError('Pinned Ultralytics8.4.56 required')
    torch.set_num_threads(4);torch.set_num_interop_threads(2)
    torch.backends.cuda.matmul.allow_tf32=False;torch.backends.cudnn.allow_tf32=False
    torch.backends.cudnn.benchmark=False;torch.backends.cudnn.deterministic=True
    manifest=json.loads(args.manifest.read_text());frames=validate_manifest(manifest,args.images_root,args.splits)
    args.output.mkdir(parents=True)
    config={'schema':'youspeed-city-detector-tile-benchmark-v1','script_sha256':base.sha(__file__),
        'helper_sha256':HELPER_SHA,'manifest_sha256':args.manifest_sha256,'checkpoint_sha256':base.BASELINE_SHA,
        'strategies':list(STRATEGIES),'imgsz':base.SIZE,'minimum_grid_overlap':MINIMUM_OVERLAP,
        'per_tile_score':CONFIDENCE,'confirmation_floor':CONFIRMATION,'tile_and_global_nms_iou':NMS_IOU,
        'per_tile_max_proposals':MAX_PROPOSALS,'global_max_proposals':MAX_PROPOSALS,
        'selected_splits':args.splits,'scope_note':args.scope_note,'warmups':args.warmups,'gpu_repeats':args.repeats,
        'frames':len(frames),'device':args.device,'gpu':torch.cuda.get_device_name(args.device),
        'torch':str(torch.__version__),'ultralytics':ultralytics.__version__,'numpy':np.__version__,
        'platform':platform.platform(),'float32':True,'tf32':False,'training':False,'native_deployment':False,
        'timing_scope':{'gpu':'Median across repeated serial tile forward sums per frame; excludes transfers, rendering, decoding, classifier and image I/O.',
                        'wall':'Single diagnostic pass: rendering, tensor creation, transfer, model forward, output transfer, decoding and global NMS. Excludes source image I/O, hashes, GT scoring, repeat profiling and classifier.'},
        'limitations':['Partial/provisional known-box recall only; no precision, AP or F1.',
            'Proposals are classifier-workload counts, not measured classifier latency or false positives.',
            'Pillow input approximates native rendering; this is not a CoreML/LiteRT or phone benchmark.',
            'Previously predicted v1 images are exploratory and remain quarantined for qualification.',
            'Each global proposal is limited to one tile prediction; no box stitching or learned fusion.',
            'All arms use source-image clipping and global NMS, including single-input arms; padded-edge proposals may differ from the older tile-space evaluator.',
            'Full-height windows can leave gaps on extreme aspect ratios wider than their tile count; coverage is measured rather than assumed.',
            'Full-height windows collapse to one input on portrait frames; grid6 is the small-sign magnification arm.']}
    # Persist the complete fixed strategy and cost contract before any predictions.
    base.write(args.output/'configuration.json',config)
    model,_=base.load_model(args.model,args.device)
    def forward(tensor):
        start=torch.cuda.Event(enable_timing=True);end=torch.cuda.Event(enable_timing=True)
        start.record();output=model(tensor);end.record();end.synchronize()
        value=output[0] if isinstance(output,tuple) else output
        if tuple(value.shape)!=(1,7,21504):raise ValueError('Detector output ontology/shape changed')
        return value,float(start.elapsed_time(end))
    results={strategy:[] for strategy in STRATEGIES}
    with torch.inference_mode():
        warm=torch.zeros((1,3,base.SIZE,base.SIZE),device=args.device)
        for _ in range(args.warmups):model(warm)
        torch.cuda.synchronize()
        for frame_number,frame in enumerate(frames):
            with Image.open(args.images_root/frame['image_path']) as source:image=source.convert('RGB')
            current=coverage_targets(frame.get('boxes',[]),tile_transforms(*image.size,'mobile_right'))
            for strategy in STRATEGIES:
                transforms=tile_transforms(*image.size,strategy);prepared=[];predictions=[];tile_proposals=0
                started=time.perf_counter()
                for transform in transforms:
                    pixels=np.asarray(render(image,transform),dtype=np.uint8)
                    array=np.ascontiguousarray(pixels.transpose(2,0,1)).astype('<f4')/np.float32(255)
                    tensor=torch.from_numpy(array).unsqueeze(0).to(args.device)
                    output,elapsed=forward(tensor);raw=output[0].float().cpu().numpy()
                    if not np.isfinite(raw).all():raise ValueError('Nonfinite detector output')
                    decoded=base.decode_sign_predictions(raw,CONFIDENCE,NMS_IOU,MAX_PROPOSALS)
                    tile_proposals+=len(decoded);predictions.extend(source_predictions(decoded,transform))
                    prepared.append((transform,pixels,array,tensor,raw,elapsed,len(decoded)))
                predictions,merge=merge_predictions(predictions)
                wall_ms=(time.perf_counter()-started)*1000
                timing_sums=[sum(item[5] for item in prepared)]
                for _ in range(args.repeats-1):
                    timing_sums.append(sum(forward(item[3])[1] for item in prepared))
                targets=coverage_targets(frame.get('boxes',[]),transforms)
                for target,reference in zip(targets,current):
                    target['outside_current_mobile_window']=reference['window_status']=='outside'
                tiles=[{'transform':t,'rgb_sha256':hashlib.sha256(p.tobytes()).hexdigest(),
                    'tensor_nchw_float32_sha256':hashlib.sha256(a.tobytes()).hexdigest(),
                    'raw_output_float32_sha256':hashlib.sha256(raw.astype('<f4').tobytes()).hexdigest(),
                    'single_pass_forward_ms':ms,'proposals':n}
                    for t,p,a,_,raw,ms,n in prepared]
                row={'image_id':frame['image_id'],'image_sha256':frame['image_sha256'],
                    'width':frame['width'],'height':frame['height'],'split':frame['split'],
                    'source':frame.get('source',manifest.get('source','panoramax_existing')),
                    'reference_status':frame.get('reference_status','source_history_manual_geometry_no_independent_qa'),
                    'route_group':frame.get('route_group'),'strategy':strategy,'tiles':tiles,'targets':targets,
                    'predictions':predictions,'tile_proposals_before_merge':tile_proposals,'merge':merge,
                    'matches':base.match_known_boxes(targets,predictions),
                    'matches_confirmation_floor':base.match_known_boxes(targets,[p for p in predictions if p['score']>=CONFIRMATION]),
                    'gpu_forward_frame_repeats_ms':timing_sums,'gpu_forward_frame_median_ms':float(np.median(timing_sums)),
                    'processing_wall_ms':wall_ms}
                results[strategy].append(row)
                del prepared
            print(json.dumps({'processed_frames':frame_number+1,'total_frames':len(frames),'image_id':frame['image_id']}),flush=True)
    report={**config,'status':'complete','strategies':{}}
    for strategy,rows in results.items():
        groups=defaultdict(list)
        for row in rows:groups[(row['source'],row['reference_status'])].append(row)
        summary=summarize(rows)
        summary['by_source_and_reference_status']=[{'source':s,'reference_status':r,**summarize(v)} for (s,r),v in sorted(groups.items())]
        filename=strategy+'.json';base.write(args.output/filename,{'rows':rows,'summary':summary})
        report['strategies'][strategy]={**summary,'results_file':filename,'results_sha256':base.sha(args.output/filename)}
    base.write(args.output/'summary.json',report)
    print(json.dumps({'status':'complete','output':str(args.output)}),flush=True)
    return report


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest',type=Path,required=True);p.add_argument('--manifest-sha256',required=True)
    p.add_argument('--images-root',type=Path,required=True);p.add_argument('--model',type=Path,required=True)
    p.add_argument('--output',type=Path,required=True);p.add_argument('--device',default='cuda:0')
    p.add_argument('--splits',nargs='+',default=['train','val','test'])
    p.add_argument('--warmups',type=int,default=10);p.add_argument('--repeats',type=int,default=5)
    p.add_argument('--scope-note',required=True)
    args=p.parse_args()
    if args.warmups<1 or args.repeats<3:p.error('Use at least one warmup and three timing repeats')
    run(args)


if __name__=='__main__':main()
