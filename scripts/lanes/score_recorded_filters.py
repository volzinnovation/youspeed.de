#!/usr/bin/env python3
"""Score detector polylines against frozen partial manual annotations.

This is a small, exploratory paint-coverage/negative-region audit, not an accuracy
benchmark. The scorer never selects configurations or treats unlabeled paint as
false positive. All inputs/outputs are private ignored experiment artifacts.
"""
from pathlib import Path
from collections import defaultdict
import argparse
import hashlib
import json
import cv2
import numpy as np
from compare_recorded_filters import score_response, paint_response, input_path


def poly(points, width, height):
    return np.array([[round(x * (width - 1)), round(y * (height - 1))]
                     for x, y in points], np.int32)


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--dataset', type=Path, required=True)
    p.add_argument('--input', type=Path, action='append', required=True)
    p.add_argument('--annotations', type=Path, action='append', required=True)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--variant', action='append', help='Optional variants to retain')
    p.add_argument('--tuning-source', default='fourth', help='Dataset source name designated as tuning before scoring')
    p.add_argument('--run', type=Path, help='Optional filter output directory; adds dense response and compatible-ridge diagnostics')
    p.add_argument('--overlays', type=Path, help='Optional new directory for annotated native-output comparisons')
    p.add_argument('--frame-id', action='append', default=[], help='Frame id to render; repeatable, defaults to annotated frames')
    a = p.parse_args()
    if a.output.exists():
        raise SystemExit('Choose a new output JSON; refusing to overwrite existing result')
    if a.overlays and a.overlays.exists():
        raise SystemExit('Choose a new overlays directory; refusing to overwrite existing result')
    data = json.loads(a.dataset.read_text())
    frames = {f['id']: f for f in data['frames']}
    indices = {f['id']: i for i, f in enumerate(data['frames'])}
    annotations = {}
    for path in a.annotations:
        for annotation in json.loads(path.read_text())['frames']:
            assert annotation['id'] not in annotations, 'Duplicate annotation id'
            annotations[annotation['id']] = annotation
    records = []
    render_rows = defaultdict(list)
    score_groups = defaultdict(list)
    all_groups = defaultdict(list)
    seen = set()
    for path in a.input:
        for line in path.read_text().splitlines():
            row = json.loads(line)
            variant = row.get('variant') or 'unnamed'
            if a.variant and variant not in a.variant:
                continue
            fid = row.get('sourceFrameId') or row['id'].split('::')[0]
            assert (variant, fid) not in seen, 'Duplicate frame+variant'
            seen.add((variant, fid))
            assert fid in frames, 'Unknown source frame'
            frame = frames[fid]
            split = 'tuning' if frame['source'] == a.tuning_source else 'heldout'
            all_groups[(variant, split)].append(row)
            render_rows[fid].append(row)
            if fid not in annotations:
                continue
            width, height = frame['width'], frame['height']
            masks = {cue: np.zeros((height, width), np.uint8) for cue in ('paint', 'edge')}
            legacy = row.get('legacy', {})
            if 'state' in legacy or any(legacy.get(side) for side in ('left','right')):
                masks['legacy'] = np.zeros((height, width), np.uint8)
            for boundary in row['road']['boundaries']:
                cue = boundary['cue'].lower()
                assert cue in masks, f'Unknown cue {cue}'
                # Disjoint supported groups must be separate polylines/segments.
                segments = boundary.get('segments', [boundary['points']])
                for segment in segments:
                    if len(segment) >= 2:
                        cv2.polylines(masks[cue], [poly(segment, width, height)], False, 255, 1)
            for side in ('left','right'):
                boundary = row.get('legacy',{}).get(side)
                if boundary:
                    cv2.polylines(masks['legacy'], [poly(boundary['points'], width, height)], False, 255, 1)
            scores = {cue: score_response(mask > 0, annotations[fid], 3)
                      for cue, mask in masks.items()}
            if a.run:
                stem = f'{indices[fid]:04d}'
                folder = a.run / variant
                raw_path = folder / (stem + '.gray')
                mask_path = folder / (stem + '-mask.png')
                if raw_path.exists() and mask_path.exists():
                    processed = np.frombuffer(raw_path.read_bytes(), np.uint8).reshape(height,width)
                    scores['compatibleRidge'] = score_response(paint_response(processed) >= 26, annotations[fid], 3)
                    scores['response'] = score_response(cv2.imread(str(mask_path),cv2.IMREAD_GRAYSCALE) > 0, annotations[fid], 3)
            record = dict(id=fid, source=frame['source'], split=split,
                          variant=variant, **scores)
            records.append(record)
            score_groups[(variant, split)].append(record)
    summary = []
    for (variant, split), rows in sorted(all_groups.items()):
        scores = score_groups[(variant, split)]
        stages = {}
        for cue in ('paint', 'edge', 'legacy', 'compatibleRidge', 'response'):
            values = [record[cue] for record in scores if cue in record]
            if not values:continue
            annotated = sum(v.get('annotatedPaintPixels', 0) for v in values)
            covered = sum(v.get('coveredPaintPixels', 0) for v in values)
            negative = sum(v.get('noPaintRoiPixels', 0) for v in values)
            false = sum(v.get('falseResponsePixelsInNoPaintRoi', 0) for v in values)
            stages[cue] = dict(annotatedPaintPixels=annotated, coveredPaintPixels=covered,
                               coverage=covered / annotated if annotated else None,
                               noPaintRoiPixels=negative, responsePixelsInNoPaintRoi=false,
                               densityInNoPaintRoi=false / negative if negative else None)
        summary.append(dict(variant=variant, split=split, frames=len(rows),
                            annotatedFrames=len(scores), stages=stages,
                            framesWithPaint=sum(any(b['cue'].lower() == 'paint' for b in r['road']['boundaries']) for r in rows),
                            paintPolylines=sum(sum(b['cue'].lower() == 'paint' for b in r['road']['boundaries']) for r in rows)))
    rendered=[]
    if a.overlays:
        a.overlays.mkdir(parents=True,exist_ok=False)
        for fid in a.frame_id or annotations.keys():
            if fid not in render_rows:continue
            frame=frames[fid];width,height=frame['width'],frame['height']
            rgb=cv2.imread(str(input_path(frame['rgbPath'],a.dataset))) if frame.get('rgbPath') else None
            if rgb is None:
                gray=np.frombuffer(input_path(frame['grayPath'],a.dataset).read_bytes(),np.uint8).reshape(height,width)
                rgb=cv2.cvtColor(gray,cv2.COLOR_GRAY2BGR)
            rgb=cv2.resize(rgb,(width,height),interpolation=cv2.INTER_AREA)
            def panel(label):
                image=cv2.copyMakeBorder(rgb.copy(),32,0,0,0,cv2.BORDER_CONSTANT,value=(25,25,25))
                cv2.putText(image,label,(5,21),cv2.FONT_HERSHEY_SIMPLEX,.40,(255,255,255),1,cv2.LINE_AA)
                return image
            original=panel(fid+' manual paint (magenta)')
            for boundary in annotations.get(fid,{}).get('boundaries',[]):
                if boundary.get('kind','paint')=='paint':cv2.polylines(original[32:],[poly(boundary['points'],width,height)],False,(255,0,255),1,cv2.LINE_AA)
            panels=[original]
            for row in render_rows[fid]:
                image=panel(row.get('variant') or 'unnamed')
                for boundary in row['road']['boundaries']:
                    color=(0,235,0) if boundary['cue'].lower()=='paint' else (0,150,255)
                    for segment in boundary.get('segments',[boundary['points']]):
                        cv2.polylines(image[32:],[poly(segment,width,height)],False,color,2,cv2.LINE_AA)
                panels.append(image)
            columns=min(4,len(panels))
            while len(panels)%columns:panels.append(np.zeros_like(original))
            sheet=np.vstack([np.hstack(panels[i:i+columns]) for i in range(0,len(panels),columns)])
            # Frame identifiers are manifest data, not filesystem paths.
            image_path=a.overlays/(hashlib.sha256(fid.encode()).hexdigest()[:16]+'.jpg')
            cv2.imwrite(str(image_path),sheet);rendered.append(dict(id=fid,path=str(image_path.resolve())))
    a.output.write_text(json.dumps(dict(
        scope='Exploratory partial-manual coverage within3px; negatives only in explicit noPaintROI; EDGE response is not false PAINT',
        inputs=[str(x.resolve()) for x in a.input], annotationFiles=[str(x.resolve()) for x in a.annotations],
        inputSha256={str(path):hashlib.sha256(path.read_bytes()).hexdigest() for path in [a.dataset,*a.input,*a.annotations]},
        scriptSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),tuningSource=a.tuning_source,
        summaries=summary, perFrame=records, overlays=rendered), indent=2) + '\n')
    print(json.dumps({'output': str(a.output.resolve()), 'summaries': summary}, indent=2))


if __name__ == '__main__':
    main()
